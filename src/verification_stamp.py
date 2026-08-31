#!/usr/bin/env python3
"""No ingest script may write a `last_verified`/`verified_by` value nobody earned (#295,
AGENTS.md rule 6, the residue of #109).

  python3 src/verification_stamp.py             # what every scannable src/*.py writes
  python3 src/verification_stamp.py --check      # CI: every write is the empty string
  python3 src/verification_stamp.py --selftest   # CI: the rule above can fail, and fires

WHY THIS EXISTS. AGENTS.md rule 6: "Do not set `last_verified`/`verified_by` to a real
value -- the human reviewer does that at approval. The schema REQUIRES both keys, so
ingestion writes them as empty strings ... Never write a date or a handle you did not earn;
a fabricated verification stamp is worse than an obviously-empty one." #109 un-stamped
every document carrying a fabricated `last_verified` value and fixed the generators that
wrote them. #295 found the fix had not reached every generator: `ingest_ors.py`,
`ingest_eo.py`, `ingest_policies.py` and `ingest_constitution.py` all still wrote
`last_verified: "{TODAY}"` (`ingest_policies.py` also `verified_by: "{HANDLE}"`, the other
three `verified_by: "@morficflux"`) -- a rule stated in AGENTS.md, demonstrated correctly by
two OCR scripts in the same repository (`ocr_fallback_eo.py`, `ocr_promote.py`), and
enforced by NOTHING. A fix without a gate is how a rule that already has one violation on
record acquires a fifth.

THE POPULATION IS A GLOB, NOT A LIST OF NAMES (`scannable_scripts()`, `SRC.glob("*.py")`)
-- #295's exact failure mode, and the SAME failure mode a review of this fix found in the
gate itself. `ingest_oar.py` was fixed on `feat/oar-ingest-238`; the other four were not,
because nothing scanned them TOGETHER. A population hand-typed as four or five names would
repeat that mistake the day a sixth ingest script is added and nobody remembers to list it
here; a glob catches it by construction, the moment the file exists
(`_proof_population_is_a_glob_not_a_list` proves this against a real file dropped into
`src/` and removed again, not merely against the glob call that already defines the
population -- that call could itself have been a list, and a proof that never leaves the
pure-Python fixtures could not tell the difference). THE FIRST VERSION OF THIS GATE GLOBBED
`ingest_*.py` ONLY -- a name-prefix filter, the same shape of mistake at one remove: it
excluded `ocr_promote.py` and `ocr_fallback_eo.py`, the two scripts THIS MODULE'S OWN
DOCSTRING (below) names as the correct exemplars of the rule, and a live mutation of
`ocr_promote.py` to write a fabricated stamp passed `--check` clean. A prefix is a list with
extra steps; the population is now every `src/*.py`, because the next writer of these
fields will not necessarily be named `ingest_*` -- `ocr_*`, `reingest_*` and `backfill_*`
all already exist in this directory. `verification_stamp.py` itself is the one exclusion
(`p.resolve() != Path(__file__).resolve()`, the same shape `stated_census.citable_paths()`
uses and for the same reason): it is the one file in `src/` whose JOB is to talk ABOUT this
shape, so its own docstring and its own selftest fixtures necessarily contain literal
example occurrences of a fabricated stamp. Scanning itself would be the pattern matching its
own definition, not a second instance of the defect it exists to catch.

THE SCAN IS AST, NOT A LINE-GREP FOR `{TODAY}` -- the #293 warning ("when you widen
anything, measure what else it now admits"). A narrower scanner that looked only for
f-string interpolation (`"{TODAY}"`, `"{HANDLE}"`) would catch the three bugs #295 found
and miss a FOURTH shape with the identical effect: a hardcoded non-empty literal with no
interpolation at all, e.g. `verified_by: "@morficflux"` written as plain text. Both shapes
assign a value nobody earned; both must fire the same rule
(`_proof_a_hardcoded_literal_is_caught`, `_proof_interpolation_is_caught`). The scan reads
every f-string (`ast.JoinedStr`) and plain string literal in a module, reconstructs the
literal text it would print with each interpolated `{...}` replaced by a placeholder that
can never appear in real template text, and checks whether the value written after
`last_verified:`/`verified_by:` is the empty string either way -- DOUBLE-QUOTED,
SINGLE-QUOTED, OR BARE TO END OF LINE, all three read the same. The first version of this
gate matched only `"..."`; single-quoted YAML is not a hypothetical spelling -- real
committed documents already carry `last_verified: ''`, from the retention-schedule generator
folded in at 780b192a53 -- and a review of this fix proved the double-quote-only regex blind
to both `'{TODAY}'` and a bare unquoted `{TODAY}` (`_proof_single_quoted_stamp_is_caught`,
`_proof_unquoted_stamp_is_caught`). It is still LITERAL-QUOTED-VALUE ONLY, the same
over-inclusive-in-one-direction shape `name_readers.py` uses for its comma scan: a value
built by string concatenation (`"last_verified: \"" + x + "\""`) or by a library call
(`yaml.safe_dump(...)`) would not be read as a template write. No writer in this corpus
builds one that way today; the cost of that gap is a shape nobody has used, and the cost of
the alternative (an unparseable-only scanner) is silence on the exact four sites #295 found.

MODULE/CLASS/FUNCTION DOCSTRINGS ARE NOT SCANNED. An ingest script explaining, in its own
docstring, the wrong shape it used to write (exactly what this module's docstring does,
above) is not a second instance of writing it -- `field_writes()` walks the syntax tree but
skips the one string-constant node that is a def/class/module's actual `__doc__`
(`_docstring_node_ids()`), so quoting the forbidden shape in prose cannot fail the gate
(`_proof_docstrings_are_not_scanned`). This is narrower than "skip every string literal
that looks like prose" -- only the specific AST position Python itself treats as a
docstring is exempt; a template string built and returned from inside a function body,
docstring-shaped or not, is still scanned.

COULD NOT PARSE IS A FAILURE, NOT A PASS. A module this scan cannot read is not a module
with no violations in it -- AGENTS.md's "could not check is never reported as is not
there," the same rule `ingest_status.ingest_vocabulary()` applies to an unparseable
writer."""
import argparse
import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from check_rule_ledger import RuleLedger
from repo_lib import REPO_ROOT, Checks

