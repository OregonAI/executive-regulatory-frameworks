#!/usr/bin/env python3
"""Fetch the `source_url`s this corpus publishes that nothing else checks (#435).

  python3 src/check_source_urls.py              # weekly job: network, bounded
  python3 src/check_source_urls.py --check      # PR gate, OFFLINE: coverage arithmetic + wiring
  python3 src/check_source_urls.py --selftest   # PR gate, OFFLINE (loopback server only)
  python3 src/check_source_urls.py --dry-run    # print this week's plan, fetch nothing

WHY THIS EXISTS. The weekly lychee scan no longer reads verbatim documents (their body links
are copies of third-party text, and a dead URL in a faithful copy is accurate). What IS ours
in those documents is their frontmatter `source_url` -- the link we tell a reader to cite.
Something has to keep checking those.

WHAT ALREADY CHECKS SOME OF THEM, MEASURED 2026-10-06 (`--check` prints the live figures):
44,638 distinct `source_url`s across 81,997 documents. 8,052 of them are in
`_meta/sources/*.yml` (8,181 manifest URLs in all), which the drift job fetches and hashes -- statutes (ORS chapter pages),
the Constitution, policy listings. 36,586 are NOT: 36,008 are per-rule OAR pages
(`secure.sos.state.or.us/oard/view.action?ruleNumber=...`, one per rule document), 526 are
executive-order PDFs on oregon.gov, 52 are DEQ records. Those are this script's population.
The same claim -- "drift checks every document's source_url" -- was the false comment that
federal-reference's own `src/check_source_urls.py` was written to retire; this is its
counterpart here.

BOUNDED, NOT TRUNCATED. 36k fetches of one state host every Monday is neither polite nor
necessary, and it would not finish inside a job limit. So:

  * every host with at most SMALL_HOST distinct URLs is checked IN FULL every run;
  * a bulk host (the OAR pages) is checked in a deterministic ROTATING WINDOW of
    ~`--max-urls` per run: a URL's slot is `int(sha1(url), 16) % CYCLE_WEEKS` and the run
    visits slot `week % CYCLE_WEEKS`, so every URL is visited exactly once per CYCLE_WEEKS
    weeks and a URL's slot depends on the URL alone -- adding or removing documents never moves
    another URL and never skips a slot. `--check` fails when the largest slot plus the
    small hosts outgrows `--max-urls`: that is the signal to raise CYCLE_WEEKS;
  * the run prints its window ("window 7 of 15") and the cycle length, so "checked this
    week" is never confused with "checked";
  * a wall-clock `--deadline-minutes` stops fetching and lists what it did NOT reach as
    NOT CHECKED -- a run that ran out of time says so, it does not report the rest as fine.

STATUS MEANINGS. 2xx/3xx-followed: ok, EXCEPT a final URL on a SOFT_404 host that is that
host's "no such record" page (OARD answers an unknown rule number with a 302 to a search page
that returns 200): FAIL. A redirect that cannot be followed (loop, no Location): FAIL.
404/410 FAIL at once; 5xx/DNS/TLS/refused/reset/timeout FAIL only after RETRY_WAITS retries with backoff (exit 1). 429 from a host not in
KNOWN_BLOCKED is "throttled -- could not check", and a URL the deadline did not reach is "not
checked": both are listed AND the job exits 2 (red, distinct from a real failure), because a
skipped check is not a green one; 403 is a FAIL, because a 403 cannot be told from a withdrawn page and this
repository never reports could-not-check as is-fine. KNOWN_BLOCKED is the federal-reference
mechanism: a host that refuses our runners with a recorded status is reported unverifiable,
and only while it keeps answering that exact status.

Network-dependent, so it runs in the weekly `check-links` workflow, never as a per-PR gate.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import http.server
import math
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
UA = ("OregonAI-corpus-bot/0.1 (+https://github.com/OregonAI/executive-regulatory-frameworks; "
      "civic corpus link check)")

SMALL_HOST = 1000      # a host with at most this many distinct URLs is checked in full each run
DEFAULT_MAX_URLS = 2500  # per-run budget: small hosts first, the bulk-host window gets the rest
CYCLE_WEEKS = 34       # the bulk host is split into this many hash slots; one slot per weekly run
TIMEOUT = 30
PAUSE = 0.25           # seconds each worker waits after a request
WORKERS = 4
DEADLINE_MINUTES = 40

# TRANSIENT FAULTS (#437). secure.sos.state.or.us refuses some connections when a GitHub runner
# sends it a burst ([Errno 111] Connection refused, 72 of 2,313 URLs on 2026-10-07); every one of
# 20 re-fetched from elsewhere was fine. A refused/reset connection, a timeout or a 5xx is retried
# with growing waits (3 attempts in all) before the URL is called dead. A REFUSAL or RESET (only
# those) also puts the HOST on a shared cool-down, so every worker pauses instead of keeping the
# burst going; a timeout or 5xx only makes the retrying worker sleep before its own retry.
# 404/410/403/429, a soft-404, a redirect loop are answers, not faults: never retried.
RETRY_WAITS = (2, 6)   # seconds before attempt 2 and attempt 3
# BUDGET. Measured 2026-10-07 (run 37571625562): 2,313 URLs took ~39.5 min on 4 workers, i.e.
# 4.1 s per URL per worker slot, pause included -- already the whole 40-minute deadline, so any
# retry on top of that window turns URLs into not-checked. `--check` therefore requires
#   largest_run * SECONDS_PER_URL / workers + RETRY_ALLOWANCE_S <= deadline.
# RETRY_ALLOWANCE_S: the host-wide cool-down stops ALL workers, so its waits are serial wall clock,
# not divided by workers: the 72 refusals seen, each costing 2 + 6 s, is 72 x 8 = 576 s (an upper
# bound: overlapping cool-downs merge, they do not add). WORST CASE, stated: every sleep is bounded by the deadline check before each
# URL, so a host that refuses everything cannot run past the deadline by more than the URL in
# flight, 3 attempts x TIMEOUT + 8 s of waits = 98 s (41.6 min of a 75-minute job); the rest of the
# window is then reported not-checked (red), never ok.
SECONDS_PER_URL = 4.1
EXPECTED_REFUSALS = 72   # refusals seen in run 37571625562
RETRY_ALLOWANCE_S = EXPECTED_REFUSALS * sum(RETRY_WAITS)

# host -> {"status", "since", "evidence"}. Empty today: nothing is recorded as refusing our
# runners. An entry is a fact about OUR ACCESS, never about upstream; see the module docstring.
KNOWN_BLOCKED: dict[str, dict] = {}

# host -> substring of the FINAL url (after redirects) that means "no such record" although the
# status is 200. secure.sos.state.or.us/oard answers an unknown or repealed ruleNumber with a 302
# to ruleSearchResults.action;JSESSIONID=... (200); a real rule lands on viewSingleRule.action.
SOFT_404 = {"secure.sos.state.or.us": "ruleSearchResults.action"}

FM = re.compile(r"\A---\r?\n(.*?)\r?\n---", re.S)
SRC = re.compile(r"^source_url:[ \t]*(.*?)[ \t]*$", re.M)


def _source_url(text: str) -> str | None:
    m = FM.match(text)
    if not m:
        return None
    mm = SRC.search(m.group(1))
    if not mm:
        return None
    v = mm.group(1).strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        v = v[1:-1]
    return v or None


def document_urls(root: Path = ROOT) -> dict[str, list[str]]:
    """{source_url: [document paths]} over every markdown document, hidden dirs and
    `_meta/` (templates, snapshots) excluded -- they are not published documents."""
    urls: dict[str, list[str]] = defaultdict(list)
    for dirpath, dirs, files in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (rel_dir == "." and d == "_meta"))
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            p = Path(dirpath, f)
            u = _source_url(p.read_text(encoding="utf-8", errors="replace"))
            if u:
                urls[u].append(p.relative_to(root).as_posix())
    return urls


def manifest_urls(root: Path = ROOT) -> set[str]:
    out = set()
    for f in sorted((root / "_meta" / "sources").glob("*.yml")):
        for s in (yaml.safe_load(f.read_text()) or {}).get("sources", []) or []:
            if s.get("url"):
                out.add(s["url"])
    return out


def _h(u: str) -> str:
    return hashlib.sha1(u.encode()).hexdigest()


def plan(urls, week: int, max_urls: int = DEFAULT_MAX_URLS, cycle: int = CYCLE_WEEKS):
    """Return (this_run, info). `urls` is the population (already deduped, not manifest)."""
    by_host: dict[str, list[str]] = defaultdict(list)
    for u in set(urls):
        by_host[urllib.parse.urlsplit(u).hostname or ""].append(u)
    full = sorted(u for h, us in by_host.items() if len(us) <= SMALL_HOST for u in us)
    bulk = sorted(u for h, us in by_host.items() if len(us) > SMALL_HOST for u in us)
    slots: dict[int, list[str]] = defaultdict(list)
    for u in bulk:
        slots[int(_h(u), 16) % cycle].append(u)
    k = week % cycle
    chunk = slots.get(k, [])
    largest = max((len(v) for v in slots.values()), default=0)
    return full + chunk, {"full": len(full), "bulk": len(bulk), "cycle": cycle, "k": k,
                          "largest": largest, "budget": max_urls,
                          "this_run": len(full) + len(chunk)}


def classify(status: int, host: str) -> str:
    """ok | blocked | throttled | fail  (blocked only for a host whose RECORDED status this is)."""
    known = KNOWN_BLOCKED.get(host)
    if known and status == known["status"]:
        return "blocked"
    if status == 429:
        return "throttled"
    return "ok" if status < 400 else "fail"


RETRIED: dict[str, int] = {}       # url -> retries it needed (reported by main)
_COOLDOWN: dict[str, float] = {}   # host -> monotonic time before which nobody sends to it
_LOCK = threading.Lock()


def _note_transient(host: str, wait: float) -> None:
    with _LOCK:
        _COOLDOWN[host] = max(_COOLDOWN.get(host, 0.0), time.monotonic() + wait)


def _wait_cooldown(host: str) -> None:
    with _LOCK:
        until = _COOLDOWN.get(host, 0.0)
    delay = until - time.monotonic()
    if delay > 0:
        time.sleep(delay)


def _is_refusal(e: BaseException) -> bool:
    """A refused or reset connection: the host pushing back on a burst (not a slow page or a 5xx)."""
    r = e.reason if isinstance(e, urllib.error.URLError) else e
    return isinstance(r, (ConnectionRefusedError, ConnectionResetError))


def budget_problem(n_urls: int, workers: int = WORKERS, deadline_minutes: float = DEADLINE_MINUTES):
    """None when n_urls fit the deadline with the retry allowance, else the reason."""
    need = n_urls * SECONDS_PER_URL / workers + RETRY_ALLOWANCE_S  # allowance is serial: it stalls every worker
    if need > deadline_minutes * 60:
        return (f"{n_urls} URLs need ~{need / 60:.1f} min ({SECONDS_PER_URL}s/URL over {workers} workers "
                f"+ {RETRY_ALLOWANCE_S}s retry allowance), over the {deadline_minutes:g}-minute deadline")
    return None


def fetch(url: str, waits=RETRY_WAITS) -> tuple[str, str]:
    """-> (verdict, detail). Transport errors and 5xx are retried after each of `waits` seconds
    (shared per-host cool-down); never raises."""
    host = urllib.parse.urlsplit(url).hostname or ""
    last = ""
    last_code: int | None = None
    attempts = len(waits) + 1
    for attempt in range(attempts):
        _wait_cooldown(host)
        if attempt:
            with _LOCK:
                RETRIED[url] = attempt
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                r.read(1)  # the body starts; the headers alone prove less
                final = r.geturl()
                marker = SOFT_404.get(host)
                if marker and marker in final:
                    return "fail", f"soft-404: redirected to {final}"
                return classify(r.status, host), f"HTTP {r.status}"
        except urllib.error.HTTPError as e:
            if 300 <= e.code < 400:
                return "fail", f"HTTP {e.code} (redirect not followed)"
            if e.code < 500:
                return classify(e.code, host), f"HTTP {e.code}"
            last, last_code = f"HTTP {e.code}", e.code
        except Exception as e:  # noqa: BLE001 -- reported, not raised
            last, last_code = f"{type(e).__name__}: {e}", None
            if _is_refusal(e) and attempt < attempts - 1:
                _note_transient(host, waits[attempt])
                continue
        if attempt < attempts - 1:
            time.sleep(waits[attempt])
    if last_code is not None:  # a 5xx on the last attempt is an answer: a host recorded as returning it is blocked
        return classify(last_code, host), f"{last} (after {attempts} attempts)"
    return "fail", f"{last} (after {attempts} attempts)"


def run_fetches(urls, workers: int = WORKERS, deadline: float | None = None, fetcher=fetch, pause: float = PAUSE):
    """-> {url: (verdict, detail)}; a url the deadline stopped us before is `not-checked`."""
    results: dict[str, tuple[str, str]] = {}
    RETRIED.clear()

    def one(u):
        if deadline is not None and time.monotonic() > deadline:
            return u, ("not-checked", "deadline reached before this URL")
        r = fetcher(u)
        time.sleep(pause)
        return u, r

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for u, r in ex.map(one, urls):
            results[u] = r
    return results


def coverage(root: Path = ROOT):
    docs = document_urls(root)
    man = manifest_urls(root)
    uncovered = sorted(u for u in docs if u not in man)
    return docs, man, uncovered


def _week(today: dt.date | None = None) -> int:
    return (today or dt.date.today()).toordinal() // 7


def lychee_wiring_problems(wf: dict) -> list[str]:
    """Pure: what is wrong with how the parsed check-links workflow calls lychee."""
    bad = []
    lychee = next((j.get("with", {}) for j in wf["jobs"].values() if "check-links.yml" in str(j.get("uses", ""))), {})
    if int(lychee.get("max-retries", 0)) < 3 or float(lychee.get("retry-wait-time", 0)) < 2:
        bad.append("check-links.yml gives lychee no retries (max-retries >= 3, retry-wait-time >= 2); "
                   "a refused connection on one curated link would turn the run red (#437)")
    if "accept-codes" in lychee:
        bad.append("check-links.yml sets accept-codes; widening it hides real failures (#437)")
    return bad


def check() -> int:
    """Offline. The arithmetic the weekly job's claim rests on, and its wiring."""
    docs, man, uncovered = coverage()
    in_man = len(docs) - len(uncovered)
    n_docs = sum(len(v) for v in docs.values())
    this_run, info = plan(uncovered, 0)
    print(f"  {len(docs)} distinct source_url(s) across {n_docs} document(s)")
    print(f"  {in_man} are manifest URLs (drift job); {len(uncovered)} are checked here "
          f"({sum(len(docs[u]) for u in uncovered)} document(s))")
    print(f"  per run: {info['full']} small-host URL(s) in full + one of {info['cycle']} hash slots "
          f"of {info['bulk']} bulk-host URL(s) (largest slot {info['largest']}); "
          f"full cycle = {info['cycle']} week(s); budget {info['budget']} fetches/run")
    print(f"  worst-case time of the largest run: "
          f"{(info['full'] + info['largest']) * SECONDS_PER_URL / WORKERS / 60:.1f} min + "
          f"{RETRY_ALLOWANCE_S / 60:.1f} min retry allowance, deadline {DEADLINE_MINUTES} min")
    bad = []
    if info["full"] + info["largest"] > info["budget"]:
        bad.append(f"the largest weekly slot ({info['full']} + {info['largest']} URLs) exceeds the "
                   f"{info['budget']}-URL budget; raise CYCLE_WEEKS (now {info['cycle']})")
    over = budget_problem(info["full"] + info["largest"])
    if over:
        bad.append(f"the largest weekly run does not fit the deadline with retries: {over}; raise CYCLE_WEEKS "
                   f"(now {info['cycle']})")
    seen: set[str] = set()
    for w in range(info["cycle"]):
        run, _ = plan(uncovered, w)
        seen.update(run)
    if seen != set(uncovered):
        bad.append(f"rotation does not cover every uncovered source_url over {info['cycle']} week(s): "
                   f"{len(set(uncovered) - seen)} never visited")
    # Every document source_url is either a manifest URL or in the population -- by construction
    # of `coverage`, but the NUMBERS ARE THE POINT: a zero-document population would be a green
    # run that checked nothing.
    if not docs or not uncovered:
        bad.append("no source_url population found; refusing to call that covered")
    wf = yaml.safe_load((ROOT / ".github/workflows/check-links.yml").read_text())
    steps = [s for j in wf["jobs"].values() for s in j.get("steps", [])]
    if not any("src/check_source_urls.py" in (s.get("run") or "") for s in steps):
        bad.append(".github/workflows/check-links.yml does not run src/check_source_urls.py")
    if "schedule" not in (wf.get(True) or wf.get("on") or {}):
        bad.append("check-links.yml has no schedule; the source_url check would only run by hand")
    bad += lychee_wiring_problems(wf)
    for m in bad:
        print("FAIL", m, file=sys.stderr)
    return 1 if bad else 0


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        code = {"/ok": 200, "/gone": 404, "/forbidden": 403, "/throttle": 429, "/boom": 500}.get(self.path)
        if self.path == "/loop":
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.end_headers()
            return
        if self.path == "/oard/view.action":
            self.send_response(302)
            self.send_header("Location", "/oard/ruleSearchResults.action;JSESSIONID=abc?ruleNumber=1")
            self.end_headers()
            return
        if self.path == "/oard/viewSingleRule.action" or self.path.startswith("/oard/ruleSearchResults.action"):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        m = re.fullmatch(r"/(reset|boom)(\d)", self.path)
        if m:  # misbehave on the first N hits of this path, then answer 200
            _H.hits[self.path] += 1
            if _H.hits[self.path] <= int(m.group(2)):
                if m.group(1) == "reset":
                    self.close_connection = True
                    self.connection.close()
                    return
                self.send_response(500)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"no")
                return
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
            return
        self.send_response(code or 404)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")
        _H.agents.append(self.headers.get("User-Agent"))

    def log_message(self, *a):
        pass

    agents: list = []
    hits: dict = defaultdict(int)


