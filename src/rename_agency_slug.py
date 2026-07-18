#!/usr/bin/env python3
"""Mechanically rename an agency's slug across the repo — the operations performed by
hand the first time DAS was renamed (2026-07-18), now scripted because registry churn
(a better source dataset, the state renaming an org) can recur.

  python3 src/rename_agency_slug.py <old-slug> <new-slug>

Renames, via `git mv` (history preserved):
  - agencies/<old>/                              -> agencies/<new>/
  - every moved .md file's `agency: <old>` line   -> `agency: <new>`
  - _meta/sources/<old>-*.yml   (group: field, listing_snapshot: path fixed)
  - _meta/catalog/<old>-*.yml   (embedded `path: agencies/<old>/...` fixed)
  - _meta/snapshots/<old>-*.json

Does NOT rename document ids/filenames/citations (e.g. das-107-004-052) -- those
transcribe the source's own citation text and are unrelated to the internal agency
slug. Does NOT fix prose links/examples outside the moved tree and renamed files
(README.md, AGENTS.md, templates, docstring examples, statute cross-references) --
those are few enough (a handful of files) to grep-and-fix by hand afterward; this
script prints a reminder grep at the end."""
import re
import subprocess
import sys
from pathlib import Path

from repo_lib import REPO_ROOT


def git_mv(src: Path, dst: Path):
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "mv", str(src), str(dst)], cwd=REPO_ROOT, check=True)
    return True


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    old, new = sys.argv[1], sys.argv[2]
    if old == new:
        sys.exit("old and new slugs are identical")

    moved = []

    old_dir = REPO_ROOT / "agencies" / old
    new_dir = REPO_ROOT / "agencies" / new
    if old_dir.is_dir():
        subprocess.run(["git", "mv", str(old_dir), str(new_dir)], cwd=REPO_ROOT, check=True)
        moved.append(f"agencies/{old}/ -> agencies/{new}/")
        agency_re = re.compile(rf"^agency: {re.escape(old)}$", re.M)
        n = 0
        for p in new_dir.rglob("*.md"):
            text = p.read_text()
            new_text = agency_re.sub(f"agency: {new}", text)
            if new_text != text:
                p.write_text(new_text)
                n += 1
        moved.append(f"agency: field updated in {n} file(s)")
    else:
        print(f"note: agencies/{old}/ does not exist, skipping directory move")

    # _meta/sources/<old>-*.yml and _meta/catalog/<old>-*.yml
    for base in ("_meta/sources", "_meta/catalog"):
        for p in sorted((REPO_ROOT / base).glob(f"{old}-*")):
            new_name = new + p.name[len(old):]
            dst = p.parent / new_name
            if git_mv(p, dst):
                text = dst.read_text()
                new_text = text.replace(f"group: {old}-", f"group: {new}-")
                new_text = new_text.replace(f"{old}-", f"{new}-")  # path/id refs sharing the prefix
                if new_text != text:
                    dst.write_text(new_text)
                moved.append(f"{p.relative_to(REPO_ROOT)} -> {dst.relative_to(REPO_ROOT)}")

    # _meta/snapshots/<old>-*.json referenced by listing_snapshot:
    for p in sorted((REPO_ROOT / "_meta/snapshots").glob(f"{old}-*")):
        new_name = new + p.name[len(old):]
        dst = p.parent / new_name
        if git_mv(p, dst):
            moved.append(f"{p.relative_to(REPO_ROOT)} -> {dst.relative_to(REPO_ROOT)}")

    # fix listing_snapshot:/path: references inside the renamed group+catalog files
    # to the renamed snapshot filename (second pass, after both renames landed)
    for base in ("_meta/sources", "_meta/catalog"):
        for p in sorted((REPO_ROOT / base).glob(f"{new}-*")):
            text = p.read_text()
            new_text = text.replace(f"snapshots/{old}-", f"snapshots/{new}-") \
                            .replace(f"agencies/{old}/", f"agencies/{new}/")
            if new_text != text:
                p.write_text(new_text)

    for m in moved:
        print(m)
    if not moved:
        print("nothing to rename")

    print(f"""
Remaining manual step: grep for prose links/examples that still name the old slug
(these are the handful of docs touched last time, not auto-fixed here):

  grep -rn "{old}" --include="*.md" --include="*.py" .

Then: python3 src/link_graph.py && python3 src/review_queue.py && \\
      python3 src/validate_frontmatter.py && python3 src/verify_provenance.py""")


if __name__ == "__main__":
    main()
