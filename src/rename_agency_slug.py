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

  - prose references to a renamed snapshot filename, inside the moved .md files
    (`_meta/snapshots/<old>-....json` -> `_meta/snapshots/<new>-....json`, e.g. the
    `## Provenance & change history` line's "Listed in the ... listing of record" link)

Does NOT rename document ids/filenames/citations (e.g. das-107-004-052) -- those
transcribe the source's own citation text and are unrelated to the internal agency
slug. Does NOT fix prose links/examples outside the moved tree and renamed files
(README.md, AGENTS.md, templates, docstring examples, statute cross-references) --
those are few enough (a handful of files) to grep-and-fix by hand afterward; this
script prints a reminder grep at the end.

#425: the first DAS rename (e71034a168) moved
`_meta/snapshots/das-policies-listing.json` to its new name but never touched the ~99
documents' own prose reference to the old filename -- the snapshot rename loop below
renamed the FILE, and a separate pass over every `agency:`-field document rewrote only
that one frontmatter line, so nothing ever walked the moved tree looking for a prose
citation of the OLD snapshot name. `rewrite_snapshot_prose()` closes that gap."""
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


def rewrite_snapshot_prose(text: str, renames: dict) -> str:
    """Rewrite every `_meta/snapshots/<old-name>` prose reference in `text` to
    `_meta/snapshots/<new-name>`, for each (old filename -> new filename) pair in
    `renames` (e.g. {"das-policies-listing.json":
    "department-of-administrative-services-policies-listing.json"}).

    This is the one place a renamed snapshot's prose citation (the provenance line's
    "Listed in the ... listing of record" link, not its frontmatter or the `agency:`
    field -- those are rewritten elsewhere) gets updated; #425 is this pass not
    existing at all."""
    for old_name, new_name in renames.items():
        text = text.replace(f"_meta/snapshots/{old_name}", f"_meta/snapshots/{new_name}")
    return text


def _selftest() -> int:
    """`rewrite_snapshot_prose()` in isolation, from strings only -- no git_mv, no disk
    writes outside this function's own locals. Proves the #425 gap is closed: a document
    citing a renamed snapshot's OLD name is rewritten to its new one."""
    fails = []
    renames = {"das-policies-listing.json":
               "department-of-administrative-services-policies-listing.json"}

    doc = ('- Listed in the DAS policies listing of record '
           '(`_meta/snapshots/das-policies-listing.json`), view "Facilities".\n')
    out = rewrite_snapshot_prose(doc, renames)
    if "_meta/snapshots/department-of-administrative-services-policies-listing.json" not in out:
        fails.append("FAIL a-renamed-snapshots-prose-citation-is-rewritten: "
                     f"new name not found in {out!r}")
    if "_meta/snapshots/das-policies-listing.json" in out:
        fails.append(f"FAIL the-old-snapshot-name-is-left-nowhere: still present in {out!r}")

    # A reference to an UNRELATED snapshot (not in `renames`) must be left alone -- this
    # function touches only the filenames it was told were renamed.
    unrelated = "- Snapshot: `_meta/snapshots/das-40-080-01.pdf` / `.txt`\n"
    unrelated_out = rewrite_snapshot_prose(unrelated, renames)
    if unrelated_out != unrelated:
        fails.append("FAIL an-unrelated-snapshot-reference-is-left-alone: "
                     f"{unrelated!r} became {unrelated_out!r}")

    # NO RENAMES declared is a no-op, not an error.
    if rewrite_snapshot_prose(doc, {}) != doc:
        fails.append("FAIL no-renames-is-a-no-op")

    for f in fails:
        print(f)
    if fails:
        print(f"{len(fails)} rule(s) did not hold")
        return 1
    print("rewrite_snapshot_prose(): a renamed snapshot's prose citation is rewritten, "
          "an unrelated one is left alone")
    return 0


def main():
    if "--selftest" in sys.argv:
        return _selftest()
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
    snapshot_renames = {}
    for p in sorted((REPO_ROOT / "_meta/snapshots").glob(f"{old}-*")):
        new_name = new + p.name[len(old):]
        dst = p.parent / new_name
        if git_mv(p, dst):
            snapshot_renames[p.name] = new_name
            moved.append(f"{p.relative_to(REPO_ROOT)} -> {dst.relative_to(REPO_ROOT)}")

    # #425: prose references to a renamed snapshot filename, inside the moved agency tree
    # (the provenance line's "Listed in the ... listing of record" link) -- the file itself
    # was just renamed above; this is the pass that was missing entirely the first time.
    if snapshot_renames and new_dir.is_dir():
        n = 0
        for p in new_dir.rglob("*.md"):
            text = p.read_text()
            new_text = rewrite_snapshot_prose(text, snapshot_renames)
            if new_text != text:
                p.write_text(new_text)
                n += 1
        moved.append(f"prose snapshot reference updated in {n} file(s)")

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
      corpus-validate-frontmatter --config _meta/corpus.yml && \\
      corpus-verify-provenance --config _meta/corpus.yml""")


if __name__ == "__main__":
    sys.exit(main())
