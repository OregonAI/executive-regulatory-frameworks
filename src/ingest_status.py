#!/usr/bin/env python3
"""The one module owning the INGEST-status vocabulary -- whether this mirror holds a copy of
an OAR rule, and in what shape. NOT a rule's LEGAL status (`legal_status.py`, CONTEXT.md's
*Legal status* / *Ingest status* -- the two fields are spelled `status` and mean different
things, which is why both glossary entries exist).

  python3 src/ingest_status.py             # print the vocabulary and where it is written
  python3 src/ingest_status.py --check     # CI: the words ingest_oar.py/catalog_oar.py
                                            #     actually write are exactly the words
                                            #     declared here
  python3 src/ingest_status.py --selftest  # CI: the check above can fail, and fires

#333. One vocabulary, four declarations, measured on `main` at `b28bfac769`:

  legal_status.INGEST_STATUS_VALUES   6 words, gated against the writers' syntax trees by
                                       the rule `ingest-vocabulary-declared-once`
  catalog_oar.RULE_STATUSES           4 words, ungated -- missing `not_sliceable` and
                                       `needs_registry`
  CONTEXT.md's *Ingest status*        the same 4, ungated
  legal_status.HELD_INGEST_STATUSES   2 words, a partition of the six restated with nothing
                                       saying so

`ingest_oar.py` demonstrably writes both missing words (`r["status"] = "not_sliceable"`,
`r["status"] = "needs_registry"`); `catalog_oar.py --summary` bucketed rows in neither the
four-word declared vocabulary nor a legal status into `other`, which is the concrete failure
mode -- #282 already hit the same shape once, a word the pipeline writes landing in a
residual bucket on the repository's headline coverage number.

WHY THE GATED COPY LIVED IN `legal_status.py` AND WHY THAT WAS WRONG. `legal_status.py`
needed the ingest vocabulary for exactly one reason: `--check` refuses a catalog row where
`status` (ingest) and `legal_status` (legal) hold each other's words, and telling that apart
means knowing both vocabularies. Hosting the SECOND one there rather than importing it is
the precise collision CONTEXT.md's *Ingest status* entry keeps a whole `_Avoid_` line to
name: "Status, unqualified. The two fields share a name and mean different things, which is
why both entries exist." A module about legal status is not the place the ingest vocabulary
gets to live just because it is read from there too.

WHAT THIS MODULE OWNS, and no more:

  1. THE VALUE SET (`INGEST_STATUS_VALUES`) and the HELD/NOT-HELD PARTITION
     (`HELD_INGEST_STATUSES`), declared together as one structure (`_HELD_BY_VALUE` below)
     so a word cannot be added to one without saying, in the same place, whether this mirror
     still holds a rule carrying it -- the failure `HELD_INGEST_STATUSES` was in before this
     ticket, a bare second tuple with nothing connecting it to the six-word set it was a
     subset of.
  2. THE WRITERS' CENSUS (`ingest_vocabulary()`), read off the syntax trees of the two
     modules that write this field rather than trusted -- `ingest_oar.py` (`INGESTER`) and,
     since #276 retired `ingest_oar.py --enumerate`, `catalog_oar.py` (`DISCOVERER`), which
     is where `not_ingested` has been written from ever since.
  3. THE GATE (`check_vocabulary()`, rule `ingest-vocabulary-declared-once`), moved here
     verbatim from `legal_status.py` -- same comparison, same rule name, same Failure shape,
     now constructed by THIS module's own `check_rule_ledger` (#319) ledger rather than
     `legal_status`'s.

`legal_status.py` imports `INGEST_STATUS_VALUES` and `HELD_INGEST_STATUSES` from here rather
than restating them (it still needs both, to tell the two vocabularies apart on a catalog
row), and its own `cmd_check()` still calls `check_vocabulary(ingest_vocabulary())` from
here -- the CI step `legal_status.py --check` already wired into
`.github/workflows/validate-frontmatter.yml` keeps enforcing this rule with no workflow
change, because the enforcement moved with the code that decides it, not with the process
that happens to run it. `catalog_oar.py`'s own bucketing vocabulary (`RULE_STATUSES`, #282)
is gone as a separate declaration for the same reason -- it now reads `INGEST_STATUS_VALUES`
directly, so `--summary` buckets every row against the same six words this module and
`legal_status.py` do."""
import argparse
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from check_rule_ledger import RuleLedger
from repo_lib import REPO_ROOT, Checks, assigned_string_constants

SRC = REPO_ROOT / "src"

