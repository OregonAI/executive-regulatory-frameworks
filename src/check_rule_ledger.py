#!/usr/bin/env python3
"""The check-rule ledger every full-pattern `--selftest` proves itself against (#319).

  python3 src/check_rule_ledger.py --selftest   # CI: every rule THIS module can fail, fails

WHY THIS EXISTS. `legal_status.py` and `stated_census.py` each hand-rolled the same four
pieces: a `Failure` type that records the rule name it was built under the moment it is
constructed (`_FIRED`, so no proof has to remember to say a rule fired); an AST scan of the
module's own source for every rule name a `Failure(...)` call site can EMIT
(`emitted_rules()`), read off the syntax tree rather than trusted, so the declared table
cannot silently drift from what the code actually does; and the both-directions comparison of
the two -- a rule DECLARED with no proof is invisible to one direction, a rule EMITTED with no
declaration is invisible to the other, and #306 found `stated_census.py` missing the second
direction entirely: an emitted-but-undeclared `Failure` passed its `--selftest` green.

ELEVEN MODULES COPY PART OF THIS BY HAND, IN THREE STRENGTHS (#319's own measurement, `main`
at d8de9f50a6, corrected by #323 -- the original count of ten missed `snapshot_identity` --
and by #320, which adopted the pattern in `catalog_agencies`, moving it out of the "neither"
bucket #319 measured it in): three have the full pattern (`legal_status`, `stated_census`,
`catalog_agencies`), two have `CHECK_RULES` and `_FIRED` with no AST scan (`reingest_oar`,
`bulletin_report` -- an emitted-but-undeclared refusal these two cannot catch), five have
`_FIRED` alone (`provenance_spelling`, `catalog_agreement`, `oar_watch_coverage`,
`seed_oar_watch`, `snapshot_identity`), and one has neither (`catalog_oar`). THIS TICKET
EXTRACTED THE SHAPE FROM THE TWO THAT ALREADY HAD IT WHOLE AND ADOPTED IT IN EXACTLY THOSE
TWO -- proving the extraction is faithful (identical `--check`/`--selftest` output, before
and after) is the point, and mixing
in a module that lacks the pattern would hide a regression behind a module's first-ever
findings. `catalog_agencies` and the rest are a later ticket's, not this one's.

`reingest_oar.py` and `bulletin_report.py` subclass `legal_status.Failure` directly (each
overriding `__new__` to record into ITS OWN `_FIRED` rather than `legal_status`'s -- see
either module's `Failure` docstring) and call `legal_status.emitted_rules(...)` by name. Both
predate this ticket and are OUT OF ITS SCOPE (#319's "no caller outside these two modules
changes") -- `legal_status.Failure` and `legal_status.emitted_rules` stay importable,
subclassable and callable exactly as they were, bound to a `RuleLedger` underneath rather than
hand-written, so neither of those two importers has anything to change.

WHAT THIS MODULE OWNS, and no more:

  1. RECORDING. `RuleLedger(check_rules, module_file).Failure` is a `namedtuple("Failure",
     "rule site detail")` subclass whose `__new__` refuses a rule not in `check_rules`
     (`ValueError`, so a typo in a rule name fails LOUD rather than passing an unmarked
     write silently through) and records the rule into `.fired` -- the LEDGER'S OWN set, not
     a module-level global, so two ledgers in the same process (two modules each importing
     this one) never let a rule that fired in one be reported as watched in the other.
  2. THE SCAN. `.emitted_rules(source=None)` walks the syntax tree of `module_file` (or
     `source`, a string, for a module's own `--selftest` to fire the scan against a synthetic
     module) and returns every string literal a `Failure(...)` call's first argument can
     evaluate to -- the same shape both modules carried before this ticket, unchanged.
  3. THE COMPARISON. `.gaps(source=None)` is the whole both-directions check as ONE call:
     which declared rules the scan does not find EMITTED (declared with no proof that could
     ever construct it), which emitted rules are not DECLARED (the code can report it and
     `CHECK_RULES` does not name it -- #306's hole), and which declared rules never actually
     FIRED in this process (declared and emittable, but no proof exercised it). A caller's
     `--selftest` still decides how to REPORT the three sets -- `legal_status.py`'s
     `Checks`-style PASS/FAIL lines and `stated_census.py`'s FAIL-only list are different
     shapes and stay different shapes; only the comparison that PRODUCES the sets is shared.
  4. THE COUNT. `.demonstrated_count` is `len(.fired)` -- how many declared rules were
     actually watched firing in this process, derived from what happened rather than kept as
     a literal a docstring or a summary line would otherwise have to hand-update in step with
     `CHECK_RULES`. Equal to `len(check_rules)` on any run where `.gaps()` reports clean, since
     that equality is exactly what a clean `.gaps()` means -- but stated as a MEASUREMENT
     rather than a restatement of the declaration, the same distinction AGENTS.md draws
     between a count that was asked and a count that was assumed.

WHAT THIS MODULE DOES NOT OWN. Every domain rule's NAME, its `CHECK_RULES` table, and what
condition makes it fire stay in the module that owns the domain -- a legal-status write's
one-writer rule and a stated figure's census-tag rule have nothing in common except this
shape, and folding the domains together would be the opposite of what #319 asks for."""
import argparse
import ast
import sys
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from repo_lib import Checks

