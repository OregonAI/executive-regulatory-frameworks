#!/usr/bin/env python3
"""Verifies a statute document's own three title positions agree with its catalog row.

  python3 src/statute_title_agreement.py --check      every ingested ORS statute document
  python3 src/statute_title_agreement.py --selftest   every rule, watched failing

WHY THIS EXISTS (#398). `backfill_ors_titles.py --check` compares the CATALOG's title
against a FRESH RE-PARSE of the cached chapter snapshot -- it never reads the FILES that
were supposedly patched from an earlier catalog title. Four statute documents drifted
undetected for exactly that reason: `patch_statute_file()` correctly matched 0 of its 3
targets (the file's committed title was the single word "and" -- a TOC line-wrap or
list-continuation artifact from whatever produced the frontmatter at ingestion, not the
catalog's `old_title`) and correctly left the files untouched rather than guess, printing a
WARN that scrolled past in ingestion output. Nothing ever re-checked the FILES against the
catalog afterwards, so the documents sat wrong -- `title: "and"`, `# and (ORS ...)`, `ORS
... -- and.` -- with every other gate green.

This module reads the committed catalog and the committed statute files ONLY -- no network,
no re-parse of the source snapshot (that is `backfill_ors_titles.py`'s job, and this module
does not duplicate it). It answers a narrower, different question: does each already-
ingested document agree with ITS OWN catalog row, in the three positions a reader -- and
every downstream generated view -- actually sees: the frontmatter `title:`, the `#`
heading, and the At-a-glance line's section-title clause.

THREE OUTCOMES PER POSITION, never collapsed into two (AGENTS.md's overriding rule): a
position AGREES with the catalog, a position is FOUND and DISAGREES, or a position COULD
NOT BE READ AT ALL -- the heading or At-a-glance line does not follow the shape this module
knows how to parse. A handful of documents carry a hand-curated At-a-glance paragraph
instead of the generated `ORS {sec} -- {title}. Chapter ...` boilerplate (flagship
documents with editorial context, e.g. ors-276a.300 -- measured across the whole corpus:
3 of 37,534 ingested sections, none of them a title-drift finding). COULD-NOT-READ is
reported by name and counted; it is never silently folded into AGREES, and it is not what
this gate exists to catch, so it does not fail the run on its own -- only a FOUND
DISAGREEMENT does. `title:` frontmatter and a missing catalog-ingested file are always
determinable (a YAML parse, a path check), so a bare absence there is a disagreement, not
a could-not-read.
"""
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog_ors import CATALOG  # noqa: E402
from repo_lib import REPO_ROOT, Checks  # noqa: E402


def frontmatter_title(text: str, sec: str, ch: str):
    """(title, could_not_read) for the file's frontmatter `title:` field. `sec`/`ch` are
    unused here -- every position function shares the same (text, sec, ch) signature so
    callers can iterate POSITIONS uniformly."""
    end = text.find("\n---", 3)
    if end == -1:
        return None, True
    try:
        fm = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return None, True
    if not isinstance(fm, dict):
        return None, True
    # A frontmatter block that parses but carries no `title:` at all is a determinable
    # fact -- the document has no title -- which disagrees with a catalog row that has one.
    # It is not a could-not-read: the read succeeded, it just found nothing.
    return fm.get("title"), False


def heading_title(text: str, sec: str, ch: str):
    """(title, could_not_read) for the file's `# {title} (ORS {sec})` heading."""
    m = re.search(r'^# (.+) \(ORS ' + re.escape(sec) + r'\)\s*$', text, re.M)
    if not m:
        return None, True
    return m.group(1), False


