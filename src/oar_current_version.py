#!/usr/bin/env python3
"""Resolve a pinned OAR document's CURRENT ruleVrsnRsn from OARD's chapter listing (#440).

  python3 src/oar_current_version.py --resolve        # report: is each pinned rsn still current?
  python3 src/oar_current_version.py --mark           # record the mechanism on each pinned document
  python3 src/oar_current_version.py --sync-manifest  # point _meta/sources/oar.yml at the current rsn
  python3 src/oar_current_version.py --check          # CI (offline): every pinned document says so
  python3 src/oar_current_version.py --selftest       # CI: a new rsn in a listing changes what is fetched

WHY. #442 re-pointed 37 documents -- OARD search-result pages -- at pinned
`viewSingleRule.action?ruleVrsnRsn=<n>` pages, because the bare `view.action?ruleNumber=` URL is
a soft 404 for those numbers. OARD issues a NEW `ruleVrsnRsn` when a rule is amended, so a
pinned page never changes and drift, which hashes the page, reports the amendment as "unchanged"
forever. The chapter listing of record (`displayChapterRules.action?selectedChapter=<id>`) names
the CURRENT record for every number it carries (the href of each rule row), so:

  * a number the listing links to an rsn other than the pinned one has been AMENDED: the listing's
    rsn is the page to fetch (the Bulletin refresh, `reingest_oar.py`) and to hash (drift, through
    `--sync-manifest`, which moves the manifest `url` and leaves its `sha256`, so the next drift
    run sees the new record as changed);
  * a number the listing no longer carries is not current: OARD has dropped it (repealed). The
    pinned LAST-IN-FORCE record is kept, and the document says so (`current_version_listed:
    false`) -- it is never refetched as if it were live and never silently treated as current;
  * a listing that cannot be read (an error page, a chapter the catalog has no id for) is
    REFUSED (`ListingUnreadable`), never read as "the number was repealed". "Could not check" is
    not "is not there".

`current_version_listed: true` says ONLY that the listing links a record for the number. It says
nothing about force: OARD still lists some sunset rules (titled "Migrated from Repeals and
Renumbers file") and those are `status: repealed` beside `listed: true`.

The chapter id is the catalog's (`_meta/catalog/oar.yml`, refreshed by `catalog_oar.py`). Listings
are fetched politely through `ingest_lib.fetch_page` (honest user agent, one host, spaced)."""
import argparse
import re
import sys
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml

from repo_lib import REPO_ROOT, Checks, content_files, parse_frontmatter

CATALOG = REPO_ROOT / "_meta/catalog/oar.yml"
MANIFEST = REPO_ROOT / "_meta/sources/oar.yml"
OARD = "https://secure.sos.state.or.us/oard"
VERSION_URL = OARD + "/viewSingleRule.action?ruleVrsnRsn={rsn}"

# The row of a chapter listing: the rule number is the link text, the record is the href's
# ruleVrsnRsn (a session id sits between, which is why the pattern skips to the parameter).
LISTING_LINK_RE = re.compile(r"<a href='[^']*?ruleVrsnRsn=(\d+)'>(\d{3}-\d{3}-\d{4})</a>")
PINNED_RE = re.compile(r'^source_url:\s*"?https://secure\.sos\.state\.or\.us/oard/'
                       r'viewSingleRule\.action\?ruleVrsnRsn=(\d+)', re.M)

CURRENT, AMENDED, NOT_LISTED, AMBIGUOUS = "current", "amended", "not_listed", "ambiguous"
Resolution = namedtuple("Resolution", "number pinned rsn state")

# What each pinned document says about itself.
VIA_KEY, LISTED_KEY, VIA_VALUE = "current_version_via", "current_version_listed", "chapter-listing"
VIA_LINE_RE = re.compile(r"^current_version_via: .*\n", re.M)
LISTED_LINE_RE = re.compile(r"^current_version_listed: .*\n", re.M)


class ListingUnreadable(Exception):
    """A chapter listing that cannot be trusted to say a number is gone."""