SRC = REPO_ROOT / "src"

# The two fields AGENTS.md rule 6 reserves for the human reviewer at approval.
FIELDS = ("last_verified", "verified_by")

# A value after either field, at the start of a (reconstructed) line -- ANY of the three
# spellings this corpus's own generators use: double-quoted (every template written by
# hand), single-quoted (the retention-schedule generator folded in at 780b192a53), or
# bare to end of line (no generator uses this today, but nothing
# stops a sixth one from writing it, and the empty-string check has to be able to tell
# "wrote nothing" from "wrote nothing between quotes" either way). Quoted alternatives are
# tried first so a quoted empty value (`""`, `''`) reads as the empty string rather than as
# a bare value that happens to start with a quote character; `[^"\n]*`/`[^'\n]*` so an
# interpolation placeholder (never a literal quote or newline) is captured whole.
_FIELD_RE = re.compile(
    r'^[ \t]*(last_verified|verified_by):[ \t]*'
    r'(?:"([^"\n]*)"|\'([^\'\n]*)\'|([^\n]*))',
    re.M)

# A byte that cannot occur in real Python source text once parsed -- stands in for an
# f-string's interpolated `{...}` so reconstructed text can tell "empty" from "something
# was substituted here" without evaluating the expression.
_PLACEHOLDER = "\x00"

RULE = "ingest-verification-stamp-earned"
CHECK_RULES = (RULE,)

