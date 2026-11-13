#!/usr/bin/env python3
"""Independent check that no ORS section document's '## Full text' runs past its own section.

  python3 src/check_ors_section_bounds.py --check      every statutes/ors-*.md
  python3 src/check_ors_section_bounds.py --selftest   every rule, watched failing

WHY THIS EXISTS (#446, #449). `repo_lib.snapshot_slice` is called both by the generator that
writes a document and by `verify_provenance` that measures the document's coverage, so the
two agree by construction: a slice that runs on past its section is a document that runs on
past its section, and the provenance gate reports it as fully covered. 8,435 documents
carried a stub and 525 ended in the closing rule behind green gates (0 carried another section's
heading; measured by direct count at 50f77ca4b4; the issue's 3,641 / 9,755 / 1,052 were measured
at 6fe545cfb2).

This module does not call `snapshot_slice`. It reads only the committed DOCUMENTS and asks
three questions of each one's own text, with patterns of its own:

  1. does the text contain the heading of ANOTHER section that has its own document
     ('36.245 Something ...', not preceded by a citation word)?
  2. does it contain the bracket stub of a repealed or renumbered section
     ('171.020 [Repealed by ...]', also a list or a range of numbers)?
  3. does it END in the chapter page's closing rule (fifteen underscores)?

A rule of seventy-eight underscores, blanks inside a printed form, Legislative Counsel
notes, parenthesised subheadings and second prints of a section are NOT findings: whether
they belong to a section is a design choice the slicer makes, not a boundary error.
No network; a document whose '## Full text' block cannot be read is reported by name as
UNREADABLE and fails the run, never counted as clean (AGENTS.md: could not check is never
is not there).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT, Checks  # noqa: E402

FT_RE = re.compile(r"## Full text\n\n(.*?)\n\n## Provenance", re.S)
NUM = r"\d{1,3}[A-Z]?\.\d{3,4}"
HEADING_RE = re.compile(rf"(?<![\w.])({NUM}) [A-Z“\"]")
STUB_RE = re.compile(rf"(?<![\w.])({NUM})(?:(?:,| to| and|, and) {NUM})* \[")
CITE_BEFORE_RE = re.compile(r"(?:\bORS|\band|\bto|\bor|\bsections?|,|\d)\s*$", re.I)
# Documents whose overrun carries a Legislative Counsel 'Note:' that exists in no other
# document: trimming them would delete verbatim session-law text, so they are left as they
# are and listed here (one 'ors-N.NNN' per line, '#' comments) until such notes have a home.
HELD_FILE = "ors-section-bounds-held.txt"
END_RULE_RE = re.compile(r"(?<!_)_{14,15}\s*$")


def findings(doc_id: str, full_text: str, section_ids) -> list[str]:
    """What is wrong with one document's text. `section_ids` is the set of section numbers
    (upper case, as in 'ors-36.110' -> '36.110') that have a document of their own."""
    own = doc_id.replace("ors-", "").upper()
    flat = re.sub(r"\s+", " ", full_text.replace("\xa0", " ")).strip()
    out = []

    def cited(m):
        return bool(CITE_BEFORE_RE.search(flat[max(0, m.start() - 12):m.start()]))

    heads = sorted({m.group(1) for m in HEADING_RE.finditer(flat)
                    if m.group(1) != own and m.group(1) in section_ids and not cited(m)})
    if heads:
        out.append("contains the heading of " + ", ".join(heads[:3]))
    stubs = sorted({m.group(1) for m in STUB_RE.finditer(flat)
                    if m.group(1) != own and not cited(m)})
    if stubs:
        out.append("contains the repealed/renumbered stub of " + ", ".join(stubs[:3]))
    if END_RULE_RE.search(flat):
        out.append("ends in the chapter page's closing rule")
    return out


def check(root: Path = REPO_ROOT) -> int:
    paths = sorted((root / "statutes").glob("ors-*.md"))
    ids = {p.stem[4:].upper() for p in paths}
    bad, unreadable, held_seen = [], [], set()
    hf = root / "_meta" / HELD_FILE
    held = {ln.strip() for ln in hf.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")} if hf.exists() else set()
    for p in paths:
        m = FT_RE.search(p.read_text(encoding="utf-8"))
        if not m:
            unreadable.append(p.name)
            continue
        f = findings(p.stem, m.group(1), ids)
        if f and p.stem in held:
            held_seen.add(p.stem)
        elif f:
            bad.append((p.name, f))
    for name, f in bad[:25]:
        print(f"FAIL {name}: " + "; ".join(f))
    for name in unreadable[:25]:
        print(f"UNREADABLE {name}: no '## Full text' block found; not checked")
    stale = sorted(held - held_seen)
    for h in stale[:25]:
        print(f"STALE {h}: listed in _meta/{HELD_FILE} but not flagged (or no document); remove it")
    if bad or unreadable or stale:
        print(f"FAILED: {len(bad)} of {len(paths)} ORS section documents run past their own "
              f"section, {len(unreadable)} could not be read, {len(stale)} stale held entries -- run: "
              "python3 src/backfill_ors_section_bounds.py")
        return 1
    print(f"OK: none of {len(paths)} ORS section documents contains another section's heading "
          f"or stub, or ends in the closing rule ({len(held_seen)} held: their overrun carries a "
          "note found nowhere else).")
    return 0


def _selftest() -> int:
    ck = Checks()
    ids = {"9.100", "9.200", "36.110"}
    ck("a clean section passes", not findings("ors-9.100", "9.100 Real. Body. [1990 c.1]", ids))
    ck("another section's heading is found",
       any("heading of 9.200" in f for f in findings(
           "ors-9.100", "9.100 Real. Body. [1990 c.1] 9.200 Other. More.", ids)))
    ck("a heading with no document of its own is not a finding",
       not findings("ors-9.100", "9.100 Real. [1990 c.1] 9.300 Other. More.", ids))
    ck("a citation is not a heading",
       not findings("ors-9.100", "9.100 Real. See ORS 9.200 Other for more. [1]", ids))
    ck("a repealed stub is found",
       any("stub of 9.150" in f for f in findings(
           "ors-9.100", "9.100 Real. [1990 c.1] 9.150 [Repealed by 1991 c.2]", ids)))
    ck("a range stub is found",
       any("stub of 9.150" in f for f in findings(
           "ors-9.100", "9.100 Real. [1990 c.1] 9.150 to 9.160 [Repealed by 1991 c.2]", ids)))
    ck("a cited stub is not a finding",
       not findings("ors-9.100", "9.100 Real. See ORS 9.150 [Repealed by 1991 c.2] now. [1]", ids))
    ck("the closing rule at the end is found",
       any("closing rule" in f for f in findings(
           "ors-9.100", "9.100 Real. [1990 c.1] " + "_" * 15, ids)))
    ck("a rule inside a form is not a finding",
       not findings("ors-9.100", "9.100 Real. Name: " + "_" * 15 + " Relationship: x [1]", ids))
    ck("a seventy-eight underscore rule is a design choice, not a finding",
       not findings("ors-9.100", "9.100 Real. [1] " + "_" * 78, ids))
    # The gate over a throwaway tree: it fails on a planted violation and on an unreadable
    # document, and passes on a clean one.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "statutes").mkdir()

        def doc(n, body):
            (root / "statutes" / f"ors-{n}.md").write_text(
                f"---\nid: ors-{n}\n---\n\n## Full text\n\n{body}\n\n## Provenance & change history\n")
        doc("9.100", "9.100 Real. Body. [1990 c.1]")
        doc("9.200", "9.200 Other. Body. [1990 c.2]")
        ck("a clean throwaway tree passes", check(root) == 0)
        doc("9.100", "9.100 Real. Body. [1990 c.1] 9.200 Other. Body. [1990 c.2]")
        ck("a planted overrun fails the gate", check(root) == 1)
        doc("9.100", "9.100 Real. Body. [1990 c.1]")
        (root / "statutes" / "ors-9.300.md").write_text("no full text block here\n")
        ck("an unreadable document fails the gate, it is not counted clean", check(root) == 1)
        # A HELD document (its overrun carries a Legislative Counsel note that exists nowhere
        # else) is reported, not failed; a held entry that is no longer flagged, or has no
        # document, fails so the list cannot rot.
        (root / "statutes" / "ors-9.300.md").unlink()
        doc("9.100", "9.100 Real. [1990 c.1] 9.150 [Repealed by 1991 c.2] Note: kept.")
        ck("an overrun fails the gate when not held", check(root) == 1)
        (root / "_meta").mkdir(exist_ok=True)
        (root / "_meta" / HELD_FILE).write_text("# why\nors-9.100\n")
        ck("a held overrun does not fail the gate", check(root) == 0)
        doc("9.100", "9.100 Real. Body. [1990 c.1]")
        ck("a held entry that is no longer flagged fails the gate", check(root) == 1)
        (root / "_meta" / HELD_FILE).write_text("ors-9.999\n")
        ck("a held entry with no document fails the gate", check(root) == 1)
    return ck.report("check-ors-section-bounds selftest")


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    if "--check" in sys.argv[1:]:
        sys.exit(check())
    print("usage: check_ors_section_bounds.py --check | --selftest")
    sys.exit(2)
