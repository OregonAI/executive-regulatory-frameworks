#!/usr/bin/env python3
"""The one writer of a rule's LEGAL STATUS, and the gate that fails if a second appears.

  python3 src/legal_status.py             # the census of every legal-status write in src/
  python3 src/legal_status.py --mark      # derive the catalog's legal statuses from the
                                          #     committed Oregon Bulletin worklist (#229),
                                          #     and NAME every rule whose force changed
  python3 src/legal_status.py --check     # CI: one writer, and the catalog and the
                                          #     documents agree about legal status
  python3 src/legal_status.py --selftest  # CI: every rule --check enforces fires

WHY THIS EXISTS. A rule document's `status` frontmatter field is corpus-toolkit's schema
enum -- `current | superseded | repealed | proposed | draft` -- and it is A CLAIM ABOUT
OREGON LAW (CONTEXT.md, *Legal status*). ADR 0006 gives it ONE writer, the Oregon Bulletin.

It had two. Measured on `main` the day this module landed:

  src/ingest_oar.py   `status: current` written as a hardcoded literal into every rule
                      document it creates -- 36,953 of them
  src/enrich_oar.py   `d["status"] = "repealed" if repealed else "current"`, derived from
                      the newest History action in the rule's own served text, stamped over
                      `^status: .*$` by `apply()` -- and COMPARED by `--check`, a gate that
                      runs nightly

That second one is not merely another writer: it is an enforcer. Once #229 records a repeal
the Bulletin filed against a rule whose OARD History line does not yet print one, the
enricher's rewrite mode would restamp the document `current` and its `--check` would fail
the build for the Bulletin being right. And once #230 re-ingests amendments automatically,
an amended rule runs straight through the ingester's literal -- silently resurrecting a rule
the Bulletin marked repealed, and publishing a false statement about Oregon law under
provenance. This is the two-writers failure that broke this repository's CI on 2026-08-22,
in the one form where the thing that drifts is not a derived view but a claim about law.

So the decision moves HERE, into `resolve()`, and both of those modules become readers of
it. Neither decides any more; each supplies what it knows and is told the answer.

THE ORDER OF AUTHORITY, and why each step sits where it does:

  1. the Bulletin      `bulletin=` -- the status the Oregon Bulletin set, carried on the OAR
                       catalog's rule entry (`legal_status`, see below). ADR 0006's writer.
                       NOTHING BELOW MAY OVERRIDE IT: that single fact is the whole safety
                       property #230 is blocked on.
  2. the rule's own    `history_repealed=` -- whether the NEWEST History action OARD prints
     served text       inside the rule says it was repealed. It is the rule's own text and
                       it beats what a document happens to hold, which is how the 2,031
                       documents reading `repealed` today came to say so.
  3. what the document `existing=` -- a caller that has learned nothing new keeps what the
     already says      document says rather than asserting over it. This is the state 39 of
                       the 36,953 rules are in: OARD prints no History line inside them, so
                       the enricher has read no history rather than one that is not a
                       repeal, and without this step it would restamp `current` over
                       whatever those documents said.
  4. `current`         nothing better is known. This is the ONLY thing this ticket lets a
                       fresh ingest assert, and it is what a first ingest of a rule OARD
                       serves normally has.

LEGAL STATUS IS NOT INGEST STATUS, and this is the failure mode of the whole area. Two
fields are spelled `status` and they mean different things (CONTEXT.md keeps two glossary
entries for exactly this reason):

  the document's `status`        whether the rule is IN FORCE -- a claim about Oregon law
  the catalog's `rules[].status` whether THIS MIRROR holds a copy, and in what shape:
                                 `ingested` (36,474), `not_ingested` (5,608, #270),
                                 `renumbered` (484), `not_served` (49)

A rule can be in force and absent here, or repealed and still held. So the Bulletin's claim
about force gets its OWN key on the catalog row -- `legal_status` -- and never borrows the
one already there. `--check` refuses either field holding the other's vocabulary, over all
42,615 committed rule entries, because the day those two collide the collision is invisible.

THE GATE IS AN ALLOWLIST, NOT A BLOCKLIST (CONTEXT.md's overriding rule). Any site in `src/`
that writes a legal-status value must say, where it sits, which of four things it is; a
site with no marker FAILS rather than being passed over, because an unmarked write is one
nobody has looked at and "could not check" is never reported as "is not there".

  WRITER              the site decides a rule's legal status. ONE MODULE MAY CARRY IT. A
                      second module carrying it is the failure this gate exists for, and it
                      fails the run.
  READER              the site STAMPS a legal status it was handed and decides nothing --
                      the enricher's line rewrite is the one such site. A reader may not
                      hold a legal-status literal of its own, and `--check` refuses one that
                      does, so "reader" cannot be used to smuggle a decision past the count.
  NOT-A-RULE          the site writes a status for something that is not an OAR rule -- an
                      executive order, an ORS section, a policy. ADR 0006 fixes the writer
                      of a RULE's legal status; those have their own sources and the
                      Bulletin is not one of them. The marker records that somebody checked
                      which corpus the site was writing into.
  NOT-A-LEGAL-STATUS  the `status` here is the catalog's ingest status, or another field
                      that shares the name. The marker is the place the two-fields-one-name
                      confusion has to be resolved out loud.

WHAT THIS GATE DOES NOT CLAIM. That a site's marker is TRUE -- a rule write mismarked
`NOT-A-RULE` reads to a scanner exactly like an executive order's. What it enforces is that
every site was read and its reading recorded next to it, and that no second module claims to
decide. The scan is also LITERAL-ONLY: it finds a legal-status value written as a constant,
so a status held in a variable and assigned from somewhere else passes it. It is deliberately
over-inclusive in the other direction -- every `status`-keyed write of one of those five
words, whatever corpus it is about -- because the cost of that is a marker on a site that
turns out to be an executive order's, and the cost of the other direction is a second writer
of Oregon law nobody knows about."""
import argparse
import ast
import re
import sys
import tempfile
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml

from repo_lib import REPO_ROOT, Checks

SRC = REPO_ROOT / "src"
CATALOG = REPO_ROOT / "_meta/catalog/oar.yml"
RULES_DIR = REPO_ROOT / "rules"

# corpus-toolkit's schema enum for a document's `status`. Not this repository's to extend:
# it is shared by every corpus, and #225 put renaming it out of scope.
LEGAL_STATUS_VALUES = ("current", "superseded", "repealed", "proposed", "draft")

# What a fresh ingest may assert, and only where nothing better is known (step 4 above).
UNKNOWN_BUT_SERVED = "current"

# The OAR catalog's OWN `status` vocabulary -- ingest status, a claim about this mirror.
# Declared here so `--check` can refuse either field holding the other's words, WHICH MAKES
# IT THE SAME FACT WRITTEN IN TWO PLACES: `ingest_oar.py` writes these words and this is a
# second copy of them, which is the shape this whole module exists to refuse. So it is not
# trusted. `ingest-vocabulary-declared-once` reads what the ingester actually writes, out of
# its syntax tree, and fails if the two sets differ -- the arrangement AGENTS.md already
# describes for `CADENCES` versus the `recheck` enum and for `CURATED_KEYS` versus `FIELDS`,
# where a value curated in one place and forgotten in the other is the failure. A word added
# to the ingester is caught by that rule the moment it is added, and by
# `ingest-status-is-known` again if it reaches the committed catalog first.
INGEST_STATUS_VALUES = ("ingested", "renumbered", "not_served", "not_sliceable",
                        "not_ingested", "needs_registry")

# The ingest statuses that mean THIS MIRROR STILL HOLDS THE RULE. A Bulletin-set legal
# status is a mark on a document that stays; a row carrying one while saying this mirror
# no longer serves the rule is what DELETING the document leaves behind, and ADR 0006's
# whole point is that deleting breaks every citation pointing at it.
HELD_INGEST_STATUSES = ("ingested", "renumbered")

# Where that vocabulary is written, and the only module allowed to write it.
INGESTER = SRC / "ingest_oar.py"
# THE INGEST VOCABULARY IS WRITTEN BY TWO MODULES, NOT ONE, SINCE #276. That ticket
# retired `ingest_oar.py --enumerate`, and with it the only place this pipeline wrote
# `not_ingested` -- membership is now `catalog_oar.py`'s to write, and it is where that
# word lives. Reading only the ingester made the declaration below look like drift
# (CI: "the ingester writes [...] and this module declares [...]") when nothing had
# drifted: one writer had moved. Both are read, and the union is what must match.
DISCOVERER = SRC / "catalog_oar.py"

# The catalog key carrying a Bulletin-set legal status. Deliberately NOT `status`.
CATALOG_KEY = "legal_status"

# WHAT A FILED ACTION DOES TO A RULE'S FORCE. The mapping lives HERE, in the one writer,
# because the mapping IS the decision: a module that turned `repeal` into `repealed` and
# handed the answer to `resolve()` would be deciding a rule's legal status somewhere else,
# and ADR 0006 allows one place. Only the two actions that change FORCE are here --
# `adopt`, `amend` and `renumber` change TEXT and are #230's, which is the split ADR 0006
# makes and the reason this table is not simply every verb `check_bulletin.ACTIONS` names.
#
# A SUSPENSION IS NOT A REPEAL, and the schema enum cannot say what it is. Its five words
# are `current | superseded | repealed | proposed | draft`; `repealed` is the only one that
# names a loss of force and it means a PERMANENT one. Every suspension this corpus holds
# text for prints an END DATE -- its History text reads `temporary suspend filed ...,
# effective ... THROUGH ...` -- so writing `repealed` for one is a claim the corpus can
# disprove from its own committed text, and #229 forbids it in as many words. THE COUNT IS
# DELIBERATELY NOT RESTATED HERE: an earlier version of this comment pinned it as a literal
# (185, then drifted to 248) with nothing rechecking a number written in prose -- the same
# failure #307 exists to close, one level up. `temporary_suspension_counts()` below is the
# one place that count is computed, and `document_status_census()`'s printed line and
# CONTEXT.md's *Filed force action* entry are where it is stated; this comment does not
# restate it again, so it cannot drift a third time. Leaving
# `current` is the other direction and it is worse: CONTEXT.md defines this field as
# WHETHER THE RULE IS IN FORCE, and corpus-toolkit's consumers print `current` with no
# warning at all while printing anything else as "not current text". So the enum carries
# the part it can say -- THIS IS NOT THE OPERATIVE TEXT RIGHT NOW -- and the part it cannot
# is carried beside it in the catalog's `legal_status_action`, which is what tells a
# suspension from a repeal and is why that key exists rather than being derivable.
# The missing enum member is filed upstream as corpus-toolkit#159, not papered over
# here, and this comment is what a reader follows when that issue is settled.
#
# LEGAL STATUS - WRITER: this table is the decision, and `force_status()` below is
# the only reader of it.
FORCE_ACTIONS = {"repeal": "repealed", "suspend": "superseded"}

# The catalog keys that say WHERE a Bulletin-set legal status came from. `legal_status` is
# a claim about Oregon law and a claim about law with no citation is unattributable; these
# are what a human follows to check it, and `legal-status-cites-its-notice` requires them.
ACTION_KEY = "legal_status_action"
NOTICE_KEY = "legal_status_notice"

# The three keys a marked row states, IN THE ORDER THEY ARE WRITTEN, declared once so the
# writer, the gates and REVIEW.md read the same list. `legal-status-cites-its-notice`
# requires all three or none: a status with no notice is a claim about Oregon law nobody
# can check, and an action with no status is a filing recorded as having changed nothing.
MARKED_KEYS = (CATALOG_KEY, ACTION_KEY, NOTICE_KEY)

# The Oregon Bulletin's monthly worklist -- the NOTICE a legal status is derived from
# (ADR 0006). Read here and written nowhere: `check_bulletin.py` is its one writer.
WORKLIST = REPO_ROOT / "_meta/bulletin-worklist.yml"

# What re-derives the catalog from that notice, quoted by every rule that can
# only be fixed by running it.
REGENERATE = "python3 src/legal_status.py --mark && python3 src/enrich_oar.py"

MARKER_RE = re.compile(r"LEGAL STATUS\s+[-–—]+\s+([A-Z][A-Z_-]*)")
PURPOSES = ("WRITER", "READER", "NOT-A-RULE", "NOT-A-LEGAL-STATUS")

# How far above a write its marker may sit when the write is not inside a function, matching
# `name_readers.py`: the comment blocks in this codebase are long and one marker legitimately
# covers a small group of writes. Inside a function the marker may also sit anywhere at or
# below the `def` -- see `scan_source`.
MARKER_WINDOW = 30

# Not a purpose: what a module is marked with when the scan could not read it at all. It
# fails like an unmarked write, under its own rule, because the two are different states.
UNREADABLE = "UNREADABLE"

# Proof code is not a writer. A fixture that hands `resolve()` a synthetic Bulletin status,
# or a selftest source written to break a rule, states something about this gate rather than
# about any document -- and demanding WRITER next to it would put the marker on code that
# writes nothing. ANCHORED, and narrowly: an unanchored `fixture` alternative would exempt a
# production `load_fixture_rows()` from a gate whose whole rule is that an unmarked write
# fails, and an exemption nobody marked is the thing this module refuses everywhere else.
PROOF_FUNCTIONS = re.compile(r"^(selftest|_case_|_proof_|_fixture)")

FRONTMATTER_RE = re.compile(r"^\s*status:\s*(" + "|".join(LEGAL_STATUS_VALUES) + r")\s*$")