def parse_listing(html: str) -> dict:
    """A chapter listing page -> {rule number: (rsn, ...)} in page order, no duplicates."""
    out = {}
    for rsn, number in LISTING_LINK_RE.findall(html):
        seen = out.setdefault(number, [])
        if rsn not in seen:
            seen.append(rsn)
    return {n: tuple(v) for n, v in out.items()}


def resolve_number(number: str, pinned: str, listing: dict) -> Resolution:
    """Pure: what a readable `listing` says about `number`, which is pinned at `pinned`."""
    rsns = listing.get(number)
    if not rsns:
        return Resolution(number, pinned, pinned, NOT_LISTED)
    if pinned in rsns:
        return Resolution(number, pinned, pinned, CURRENT)
    if len(rsns) == 1:
        return Resolution(number, pinned, rsns[0], AMENDED)
    return Resolution(number, pinned, pinned, AMBIGUOUS)


class ChapterListings:
    """Chapter listings fetched on demand, ONCE per chapter. `fetch(url) -> str` is the network,
    injected so nothing here needs a live site to be exercised."""

    def __init__(self, catalog=None, fetch=None):
        catalog = catalog if catalog is not None else yaml.safe_load(CATALOG.read_text())
        self._urls = {c["chapter"]: c.get("url") for c in catalog.get("chapters", [])}
        self._fetch = fetch or _default_fetch
        self._cache = {}

    def listing(self, number: str) -> dict:
        chapter = number.split("-")[0]
        if chapter not in self._cache:
            url = self._urls.get(chapter)
            if not url:
                raise ListingUnreadable(f"chapter {chapter}: the catalog holds no listing url")
            parsed = parse_listing(self._fetch(url))
            if not any(n.startswith(chapter + "-") for n in parsed):
                raise ListingUnreadable(
                    f"chapter {chapter}: {url} carried no rule of that chapter -- an error page "
                    "is not evidence that a rule was repealed")
            self._cache[chapter] = parsed
        return self._cache[chapter]


def resolve(listings: ChapterListings, number: str, pinned: str) -> Resolution:
    return resolve_number(number, pinned, listings.listing(number))


def _default_fetch(url: str) -> str:
    from ingest_lib import fetch_page
    return fetch_page(url).body.decode("utf-8", errors="replace")


def version_url(rsn: str) -> str:
    return VERSION_URL.format(rsn=rsn)


def pinned_rsn(text: str):
    """The ruleVrsnRsn a document's `source_url` is pinned at, or None."""
    block = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    m = PINNED_RE.search(block.group(1) if block else text)
    return m.group(1) if m else None


def pinned_documents(paths=None) -> dict:
    """{rule number: (path, pinned rsn)} for every OAR document pinned to a record."""
    out = {}
    for p in (paths if paths is not None else content_files()):
        if not p.stem.startswith("oar-"):
            continue
        rsn = pinned_rsn(p.read_text(encoding="utf-8"))
        if rsn:
            out[p.stem[len("oar-"):]] = (p, rsn)
    return out


def refresh_url(number: str, pinned: str, listings) -> str:
    """The page a refresh of `number` must fetch: the listing's current record where it names a
    new one, the pinned record otherwise (current, not listed, ambiguous). `listings=None`
    means no resolver was supplied and the pinned record is all there is."""
    if listings is None:
        return version_url(pinned)
    return version_url(resolve(listings, number, pinned).rsn)


def mark_text(text: str, listed: bool) -> str:
    """The document with its resolution record set: where the current version comes from, and
    whether the listing of record still carries the number."""
    text = VIA_LINE_RE.sub("", LISTED_LINE_RE.sub("", text, count=1), count=1)
    lines = f'{VIA_KEY}: "{VIA_VALUE}"\n{LISTED_KEY}: {"true" if listed else "false"}\n'
    new, n = re.subn(r"^((?:upstream_tracking|source_sha256): .*\n)(?!upstream_tracking)",
                     lambda m: m.group(1) + lines, text, count=1, flags=re.M)
    return new if n else text