# THE VOCABULARY AND ITS PARTITION, ONE DECLARATION. Every word this field can hold, paired
# with whether it means THIS MIRROR STILL HOLDS A COPY of the rule -- a Bulletin-set legal
# status is a mark on a document that stays, and a row carrying one while its ingest status
# says this mirror no longer serves the rule is what DELETING the document leaves behind
# (ADR 0006's whole point is that deleting breaks every citation pointing at it). Declaring
# the partition AS PART OF the value set, rather than beside it, is what makes a word added
# here without an answer to "does this mean held?" IMPOSSIBLE TO WRITE AT ALL: a dict
# literal cannot carry a key with no value, so the omission is a `SyntaxError` at import
# time -- caught before the module even loads, never a silent gap the way a bare second
# tuple (`HELD_INGEST_STATUSES` used to be exactly that) could quietly fall behind the full
# set it was meant to be a subset of, which is the failure #333 exists to fix.
_HELD_BY_VALUE = {
    "ingested": True,
    "renumbered": True,
    "not_ingested": False,
    "not_served": False,
    "not_sliceable": False,
    "needs_registry": False,
}

# The full vocabulary, in declaration order (dict insertion order, Python's own guarantee).
INGEST_STATUS_VALUES = tuple(_HELD_BY_VALUE)

# DERIVED, not typed beside the full set: every word `_HELD_BY_VALUE` marks held, filtered
# out of `INGEST_STATUS_VALUES` rather than written as its own literal tuple. A second,
# independent two-word tuple is exactly what let this partition state only `ingested` and
# `renumbered` while the full set had grown to six words with nothing catching the gap.
HELD_INGEST_STATUSES = tuple(v for v in INGEST_STATUS_VALUES if _HELD_BY_VALUE[v])

# Where the vocabulary is written, and the only two modules allowed to write it. TWO, NOT
# ONE, SINCE #276: that ticket retired `ingest_oar.py --enumerate`, and with it the only
# place the pipeline wrote `not_ingested` -- membership is `catalog_oar.py`'s to write now,
# and it is where that word lives. Reading only the ingester would make the declaration
# above look like drift ("the ingester writes [...] and this module declares [...]") when
# nothing had drifted: one writer had moved. Both are read, and the union is what must match.
INGESTER = SRC / "ingest_oar.py"
DISCOVERER = SRC / "catalog_oar.py"

# EVERY RULE THIS MODULE CAN REPORT (#319/#333). Declared rather than counted at run time so
# a rule added with no proof is visible as a list that did not grow, and compared against
# what the code actually emits, read out of this module's own syntax tree -- the same
# both-directions gate `legal_status.py` and `catalog_agencies.py` already carry.
CHECK_RULES = (
    "ingest-vocabulary-declared-once",
)

# THE CHECK-RULE LEDGER (#319), adopted here rather than hand-rolled: recording a rule name
# when a Failure is built (`_LEDGER.fired`), the AST scan of this module's own source for
# the rule names it can EMIT (`_LEDGER.emitted_rules`), and the both-directions comparison
# of the two against `CHECK_RULES` (`_LEDGER.gaps()`) are `check_rule_ledger.py`'s one
# shared implementation, not a fourth hand-rolled copy of it.
_LEDGER = RuleLedger(CHECK_RULES, __file__)
Failure = _LEDGER.Failure
emitted_rules = _LEDGER.emitted_rules


