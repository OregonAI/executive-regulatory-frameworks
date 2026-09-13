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

A FOURTH, DOCUMENT-LEVEL OUTCOME (#398/#414's follow-on): a document with a found
disagreement is not automatically the FILE's fault. Before a found disagreement is reported
as a plain DISAGREEMENT, this module consults the section's own printed catchline in the
committed `_meta/snapshots/ors-chapter-<ch>.txt` (via `repo_lib.snapshot_slice` and
`ingest_ors`'s own catchline-boundary regex -- the same extraction #286's backfill already
established as the one ground truth this repository trusts for a catalog title's own
printed source; not a second TOC parser, and not `catalog_ors.parse_toc()`, which reads the
chapter's TOC LISTING, the very thing a `title[:160]` cap and a TOC line-wrap corrupt). If
the catalog row itself agrees with that snapshot, the FILE is at fault -- an ordinary
DISAGREEMENT, gate fails, as before. If the catalog row DISAGREES with its own committed
snapshot, the correct title cannot be determined from the catalog at all, and copying it
into the file would write the catalog's defect (a mid-word truncation, a dropped
line-wrap continuation) into the corpus as a document title. This is measured per
section at check time against the actual committed snapshot text -- never a fixed list of
section numbers -- and reported by name, with both strings shown, exactly like
COULD-NOT-READ: named, counted separately, and does not fail the gate on its own.
a could-not-read.
"""
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalog_ors import CATALOG  # noqa: E402
# `_CATCHLINE_END_RE`/`_CATCHLINE_WINDOW` -- reused, not reimplemented: the exact
# body-catchline boundary `ingest_ors.anchor_ok` itself checks against, and the extraction
# `backfill_ors_286_titles.py`'s own docstring names as "the one ground truth this
# repository already trusts" for a catalog title's own printed source. Importing this
# module is import-safe: everything below its function/constant definitions is guarded by
# `if __name__ == "__main__":`.
from ingest_ors import _CATCHLINE_END_RE, _CATCHLINE_WINDOW  # noqa: E402
from repo_lib import REPO_ROOT, SNAPSHOT_DIR, Checks, snapshot_slice  # noqa: E402


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


def _snapshot_catchline(sec: str, ch: str):
    """(catchline, could_not_measure) for a section's OWN printed catchline, read straight
    from the committed `_meta/snapshots/ors-chapter-<ch>.txt` -- `repo_lib.snapshot_slice`
    locates the section's body text, then `ingest_ors._CATCHLINE_END_RE` (ORS's own
    convention: NUMBER CATCHLINE. body...) finds where the catchline ends, exactly as
    `ingest_ors.anchor_ok` reads it. `could_not_measure` covers every reason this can't be
    read -- no cached snapshot for the chapter, or the section's own number not found in
    it -- so a caller never mistakes "nothing was found" for "an empty catchline was
    found"."""
    snap_path = SNAPSHOT_DIR / f"ors-chapter-{ch.lower()}.txt"
    if not snap_path.exists():
        return None, True
    raw = snap_path.read_text(encoding="utf-8", errors="replace")
    sl = snapshot_slice(f"ors-{sec.lower()}", f"ors-chapter-{ch.lower()}", raw)
    if not sl:
        return None, True
    body = sl[len(sec):len(sec) + _CATCHLINE_WINDOW]
    m = _CATCHLINE_END_RE.search(body)
    catchline = (body[:m.start()] if m else body).strip()
    return (catchline, False) if catchline else (None, True)


