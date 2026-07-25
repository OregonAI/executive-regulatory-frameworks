#!/usr/bin/env python3
"""One-off backfill for the parse_signed_date() bug fixed in ingest_eo.py.

The old pattern required the literal phrase "Dated this Nth day of Month, Year". Oregon
has never used it — every order signs off "Done at Salem, Oregon this Nth day of Month,
Year" (or a word-order variant). The phrase "Dated this" appears in ZERO of the 499
committed order snapshots, so parse_signed_date() never matched anything and all 526
executive orders carry `effective_date: null`.

Nothing needs re-fetching or re-OCRing: the dates are already sitting in the committed
_meta/snapshots/eo-*.txt extractions. This re-parses those with the corrected function
and writes the recovered date into each order's `effective_date` frontmatter field.

Safety: parse_signed_date(text, order_id) rejects any date whose year contradicts the
year encoded in the order id (eo-YY-NN is signed in 20YY, or rarely that December of
20YY-1). On the current corpus that cross-check passes for 100% of parsed dates. Orders
whose signature block is too garbled to read are left null — an unreadable date stays
unrecorded rather than being guessed.

Only `effective_date` is touched; nothing else in any file changes, and files that
already carry a date are skipped.

  python3 src/backfill_eo_signed_dates.py            # apply
  python3 src/backfill_eo_signed_dates.py --check    # report only; exit 1 if any pending
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ingest_eo import SNAPSHOT_DIR, parse_signed_date
from repo_lib import REPO_ROOT, normalize_ws

EO_DIR = REPO_ROOT / "executive-orders"
# Only ever rewrite a null/empty effective_date — never overwrite a recorded one.
NULL_DATE_RE = re.compile(r"^effective_date:[ \t]*(null|~|)[ \t]*$", re.M)


def recoverable():
    """(path, order_id, iso_date) for every order whose date is null but readable."""
    out = []
    for md in sorted(EO_DIR.glob("eo-*.md")):
        if md.name.startswith("_"):
            continue
        text = md.read_text(encoding="utf-8")
        if not NULL_DATE_RE.search(text):
            continue                                    # already has a date
        snap = SNAPSHOT_DIR / f"{md.stem}.txt"
        if not snap.is_file():
            continue                                    # no committed extraction to read
        date = parse_signed_date(
            normalize_ws(snap.read_text(encoding="utf-8", errors="replace")), md.stem)
        if date:
            out.append((md, md.stem, date))
    return out


def main():
    check = "--check" in sys.argv
    todo = recoverable()
    total = len([p for p in EO_DIR.glob("eo-*.md") if not p.name.startswith("_")])

    if check:
        if todo:
            print(f"{len(todo)} of {total} executive orders have a recoverable "
                  f"effective_date not yet written — run: "
                  f"python3 src/backfill_eo_signed_dates.py")
            for md, oid, date in todo[:10]:
                print(f"  {oid}: {date}")
            if len(todo) > 10:
                print(f"  … and {len(todo) - 10} more")
            sys.exit(1)
        print("all recoverable executive-order signed dates are recorded.")
        return

    for md, oid, date in todo:
        text = md.read_text(encoding="utf-8")
        patched, n = NULL_DATE_RE.subn(f'effective_date: "{date}"', text, count=1)
        if n:
            md.write_text(patched, encoding="utf-8")
    still_null = total - len(todo) - sum(
        1 for p in EO_DIR.glob("eo-*.md")
        if not p.name.startswith("_") and not NULL_DATE_RE.search(p.read_text(encoding="utf-8")))
    print(f"backfilled {len(todo)} of {total} executive orders with their signed date; "
          f"the rest have no readable date block in their committed extraction.")


if __name__ == "__main__":
    main()