def glance_title(text: str, sec: str, ch: str):
    """(title, could_not_read) for the At-a-glance line's section-title clause, `ORS {sec}
    -- {title}. Chapter {ch} (...` -- the chapter-title parenthetical that follows is
    deliberately not parsed here (matched only far enough to anchor the section-title's own
    end): it is a separate, pre-existing drift (#348) `patch_statute_file()` itself declines
    to resync, and this module does not re-litigate that -- only the section-title clause is
    this issue's concern.

    A section title routinely contains its OWN periods (an ORS citation like "100.250"), so
    the boundary cannot be "the next period" -- it has to be anchored on the literal
    ". Chapter {ch} (" that the generator always writes next, with a GREEDY `.+` so a title
    that itself contains that exact substring (there is no such title in this corpus, but a
    greedy match degrades to "matches the LAST occurrence" rather than the first, same
    reasoning as `patch_statute_file`'s own greedy chapter-parenthetical capture)."""
    m = re.search(r'^ORS ' + re.escape(sec) + r' — (.+)\. Chapter ' + re.escape(ch) + r' \(',
                  text, re.M)
    if not m:
        return None, True
    return m.group(1), False


POSITIONS = (
    ("title: frontmatter", frontmatter_title),
    ("# heading", heading_title),
    ("At-a-glance line", glance_title),
)


def check_document(text: str, sec: str, ch: str, catalog_title: str):
    """[(position_name, outcome, found_title)] for the three positions against
    `catalog_title`. `outcome` is one of 'agree' / 'disagree' / 'could-not-read'."""
    out = []
    for name, fn in POSITIONS:
        title, could_not_read = fn(text, sec, ch)
        if could_not_read:
            out.append((name, "could-not-read", title))
        elif title == catalog_title:
            out.append((name, "agree", title))
        else:
            out.append((name, "disagree", title))
    return out


def _iter_ingested(cat):
    """(section_number, chapter, catalog_title, repo_relative_path) for every catalog row
    the catalog itself marks as already ingested with a path."""
    for c in cat["chapters"]:
        ch = c["chapter"]
        for s in c["sections"]:
            if s.get("status") == "ingested" and s.get("path"):
                yield s["number"], ch, s["title"], s["path"]


def cmd_check() -> int:
    cat = yaml.safe_load(CATALOG.read_text())

    checked = agree_docs = disagree_docs = could_not_read_docs = missing_files = 0
    disagreement_lines = []
    could_not_read_lines = []

    for sec, ch, catalog_title, rel_path in _iter_ingested(cat):
        fpath = REPO_ROOT / rel_path
        if not fpath.exists():
            missing_files += 1
            disagreement_lines.append(
                f"  MISSING   {rel_path} (ORS {sec}): catalog marks this section ingested "
                f"at this path, but the file does not exist on disk -- could not check its "
                f"title, and a claimed ingest that is not there is a disagreement, not an "
                f"absence of one")
            continue
        checked += 1
        text = fpath.read_text(encoding="utf-8", errors="replace")
        results = check_document(text, sec, ch, catalog_title)
        bad = [(n, t) for n, o, t in results if o == "disagree"]
        unread = [(n, t) for n, o, t in results if o == "could-not-read"]
        if bad:
            disagree_docs += 1
            for n, t in bad:
                disagreement_lines.append(
                    f"  DISAGREE  {rel_path} (ORS {sec}): {n} says {t!r}, catalog says "
                    f"{catalog_title!r}")
        elif unread:
            could_not_read_docs += 1
            for n, _ in unread:
                could_not_read_lines.append(
                    f"  ?         {rel_path} (ORS {sec}): {n} does not follow the shape "
                    f"this gate reads (non-standard At-a-glance/heading text) -- could not "
                    f"check it against catalog title {catalog_title!r}")
        else:
            agree_docs += 1

    for line in disagreement_lines:
        print(line)
    for line in could_not_read_lines:
        print(line)

    print(f"\n{checked} ingested statute document(s) checked against their catalog row "
          f"({missing_files} catalog-ingested path(s) missing from disk); "
          f"{agree_docs} agree in all three positions, {disagree_docs} disagree in at "
          f"least one position (named above), {could_not_read_docs} carry a position this "
          f"gate could not read but no found disagreement (named above -- a shape gap, not "
          f"a title-drift finding, and does not fail this gate on its own).")

    if disagree_docs or missing_files:
        print(f"\nFAILED: {disagree_docs} document(s) disagree with their catalog row and/or "
              f"{missing_files} claimed-ingested path(s) are missing -- see lines above.")
        return 1
    print("OK: every ingested statute document whose title positions this gate can read "
          "agrees with its catalog row.")
    return 0


