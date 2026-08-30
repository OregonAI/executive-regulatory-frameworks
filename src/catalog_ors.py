#!/usr/bin/env python3
"""Populate _meta/catalog/ors.yml with a new ORS chapter's table of contents
(Gate A input for corpus growth: run this, review the printed summary, THEN run
ingest_ors.py on the approved chapters). Idempotent -- safe to rerun.

  python3 src/catalog_ors.py 240 276 278 279A 279B 279C 282 283 292

Fetches the chapter HTML (same snapshot ingest_ors.py will reuse), locates the
table-of-contents span right after the "EDITION" marker (bounded by the first
prose marker: "(1)" or "means"), and extracts (section, catchline) pairs. Junk
entries (bare cross-references, repealed/renumbered stubs with no real catchline)
are dropped -- never fabricated, only parsed from what the source actually prints.
"""
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError

import yaml

from html_to_text import html_to_text
from ingest_lib import fetch
from repo_lib import REPO_ROOT, SNAPSHOT_DIR, ws_only, snapshot_text

CATALOG = REPO_ROOT / "_meta/catalog/ors.yml"

CHAPTER_TITLES = {
    "174": "Construction of Statutes; General Definitions",
    "176": "Governor",
    "177": "Secretary of State",
    "178": "State Treasurer",
    "179": "Administration of State Institutions",
    "180": "Attorney General; Department of Justice",
    "181A": "State Police; Public Safety Standards and Training",
    "182": "State Administrative Agencies Generally",
    "185": "Oregon Disabilities Commission; Commissions on Hispanic Affairs, Black Affairs, and Asian and Pacific Islander Affairs; Commission for Women",
    "240": "State Personnel Relations",
    "276": "Public Facilities",
    "278": "Insurance for Public Bodies",
    "279A": "Public Contracting - General Provisions",
    "279B": "Public Contracting - Public Procurements",
    "279C": "Public Contracting - Public Improvements",
    "282": "Public Printing",
    "283": "Interagency Services",
    "292": "Salaries and Expenses of State Officers and Employees",
}


# oregonlegislature.gov zero-pads the numeric part to three digits: ors025.html, not
# ors25.html (which 404s). Every chapter below 100 was silently unreachable until this
# was fixed, which is why 54 of them were missing from the catalog entirely.
def chapter_url(ch):
    m = re.fullmatch(r"(\d+)([A-Za-z]?)", str(ch))
    slug = f"{int(m.group(1)):03d}{m.group(2).lower()}" if m else str(ch).lower()
    return f"https://www.oregonlegislature.gov/bills_laws/ors/ors{slug}.html"


def fetch_chapter(ch):
    snap_id = f"ors-chapter-{ch.lower()}"
    html_path = SNAPSHOT_DIR / f"{snap_id}.html"
    if not html_path.exists():
        url = chapter_url(ch)
        time.sleep(1.0)  # bulk runs walk hundreds of chapters; don't hammer the source
        raw = fetch(url)
        html_path.write_bytes(raw)
        (SNAPSHOT_DIR / f"{snap_id}.txt").write_text(snapshot_text(raw), encoding="utf-8")
    return (SNAPSHOT_DIR / f"{snap_id}.txt").read_text(encoding="utf-8", errors="replace")


def extract_chapter_title(raw_text, ch):
    """Pull the chapter's real title from the source ("Chapter 305. Administration of
    Revenue and Tax Laws; Appeals ... 306. ...") so mass-catalogued chapters aren't all
    labeled "Chapter NNN". Returns None if the pattern isn't found.

    Two heading forms occur. The dominant one on the chapter pages themselves is an em
    dash ("Chapter 25 — Child Support Services 2025 EDITION"); only the period form was
    handled originally, which is why 371 of 433 catalogued chapters carry a bare label.
    The title runs until the edition banner or the first TOC section number."""
    t = ws_only(raw_text)
    # Some chapters carry a legislative-session notice between the heading and the edition
    # banner; without it as a terminator the notice is swallowed into the title.
    notice = (r"New sections of law|(?:ORS|Uncodified) sections (?:in this chapter|printed)|Note:"
              r"|TITLE\s+\d+|_{3,}")
    m = re.search(rf"Chapter\s+{re.escape(ch)}\s*[—–-]\s*(.+?)\s+"
                  rf"(?:\d{{4}}\s+EDITION|{notice}|\d{{1,3}}[A-Z]?\.\d{{3}}\b)", t)
    if not m:
        m = re.search(rf"Chapter\s+{re.escape(ch)}\.\s*(.+?)\s+\d{{2,3}}[A-Z]?\.\s", t)
    if not m:
        # Repealed/renumbered chapters print "Chapter 181 (Former Provisions) State Police;
        # ..." with the title running until the first all-caps part heading. Keeping the
        # marker in the title is the point: these are not current law.
        m = re.search(rf"Chapter\s+{re.escape(ch)}\s+\(Former Provisions\)\s+"
                      rf"(.+?)\s+(?=TITLE\s+\d+|[A-Z][A-Z ']{{7,}})", t)
        if m:
            return f"{m.group(1).strip(' .;')} (Former Provisions)"[:160]
    if not m:
        # A fourth heading form, with NO separator between the number and the title — the
        # edition banner sits between them instead: "Chapter 5 2025 EDITION County Courts
        # (Judicial Functions)". Both patterns above need a dash or a period after the
        # chapter number, so this one fell through to the bare "Chapter 5" label. The title
        # runs until the all-caps repeat of itself that heads the chapter body.
        m = re.search(rf"Chapter\s+{re.escape(ch)}\s+\d{{4}}\s+EDITION\s+"
                      rf"(.+?)\s+(?=TITLE\s+\d+|[A-Z][A-Z ']{{7,}})", t)
    if not m:
        return None
    title = m.group(1).strip(" .;")
    return title[:160] if len(title) >= 3 else None


