#!/usr/bin/env python3
"""Re-evaluate every committed executive-order effective_date against its snapshot.

The companion to backfill_eo_signed_dates.py, which only ever fills a NULL. This one
runs the other direction: it re-parses each order that ALREADY carries a date and
clears the ones the current parser no longer trusts.

Why it exists. parse_signed_date's day regex used to absorb whatever glyphs sat between
the day digits and the word "day", on the assumption they were an ordinal suffix
("29'th", "20%"). OCR also renders digits as letters, so "3I day of October" — 31 with
the 1 misread as I — was stored as the 3rd. The id-year cross-check validates only the
YEAR, so it agreed with every one of these. Roughly 6-10 orders are affected.

A cleared date is not a loss of information: the date was never readable from the
document in the first place, and null is the honest record of that. Restoring it needs
a human with the source PDF, which is what REVIEW.md's queue is for.

  python3 src/recheck_eo_signed_dates.py            # report what would change
  python3 src/recheck_eo_signed_dates.py --apply    # clear untrusted dates
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ingest_eo import parse_signed_date
from repo_lib import REPO_ROOT, SNAPSHOT_DIR, normalize_ws

EO_DIR = REPO_ROOT / "executive-orders"
DATE_RE = re.compile(r'^effective_date:\s*"?(\d{4}-\d{2}-\d{2})"?\s*$', re.M)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write changes (default: report)")
    args = ap.parse_args()

    cleared = kept = no_snapshot = 0
    changes = []
    for md in sorted(EO_DIR.glob("eo-*.md")):
        raw = md.read_text(encoding="utf-8")
        m = DATE_RE.search(raw)
        if not m:
            continue
        snap = SNAPSHOT_DIR / f"{md.stem}.txt"
        if not snap.is_file():
            # Hash-only order with no committed extraction: nothing to re-derive the
            # date from, so leave whatever is recorded alone rather than guess.
            no_snapshot += 1
            continue
        reparsed = parse_signed_date(
            normalize_ws(snap.read_text(encoding="utf-8", errors="replace")), md.stem)
        if reparsed == m.group(1):
            kept += 1
            continue
        changes.append((md.stem, m.group(1), reparsed))
        if args.apply:
            # A re-parse can in principle land on a DIFFERENT readable date rather than
            # nothing; write what the parser actually derived instead of assuming null.
            new = f'effective_date: "{reparsed}"' if reparsed else "effective_date: null"
            md.write_text(DATE_RE.sub(new, raw, count=1), encoding="utf-8")
        cleared += 1

    for oid, was, now in changes:
        print(f"{oid:18s} {was} -> {now or 'null'}")
    print(f"\n{kept} unchanged, {cleared} cleared, {no_snapshot} skipped (no committed snapshot)")
    if changes and not args.apply:
        print("report only — pass --apply to write")


if __name__ == "__main__":
    main()
