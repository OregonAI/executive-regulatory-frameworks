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
    `--max-urls` per run: URLs are ordered by sha1(url) and the window is
    `week % cycle`, so every URL is visited exactly once per `cycle` weeks and the order does
    not shift when documents are added;
  * the run prints its window ("window 7 of 15") and the cycle length, so "checked this
    week" is never confused with "checked";
  * a wall-clock `--deadline-minutes` stops fetching and lists what it did NOT reach as
    NOT CHECKED -- a run that ran out of time says so, it does not report the rest as fine.

STATUS MEANINGS. 2xx/3xx-followed: ok. 404/410/5xx/DNS/TLS/timeout after one retry: FAIL
(exit 1). 403 and 429 from a host not in KNOWN_BLOCKED: 429 is "throttled -- could not check"
(listed, exit 0); 403 is a FAIL, because a 403 cannot be told from a withdrawn page and this
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
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
UA = ("OregonAI-corpus-bot/0.1 (+https://github.com/OregonAI/executive-regulatory-frameworks; "
      "civic corpus link check)")

SMALL_HOST = 1000      # a host with at most this many distinct URLs is checked in full each run
DEFAULT_MAX_URLS = 2500  # per-run budget: small hosts first, the bulk-host window gets the rest
MIN_WINDOW = 500       # the bulk window never shrinks below this, however many small URLs there are
TIMEOUT = 30
PAUSE = 0.25           # seconds each worker waits after a request
WORKERS = 4

# host -> {"status", "since", "evidence"}. Empty today: nothing is recorded as refusing our
# runners. An entry is a fact about OUR ACCESS, never about upstream; see the module docstring.
KNOWN_BLOCKED: dict[str, dict] = {}

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


def plan(urls, week: int, max_urls: int = DEFAULT_MAX_URLS):
    """Return (this_run, info). `urls` is the population (already deduped, not manifest)."""
    by_host: dict[str, list[str]] = defaultdict(list)
    for u in set(urls):
        by_host[urllib.parse.urlsplit(u).hostname or ""].append(u)
    full = sorted(u for h, us in by_host.items() if len(us) <= SMALL_HOST for u in us)
    bulk = sorted((u for h, us in by_host.items() if len(us) > SMALL_HOST for u in us), key=_h)
    window = max(max_urls - len(full), MIN_WINDOW)
    cycle = max(1, math.ceil(len(bulk) / window)) if bulk else 1
    k = week % cycle
    chunk = bulk[k * window:(k + 1) * window]
    return full + chunk, {"full": len(full), "bulk": len(bulk), "window": window,
                          "cycle": cycle, "k": k, "this_run": len(full) + len(chunk)}


def classify(status: int, host: str) -> str:
    """ok | blocked | throttled | fail  (blocked only for a host whose RECORDED status this is)."""
    known = KNOWN_BLOCKED.get(host)
    if known and status == known["status"]:
        return "blocked"
    if status == 429:
        return "throttled"
    return "ok" if status < 400 else "fail"


def fetch(url: str) -> tuple[str, str]:
    """-> (verdict, detail). One retry on a transport error or 5xx; never raises."""
    host = urllib.parse.urlsplit(url).hostname or ""
    last = ""
    for attempt in (0, 1):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                r.read(1)  # the body starts; the headers alone prove less
                return classify(r.status, host), f"HTTP {r.status}"
        except urllib.error.HTTPError as e:
            v = classify(e.code, host)
            if e.code >= 500 and attempt == 0:
                last = f"HTTP {e.code}"
                time.sleep(2)
                continue
            return v, f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001 -- reported, not raised
            last = f"{type(e).__name__}: {e}"
            if attempt == 0:
                time.sleep(2)
                continue
    return "fail", last


def run_fetches(urls, workers: int = WORKERS, deadline: float | None = None, fetcher=fetch, pause: float = PAUSE):
    """-> {url: (verdict, detail)}; a url the deadline stopped us before is `not-checked`."""
    results: dict[str, tuple[str, str]] = {}

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