# The both-directions comparison's result: every declared rule the scan could not find
# emitted, every emitted rule nothing declared, and every declared rule this process has not
# watched fire. A clean `--selftest` is one where all three come back empty.
Gaps = namedtuple("Gaps", "emitted_but_undeclared unemitted_but_declared unfired")


class RuleLedger:
    """One module's check-rule ledger: the rules it may declare (`check_rules`), the ones
    watched firing so far in this process (`fired`), a `Failure` type bound to both, and the
    scan + comparison used to gate them from both directions. #319."""

    def __init__(self, check_rules, module_file):
        self.check_rules = tuple(check_rules)
        self.module_path = Path(module_file)
        self.fired = set()

        # Closed over rather than read off `self` inside `Failure.__new__` -- a namedtuple
        # subclass's `__new__` is a classmethod-shaped callable and every construction is on
        # the hot path of every proof in both adopting modules, so this avoids an attribute
        # lookup through `self` (the ledger instance) on every single `Failure(...)` call.
        declared, fired = self.check_rules, self.fired

        class Failure(namedtuple("Failure", "rule site detail")):
            """One rule, the thing it is about, and what is wrong with it.

            Recorded on construction rather than at the call sites, so no proof has to
            remember to say it fired and no rule can be exempted from the count by being
            checked a new way. A rule not in `check_rules` refuses HERE, at construction,
            rather than being recorded and caught only later by `.gaps()` -- a typo in a rule
            name is a bug in the module that made it, and this is where that module finds
            out, the moment the call site actually runs."""

            __slots__ = ()

            def __new__(cls, rule, site, detail):
                if rule not in declared:
                    raise ValueError(
                        f"{rule!r} is not a declared rule -- add it to CHECK_RULES")
                fired.add(rule)
                return super().__new__(cls, rule, site, detail)

        self.Failure = Failure

    def emitted_rules(self, source=None) -> set:
        """Every rule name this module's OWN `Failure(...)` call sites can emit, read out of
        its syntax tree rather than trusted -- so `CHECK_RULES` is compared with what the code
        actually does, not with itself. `source=None` reads `module_path`; a string reads that
        text instead, which is what lets a module's `--selftest` fire this scan against a
        synthetic source carrying an extra, undeclared `Failure(...)` call."""
        tree = ast.parse(source if source is not None else self.module_path.read_text())
        return {n.args[0].value for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "Failure" and n.args
                and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)}

    def gaps(self, source=None) -> Gaps:
        """The both-directions comparison, as one call: which declared rules the scan does
        not find emitted, which emitted rules are not declared, and which declared rules this
        process has not watched fire. Empty in all three fields is the only state a clean
        `--selftest` may report."""
        declared = set(self.check_rules)
        emitted = self.emitted_rules(source)
        return Gaps(emitted_but_undeclared=emitted - declared,
                    unemitted_but_declared=declared - emitted,
                    unfired=declared - self.fired)

    @property
    def demonstrated_count(self) -> int:
        """How many declared rules have been watched firing in this process -- derived from
        `.fired` rather than restated as a literal, so a summary line cannot drift from what
        actually ran."""
        return len(self.fired)


