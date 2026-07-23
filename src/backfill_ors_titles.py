#!/usr/bin/env python3
"""One-off backfill for the parse_toc() TOC-splitting bug fixed in catalog_ors.py: a
cross-reference embedded in an earlier section's own catchline ("'Agency' defined for ORS
283.140 and 283.143") was mistaken for a real TOC-entry boundary, truncating that entry's
own title and, via the `seen` dedup, silently discarding the real title of the section the
cross-reference numbers point to (see ors-283.140, ors-283.130 before this backfill).

Re-parses every already-cached ORS chapter snapshot with the fixed parser, and for every
section whose title comes out different: updates _meta/catalog/ors.yml, and if the section
has already been ingested (statutes/ors-*.md exists), patches that file's `title:`
frontmatter, its `# {title} (ORS {sec})` heading, and its "At a glance" line in place. Reads
only already-cached _meta/snapshots/ors-chapter-*.txt — no network calls. Everything else in
each patched file (full text, citations, dates, verified_by, etc.) is left untouched.

  python3 src/backfill_ors_titles.py            # apply
  python3 src/backfill_ors_titles.py --check    # report only, no writes; exit 1 if any diff
"""
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from catalog_ors import CATALOG, parse_toc
from repo_lib import REPO_ROOT

SNAP = REPO_ROOT / "_meta/snapshots"


def patch_statute_file(path: Path, sec: str, ch: str, ch_title: str, old_title: str, new_title: str):
    text = path.read_text(encoding="utf-8")
    old_q = old_title.replace('"', "'")
    new_q = new_title.replace('"', "'")
    n = 0
    text, c = re.subn(r'^title: ' + re.escape(f'"{old_q}"') + r'\s*$',
                      f'title: "{new_q}"', text, count=1, flags=re.M)
    n += c
    text, c = text.replace(f"# {old_title} (ORS {sec})", f"# {new_title} (ORS {sec})"), \
        (f"# {old_title} (ORS {sec})" in text)
    n += int(c)
    old_glance = f"ORS {sec} — {old_title}. Chapter {ch} ({ch_title}),"
    new_glance = f"ORS {sec} — {new_title}. Chapter {ch} ({ch_title}),"
    text, c = text.replace(old_glance, new_glance), (old_glance in text)
    n += int(c)
    if n:
        path.write_text(text, encoding="utf-8")
    return n


def main():
    check = "--check" in sys.argv
    cat = yaml.safe_load(CATALOG.read_text())

    n_chapters = n_section_diffs = n_files_patched = n_incomplete = 0
    for c in cat["chapters"]:
        ch = c["chapter"]
        snap = SNAP / f"ors-chapter-{ch.lower()}.txt"
        if not snap.exists():
            continue
        raw = snap.read_text(encoding="utf-8", errors="replace")
        new_by_num = {s["number"]: s["title"] for s in parse_toc(raw, ch)}
        if not new_by_num:
            continue
        touched = False
        for s in c["sections"]:
            new_title = new_by_num.get(s["number"])
            if not new_title or new_title == s["title"]:
                continue
            n_section_diffs += 1
            old_title = s["title"]
            if check:
                print(f"DIFF  ORS {s['number']}: {old_title!r} -> {new_title!r}")
                continue
            if s.get("status") == "ingested" and s.get("path"):
                fpath = REPO_ROOT / s["path"]
                if fpath.exists():
                    n = patch_statute_file(fpath, s["number"], ch, c["title"], old_title, new_title)
                    if n == 3:
                        n_files_patched += 1
                    else:
                        n_incomplete += 1
                        print(f"WARN  {s['path']}: only {n}/3 title occurrences matched "
                              f"(section {s['number']}) — left partially patched, check by hand")
            s["title"] = new_title
            touched = True
        if touched:
            n_chapters += 1

    if check:
        if n_section_diffs:
            print(f"FAILED: {n_section_diffs} section title(s) across catalog would change — "
                  "run: python3 src/backfill_ors_titles.py")
            sys.exit(1)
        print("OK: catalog section titles match the fixed parser.")
        return

    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    print(f"backfilled {n_section_diffs} section title(s) across {n_chapters} chapter(s) "
          f"in the catalog; patched {n_files_patched} already-ingested statute file(s)"
          + (f" ({n_incomplete} incomplete, see WARN lines above)" if n_incomplete else ""))


if __name__ == "__main__":
    main()