def _label(path) -> str:
    try:
        return str(Path(path).relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def ingest_vocabulary(source=None) -> set:
    """Every word the pipeline assigns to a `status` key -- the INGEST vocabulary, read off
    the modules that write it rather than restated.

    TWO MODULES, since #276: `ingest_oar.py` writes what an ingest attempt concluded, and
    `catalog_oar.py` writes `not_ingested` when discovery names a rule nothing has fetched
    yet. Passing `source` reads that one text instead, which is what lets a rule be fired
    against a synthetic ingester.

    A module that does not parse yields the EMPTY set, which fails
    `ingest-vocabulary-declared-once` against a non-empty declaration rather than passing:
    a vocabulary this could not read is not a vocabulary with no words in it."""
    if source is None:
        out = set()
        for mod in (INGESTER, DISCOVERER):
            out |= ingest_vocabulary(mod.read_text())
        return out
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(isinstance(x, ast.Subscript) and isinstance(x.slice, ast.Constant)
                   and x.slice.value == "status" for x in node.targets):
                out |= assigned_string_constants(node.value)
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "status":
                    out |= assigned_string_constants(v)
    return out


def check_vocabulary(written) -> list:
    """The rule that this module's declared vocabulary still matches the writers'.

    `written` is what `ingest_vocabulary()` read out of `ingest_oar.py`/`catalog_oar.py`,
    passed in rather than read here so the rule can be fired against a synthetic writer."""
    declared = set(INGEST_STATUS_VALUES)
    if declared == set(written):
        return []
    return [Failure(
        "ingest-vocabulary-declared-once", str(_label(INGESTER)),
        f"the writers write {sorted(written) or '(nothing this could read)'} and this "
        f"module declares {sorted(declared)}. That declaration is the ONLY thing that tells "
        "an ingest status apart from a legal status on a catalog row, so a word on one side "
        "only stops the two fields named `status` from being distinguishable -- update "
        "INGEST_STATUS_VALUES, or stop a writer writing a word nobody declared")]


def report(failures) -> int:
    for f in failures:
        print(f"  FAIL [{f.rule}] {f.site}: {f.detail}", file=sys.stderr)
    return len(failures)


def cmd_check() -> int:
    written = ingest_vocabulary()
    failures = check_vocabulary(written)
    if report(failures):
        print(f"\n{len(failures)} ingest-vocabulary violation(s)", file=sys.stderr)
        return 1
    print(f"{len(INGEST_STATUS_VALUES)} ingest-status word(s) declared, matching what "
          f"{_label(INGESTER)} and {_label(DISCOVERER)} write: "
          + ", ".join(sorted(INGEST_STATUS_VALUES))
          + f"; {len(HELD_INGEST_STATUSES)} of them mean this mirror still holds the rule: "
          + ", ".join(HELD_INGEST_STATUSES))
    return 0


# ------------------------------------------------------------------------------ selftest


def _proof_the_partition_is_derived(check) -> None:
    check("the full vocabulary is the six words #333 measured",
          set(INGEST_STATUS_VALUES) == {"ingested", "renumbered", "not_served",
                                        "not_sliceable", "not_ingested", "needs_registry"})
    check("the held partition is the two words that mean this mirror still holds the rule",
          set(HELD_INGEST_STATUSES) == {"ingested", "renumbered"})
    check("every held word is a member of the full set -- a partition, not a second set",
          set(HELD_INGEST_STATUSES) <= set(INGEST_STATUS_VALUES))
    check("every declared word says whether it is held -- nothing is unaccounted for",
          set(_HELD_BY_VALUE) == set(INGEST_STATUS_VALUES))


def _proof_the_vocabulary_matches_the_real_writers(check) -> None:
    """The gate against the ACTUAL committed `ingest_oar.py`/`catalog_oar.py`, not only a
    fixture -- proving the declaration above is not merely internally consistent but agrees
    with what the pipeline writes today."""
    real = ingest_vocabulary()
    check("the declared vocabulary is what the real writers write",
          not check_vocabulary(real))
    check("...and it is not empty", bool(real))


def _proof_an_invented_word_is_caught(check) -> None:
    """`ingest-vocabulary-declared-once` moved here from `legal_status.py` -- proved against
    a synthetic writer so the rule is watched firing without touching the real pipeline."""
    # THE NARROWING THAT MAKES THIS READING TRUE. The ingester's division line is
    # `d["status"] = d.get("status") if any(r.get("status") == "ingested" for r in
    # d["rules"]) else "not_ingested"`, and a walk of every constant beneath it would report
    # `status` and `rules` as vocabulary if the test were not excluded from the read.
    divisionish = ('def f(d, r):\n'
                   '    d["status"] = d.get("status") if any(x.get("status") == "ingested"\n'
                   '                  for x in d["rules"]) else "not_ingested"\n')
    check("a conditional's test is not read as vocabulary",
          ingest_vocabulary(divisionish) == {"not_ingested"})
    # THE ACTUAL PROOF #333 ASKS FOR: a write site the ingester does not have today.
    invented = ('def cmd_ingest():\n'
               '    r["status"] = "invented_word"\n')
    check("a word a writer writes and this module has not declared is caught",
          any(f.rule == "ingest-vocabulary-declared-once"
              for f in check_vocabulary(ingest_vocabulary(invented))))
    check("...and so is a word declared here that no writer writes any more",
          any(f.rule == "ingest-vocabulary-declared-once"
              for f in check_vocabulary(set(INGEST_STATUS_VALUES) - {"needs_registry"})))
    # An unparseable writer yields no words, which must fail rather than agree with an
    # empty expectation -- could not check is never reported as is not there.
    check("a writer that does not parse is not a vocabulary of no words",
          ingest_vocabulary("def f(d)\n    d['status'] = 'ingested'\n") == set()
          and any(f.rule == "ingest-vocabulary-declared-once"
                  for f in check_vocabulary(set())))


def selftest() -> int:
    check = Checks()
    _proof_the_partition_is_derived(check)
    _proof_the_vocabulary_matches_the_real_writers(check)
    _proof_an_invented_word_is_caught(check)
    # THE DECLARATION, GATED FROM BOTH SIDES -- `_LEDGER.gaps()` (#319). A rule the code can
    # emit and `CHECK_RULES` does not name would go uncounted; a rule named there that
    # nothing above actually made fire is one nobody has watched work.
    gaps = _LEDGER.gaps()
    declared_gap = (f" (emitted-not-declared={sorted(gaps.emitted_but_undeclared)}, "
                    f"declared-not-emitted={sorted(gaps.unemitted_but_declared)})"
                    if gaps.emitted_but_undeclared or gaps.unemitted_but_declared else "")
    check("every rule this module can report is declared" + declared_gap,
          not declared_gap)
    unfired_gap = f" (unfired={sorted(gaps.unfired)})" if gaps.unfired else ""
    check("...and every declared rule was watched firing, not merely listed" + unfired_gap,
          not unfired_gap)
    return check.report(
        f"{_LEDGER.demonstrated_count} rule(s) declared, every one both emitted by this "
        "module and watched firing here; an invented word and a retired one both caught "
        "against a synthetic writer, and the real ingest_oar.py/catalog_oar.py agree with "
        "the declared vocabulary -- selftest")


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