def sync_manifest(manifest: dict, resolutions: dict) -> list:
    """Point every manifest entry of a pinned document at its CURRENT record. `resolutions` is
    {rule number: Resolution}. The entry's `sha256` is left alone: it is the hash of the page it
    last saw, so drift sees the new record as a change. Returns the ids moved."""
    moved = []
    for s in manifest.get("sources") or []:
        r = resolutions.get(s["id"][len("oar-"):]) if s["id"].startswith("oar-") else None
        if r is not None and r.state == AMENDED and "viewSingleRule" in s["url"]:
            s["url"] = version_url(r.rsn)
            moved.append(s["id"])
    return moved


# ----------------------------------------------------------------------------- commands


def _resolve_all(listings=None):
    listings = listings or ChapterListings()
    out, unreadable = {}, []
    for number, (_, rsn) in sorted(pinned_documents().items()):
        try:
            out[number] = resolve(listings, number, rsn)
        except ListingUnreadable as e:
            unreadable.append(f"{number}: {e}")
    return out, unreadable


def cmd_resolve() -> int:
    res, unreadable = _resolve_all()
    for r in res.values():
        print(f"{r.state:10} oar-{r.number} pinned {r.pinned} -> {r.rsn}")
    for u in unreadable:
        print(f"UNREADABLE {u}")
    print(f"{len(res)} pinned document(s) resolved: "
          + ", ".join(f"{s} {sum(1 for r in res.values() if r.state == s)}"
                      for s in (CURRENT, AMENDED, NOT_LISTED, AMBIGUOUS)))
    return 1 if unreadable else 0


def cmd_mark() -> int:
    res, unreadable = _resolve_all()
    pinned = pinned_documents()
    changed = 0
    for number, r in res.items():
        path, _ = pinned[number]
        text = path.read_text(encoding="utf-8")
        new = mark_text(text, r.state != NOT_LISTED)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed += 1
    for u in unreadable:
        print(f"UNREADABLE {u}")
    print(f"marked {changed} of {len(res)} pinned document(s)")
    return 1 if unreadable else 0


def cmd_sync_manifest() -> int:
    res, unreadable = _resolve_all()
    manifest = yaml.safe_load(MANIFEST.read_text())
    moved = sync_manifest(manifest, res)
    if moved:
        MANIFEST.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=110))
    for u in unreadable:
        print(f"UNREADABLE {u}")
    print(f"{len(moved)} manifest entr(ies) moved to a new record: {', '.join(moved) or 'none'}")
    return 1 if unreadable else 0


def check_documents(docs: dict, manifest_urls: dict) -> list:
    """Offline. `docs` is {number: text}. Every document pinned to a record must say its current
    version is resolved through the chapter listing, and say whether the listing still carries
    it; nothing else may claim it. A manifest entry for a pinned document must itself be a
    viewSingleRule page (the bare-number URL is a soft 404 for these numbers)."""
    out = []
    for number, text in sorted(docs.items()):
        block = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
        fm = yaml.safe_load(block.group(1)) if block else {}
        pinned = pinned_rsn(text) is not None
        if pinned and (fm.get(VIA_KEY) != VIA_VALUE or not isinstance(fm.get(LISTED_KEY), bool)):
            out.append(f"oar-{number} is pinned to a ruleVrsnRsn but does not record that its "
                       f"current version is resolved via the chapter listing -- run: "
                       "python3 src/oar_current_version.py --mark")
        if not pinned and (VIA_KEY in fm or LISTED_KEY in fm):
            out.append(f"oar-{number} claims chapter-listing resolution but is not pinned")
        url = manifest_urls.get(f"oar-{number}")
        if pinned and url and "viewSingleRule.action?ruleVrsnRsn=" not in url:
            out.append(f"oar-{number} is pinned but its manifest entry watches {url}, a soft 404")
    return out