def classify_document(sec: str, ch: str, catalog_title: str, results):
    """(category, positions, snapshot_catchline) for one document's `check_document()`
    results -- the fourth, document-level outcome layered on top of the three per-position
    outcomes. `category` is one of 'agree' / 'disagree' / 'could-not-read' /
    'catalog-disagrees-with-snapshot'; `positions` is the [(name, found_title)] list that
    outcome is reported against; `snapshot_catchline` is set only for the fourth category.

    The committed snapshot is consulted ONLY when a FOUND disagreement exists -- never for
    a clean document, and never for a could-not-read one -- so the ~37.5k agreeing rows and
    the handful of could-not-read ones never pay for (or risk a false read from) a snapshot
    lookup they don't need. When a disagreement exists, this is the measurement (#398/#414's
    operator decision): does the CATALOG row itself agree with this section's own printed
    catchline? If yes, the file is what's wrong -- 'disagree', unchanged from before this
    category existed. If the catalog disagrees with its own snapshot too (or the snapshot
    can't be read), the file cannot be corrected by copying the catalog, so this is not
    reported as an ordinary disagreement at all."""
    bad = [(n, t) for n, o, t in results if o == "disagree"]
    unread = [(n, t) for n, o, t in results if o == "could-not-read"]
    if bad:
        catchline, could_not_measure = _snapshot_catchline(sec, ch)
        if not could_not_measure and catchline != catalog_title.strip():
            return "catalog-disagrees-with-snapshot", bad, catchline
        return "disagree", bad, None
    if unread:
        return "could-not-read", unread, None
    return "agree", [], None


def _classify_all(cat):
    """(section_number, chapter, repo_relative_path, catalog_title, category, positions,
    snapshot_catchline) for every catalog-ingested document -- `category` is 'missing' for
    a claimed path that isn't on disk, otherwise one of `classify_document`'s four. The
    single place the corpus is walked and classified; `cmd_check` and the selftest's
    firing/non-swallowing proofs below all walk THIS, so a selftest proof asserting the
    fourth category exists is a claim about the same code `--check` runs, not a second copy
    of it."""
    for sec, ch, catalog_title, rel_path in _iter_ingested(cat):
        fpath = REPO_ROOT / rel_path
        if not fpath.exists():
            yield sec, ch, rel_path, catalog_title, "missing", [], None
            continue
        text = fpath.read_text(encoding="utf-8", errors="replace")
        results = check_document(text, sec, ch, catalog_title)
        category, positions, snapshot_catchline = classify_document(sec, ch, catalog_title,
                                                                     results)
        yield sec, ch, rel_path, catalog_title, category, positions, snapshot_catchline


def cmd_check() -> int:
    cat = yaml.safe_load(CATALOG.read_text())

    checked = agree_docs = disagree_docs = could_not_read_docs = missing_files = 0
    catalog_snapshot_docs = 0
    disagreement_lines = []
    catalog_snapshot_lines = []
    could_not_read_lines = []

    for (sec, ch, rel_path, catalog_title, category, positions,
         snapshot_catchline) in _classify_all(cat):
        if category == "missing":
            missing_files += 1
            disagreement_lines.append(
                f"  MISSING   {rel_path} (ORS {sec}): catalog marks this section ingested "
                f"at this path, but the file does not exist on disk -- could not check its "
                f"title, and a claimed ingest that is not there is a disagreement, not an "
                f"absence of one")
            continue
        checked += 1
        if category == "disagree":
            disagree_docs += 1
            for n, t in positions:
                disagreement_lines.append(
                    f"  DISAGREE  {rel_path} (ORS {sec}): {n} says {t!r}, catalog says "
                    f"{catalog_title!r}")
        elif category == "catalog-disagrees-with-snapshot":
            catalog_snapshot_docs += 1
            pos_names = ", ".join(n for n, _ in positions)
            catalog_snapshot_lines.append(
                f"  CATALOG≠SNAPSHOT  {rel_path} (ORS {sec}): {pos_names} disagree(s) "
                f"with the catalog row, but the catalog row ITSELF disagrees with this "
                f"section's own catchline in the committed "
                f"_meta/snapshots/ors-chapter-{ch.lower()}.txt -- the correct title cannot "
                f"be determined from the catalog, so this is not fixable by copying the "
                f"catalog into the file: catalog says {catalog_title!r} "
                f"({len(catalog_title)} chars), snapshot says {snapshot_catchline!r} "
                f"({len(snapshot_catchline)} chars)")
        elif category == "could-not-read":
            could_not_read_docs += 1
            for n, _ in positions:
                could_not_read_lines.append(
                    f"  ?         {rel_path} (ORS {sec}): {n} does not follow the shape "
                    f"this gate reads (non-standard At-a-glance/heading text) -- could not "
                    f"check it against catalog title {catalog_title!r}")
        else:
            agree_docs += 1

    for line in disagreement_lines:
        print(line)
    for line in catalog_snapshot_lines:
        print(line)
    for line in could_not_read_lines:
        print(line)

    print(f"\n{checked} ingested statute document(s) checked against their catalog row "
          f"({missing_files} catalog-ingested path(s) missing from disk); "
          f"{agree_docs} agree in all three positions, {disagree_docs} disagree in at "
          f"least one position (named above), {catalog_snapshot_docs} disagree with their "
          f"catalog row but the catalog row itself disagrees with its own committed chapter "
          f"snapshot (named above -- the correct title cannot be determined from the "
          f"catalog, and this does not fail the gate on its own), {could_not_read_docs} "
          f"carry a position this gate could not read but no found disagreement (named "
          f"above -- a shape gap, not a title-drift finding, and does not fail this gate "
          f"on its own).")

    if disagree_docs or missing_files:
        print(f"\nFAILED: {disagree_docs} document(s) disagree with their catalog row and/or "
              f"{missing_files} claimed-ingested path(s) are missing -- see lines above.")
        return 1
    print("OK: every ingested statute document whose title positions this gate can read "
          "agrees with its catalog row (or its catalog row's own disagreement with the "
          "committed snapshot is named above and does not fail this gate).")
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


