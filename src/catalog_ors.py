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
from repo_lib import REPO_ROOT, SNAPSHOT_DIR, ws_only

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
        (SNAPSHOT_DIR / f"{snap_id}.txt").write_text(html_to_text(raw), encoding="utf-8")
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
XREF_RE = re.compile(r"\bORS\s+\d{3}[A-Z]?\.\d{3}(?:\s+and\s+\d{3}[A-Z]?\.\d{3})*\b")
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


def main():
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