def cmd_check() -> int:
    manifest = yaml.safe_load(MANIFEST.read_text())
    urls = {s["id"]: s["url"] for s in manifest.get("sources") or []}
    docs = {}
    for p in content_files():
        if p.stem.startswith("oar-"):
            text = p.read_text(encoding="utf-8")
            if pinned_rsn(text) or VIA_KEY in text[:4000]:
                docs[p.stem[len("oar-"):]] = text
    problems = check_documents(docs, urls)
    for p in problems:
        print("FAIL", p)
    if problems:
        return 1
    n = sum(1 for t in docs.values() if pinned_rsn(t))
    gone = sum(1 for t in docs.values() if pinned_rsn(t) and re.search(
        r"^current_version_listed: false$", t, re.M))
    print(f"OK: {n} document(s) pinned to a ruleVrsnRsn, every one records resolution via the "
          f"chapter listing ({gone} no longer listed: pinned last-in-force record kept)")
    return 0


# --------------------------------------------------------------------------- selftest


def _listing(*pairs, chapter="813") -> str:
    rows = "".join(
        f"<p><strong><a href='/oard/viewSingleRule.action;JSESSIONID_OARD=abc!-1?ruleVrsnRsn={rsn}'>"
        f"{num}</a></strong>&nbsp;&nbsp;A Rule</p>" for num, rsn in pairs)
    return f"<html><body><h3>Chapter {chapter}</h3>{rows}</body></html>"


def _proof_parse_listing(check) -> None:
    got = parse_listing(_listing(("813-005-0025", "335876"), ("813-005-0030", "196419")))
    check("a chapter listing yields number -> the ruleVrsnRsn it links to",
          got == {"813-005-0025": ("335876",), "813-005-0030": ("196419",)})
    check("a number the listing links twice keeps both records, in order",
          parse_listing(_listing(("165-020-0125", "5"), ("165-020-0125", "9")))
          == {"165-020-0125": ("5", "9")})


def _proof_resolve(check) -> None:
    lst = parse_listing(_listing(("813-005-0025", "335877"), ("813-005-0030", "196419"),
                                 ("165-020-0125", "5"), ("165-020-0125", "9")))
    r = resolve_number("813-005-0030", "196419", lst)
    check("a pinned rsn the listing still names is current", r.state == CURRENT and r.rsn == "196419")
    r = resolve_number("813-005-0025", "335876", lst)
    check("a NEW rsn in the listing is an amendment: the listing's rsn is what is fetched",
          r.state == AMENDED and r.rsn == "335877")
    r = resolve_number("813-005-0020", "333874", lst)
    check("a number the listing no longer carries keeps the pinned last-in-force record",
          r.state == NOT_LISTED and r.rsn == "333874")
    r = resolve_number("165-020-0125", "5", lst)
    check("two records for one number, the pinned one among them, stays pinned",
          r.state == CURRENT and r.rsn == "5")
    r = resolve_number("165-020-0125", "3", lst)
    check("two records and neither is the pinned one is AMBIGUOUS, never a guess",
          r.state == AMBIGUOUS and r.rsn == "3")


def _proof_listings(check) -> None:
    calls = []

    def fetch(url):
        calls.append(url)
        if url.endswith("=144"):
            return _listing(("813-005-0025", "335877"))
        return "<html><body><div class='errors'>Error retrieving chapter</div></body></html>"
    cat = {"chapters": [{"chapter": "813", "url": "https://x/displayChapterRules.action?selectedChapter=144"},
                        {"chapter": "999", "url": "https://x/displayChapterRules.action?selectedChapter=1"}]}
    ls = ChapterListings(cat, fetch)
    a = resolve(ls, "813-005-0025", "335876")
    b = resolve(ls, "813-005-0030", "1")
    check("one chapter is fetched once however many of its rules are resolved", len(calls) == 1)
    check("...and the amendment is found through it", a.state == AMENDED and a.rsn == "335877")
    check("a rule absent from a readable listing is NOT_LISTED", b.state == NOT_LISTED)
    try:
        resolve(ls, "999-001-0001", "7")
        check("an unreadable listing is refused, not read as 'repealed'", False)
    except ListingUnreadable:
        check("an unreadable listing is refused, not read as 'repealed'", True)
    try:
        resolve(ls, "555-001-0001", "7")
        check("a chapter the catalog does not know is refused", False)
    except ListingUnreadable:
        check("a chapter the catalog does not know is refused", True)