# A cross-reference embedded in an earlier entry's own catchline ("'Agency' defined for
# ORS 283.140 and 283.143") contains section-number-looking substrings that would
# otherwise be mistaken for real TOC-entry boundaries below, truncating the entry that
# contains them and stealing/discarding the real entry those numbers actually belong to.
#
# #286: was `(?:\s+and\s+\d{3}[A-Z]?\.\d{3})*` -- covered only an "and"-joined LIST
# ("283.140 and 283.143"), not a "to"-joined RANGE ("691.405 to 691.485"), Oregon's other
# ordinary way of citing a span of sections, or a chain mixing both ("824.020 to 824.042,
# 824.050 to 824.110 and 824.200 to 824.256" -- one "ORS" governing three ranges joined by
# comma and "and"). The uncovered continuation reproduced this exact bug ONE TOKEN OVER
# from the case the comment above already understood: `691.485` matched, mistaken for the
# START of a new TOC entry, and stole the bare part heading trailing it ("BOARD") --
# or, worse, both fed to `TRAILING_HEADING_RE` (452.300 stole "VECTOR CONTROL DISTRICTS",
# then lost everything but "VECTOR" to that SECOND regex) -- while the section's own real
# entry, appearing later with the same number, was silently dropped as a duplicate
# (#286's two heading-fragment cases, `691.485`/`452.300`). The same gap also TRUNCATED
# an entry whose own catchline names its own range ("735.345 Violation of ORS 735.300 to
# 735.365" cut to "...to" at the false boundary; "824.200 Definitions for ORS 824.200 to
# 824.256" the same way) -- #286's other two parser-attributed rows. `,`/`and`/`to` cover
# every join word measured across every xref chain on the committed chapter snapshots.
XREF_RE = re.compile(
    r"\bORS\s+\d{3}[A-Z]?\.\d{3}(?:\s*(?:,|and|to)\s*\d{3}[A-Z]?\.\d{3})*\b")
# A bare part/subpart heading ("TREATMENT OF PRISONERS") between two numbered TOC entries
# has no section number of its own, so it isn't a split boundary either — it trails onto
# the PRECEDING entry's catchline instead. Distinguished from real title text by being an
# all-caps multi-word run (ORS catchlines are Title Case); length-gated so a short acronym
# at the end of a real title ("...eligibility for TANF") isn't mistaken for one.
TRAILING_HEADING_RE = re.compile(r"\s+[A-Z][A-Z '\-]{7,}$")


