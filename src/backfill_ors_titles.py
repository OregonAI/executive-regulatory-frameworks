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
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from catalog_ors import CATALOG, parse_toc
from repo_lib import REPO_ROOT, Checks

SNAP = REPO_ROOT / "_meta/snapshots"


def patch_statute_file(path: Path, sec: str, ch: str, old_title: str, new_title: str):
    """Patches the SECTION title only -- the At-a-glance regex below matches whatever
    chapter-title text the file's own At-a-glance line already carries rather than assuming
    it agrees with the CURRENT catalog's chapter title (see the regex's own comment for why),
    so this function never needs a chapter title passed in at all."""
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
    # #348: matched on the CURRENT catalog's `ch_title` here, not on whatever chapter-title
    # text the file's own At-a-glance line already carries -- measured live, 1180 of 1429
    # already-ingested files being patched carry an OLDER chapter title in that line
    # (chapter titles have since been enriched in ors.yml with nothing re-syncing this
    # line when that happens, a separate drift from the section-title bug this module
    # exists to fix). Matching the SECTION-title portion only, and capturing whatever
    # chapter-title text is already there rather than assuming it agrees with `ch_title`,
    # is what lets this patch land regardless of that other, unrelated drift.
    # GREEDY capture, not `[^)]*`: a chapter title can itself hold parentheses ("Certain
    # Executive Branch Departments (incl. DAS)", chapter 184 -- measured live, 5 of the
    # 1429 files this backfill touches), and a non-greedy/exclude-close-paren capture stops
    # at the FIRST `)` (the inner one), leaving the outer `),` this pattern expects next
    # unmatched. Greedy `.*` backtracks to the LAST `),` on the line instead, which is the
    # real close -- the line never contains a second `),` after it (nothing legitimately
    # follows the chapter-title parenthetical but the edition/date text and a period).
    glance_re = re.compile(r'ORS ' + re.escape(sec) + r' — ' + re.escape(old_title)
                           + r'\. Chapter ' + re.escape(ch) + r' \((.*)\),')
    text, c = glance_re.subn(
        lambda m: f'ORS {sec} — {new_title}. Chapter {ch} ({m.group(1)}),', text, count=1)
    n += c
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
                    n = patch_statute_file(fpath, s["number"], ch, old_title, new_title)
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


# ------------------------------------------------------------------------------ selftest


def _fixture_file(tmpdir: Path, sec: str, old_title: str, file_chapter_title: str) -> Path:
    """A minimal statute file carrying `old_title` in all three occurrences
    `patch_statute_file` targets -- `file_chapter_title` is whatever chapter-title text the
    file's own committed At-a-glance line already carries, independent of what today's
    catalog says the chapter is called."""
    p = tmpdir / f"ors-{sec}.md"
    p.write_text(
        "---\n"
        f'title: "{old_title}"\n'
        "doc_type: statute\n"
        "---\n\n"
        f"# {old_title} (ORS {sec})\n\n"
        "## At a glance\n\n"
        f"ORS {sec} — {old_title}. Chapter 836 ({file_chapter_title}), 2025 Edition.\n\n"
        "## Full text\n\n"
        f"{sec} {old_title}. Text.\n",
        encoding="utf-8")
    return p