Site = namedtuple("Site", "path line text function purpose")

# Every rule name a Failure has been built under in this process. `--selftest` asserts that
# it covers `CHECK_RULES`, which is the difference between a rule DECLARED and a rule
# WATCHED FIRING: the declaration alone could be satisfied by adding a name to two lists,
# and a refusal nobody has seen fire is not known to work.
_FIRED = set()


class Failure(namedtuple("Failure", "rule site detail")):
    """One rule, the thing it is about, and what is wrong with it.

    Recorded on construction rather than at the call sites, so no proof has to remember to
    say it fired and no rule can be exempted from the count by being checked a new way."""

    __slots__ = ()

    def __new__(cls, rule, site, detail):
        _FIRED.add(rule)
        return super().__new__(cls, rule, site, detail)

# EVERY RULE THIS MODULE CAN REPORT, and each is demonstrated failing by a proof below.
# Declared rather than counted at run time so a rule added with no proof is visible as a
# list that did not grow -- and compared against what the code actually emits, read out of
# this module's own syntax tree by `emitted_rules()`, so the declaration cannot drift from
# it. `--selftest` asserts both that this list is what the code can emit and that every
# name on it was watched firing during the run -- `_FIRED`, recorded by `Failure` itself.
CHECK_RULES = (
    # the census -- who may decide a rule's legal status, and where
    "readable-module", "legal-status-write-classified", "known-purpose",
    "a-reader-decides-nothing", "one-writer",
    # the two fields spelled `status`, and this module's copy of the other one's words
    "two-fields-named-status", "ingest-status-is-known", "bulletin-status-is-known",
    "ingest-vocabulary-declared-once",
    # a marked row: what it must say, and that the document still carries it
    "legal-status-cites-its-notice", "legal-status-action-is-known",
    "legal-status-derives-from-the-action", "a-marked-rule-is-still-served",
    "the-document-reads-it", "legal-status-agrees",
    # the notice, and the half no rule about an existing row can state
    "catalog-reaches-the-rule", "a-filed-force-action-is-recorded",
    "the-notice-names-the-filing", "the-notice-is-readable",
)


# ------------------------------------------------------------------- the one writer


def resolve(*, bulletin=None, history_repealed=None, existing=None) -> str:
    """The legal status a rule document must carry. THE ONLY PLACE THIS IS DECIDED.

    Every argument is what one caller happens to know, and `None` means "this caller has
    nothing to say", which is a different thing from `False`: `history_repealed=False` is
    an OARD History line read and found not to be a repeal, and `history_repealed=None` is
    a caller that never looked at one.

    See the order of authority in this module's docstring. The first step is the safety
    property the rest of the Bulletin work rests on and it is asserted here, not implied:
    a Bulletin-set status is RETURNED UNCHANGED whatever else the caller supplies."""
    # LEGAL STATUS - WRITER: this is that one place. Nothing below step 1 may override it.
    if bulletin is not None:
        if bulletin not in LEGAL_STATUS_VALUES:
            raise ValueError(
                f"{bulletin!r} is not a legal status ({', '.join(LEGAL_STATUS_VALUES)}) -- "
                "the OAR catalog's `status` field is INGEST status and its vocabulary is "
                "not this one (CONTEXT.md, *Legal status* / *Ingest status*)")
        return bulletin
    if history_repealed is not None:
        return "repealed" if history_repealed else UNKNOWN_BUT_SERVED
    if existing in LEGAL_STATUS_VALUES:
        return existing
    return UNKNOWN_BUT_SERVED


def force_status(action: str):
    """The legal status a filed ACTION puts a rule in, or None if it changes no force.

    THE OTHER HALF OF THE ONE WRITER. `resolve()` weighs what several callers know about a
    rule; this turns the Bulletin's verb into the thing `resolve()` is handed. Both live
    here because both are the decision ADR 0006 gives one place."""
    # LEGAL STATUS - WRITER: the action-to-force table above is a decision about Oregon
    # law and this is the only place it is read.
    return FORCE_ACTIONS.get(action)


def bulletin_status_by_rule(catalog=None) -> dict:
    """{rule number: legal status} for every catalog rule entry the Bulletin has set one on.

    EMPTY TODAY, and that is a state rather than an oversight: #229 is what records a filed
    repeal here. `--check` prints the count on every run so the day it stops being zero is
    visible, and so a rule that silently went back to zero is too."""
    return {r["number"]: r[CATALOG_KEY] for r in catalog_rules(catalog)
            if r.get(CATALOG_KEY) is not None}



def filed_force_actions(worklist) -> dict:
    """{rule number: (legal status, the action that caused it)} for every force action one
    bulletin filed against a rule this corpus HOLDS.

    ONE PLACE, read by the writer and by the gate that checks the writer ran. A second
    copy of this precedence would let `mark()` and `check_filings()` disagree about what
    the same month says, which is the one fact written twice this module exists to refuse.

    A PERMANENT LOSS OF FORCE BEATS A TEMPORARY ONE, IN EITHER ORDER. One month can file
    both against one rule, and taking the rows in file order would make the answer depend
    on which was written second -- a repealed rule left `superseded` because its suspension
    came after is a permanent loss of force served as a recoverable one, this ticket's
    failure mode inverted."""
    filed = {}
    for row in (worklist.get("rules") or []):
        if not isinstance(row, dict) or row.get("corpus_state") != "held":
            continue
        status = force_status(row.get("action"))
        if status is None:
            continue
        prior = filed.get(row.get("number"))
        if prior is None or (prior[0] != FORCE_ACTIONS["repeal"]
                             and status == FORCE_ACTIONS["repeal"]):
            filed[row["number"]] = (status, row["action"])
    return filed


def catalog_force_action_counts(catalog=None) -> dict:
    """How many committed OAR catalog rows carry each Bulletin-filed FORCE action
    (`legal_status_action`) -- CONTEXT.md's *Legal status* and *Filed force action*
    entries' "66 repeals and 34 suspensions" (#307 code review: `cmd_check()` already
    prints exactly this `Counter` every run, so those two figures sat as `observed:` marks
    only because nothing exposed the count it was already computing by name).

    Named categories, THE ZEROES INCLUDED (AGENTS.md) -- every action `FORCE_ACTIONS`
    knows, not just the ones the catalog currently holds, so an action that happens to be
    zero this month reads as measured rather than as never asked. A row with no
    Bulletin-set `legal_status` at all (the overwhelming majority of the catalog) carries no
    action and is not counted -- this is a census of FILED ACTIONS, not of rules.

    `catalog=None` reads the committed OAR catalog; `--selftest` passes a synthetic one
    built the same way every other proof in this module does (`_fixture_catalog`)."""
    counts = {a: 0 for a in FORCE_ACTIONS}
    total = 0
    for r in catalog_rules(catalog):
        if r.get(CATALOG_KEY) is None:
            continue
        counts[r.get(ACTION_KEY)] = counts.get(r.get(ACTION_KEY), 0) + 1
        total += 1
    counts["total"] = total
    return counts


def mark(catalog, worklist) -> tuple:
    """Write every force action the Bulletin filed against a rule this corpus HOLDS onto
    its OAR catalog row. Returns (rows changed, Problems).

    MARKED, NEVER DELETED (ADR 0006). Nothing here removes a document, a path or an ingest
    status: this corpus mirrors ORS sections that cite administrative rules, and a citation
    resolves through the catalog row and the file it names. What changes is three keys on
    a row that keeps everything else it had.

    THE CATALOG WRITES AND THE DOCUMENT READS. This function stops at the catalog;
    `enrich_oar.py` stamps the document from `bulletin_status_by_rule()`, so a legal status
    is decided in one place and written into 36,953 files from one other.

    A ROW IS ONLY WRITTEN FOR A RULE RECORDED `held`. A claim about Oregon law needs a
    document to carry it, and `the-document-reads-it` refuses a row stating one for a
    document nobody can find -- so a repeal filed against a chapter this corpus never
    mirrored is left alone rather than recorded as a fact nothing here serves.

    Both arguments are passed in rather than read here, so `--selftest` can fire the whole
    write against a synthetic bulletin and a synthetic catalog."""
    rows = {r["number"]: r for r in catalog_rules(catalog) if r.get("number")}
    filed, problems = filed_force_actions(worklist), []
    for number in sorted(set(filed) - set(rows)):
        problems.append(Failure(
            "catalog-reaches-the-rule", f"{number}",
            f"the Bulletin filed a {filed[number][1]} against it and the OAR catalog "
            "names no such rule, so there is no row to write the status onto and no "
            "document to stamp it from. The catalog writes and the document reads -- a "
            "rule reachable from neither is drift, not an accident"))
        filed.pop(number)

    notice, changed = worklist.get("bulletin"), 0
    for number, (status, action) in filed.items():
        row = rows[number]
        if tuple(row.get(k) for k in MARKED_KEYS) == (status, action, notice):
            continue
        # LEGAL STATUS - WRITER: the three keys, written together. The status is what the
        # document reads; the action is the part of the fact the schema enum cannot hold
        # (a suspension is not a repeal); the notice is the citation that makes a claim
        # about Oregon law checkable. `legal-status-cites-its-notice` refuses any of the
        # three arriving without the others.
        for key, value in zip(MARKED_KEYS, (status, action, notice)):
            row[key] = value
        changed += 1
    return changed, problems


def catalog_rules(catalog=None):
    """Every rule entry in the OAR catalog, flat."""
    cat = catalog if catalog is not None else yaml.safe_load(CATALOG.read_text())
    for ch in cat.get("chapters") or []:
        for d in ch.get("divisions") or []:
            rules = d.get("rules")
            if not isinstance(rules, list):
                continue
            yield from rules


# ------------------------------------------------------------------- the census


def _frontmatter_writes(lines):
    """Lines writing a legal status as a frontmatter literal -- `status: current` inside a
    document template.

    Read off the TEXT rather than the syntax tree, unlike everything below it: these sit
    inside multi-line f-strings, where the constant chunk carrying the line begins many
    lines above it and an AST position would put the marker window over the wrong code."""
    for i, line in enumerate(lines, 1):
        if FRONTMATTER_RE.match(line.split("#")[0].rstrip()):
            yield i


def _assigned_constants(node) -> set:
    """The string constants an expression can EVALUATE TO, rather than merely mention.

    `"repealed" if gone else "current"` yields both; `[r for r in rows if r["status"] ==
    "current"]` yields none, and the difference is a filter versus a decision. The narrowing
    matters in both directions -- a walk of every constant under the node reports the test of
    a conditional as though it were the answer, and `d["status"] = d.get("status") if
    any(r.get("status") == "ingested" for ...) else "not_ingested"` would name `ingested`,
    `status` and `rules` as vocabulary the ingester writes."""
    if isinstance(node, ast.Constant):
        return {node.value} if isinstance(node.value, str) else set()
    if isinstance(node, ast.IfExp):
        return _assigned_constants(node.body) | _assigned_constants(node.orelse)
    if isinstance(node, ast.BoolOp):
        return set().union(*(_assigned_constants(v) for v in node.values))
    return set()


def _yields_a_status(node) -> bool:
    """Whether an expression evaluates to a legal-status literal."""
    return bool(_assigned_constants(node) & set(LEGAL_STATUS_VALUES))


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
                out |= _assigned_constants(node.value)
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "status":
                    out |= _assigned_constants(v)
    return out


def emitted_rules(source=None) -> set:
    """Every rule name this module can report, read out of its own syntax tree.

    So that `CHECK_RULES` -- the list `--selftest` counts its proofs against -- is compared
    with what the code actually emits rather than trusted. A rule added to `check_committed`
    or `check_filings` and to no proof is a rule nobody has watched fire, and the whole
    discipline here is that a refusal nobody has seen fire is not known to work. Same
    arrangement as `ingest-vocabulary-declared-once` one field over."""
    tree = ast.parse(source if source is not None else Path(__file__).read_text())
    return {n.args[0].value for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "Failure" and n.args
            and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)}


def _status_key_writes(tree):
    """Lines assigning a legal-status word to something named `status`.

    Through the syntax tree, because the shapes differ and the text does not distinguish
    them: `d["status"] = "repealed" if repealed else "current"`, `{"status": "repealed"}`,
    `status = "current"`, `f(status="draft")`. A READ of the key writes nothing and is not
    a site -- this gate is about who decides, not about who looks."""
    def decides(value):
        return any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                   and n.value in LEGAL_STATUS_VALUES for n in ast.walk(value))

    def names_status(target):
        if isinstance(target, ast.Subscript):
            return isinstance(target.slice, ast.Constant) and target.slice.value in (
                "status", CATALOG_KEY)
        if isinstance(target, ast.Name):
            return target.id in ("status", CATALOG_KEY)
        if isinstance(target, ast.Attribute):
            return target.attr in ("status", CATALOG_KEY)
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and decides(node.value):
            if any(names_status(t) for t in node.targets):
                yield node.lineno
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if names_status(node.target) and decides(node.value):
                yield node.lineno
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value in ("status", CATALOG_KEY)
                        and decides(v)):
                    yield k.lineno
                # A MAPPING ONTO A LEGAL STATUS DECIDES ONE, whatever its keys are called.
                # `{"repeal": "repealed", "suspend": "superseded"}` turns the Bulletin's
                # verb into a claim about Oregon law and names no key `status` anywhere,
                # so every rule above it passed over the most consequential table #229
                # adds -- and that table is the shape the next second writer takes.
                # Narrower than `decides()` on purpose, and asymmetric: the VALUE must be
                # the status. A dict KEYED by one (`{"repealed": "no longer in force"}`)
                # is a lookup that writes nothing, and reporting it would put this gate on
                # every consumer that renders the field.
                elif _yields_a_status(v):
                    yield (k or v).lineno
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in ("status", CATALOG_KEY) and decides(kw.value):
                    yield kw.value.lineno
        # A FUNCTION THAT RETURNS ONE DECIDES ONE. Without this the strongest write in the
        # repository would be invisible to its own gate: `resolve()` below assigns nothing
        # and keys nothing -- it hands the answer back -- so a scan looking only for
        # assignments would report a corpus with no writer at all and pass. Narrower than
        # `decides()` on purpose: the RETURNED VALUE must be the status, not merely contain
        # the word, or `return [r for r in rows if r["status"] == "current"]` -- a filter
        # that writes nothing -- would be reported as a write of Oregon law.
        elif isinstance(node, ast.Return) and node.value is not None \
                and _yields_a_status(node.value):
            yield node.lineno