def parse_toc(raw_text, ch):
    t = ws_only(raw_text)
    i = t.find("EDITION")
    if i < 0:
        return []
    start = i + len("EDITION")
    # Wide enough for any chapter's real TOC (the largest, ORS 656, has ~220 entries) --
    # the old fixed 30,000-char window plus a first-match-of-"(1)"/"means" boundary was too
    # small AND too fragile for large chapters: it broke whenever an early section's own
    # catchline happened to contain either phrase (e.g. ORS 656.010 "Treatment by spiritual
    # means"), silently truncating the TOC to a handful of entries. Instead, find every
    # real (non-cross-reference) section-number match in a wide window, and use match
    # DENSITY to find the boundary: the TOC is a dense run of "NUM catchline NUM catchline
    # ..." (each entry a few dozen characters), while body prose is not -- the first big
    # gap between consecutive matches marks the transition to body text.
    chunk = t[start:start + 600000]
    xref_spans = [m.span() for m in XREF_RE.finditer(chunk)]

    def real_boundary(m):
        return not any(a <= m.start() < b for a, b in xref_spans)

    # The UCC chapters (71-80) number sections with FOUR digits after the point --
    # 72.1010, not 72.101 -- so a hard \d{3}\b matched nothing and silently yielded an
    # empty TOC for every one of them. Case-insensitive because a lettered chapter is
    # printed uppercase in the text (86A.095) whatever case the caller passed.
    num_re = re.compile(re.escape(ch) + r"[A-Z]?\.\d{3,4}\b", re.I)
    all_matches = [m for m in num_re.finditer(chunk) if real_boundary(m)]
    if not all_matches:
        return []
    GAP = 600
    # #346: when the chapter's own genuinely LAST TOC entry is itself immediately
    # followed by a >600-char gap (no nearby xref keeps the density high past it --
    # ORS 221.928 is the one instance measured so far), `all_matches[cut]` here IS that
    # last entry, not a body reoccurrence, and excluding it from `bounds` below drops it
    # from the catalog entirely. NOT fixed here: the obvious fix -- only exclude
    # `all_matches[cut]` when its own number is already in an earlier bound, otherwise
    # advance `cut` past it -- was tried and measured (full 569-chapter regression) to
    # avoid every entry LOSS it targets, but it does so by handing that entry's own
    # `toc` slice everything up to the NEXT match instead of a bounded catchline, and on
    # 221.928 (and 3 similar cases elsewhere) that slice runs on into trailing chapter
    # furniture -- a heading, a temporary-provisions note -- producing a garbage-suffixed
    # title, which is a worse defect than the current silent drop. A real fix needs its
    # own end-of-entry boundary, not just a corrected `cut`; out of scope here, still
    # #346, decision documented in that issue's thread rather than repeated by the next
    # person who tries the same one-line patch.
    cut = len(all_matches) - 1
    for k in range(len(all_matches) - 1):
        if all_matches[k + 1].start() - all_matches[k].start() > GAP:
            cut = k
            break
    last = all_matches[cut]
    toc = chunk[:last.start()]

    bounds = [m.start() for m in all_matches[:cut]]
    parts = [toc[b:(bounds[i + 1] if i + 1 < len(bounds) else len(toc))]
             for i, b in enumerate(bounds)]
    out, seen = [], set()
    for p in parts:
        pm = re.match(r"(" + re.escape(ch) + r"\.\d{3,4})\s+(.*)", p.strip(), re.I)
        if not pm:
            continue
        num, rest = pm.groups()
        rest = re.split(r"\[", rest)[0].strip(" .")
        rest = TRAILING_HEADING_RE.sub("", rest).strip(" .")
        # a heavily-renumbered chapter (e.g. 279, split into 279A/B/C in 2003) often carries
        # a "repealed sections" summary elsewhere on the page listing old numbers with their
        # repeal year in a bracket ("279.435 [... repealed by ... in 1989]") -- these also
        # match the section-number pattern but aren't real TOC entries. A real catchline is
        # always capitalized; a lowercase-first fragment like "in 1989]" is this artifact.
        if num in seen or len(rest) < 3 or rest.lower() in ("to", "enacted in lieu of") \
                or not (rest[0].isupper() or rest[0] in "“‘\"'"):
            continue
        seen.add(num)
        out.append({"number": num, "title": rest[:160], "status": "not_ingested"})
    return out