def _proof_patch_survives_a_stale_at_a_glance_chapter_title(check) -> None:
    """#348: measured live on the real corpus running the full 1443-row backfill --
    `patch_statute_file` used to build the At-a-glance line it searches for out of the
    CURRENT catalog chapter title (a `ch_title` parameter, since removed -- nothing reads it
    any more), but 1180 of 1429 already-ingested files being patched carry an OLDER chapter
    title in that line, unchanged since ingestion (chapter
    titles have since been enriched/corrected in `_meta/catalog/ors.yml`, and nothing
    re-syncs the At-a-glance line's chapter-title portion when that happens -- a different,
    pre-existing drift than the section-title bug this module exists to fix). The mismatch
    made the search string not found, so the At-a-glance line was silently left showing the
    stale section title while `title:` and the `#` heading were correctly patched --
    3 fields that are supposed to agree left disagreeing by this module's OWN patch, not by
    the pre-existing drift it found. `ors-836.080.md` is the real file this was first
    measured against."""
    tmpdir = Path(tempfile.mkdtemp(prefix="backfill-ors-titles-selftest-"))
    try:
        old_title = "Exemptions from ORS 836.085 to"
        new_title = "Exemptions from ORS 836.085 to 836.120"
        p = _fixture_file(tmpdir, "836.080", old_title, file_chapter_title="Chapter 836")
        n = patch_statute_file(p, "836.080", "836", old_title, new_title)
        text = p.read_text(encoding="utf-8")
        check("RED/GREEN: all three occurrences are patched despite the file's chapter "
              f"title disagreeing with today's catalog (got n={n})", n == 3)
        check("the title: frontmatter is patched", f'title: "{new_title}"' in text)
        check("the # heading is patched", f"# {new_title} (ORS 836.080)" in text)
        check("the At-a-glance line's SECTION title is patched",
              f"ORS 836.080 — {new_title}." in text)
        check("...and the At-a-glance line's own (stale) chapter title is left exactly as "
              "the file already had it -- fixing chapter-title drift is a separate concern "
              "(#397-adjacent), not this module's job",
              "Chapter 836 (Chapter 836)," in text)
    finally:
        shutil.rmtree(tmpdir)


def _proof_patch_survives_a_chapter_title_with_its_own_parentheses(check) -> None:
    """#348: measured live -- 5 of 1429 files patched carry a chapter title that itself
    holds parentheses (`ors-184.400.md`, chapter 184: "Certain Executive Branch Departments
    (incl. DAS)"). Against the PRE-FIX code (an exact string match embedding the CURRENT
    catalog's chapter title verbatim, via the now-removed `ch_title` parameter), this fails
    the SAME way the stale-chapter-title proof above does, and for the same reason -- the
    literal search string never appears in the file at all when its own chapter-title text
    differs from what was passed in, so `title:` and the `#` heading patch (n=2 of 3) but
    the At-a-glance line does not. It earns its own proof because the FIX has a distinct
    failure mode worth guarding separately: a capture that excludes `)` (`[^)]*`), one naive
    way to parse the line's own chapter title instead of assuming it agrees with the catalog,
    would stop at the FIRST close-paren -- the inner one -- leaving the real, outer `),`
    this pattern expects immediately after unmatched, and fail to match this file at all.
    The GREEDY `.*` this module actually uses (see `patch_statute_file`'s own comment)
    avoids that trap."""
    tmpdir = Path(tempfile.mkdtemp(prefix="backfill-ors-titles-selftest-"))
    try:
        old_title = "Definitions for ORS 184.400 to"
        new_title = "Definitions for ORS 184.400 to 184.408; rules"
        p = _fixture_file(tmpdir, "184.400", old_title,
                          file_chapter_title="Certain Executive Branch Departments (incl. DAS)")
        n = patch_statute_file(p, "184.400", "836", old_title, new_title)
        check(f"all three occurrences patch despite the chapter title's own parentheses "
              f"(got n={n})", n == 3)
        check("...and the embedded parenthetical inside the chapter title survives intact",
              "(Certain Executive Branch Departments (incl. DAS))," in p.read_text())
    finally:
        shutil.rmtree(tmpdir)


def _proof_patch_still_works_when_the_chapter_title_agrees(check) -> None:
    """The ordinary case, unaffected by the fix above: when the file's At-a-glance chapter
    title already agrees with what's passed in, all three occurrences still patch."""
    tmpdir = Path(tempfile.mkdtemp(prefix="backfill-ors-titles-selftest-"))
    try:
        old_title = "Definitions for ORS 1.010 to"
        new_title = "Definitions for ORS 1.010 to 1.020"
        p = _fixture_file(tmpdir, "1.010", old_title, file_chapter_title="Definitions")
        n = patch_statute_file(p, "1.010", "836", old_title, new_title)
        check("all three occurrences patch when the chapter title already agrees",
              n == 3)
    finally:
        shutil.rmtree(tmpdir)


def selftest() -> int:
    check = Checks()
    _proof_patch_survives_a_stale_at_a_glance_chapter_title(check)
    _proof_patch_survives_a_chapter_title_with_its_own_parentheses(check)
    _proof_patch_still_works_when_the_chapter_title_agrees(check)
    return check.report()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    main()