def _status_line_rewrites(tree):
    """Lines rewriting a document's existing `status:` line in place -- the `re.sub` shape
    the enricher stamps 36,953 files with.

    Its VALUE is not a constant, so nothing above finds it, and it is the most powerful
    write in the repository: it replaces whatever a document already said."""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("sub", "subn")):
            continue
        if any(isinstance(a, ast.Constant) and isinstance(a.value, str)
               and re.search(r"\bstatus:", a.value) for a in node.args):
            yield node.lineno


def _enclosing_functions(tree):
    """{line: (innermost function name, its `def` line)} for every line inside a body."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                out[line] = (node.name, node.lineno)
    return out


def scan_source(path: str, source: str) -> list:
    """Every legal-status write in one module, with the marker classifying it (or None).

    A module that does not PARSE is reported as one unreadable site rather than skipped:
    it is a module this scan could not read, which is not the same as one with no writes."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [Site(path, e.lineno or 0, f"module does not parse: {e.msg}", None,
                     UNREADABLE)]
    lines = source.splitlines()
    functions = _enclosing_functions(tree)
    markers = {}
    for i, line in enumerate(lines, 1):
        m = MARKER_RE.search(line)
        if m:
            markers[i] = m.group(1)

    found = set(_frontmatter_writes(lines)) | set(_status_key_writes(tree)) \
        | set(_status_line_rewrites(tree))
    sites = []
    for line in sorted(found):
        function, def_line = functions.get(line, (None, line))
        if function and PROOF_FUNCTIONS.search(function):
            continue
        # WHERE A MARKER MAY SIT: within `MARKER_WINDOW` lines above the write, or ANYWHERE
        # IN THE SAME FUNCTION. The second half is not a loosening for its own sake -- four
        # of the writes this gate found are `status: current` lines inside multi-line
        # frontmatter templates, where a `#` comment cannot be placed at all -- it would be
        # written into every document -- so the nearest line that can carry one is the
        # comment block above the function, up to 42 lines away.
        start = min(line, def_line) - MARKER_WINDOW
        near = [n for n in markers if start <= n <= line]
        sites.append(Site(path, line, lines[line - 1].strip(), function,
                          markers[max(near)] if near else None))
    return sites


