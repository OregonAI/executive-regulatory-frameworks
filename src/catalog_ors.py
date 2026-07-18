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
from pathlib import Path

import yaml

from html_to_text import html_to_text
from ingest_lib import fetch
from repo_lib import REPO_ROOT, SNAPSHOT_DIR, ws_only

CATALOG = REPO_ROOT / "_meta/catalog/ors.yml"

CHAPTER_TITLES = {
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


def fetch_chapter(ch):
    snap_id = f"ors-chapter-{ch.lower()}"
    html_path = SNAPSHOT_DIR / f"{snap_id}.html"
    if not html_path.exists():
        url = f"https://www.oregonlegislature.gov/bills_laws/ors/ors{ch}.html"
        raw = fetch(url)
        html_path.write_bytes(raw)
        (SNAPSHOT_DIR / f"{snap_id}.txt").write_text(html_to_text(raw), encoding="utf-8")
    return (SNAPSHOT_DIR / f"{snap_id}.txt").read_text(encoding="utf-8", errors="replace")


def parse_toc(raw_text, ch):
    t = ws_only(raw_text)
    i = t.find("EDITION")
    if i < 0:
        return []
    start = i + len("EDITION")
    chunk = t[start:start + 30000]
    m = re.search(r" \(1\) | means ", chunk[300:])
    end = 300 + m.start() if m else len(chunk)
    seg = chunk[:end]
    nums = list(re.finditer(re.escape(ch) + r"[A-Z]?\.\d{3}\b", seg))
    if not nums:
        return []
    last = nums[-1]
    toc = seg[:last.start()]

    parts = re.split(r"(?=\b" + re.escape(ch) + r"\.\d{3}\b)", toc)
    out, seen = [], set()
    for p in parts:
        pm = re.match(r"(" + re.escape(ch) + r"\.\d{3})\s+(.*)", p.strip())
        if not pm:
            continue
        num, rest = pm.groups()
        rest = re.split(r"\[", rest)[0].strip(" .")
        if num in seen or len(rest) < 3 or rest.lower() in ("to", "enacted in lieu of"):
            continue
        seen.add(num)
        out.append({"number": num, "title": rest[:160], "status": "not_ingested"})
    return out


def main():
    chapters = sys.argv[1:]
    if not chapters:
        print("usage: catalog_ors.py <chapter> [<chapter> ...]")
        sys.exit(2)
    cat = yaml.safe_load(CATALOG.read_text())
    by_num = {c["chapter"]: c for c in cat["chapters"]}

    for ch in chapters:
        raw = fetch_chapter(ch)
        secs = parse_toc(raw, ch)
        existing = by_num.get(ch)
        if existing:
            have = {s["number"]: s for s in existing["sections"]}
            for s in secs:
                if s["number"] not in have:
                    existing["sections"].append(s)
            existing["sections"].sort(key=lambda s: s["number"])
        else:
            entry = {"chapter": ch, "title": CHAPTER_TITLES.get(ch, f"Chapter {ch}"),
                     "url": f"https://www.oregonlegislature.gov/bills_laws/ors/ors{ch}.html",
                     "sections": secs}
            cat["chapters"].append(entry)
            by_num[ch] = entry
        print(f"chapter {ch} ({CHAPTER_TITLES.get(ch, '?')}): {len(secs)} sections found")

    cat["chapters"].sort(key=lambda c: c["chapter"])
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))


if __name__ == "__main__":
    main()