# ------------------------------------------------------------------------------ selftest
#
# THIS MODULE'S OWN RULES ARE NOT A `CHECK_RULES` TABLE -- it is the infrastructure a domain
# module's table is checked against, not a domain itself, so there is nothing here for a
# `RuleLedger` to declare about its own behaviour. What follows proves the four things the
# module docstring says it owns, the same way every other `--selftest` in this repository
# proves its claims: by constructing the state that should pass, mutating it, and watching
# the mutation get caught.


def _fixture_source(*rule_names) -> str:
    """A synthetic module whose only content is one `Failure(name, "site", "detail")` call
    per name in `rule_names`, plus two shapes that must NOT be read as emitting anything: a
    call to a different function sharing none of `Failure`'s meaning, and a `Failure(...)`
    call whose first argument is not a string literal (a variable -- the narrowing
    `emitted_rules()` exists to keep, matching `legal_status.py`'s own proof of the same
    scanner)."""
    lines = [f'Failure({n!r}, "site", "detail")' for n in rule_names]
    lines.append('NotFailure("not-a-rule", "site", "detail")')
    lines.append('Failure(some_variable, "site", "detail")')
    return "\n".join(lines) + "\n"


def _proof_recording(check) -> None:
    ledger = RuleLedger(("a", "b"), __file__)
    f = ledger.Failure("a", "the-site", "the-detail")
    check("a Failure records the fields it was built with",
          (f.rule, f.site, f.detail) == ("a", "the-site", "the-detail"))
    check("...and is recorded into THIS ledger's fired set",
          ledger.fired == {"a"})
    ledger.Failure("b", "site-2", "detail-2")
    check("a second construction adds to the set rather than replacing it",
          ledger.fired == {"a", "b"})


def _proof_undeclared_rule_is_refused(check) -> None:
    ledger = RuleLedger(("a",), __file__)
    raised = None
    try:
        ledger.Failure("not-declared", "site", "detail")
    except ValueError as e:
        raised = e
    check("a rule not in check_rules refuses construction",
          raised is not None)
    check("...and the error names the rule",
          raised is not None and "not-declared" in str(raised))
    check("...and a refused construction is not recorded as fired",
          "not-declared" not in ledger.fired)


def _proof_two_ledgers_do_not_share_state(check) -> None:
    """THE PROPERTY `reingest_oar.py` AND `bulletin_report.py`'s OWN `Failure` DOCSTRINGS
    NAME BY HAND (`legal_status`'s `_FIRED` would let a rule that never fired in the
    subclassing module be reported as watched because a same-named rule fired in
    `legal_status`) -- proved here at the level THIS module can prove it: two ledgers
    declaring the SAME rule name are independent."""
    first, second = RuleLedger(("shared-name",), __file__), RuleLedger(("shared-name",), __file__)
    first.Failure("shared-name", "site", "detail")
    check("firing a rule in one ledger leaves a second, independent ledger unfired",
          first.fired == {"shared-name"} and second.fired == set())
    check("...and the second ledger's own gaps() still reports it unfired",
          "shared-name" in second.gaps(source="Failure('shared-name', 1, 2)\n").unfired)


def _proof_emitted_rules(check) -> None:
    ledger = RuleLedger(("x", "y"), __file__)
    emitted = ledger.emitted_rules(_fixture_source("x", "y"))
    check("every Failure(...) call's string literal rule name is found",
          emitted == {"x", "y"})
    check("a same-named call to a different function is not read as emitting anything",
          "not-a-rule" not in emitted)
    check("a Failure(...) call whose first argument is not a string literal emits nothing",
          len(emitted) == 2)
    check("a module with no Failure(...) call at all emits the empty set",
          ledger.emitted_rules("def f(x):\n    return x + 1\n") == set())