# ------------------------------------------------------------------------------ selftest


def _fixture(tmp_path: Path, sec: str, ch: str, title: str, *, glance_ok=True) -> Path:
    """A minimal statute file carrying `title` in all three positions this module reads,
    shaped like a real committed document (see `backfill_ors_titles._fixture_file`, the
    sibling this mirrors). `glance_ok=False` writes a hand-curated At-a-glance paragraph
    instead of the generated boilerplate, the real shape gap measured on 3 of 37,534
    ingested sections (e.g. ors-276a.300)."""
    glance = (f"ORS {sec} — {title}. Chapter {ch} (Chapter {ch}), 2025 Edition.\n"
              if glance_ok else
              "A hand-curated summary that does not start with \"ORS ... — \".\n")
    p = tmp_path / f"ors-{sec}.md"
    p.write_text(
        "---\n"
        f'title: "{title}"\n'
        "doc_type: statute\n"
        "---\n\n"
        f"# {title} (ORS {sec})\n\n"
        "## At a glance\n\n"
        f"{glance}\n"
        "## Full text\n\n"
        f"{sec} {title}. Text.\n",
        encoding="utf-8")
    return p


def _real_clean_document():
    """A real, committed statute document whose three positions already agree with its own
    catalog row -- proving the rule against a fixture would prove it about a document shape
    the corpus may not actually have."""
    cat = yaml.safe_load(CATALOG.read_text())
    for sec, ch, catalog_title, rel_path in _iter_ingested(cat):
        fpath = REPO_ROOT / rel_path
        if not fpath.exists():
            continue
        text = fpath.read_text(encoding="utf-8", errors="replace")
        results = check_document(text, sec, ch, catalog_title)
        if all(o == "agree" for _, o, _ in results):
            return sec, ch, catalog_title, text
    raise SystemExit("no committed statute document agrees in all three positions -- the "
                      "corpus this gate governs does not have the shape it assumes")


def _proof_a_clean_committed_document_agrees(check) -> None:
    sec, ch, catalog_title, text = _real_clean_document()
    results = check_document(text, sec, ch, catalog_title)
    check("RED/GREEN: a real, unmutated, already-agreeing document agrees in all three "
          f"positions (ORS {sec})",
          all(o == "agree" for _, o, _ in results))


def _proof_the_and_defect_shape_is_caught_in_all_three_positions(check) -> None:
    """The real defect this gate exists for (#398): all three positions carry the same
    wrong word, and the gate must name all three, not stop at the first."""
    import tempfile
    tmp_path = Path(tempfile.mkdtemp(prefix="statute-title-agreement-selftest-"))
    try:
        p = _fixture(tmp_path, "999.999", "999", "and")
        text = p.read_text(encoding="utf-8")
        results = check_document(text, "999.999", "999", "Real title from the catalog")
        outcomes = {n: o for n, o, _ in results}
        check("the frontmatter title disagrees",
              outcomes["title: frontmatter"] == "disagree")
        check("the # heading disagrees", outcomes["# heading"] == "disagree")
        check("the At-a-glance line disagrees", outcomes["At-a-glance line"] == "disagree")
    finally:
        import shutil
        shutil.rmtree(tmp_path)