def _pinned_doc(rsn="335876", extra="") -> str:
    return ('---\nid: oar-813-005-0025\nsource_url: "https://secure.sos.state.or.us/oard/'
            f'viewSingleRule.action?ruleVrsnRsn={rsn}"\nsource_sha256: "{"0" * 64}"\n'
            f'upstream_tracking: manifest\n{extra}---\n\nbody\n')


def _proof_documents_and_manifest(check) -> None:
    check("a pinned document's rsn is read from its source_url", pinned_rsn(_pinned_doc()) == "335876")
    check("an unpinned document has none", pinned_rsn(
        '---\nsource_url: "https://secure.sos.state.or.us/oard/view.action?ruleNumber=1-1-1"\n---\n') is None)
    marked = mark_text(_pinned_doc(), True)
    check("marking records the mechanism and that the listing carries the number",
          'current_version_via: "chapter-listing"\ncurrent_version_listed: true\n' in marked)
    check("...idempotently", mark_text(marked, True) == marked)
    check("...and flips to false when the listing no longer carries it",
          "current_version_listed: false" in mark_text(marked, False)
          and mark_text(marked, False).count("current_version_via") == 1)
    check("an unmarked pinned document is refused by the offline check",
          check_documents({"813-005-0025": _pinned_doc()}, {}) != [])
    check("...a marked one passes", not check_documents({"813-005-0025": marked}, {}))
    check("...a claim on an unpinned document is refused", check_documents(
        {"1-1-1": "---\nid: oar-1-1-1\ncurrent_version_via: chapter-listing\n---\n"}, {}) != [])
    check("...a pinned document watched at the soft-404 url is refused", check_documents(
        {"813-005-0025": marked}, {"oar-813-005-0025": OARD + "/view.action?ruleNumber=813-005-0025"}) != [])
    man = {"sources": [{"id": "oar-813-005-0025", "url": version_url("335876"), "sha256": "a" * 64},
                       {"id": "oar-813-005-0030", "url": version_url("196419"), "sha256": "b" * 64}]}
    res = {"813-005-0025": Resolution("813-005-0025", "335876", "335877", AMENDED),
           "813-005-0030": Resolution("813-005-0030", "196419", "196419", CURRENT)}
    moved = sync_manifest(man, res)
    check("the manifest entry of an amended document moves to the new record, sha untouched",
          moved == ["oar-813-005-0025"] and man["sources"][0]["url"].endswith("=335877")
          and man["sources"][0]["sha256"] == "a" * 64)
    check("...and one whose record is still current does not move",
          man["sources"][1]["url"].endswith("=196419"))
    listings = ChapterListings(
        {"chapters": [{"chapter": "813", "url": "https://x/c?selectedChapter=144"}]},
        lambda u: _listing(("813-005-0025", "335877"), ("813-005-0030", "196419")))
    check("THE FETCH CHANGES WITH THE LISTING: a new rsn is the page refreshed",
          refresh_url("813-005-0025", "335876", listings).endswith("ruleVrsnRsn=335877"))
    check("...and a number the listing still names at the pinned rsn fetches the pinned page",
          refresh_url("813-005-0030", "196419", listings).endswith("ruleVrsnRsn=196419"))
    check("...and a number it does not carry fetches the pinned last-in-force record",
          refresh_url("813-005-0020", "333874", listings).endswith("ruleVrsnRsn=333874"))
    check("...and with no resolver at all, the pinned record",
          refresh_url("813-005-0025", "335876", None).endswith("ruleVrsnRsn=335876"))


def selftest() -> int:
    check = Checks()
    _proof_parse_listing(check)
    _proof_resolve(check)
    _proof_listings(check)
    _proof_documents_and_manifest(check)
    return check.report()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for f in ("resolve", "mark", "sync-manifest", "check", "selftest"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.check:
        return cmd_check()
    if a.mark:
        return cmd_mark()
    if a.sync_manifest:
        return cmd_sync_manifest()
    return cmd_resolve()


if __name__ == "__main__":
    raise SystemExit(main())
