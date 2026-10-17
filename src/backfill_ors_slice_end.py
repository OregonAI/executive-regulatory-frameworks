#!/usr/bin/env python3
"""One-off backfill for the snapshot_slice() next-section terminator, which recognised only a
three-digit chapter number. In a chapter numbered below 100 (and 72A/74A, whose letter and
four-digit tails it also missed) a section's '## Full text' ran on past the end of the section
-- 24.330 carried all of 24.335, 24.260 carried 24.265 through 24.335 -- and, separately, a
terminator was taken at a CITED number ('ORS 195.300, 195.305 Foo'), cutting four sections
(93.040, 105.464, 243.144, 657.435) short.

Re-slices every statute with the fixed snapshot_slice() and replaces only the '## Full text'
block, and only where the old text and the new slice differ by a SECTION: the dropped tail
holds another section's heading, or the new slice extends a cut-short one. A Full text that
differs from the slice only by a trailing part heading is a different (older) defect and is
left to backfill_ors_fulltext_bleed.py. Title, frontmatter and provenance are untouched.
Reads cached _meta/snapshots/ors-chapter-*.txt only: no network.

  python3 src/backfill_ors_slice_end.py            # apply
  python3 src/backfill_ors_slice_end.py --check    # report only; exit 1 if any would change
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ingest_lib import flow_to_lines
from repo_lib import REPO_ROOT, content_files, snapshot_slice

FT_BLOCK_RE = re.compile(r"(## Full text\n\n)(.*?)(\n\n## Provenance)", re.S)
SECTION_RE = re.compile(r"\b\d{1,3}[A-Z]?\.\d{3,4} [A-Z“\"]")


def classify(old_ft: str, new_ft: str) -> str:
    """'' (no change), 'bled' (old = new + later sections), 'cut' (new extends old),
    'heading-only' (a trailing heading differs; not this defect), 'other'."""
    if new_ft == old_ft:
        return ""
    if old_ft.startswith(new_ft.rstrip()):
        return "bled" if SECTION_RE.search(old_ft[len(new_ft.rstrip()):]) else "heading-only"
    if new_ft.startswith(old_ft.rstrip()):
        return "cut"
    return "other"


def main():
    check = "--check" in sys.argv
    counts = {"bled": 0, "cut": 0, "heading-only": 0, "other": 0}
    cache = {}
    for p in content_files():
        if not (p.stem.startswith("ors-") and p.parent.name == "statutes"):
            continue
        text = p.read_text(encoding="utf-8")
        m = FT_BLOCK_RE.search(text)
        snap_m = re.search(r"snapshot_id: (ors-chapter-\S+)", text)
        if not m or not snap_m:
            continue
        sid = snap_m.group(1)
        if sid not in cache:
            f = REPO_ROOT / "_meta/snapshots" / f"{sid}.txt"
            cache[sid] = f.read_text(encoding="utf-8", errors="replace") if f.exists() else None
        if cache[sid] is None:
            continue
        sl = snapshot_slice(p.stem, sid, cache[sid])
        if not sl:
            continue
        new_ft = flow_to_lines(sl)
        kind = classify(m.group(2), new_ft)
        if not kind:
            continue
        counts[kind] += 1
        if kind == "other":
            print(f"SKIP  {p.relative_to(REPO_ROOT)}: neither a truncation nor an extension "
                  "of the old text -- needs a human look")
            continue
        if kind == "heading-only":
            continue
        if check:
            print(f"DIFF  {p.relative_to(REPO_ROOT)} ({kind})")
            continue
        p.write_text(text[:m.start(2)] + new_ft + text[m.end(2):], encoding="utf-8")
    msg = ", ".join(f"{k}={v}" for k, v in counts.items())
    if check:
        n = counts["bled"] + counts["cut"] + counts["other"]
        if n:
            print(f"FAILED: {n} statute(s) disagree with the section-end slice ({msg}) -- "
                  "run: python3 src/backfill_ors_slice_end.py")
            sys.exit(1)
        print(f"OK: every statute's Full text ends where its section ends ({msg}; "
              "heading-only differences are not this check's).")
        return
    print(f"patched: {msg}")


if __name__ == "__main__":
    main()