def check() -> int:
    """Offline. The arithmetic the weekly job's claim rests on, and its wiring."""
    docs, man, uncovered = coverage()
    in_man = len(docs) - len(uncovered)
    n_docs = sum(len(v) for v in docs.values())
    this_run, info = plan(uncovered, 0)
    print(f"  {len(docs)} distinct source_url(s) across {n_docs} document(s)")
    print(f"  {in_man} are manifest URLs (drift job); {len(uncovered)} are checked here "
          f"({sum(len(docs[u]) for u in uncovered)} document(s))")
    print(f"  per run: {info['full']} small-host URL(s) in full + a {info['window']}-URL window of "
          f"{info['bulk']} bulk-host URL(s); full cycle = {info['cycle']} week(s); "
          f"~{info['this_run']} fetches/run")
    bad = []
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
    for m in bad:
        print("FAIL", m, file=sys.stderr)
    return 1 if bad else 0


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        code = {"/ok": 200, "/gone": 404, "/forbidden": 403, "/throttle": 429, "/boom": 500}.get(self.path)
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

    # plan: small hosts in full, bulk host rotates, every URL visited exactly once per cycle
    small = [f"https://small.example/{i}" for i in range(40)]
    bulk = [f"https://bulk.example/{i}" for i in range(SMALL_HOST + 700)]
    pop = small + bulk
    run0, info = plan(pop, 0, max_urls=DEFAULT_MAX_URLS)
    eq("cycle length", info["cycle"], math.ceil(len(bulk) / max(DEFAULT_MAX_URLS - 40, MIN_WINDOW)))
    run_small, info2 = plan(pop, 0, max_urls=40 + 600)
    eq("window sized to budget", info2["window"], 600)
    eq("small host fully in every run", set(small) <= set(run_small), True)
    visits = defaultdict(int)
    for w in range(info2["cycle"]):
        r, _ = plan(pop, w, max_urls=40 + 600)
        for u in r:
            if u.startswith("https://bulk"):
                visits[u] += 1
    eq("each bulk URL visited exactly once per cycle", set(visits.values()), {1})
    eq("cycle visits all bulk URLs", len(visits), len(bulk))
    eq("dedupes", len(plan(pop + pop, 0, max_urls=10 ** 6)[0]), len(pop))
    r1, _ = plan(pop + ["https://bulk.example/new"], 0, max_urls=40 + 600)
    r0, _ = plan(pop, 0, max_urls=40 + 600)
    # order is by hash of the URL itself, so adding one URL shifts the window by at most one slot
    eq("window mostly stable when a document is added", len(set(r0) & set(r1)) >= len(r0) - 1, True)

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
        eq("honest user agent sent", set(a for a in _H.agents if a), {UA})
        eq("unreachable host fails (not skipped)", fetch("http://127.0.0.1:9/x")[0], "fail")
        res = run_fetches([base + "/ok", base + "/gone"], workers=2, pause=0)
        eq("run_fetches verdicts", {u.rsplit("/", 1)[1]: v[0] for u, v in res.items()}, {"ok": "ok", "gone": "fail"})
        res = run_fetches([base + "/ok"] * 1 + [base + "/gone"], workers=1, deadline=time.monotonic() - 1, pause=0)
        eq("deadline lists the rest as not-checked, never ok", {v[0] for v in res.values()}, {"not-checked"})
    finally:
        srv.shutdown()

    for m in fails:
        print("FAIL", m, file=sys.stderr)
    if fails:
        return 1
    print("selftest ok: extraction, rotation, classification, fetch, deadline")
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
    ap.add_argument("--deadline-minutes", type=float, default=40)
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
    if tally["not-checked"]:
        print(f"{len(tally['not-checked'])} URL(s) were NOT CHECKED: the deadline ran out first.")
    if tally["blocked"] or tally["throttled"]:
        print(f"{len(tally['blocked']) + len(tally['throttled'])} URL(s) could not be verified "
              f"(blocked/throttled); not counted as failures, not confirmed reachable either.")
    if tally["fail"]:
        print(f"{len(tally['fail'])} of our own source_url(s) are unreachable", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