def _selftest() -> int:
    """#286. `XREF_RE` widened to cover "to"-joined ranges and comma/"and"/"to" chains,
    not just an "and"-joined list -- proved against the actual committed chapter
    snapshots that produced the bug, the same reproduction #286 itself measured with,
    not a synthetic fixture. `python3 src/catalog_ors.py --selftest`."""
    from repo_lib import Checks
    ck = Checks()

    def secs(ch: str) -> dict:
        path = SNAPSHOT_DIR / f"ors-chapter-{ch.lower()}.txt"
        raw = path.read_text(encoding="utf-8", errors="replace")
        return {s["number"]: s["title"] for s in parse_toc(raw, ch)}

    # THE TWO HEADING-FRAGMENT CASES: an in-catchline "to" range's own tail number
    # ("...ORS 691.405 to 691.485") used to be an uncovered false TOC-entry boundary,
    # stealing a bare part heading ("BOARD") as 691.485's title while the real entry
    # later in the text was dropped as a `seen` duplicate.
    s691 = secs("691")
    ck("691.485 no longer captures the bare 'BOARD' heading fragment",
       s691.get("691.485") == "Board of Licensed Dietitians")
    s452 = secs("452")
    ck("452.300 no longer captures 'VECTOR' (TRAILING_HEADING_RE's own further bite "
       "into the stolen heading text)",
       s452.get("452.300") == "Oregon Health Authority vector control program")

    # THE TWO IN-CHAPTER XREF-TRUNCATION CASES: a section naming its OWN range in its
    # own catchline ("735.345 Violation of ORS 735.300 to 735.365; penalties") used to
    # be truncated at the false boundary the untracked "to" continuation created.
    s735 = secs("735")
    ck("735.345 is no longer truncated at the in-catchline 'to'",
       s735.get("735.345") == "Violation of ORS 735.300 to 735.365; penalties")
    s824 = secs("824")
    ck("824.200 is no longer truncated at the in-catchline 'to'",
       s824.get("824.200") == "Definitions for ORS 824.200 to 824.256")

    # A COLLATERAL CASUALTY OF THE SAME BUG, not named in #286's own list: the false
    # boundary a section's OWN self-referencing range created also shadowed the LATER,
    # genuinely separate entry sharing that same number (735.365 itself, "Short
    # title") via the `seen` dedup -- fixed by the same regex change, not a second fix.
    ck("735.365 (the range's own endpoint, a separate real entry) is no longer "
       "shadowed by the false boundary inside 735.345's catchline",
       s735.get("735.365") == "Short title")

    # THE ORIGINAL "and"-ONLY CASE THIS REGEX ALREADY COVERED MUST KEEP WORKING: an
    # "and"-joined cross-reference embedded in an earlier entry's own catchline
    # ("283.130 'Agency' defined for ORS 283.140 and 283.143") must still not be
    # mistaken for a real TOC-entry boundary -- 283.140 and 283.143 must each keep
    # their OWN separate, correct titles, not 283.130's leftover text.
    s283 = secs("283")
    ck("283.130 keeps its own full catchline, not truncated at the embedded xref",
       s283.get("283.130") == "“Agency” defined for ORS 283.140 and 283.143")
    ck("283.140 (the xref's first target) keeps its own real title",
       s283.get("283.140") == "Telephone and telecommunications, mail, shuttle bus "
       "and messenger services; recovery of costs; rules")
    ck("283.143 (the xref's second target) keeps its own real title",
       s283.get("283.143") == "Surcharge for telecommunications services; purpose; "
       "exempt agencies")

    return ck.report("catalog-ors selftest")


def main():
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    # ORS prints a lettered chapter uppercase (86A, 657B) and the catalog follows suit;
    # accept either case from the caller so "86a" doesn't create a duplicate entry.
    chapters = [c.upper() for c in sys.argv[1:]]
    if not chapters:
        print("usage: catalog_ors.py <chapter> [<chapter> ...]")
        sys.exit(2)
    cat = yaml.safe_load(CATALOG.read_text())
    by_num = {c["chapter"]: c for c in cat["chapters"]}

    def save():
        cat["chapters"].sort(key=lambda c: c["chapter"])
        CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))

    missing = []
    for n, ch in enumerate(chapters, 1):
        # Not every chapter number is a live page: repealed chapters are simply absent from
        # the site. A bulk run must survive that -- previously one 404 aborted the loop and,
        # because the catalog was only written at the end, discarded every chapter before it.
        try:
            raw = fetch_chapter(ch)
        except HTTPError as e:
            if e.code == 404:
                missing.append(ch)
                print(f"chapter {ch}: no page at {chapter_url(ch)} (HTTP 404) -- skipped")
                continue
            raise
        secs = parse_toc(raw, ch)
        # Prefer the curated title, then the one printed in the source, then a bare label.
        title = CHAPTER_TITLES.get(ch) or extract_chapter_title(raw, ch) or f"Chapter {ch}"
        existing = by_num.get(ch)
        if existing:
            have = {s["number"]: s for s in existing["sections"]}
            for s in secs:
                if s["number"] not in have:
                    existing["sections"].append(s)
            existing["sections"].sort(key=lambda s: s["number"])
            if existing.get("title", "").startswith("Chapter ") and not title.startswith("Chapter "):
                existing["title"] = title  # upgrade a bare label if we now have a real one
        else:
            entry = {"chapter": ch, "title": title, "url": chapter_url(ch), "sections": secs}
            cat["chapters"].append(entry)
            by_num[ch] = entry
        print(f"chapter {ch} ({title}): {len(secs)} sections found")
        if n % 10 == 0:
            save()  # checkpoint, so an interrupted bulk run keeps what it already parsed

    save()
    if missing:
        print(f"\n{len(missing)} chapter(s) have no page on the site: {' '.join(missing)}")


if __name__ == "__main__":
    main()