def _label(path) -> str:
    try:
        return str(Path(path).relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def census(paths=None) -> list:
    """Every legal-status write in src/, in file and line order."""
    paths = sorted(paths if paths is not None else SRC.glob("*.py"))
    sites = []
    for p in paths:
        sites += scan_source(_label(p), Path(p).read_text())
    return sites


def _holds_a_status_literal(text: str) -> bool:
    """Whether a source line names one of the five legal-status words inside a string.

    Word-bounded and quote-bounded so `d["status"]` and a variable called `current_rules`
    do not read as literals -- what is being looked for is the WORD written out as a value,
    which is what deciding a status looks like."""
    return any(re.search(rf"""['"]{v}['"]|:\s*{v}\b""", text) for v in LEGAL_STATUS_VALUES)


def check_sites(sites) -> list:
    """Every way the census violates the one-writer contract, as Failures."""
    failures = []
    for s in sites:
        if s.purpose == UNREADABLE:
            failures.append(Failure(
                "readable-module", f"{s.path}:{s.line}",
                f"{s.text} -- no legal-status write in it could be evaluated, which is not "
                "the same as its having none"))
        elif s.purpose is None:
            failures.append(Failure(
                "legal-status-write-classified", f"{s.path}:{s.line}",
                f"writes a legal status with no marker within {MARKER_WINDOW} lines above "
                f"it or anywhere in its function: {s.text[:70]!r}. A rule's `status` is a "
                f"claim about Oregon law and ADR 0006 gives it one writer -- mark the site "
                f"`LEGAL STATUS - {'|'.join(PURPOSES)}` and say which it is"))
        elif s.purpose not in PURPOSES:
            failures.append(Failure(
                "known-purpose", f"{s.path}:{s.line}",
                f"marked {s.purpose!r}, which is not one of {', '.join(PURPOSES)}"))
        # THE ESCAPE HATCH, CLOSED. Without this a second writer could keep its hardcoded
        # `status: repealed` and call itself a reader, and the one-writer count -- which
        # only counts modules carrying WRITER -- would report one writer and pass. A reader
        # is a site that stamps a value it was handed, so it holds no legal-status word of
        # its own, and that is mechanically checkable where the marker's truth is not.
        elif s.purpose == "READER" and _holds_a_status_literal(s.text):
            failures.append(Failure(
                "a-reader-decides-nothing", f"{s.path}:{s.line}",
                f"marked READER and holds the legal-status literal it claims to have been "
                f"handed: {s.text[:70]!r}. A site that names the status is deciding it -- "
                "mark it WRITER and it will be counted, or take the literal out"))

    # THE RULE THIS MODULE EXISTS FOR. Counted over MODULES and not over sites: the one
    # writer legitimately decides in more than one place inside its own file, and what may
    # not happen is a SECOND FILE claiming to decide.
    writers = sorted({s.path for s in sites if s.purpose == "WRITER"})
    if len(writers) > 1:
        for path in writers:
            failures.append(Failure(
                "one-writer", path,
                f"{len(writers)} modules write legal status and ADR 0006 allows ONE: "
                f"{', '.join(writers)}. Two writers drift, and the thing that drifts here "
                "is a claim about Oregon law -- an amended rule running through a second "
                "writer's `current` resurrects one the Bulletin marked repealed. Route this "
                "site through `legal_status.resolve()` and mark it READER, or say which of "
                "the other purposes it is"))
    return failures


# ------------------------------------------------------------------- committed data


def check_vocabulary(written) -> list:
    """The rule that this module's copy of the ingest vocabulary still matches the ingester's.

    `written` is what `ingest_vocabulary()` read out of `ingest_oar.py`, passed in rather
    than read here so the rule can be fired against a synthetic ingester."""
    declared = set(INGEST_STATUS_VALUES)
    if declared == set(written):
        return []
    return [Failure(
        "ingest-vocabulary-declared-once", str(_label(INGESTER)),
        f"the ingester writes {sorted(written) or '(nothing this could read)'} and this "
        f"module declares {sorted(declared)}. That second copy is the ONLY thing that tells "
        "an ingest status apart from a legal status here, so a word on one side only stops "
        "the two fields named `status` from being distinguishable -- update "
        "INGEST_STATUS_VALUES, or stop the ingester writing a word nobody declared")]


def check_committed(catalog, doc_status) -> list:
    """Every way the COMMITTED data breaks the one-writer arrangement, as Failures.

    `doc_status` is {rule number: the document's `status`}, passed in rather than read here
    so the rules can be fired against fixtures by `--selftest`. A number ABSENT from it is
    a document this run could not read, which is reported rather than skipped."""
    failures = []
    for r in catalog_rules(catalog):
        num = r.get("number")
        ingest, legal = r.get("status"), r.get(CATALOG_KEY)

        # THE TWO FIELDS NAMED `status`, kept apart by measurement rather than by the
        # glossary alone. A catalog row saying `status: repealed` is a claim about Oregon
        # law written into the field that means "does this mirror hold a copy", and the day
        # it happens nothing else in the repository would notice.
        if ingest is not None and ingest in LEGAL_STATUS_VALUES:
            failures.append(Failure(
                "two-fields-named-status", f"{num}",
                f"catalog `status: {ingest}` is a LEGAL status in the field that means "
                f"INGEST status ({', '.join(INGEST_STATUS_VALUES)}). A rule can be in force "
                f"and absent here, or repealed and still held -- a Bulletin-set status "
                f"belongs in `{CATALOG_KEY}` (CONTEXT.md, *Legal status* / *Ingest status*)"))
        if ingest is not None and ingest not in INGEST_STATUS_VALUES \
                and ingest not in LEGAL_STATUS_VALUES:
            failures.append(Failure(
                "ingest-status-is-known", f"{num}",
                f"catalog `status: {ingest}` is not one of the ingest-status words this "
                f"module knows ({', '.join(INGEST_STATUS_VALUES)}). A word in neither "
                "vocabulary is one nothing here can tell a claim about this mirror from a "
                "claim about Oregon law by -- if `ingest_oar.py` writes it, "
                "`ingest-vocabulary-declared-once` will name it too; if nothing does, it is "
                "a value nobody declared"))
        if legal is not None and legal in INGEST_STATUS_VALUES:
            failures.append(Failure(
                "two-fields-named-status", f"{num}",
                f"catalog `{CATALOG_KEY}: {legal}` is an INGEST status in the field that "
                f"means LEGAL status ({', '.join(LEGAL_STATUS_VALUES)})"))
        elif legal is not None and legal not in LEGAL_STATUS_VALUES:
            failures.append(Failure(
                "bulletin-status-is-known", f"{num}",
                f"{legal!r} is not one of corpus-toolkit's {', '.join(LEGAL_STATUS_VALUES)}"))

        # WHERE THE CLAIM CAME FROM. `legal_status` is the Oregon Bulletin's word for
        # whether a rule is in force, and a claim about Oregon law with no citation is
        # unattributable -- nobody can check it and nothing can tell it from a value
        # somebody typed. The ACTION is not decoration either: it is the half of the fact
        # corpus-toolkit's five-word enum has no room for, so a row that loses it can no
        # longer tell a suspension from a repeal (ADR 0006, and #229's whole point).
        action, notice = r.get(ACTION_KEY), r.get(NOTICE_KEY)
        # ALL THREE OR NONE, counted rather than tested pairwise. Written as
        # `(legal is not None) != (bool(action) and bool(notice))` this rule PASSED a row
        # carrying an action alone -- both sides came out false, so a row saying a repeal
        # was filed while saying no rule lost its force and naming no bulletin read as
        # clean. A guard that fires on the wrong condition is one nobody can tell from a
        # guard that works, and this one was watched failing on each of the three keys
        # only after it was written to count them.
        present = [k for k, v in ((CATALOG_KEY, legal), (ACTION_KEY, action),
                                  (NOTICE_KEY, notice)) if v is not None]
        if present and len(present) != len(MARKED_KEYS):
            failures.append(Failure(
                "legal-status-cites-its-notice", f"{num}",
                f"holds {', '.join(present)} and not "
                f"{', '.join(k for k in MARKED_KEYS if k not in present)}. "
                "The three are one record and arrive together: the status is what the "
                "document reads, the action is what the schema enum cannot say, and the "
                "notice is the bulletin a human opens to check the claim. Any of them "
                "without the others is a statement about Oregon law nobody can follow -- "
                f"re-derive with: {REGENERATE}"))
        elif legal is not None and action not in FORCE_ACTIONS:
            failures.append(Failure(
                "legal-status-action-is-known", f"{num}",
                f"{ACTION_KEY}={action!r} changes no rule's FORCE. The Bulletin's actions "
                f"that do are {', '.join(sorted(FORCE_ACTIONS))}; an adoption, an "
                "amendment or a renumber changes TEXT, which re-ingests on its own "
                "(ADR 0006) and is not a claim anybody set a legal status from"))
        elif legal is not None and force_status(action) != legal:
            failures.append(Failure(
                "legal-status-derives-from-the-action", f"{num}",
                f"is recorded {action!r} and {legal!r}, and a {action} makes a rule "
                f"{force_status(action)!r}. The two are ONE FACT WRITTEN TWICE and this is "
                "the gate on their agreement -- a row reading `suspend` beside `repealed` "
                "publishes a temporary loss of force as a permanent one, which is the "
                "substitution #229 exists to prevent"))
        # MARKED, NEVER DELETED. The catalog row is what a citation resolves through, so a
        # row that carries a repeal while saying this mirror no longer holds the rule is
        # the deletion ADR 0006 refuses, recorded as though it were the marking.
        if legal is not None and ingest not in HELD_INGEST_STATUSES:
            failures.append(Failure(
                "a-marked-rule-is-still-served", f"{num}",
                f"carries {CATALOG_KEY}={legal!r} and ingest status {ingest!r}, which is "
                f"not one of {', '.join(HELD_INGEST_STATUSES)}. ADR 0006 marks a repealed "
                "rule and KEEPS it: this corpus mirrors ORS sections that cite "
                "administrative rules, and a row that stops naming a served document "
                "breaks every citation pointing at it while still looking answered"))

        # ONE FACT DECLARED TWICE, AND THE GATE ON THEIR AGREEMENT. The catalog is the
        # writer and the document is a reader (ADR 0006); a document that stopped agreeing
        # with the row it was stamped from is the drift this arrangement is supposed to make
        # detectable rather than accidental.
        if legal in LEGAL_STATUS_VALUES:
            if num not in doc_status:
                failures.append(Failure(
                    "the-document-reads-it", f"{num}",
                    f"the catalog says the Bulletin set {legal!r} and no document could be "
                    "read to carry it. A row stating a legal status for a document nobody "
                    "can find asserts something about Oregon law that nothing serves -- "
                    "could not check is never reported as is not there"))
            elif doc_status[num] != legal:
                failures.append(Failure(
                    "legal-status-agrees", f"{num}",
                    f"the catalog says the Bulletin set {legal!r} and the document says "
                    f"{doc_status[num]!r}. The catalog writes and the document reads -- "
                    "re-stamp it rather than editing the document by hand"))
    return failures



def check_filings(catalog, worklist) -> list:
    """The rule that makes every other rule here unsatisfiable by doing nothing.

    Everything in `check_committed` checks a row that EXISTS. Strip the three keys off all
    100 of them and every one of those rules passes on a corpus publishing 66 repealed
    rules as `current` -- a gate a blank field satisfies, which is the shape #226 and #228
    both had to close. This one reads the NOTICE and asks what is missing from the catalog,
    so the only way to satisfy it is to have done the work.

    Both directions, because they fail differently. A filing nothing recorded serves a
    rule that lost its force as though it had not; a row citing this month's bulletin for
    a filing the bulletin does not contain is a claim with a citation that does not support
    it, which is worse than an uncited one because it looks checked.

    SCOPED TO THE BULLETIN THIS WORKLIST HOLDS. This corpus keeps one month's worklist at a
    time, so a row citing an earlier bulletin is one this run has nothing to read it
    against -- it is left alone rather than reported, because could not check is never
    reported as is not there."""
    # NOTHING TO CHECK AGAINST IS NOT A CLEAN BILL. A worklist this could not read yields
    # no filings, and no filings is exactly what a corpus with nothing outstanding looks
    # like -- so the gate refuses rather than reporting the catalog complete on the
    # strength of having read nothing. Its SHAPE is `check_bulletin.py --check`'s to
    # report; this says only that the notice could not be read here.
    rules = worklist.get("rules") if isinstance(worklist, dict) else None
    if not isinstance(rules, list) or not rules:
        return [Failure(
            "the-notice-is-readable", _label(WORKLIST),
            f"holds no rule actions ({rules!r}), so nothing here can say which repeals and "
            "suspensions the catalog is missing. Every bulletin measured has named "
            "hundreds; a worklist that cannot be read and a month in which nothing was "
            "filed are different things -- run: python3 src/check_bulletin.py")]
    rows = {r["number"]: r for r in catalog_rules(catalog) if r.get("number")}
    notice = worklist.get("bulletin")
    filed = filed_force_actions(worklist)
    failures = []
    for number, (status, action) in sorted(filed.items()):
        row = rows.get(number)
        # A number the catalog does not name is `check_bulletin.py --check`'s
        # `catalog-knows-the-rule`, and reporting it twice would put one defect in two
        # gates' counts.
        if row is None:
            continue
        held = tuple(row.get(k) for k in MARKED_KEYS)
        if held != (status, action, notice):
            failures.append(Failure(
                "a-filed-force-action-is-recorded", f"{number}",
                f"{notice} filed a {action} against it and this corpus holds the rule, and "
                f"its catalog row says {held!r} rather than "
                f"{(status, action, notice)!r}. Until the row says so the document is "
                f"served as though nothing had happened -- run: {REGENERATE}"))
    for number, row in sorted(rows.items()):
        if row.get(NOTICE_KEY) == notice and number not in filed:
            failures.append(Failure(
                "the-notice-names-the-filing", f"{number}",
                f"cites {notice!r} for a {row.get(ACTION_KEY)!r} that bulletin filed "
                "against no rule this corpus holds. A claim about Oregon law whose "
                "citation does not support it is worse than one with no citation, because "
                "it looks checked"))
    return failures


# The `status:` line of a rule document, read off the text. The whole frontmatter is not
# parsed here for one field: `mark_upstream_tracking --check` reads 36,953 rules in about
# two seconds this way and a YAML parse of the same set costs thirty. Applied to the
# FRONTMATTER BLOCK ONLY -- a rule's verbatim text can print `status:` at the start of a
# line, and a body line read as the document's legal status would report a disagreement
# that is not there.
DOC_STATUS_RE = re.compile(r"^status:\s*(\S+)\s*$", re.M)
FRONTMATTER_BLOCK_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def doc_status_by_rule(catalog, numbers) -> dict:
    """{rule number: the document's `status`} for the rules asked about, and NOTHING ELSE.

    Scoped to the rules the catalog states a Bulletin-set legal status for, because those
    are the only ones there is a second declaration of the fact to compare against -- and
    because reading all 36,953 documents to check a handful is what turns a per-run gate
    into one somebody moves to the nightly tier and stops watching.

    A rule whose row names no path, or whose file is unreadable or prints no `status:`
    line, is LEFT OUT rather than defaulted, so `check_committed` reports it."""
    want = set(numbers)
    out = {}
    for r in catalog_rules(catalog):
        if r.get("number") not in want or not r.get("path"):
            continue
        p = REPO_ROOT / r["path"]
        try:
            head = p.read_text()[:8000]
        except OSError:
            continue
        block = FRONTMATTER_BLOCK_RE.match(head)
        if not block:
            continue
        m = DOC_STATUS_RE.search(block.group(1))
        if m:
            out[r["number"]] = m.group(1)
    return out


def rule_number(doc_id: str) -> str:
    """`oar-125-010-0005` -> `125-010-0005`, the key both the OAR catalog and the Bulletin
    worklist use. One place, because two call sites slicing `[4:]` by hand is the same
    second copy this module refuses everywhere else."""
    return doc_id[4:] if doc_id.startswith("oar-") else doc_id


# ------------------------------------------------------- the document-level censuses (#307)
#
# `census()` ABOVE COUNTS SOMETHING ELSE WEARING THE SAME WORD. It walks `src/*.py` and
# counts WRITE SITES -- lines of code that decide a legal status. The two functions below
# walk `rules/` and count STATUS VALUES -- what the committed DOCUMENTS actually say. A
# module writing legal status once and a corpus holding 42,561 claims about it are
# different facts, and #304 found both pinned by hand in CONTEXT.md with nothing behind
# either. Giving the second one `census()`'s name would make the collision this comment is
# about invisible again the next time someone reads the function list and assumes there is
# one census per module; two names for two measurements is the fix, not a docstring apology
# next to an overloaded one.

TEMP_SUSPEND_FULL_RE = re.compile(
    r"temporary suspend filed \d{2}/\d{2}/\d{4}, effective \d{2}/\d{2}/\d{4} "
    r"through \d{2}/\d{2}/\d{4}")
# The shorter phrase alone -- every occurrence of this is a filed temporary suspension,
# whether or not this corpus's own text goes on to record where it ends. Compared against
# `TEMP_SUSPEND_FULL_RE`'s count rather than trusted alone: an OPEN-ENDED suspension (filed,
# in force, with no closing date on record yet) would match this and not that, and the two
# counts are reported side by side so a gap between them is a visible fact rather than a
# silent undercount hiding inside one number.
TEMP_SUSPEND_MENTION_RE = re.compile(r"temporary suspend filed")


def _rule_document_paths() -> list:
    """Every committed rule document's path -- `rules/oar-*.md` rather than `rules/*.md`,
    which also matches `rules/_index.md` and `rules/CHANGELOG.md`: two files that are not
    claims about Oregon law and whose absence of a `status:` line would otherwise be
    reported as a corpus gap rather than left out as never having been one. #229's own
    worklist reader (`check_bulletin.py`) already names this glob `RULES_DIR` for the same
    reason; this module gets its own constant because it is a different corpus of callers
    and `import check_bulletin` for one glob would be the heavier dependency.

    REFUSES rather than returning an empty list if the walk could not run at all --
    `rules/` missing, or present but yielding nothing. Either state is NOT a corpus that
    was measured and found to hold zero documents, and the two document-level censuses
    below printing "0 rule document(s)" on that state would be exactly the substitution
    AGENTS.md's overriding rule forbids: a fetch that failed reported as a measurement of
    zero (#307 code review)."""
    if not RULES_DIR.is_dir():
        raise RuntimeError(
            f"{RULES_DIR} is not a directory -- refusing to report the document-level "
            "legal-status censuses as zero when the corpus could not be walked. Could not "
            "check is never reported as is not there (AGENTS.md).")
    paths = sorted(RULES_DIR.rglob("oar-*.md"))
    if not paths:
        raise RuntimeError(
            f"{RULES_DIR} exists but no oar-*.md documents were found in it -- same "
            "refusal, for the same reason: a walk that found nothing here is not "
            "distinguishable from one that could not run, so it may not be reported as "
            "the corpus's true zero.")
    return paths


def _rule_document_texts() -> list:
    """The full text of every committed rule document, via `_rule_document_paths()`.
    Kept as a convenience for a caller wanting only ONE of the two document-level
    censuses (both accept `texts=` for exactly this); the live-corpus path wanting BOTH
    together is `document_censuses()` below, which reads each document once and does not
    hold every document's text in memory at once the way materializing this list does."""
    return [p.read_text() for p in _rule_document_paths()]


def _status_key(text: str) -> str:
    """The `status:` value off a single document's FRONTMATTER BLOCK ONLY -- shared by
    `document_status_counts()` and `document_censuses()` so the classification rule is
    written once, not once per caller. See `document_status_counts()` for why frontmatter-
    only matters (a rule's own served text can print a body line that starts `status:`)."""
    block = FRONTMATTER_BLOCK_RE.match(text)
    m = DOC_STATUS_RE.search(block.group(1)) if block else None
    return m.group(1) if m else "no_status"


def _temp_suspend_matches(text: str) -> tuple:
    """`(full, mentions, lines)` for a single document's History text -- shared by
    `temporary_suspension_counts()` and `document_censuses()`, same reason as
    `_status_key()`. See `temporary_suspension_counts()` for what each of the three
    counts."""
    full = len(TEMP_SUSPEND_FULL_RE.findall(text))
    mentions = len(TEMP_SUSPEND_MENTION_RE.findall(text))
    lines = sum(1 for line in text.splitlines() if TEMP_SUSPEND_MENTION_RE.search(line))
    return full, mentions, lines


def document_censuses(paths=None) -> tuple:
    """`(document_status_counts(), temporary_suspension_counts())`, computed TOGETHER IN
    ONE PASS over the corpus -- the live-corpus path both `cmd_check()` and
    `stated_census._legal_status_docs_measurement()` call for both censuses at once.

    Reads each committed document's text once and discards it before the next, rather than
    materializing every document's text into a list first and handing it to both counting
    functions in turn (what this replaced at those two call sites): #307 code review
    measured that list-of-texts shape at 2.3x peak RSS -- 268MB->633MB for `legal_status.py
    --check`, 267MB->625MB for `stated_census.py --check` -- against roughly a one-second
    difference in wall time from reading the corpus's 42,561 files twice, which is the
    trade the list shape was defending and the wrong one at this corpus's size.

    NOT A THIRD COPY OF THE COUNTING LOGIC: `_status_key()` and `_temp_suspend_matches()`
    are the SAME per-document classifiers `document_status_counts()` and
    `temporary_suspension_counts()` call, so a rule added to either is a rule this function
    also sees. Kept as a third function rather than folding the two together, because those
    two stay independently provable against synthetic texts with no disk access at all
    (`_proof_document_status_counts`, `_proof_temporary_suspension_counts`); this one is the
    disk-facing composition of both, proved separately (`_proof_document_censuses`).

    `paths=None` walks every committed `rules/oar-*.md` (`_rule_document_paths()`);
    `--selftest` passes a list of objects carrying `.read_text()` instead -- the same
    interface a `pathlib.Path` offers, so a real path and a fixture are interchangeable
    here."""
    if paths is None:
        paths = _rule_document_paths()
    status_counts = {v: 0 for v in LEGAL_STATUS_VALUES}
    status_counts["no_status"] = 0
    total = full = mentions = lines = 0
    for p in paths:
        text = p.read_text()
        total += 1
        key = _status_key(text)
        status_counts[key] = status_counts.get(key, 0) + 1
        f, m, l = _temp_suspend_matches(text)
        full += f
        mentions += m
        lines += l
    status_counts["total"] = total
    return status_counts, {"full": full, "filed_mentions": mentions, "lines": lines}


def document_status_counts(texts=None) -> dict:
    """The `status:` distribution over every committed rule document -- CONTEXT.md's *Legal
    status* entry's "40,442 current / 2,085 repealed / 34 superseded" (#307). A DIFFERENT
    MEASUREMENT FROM `census()` ABOVE, wearing the same word -- see this section's banner
    comment.

    Every value in `LEGAL_STATUS_VALUES` is a named key, THE ZEROES INCLUDED (AGENTS.md): a
    schema word this corpus currently holds none of must still read as a measured zero, not
    as a key absent because nobody asked. `no_status` counts a document whose frontmatter
    block carries no `status:` line at all -- read the same way `doc_status_by_rule` does,
    off the FRONTMATTER BLOCK ONLY, because a rule's own served text can print a line that
    starts `status:` in its body (the exact case `_proof_only_frontmatter_is_read_for_a_
    status` exists to prove `doc_status_by_rule` does not misread), and a bare frontmatter
    value this module has no name for -- a schema drift nothing else here would catch --
    surfaces under its own literal key rather than being folded into `no_status` and hidden.

    `texts=None` reads the committed corpus (`_rule_document_texts()`); `--selftest` passes
    a list of synthetic document strings instead, so this can be proved without touching
    disk."""
    if texts is None:
        texts = _rule_document_texts()
    counts = {v: 0 for v in LEGAL_STATUS_VALUES}
    counts["no_status"] = 0
    total = 0
    for text in texts:
        total += 1
        key = _status_key(text)
        counts[key] = counts.get(key, 0) + 1
    counts["total"] = total
    return counts


def document_status_census(texts=None, counts=None) -> str:
    """`document_status_counts()`, formatted -- printed by `--check` on every run, the same
    reason `catalog_agencies.py`'s `*_census()` functions are (#306's own precedent): a
    figure that can only be watched NOT changing is one nobody can tell from a figure that
    stopped being measured. FORMATS the dict rather than measuring anything itself, so this
    sentence and a `census:legal_status_docs.status_*` tag elsewhere can never disagree
    about what the corpus holds.

    `counts=None` computes it (`document_status_counts(texts)`); a caller that already has
    the dict -- `cmd_check()`, from `document_censuses()` -- passes it directly rather than
    re-deriving it, so formatting a printed line never re-reads the corpus."""
    c = counts if counts is not None else document_status_counts(texts)
    named = ", ".join(f"{c[v]} {v}" for v in LEGAL_STATUS_VALUES)
    return f"{c['total']} rule document(s): {named} ({c['no_status']} carry no status: line)"


def temporary_suspension_counts(texts=None) -> dict:
    """How many times committed rule documents' History text reads `temporary suspend
    filed …, effective … through …` -- CONTEXT.md's *Filed force action* entry's figure for
    why a suspension is stamped `superseded` rather than `repealed` (#307): every suspension
    Oregon files carries an end date, which is the fact this counts.

    `full` AND `filed_mentions` COUNT OCCURRENCES, NOT LINES, and `lines` IS THE SEPARATE
    FIGURE FOR THAT: a rule amended and re-suspended more than once prints every filing on
    the SAME History line, so an occurrence count and a line count can differ (measured on
    the committed corpus: 248 occurrences on 241 distinct lines -- #307 code review found
    the prose calling the occurrence count "History lines", which is wrong for three
    documents that print more than one filing on one line). Naming the occurrence counts a
    line count would be wrong for what they measure, which is why neither this docstring nor
    `temporary_suspension_census()`'s printed sentence calls `full` or `filed_mentions` a
    line.

    `full` is the complete shape (a filed date AND a recorded effective/through pair);
    `filed_mentions` is the bare `temporary suspend filed` phrase alone, which every `full`
    match is also an instance of. THE TWO ARE REPORTED SEPARATELY ON PURPOSE -- see
    `TEMP_SUSPEND_MENTION_RE`'s comment -- so a suspension filed with no closing date on
    record yet would move `filed_mentions` without moving `full`, visibly, rather than being
    silently absorbed into one count that cannot tell the two shapes apart. On the corpus
    committed here today the two agree; a future filing that makes them diverge is exactly
    what keeping both is for. `lines` is keyed to `filed_mentions` (the loosest pattern),
    not `full`, so a filing with no recorded closing date still counts as its own line.

    `texts=None` reads the committed corpus; `--selftest` passes synthetic strings."""
    if texts is None:
        texts = _rule_document_texts()
    full = mentions = lines = 0
    for text in texts:
        f, m, l = _temp_suspend_matches(text)
        full += f
        mentions += m
        lines += l
    return {"full": full, "filed_mentions": mentions, "lines": lines}


def temporary_suspension_census(texts=None, counts=None) -> str:
    """`temporary_suspension_counts()`, formatted -- printed by `--check` on every run,
    same reason `document_status_census()` is, `counts=` included."""
    c = counts if counts is not None else temporary_suspension_counts(texts)
    return (f"{c['full']} temporary-suspend History occurrence(s) read in full "
            f"(effective ... through ...); {c['filed_mentions']} `temporary suspend filed` "
            f"mention(s) in all, across {c['lines']} distinct History line(s)")


# ------------------------------------------------------------------- commands


def report(failures) -> int:
    """Print every failure and return the count. One printer, because both commands print
    the same shape and a second copy is where the two spellings drift apart."""
    for f in failures:
        print(f"  FAIL [{f.rule}] {f.site}: {f.detail}", file=sys.stderr)
    return len(failures)


def load_worklist():
    """The committed Oregon Bulletin worklist, or None where it could not be read.

    Read only: `check_bulletin.py` is its one writer. A file that is absent or unparseable
    comes back as None rather than as a traceback, so `the-notice-is-readable` names the
    rule -- a gate that dies instead of naming its rule is what #226 exists to close."""
    try:
        return yaml.safe_load(WORKLIST.read_text())
    except (OSError, yaml.YAMLError):
        return None


def cmd_check() -> int:
    sites = census()
    catalog = yaml.safe_load(CATALOG.read_text())
    worklist = load_worklist()
    bulletin_set = bulletin_status_by_rule(catalog)
    failures = (check_sites(sites) + check_vocabulary(ingest_vocabulary())
                + check_committed(catalog, doc_status_by_rule(catalog, bulletin_set))
                + check_filings(catalog, worklist))
    if report(failures):
        print(f"\n{len(failures)} legal-status violation(s)", file=sys.stderr)
        return 1
    writers = sorted({s.path for s in sites if s.purpose == "WRITER"})
    n_rules = sum(1 for _ in catalog_rules(catalog))
    # THE CENSUS LINE, printed on every clean run, because a rule that can only be watched
    # NOT firing is one nobody can tell from a rule that stopped running. The Bulletin-set
    # count was zero until #229 recorded the August 2026 bulletin's 66 repeals and 34
    # suspensions; it is on screen so a run that silently went back to zero is visible.
    print(f"{len(sites)} legal-status write(s) across "
          f"{len({s.path for s in sites})} module(s), every one marked: "
          + ", ".join(f"{p.lower()} {sum(1 for s in sites if s.purpose == p)}"
                      for p in PURPOSES))
    print(f"one writer: {writers[0] if writers else 'NONE'}")
    # MEASURED, not asserted. A summary line whose last number is the literal `0` says
    # nothing a clean run does not already imply, and this ticket is about facts stated
    # twice with nothing checking they agree.
    crossed = sum(1 for r in catalog_rules(catalog)
                  if r.get("status") in LEGAL_STATUS_VALUES
                  or r.get(CATALOG_KEY) in INGEST_STATUS_VALUES)
    print(f"{n_rules} catalog rule entr(ies) checked; {len(bulletin_set)} carr(y) a "
          f"Bulletin-set `{CATALOG_KEY}`, every one STILL SERVED by a document that "
          f"could be read and agrees with it; {crossed} hold the other field's vocabulary")
    # BY ACTION, because that is the distinction the schema enum cannot make. A single
    # count of "rules out of force" would let 34 suspensions become 34 repeals with the
    # total unchanged, which is exactly the collapse #229 forbids. `catalog_force_action_
    # counts()` is also the reader `stated_census.py` resolves a `census:legal_status_docs.
    # filed_*` tag against (#307 code review), so this printed line and CONTEXT.md's prose
    # can never quietly disagree about what the catalog holds.
    by_action = catalog_force_action_counts(catalog)
    print(f"{by_action['total']} rule(s) marked out of force by the Bulletin: "
          + ", ".join(f"{a} {by_action[a]} ({force_status(a)})" for a in sorted(FORCE_ACTIONS))
          + f"; {len(filed_force_actions(worklist))} filed by "
          f"{worklist.get('bulletin')}, every one recorded")
    # THE TWO DOCUMENT-LEVEL CENSUSES (#307), printed the same way every other census in
    # this run is: a figure `stated_census.py` resolves a `census:legal_status_docs.*` tag
    # against, so CONTEXT.md's prose and this line can never quietly disagree about what
    # the corpus holds. `census()` above counted WRITE SITES; this counts STATUS VALUES.
    # ONE PASS OVER THE CORPUS, shared by both, AT FLAT MEMORY -- see `document_censuses()`.
    status_counts, temp_counts = document_censuses()
    print(document_status_census(counts=status_counts))
    print(temporary_suspension_census(counts=temp_counts))
    return 0


def cmd_mark() -> int:
    """Derive the catalog's legal statuses from the committed worklist, and SAY SO.

    A REPEAL OR SUSPENSION REACHES A PERSON (ADR 0006). An amendment is a text refresh the
    provenance chain already verifies and #230 re-ingests without asking; a claim about
    FORCE is not applied silently, so every rule this changes is named here, and
    `review_queue.py` puts the standing list in REVIEW.md where the other items needing
    human attention live. corpus-toolkit#67 exists because a notice on stderr is a notice
    nobody read."""
    catalog = yaml.safe_load(CATALOG.read_text())
    worklist = load_worklist()
    # THE SAME REFUSAL THE GATE MAKES, on the write side. A worklist this could not read
    # names no filings, and marking nothing would leave the catalog looking derived.
    unreadable = [f for f in check_filings(catalog, worklist)
                  if f.rule == "the-notice-is-readable"]
    if report(unreadable):
        return 1
    changed, problems = mark(catalog, worklist)
    if report(problems):
        print(f"\n{len(problems)} rule(s) the Bulletin named and the catalog cannot reach",
              file=sys.stderr)
        return 1
    marked = sorted((r["number"], r[ACTION_KEY], r[CATALOG_KEY])
                    for r in catalog_rules(catalog) if r.get(CATALOG_KEY) is not None)
    for action in sorted(FORCE_ACTIONS):
        rules = [m for m in marked if m[1] == action]
        print(f"\n{action}: {len(rules)} rule(s) -> status {force_status(action)!r}")
        for number, _, _ in rules:
            print(f"  OAR {number}")
    print(f"\n{worklist.get('bulletin')}: {worklist.get('bulletin_url')}")
    print(f"{changed} catalog row(s) rewritten, {len(marked)} marked in all. THE CATALOG "
          "WRITES AND THE DOCUMENT READS -- stamp the documents with: "
          "python3 src/enrich_oar.py")
    CATALOG.write_text(yaml.safe_dump(catalog, sort_keys=False, allow_unicode=True,
                                      width=100))
    return 0


def cmd_census() -> int:
    sites = census()
    for path in sorted({s.path for s in sites}):
        print(path)
        for s in sorted((x for x in sites if x.path == path), key=lambda x: x.line):
            print(f"  {s.line:>5}  {str(s.purpose or 'UNMARKED'):<20} {s.text[:60]}")
    print(f"\n{len(sites)} site(s) across {len({s.path for s in sites})} module(s)")
    for p in PURPOSES + (None,):
        print(f"  {str(p or 'UNMARKED').lower():<22} "
              f"{sum(1 for s in sites if s.purpose == p)}")
    return 0


# ------------------------------------------------------------------------------ selftest
#
# THE PROOF THAT EVERYTHING ABOVE CAN FAIL. Two of these are the only way their criteria can
# be shown at all -- introducing a second writer, and a re-ingest overwriting a status the
# Bulletin set are both things you prove by BREAKING the arrangement and watching, never by
# adding code. Every source below is synthetic; every fixture lives in a function this
# module's own scan excludes as proof code (`PROOF_FUNCTIONS`), which is why the
# `status: current` lines inside them are not counted as writes of this module's own.


def _fixture_sources() -> dict:
    """{case name: a synthetic module}, each written to break exactly one rule.

    Kept inside a function so the frontmatter literals in them are proof code rather than
    writes -- and that exclusion is itself proved by `clean-module-with-proof-code` below."""
    marked = "# LEGAL STATUS " + "- WRITER\n"
    reader = "# LEGAL STATUS " + "- READER\n"
    invented = "# LEGAL STATUS " + "- PROBABLY_FINE\n"
    not_a_rule = "# LEGAL STATUS " + "- NOT-A-RULE\n"
    not_a_legal_status = "# LEGAL STATUS " + "- NOT-A-LEGAL-STATUS\n"
    template = '\ndef doc_body(x):\n    return f"""---\nid: {x}\nstatus: current\n---\n"""\n'
    return {
        # A module with no legal-status write at all.
        "clean-module": "\ndef titles(rows):\n    return [r['title'] for r in rows]\n",
        # A READ of the field decides nothing and is not a site.
        "reading-a-status-is-not-writing-one":
            "\ndef live(rows):\n    return [r for r in rows if r['status'] == 'current']\n",
        # The four shapes a write takes, each unmarked.
        "unmarked-frontmatter-literal": template,
        "unmarked-key-assignment":
            "\ndef mark(d, gone):\n    d['status'] = 'repealed' if gone else 'current'\n",
        "unmarked-dict-literal":
            "\ndef row(sec):\n    return {'section': sec, 'status': 'repealed'}\n",
        "unmarked-line-rewrite":
            "\nimport re\n\n\ndef stamp(text, v):\n"
            "    return re.sub(r'^status: .*$', 'status: repealed', text, flags=re.M)\n",
        "unmarked-return":
            "\ndef status_of(gone):\n    return 'repealed' if gone else 'current'\n",
        # Marked, but with a word this repository has no meaning for.
        "invented-purpose": invented + "\ndef status_of(gone):\n    return 'current'\n",
        # Correctly marked: one writer, and a non-rule write beside it.
        "one-writer-only":
            marked + "\ndef status_of(gone):\n    return 'repealed' if gone else 'current'\n",
        "a-non-rule-write-is-marked-as-one": not_a_rule + template,
        # THE MUTATION. A second module claiming to decide -- scanned together with
        # `one-writer-only` below, because one module alone can never break this rule.
        "a-second-writer":
            marked + "\ndef status_of(gone):\n    return 'repealed' if gone else 'current'\n",
        # THE ESCAPE HATCH. A second writer that calls itself a reader keeps its literal, and
        # a gate counting only WRITER markers would report one writer and pass.
        "a-reader-that-decides":
            reader + "\ndef status_of(gone):\n    return 'repealed' if gone else 'current'\n",
        # A reader that genuinely stamps what it was handed.
        "a-reader-that-stamps-what-it-was-given":
            reader + "\nimport re\n\n\ndef stamp(text, v):\n"
            "    return re.sub(r'^status: .*$', f'status: {v}', text, flags=re.M)\n",
        # A module this scan could not read at all, which is not a module with no writes.
        "module-that-does-not-parse": "\ndef status_of(gone)\n    return 'current'\n",
        # Proof code is not a writer: the literal sits in a fixture.
        "clean-module-with-proof-code":
            "\ndef _fixture_document():\n    return 'status: repealed'\n",
        # ...and the exemption is ANCHORED. A production helper whose name merely contains
        # the word is not proof code, and exempting it would be an unmarked escape from a
        # gate whose rule is that an unmarked write fails.
        "a-production-function-named-like-a-fixture":
            "\ndef load_fixture_rows(d):\n    d['status'] = 'repealed'\n",
        # A DECISION TABLE MAPPING SOMETHING ELSE ONTO A LEGAL STATUS. The keys are not
        # `status`, so nothing above this ticket saw it -- and it is the exact shape the
        # next second writer takes: the Bulletin's verb turned into a claim about Oregon
        # law by a module that is not the one writer. A mapping TO a legal status decides
        # one as surely as an assignment OF one.
        "unmarked-action-table":
            "\ndef status_of(action):\n"
            "    return {'repeal': 'repealed', 'suspend': 'superseded'}.get(action)\n",
        # ...and a mapping that merely mentions the words as KEYS is a lookup, not a
        # decision: the narrowing that keeps this from firing on every consumer.
        "a-status-keyed-lookup-is-not-a-decision":
            "\ndef label(status):\n"
            "    return {'repealed': 'no longer in force', 'draft': 'not adopted'}[status]\n",
        # THE FOURTH PURPOSE, exercised. No site in src/ carries it today -- the catalog's
        # own `not_ingested` is not one of the five words, so nothing trips the scan -- and
        # a purpose nobody has watched being accepted is one nobody knows is accepted.
        "a-status-that-is-not-a-legal-status":
            not_a_legal_status + "\ndef mark(d, gone):\n"
            "    d['status'] = 'repealed' if gone else 'current'\n",
    }


# (case name, the rule it must break -- None for a source that must come out clean)
_SOURCE_CASES = [
    ("clean-module", None),
    ("reading-a-status-is-not-writing-one", None),
    ("unmarked-frontmatter-literal", "legal-status-write-classified"),
    ("unmarked-key-assignment", "legal-status-write-classified"),
    ("unmarked-dict-literal", "legal-status-write-classified"),
    ("unmarked-line-rewrite", "legal-status-write-classified"),
    ("unmarked-return", "legal-status-write-classified"),
    ("invented-purpose", "known-purpose"),
    ("one-writer-only", None),
    ("a-non-rule-write-is-marked-as-one", None),
    ("a-reader-that-decides", "a-reader-decides-nothing"),
    ("a-reader-that-stamps-what-it-was-given", None),
    ("module-that-does-not-parse", "readable-module"),
    ("clean-module-with-proof-code", None),
    ("a-production-function-named-like-a-fixture", "legal-status-write-classified"),
    ("a-status-that-is-not-a-legal-status", None),
    ("unmarked-action-table", "legal-status-write-classified"),
    ("a-status-keyed-lookup-is-not-a-decision", None),
]


def _fixture_catalog(number="101-015-0056", **rule) -> dict:
    """A one-rule OAR catalog in the committed file's shape."""
    return {"chapters": [{"chapter": "101", "divisions": [
        {"division": "15", "rules": [dict({"number": number}, **rule)]}]}]}


# The bulletin a fixture cites when the proof is about something other than the citation.
FIXTURE_NOTICE = "August 2026 (bulltnRsn=1761)"


def _marked_fixture(**rule) -> dict:
    """A one-rule catalog whose row is marked WHOLE -- status, action and notice together,
    the three keys `legal-status-cites-its-notice` requires of each other.

    Separate from `_fixture_catalog` on purpose: the rule that a marked row cites its
    notice is proved by STRIPPING keys off a row, so the fixture that builds one must not
    fill them back in."""
    return _fixture_catalog(legal_status_notice=FIXTURE_NOTICE, **rule)


def _proof_resolve(check) -> None:
    """The order of authority, asserted rather than described.

    THE SECOND MUTATION PROOF LIVES HERE. `bulletin-survives-a-re-ingest` is the exact shape
    of what #230 will do: a rule the Bulletin marked repealed is fetched again, its OARD
    History line does not print a repeal, and the document on disk still says `current`. Both
    of the other two inputs say `current` and the answer must still be `repealed` -- delete
    the first branch of `resolve()` and this is the case that goes red."""
    check("a fresh ingest asserts current where nothing better is known",
          resolve() == UNKNOWN_BUT_SERVED)
    check("...and only where nothing better is known: a repeal in the rule's own history "
          "wins", resolve(history_repealed=True) == "repealed")
    check("a re-ingest that learned nothing keeps what the document says",
          resolve(existing="repealed") == "repealed")
    check("a bulletin-set status beats the rule's own history line",
          resolve(bulletin="repealed", history_repealed=False) == "repealed")
    check("a bulletin-set status beats what the document already says",
          resolve(bulletin="repealed", existing="current") == "repealed")
    check("bulletin-survives-a-re-ingest: repealed, history silent, document says current",
          resolve(bulletin="repealed", history_repealed=False, existing="current")
          == "repealed")
    check("...and the same holds for every value in the schema enum",
          all(resolve(bulletin=v, history_repealed=True, existing="current") == v
              for v in LEGAL_STATUS_VALUES))
    check("a history line read and found not to be a repeal is not silence",
          resolve(history_repealed=False, existing="repealed") == UNKNOWN_BUT_SERVED)
    try:
        resolve(bulletin="ingested")
        check("an ingest status is refused as a legal status", False)
    except ValueError as e:
        check("an ingest status is refused as a legal status", "INGEST" in str(e).upper()
              or "not a legal status" in str(e))


def _proof_the_gate_sees_a_second_writer(check) -> None:
    """ONE MODULE ALONE CAN NEVER BREAK THE ONE-WRITER RULE, so it is fired over a PAIR.

    This is the criterion's mutation: `one-writer-only` on its own is clean, and the same
    source scanned beside a second module carrying the same marker fails."""
    sources = _fixture_sources()
    alone = check_sites(scan_source("<writer>", sources["one-writer-only"]))
    check("one writer alone is clean", not alone)
    both = check_sites(scan_source("<writer>", sources["one-writer-only"])
                       + scan_source("<second-writer>", sources["a-second-writer"]))
    check("a second writer fails the gate",
          any(f.rule == "one-writer" for f in both))
    check("...and names both modules", any("<second-writer>" in f.detail for f in both))


def _proof_the_agreement_rule_reads_real_documents(check) -> None:
    """THE ONE FACT DECLARED TWICE, fired against a COMMITTED document rather than a string.

    `legal-status-agrees` compares the catalog's Bulletin-set status with the document's,
    and NO COMMITTED ROW CARRIES ONE YET -- #229 is what records the first. A rule proved
    only against a fixture catalog and a fixture document would be a rule nobody has watched
    reach a real file, and this repository has shipped a guard that could not fail. So the
    fixture row names a real path, `doc_status_by_rule` opens it, and the document's own
    committed `status: repealed` is what the comparison is made against."""
    real, path = "101-015-0056", "rules/101/015/oar-101-015-0056.md"
    # WHAT THE DOCUMENT SAYS IS READ, NOT ASSERTED. Pinning the expected value here would
    # turn a legitimate future restamp of this one rule into a red gate for an unrelated
    # reason; what this proves is that the function reaches a real file and returns what is
    # in it, so the fixture row is built from the answer rather than the other way round.
    said = doc_status_by_rule(_fixture_catalog(number=real, status="ingested", path=path),
                              [real])
    check("a committed rule document's status is read off disk",
          said.get(real) in LEGAL_STATUS_VALUES)
    # AND THE ROW IS BUILT WHOLE. Since #229 a catalog row stating a legal status also
    # states the action and the notice it came from, and `legal-status-derives-from-the-
    # action` gates the pair -- so the fixture takes the action that PRODUCES what the
    # document says rather than restating the status beside an unrelated verb.
    action = next((a for a, v in FORCE_ACTIONS.items() if v == said.get(real)), None)
    check("...and it is a status some filed action produces", action is not None)
    agreeing = _marked_fixture(number=real, status="ingested", path=path,
                               legal_status=said.get(real), legal_status_action=action)
    check("a document agreeing with the catalog is not a finding",
          not check_committed(agreeing, said))
    # THE OVERWRITE, CAUGHT. This is what a re-ingest stamping a different status over a
    # Bulletin-set one leaves behind on disk, and it is the state `--check` must refuse.
    other = next(v for v in LEGAL_STATUS_VALUES if v != said.get(real))
    overwritten = check_committed(agreeing, {real: other})
    check("a re-ingest that overwrote a bulletin-set status is caught",
          any(f.rule == "legal-status-agrees" for f in overwritten))
    check("...and a row whose document could not be read is not silently passed",
          any(f.rule == "the-document-reads-it"
              for f in check_committed(agreeing, {})))
    # A row naming no path is one no document could be read for, and must not pass either.
    pathless = _marked_fixture(number=real, status="ingested",
                               legal_status="repealed", legal_status_action="repeal")
    check("...nor is a row that names no document at all",
          any(f.rule == "the-document-reads-it"
              for f in check_committed(pathless,
                                       doc_status_by_rule(pathless, [real]))))


def _proof_the_two_fields_named_status(check) -> None:
    """The failure mode CONTEXT.md keeps two glossary entries to prevent."""
    legal_in_the_ingest_field = _fixture_catalog(status="repealed")
    check("a legal status in the catalog's ingest-status field is caught",
          any(f.rule == "two-fields-named-status"
              for f in check_committed(legal_in_the_ingest_field, {})))
    ingest_in_the_legal_field = _fixture_catalog(status="ingested",
                                                 legal_status="not_served")
    check("an ingest status in the catalog's legal-status field is caught",
          any(f.rule == "two-fields-named-status"
              for f in check_committed(ingest_in_the_legal_field, {})))
    check("a value in neither vocabulary is caught",
          any(f.rule == "bulletin-status-is-known"
              for f in check_committed(_fixture_catalog(status="ingested",
                                                        legal_status="retired"), {})))
    # THE MUST-NOT-FIRE GUARD. All but 100 of the 42,615 committed rows are exactly this
    # shape -- an ingest status and no legal status -- so a rule that fired on it would
    # fire 42,515 times, and a "clean catalog produces no finding" proof is what stops a
    # blanket refusal passing for a working gate.
    check("a catalog carrying only ingest statuses produces no finding",
          not check_committed(_fixture_catalog(status="ingested",
                                               path="rules/101/015/oar-101-015-0056.md"),
                              {}))
    check("...for every one of the ingest vocabulary's words",
          not [f for v in INGEST_STATUS_VALUES
               for f in check_committed(_fixture_catalog(status=v), {})])
    # THE SECOND COPY OF THE INGEST VOCABULARY, GATED. `INGEST_STATUS_VALUES` restates what
    # `ingest_oar.py` writes, and an unchecked second copy of a fact is what this whole
    # module is about -- so a word this list has not got is reported rather than passed over
    # as "not a legal status, therefore fine".
    check("an ingest status this module does not know is caught",
          any(f.rule == "ingest-status-is-known"
              for f in check_committed(_fixture_catalog(status="quarantined"), {})))


def _proof_the_ingest_vocabulary_is_not_a_second_copy(check) -> None:
    """`INGEST_STATUS_VALUES` restates what `ingest_oar.py` writes, and an unchecked second
    copy of a fact is the shape this module exists to refuse -- so the copy is compared with
    the original rather than trusted, out of the ingester's own syntax tree."""
    real = ingest_vocabulary()
    check("the declared ingest vocabulary is what the ingester writes",
          not check_vocabulary(real))
    check("...and it is not empty", bool(real))
    # THE NARROWING THAT MAKES THAT READING TRUE. The ingester's division line is
    # `d["status"] = d.get("status") if any(r.get("status") == "ingested" for r in
    # d["rules"]) else "not_ingested"`, and a walk of every constant beneath it reports
    # `status` and `rules` as vocabulary.
    divisionish = ('def f(d, r):\n'
                   '    d["status"] = d.get("status") if any(x.get("status") == "ingested"\n'
                   '                  for x in d["rules"]) else "not_ingested"\n')
    check("a conditional's test is not read as vocabulary",
          ingest_vocabulary(divisionish) == {"not_ingested"})
    check("a word the ingester writes and this module has not declared is caught",
          any(f.rule == "ingest-vocabulary-declared-once"
              for f in check_vocabulary(set(INGEST_STATUS_VALUES) | {"quarantined"})))
    check("...and so is a word declared here that the ingester no longer writes",
          any(f.rule == "ingest-vocabulary-declared-once"
              for f in check_vocabulary(set(INGEST_STATUS_VALUES) - {"needs_registry"})))
    # An ingester this could not parse yields no words, which must fail rather than agree
    # with an empty expectation -- could not check is never reported as is not there.
    check("an ingester that does not parse is not a vocabulary of no words",
          ingest_vocabulary("def f(d)\n    d['status'] = 'ingested'\n") == set()
          and any(f.rule == "ingest-vocabulary-declared-once"
                  for f in check_vocabulary(set())))


def _proof_only_frontmatter_is_read_for_a_status(check) -> None:
    """A rule's verbatim text can print `status:` at the start of a line, and this corpus's
    whole content policy is that the full text is reproduced unaltered. Reading such a line
    as the document's legal status would report a disagreement that is not there.

    Fired through `doc_status_by_rule` rather than against the regex, because what is being
    proved is what the function returns to the agreement rule."""
    d = Path(tempfile.mkdtemp())
    (d / "oar-125-010-0005.md").write_text(
        "---\nid: oar-125-010-0005\nstatus: repealed\n---\n\n## Full text\n\n"
        "status: current shall be recorded by the agency.\n")
    cat = _marked_fixture(number="125-010-0005", status="ingested",
                          legal_status="repealed", legal_status_action="repeal",
                          path=str(d / "oar-125-010-0005.md"))
    got = doc_status_by_rule(cat, ["125-010-0005"])
    check("a `status:` line in a rule's own text is not read as its legal status",
          got.get("125-010-0005") == "repealed")
    check("...so the agreement rule reports nothing on it", not check_committed(cat, got))
    # A file with no frontmatter block at all yields no status, and the row stating one is
    # reported rather than passed over.
    (d / "oar-125-010-0006.md").write_text("status: current\n")
    bare = _marked_fixture(number="125-010-0006", status="ingested",
                           legal_status="repealed", legal_status_action="repeal",
                           path=str(d / "oar-125-010-0006.md"))
    check("a file with no frontmatter block is a document that could not be read",
          any(f.rule == "the-document-reads-it"
              for f in check_committed(bare, doc_status_by_rule(bare, ["125-010-0006"]))))


def _proof_force_status(check) -> None:
    """WHAT A FILED ACTION DOES TO A RULE'S FORCE, asserted rather than described."""
    check("a filed repeal is a repeal", force_status("repeal") == "repealed")
    check("a filed suspension is not a repeal", force_status("suspend") != "repealed")
    check("a suspension takes the rule out of force",
          force_status("suspend") != UNKNOWN_BUT_SERVED)
    check("every force action maps into the schema enum",
          all(v in LEGAL_STATUS_VALUES for v in FORCE_ACTIONS.values()))
    check("an amendment is not a force action", force_status("amend") is None)


def _fixture_worklist(*actions, bulletin=FIXTURE_NOTICE) -> dict:
    """A bulletin worklist in the committed file's shape. `actions` are (number, action,
    corpus_state) triples."""
    return {"bulletin": bulletin, "rules": [
        {"number": n, "action": a, "corpus_state": st} for n, a, st in actions]}


def _proof_marking(check) -> None:
    """THE WRITE ITSELF: a filed action becomes a catalog row, and a suspension does not
    become a repeal."""
    cat = _fixture_catalog(number="101-015-0056", status="ingested",
                           path="rules/101/015/oar-101-015-0056.md")
    cat["chapters"][0]["divisions"][0]["rules"].append(
        {"number": "165-002-0010", "status": "ingested",
         "path": "rules/165/002/oar-165-002-0010.md"})
    work = _fixture_worklist(("101-015-0056", "repeal", "held"),
                             ("165-002-0010", "suspend", "held"))
    written, problems = mark(cat, work)
    rows = {r["number"]: r for r in catalog_rules(cat)}
    check("a filed repeal is written onto the catalog row",
          rows["101-015-0056"][CATALOG_KEY] == "repealed")
    check("...and cites the notice it came from",
          rows["101-015-0056"][NOTICE_KEY] == FIXTURE_NOTICE)
    # THE CRITERION. Both rows lose force and the two are told apart in BOTH fields --
    # flip FORCE_ACTIONS["suspend"] to "repealed" and this is what goes red.
    check("a suspension is not written as a repeal",
          rows["165-002-0010"][CATALOG_KEY] != "repealed")
    check("...and the action that produced it is on the row",
          (rows["165-002-0010"][ACTION_KEY], rows["101-015-0056"][ACTION_KEY])
          == ("suspend", "repeal"))
    check("both rules are marked", written == 2 and not problems)
    # MARKED, NEVER DELETED: the row keeps its ingest status and its path.
    check("a marked rule is still held and still has a document",
          (rows["101-015-0056"]["status"], bool(rows["101-015-0056"]["path"]))
          == ("ingested", True))
    check("re-marking the same worklist writes nothing new", mark(cat, work)[0] == 0)
    # AN AMENDMENT CHANGES TEXT, NOT FORCE -- #230's, and this writer must not touch it.
    amended = _fixture_catalog(number="101-015-0056", status="ingested", path="x.md")
    check("an amendment is not a legal-status write",
          mark(amended, _fixture_worklist(("101-015-0056", "amend", "held")))[0] == 0
          and CATALOG_KEY not in list(catalog_rules(amended))[0])
    # A RULE THIS CORPUS DOES NOT HOLD gets no claim written about it: there is no
    # document to carry it, and a catalog row asserting a status nothing serves is what
    # `the-document-reads-it` exists to refuse.
    absent = _fixture_catalog(number="101-015-0056", status="ingested", path="x.md")
    check("a rule the corpus does not hold is not marked",
          mark(absent, _fixture_worklist(
              ("101-015-0056", "repeal", "chapter_not_mirrored")))[0] == 0)
    # A NUMBER THE CATALOG DOES NOT NAME IS REPORTED, not skipped: the catalog writes and
    # the document reads, so a filing against a rule the catalog cannot reach is drift.
    stranger = _fixture_catalog(number="101-015-0056", status="ingested", path="x.md")
    check("a filing against a rule the catalog does not name is reported",
          any(f.rule == "catalog-reaches-the-rule" for f in mark(
              stranger, _fixture_worklist(("999-999-9999", "repeal", "held")))[1]))
    # TWO FILINGS IN ONE MONTH. A repeal and a suspension against the same rule is a
    # permanent loss of force and a temporary one filed together; the permanent one is
    # what the rule ends in, whichever order the rows arrive.
    both = _fixture_catalog(number="101-015-0056", status="ingested", path="x.md")
    mark(both, _fixture_worklist(("101-015-0056", "suspend", "held"),
                                 ("101-015-0056", "repeal", "held")))
    check("a repeal filed alongside a suspension wins",
          list(catalog_rules(both))[0][CATALOG_KEY] == "repealed")
    reversed_ = _fixture_catalog(number="101-015-0056", status="ingested", path="x.md")
    mark(reversed_, _fixture_worklist(("101-015-0056", "repeal", "held"),
                                      ("101-015-0056", "suspend", "held")))
    check("...whichever order the rows arrive in",
          list(catalog_rules(reversed_))[0][CATALOG_KEY] == "repealed")


def _proof_a_marked_row_says_where_it_came_from(check) -> None:
    """A CLAIM ABOUT OREGON LAW CARRIES ITS CITATION, or it is unattributable.

    `legal_status` is the Bulletin's word for whether a rule is in force. A row holding one
    with no action and no notice states that word on nobody's authority -- and the action
    is not decoration: it is the half of the fact corpus-toolkit's five-word enum cannot
    hold, so a row that loses it can no longer tell a suspension from a repeal."""
    marked = dict(number="101-015-0056", status="ingested",
                  path="rules/101/015/oar-101-015-0056.md", legal_status="repealed",
                  legal_status_action="repeal",
                  legal_status_notice=FIXTURE_NOTICE)
    whole = _fixture_catalog(**marked)
    said = doc_status_by_rule(whole, ["101-015-0056"])
    check("a fully attributed row is not a finding",
          not [f for f in check_committed(whole, dict(said, **{"101-015-0056": "repealed"}))])
    # EACH OF THE THREE, ALONE AND MISSING. Both directions matter and the second is the
    # one that got through: written as a pair of booleans this rule PASSED a row holding
    # `legal_status_action: repeal` and nothing else -- a filing recorded as having changed
    # no rule's force, which is the fact the ticket exists to record, lost.
    for key in MARKED_KEYS:
        stripped = {k: v for k, v in marked.items() if k != key}
        check(f"a marked row with no {key} is caught",
              any(f.rule == "legal-status-cites-its-notice"
                  for f in check_committed(_fixture_catalog(**stripped),
                                           {"101-015-0056": "repealed"})))
        alone = {k: v for k, v in marked.items() if k not in MARKED_KEYS or k == key}
        check(f"a row holding {key} and neither of the others is caught",
              any(f.rule == "legal-status-cites-its-notice"
                  for f in check_committed(_fixture_catalog(**alone),
                                           {"101-015-0056": "repealed"})))
    # THE MUST-NOT-FIRE SIDE: an unmarked row is every one of the 36,907 rows that carry
    # no Bulletin claim at all, and a rule that fired on those would fire 36,907 times.
    check("a row carrying none of the three is not a finding",
          not [f for f in check_committed(
              _fixture_catalog(number="101-015-0056", status="ingested",
                               path="rules/101/015/oar-101-015-0056.md"), {})
              if f.rule == "legal-status-cites-its-notice"])
    # THE ACTION AND THE STATUS ARE ONE FACT WRITTEN TWICE, so their agreement is gated.
    # Without this a row could say `legal_status_action: suspend` beside `legal_status:
    # repealed` and every other rule here would pass it -- a temporary loss of force
    # published as a permanent one, which is the thing #229 exists to prevent.
    check("a status that does not follow from its action is caught",
          any(f.rule == "legal-status-derives-from-the-action"
              for f in check_committed(
                  _fixture_catalog(**dict(marked, legal_status_action="suspend")),
                  {"101-015-0056": "repealed"})))
    check("an action that changes no force is caught",
          any(f.rule == "legal-status-action-is-known"
              for f in check_committed(
                  _fixture_catalog(**dict(marked, legal_status_action="amend")),
                  {"101-015-0056": "repealed"})))
    # MARKED, NEVER DELETED. The row that carries the repeal is the row a citation
    # resolves through; an ingest status saying this mirror no longer holds the rule is
    # what deleting the document leaves behind, and it must not pass as a clean repeal.
    check("a marked rule the catalog no longer holds is caught",
          any(f.rule == "a-marked-rule-is-still-served"
              for f in check_committed(
                  _fixture_catalog(**dict(marked, status="not_served")),
                  {"101-015-0056": "repealed"})))


def _proof_every_filed_force_action_is_recorded(check) -> None:
    """THE RULE THAT MAKES THE OTHERS UNSATISFIABLE BY DOING NOTHING.

    Every rule above checks a row that EXISTS. Delete the three keys from all 100 of them
    and every one of those rules passes on a corpus that publishes 66 repealed rules as
    current -- a criterion a blank file satisfies. This is the rule that reads the notice
    and asks what is missing, and it is the one that had to be written last because it is
    the only one that cannot be satisfied by deleting information."""
    cat = _fixture_catalog(number="101-015-0056", status="ingested", path="x.md")
    work = _fixture_worklist(("101-015-0056", "repeal", "held"))
    check("a filed repeal nothing recorded is caught",
          any(f.rule == "a-filed-force-action-is-recorded"
              for f in check_filings(cat, work)))
    mark(cat, work)
    check("...and is not a finding once it is recorded", not check_filings(cat, work))
    # THE MUST-NOT-FIRE GUARD, on the other side: an amendment is #230's and a rule this
    # corpus does not hold has no document to carry a claim, so neither may be demanded.
    for action, state in (("amend", "held"), ("repeal", "chapter_not_mirrored"),
                          ("repeal", "missing_from_mirrored_chapter")):
        bare = _fixture_catalog(number="101-015-0056", status="ingested", path="x.md")
        check(f"a {action} recorded {state} is not demanded",
              not check_filings(bare, _fixture_worklist(
                  ("101-015-0056", action, state))))
    # A NOTICE THIS COULD NOT READ IS NOT A MONTH WITH NOTHING IN IT. Without this the
    # whole rule above passes on an unreadable worklist, which is the same "could not
    # check reported as is not there" substitution one level up.
    for unreadable in (None, {}, {"rules": []}, {"rules": None}, "not a mapping"):
        check(f"an unreadable notice is refused, not read as a quiet month ({unreadable!r})",
              any(f.rule == "the-notice-is-readable"
                  for f in check_filings(cat, unreadable)))
    # AND THE CONVERSE. A row citing this month's bulletin for a filing the bulletin does
    # not contain is a claim about Oregon law with a citation that does not support it,
    # which is worse than an uncited one -- it looks checked.
    invented = _fixture_catalog(number="101-015-0056", status="ingested", path="x.md")
    mark(invented, _fixture_worklist(("101-015-0056", "repeal", "held")))
    check("a marked row this month's bulletin does not support is caught",
          any(f.rule == "the-notice-names-the-filing"
              for f in check_filings(invented, _fixture_worklist(
                  ("101-015-0056", "amend", "held")))))
    # ...and a row citing a DIFFERENT bulletin is left alone: this corpus holds one
    # month's worklist at a time, so an older notice is one this run cannot read, and
    # "could not check" is never reported as "is not there".
    check("a row citing an earlier bulletin is not contradicted by this one",
          not check_filings(invented, _fixture_worklist(
              ("101-015-0056", "amend", "held"),
              bulletin="September 2026 (bulltnRsn=1762)")))


def _proof_catalog_force_action_counts(check) -> None:
    """`catalog_force_action_counts()`: CONTEXT.md's *Legal status* and *Filed force
    action* entries' "66 repeals and 34 suspensions" (#307 code review) -- these sat as
    `observed:` marks though `cmd_check()` already computed and printed exactly this
    `Counter` every run. Proven against a synthetic multi-rule catalog, not the committed
    one, so the mutation below is controlled rather than a coincidence of whatever the
    corpus's current bulletin happens to hold."""
    def _row(number, action):
        return {"number": number, CATALOG_KEY: force_status(action), ACTION_KEY: action,
                NOTICE_KEY: FIXTURE_NOTICE}
    cat = {"chapters": [{"divisions": [{"rules": [
        _row("101-015-0001", "repeal"), _row("101-015-0002", "repeal"),
        _row("101-015-0003", "suspend"),
        {"number": "101-015-0004"},  # no Bulletin-set status at all -- not a filed action
    ]}]}]}
    counts = catalog_force_action_counts(cat)
    check("every FORCE_ACTIONS word is a named category, the zeroes included",
          set(FORCE_ACTIONS) <= set(counts))
    check("a mixed catalog counts each filed action correctly",
          (counts["repeal"], counts["suspend"]) == (2, 1))
    check("the total counts only rows carrying a Bulletin-set status, not every row",
          counts["total"] == 3)
    # THE MUTATION: change the underlying data, watch the figure move.
    cat["chapters"][0]["divisions"][0]["rules"].append(_row("101-015-0005", "suspend"))
    moved = catalog_force_action_counts(cat)
    check("...and the count MOVES when the underlying data does",
          moved["suspend"] == counts["suspend"] + 1 and moved["repeal"] == counts["repeal"])
    # A CATALOG WITH NO FILED ACTIONS AT ALL still names both categories at zero
    # (AGENTS.md) rather than omitting them because nothing filed this month.
    empty = catalog_force_action_counts({"chapters": [{"divisions": [{"rules": [
        {"number": "101-015-0006"}]}]}]})
    check("a catalog with nothing filed reports both actions as a measured zero, not absent",
          empty == {"repeal": 0, "suspend": 0, "total": 0})


def _fixture_rule_doc(status: str) -> str:
    """A minimal committed rule document's text, frontmatter and all -- the shape
    `document_status_counts` and `temporary_suspension_counts` read."""
    return f"---\nid: oar-1-001-0001\nstatus: {status}\n---\n\n## Full text\n\nbody.\n"


def _proof_document_status_counts(check) -> None:
    """`document_status_counts()`: CONTEXT.md's *Legal status* headline figure (#307), and
    a DIFFERENT MEASUREMENT from `census()` above wearing the same word -- see this
    module's "the document-level censuses" section banner. Proven against synthetic
    document texts, not the corpus, so this stays fast and independent of the corpus's
    current distribution -- and so the mutation below (the point of #307's own ticket:
    "change the underlying data, watch the figure move") is a controlled one rather than a
    coincidence of whatever the committed corpus happens to hold today."""
    docs = [_fixture_rule_doc("current"), _fixture_rule_doc("current"),
            _fixture_rule_doc("repealed")]
    counts = document_status_counts(docs)
    check("every LEGAL_STATUS_VALUES word is a named category, the zeroes included",
          set(LEGAL_STATUS_VALUES) <= set(counts))
    check("a mixed set of documents counts each status correctly",
          (counts["current"], counts["repealed"], counts["superseded"]) == (2, 1, 0))
    check("the total is every document counted, whatever its status",
          counts["total"] == len(docs))
    # THE MUTATION: change the underlying data, watch the figure move.
    moved = document_status_counts(docs + [_fixture_rule_doc("repealed")])
    check("...and the count MOVES when the underlying data does",
          moved["repealed"] == counts["repealed"] + 1
          and moved["current"] == counts["current"])
    # A document with no status: line at all is a NAMED category, not a silent drop --
    # "could not check is never reported as is not there" applied to this census itself.
    no_status = document_status_counts(docs + ["---\nid: oar-1-001-0002\n---\n\nbody\n"])
    check("a document with no status: line is counted as its own named category",
          no_status.get("no_status") == 1)
    # A rule's own served text can print a `status:` line INSIDE its body -- this corpus's
    # whole content policy is that the full text is reproduced unaltered, and reading such
    # a line as the document's legal status would misclassify it. Same rule
    # `doc_status_by_rule` keeps by reading the frontmatter block only
    # (`_proof_only_frontmatter_is_read_for_a_status`, above).
    body_only = document_status_counts(
        ["---\nid: oar-1-001-0003\n---\n\nstatus: current shall be recorded by the agency.\n"])
    check("a `status:` line in a document's own BODY is not read as its frontmatter status",
          body_only.get("no_status") == 1 and body_only.get("current", 0) == 0)


def _proof_temporary_suspension_counts(check) -> None:
    """`temporary_suspension_counts()`: CONTEXT.md's *Filed force action* entry's History-
    line figure (#307) -- why a suspension is stamped `superseded` rather than `repealed`:
    every suspension Oregon files carries an end date, and this counts the lines that say
    so. Proven against synthetic History text, not the corpus."""
    full_line = ("History: BHS 1-2024, temporary suspend filed 01/01/2024, effective "
                "01/01/2024 through 06/01/2024 BHS 2-2023, adopt filed 03/03/2023, "
                "effective 03/03/2023\n")
    # AN OPEN-ENDED SUSPENSION: filed, and in force, with no closing date on record yet --
    # a real possibility this corpus's own text distinguishes with the `full` vs
    # `filed_mentions` split (see the module docstring at `TEMP_SUSPEND_MENTION_RE`).
    open_ended = "History: BHS 3-2024, temporary suspend filed 02/02/2024, effective 02/02/2024\n"

    counts = temporary_suspension_counts([full_line])
    check("a full temporary-suspend History line is counted in both figures",
          (counts["full"], counts["filed_mentions"]) == (1, 1))
    check("...and as one distinct line",
          counts["lines"] == 1)

    diverging = temporary_suspension_counts([full_line, open_ended])
    check("a filed suspension with no recorded through-date moves filed_mentions and not "
          "full -- the two figures CAN diverge, and this is what that looks like",
          (diverging["filed_mentions"], diverging["full"]) == (2, 1))

    # THE MUTATION: change the underlying data, watch the figure move.
    doubled = temporary_suspension_counts([full_line, full_line])
    check("...and full MOVES when a second complete line is added",
          doubled["full"] == counts["full"] + 1)

    # TWO FILINGS, ONE LINE: `full`/`filed_mentions` count OCCURRENCES, `lines` counts
    # DISTINCT LINES, and #307 code review found prose that called an occurrence count a
    # line count -- this is the case that makes the two different numbers.
    two_on_one_line = ("History: BHS 4-2024, temporary suspend filed 01/01/2024, effective "
                       "01/01/2024 through 06/01/2024 BHS 5-2024, temporary suspend filed "
                       "07/01/2024, effective 07/01/2024 through 12/01/2024\n")
    two_filings = temporary_suspension_counts([two_on_one_line])
    check("two filings on the same physical line count as two occurrences...",
          (two_filings["full"], two_filings["filed_mentions"]) == (2, 2))
    check("...but as ONE line -- occurrences and lines are different figures",
          two_filings["lines"] == 1)

    clean = temporary_suspension_counts(["History: BHS 1-2024, adopt filed 01/01/2024, "
                                         "effective 01/01/2024\n"])
    check("a History line with no temporary suspension at all counts zero, not absent",
          clean == {"full": 0, "filed_mentions": 0, "lines": 0})


class _FixtureDoc:
    """A `pathlib.Path`-shaped stand-in offering just `.read_text()` -- what
    `document_censuses()` asks of everything in `paths`, so this proves it against synthetic
    documents without either function reading `rules/` from disk."""
    def __init__(self, text):
        self._text = text

    def read_text(self):
        return self._text


def _proof_document_censuses(check) -> None:
    """`document_censuses()`: the live-corpus path both `cmd_check()` and
    `stated_census._legal_status_docs_measurement()` call for `document_status_counts()`
    and `temporary_suspension_counts()` TOGETHER, in one pass, at flat memory (#307 code
    review). Proves the one-pass result AGREES with calling the two functions separately on
    the same documents -- the property that makes replacing "materialize a list, call both"
    with this safe -- and that it moves the same way the two functions already proved they
    do above."""
    docs = [_fixture_rule_doc("current"), _fixture_rule_doc("repealed"),
           "History: BHS 1-2024, temporary suspend filed 01/01/2024, effective "
           "01/01/2024 through 06/01/2024\n"]
    separately = (document_status_counts(docs), temporary_suspension_counts(docs))
    together = document_censuses([_FixtureDoc(d) for d in docs])
    check("one pass over the same documents agrees with the two functions run separately",
          together == separately)
    # THE MUTATION: change the underlying data, watch the figure move -- through the
    # one-pass path, not just the two functions it composes.
    moved = document_censuses([_FixtureDoc(d) for d in docs] + [_FixtureDoc(_fixture_rule_doc(
        "repealed"))])
    check("...and document_censuses() moves the same way when a document is added",
          moved[0]["repealed"] == together[0]["repealed"] + 1)


def _proof_a_corpus_that_could_not_be_walked_is_refused(check) -> None:
    """`_rule_document_paths()`: a `rules/` directory that does not exist, or that exists
    and yields nothing, is REFUSED rather than reported as a corpus of zero documents --
    AGENTS.md's overriding rule applied to the two document-level censuses, which would
    otherwise print a full set of measured-looking zeroes on a corpus that could not be
    read at all (#307 code review)."""
    real_rules_dir = globals()["RULES_DIR"]
    try:
        with tempfile.TemporaryDirectory() as d:
            globals()["RULES_DIR"] = Path(d) / "does-not-exist"
            raised = False
            try:
                _rule_document_paths()
            except RuntimeError:
                raised = True
            check("a missing rules/ directory is refused, not read as a corpus of zero",
                  raised)

            globals()["RULES_DIR"] = Path(d)  # exists, but holds no oar-*.md at all
            raised = False
            try:
                _rule_document_paths()
            except RuntimeError:
                raised = True
            check("an empty rules/ directory is refused the same way, for the same reason",
                  raised)
    finally:
        globals()["RULES_DIR"] = real_rules_dir


def selftest() -> int:
    check = Checks()
    _proof_resolve(check)
    _proof_force_status(check)
    _proof_marking(check)
    sources = _fixture_sources()
    for name, rule in _SOURCE_CASES:
        failures = check_sites(scan_source(f"<{name}>", sources[name]))
        if rule is None:
            check(f"{name}: no finding", not failures)
        else:
            check(f"{name}: [{rule}]", any(f.rule == rule for f in failures))
    _proof_the_gate_sees_a_second_writer(check)
    _proof_the_agreement_rule_reads_real_documents(check)
    _proof_the_two_fields_named_status(check)
    _proof_the_ingest_vocabulary_is_not_a_second_copy(check)
    _proof_only_frontmatter_is_read_for_a_status(check)
    _proof_a_marked_row_says_where_it_came_from(check)
    _proof_every_filed_force_action_is_recorded(check)
    _proof_catalog_force_action_counts(check)
    _proof_document_status_counts(check)
    _proof_temporary_suspension_counts(check)
    _proof_document_censuses(check)
    _proof_a_corpus_that_could_not_be_walked_is_refused(check)
    # THE DECLARATION, GATED FROM BOTH SIDES. A rule the code can emit and `CHECK_RULES`
    # does not name would go uncounted; a rule named there that nothing above actually made
    # fire is one nobody has watched work, and a name in two lists is not a proof.
    check("every rule this module can report is declared",
          emitted_rules() == set(CHECK_RULES))
    check("...and every declared rule was watched firing, not merely listed",
          set(CHECK_RULES) <= _FIRED)
    return check.report(
        f"{sum(1 for c in _SOURCE_CASES if c[1])} unmarked or mismarked write(s) "
        f"demonstrated failing across {len({c[1] for c in _SOURCE_CASES if c[1]})} rule(s), "
        f"{sum(1 for c in _SOURCE_CASES if not c[1])} clean module(s) left alone, "
        f"{len(CHECK_RULES)} rule(s) declared, every one both emitted by this module "
        "and watched firing here; "
        "a second writer, an overwritten bulletin status and a suspension written as a "
        "repeal all watched failing -- selftest")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--mark", action="store_true",
                    help="derive the catalog's legal statuses from the committed Oregon "
                         "Bulletin worklist and name every rule that changed")
    a = ap.parse_args()
    if a.check:
        return cmd_check()
    if a.mark:
        return cmd_mark()
    if a.selftest:
        return selftest()
    return cmd_census()


if __name__ == "__main__":
    raise SystemExit(main())