# THE CHECK-RULE LEDGER (#319), not a hand-rolled `_FIRED` set: recording a rule when a
# Failure is built, the AST scan of THIS module's own source for the rule names it can
# emit, and the both-directions comparison against CHECK_RULES are check_rule_ledger.py's
# one shared implementation.
_LEDGER = RuleLedger(CHECK_RULES, __file__)
Failure = _LEDGER.Failure
emitted_rules = _LEDGER.emitted_rules


def _label(path) -> str:
    try:
        return str(Path(path).relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def scannable_scripts() -> list:
    """Every `src/*.py` this gate covers -- EXCLUDING ITSELF -- discovered by glob, not
    named one at a time. See the module docstring: a hardcoded list, and a name-prefix
    glob narrower than this one, are both the exact shape of #295's own root cause.
    `verification_stamp.py` is excluded (`p.resolve() != Path(__file__).resolve()`, the
    same shape `stated_census.citable_paths()` uses) because it is the one file whose job
    is to talk ABOUT this shape -- its own docstring and selftest fixtures necessarily
    contain literal example occurrences of a fabricated stamp, and scanning itself would be
    the pattern matching its own definition."""
    return sorted(p for p in SRC.glob("*.py") if p.resolve() != Path(__file__).resolve())


def _reconstruct(node):
    """The literal text `node` would print, with every f-string interpolation replaced by
    `_PLACEHOLDER`. `None` for anything that is not a string-producing literal."""
    if isinstance(node, ast.JoinedStr):
        out = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                out.append(v.value)
            else:
                out.append(_PLACEHOLDER)
        return "".join(out)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _joinedstr_child_ids(tree) -> set:
    """`id()` of every node that is one PIECE of an f-string (`ast.JoinedStr.values`),
    never the whole thing. `ast.walk()` visits a `JoinedStr` AND each of its child
    `Constant`/`FormattedValue` fragments as separate nodes -- `_reconstruct()` already
    assembles the complete printed text once, for the `JoinedStr` itself; scanning a lone
    fragment again is not a second real write, it is the boundary where an interpolation
    happened to fall read as one. A single-quoted interpolated stamp
    (`f"last_verified: '{TODAY}'"`) splits into a fragment ending `last_verified: '` with
    no closing quote in sight -- exactly the shape the bare-to-end-of-line alternative
    would otherwise misread as a one-character bare value (`'`) alongside the correct
    match from the whole `JoinedStr`, a false positive from the widening `_FIELD_RE`
    picked up (found scanning the corpus this fix's own adversarial tests were built
    against, not by any of the reported findings)."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for v in node.values:
                ids.add(id(v))
    return ids


def _docstring_node_ids(tree) -> set:
    """`id()` of every AST node that IS a module/class/function's actual `__doc__` --
    the first statement of its body, an `Expr` whose value is a plain (non-f-string)
    string `Constant`, exactly what Python itself recognizes as a docstring (an f-string
    can never be one). Not "every string literal that reads like prose" -- only this exact
    position, so a template string built and returned from inside a function body stays
    scanned regardless of how docstring-shaped its content looks."""
    ids = set()
    for node in [tree] + [n for n in ast.walk(tree)
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                              ast.ClassDef))]:
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            ids.add(id(body[0].value))
    return ids


def field_writes(source: str):
    """Every `(field, value)` this module's source assigns to `last_verified`/
    `verified_by` inside a string template, read off the syntax tree. `value` has any
    interpolation collapsed to the literal text `<interpolated>` -- non-empty either way,
    which is the point (see module docstring on the #293 warning). A module/class/function
    DOCSTRING is skipped (`_docstring_node_ids()`) -- prose explaining the forbidden shape
    is not a second instance of writing it -- and so is a bare f-string FRAGMENT
    (`_joinedstr_child_ids()`) -- `ast.walk()` visits a `JoinedStr` and each of its own
    child pieces separately, and scanning a fragment again after already reading the whole
    assembled `JoinedStr` is not a second write either, just the same one seen at the
    interpolation boundary. `None` if `source` does not parse as Python --
    distinct from `[]` (parses, and writes nothing), because a module this could not read
    is not a module with no writes in it."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    skip = _docstring_node_ids(tree) | _joinedstr_child_ids(tree)
    out = []
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        text = _reconstruct(node)
        if not text:
            continue
        for m in _FIELD_RE.finditer(text):
            field = m.group(1)
            if m.group(2) is not None:
                value = m.group(2)
            elif m.group(3) is not None:
                value = m.group(3)
            else:
                value = (m.group(4) or "").rstrip()
            out.append((field, value.replace(_PLACEHOLDER, "<interpolated>")))
    return out


def stamp_failures(source: str, label: str) -> list:
    """The rule (`ingest-verification-stamp-earned`), fired against ONE module's source.
    `label` is what a `Failure` names as its site, so a `--selftest` can fire this against
    a synthetic module with no file on disk."""
    writes = field_writes(source)
    if writes is None:
        return [Failure("ingest-verification-stamp-earned", label,
                         "does not parse as Python -- could not verify last_verified/"
                         "verified_by are written empty; could-not-check is never "
                         "reported as is-not-there")]
    out = []
    seen = set()
    for field, value in writes:
        if value == "" or (field, value) in seen:
            continue
        seen.add((field, value))
        out.append(Failure(
            "ingest-verification-stamp-earned", label,
            f'writes {field}: "{value}" -- a verification stamp nobody earned. '
            'Ingestion writes both fields "" and the human reviewer sets them at '
            'approval (AGENTS.md rule 6, #109, #295)'))
    return out


def check_all_scripts() -> list:
    """The rule, over every real committed `src/*.py` (excluding this module itself)."""
    failures = []
    for path in scannable_scripts():
        try:
            source = path.read_text()
        except OSError as e:
            failures.append(Failure("ingest-verification-stamp-earned", _label(path),
                                     f"could not be read: {e}"))
            continue
        failures.extend(stamp_failures(source, _label(path)))
    return failures


def report(failures) -> int:
    for f in failures:
        print(f"  FAIL [{f.rule}] {f.site}: {f.detail}", file=sys.stderr)
    return len(failures)


def cmd_check() -> int:
    scripts = scannable_scripts()
    failures = check_all_scripts()
    if report(failures):
        print(f"\n{len(failures)} verification-stamp violation(s)", file=sys.stderr)
        return 1
    print(f"{len(scripts)} script(s) checked, every last_verified/verified_by "
          "write is the empty string: " + ", ".join(_label(p) for p in scripts))
    return 0


# ------------------------------------------------------------------------------ selftest


def _proof_the_real_scripts_are_clean(check) -> None:
    failures = check_all_scripts()
    scripts = scannable_scripts()
    check(f"every real committed src/*.py (excluding this module) writes "
          f"last_verified/verified_by empty ({len(scripts)} scripts)",
          not failures)
    check("...and at least one script actually carries the fields (a clean scan of zero "
          "sites would agree with an empty declaration for the wrong reason)",
          any('last_verified: ""' in p.read_text() for p in scripts))


def _proof_the_ocr_scripts_are_in_population(check) -> None:
    """The gap a review of this fix found: the ORIGINAL population (`SRC.glob
    ("ingest_*.py")`) excluded `ocr_promote.py` and `ocr_fallback_eo.py` -- the two scripts
    this module's own docstring names as the correct exemplars of the rule -- and a live
    mutation of `ocr_promote.py` to write a fabricated stamp passed `--check` clean with
    that population. Proved here by name, against the real committed tree, not by mutating
    a real file inside a selftest."""
    names = {p.name for p in scannable_scripts()}
    check("ocr_promote.py (named in this module's own docstring) is in the scanned "
          "population", "ocr_promote.py" in names)
    check("ocr_fallback_eo.py (named in this module's own docstring) is in the scanned "
          "population", "ocr_fallback_eo.py" in names)
    check("this module itself is NOT in its own scanned population -- it is the one file "
          "whose job is to talk ABOUT this shape, not a writer of it",
          "verification_stamp.py" not in names)


def _proof_interpolation_is_caught(check) -> None:
    """The three shapes #295 actually found: an f-string interpolation."""
    src = ('def doc_text(TODAY):\n'
           '    return f"""last_verified: "{TODAY}"\n'
           'verified_by: ""\n"""\n')
    fs = stamp_failures(src, "synthetic")
    check("an interpolated stamp (last_verified: \"{TODAY}\") is caught",
          any(f.rule == RULE and "last_verified" in f.detail for f in fs))
    check("...and a clean field on the same template does not also fire",
          not any(f.rule == RULE and "verified_by" in f.detail for f in fs))


def _proof_a_hardcoded_literal_is_caught(check) -> None:
    """The #293 warning: a scanner built to catch interpolation only would miss this --
    same violation, no `{...}` at all."""
    src = ('def doc_text():\n'
           '    return f"""last_verified: ""\n'
           'verified_by: "@morficflux"\n"""\n')
    fs = stamp_failures(src, "synthetic")
    check("a hardcoded non-empty literal (no interpolation) is caught the same way",
          any(f.rule == RULE and "verified_by" in f.detail for f in fs))


def _proof_single_quoted_stamp_is_caught(check) -> None:
    """Single-quoted YAML is not a hypothetical spelling: real committed documents already
    carry `last_verified: ''` from the retention-schedule generator folded in at
    780b192a53. A review of this fix proved the original double-quote-only regex blind to
    this shape."""
    src = ("def doc_text(TODAY):\n"
           "    return f\"last_verified: '{TODAY}'\\nverified_by: ''\\n\"\n")
    fs = stamp_failures(src, "synthetic")
    check("a single-quoted interpolated stamp (last_verified: '{TODAY}') is caught",
          any(f.rule == RULE and "last_verified" in f.detail for f in fs))
    check("...and a single-quoted EMPTY field on the same template does not also fire",
          not any(f.rule == RULE and "verified_by" in f.detail for f in fs))
    check("...and it fires EXACTLY ONCE for last_verified -- not once for the assembled "
          "JoinedStr and again for the bare leftover-quote fragment ast.walk() visits "
          "separately at the interpolation boundary",
          sum(1 for f in fs if f.rule == RULE and "last_verified" in f.detail) == 1)


def _proof_unquoted_stamp_is_caught(check) -> None:
    """No generator in this corpus writes the bare-unquoted spelling today, but nothing
    stops a sixth one from doing so, and a scanner that reads quoted values only would
    silently agree an unquoted fabricated stamp was clean."""
    src = ("def doc_text(TODAY):\n"
           "    return f\"last_verified: {TODAY}\\nverified_by: morficflux\\n\"\n")
    fs = stamp_failures(src, "synthetic")
    check("a bare unquoted interpolated stamp (last_verified: {TODAY}, no quotes) is "
          "caught",
          any(f.rule == RULE and "last_verified" in f.detail for f in fs))
    check("...and a bare unquoted hardcoded literal (verified_by: morficflux) is caught "
          "the same way",
          any(f.rule == RULE and "verified_by" in f.detail for f in fs))


def _proof_docstrings_are_not_scanned(check) -> None:
    """An ingest script explaining, in its own docstring, the wrong shape it used to write
    -- exactly what THIS module's docstring does -- is not a second instance of writing it.
    The forbidden shape appears only inside the synthetic module's docstring below (using
    the single-quote spelling too, so this proof also covers that path through the
    docstring exemption); its actual write is the correct empty form."""
    src = ("'''DO NOT do what #295 found: never write\n"
           "last_verified: '{TODAY}'\n"
           "into a document.'''\n"
           "def doc_text():\n"
           "    return f'last_verified: \"\"\\nverified_by: \"\"\\n'\n")
    check("a forbidden shape quoted only inside a module docstring does not fire",
          not stamp_failures(src, "synthetic"))


def _proof_the_correct_form_passes(check) -> None:
    src = ('def doc_text():\n'
           '    return f"""last_verified: ""\n'
           'verified_by: ""\nmaintainer: "@morficflux"\n"""\n')
    check("the correct empty form raises nothing, including for a NEIGHBOURING field "
          "(maintainer) that legitimately carries a handle",
          not stamp_failures(src, "synthetic"))


def _proof_unparseable_is_could_not_check(check) -> None:
    fs = stamp_failures("def f(:\n    broken\n", "synthetic")
    check("a module that does not parse FAILS rather than passing as clean "
          "(could-not-check is never is-not-there)",
          any(f.rule == RULE for f in fs))


def _proof_population_is_a_glob_not_a_list(check) -> None:
    """#295's own root cause: `ingest_oar.py`'s fix did not stop the other four ingest
    scripts from carrying the same bug, because nothing scanned them together. Proved
    against a real file dropped into `src/` and removed again -- not merely against the
    glob call that defines `scannable_scripts()`, which could itself have been a hardcoded
    list and a pure-Python proof would not catch that. Named `zz_selftest_fixture...`, NOT
    `ingest_...` -- a review of this fix found the ORIGINAL population was `ingest_*.py`
    only and missed two real writers named outside that prefix; a fixture that happens to
    start with `ingest_` would no longer distinguish this proof from that narrower, already
    -disproven population."""
    fixture = SRC / "zz_selftest_fixture__do_not_commit.py"
    if fixture.exists():
        check("selftest fixture path was free to use before this proof ran", False)
        return
    try:
        fixture.write_text("# verification_stamp.py selftest fixture\nX = 1\n")
        check("a newly-created src/*.py is discovered with no name added anywhere, "
              "regardless of its name's prefix",
              fixture in scannable_scripts())
    finally:
        fixture.unlink(missing_ok=True)
    check("...and the fixture is cleaned up -- selftest leaves no residue",
          not fixture.exists())


def selftest() -> int:
    check = Checks()
    _proof_the_real_scripts_are_clean(check)
    _proof_the_ocr_scripts_are_in_population(check)
    _proof_interpolation_is_caught(check)
    _proof_a_hardcoded_literal_is_caught(check)
    _proof_single_quoted_stamp_is_caught(check)
    _proof_unquoted_stamp_is_caught(check)
    _proof_docstrings_are_not_scanned(check)
    _proof_the_correct_form_passes(check)
    _proof_unparseable_is_could_not_check(check)
    _proof_population_is_a_glob_not_a_list(check)
    # THE DECLARATION, GATED FROM BOTH SIDES (#319's `_LEDGER.gaps()`).
    gaps = _LEDGER.gaps()
    declared_gap = (f" (emitted-not-declared={sorted(gaps.emitted_but_undeclared)}, "
                     f"declared-not-emitted={sorted(gaps.unemitted_but_declared)})"
                     if gaps.emitted_but_undeclared or gaps.unemitted_but_declared else "")
    check("every rule this module can report is declared" + declared_gap, not declared_gap)
    unfired_gap = f" (unfired={sorted(gaps.unfired)})" if gaps.unfired else ""
    check("...and every declared rule was watched firing, not merely listed" + unfired_gap,
          not unfired_gap)
    return check.report(
        f"{_LEDGER.demonstrated_count} rule(s) declared and watched firing here; an "
        "interpolated stamp (double- and single-quoted), a hardcoded literal (quoted and "
        "bare), a docstring-only mention, an unparseable module, and a newly-discovered "
        "script under any name are each handled correctly, the two OCR scripts this "
        "module's docstring names are confirmed in the scanned population, and the real "
        "src/*.py agree with a clean scan -- selftest")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.check:
        return cmd_check()
    if a.selftest:
        return selftest()
    print(__doc__)
    for path in scannable_scripts():
        writes = field_writes(path.read_text()) or []
        stamped = {(f, v) for f, v in writes if v}
        state = "clean" if not stamped else f"FABRICATED: {sorted(stamped)}"
        print(f"  {_label(path)}: {state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
