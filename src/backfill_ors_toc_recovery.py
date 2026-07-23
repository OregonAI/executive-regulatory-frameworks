#!/usr/bin/env python3
"""One-off backfill for the parse_toc() boundary-detection bug fixed in catalog_ors.py: the
old TOC-end heuristic (first " (1) "/" means " in a fixed 30,000-char window) broke on large
chapters whenever an early section's own catchline happened to contain either phrase (e.g.
ORS 656.010 "Treatment by spiritual means"), silently truncating the TOC to a handful of
entries — ORS 656 (workers' compensation) catalogued only 5 of its ~200 real sections. Fixed
with a match-density boundary instead (see catalog_ors.py). Also fixed a second issue found
while validating: heavily-renumbered chapters (e.g. 279, split into 279A/B/C in 2003) carry
a "repealed sections" summary elsewhere on the page that produced junk catalog entries like
{"number": "279.435", "title": "in 1989]"} — now filtered (a real catchline is capitalized).

For every already-cataloged chapter with a local snapshot: recomputes the TOC with the fixed
parser, adds newly-discovered sections (status not_ingested), removes now-invalid junk
entries (title matches the known garbage pattern AND the fixed parser no longer finds that
number), and updates titles for existing entries that changed — without touching the
status/path of anything already ingested. Then re-ingests every chapter with new
not_ingested entries via ingest_ors.py's own ingest_chapter() (reads only the already-cached
snapshot — no network calls, since every chapter here was already ingested at least once
before).

  python3 src/backfill_ors_toc_recovery.py            # apply (catalog + ingest)
  python3 src/backfill_ors_toc_recovery.py --check    # report scope only, no writes
"""
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from catalog_ors import CATALOG, parse_toc
from ingest_ors import ingest_chapter
from repo_lib import REPO_ROOT

SNAP = REPO_ROOT / "_meta/snapshots"
JUNK_TITLE_RE = re.compile(r"^in \d{4}\]?$")


def main():
    check = "--check" in sys.argv
    cat = yaml.safe_load(CATALOG.read_text())

    n_added = n_removed = n_retitled = 0
    chapters_to_ingest = []
    for c in cat["chapters"]:
        ch = c["chapter"]
        snap = SNAP / f"ors-chapter-{ch.lower()}.txt"
        if not snap.exists():
            continue
        raw = snap.read_text(encoding="utf-8", errors="replace")
        new_secs = {s["number"]: s["title"] for s in parse_toc(raw, ch)}
        if not new_secs:
            continue
        old_by_num = {s["number"]: s for s in c["sections"]}

        added = [n for n in new_secs if n not in old_by_num]
        removed = [n for n, s in old_by_num.items()
                   if n not in new_secs and JUNK_TITLE_RE.match(s["title"])]
        retitled = [n for n in new_secs if n in old_by_num and old_by_num[n]["title"] != new_secs[n]]

        if not (added or removed or retitled):
            continue
        n_added += len(added)
        n_removed += len(removed)
        n_retitled += len(retitled)
        if check:
            if added or removed:
                print(f"ORS {ch}: +{len(added)} new, -{len(removed)} junk removed, "
                      f"~{len(retitled)} retitled")
            continue

        new_sections = [s for s in c["sections"] if s["number"] not in removed]
        for n in retitled:
            for s in new_sections:
                if s["number"] == n:
                    s["title"] = new_secs[n]
        for n in added:
            new_sections.append({"number": n, "title": new_secs[n], "status": "not_ingested"})
        new_sections.sort(key=lambda s: s["number"])
        c["sections"] = new_sections
        if added:
            chapters_to_ingest.append(ch)

    if check:
        print(f"\nTOTAL: +{n_added} new sections, -{n_removed} junk entries removed, "
              f"~{n_retitled} retitled, across chapters needing changes")
        return

    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    print(f"catalog: +{n_added} new sections, -{n_removed} junk entries removed, "
          f"~{n_retitled} retitled")

    # re-ingest chapters with newly-discovered sections (from cached snapshots, no fetch)
    cat = yaml.safe_load(CATALOG.read_text())  # reload post-write for ingest_chapter to use
    by_num = {c["chapter"]: c for c in cat["chapters"]}
    made = skipped = 0
    for ch in chapters_to_ingest:
        m, s, k, sha, url = ingest_chapter(ch, by_num[ch])
        made += m
        skipped += s
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    print(f"ingested {made} new statute document(s) across {len(chapters_to_ingest)} "
          f"chapter(s) ({skipped} not sliceable)")


if __name__ == "__main__":
    main()
