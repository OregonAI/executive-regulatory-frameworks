#!/usr/bin/env python3
"""One-off backfill for the snapshot_slice() bug fixed in repo_lib.py: a bare part/subpart
heading with no section number of its own ("TREATMENT OF PRISONERS") sitting between two
numbered ORS sections in the chapter snapshot wasn't recognized as a slice boundary, so it
bled onto the end of the PRECEDING section's '## Full text' body (right after that section's
closing citation bracket).

Re-slices every already-ingested statute whose Full text ends in a bare all-caps run with
the fixed snapshot_slice(), and where the new slice is a genuine truncation of the old one
(same content, just without the bled heading — the safety check below), replaces only the
'## Full text' block in place. Reads only already-cached _meta/snapshots/ors-chapter-*.txt —
no network calls. Title, frontmatter, and provenance are untouched (already handled by
backfill_ors_titles.py for the corresponding title-bleed cases).

  python3 src/backfill_ors_fulltext_bleed.py            # apply
  python3 src/backfill_ors_fulltext_bleed.py --check    # report only, exit 1 if any diff
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ingest_lib import flow_to_lines
from repo_lib import REPO_ROOT, content_files, snapshot_slice

BLEED_RE = re.compile(r"\] [A-Z][A-Z '\-]{7,}\s*$")
FT_BLOCK_RE = re.compile(r"(## Full text\n\n)(.*?)(\n\n## Provenance)", re.S)


def main():
    check = "--check" in sys.argv
    candidates = [p for p in content_files() if p.stem.startswith("ors-")
                  and p.parent.name == "statutes"]

    n_diff = n_patched = n_skipped_unsafe = 0
    for p in candidates:
        text = p.read_text(encoding="utf-8")
        m = FT_BLOCK_RE.search(text)
        if not m or not BLEED_RE.search(m.group(2)):
            continue
        old_ft = m.group(2)
        sec = p.stem.replace("ors-", "").upper()
        snap_m = re.search(r"snapshot_id: (ors-chapter-\S+)", text)
        if not snap_m:
            continue
        snap = REPO_ROOT / "_meta/snapshots" / f"{snap_m.group(1)}.txt"
        if not snap.exists():
            continue
        raw = snap.read_text(encoding="utf-8", errors="replace")
        sl = snapshot_slice(p.stem, snap_m.group(1), raw)
        if not sl:
            continue
        new_ft = flow_to_lines(sl)
        if new_ft == old_ft:
            continue
        n_diff += 1
        # safety: only apply if the new text is what you get by trimming the OLD text at
        # its own bracket boundary — i.e. this is strictly removing the bled heading, not
        # picking up any different content.
        old_trimmed = BLEED_RE.sub("]", old_ft)
        if new_ft != old_trimmed:
            n_skipped_unsafe += 1
            print(f"SKIP  {p.relative_to(REPO_ROOT)}: new slice isn't a clean bracket-"
                  "truncation of the old one — needs a human look")
            continue
        if check:
            print(f"DIFF  {p.relative_to(REPO_ROOT)}")
            continue
        text = text[:m.start(2)] + new_ft + text[m.end(2):]
        p.write_text(text, encoding="utf-8")
        n_patched += 1

    if check:
        if n_diff:
            print(f"FAILED: {n_diff} statute(s) have a bled Full text section "
                  f"({n_skipped_unsafe} unsafe to auto-fix) — run: "
                  "python3 src/backfill_ors_fulltext_bleed.py")
            sys.exit(1)
        print("OK: no bled Full text sections found.")
        return
    print(f"patched {n_patched} of {n_diff} affected statute file(s)"
          + (f" ({n_skipped_unsafe} left for manual review)" if n_skipped_unsafe else ""))


if __name__ == "__main__":
    main()