def _proof_emitted_rules_reads_module_path_by_default(check) -> None:
    """`source=None` reads `module_path`, not the caller's own file -- proved against a real
    temporary file rather than `__file__`, so a bug that silently ignored `module_path` and
    fell back to `Path(__file__)` would be caught rather than coincidentally passing because
    this module's own source contains no bare `Failure(...)` call of its own to confuse it
    with (it names the class through `self.Failure` throughout, never the bare identifier)."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "synthetic_module.py"
        p.write_text(_fixture_source("from-disk"))
        ledger = RuleLedger(("from-disk",), p)
        check("emitted_rules() with no source reads module_path off disk",
              ledger.emitted_rules() == {"from-disk"})


def _proof_gaps(check) -> None:
    ledger = RuleLedger(("a", "b", "c"), __file__)
    ledger.Failure("a", "site", "detail")  # only "a" fires
    # "a" and "b" are emitted (in the synthetic source), "c" is declared but emits nothing.
    got = ledger.gaps(source=_fixture_source("a", "b"))
    check("a declared rule the scan does not find emitted is named",
          got.unemitted_but_declared == {"c"})
    check("a rule emitted but never fired is named unfired, alongside one never emitted",
          got.unfired == {"b", "c"})
    check("a rule both declared and fired is named in neither gap",
          "a" not in got.unemitted_but_declared and "a" not in got.unfired)
    check("nothing here is emitted but undeclared -- the synthetic source names only "
          "declared rules", got.emitted_but_undeclared == set())

    # THE HOLE #306 FOUND: a rule the code can emit that CHECK_RULES does not name.
    undeclared = ledger.gaps(source=_fixture_source("a", "b", "an-undeclared-rule"))
    check("a rule the scan finds emitted with no declaration is caught",
          undeclared.emitted_but_undeclared == {"an-undeclared-rule"})

    # A clean ledger: everything declared is emitted and fired, nothing else is emitted.
    clean = RuleLedger(("only",), __file__)
    clean.Failure("only", "site", "detail")
    check("a ledger with every declared rule emitted and fired reports all three gaps empty",
          clean.gaps(source=_fixture_source("only")) == ((set(), set(), set())))


def _proof_demonstrated_count(check) -> None:
    ledger = RuleLedger(("a", "b"), __file__)
    check("a ledger nothing has fired in demonstrates zero",
          ledger.demonstrated_count == 0)
    ledger.Failure("a", "site", "detail")
    check("firing one declared rule moves the count to one",
          ledger.demonstrated_count == 1)
    ledger.Failure("b", "site", "detail")
    check("...and firing the second moves it again",
          ledger.demonstrated_count == 2)
    check("a clean ledger's demonstrated count equals its declared count",
          ledger.demonstrated_count == len(ledger.check_rules))


def orphaned_proofs(source) -> set:
    """Proof functions defined in this module that `selftest()` never calls (#324).

    The checks above can catch a mutation to code a proof exercises, but not a proof that
    was written and never wired into `selftest()` at all -- it never runs, so nothing above
    can turn it red. A proof nobody runs is indistinguishable from one that passes, and it
    is worse than no proof at all: the file reads as though the claim were watched. Same
    shape as `bulletin_report.py`'s own gate of this kind, and the same move
    `RuleLedger.emitted_rules()` already makes for rule names -- read off the syntax tree
    rather than trusted -- applied here to proof functions instead."""
    tree = ast.parse(source)
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name.startswith("_proof_")}
    body = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "selftest"), None)
    called = {n.func.id for n in ast.walk(body) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Name)} if body else set()
    return defined - called


def selftest() -> int:
    check = Checks()
    _proof_recording(check)
    _proof_undeclared_rule_is_refused(check)
    _proof_two_ledgers_do_not_share_state(check)
    _proof_emitted_rules(check)
    _proof_emitted_rules_reads_module_path_by_default(check)
    _proof_gaps(check)
    _proof_demonstrated_count(check)
    # AND EVERY PROOF IS ACTUALLY RUN (#324). The checks above compare declared rules
    # against emitted and fired rules, and neither can see a proof that was written and
    # never called -- exactly how a future `_proof_something_new` could sit in this file,
    # fully written, contributing nothing, while the selftest reported OK. This module is
    # what every adopting module's own rule discipline is checked against, so an unexercised
    # claim here is the worst place in the repo for one to hide.
    source = Path(__file__).read_text()
    check("a proof written in this file and never called is caught",
          orphaned_proofs(source.replace("    _proof_demonstrated_count(check)\n", ""))
          == {"_proof_demonstrated_count"})
    check("...and every proof written in this file is one selftest() calls",
          orphaned_proofs(source) == set())
    return check.report(
        "the check-rule ledger's own recording, scan, both-directions comparison and "
        "demonstrated count all watched working, and an undeclared rule refused at "
        "construction and caught by the scan alike -- selftest")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