def _proof_each_position_can_disagree_independently(check) -> None:
    """A file patched in 2 of 3 places -- the exact failure mode this gate exists to catch
    (constraint in #398: "a file patched in 2 of 3 places is the failure mode this work
    exists to catch") -- must be reported as ONE disagreeing position, not silently
    averaged into a pass because the other two agree."""
    import tempfile
    import shutil
    tmp_path = Path(tempfile.mkdtemp(prefix="statute-title-agreement-selftest-"))
    try:
        title = "Correct title for ORS 999.999"
        p = _fixture(tmp_path, "999.999", "999", title)
        text = p.read_text(encoding="utf-8")
        # Patch only the heading and At-a-glance line, leaving frontmatter stale -- the
        # partial-patch shape the constraint names.
        stale = text.replace('title: "' + title + '"', 'title: "and"', 1)
        results = check_document(stale, "999.999", "999", title)
        outcomes = {n: o for n, o, _ in results}
        check("a partially-patched file is caught: frontmatter disagrees",
              outcomes["title: frontmatter"] == "disagree")
        check("...while the two already-correct positions still agree",
              outcomes["# heading"] == "agree" and outcomes["At-a-glance line"] == "agree")
    finally:
        shutil.rmtree(tmp_path)


def _proof_a_nonstandard_at_a_glance_is_could_not_read_not_agree_or_disagree(check) -> None:
    """The real shape gap measured on 3 of 37,534 ingested sections (e.g. ors-276a.300): a
    hand-curated At-a-glance paragraph. This must be reported honestly as could-not-read --
    AGENTS.md's overriding rule -- never silently scored as agreeing (it wasn't checked) and
    never scored as disagreeing (nothing was found to disagree)."""
    import tempfile
    import shutil
    tmp_path = Path(tempfile.mkdtemp(prefix="statute-title-agreement-selftest-"))
    try:
        title = "Curated flagship title (ORS 999.999)".replace(" (ORS 999.999)", "")
        p = _fixture(tmp_path, "999.999", "999", title, glance_ok=False)
        text = p.read_text(encoding="utf-8")
        results = check_document(text, "999.999", "999", title)
        outcomes = {n: o for n, o, _ in results}
        check("a hand-curated At-a-glance paragraph is could-not-read, not agree",
              outcomes["At-a-glance line"] == "could-not-read")
        check("...and is not scored as a disagreement either",
              outcomes["At-a-glance line"] != "disagree")
        check("...while the frontmatter and heading, which DO follow the standard shape, "
              "still agree normally",
              outcomes["title: frontmatter"] == "agree" and outcomes["# heading"] == "agree")
    finally:
        shutil.rmtree(tmp_path)


def _proof_a_missing_title_key_is_a_disagreement_not_a_could_not_read(check) -> None:
    """A frontmatter block that parses as YAML but carries no `title:` at all is a
    determinable fact (there is no title), not a parse failure -- AGENTS.md's rule cuts
    both ways: an absence that WAS measured must not be reported as unmeasured either."""
    import tempfile
    import shutil
    tmp_path = Path(tempfile.mkdtemp(prefix="statute-title-agreement-selftest-"))
    try:
        title = "Some title for ORS 999.999"
        p = _fixture(tmp_path, "999.999", "999", title)
        text = p.read_text(encoding="utf-8")
        no_title = text.replace(f'title: "{title}"\n', "", 1)
        found, could_not_read = frontmatter_title(no_title, "999.999", "999")
        check("a frontmatter block with no title: key reads as None, not could-not-read",
              found is None and could_not_read is False)
    finally:
        shutil.rmtree(tmp_path)


def selftest() -> int:
    check = Checks()
    _proof_a_clean_committed_document_agrees(check)
    _proof_the_and_defect_shape_is_caught_in_all_three_positions(check)
    _proof_each_position_can_disagree_independently(check)
    _proof_a_nonstandard_at_a_glance_is_could_not_read_not_agree_or_disagree(check)
    _proof_a_missing_title_key_is_a_disagreement_not_a_could_not_read(check)
    return check.report()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    raise SystemExit(cmd_check())
