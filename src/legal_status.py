#!/usr/bin/env python3
"""The one writer of a rule's LEGAL STATUS, and the gate that fails if a second appears.

  python3 src/legal_status.py             # the census of every legal-status write in src/
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
                                 `ingested` (36,474), `renumbered` (484), `not_served` (49)

A rule can be in force and absent here, or repealed and still held. So the Bulletin's claim
about force gets its OWN key on the catalog row -- `legal_status` -- and never borrows the
one already there. `--check` refuses either field holding the other's vocabulary, over all
37,007 committed rule entries, because the day those two collide the collision is invisible.

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

# Where that vocabulary is written, and the only module allowed to write it.
INGESTER = SRC / "ingest_oar.py"

# The catalog key carrying a Bulletin-set legal status. Deliberately NOT `status`.
CATALOG_KEY = "legal_status"

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
Failure = namedtuple("Failure", "rule site detail")


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


def bulletin_status_by_rule(catalog=None) -> dict:
    """{rule number: legal status} for every catalog rule entry the Bulletin has set one on.

    EMPTY TODAY, and that is a state rather than an oversight: #229 is what records a filed
    repeal here. `--check` prints the count on every run so the day it stops being zero is
    visible, and so a rule that silently went back to zero is too."""
    return {r["number"]: r[CATALOG_KEY] for r in catalog_rules(catalog)
            if r.get(CATALOG_KEY) is not None}


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
    """Every word `ingest_oar.py` assigns to a `status` key -- the INGEST vocabulary, read
    off the ingester rather than restated.

    A module that does not parse yields the EMPTY set, which fails
    `ingest-vocabulary-declared-once` against a non-empty declaration rather than passing:
    a vocabulary this could not read is not a vocabulary with no words in it."""
    try:
        tree = ast.parse(source if source is not None else INGESTER.read_text())
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


# ------------------------------------------------------------------- commands


def cmd_check() -> int:
    sites = census()
    catalog = yaml.safe_load(CATALOG.read_text())
    bulletin_set = bulletin_status_by_rule(catalog)
    failures = (check_sites(sites) + check_vocabulary(ingest_vocabulary())
                + check_committed(catalog, doc_status_by_rule(catalog, bulletin_set)))
    for f in failures:
        print(f"  FAIL [{f.rule}] {f.site}: {f.detail}", file=sys.stderr)
    if failures:
        print(f"\n{len(failures)} legal-status violation(s)", file=sys.stderr)
        return 1
    writers = sorted({s.path for s in sites if s.purpose == "WRITER"})
    n_rules = sum(1 for _ in catalog_rules(catalog))
    # THE CENSUS LINE, printed on every clean run. The Bulletin-set count is ZERO until
    # #229 records the first repeal, and a rule that can only be watched not firing is a
    # rule nobody can tell from a rule that stopped running -- so the number is on screen.
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
          f"Bulletin-set `{CATALOG_KEY}`, every one agreeing with its document; "
          f"{crossed} hold the other field's vocabulary")
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
]


def _fixture_catalog(number="101-015-0056", **rule) -> dict:
    """A one-rule OAR catalog in the committed file's shape."""
    return {"chapters": [{"chapter": "101", "divisions": [
        {"division": "15", "rules": [dict({"number": number}, **rule)]}]}]}


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
    said = doc_status_by_rule(_fixture_catalog(number=real, status="ingested",
                                               legal_status="repealed", path=path), [real])
    check("a committed rule document's status is read off disk",
          said.get(real) in LEGAL_STATUS_VALUES)
    agreeing = _fixture_catalog(number=real, status="ingested",
                                legal_status=said.get(real), path=path)
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
    pathless = _fixture_catalog(number=real, status="not_served", legal_status="repealed")
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
    # THE MUST-NOT-FIRE GUARD. Every committed row today is exactly this shape -- an ingest
    # status and no legal status -- so a rule that fired on it would fire 37,007 times, and
    # a "clean catalog produces no finding" proof is what stops a blanket refusal passing
    # for a working gate.
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
    cat = _fixture_catalog(number="125-010-0005", status="ingested",
                           legal_status="repealed",
                           path=str(d / "oar-125-010-0005.md"))
    got = doc_status_by_rule(cat, ["125-010-0005"])
    check("a `status:` line in a rule's own text is not read as its legal status",
          got.get("125-010-0005") == "repealed")
    check("...so the agreement rule reports nothing on it", not check_committed(cat, got))
    # A file with no frontmatter block at all yields no status, and the row stating one is
    # reported rather than passed over.
    (d / "oar-125-010-0006.md").write_text("status: current\n")
    bare = _fixture_catalog(number="125-010-0006", status="ingested",
                            legal_status="repealed",
                            path=str(d / "oar-125-010-0006.md"))
    check("a file with no frontmatter block is a document that could not be read",
          any(f.rule == "the-document-reads-it"
              for f in check_committed(bare, doc_status_by_rule(bare, ["125-010-0006"]))))


def selftest() -> int:
    check = Checks()
    _proof_resolve(check)
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
    return check.report(
        f"{sum(1 for c in _SOURCE_CASES if c[1])} unmarked or mismarked write(s) "
        f"demonstrated failing across {len({c[1] for c in _SOURCE_CASES if c[1]})} rule(s), "
        f"{sum(1 for c in _SOURCE_CASES if not c[1])} clean module(s) left alone, "
        "a second writer and an overwritten bulletin status both watched failing -- selftest")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.check:
        return cmd_check()
    if a.selftest:
        return selftest()
    return cmd_census()


if __name__ == "__main__":
    raise SystemExit(main())
