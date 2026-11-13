#!/usr/bin/env python3
"""One-off backfill for the two snapshot_slice() boundaries fixed in repo_lib.py: a repealed or
renumbered section's bracket stub ('171.020 [Repealed by ...]') ends the section before it
(#446), and the chapter page's closing rule of underscores is not section text (#449).

Re-slices only the statutes that `check_ors_section_bounds.py` flags, with the fixed
snapshot_slice(), and replaces only the '## Full text' block, and only where the new text is
a STRICT PREFIX of the old one (the overrun trimmed, nothing else). A flagged document whose
new slice is not a prefix of its old text is printed and left alone; it needs a human look.
Title, frontmatter, ids and provenance are untouched. Reads cached
_meta/snapshots/ors-chapter-*.txt only: no network.

  python3 src/backfill_ors_section_bounds.py            # apply
  python3 src/backfill_ors_section_bounds.py --check    # report only; exit 1 if any would change
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from check_ors_section_bounds import FT_RE, findings  # noqa: E402
from ingest_lib import flow_to_lines  # noqa: E402
from repo_lib import REPO_ROOT, snapshot_slice  # noqa: E402

FT_BLOCK_RE = re.compile(r"(## Full text\n\n)(.*?)(\n\n## Provenance)", re.S)


def main():
    check = "--check" in sys.argv
    paths = sorted((REPO_ROOT / "statutes").glob("ors-*.md"))
    ids = {p.stem[4:].upper() for p in paths}
    cache, changed, unsafe, unreadable = {}, 0, [], []
    for p in paths:
        text = p.read_text(encoding="utf-8")
        m = FT_BLOCK_RE.search(text)
        snap = re.search(r"snapshot_id: (ors-chapter-\S+)", text)
        if not m or not snap:
            unreadable.append(p.name)
            continue
        if not findings(p.stem, m.group(2), ids):
            continue
        sid = snap.group(1)
        if sid not in cache:
            f = REPO_ROOT / "_meta/snapshots" / f"{sid}.txt"
            cache[sid] = f.read_text(encoding="utf-8", errors="replace") if f.exists() else None
        if cache[sid] is None:
            unreadable.append(p.name)
            continue
        new_ft = flow_to_lines(snapshot_slice(p.stem, sid, cache[sid]))
        old_ft = m.group(2)
        if not new_ft or new_ft == old_ft or not old_ft.startswith(new_ft.rstrip()):
            unsafe.append(p.name)
            continue
        changed += 1
        if not check:
            p.write_text(text[:m.start(2)] + new_ft + text[m.end(2):], encoding="utf-8")
    for n in unsafe[:25]:
        print(f"SKIP  statutes/{n}: the new slice is not a strict prefix of the old text "
              "-- needs a human look")
    for n in unreadable[:25]:
        print(f"UNREADABLE statutes/{n}: could not be re-sliced; not changed")
    print(("would change" if check else "patched") + f": {changed}; unsafe: {len(unsafe)}; "
          f"unreadable: {len(unreadable)}")
    if check and (changed or unsafe or unreadable):
        sys.exit(1)


if __name__ == "__main__":
    main()