def _selftest_retries(eq, base: str) -> None:
    """#437: a transient transport fault is retried with backoff and only then a FAIL; the
    semantics of 404/403/429, soft-404 and redirect loops are untouched (not retried)."""
    fast = (0.01, 0.01)
    # server resets (closes with no response) the first 2 connections, then serves 200
    _H.hits.clear()
    RETRIED.clear()
    v = fetch(base + "/reset2", waits=fast)
    eq("reset twice then 200 is ok", v[0], "ok")
    eq("...and it is counted as retried", RETRIED.get(base + "/reset2"), 2)
    # three resets with only two retries allowed: still a fail, naming the attempts
    _H.hits.clear()
    v = fetch(base + "/reset3", waits=fast)
    eq("reset on every attempt is a fail", v[0], "fail")
    eq("...detail names the attempt count", "after 3 attempts" in v[1], True)
    # 5xx first, then 200
    _H.hits.clear()
    eq("500 then 200 is ok", fetch(base + "/boom1", waits=fast)[0], "ok")
    eq("a persistent 500 is still a fail", fetch(base + "/boom", waits=fast)[0], "fail")
    # non-transient answers are NOT retried
    for path in ("/gone", "/forbidden", "/throttle", "/loop"):
        RETRIED.clear()
        fetch(base + path, waits=fast)
        eq(f"{path} is not retried", RETRIED.get(base + path), None)
    # a real ECONNREFUSED: nothing listens, the listener appears 0.4s later
    # the port is bound (so nothing else can take it) but not listening: Linux refuses connections
    late = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H, bind_and_activate=False)
    late.server_bind()
    port = late.server_address[1]
    up = threading.Event()

    def _come_up():
        late.server_activate()
        up.set()
        late.serve_forever()
    timer = threading.Timer(0.4, _come_up)
    timer.daemon = True
    timer.start()
    try:
        v = fetch(f"http://127.0.0.1:{port}/ok", waits=(0.3, 0.6, 1.0))
        eq("connection refused, then the host comes up, is ok", v[0], "ok")
        eq("...with a counted retry", RETRIED.get(f"http://127.0.0.1:{port}/ok", 0) >= 1, True)
    finally:
        timer.cancel()
        if up.is_set():
            late.shutdown()
        late.server_close()
    # a refusal makes the HOST cool down, so the other workers back off too
    _COOLDOWN.clear()
    _note_transient("h.example", 5)
    eq("cooldown is recorded per host", "h.example" in _COOLDOWN and "other.example" not in _COOLDOWN, True)
    _COOLDOWN.clear()
    # ...and another worker really waits on it, while a different host does not
    _note_transient("127.0.0.1", 0.3)
    t0 = time.monotonic()
    th = threading.Thread(target=lambda: fetch(base + "/ok", waits=fast))
    th.start()
    th.join()
    eq("a cooled host delays another worker", time.monotonic() - t0 >= 0.28, True)
    _COOLDOWN.clear()
    _note_transient("other.example", 5)
    t0 = time.monotonic()
    fetch(base + "/ok", waits=fast)
    eq("a different host is not delayed", time.monotonic() - t0 < 0.25, True)
    _COOLDOWN.clear()
    # a recorded 5xx host is blocked (KNOWN_BLOCKED semantics), an unrecorded one fails
    KNOWN_BLOCKED["127.0.0.1"] = {"status": 500, "since": "t", "evidence": "t"}
    try:
        eq("recorded persistent 500 is blocked", fetch(base + "/boom", waits=fast)[0], "blocked")
    finally:
        del KNOWN_BLOCKED["127.0.0.1"]
    eq("unrecorded persistent 500 is fail", fetch(base + "/boom", waits=fast)[0], "fail")
    # only refusals/resets cool the host; a 500 does not
    _COOLDOWN.clear()
    fetch(base + "/boom", waits=fast)
    eq("a 5xx does not cool the whole host", _COOLDOWN, {})
    # the run reports how many URLs needed a retry
    RETRIED.clear()
    res = run_fetches([base + "/reset2", base + "/ok"], workers=2, pause=0, fetcher=lambda u: fetch(u, waits=fast))
    eq("run_fetches verdicts after retry", sorted(v[0] for v in res.values()), ["ok", "ok"])
    eq("retried count reported", len(RETRIED), 1)
    # the workflow wiring rules can fail
    good = {"jobs": {"l": {"uses": "./.github/workflows/check-links.yml", "with": {"max-retries": 3, "retry-wait-time": 2}}}}
    eq("good lychee wiring has no problems", lychee_wiring_problems(good), [])
    eq("no retries is a problem", len(lychee_wiring_problems({"jobs": {"l": {"uses": "x/check-links.yml", "with": {}}}})), 1)
    good["jobs"]["l"]["with"]["accept-codes"] = "200..=599"
    eq("accept-codes is a problem", len(lychee_wiring_problems(good)), 1)
    # the deadline arithmetic the budget rests on
    eq("budget fits: worst-case run time is under the deadline", budget_problem(1700, 4, 40) is None, True)
    eq("budget counts the cool-down serially", "retry allowance" in (budget_problem(10**6) or ""), True)
    eq("budget breaks when the window outgrows the deadline", budget_problem(1847, 4, 40) is not None, True)