def _real_row_where_catalog_agrees_with_its_own_snapshot(cat):
    """A real (sec, ch, catalog_title) row whose catalog title is IDENTICAL to this
    section's own printed catchline in the committed snapshot -- found by measurement
    (`_snapshot_catchline`), not pinned as a literal, the same way #398/#414's own
    disagreeing set was discovered. Used to build a fixture that proves the new category
    cannot swallow a genuine FILE defect: the catalog side of that fixture must be known,
    by measurement, to already agree with the snapshot."""
    for sec, ch, catalog_title, _ in _iter_ingested(cat):
        catchline, could_not_measure = _snapshot_catchline(sec, ch)
        if not could_not_measure and catchline == catalog_title.strip():
            return sec, ch, catalog_title
    raise SystemExit("no catalog row agrees with its own committed snapshot catchline -- "
                      "the corpus this gate governs does not have the shape it assumes")


def _proof_catalog_disagrees_with_snapshot_fires_on_real_data(check) -> None:
    """Proves the fourth category is MEASURED against the committed catalog + snapshots,
    not a hardcoded list of section numbers (#398/#414's own constraint: "If your
    implementation ends up embedding the six numbers, you have built the wrong thing").

    #417: this proof used to walk the REAL, currently-committed catalog via `_classify_all`
    and require it to already contain a `catalog-disagrees-with-snapshot` row. That was a
    precondition about the live corpus's CURRENT DEFECT COUNT, not about the classifier's
    own logic -- true only while #415's six real rows (243.507, 279C.337, 455.097, 657.462,
    659A.145, 757.015) were still broken. #411/#412/#415 fixed every one of them, so the
    category is now correctly empty on `--check` (0 catalog-disagrees-with-snapshot, verify
    with `python3 src/statute_title_agreement.py --check`) -- and a proof that only passes
    while the corpus is broken is itself a defect: it would fail forever after a correct,
    complete fix, and would have silently stopped meaning anything the day the count first
    hit zero, long before anyone noticed. So this proof no longer reads a real defect. It
    takes a REAL section and its REAL committed chapter snapshot -- discovered dynamically
    via `_real_row_where_catalog_agrees_with_its_own_snapshot`, the same helper the sibling
    anti-swallow proof below uses, never a pinned section number -- builds a FILE that
    itself agrees with that section's real, correct title (so no FILE defect is in play),
    and passes `classify_document` a fabricated catalog title, mid-word-truncated from the
    real one exactly like #415's own catalog defects, so the CATALOG side is measured, by
    the same `_snapshot_catchline` lookup `--check` itself uses against the real committed
    snapshot, to genuinely disagree with it. This still proves the category fires by
    measurement against the committed snapshot, not by construction -- only the catalog
    row is synthetic, and it is synthesized specifically to fail that measurement rather
    than asserted to."""
    cat = yaml.safe_load(CATALOG.read_text())
    sec, ch, _real_catalog_title = _real_row_where_catalog_agrees_with_its_own_snapshot(cat)
    catchline, could_not_measure = _snapshot_catchline(sec, ch)
    # Guaranteed by the helper above (it only returns rows where this already succeeded),
    # re-checked here rather than trusted blindly.
    if could_not_measure:
        raise SystemExit("snapshot catchline vanished between measurement and use for "
                          f"ORS {sec} -- the corpus changed out from under this proof")
    # A mid-word truncation of the real, agreeing title -- the exact #415 catalog-defect
    # shape -- strictly shorter than `catchline` (which `_snapshot_catchline` guarantees is
    # non-empty), so it can never coincide with it.
    corrupted_catalog_title = catchline[: len(catchline) // 2]
    import shutil
    import tempfile
    tmp_path = Path(tempfile.mkdtemp(prefix="statute-title-agreement-selftest-"))
    try:
        # The FILE carries the section's real, correct title (== the snapshot catchline) in
        # all three positions -- no file defect. Only the catalog_title handed to
        # check_document/classify_document below is corrupted, simulating a catalog row
        # gone wrong the way #415's real ones did.
        p = _fixture(tmp_path, sec, ch, catchline)
        text = p.read_text(encoding="utf-8")
        results = check_document(text, sec, ch, corrupted_catalog_title)
        category, positions, snapshot_catchline = classify_document(
            sec, ch, corrupted_catalog_title, results)
        check(f"a catalog row measured (against the real committed "
              f"_meta/snapshots/ors-chapter-{ch.lower()}.txt) to disagree with its own "
              f"section's snapshot catchline (ORS {sec}) is classified "
              f"catalog-disagrees-with-snapshot", category == "catalog-disagrees-with-snapshot")
        check(f"...and the two strings this gate would report really do differ: catalog "
              f"{corrupted_catalog_title!r} != snapshot {snapshot_catchline!r}",
              corrupted_catalog_title.strip() != snapshot_catchline)
        check("...and at least one disagreeing position is carried along to report",
              positions is not None and len(positions) > 0)
    finally:
        shutil.rmtree(tmp_path)


def _proof_catalog_disagreement_category_cannot_swallow_a_genuine_file_defect(check) -> None:
    """The operator's own bar (#398/#414): "A gate that cannot fail is worse than no
    gate." Finds a REAL catalog row measured to already agree with its own committed
    snapshot, builds a fixture FILE for that exact section carrying the real #398 defect
    shape (every position reads "and"), and asserts the new category does NOT catch it:
    classification must still be 'disagree', with no snapshot_catchline populated -- the
    same failure this gate existed to catch before this category was added must still
    fail it."""
    cat = yaml.safe_load(CATALOG.read_text())
    sec, ch, catalog_title = _real_row_where_catalog_agrees_with_its_own_snapshot(cat)
    import shutil
    import tempfile
    tmp_path = Path(tempfile.mkdtemp(prefix="statute-title-agreement-selftest-"))
    try:
        p = _fixture(tmp_path, sec, ch, "and")
        text = p.read_text(encoding="utf-8")
        results = check_document(text, sec, ch, catalog_title)
        category, _positions, snapshot_catchline = classify_document(sec, ch, catalog_title,
                                                                      results)
        check(f"a genuine file defect on a catalog row measured to agree with its own "
              f"snapshot (ORS {sec}, catalog title {catalog_title!r}) is still classified "
              f"'disagree', not swallowed by the new category", category == "disagree")
        check("...and no snapshot_catchline is reported for a real disagreement (nothing "
              "to show -- the catalog was never in question)", snapshot_catchline is None)
    finally:
        shutil.rmtree(tmp_path)


def selftest() -> int:
    check = Checks()
    _proof_a_clean_committed_document_agrees(check)
    _proof_the_and_defect_shape_is_caught_in_all_three_positions(check)
    _proof_each_position_can_disagree_independently(check)
    _proof_a_nonstandard_at_a_glance_is_could_not_read_not_agree_or_disagree(check)
    _proof_a_missing_title_key_is_a_disagreement_not_a_could_not_read(check)
    _proof_catalog_disagrees_with_snapshot_fires_on_real_data(check)
    _proof_catalog_disagreement_category_cannot_swallow_a_genuine_file_defect(check)
    return check.report()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    raise SystemExit(cmd_check())
