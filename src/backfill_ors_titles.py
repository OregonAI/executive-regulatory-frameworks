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

REFUSES to touch a section number `backfill_ors_286_titles.FIXES` claims (#292's own code
review). This is unscoped and rerunnable, unlike that module — for two of its rows
(735.345, 824.200) `parse_toc()`'s TOC-derived text is a KNOWN-WRONG source (the section's
own catchline differs between the chapter's TOC and its body; `anchor_ok` and this
document's own `## Full text` are anchored to the body, not the TOC — see that module's
docstring for the measured evidence). Without this refusal, rerunning this tool after
`backfill_ors_286_titles.py` would silently overwrite those two hand-verified,
body-anchored titles with the TOC-derived one it was specifically NOT applied there
because it disagrees with the ground truth `anchor_ok` checks against — re-diverging a row
this repository already paid to get right.
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


def _protected_sections():
    """Section numbers a hand-verified backfill has already settled — never overwritten
    by this module's own bulk, TOC-derived re-parse. Imported lazily (not at module top)
    so the two modules' mutual `patch_statute_file`/`FIXES` dependency does not become a
    circular top-level import — by the time `main()` runs, both modules load cleanly
    either order."""
    from backfill_ors_286_titles import FIXES
    return set(FIXES)


def main():
    check = "--check" in sys.argv
    cat = yaml.safe_load(CATALOG.read_text())
    protected = _protected_sections()

    n_chapters = n_section_diffs = n_files_patched = n_incomplete = n_protected = 0
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
            if s["number"] in protected:
                n_protected += 1
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

    protected_note = (f" ({n_protected} protected row(s) skipped — see "
                      f"backfill_ors_286_titles.FIXES)" if n_protected else "")
    if check:
        if n_section_diffs:
            print(f"FAILED: {n_section_diffs} section title(s) across catalog would change — "
                  f"run: python3 src/backfill_ors_titles.py{protected_note}")
            sys.exit(1)
        print(f"OK: catalog section titles match the fixed parser.{protected_note}")
        return

    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    print(f"backfilled {n_section_diffs} section title(s) across {n_chapters} chapter(s) "
          f"in the catalog; patched {n_files_patched} already-ingested statute file(s)"
          + (f" ({n_incomplete} incomplete, see WARN lines above)" if n_incomplete else "")
          + protected_note)


if __name__ == "__main__":
    main()