def selftest() -> int:
    fails = []

    def eq(name, got, want):
        if got != want:
            fails.append(f"{name}: got {got!r}, want {want!r}")

    # extraction
    eq("plain", _source_url("---\nid: x\nsource_url: https://a/b?c=1\n---\nbody"), "https://a/b?c=1")
    eq("quoted", _source_url("---\nsource_url: 'https://a'\n---\n"), "https://a")
    eq("absent is None, not ''", _source_url("---\nid: x\n---\nsource_url: https://in-body\n"), None)
    eq("no frontmatter", _source_url("source_url: https://a"), None)

    # plan: small hosts in full, bulk host rotates by hash slot, every URL visited exactly once per cycle
    small = [f"https://small.example/{i}" for i in range(40)]
    bulk = [f"https://bulk.example/{i}" for i in range(SMALL_HOST + 700)]
    pop = small + bulk
    cyc = 5
    run0, info = plan(pop, 0, cycle=cyc)
    eq("cycle is the constant", info["cycle"], cyc)
    eq("default cycle is CYCLE_WEEKS", plan(pop, 0)[1]["cycle"], CYCLE_WEEKS)
    visits = defaultdict(int)
    for w in range(cyc):
        r, _ = plan(pop, w, cycle=cyc)
        eq("small host fully in every run", set(small) <= set(r), True)
        for u in r:
            if u.startswith("https://bulk"):
                visits[u] += 1
    eq("each bulk URL visited exactly once per cycle", set(visits.values()), {1})
    eq("cycle visits all bulk URLs", len(visits), len(bulk))
    eq("week wraps around the cycle", plan(pop, cyc, cycle=cyc)[0], plan(pop, 0, cycle=cyc)[0])
    eq("dedupes", len(plan(pop + pop, 0, cycle=1)[0]), len(pop))
    # membership is stable when the population grows: slot depends on the URL alone, so adding
    # documents -- even enough to cross a multiple of the old window -- moves no other URL
    grown = pop + [f"https://bulk.example/new{i}" for i in range(900)]
    for w in range(cyc):
        r0, _ = plan(pop, w, cycle=cyc)
        r1, _ = plan(grown, w, cycle=cyc)
        eq(f"week {w}: every URL of the old slot stays in it after growth", set(r0) <= set(r1), True)
        eq(f"week {w}: growth only adds URLs", set(r1) - set(r0) <= set(grown) - set(pop), True)
    eq("a populated slot is never empty after growth",
       all(plan(grown, w, cycle=cyc)[0] for w in range(cyc)), True)

    # classification
    eq("2xx ok", classify(200, "h"), "ok")
    eq("404 fails", classify(404, "h"), "fail")
    eq("403 fails when not recorded", classify(403, "h"), "fail")
    eq("429 throttled", classify(429, "h"), "throttled")
    KNOWN_BLOCKED["blocked.example"] = {"status": 403, "since": "t", "evidence": "t"}
    try:
        eq("recorded 403 blocked", classify(403, "blocked.example"), "blocked")
        eq("recorded host, other status still fails", classify(404, "blocked.example"), "fail")
    finally:
        del KNOWN_BLOCKED["blocked.example"]

    # the real fetch path against a loopback server
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        for path, want in (("/ok", "ok"), ("/redirect", "ok"), ("/gone", "fail"),
                           ("/forbidden", "fail"), ("/throttle", "throttled")):
            eq(f"fetch {path}", fetch(base + path)[0], want)
        eq("redirect loop fails, not ok", fetch(base + "/loop")[0], "fail")
        host = urllib.parse.urlsplit(base).hostname
        eq("soft-404 passes when the host is not in SOFT_404", fetch(base + "/oard/view.action")[0], "ok")
        SOFT_404[host] = "ruleSearchResults.action"
        try:
            v = fetch(base + "/oard/view.action")
            eq("soft-404 redirect to the search page fails", v[0], "fail")
            eq("soft-404 detail names the final url", "ruleSearchResults.action" in v[1], True)
            eq("a real record on a SOFT_404 host is ok", fetch(base + "/oard/viewSingleRule.action")[0], "ok")
        finally:
            del SOFT_404[host]
        eq("honest user agent sent", set(a for a in _H.agents if a), {UA})
        eq("unreachable host fails (not skipped)", fetch("http://127.0.0.1:9/x", waits=(0.01, 0.01))[0], "fail")
        _selftest_retries(eq, base)
        res = run_fetches([base + "/ok", base + "/gone"], workers=2, pause=0)
        eq("run_fetches verdicts", {u.rsplit("/", 1)[1]: v[0] for u, v in res.items()}, {"ok": "ok", "gone": "fail"})
        res = run_fetches([base + "/ok"] * 1 + [base + "/gone"], workers=1, deadline=time.monotonic() - 1, pause=0)
        eq("deadline lists the rest as not-checked, never ok", {v[0] for v in res.values()}, {"not-checked"})
        eq("verdicts -> exit: all ok is 0", _exit_code({"ok": [1]}), 0)
        eq("verdicts -> exit: not-checked is 2", _exit_code({"ok": [1], "not-checked": [1]}), 2)
        eq("verdicts -> exit: throttled is 2", _exit_code({"throttled": [1]}), 2)
        eq("verdicts -> exit: fail beats could-not-check", _exit_code({"fail": [1], "not-checked": [1]}), 1)
    finally:
        srv.shutdown()

    for m in fails:
        print("FAIL", m, file=sys.stderr)
    if fails:
        return 1
    print("selftest ok: extraction, rotation, classification, fetch, soft-404, redirects, deadline, exit codes")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true")
    g.add_argument("--selftest", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-urls", type=int, default=DEFAULT_MAX_URLS)
    ap.add_argument("--week", type=int, default=None, help="rotation index (default: ISO-ordinal week of today)")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--deadline-minutes", type=float, default=DEADLINE_MINUTES)
    a = ap.parse_args()
    if a.check:
        return check()
    if a.selftest:
        return selftest()

    docs, man, uncovered = coverage()
    week = _week() if a.week is None else a.week
    todo, info = plan(uncovered, week, a.max_urls)
    print(f"  {len(docs)} distinct source_url(s); {len(docs) - len(uncovered)} are manifest URLs "
          f"(fetched by the drift job); {len(uncovered)} checked here")
    print(f"  this run: window {info['k'] + 1} of {info['cycle']} (a URL in the bulk set is visited "
          f"once per {info['cycle']} week(s)); {info['full']} small-host URL(s) in full + "
          f"{info['this_run'] - info['full']} of {info['bulk']} bulk-host URL(s)")
    if a.dry_run:
        return 0
    deadline = time.monotonic() + a.deadline_minutes * 60
    res = run_fetches(todo, a.workers, deadline)
    tally = defaultdict(list)
    for u, (v, d) in sorted(res.items()):
        tally[v].append((u, d))
    for v in ("fail", "blocked", "throttled", "not-checked"):
        for u, d in tally[v][:50]:
            print(f"  {v.upper():11} {u}  {d}  ({len(docs[u])} document(s), e.g. {docs[u][0]})")
        if len(tally[v]) > 50:
            print(f"  {v.upper():11} ... {len(tally[v]) - 50} more")
    print()
    print("  " + ", ".join(f"{v}={len(tally[v])}" for v in ("ok", "fail", "blocked", "throttled", "not-checked")))
    retried = {u: n for u, n in RETRIED.items() if u in res}
    ends = Counter(res[u][0] for u in retried)
    print(f"  {len(retried)} URL(s) needed a retry (transient fault): "
          + ", ".join(f"{ends[v]} ended {v}" for v in ("ok", "fail", "throttled", "blocked") if ends[v]))
    if tally["not-checked"]:
        print(f"{len(tally['not-checked'])} URL(s) were NOT CHECKED: the deadline ran out first.")
    if tally["blocked"] or tally["throttled"]:
        print(f"{len(tally['blocked']) + len(tally['throttled'])} URL(s) could not be verified "
              f"(blocked/throttled); not confirmed reachable.")
    _step_summary(tally)
    code = _exit_code(tally)
    if code == 1:
        print(f"{len(tally['fail'])} of our own source_url(s) are unreachable", file=sys.stderr)
    elif code == 2:
        print("INCOMPLETE: some URLs were throttled or not reached; this run did not check its whole "
              "window (exit 2, not a pass).", file=sys.stderr)
    return code


def _exit_code(tally) -> int:
    """1 = a source_url is unreachable; 2 = nothing failed but part of the window could not be
    checked (throttled / deadline) -- a skipped check is not a green one; 0 = whole window ok."""
    if tally.get("fail"):
        return 1
    if tally.get("not-checked") or tally.get("throttled"):
        return 2
    return 0


def _step_summary(tally) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["## Could not check", "", "| verdict | URLs |", "|---|---|"]
    for v in ("ok", "fail", "blocked", "throttled", "not-checked"):
        lines.append(f"| {v} | {len(tally.get(v, []))} |")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as e:
        print(f"could not write step summary: {e}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
