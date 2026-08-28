#!/usr/bin/env python3
"""The automatic re-ingest path for the Oregon Bulletin's TEXT actions (#230).

  python3 src/reingest_oar.py             # what this month's bulletin asks for, and why
  python3 src/reingest_oar.py --run       # re-ingest every amended rule this corpus holds
  python3 src/reingest_oar.py --check     # CI: the catalog records what the notice filed
  python3 src/reingest_oar.py --selftest  # CI: every rule --check enforces fires

WHY THIS EXISTS. ADR 0006 splits the Bulletin's filed actions on WHETHER THEY CHANGE TEXT
OR FORCE. An amendment is a text refresh the provenance chain already verifies, so a human
adds nothing by approving each one and it re-ingests here, unattended. A repeal or a
suspension is a claim about Oregon law: `legal_status.py --mark` records it and
`review_queue.py` puts it in front of a person. August 2026 filed 418 actions against
rules this corpus holds -- 318 amendments, 66 repeals, 34 suspensions -- and one issue per
rule was rejected against a 25-issue cap.

THE FAILURE THIS PATH IS BUILT NOT TO HAVE. `ingest_oar.py` used to write `status: current`
as a hardcoded literal into every document it created. Run over an amended rule the Bulletin
had also repealed, that literal RESURRECTS THE RULE -- publishing a false statement about
Oregon law under provenance, silently, with a source URL and a hash beside it. #228 moved
the decision into `legal_status.resolve()` and gated it; this module is the caller that
made the gate necessary, and it is built so the resurrection cannot happen by THREE
independent means, each watched failing in `--selftest`:

  1. IT NEVER SELECTS A RULE WHOSE FORCE CHANGED. `TEXT_ACTIONS` and
     `legal_status.FORCE_ACTIONS` partition `check_bulletin.ACTIONS` exactly, and
     `every-filed-action-is-text-or-force` fails on a verb in neither, in both, or in
     nothing -- so a NEW verb added upstream stops this path rather than defaulting into
     it. 12 rules this month were amended AND repealed or suspended by the same bulletin;
     they are re-ingested for their text and their force is untouched.
  2. IT WRITES NO LEGAL STATUS OF ITS OWN. The status arrives from
     `legal_status.resolve(bulletin=...)`, whose first step returns a Bulletin-set status
     unchanged whatever else the caller supplies. There is no legal-status literal in this
     file, which `legal_status.py --check` enforces against the syntax tree rather than
     taking on trust.
  3. IT REFRESHES TEXT AND NOTHING ELSE. A re-ingest REPLACES THE `## Full text` SECTION
     AND ITS PROVENANCE, leaving every other field the document holds -- relationships,
     upstream tracking, the enricher's derived frontmatter. Regenerating the whole document
     from `ingest_oar.doc_body()` would satisfy "the rule was re-ingested" by DELETING
     what other tools put there -- measured over just the 306 documents this month
     re-ingested: 1,187 authority citations and relationship entries in their frontmatter,
     2,374 edges of `_meta/graph.json`. That is the shape of criterion this repository
     refuses: one you can pass by throwing information away.

WHAT `--check` READS, AND WHY IT IS NOT SATISFIABLE BY DOING NOTHING. Every rule about a
catalog row that EXISTS is satisfied by a corpus that recorded no re-ingest at all. So the
gate reads the NOTICE -- the committed `_meta/bulletin-worklist.yml` -- and asks what the
catalog is missing, in both directions: a text action filed against a held rule and not
recorded is a rule served as though it had not changed, and a row citing this month's
bulletin for a filing the bulletin does not contain is a claim whose citation does not
support it. That is the same shape `legal_status.check_filings()` uses and for the same
reason.

WHAT A ROW RECORDS, AND WHY TWO KEYS. `reingest_action` and `reingest_notice` arrive
together or not at all. The notice alone cannot say WHICH filing was applied, and the
action alone is a fact about no particular month -- and this corpus keeps one month's
worklist at a time, so a row citing an earlier bulletin is one this run has nothing to read
against and is left alone rather than reported. They are deliberately NOT called `status`:
the OAR catalog already has two fields spelled that way and CONTEXT.md keeps two glossary
entries for them.

RE-RUNNING PRODUCES BYTE-IDENTICAL OUTPUT, AND IT IS A GATE RATHER THAN AN OBSERVATION.
`refresh()` is a pure function of (the document, the committed snapshot, the retrieval date,
the legal status): given the same four it returns the same bytes. So
`the-re-ingest-reproduces-its-document` re-runs it over every rule this month re-ingested,
against the SNAPSHOT ALREADY COMMITTED, and fails if the result differs from the committed
document by one byte. A re-run that drifted is caught by CI on the next push rather than by
somebody running the command twice and looking."""
import argparse
import re
import sys
import tempfile
from collections import namedtuple
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml

import check_bulletin
import legal_status
# The one writer of a legal status, and the helpers this module would otherwise keep a
# second copy of. `report` says so in its own docstring -- "One printer, because both
# commands print the same shape and a second copy is where the two spellings drift
# apart" -- and the same argument covers `load_worklist` (one reader of one file that
# `check_bulletin.py` alone writes) and `_label` (one spelling of a path in a message).
from legal_status import (CATALOG_KEY, FORCE_ACTIONS, _label, catalog_rules,
                          load_worklist, report)
from enrich_oar import apply as enrich_apply
from enrich_oar import derive as enrich_derive
from enrich_oar import load_registry_by_chapter
from html_to_text import html_to_text
from ingest_lib import fetch, flow_to_lines
from ingest_oar import is_search_results_page, served_rule_number
from repo_lib import (REPO_ROOT, SNAPSHOT_DIR, Checks, content_hash, hash_snapshot,
                      normalize_volatile, snapshot_slice, ws_only, snapshot_text)

CATALOG = REPO_ROOT / "_meta/catalog/oar.yml"
# Read through `legal_status.load_worklist()`; named here only for the message
# `the-notice-is-readable` prints.
WORKLIST = legal_status.WORKLIST

# THE BULLETIN ACTIONS THAT CHANGE A RULE'S TEXT, and the whole of this path's mandate.
# ADR 0006: "An amendment is a text refresh the provenance chain already verifies, so it
# re-ingests automatically. A repeal or suspension is a claim about force and goes to a
# human." These three set NO legal status at all (CONTEXT.md, *Filed force action*).
#
# DECLARED, NOT DERIVED BY COMPLEMENT. Writing this as "every verb that is not a force
# action" would make a verb nobody has classified yet re-ingest AUTOMATICALLY on the day
# it is added upstream -- the dangerous default, chosen by omission. Declared, the two
# tables are checked against `check_bulletin.ACTIONS` for an EXACT partition, so a new
# verb stops this path and names itself instead.
TEXT_ACTIONS = ("adopt", "amend", "renumber")

# The one worklist state that means a document exists here to refresh. The other two --
# `missing_from_mirrored_chapter` and `chapter_not_mirrored` -- are a coverage gap and a
# boundary (ADR 0006, #227), and neither is a rule this path can re-ingest: there is
# nothing on disk to refresh and adopting one is a NEW document, which is `ingest_oar.py`'s
# job and not an automatic one.
#
# THIS IS THE FIELD'S VOCABULARY SPELLED A SECOND TIME, and `check_bulletin.py` writes it.
# A rename there would leave `select()` matching nothing, and a selection that matches
# nothing returns the same clean answer as one that matches everything -- the measurement
# error ADR 0006 records itself making, 121 rules wide. So `the-worklist-vocabulary-is-known`
# compares the two, and until it does this constant is not trusted.
HELD = "held"

# The two catalog keys a re-ingested row states, in the order they are written. Both or
# neither -- see the module docstring.
ACTION_KEY = "reingest_action"
NOTICE_KEY = "reingest_notice"
REINGEST_KEYS = (ACTION_KEY, NOTICE_KEY)

# A REFUSAL A ROW CAN CARRY (#245). `reingest_one` refuses for five reasons; one -- OARD
# unreachable -- clears on the next run, and the other four do not. Without somewhere to
# record them, a rule OARD permanently serves under a different number left
# `a-filed-text-action-is-re-ingested` red forever, reporting an UPSTREAM-AVAILABILITY fact
# under a rule that names a RECORDING failure. Two different things reading as one is the
# substitution ADR 0006 exists to refuse.
#
# The vocabulary is the INGEST one ingest_oar already writes -- not_served / renumbered /
# not_sliceable -- rather than a third, and these keys are deliberately NOT the re-ingest
# ones: a refusal that were spellable as a re-ingest would make
# `a-re-ingested-action-changes-text` stop meaning what it says.
REFUSED_KEY = "reingest_refused"
REFUSED_NOTICE_KEY = "reingest_refused_notice"
REFUSED_KEYS = (REFUSED_KEY, REFUSED_NOTICE_KEY)
REFUSAL_REASONS = ("not_served", "renumbered", "not_sliceable")

REGENERATE = "python3 src/reingest_oar.py --run"
TODAY = date.today().isoformat()

_FIRED = set()


class Failure(legal_status.Failure):
    """One rule, the thing it is about, and what is wrong with it.

    Subclassed rather than reused so this module's rule names are counted in ITS OWN
    `_FIRED` set: sharing `legal_status`'s would let a rule that never fired here be
    reported as watched because a rule of the same name fired there."""

    __slots__ = ()

    def __new__(cls, rule, site, detail):
        _FIRED.add(rule)
        return tuple.__new__(cls, (rule, site, detail))


# EVERY RULE THIS MODULE CAN REPORT, each demonstrated failing by a proof below. Compared
# against what the code actually emits, read out of this module's own syntax tree, so the
# declaration cannot drift from it.
CHECK_RULES = (
    # the split ADR 0006 turns on, and the vocabularies it is read through
    "every-filed-action-is-text-or-force", "the-worklist-vocabulary-is-known",
    # the notice, and the half no rule about an existing row can state
    "the-notice-is-readable", "a-filed-text-action-is-re-ingested",
    "a-refusal-is-recorded-in-the-ingest-vocabulary",
    "the-notice-names-the-re-ingest", "the-catalog-names-the-rule",
    # what a re-ingested row says
    "a-re-ingest-cites-its-notice", "a-re-ingested-action-changes-text",
    # what it may never have touched
    "a-force-marked-rule-is-not-re-ingested",
    # provenance, and the byte-identical re-run
    "a-re-ingested-rule-matches-its-snapshot", "the-re-ingest-reproduces-its-document",
)


# ------------------------------------------------------- the split ADR 0006 turns on


def check_partition(actions, text_actions, force_actions, corpus_states) -> list:
    """Every way the two tables stop covering the Bulletin's verbs exactly once.

    THE SPLIT IS THE SAFETY PROPERTY. `check_bulletin.ACTIONS` is what the bulletin reader
    can produce; this path re-ingests one side of it unattended and a person reviews the
    other. A verb in NEITHER table would be read by nothing; a verb in BOTH would be
    re-ingested and reviewed, and the re-ingest would run first; a table naming a verb the
    reader never emits is a classification of nothing, which reads exactly like one that
    is being enforced.

    Every argument is passed in so `--selftest` can fire this against synthetic tables --
    a rule that can only be run against the committed constants is one nobody can watch
    fail."""
    failures = []
    # AND THE OTHER VOCABULARY THIS PATH READS THE NOTICE THROUGH. `select()` keeps the
    # rows whose `corpus_state` is `held`; if `check_bulletin.py` renames that value this
    # path selects NOTHING, and nothing selected is indistinguishable from a month with
    # nothing filed. Checked here rather than trusted, for the same reason the actions are.
    if HELD not in corpus_states:
        failures.append(Failure(
            "the-worklist-vocabulary-is-known", HELD,
            f"is the worklist state this path re-ingests, and `check_bulletin.py` writes "
            f"{', '.join(corpus_states)}. A selection filtered on a value the notice no "
            "longer uses matches nothing, and matching nothing returns the same clean "
            "answer as matching everything -- which is the measurement error ADR 0006 "
            "records itself making"))
    both = sorted(set(text_actions) & set(force_actions))
    for a in both:
        failures.append(Failure(
            "every-filed-action-is-text-or-force", a,
            f"is classified as changing TEXT and as changing FORCE. ADR 0006 splits the "
            "Bulletin's actions on exactly that, and a verb on both sides is re-ingested "
            "automatically AND sent to a person -- with the re-ingest running first, so "
            "the review arrives after the thing it was meant to gate"))
    for a in sorted(set(actions) - set(text_actions) - set(force_actions)):
        failures.append(Failure(
            "every-filed-action-is-text-or-force", a,
            f"is an action the bulletin reader can report and neither "
            f"`{__name__}.TEXT_ACTIONS` nor `legal_status.FORCE_ACTIONS` classifies. It "
            "changes a rule's text or its force and nothing here says which, so the "
            "filing is read by nothing -- classify it rather than letting the default "
            "decide, which is what a complement would have done silently"))
    for a in sorted((set(text_actions) | set(force_actions)) - set(actions)):
        failures.append(Failure(
            "every-filed-action-is-text-or-force", a,
            "is classified here and `check_bulletin.ACTIONS` never reports it, so the "
            "classification governs no filing. A table naming a verb nothing emits reads "
            "exactly like one that is being enforced"))
    return failures


# ------------------------------------------------------------------- which rules, and why


class Refusal(namedtuple("Refusal", "status action")):
    """Why one rule the bulletin filed a text action against is NOT re-ingested: the legal
    status that bulletin put it in, and the verb that did it.

    A RECORD RATHER THAN A SENTENCE. This was one formatted string, and `_census()` got the
    status back out of it with `why.split(":")[0]` -- a structured fact flattened into prose
    at one end and parsed apart at the other, which is a fact declared twice with the
    formatting as the only thing holding them together."""

    __slots__ = ()

    def __str__(self):
        return (f"{self.status}: the same bulletin filed a {self.action} against it, and a "
                "claim about a rule's FORCE reaches a person (ADR 0006). Its text is left "
                "as served rather than refreshed automatically -- it is already listed in "
                "REVIEW.md")


class Candidate(namedtuple("Candidate", "number action row path")):
    """One rule this path will refresh: the number the Bulletin named, the text action it
    filed, the OAR catalog row that carries the record, and the document to rewrite."""

    __slots__ = ()


def rows_by_rule_number(catalog) -> dict:
    """{rule number: the OAR catalog row that serves it}.

    KEYED ON BOTH `number` AND `served_as`, because 484 rows are the number this corpus
    ASKED FOR and the document on disk is filed under the number OARD SERVED -- 42 of the
    318 rules this month's bulletin amends are reachable only through `served_as`, and a
    lookup on `number` alone would report them as rules the catalog does not name. A row's
    own `number` WINS a collision (5 served-as values are also some other row's number):
    it is the row's identity, and the fallback is a redirect."""
    by_served = {r["served_as"]: r for r in catalog_rules(catalog) if r.get("served_as")}
    by_number = {r["number"]: r for r in catalog_rules(catalog) if r.get("number")}
    return {**by_served, **by_number}


def select(worklist, catalog) -> tuple:
    """(candidates, {number: why it was refused}, Failures) for one bulletin.

    THE ONE PLACE THIS PATH DECIDES WHAT IT TOUCHES, called by `--run` and by `--check`
    alike. A second copy of this precedence would let the thing that re-ingests and the
    gate that audits it disagree about the same month, which is the one-fact-written-twice
    failure this area exists to refuse.

    A RULE THE BULLETIN TOOK OUT OF FORCE IS REFUSED, EVEN WHERE THE SAME BULLETIN AMENDED
    IT. August 2026 did that to 12 rules. Selecting them would leave the whole safety
    property resting on `resolve()` being handed the right argument one line later; refusing
    them by RULE means an automatic write to a repealed rule's document cannot be reached
    at all, and the refusal is NAMED rather than silent -- the rule is already in front of a
    person, in REVIEW.md, because `legal_status.py --mark` put it there.

    Everything is passed in so `--selftest` can fire the whole decision against synthetic
    worklists -- a selection that can only run against the committed file is one nobody can
    watch refuse."""
    # NOTHING TO CHECK AGAINST IS NOT A CLEAN BILL. A worklist that could not be read names
    # no filings, and no filings is exactly what a month with nothing outstanding looks
    # like -- so this refuses rather than reporting the corpus up to date on the strength
    # of having read nothing (ADR 0006: could not check is never reported as is not there).
    rules = worklist.get("rules") if isinstance(worklist, dict) else None
    if not isinstance(rules, list) or not rules:
        return [], {}, [Failure(
            "the-notice-is-readable", _label(WORKLIST),
            f"holds no rule actions ({rules!r}), so nothing here can say which rules this "
            "month amended. Every bulletin measured has named hundreds; a worklist that "
            "could not be read and a month in which nothing was filed are different "
            "things -- run: python3 src/check_bulletin.py")]

    rows = rows_by_rule_number(catalog)
    # WHAT THE BULLETIN DID TO EACH RULE'S FORCE, read from `legal_status`. Not re-derived
    # here: the action-to-force table is a decision about Oregon law and ADR 0006 allows it
    # one place, so this path asks the one writer rather than keeping a second copy of the
    # two verbs that matter.
    force = legal_status.filed_force_actions(worklist)
    filed = {}
    for row in rules:
        if not isinstance(row, dict) or row.get("corpus_state") != HELD:
            continue
        if row.get("action") in TEXT_ACTIONS:
            filed.setdefault(row.get("number"), row["action"])

    picked, refused, problems = [], {}, []
    for number, action in sorted(filed.items()):
        if number in force:
            status, action_taken = force[number]
            refused[number] = Refusal(status, action_taken)
            continue
        row = rows.get(number)
        if row is None or not row.get("path"):
            problems.append(Failure(
                "the-catalog-names-the-rule", f"{number}",
                f"the Bulletin filed a {action} against it and this corpus holds the rule, "
                f"and the OAR catalog {'names no such rule' if row is None else 'names no path for it'}. "
                "The catalog is what a citation resolves through and what a re-ingest "
                "records itself on -- a rule reachable from neither is drift, not an "
                "accident"))
            continue
        picked.append(Candidate(number, action, row, REPO_ROOT / row["path"]))
    return picked, refused, problems




# ------------------------------------------------------- the refresh, and what it leaves

# THE THREE SECTIONS EVERY RULE DOCUMENT HAS, and the split that keeps a rule's own
# verbatim text from being scanned for provenance. All 36,955 of them are written
# `## At a glance` / `## Full text` / `## Provenance & change history`, in that order.
SECTIONS_RE = re.compile(
    r"\A(?P<head>.*?\n## Full text\n\n)(?P<body>.*?)"
    r"(?P<tail>\n\n## Provenance & change history\n.*)\Z", re.S)

# What in the HEAD says when this copy was taken and of what.
FM_RETRIEVED_RE = re.compile(r'^retrieved: "[^"]*"$', re.M)
FM_SHA_RE = re.compile(r'^source_sha256: "[0-9a-f]{64}"$', re.M)
DISCLAIMER_RE = re.compile(r"^(> <[^>]*>) \(retrieved \d{4}-\d{2}-\d{2}\)\.$", re.M)
# ...and what says it in the TAIL.
PROVENANCE_RE = re.compile(
    r"^(- Source: <[^>]*> ·) retrieved \d{4}-\d{2}-\d{2} · sha256 `[0-9a-f]{64}`$", re.M)


def refresh(text: str, full_text: str, sha: str, retrieved: str):
    """One rule document with its TEXT AND PROVENANCE REPLACED and everything else kept.
    None where the document is not in a shape this can parse.

    A PURE FUNCTION OF ITS FOUR ARGUMENTS, which is what makes "re-running produces
    byte-identical output" a gate rather than an observation: `--check` re-runs it over
    every rule this month re-ingested, against the snapshot already committed, and fails
    on a one-byte difference.

    WHAT IT DOES NOT TOUCH, deliberately and by construction:

      the legal status   `enrich_oar.apply()` stamps it from `legal_status.resolve()`,
                         which is the one writer (ADR 0006). THERE IS NO LEGAL-STATUS
                         LITERAL IN THIS MODULE and `legal_status.py --check` reads the
                         syntax tree to make sure it stays that way. A re-ingest that
                         wrote the field here is exactly the resurrection #228 built its
                         gate for.
      relationships      `link_enabling_authority.py` and `link_graph.py` put thousands of
                         edges into these documents. Regenerating from the ingest template
                         would satisfy "the rule was re-ingested" by deleting them.
      `## At a glance`   curator-authored under this repository's content policy.
      upstream tracking, `mark_upstream_tracking.py` and the enricher own these fields; a
      the derived        second writer of any of them is the failure this whole area is
      frontmatter        built around.

    A DOCUMENT IT CANNOT PARSE COMES BACK None RATHER THAN UNCHANGED. Returning the input
    would make a refresh that found nothing to change indistinguishable from one whose
    markers had moved, and the second is a silent stop."""
    m = SECTIONS_RE.match(text)
    if not m:
        return None
    head, tail = m.group("head"), m.group("tail")
    head, n_ret = FM_RETRIEVED_RE.subn(f'retrieved: "{retrieved}"', head, count=1)
    head, n_sha = FM_SHA_RE.subn(f'source_sha256: "{sha}"', head, count=1)
    head, n_dis = DISCLAIMER_RE.subn(rf"\1 (retrieved {retrieved}).", head, count=1)
    tail, n_prov = PROVENANCE_RE.subn(
        rf"\1 retrieved {retrieved} · sha256 `{sha}`", tail, count=1)
    if not (n_ret and n_sha and n_dis and n_prov):
        return None
    return head + full_text + tail


# ------------------------------------------------------------------- what the catalog says


def check_rows(catalog) -> list:
    """Every way a COMMITTED catalog row records a re-ingest wrongly, as Failures.

    Row-local: everything here is decidable from the row alone, without a bulletin. The
    half that needs the notice is `check_recorded()` below, and it is the half that cannot
    be satisfied by having done nothing."""
    failures = []
    for r in catalog_rules(catalog):
        num = r.get("number")
        present = [k for k in REINGEST_KEYS if r.get(k) is not None]
        if present and len(present) != len(REINGEST_KEYS):
            failures.append(Failure(
                "a-re-ingest-cites-its-notice", f"{num}",
                f"holds {', '.join(present)} and not "
                f"{', '.join(k for k in REINGEST_KEYS if k not in present)}. The two are "
                "one record and arrive together: the notice alone cannot say which filing "
                "was applied, and the action alone is a fact about no particular month -- "
                f"re-derive with: {REGENERATE}"))
            continue
        action = r.get(ACTION_KEY)
        if action is None:
            continue
        if action not in TEXT_ACTIONS:
            failures.append(Failure(
                "a-re-ingested-action-changes-text", f"{num}",
                f"{ACTION_KEY}={action!r} is not one of the actions that change a rule's "
                f"TEXT ({', '.join(TEXT_ACTIONS)}). This path re-ingests without asking "
                "anybody, so the only filings it may record are the ones ADR 0006 says a "
                "human adds nothing to. A repeal or a suspension recorded here is an "
                "automatic write to a rule that lost its force"))
        # MARKED, NEVER RE-INGESTED. Read off the row rather than re-derived: the Bulletin
        # is the one writer of a legal status and this module asks it rather than keeping
        # a second opinion. A row stripped of its `legal_status` to get past this is caught
        # by `legal_status.py --check`, which reads the same notice and demands it back.
        if r.get(CATALOG_KEY) is not None:
            failures.append(Failure(
                "a-force-marked-rule-is-not-re-ingested", f"{num}",
                f"carries {CATALOG_KEY}={r[CATALOG_KEY]!r} filed by "
                f"{r.get('legal_status_notice')!r} AND a record that this path re-ingested "
                f"it for {r.get(NOTICE_KEY)!r}. A rule the Bulletin took out of force is "
                "MARKED AND LEFT (ADR 0006) and reaches a person through REVIEW.md; an "
                "unattended re-ingest of one is how a repealed rule comes back as current "
                "under provenance, which is the failure this whole path is shaped around"))
    return failures


def check_recorded(catalog, worklist) -> list:
    """What the NOTICE says the catalog should hold, and what it holds that the notice does
    not support. The rule that makes every rule in `check_rows` unsatisfiable by inaction.

    SCOPED TO THE BULLETIN THIS WORKLIST HOLDS. This corpus keeps one month's worklist at a
    time, so a row citing an earlier bulletin is one this run has nothing to read against --
    left alone rather than reported, because could not check is never reported as is not
    there."""
    picked, refused, failures = select(worklist, catalog)
    if failures and any(f.rule == "the-notice-is-readable" for f in failures):
        return failures
    notice = worklist.get("bulletin")
    for c in picked:
        held = tuple(c.row.get(k) for k in REINGEST_KEYS)
        if held == (c.action, notice):
            continue
        # REFUSED, AND HERE IS WHY (#245) -- against THIS bulletin, in the ingest
        # vocabulary. An upstream-availability fact recorded as one, rather than a
        # recording failure that can never be cleared.
        refused = c.row.get(REFUSED_KEY)
        if refused and c.row.get(REFUSED_NOTICE_KEY) == notice:
            if refused not in REFUSAL_REASONS:
                failures.append(Failure(
                    "a-refusal-is-recorded-in-the-ingest-vocabulary", f"{c.number}",
                    f"is refused as {refused!r}, which is not one of "
                    f"{', '.join(REFUSAL_REASONS)}. A reason nothing else in this repository "
                    f"writes is one nobody can act on"))
            continue
        failures.append(Failure(
            "a-filed-text-action-is-re-ingested", f"{c.number}",
            f"{notice} filed a {c.action} against it and this corpus holds the rule, "
            f"and its catalog row says {held!r} rather than {(c.action, notice)!r}. "
            "Until the row says so the document is served as though its text had not "
            f"changed -- run: {REGENERATE}"))
    # THE REVERSE SCAN WALKS ROWS, NOT NAMES. 484 rows are reachable under TWO rule
    # numbers -- the one this corpus asked OARD for and the `served_as` the document is
    # filed under -- so a map keyed by number yields the same row twice, and asking
    # "is this NAME one we re-ingested" reported all 42 of this month's served-as rules as
    # citing a bulletin that had not named them. It had: under their other name. So the row
    # is identified by its OWN `number` -- the catalog's primary key, the one name every
    # row has exactly once -- and not by whichever of its two names the bulletin used.
    wanted = {c.row.get("number") for c in picked}
    for row in catalog_rules(catalog):
        number = row.get("number")
        if row.get(NOTICE_KEY) != notice or number in wanted:
            continue
        why = refused.get(number) or refused.get(row.get("served_as"))
        failures.append(Failure(
            "the-notice-names-the-re-ingest", f"{number}",
            f"cites {notice!r} for a {row.get(ACTION_KEY)!r} this path did not re-ingest. "
            + (f"That bulletin took the rule out of force -- {why}"
               if why else
               "That bulletin filed no text action against a rule this corpus holds under "
               "this number. A claim whose citation does not support it is worse than an "
               "uncited one, because it looks checked")))
    return failures


def check_document(number, text, snapshot, committed_sha) -> list:
    """PROVENANCE, AND THE BYTE-IDENTICAL RE-RUN, for ONE document -- decided from the
    three strings and nothing else.

    Two facts about one file, and the second is the one a re-run could break. The hash the
    document publishes must be the hash of the snapshot committed beside it -- that is the
    chain `corpus-verify-provenance` walks, and it is what makes an amendment a text
    refresh nobody has to approve. And `refresh()` run again over that same snapshot must
    return the document BYTE FOR BYTE, which turns "re-running produces byte-identical
    output" from something somebody observed once into something CI fails on.

    NOTHING HERE OPENS A FILE, so `--selftest` can fire both rules by handing it a MUTATED
    COPY of a committed document -- proving them against the corpus they govern without
    writing to the working tree. A selftest that edits a committed file and puts it back
    is one that fails the build for any gate unlucky enough to read it in between, and
    leaves the tree dirty if it dies in the middle."""
    doc_id = f"oar-{number}"
    failures = []
    m = FM_SHA_RE.search(text)
    stated = m.group(0).split('"')[1] if m else None
    if stated != committed_sha:
        return [Failure(
            "a-re-ingested-rule-matches-its-snapshot", f"{number}",
            f"publishes source_sha256 {stated!r} and the snapshot committed beside it "
            f"hashes to {committed_sha!r}. The document's provenance no longer covers the "
            f"text it serves -- run: {REGENERATE}")]
    again = refresh(text, flow_to_lines(snapshot_slice(doc_id, doc_id, snapshot)),
                    committed_sha, _retrieved(text))
    if again != text:
        failures.append(Failure(
            "the-re-ingest-reproduces-its-document", f"{number}",
            "re-running the refresh over the snapshot this document cites does not "
            "reproduce it" + (" -- the document is not in a shape the refresh can parse"
                              if again is None else " byte for byte") +
            f". A re-ingest whose output depends on anything but its source is one nobody "
            f"can re-run to check -- run: {REGENERATE}"))
    return failures


def recorded(catalog) -> list:
    """A Candidate for EVERY catalog row that records a re-ingest, whatever bulletin filed it.

    `select()` answers "what does THIS month's notice ask for"; this answers "what has this
    path ever written". Provenance and the byte-identical re-run are checked over THIS set,
    so the ground they cover only grows -- checking only the current month would shrink the
    guarantee to nothing the day a new bulletin lands, which is a gate that quietly stops
    covering what it already passed.

    Keyed on the number the DOCUMENT is filed under -- `served_as` where the row has one,
    because 484 rows name the number this corpus asked OARD for and not the one it serves."""
    out = []
    for r in catalog_rules(catalog):
        if r.get(NOTICE_KEY) is None or not r.get("path"):
            continue
        out.append(Candidate(r.get("served_as") or r.get("number"), r.get(ACTION_KEY), r,
                             REPO_ROOT / r["path"]))
    return out


def check_documents(candidates) -> list:
    """`check_document()` over every rule this path re-ingested, reading each from disk.

    The thin half: this is where a file that cannot be opened at all is reported, because
    a document the catalog names and nothing serves is a finding rather than a skip."""
    failures = []
    for c in candidates:
        doc_id = f"oar-{c.number}"
        try:
            text = c.path.read_text()
            snapshot = (SNAPSHOT_DIR / f"{doc_id}.txt").read_text()
            committed = hash_snapshot(doc_id, "html")
        except OSError as e:
            failures.append(Failure(
                "a-re-ingested-rule-matches-its-snapshot", f"{c.number}",
                f"{_label(c.path)} or the snapshot beside it could not be read ({e}). The "
                "catalog names it as a document this path refreshed; a re-ingest that kept "
                "no readable copy of what it fetched publishes a hash nothing can be "
                "checked against"))
            continue
        failures.extend(check_document(c.number, text, snapshot, committed))
    return failures


def _retrieved(text: str):
    """The retrieval date a document already states. Read rather than assumed: `refresh()`
    is checked as a FIXED POINT here, so the date it is handed has to be the document's own
    or every row would differ on the date alone and the rule would report drift that is not
    there."""
    m = FM_RETRIEVED_RE.search(text)
    return m.group(0).split('"')[1] if m else None


# ------------------------------------------------------------------------------ commands


def _census(catalog, worklist, picked, refused) -> None:
    """The numbers a clean run prints, MEASURED rather than asserted.

    A summary whose interesting figure is the literal `0` says nothing a clean run does not
    already imply. These are on screen so that a run which silently stopped selecting
    anything, or silently started re-ingesting rules the Bulletin took out of force, is
    visible as a number that moved."""
    marked = [r for r in catalog_rules(catalog) if r.get(CATALOG_KEY) is not None]
    reingested = [r for r in catalog_rules(catalog) if r.get(NOTICE_KEY) is not None]
    print(f"{worklist.get('bulletin')}: {len(picked)} rule(s) re-ingested by this path, "
          f"{len(refused)} refused")
    for number, why in sorted(refused.items()):
        print(f"  REFUSED OAR {number} — a filed {why.action} put it {why.status}; its "
              "text is left as served and a person reviews it (REVIEW.md)")
    print(f"{len(reingested)} catalog row(s) record a re-ingest, every one for an action "
          f"that changes TEXT ({', '.join(TEXT_ACTIONS)}) and cited to the bulletin that "
          "filed it")
    # THE ONE NUMBER THIS TICKET IS ABOUT. Printed on every run because a guarantee that
    # can only be watched NOT firing is one nobody can tell from a guard that stopped
    # running -- and because it went from 0 to 100 when #229 landed.
    # COUNTED, NOT ASSERTED. Printing the words "none of them is re-ingested" states the
    # safety property in the one mode that has not checked it -- a positive claim from no
    # evidence, in the command a human runs by hand. The number is what `--check` refuses
    # a non-zero value of, under `a-force-marked-rule-is-not-re-ingested`.
    both = sum(1 for r in marked if r.get(NOTICE_KEY) is not None)
    print(f"{len(marked)} catalog row(s) carry a Bulletin-set `{CATALOG_KEY}` — "
          + (", ".join(f"{a} {sum(1 for r in marked if r.get('legal_status_action') == a)}"
                       for a in sorted(FORCE_ACTIONS)) or "none")
          + f"; {both} of them ALSO record a re-ingest by this path, and "
          f"{len(refused)} were amended by this bulletin and refused by name")


def cmd_check() -> int:
    catalog = yaml.safe_load(CATALOG.read_text())
    worklist = load_worklist()
    failures = (check_partition(check_bulletin.ACTIONS, TEXT_ACTIONS, FORCE_ACTIONS,
                                check_bulletin.CORPUS_STATES)
                + check_rows(catalog) + check_recorded(catalog, worklist))
    kept = recorded(catalog)
    failures += check_documents(kept)
    picked, refused = [], {}
    if not any(f.rule == "the-notice-is-readable" for f in failures):
        picked, refused, _ = select(worklist, catalog)
    if report(failures):
        print(f"\n{len(failures)} re-ingest violation(s)", file=sys.stderr)
        return 1
    print(f"{len(check_bulletin.ACTIONS)} bulletin action(s), split exactly: "
          f"{', '.join(TEXT_ACTIONS)} change TEXT and re-ingest here without asking; "
          f"{', '.join(sorted(FORCE_ACTIONS))} change FORCE and reach a person")
    _census(catalog, worklist, picked, refused)
    print(f"{len(kept)} document(s) this path has ever re-ingested, EVERY bulletin "
          "included, verified against the snapshot committed beside them and reproduced "
          "byte for byte by re-running the refresh over it")
    return 0


def cmd_report() -> int:
    """What this month's bulletin asks of this path, without touching anything."""
    catalog = yaml.safe_load(CATALOG.read_text())
    worklist = load_worklist()
    picked, refused, problems = select(worklist, catalog)
    if report(problems):
        return 1
    _census(catalog, worklist, picked, refused)
    todo = [c for c in picked
            if tuple(c.row.get(k) for k in REINGEST_KEYS)
            != (c.action, worklist.get("bulletin"))]
    print(f"{len(todo)} rule(s) outstanding — run: {REGENERATE}")
    return 0


# ---------------------------------------------------------------------------- the re-ingest


def _record_refusal(candidate, reason, notice) -> None:
    """Write the refusal onto the row, so `--check` can tell REFUSED, AND HERE IS WHY from
    NOBODY RAN IT. Silent when no notice is in hand -- the selftest calls this path with
    none, and a refusal that cited no bulletin would be a claim about no particular month."""
    if notice is None:
        return
    candidate.row[REFUSED_KEY] = reason
    candidate.row[REFUSED_NOTICE_KEY] = notice


def reingest_one(candidate, registry_by_chapter, today, fetch_page=None,
                 notice=None) -> tuple:
    """Refresh ONE rule from OARD. (True if the document changed, Failures).

    `fetch_page` is the network, injected so nothing here has to be reached through a
    live site to be exercised.

    EVERY REFUSAL BELOW IS A CLAIM ABOUT FORCE WEARING A TEXT ACTION'S CLOTHES. The
    bulletin said this rule's TEXT changed; if OARD now serves no rule number, or serves a
    DIFFERENT one, or serves a page with no rule body in it, then what happened upstream is
    not the amendment that was filed -- it is a repeal, a renumber or an outage, and none of
    the three is something this path may apply without asking. So each stops at this rule
    and is reported, rather than being written into a document under provenance.

    A REFUSAL THAT DOES NOT CLEAR IS FILED AS #245. The transient one -- OARD unreachable --
    goes away on the next run. The others do not: if OARD permanently serves a different
    number, the row is never recorded and `a-filed-text-action-is-re-ingested` stays red,
    reporting an upstream-availability fact under a rule that names a recording failure.
    There is no way yet for a row to say REFUSED, AND HERE IS WHY, the way `select()` says
    it for a rule out of force. Zero rules are in that state today (306 of 306 fetched,
    sliced and recorded), which is why it is an issue and not a branch here."""
    number, doc_id = candidate.number, f"oar-{candidate.number}"
    url = f"https://secure.sos.state.or.us/oard/view.action?ruleNumber={number}"
    fetch_page = fetch_page or (lambda u: normalize_volatile(fetch(u)))
    try:
        raw = fetch_page(url)
    except Exception as e:                                    # noqa: BLE001 -- see below
        # ONE RULE'S OUTAGE IS NOT THE MONTH'S. A raised exception here would stop the run
        # part-way through 306 rules with the catalog half-written; the rule is recorded as
        # not re-ingested instead, and `a-filed-text-action-is-re-ingested` keeps demanding
        # it until it is.
        return False, [Failure(
            "a-filed-text-action-is-re-ingested", f"{number}",
            f"could not be fetched from OARD ({e}). The bulletin says its text changed and "
            "this corpus still serves the old text -- re-run when the source is reachable")]
    text = snapshot_text(raw)
    served = served_rule_number(ws_only(text))
    if served and re.search(re.escape(served) + r"\s+not found", ws_only(text)):
        served = None
    if served is None:
        _record_refusal(candidate, 'not_served', notice)
        return False, [Failure(
            "a-filed-text-action-is-re-ingested", f"{number}",
            "OARD serves no rule number for it. The bulletin filed a text action and the "
            "page that came back is not a rule -- most likely the rule is gone, which is a "
            "claim about FORCE and reaches a person (ADR 0006), not an automatic write")]
    if served != number:
        _record_refusal(candidate, 'renumbered', notice)
        return False, [Failure(
            "a-filed-text-action-is-re-ingested", f"{number}",
            f"OARD serves {served} for this number. A re-ingest that wrote that page into "
            f"this document would publish one rule's text under another's citation -- the "
            "125-800 -> 128-030 lesson. Renumbering is recorded by the catalog, not here")]
    if is_search_results_page(ws_only(text)):
        _record_refusal(candidate, 'not_sliceable', notice)
        return False, [Failure(
            "a-filed-text-action-is-re-ingested", f"{number}",
            "OARD serves a search-results list for this number rather than a rule -- more "
            "than one rule shares it. Refreshing from it would publish the titles of the "
            "rules that matched, plus the site footer, as this rule's text (#251)")]
    body = snapshot_slice(doc_id, doc_id, text)
    if len(body) < 100:
        _record_refusal(candidate, 'not_sliceable', notice)
        return False, [Failure(
            "a-filed-text-action-is-re-ingested", f"{number}",
            "the OARD page carries no rule body this can slice. An empty refresh would "
            "replace the served text with nothing and call the rule re-ingested")]
    old = candidate.path.read_text()
    sha = content_hash(raw, "html")
    full_text = flow_to_lines(body)
    # THE SOURCE HAS NOT MOVED, SO NEITHER DOES THE DOCUMENT. `retrieved` is the date THESE
    # BYTES were taken, not the date somebody last looked -- that fact lives in
    # `_meta/sources/oar.yml`'s `last_checked`, which `check_updates.py` owns. Stamping
    # today over an unchanged copy would claim a new observation of the same page and make
    # RE-RUNNING THIS COMMAND REWRITE ALL 306 DOCUMENTS ON ANY LATER DAY -- the acceptance
    # criterion is byte-identical output from a re-run, not from a re-run that happens
    # before midnight. Compared as a FIXED POINT rather than on the hash alone: an
    # unchanged page whose document had drifted from it is a document that still needs
    # rewriting, and the hash on its own cannot tell the two apart.
    if refresh(old, full_text, sha, _retrieved(old)) == old:
        return False, []
    new = refresh(old, full_text, sha, today)
    if new is None:
        return False, [Failure(
            "the-re-ingest-reproduces-its-document", f"{number}",
            f"{_label(candidate.path)} is not in a shape the refresh can parse, so this "
            "rule's text cannot be replaced without rewriting the parts of the document "
            "other tools own")]
    (SNAPSHOT_DIR / f"{doc_id}.html").write_bytes(raw)
    (SNAPSHOT_DIR / f"{doc_id}.txt").write_text(text, encoding="utf-8")
    candidate.path.write_text(new)
    # THE LEGAL STATUS IS NOT THIS PATH'S TO DECIDE, and this is where that is cashed in.
    # `enrich_oar` re-derives the frontmatter the amended text changed -- authority,
    # statutes implemented, effective date, the AON source version -- and stamps the status
    # `legal_status.resolve()` returns. The Bulletin-set status is handed over EXPLICITLY
    # even though `select()` has already refused every rule that has one: `resolve()`
    # returns it unchanged whatever else it is given, so the resurrection is unreachable
    # by a second independent means and not merely by this path picking the right rules.
    enrich_apply(candidate.path, enrich_derive(
        full_text, doc_id, registry_by_chapter,
        candidate.row.get(CATALOG_KEY), _doc_status(new)))
    committed = hash_snapshot(doc_id, "html")
    if committed != sha:
        return True, [Failure(
            "a-re-ingested-rule-matches-its-snapshot", f"{number}",
            f"was written publishing {sha!r} and the snapshot committed beside it hashes "
            f"to {committed!r}")]
    return candidate.path.read_text() != old, []


def _doc_status(text: str):
    """What a document's frontmatter already says its legal status is, or None.

    Handed to `legal_status.resolve()` as `existing=` through the enricher -- step 3 of the
    order of authority, the one that keeps a caller who has learned nothing new from
    asserting over what the document holds. Read from the FRONTMATTER BLOCK ONLY: a rule's
    verbatim text can print `status:` at the start of a line."""
    block = legal_status.FRONTMATTER_BLOCK_RE.match(text)
    m = legal_status.DOC_STATUS_RE.search(block.group(1)) if block else None
    return m.group(1) if m else None


def cmd_run() -> int:
    """Re-ingest every rule this month's bulletin changed the TEXT of. No approval asked.

    A REPEAL OR A SUSPENSION NEVER REACHES THIS FUNCTION -- `select()` refuses it and
    `legal_status.py --mark` has already put it in front of a person. What this writes is a
    text refresh whose provenance chain verifies, which is the whole of what ADR 0006 says
    may happen unattended."""
    catalog = yaml.safe_load(CATALOG.read_text())
    worklist = load_worklist()
    picked, refused, problems = select(worklist, catalog)
    if report(problems):
        print(f"\n{len(problems)} rule(s) the bulletin named and this path cannot reach",
              file=sys.stderr)
        return 1
    registry = load_registry_by_chapter()
    notice, changed, failures = worklist.get("bulletin"), 0, []
    for i, c in enumerate(picked, 1):
        wrote, problems = reingest_one(c, registry, TODAY, notice=notice)
        failures += problems
        if problems:
            continue
        # A rule that re-ingests is not refused, whatever an earlier month recorded.
        for key in REFUSED_KEYS:
            c.row.pop(key, None)
        changed += bool(wrote)
        for key, value in zip(REINGEST_KEYS, (c.action, notice)):
            c.row[key] = value
        if i % 25 == 0:
            print(f"...{i}/{len(picked)} re-ingested, {changed} document(s) rewritten")
    CATALOG.write_text(yaml.safe_dump(catalog, sort_keys=False, allow_unicode=True,
                                      width=100))
    report(failures)
    _census(catalog, worklist, picked, refused)
    print(f"{len(picked) - len(failures)} rule(s) re-ingested, {changed} document(s) "
          f"rewritten, {len(failures)} refused mid-run")
    print(f"{worklist.get('bulletin_url')}")
    return 1 if failures else 0


# ------------------------------------------------------------------------------ selftest
#
# THE PROOF THAT EVERYTHING ABOVE CAN FAIL. Every fixture below is synthetic except where a
# proof says otherwise -- the two that matter most are fired against COMMITTED data, because
# a rule proved only against a fixture is one nobody has watched work on the corpus it
# governs.


def _proof_the_split_is_exact(check) -> None:
    """THE SPLIT ADR 0006 TURNS ON, fired against synthetic tables and then the real ones.

    A partition rule is the easiest thing in this file to write vacuously: compare two
    tables that were written from each other and it passes forever. So it is fired on all
    three ways the cover can break BEFORE the committed tables are looked at."""
    states = check_bulletin.CORPUS_STATES
    both = check_partition(("amend", "repeal"), ("amend", "repeal"), ("repeal",), states)
    check("a verb classified as changing both text and force is caught",
          any(f.rule == "every-filed-action-is-text-or-force" and f.site == "repeal"
              for f in both))
    neither = check_partition(("amend", "repeal", "recall"), ("amend",), ("repeal",),
                              states)
    check("a verb the reader emits and neither table classifies is caught",
          any(f.site == "recall" for f in neither))
    phantom = check_partition(("amend",), ("amend", "rescind"), (), states)
    check("a verb classified here that the reader never emits is caught",
          any(f.site == "rescind" for f in phantom))
    check("...and the committed tables partition the committed actions exactly",
          not check_partition(check_bulletin.ACTIONS, TEXT_ACTIONS, FORCE_ACTIONS, states))
    check("...over every verb the bulletin reader can report, not a subset",
          set(TEXT_ACTIONS) | set(FORCE_ACTIONS) == set(check_bulletin.ACTIONS))
    # THE OTHER VOCABULARY, fired the same way: renamed upstream, this path selects nothing
    # and a corpus that re-ingested nothing looks exactly like one with nothing to do.
    check("a worklist state this path filters on that the reader no longer writes is caught",
          any(f.rule == "the-worklist-vocabulary-is-known" for f in check_partition(
              check_bulletin.ACTIONS, TEXT_ACTIONS, FORCE_ACTIONS,
              ("in_corpus", "missing_from_mirrored_chapter"))))
    check("...and the committed worklist vocabulary still contains it",
          HELD in check_bulletin.CORPUS_STATES)



FIXTURE_NOTICE = "August 2026 (bulltnRsn=1761)"


def _fixture_catalog(*rules) -> dict:
    """An OAR catalog in the committed file's shape, one division, the rows given."""
    return {"chapters": [{"chapter": "999", "divisions": [
        {"division": "001", "rules": [dict(r) for r in rules]}]}]}


def _fixture_worklist(*actions, bulletin=FIXTURE_NOTICE) -> dict:
    """A bulletin worklist in `check_bulletin.py`'s shape. Each action is
    (number, action, corpus_state)."""
    return {"bulletin": bulletin, "rules": [
        {"number": n, "action": a, "corpus_state": c} for n, a, c in actions]}


def _row(number, **kw) -> dict:
    return dict({"number": number, "status": "ingested",
                 "path": f"rules/999/001/oar-{number}.md"}, **kw)


def _proof_selection(check) -> None:
    """WHICH RULES THIS PATH TOUCHES, and the three ways that question is answered wrongly.

    THE SPLIT IS PROVED BY EXCLUSION, NOT BY ABSENCE. A selection that excluded repeals
    because the fixture contained none would pass this proof and every rule below while
    being a claim from no evidence, so each case puts the rule it is about IN the worklist
    and asserts what came out."""
    cat = _fixture_catalog(_row("999-001-0010"), _row("999-001-0020"),
                           _row("999-001-0030"), _row("999-001-0040"))
    picked, refused, problems = select(
        _fixture_worklist(("999-001-0010", "amend", HELD),
                          ("999-001-0020", "repeal", HELD),
                          ("999-001-0030", "suspend", HELD)), cat)
    check("an amended rule this corpus holds is selected",
          [c.number for c in picked] == ["999-001-0010"])
    check("a repealed rule in the same bulletin is not",
          "999-001-0020" not in {c.number for c in picked})
    check("a suspended rule in the same bulletin is not",
          "999-001-0030" not in {c.number for c in picked})
    check("...and neither is REFUSED either: this bulletin filed no text action against "
          "them, so they were never candidates -- a rule refused and a rule never "
          "considered are different facts", refused == {})
    check("...with nothing to report as a fault", not problems)

    # THE OVERLAP CASE, and the reason this path refuses by RULE rather than by row.
    # August 2026 amended 12 rules it also repealed or suspended. Selecting them would
    # leave the whole safety property resting on `resolve()` being called correctly one
    # line later; refusing them means the resurrection cannot be reached at all.
    picked, refused, _ = select(
        _fixture_worklist(("999-001-0010", "amend", HELD),
                          ("999-001-0010", "repeal", HELD)), cat)
    check("a rule amended AND repealed by one bulletin is not re-ingested",
          not picked and "999-001-0010" in refused)
    check("...and the refusal names the force action and the status it produced",
          refused["999-001-0010"] == Refusal("repealed", "repeal"))

    picked, _, _ = select(
        _fixture_worklist(("999-001-0010", "amend", "missing_from_mirrored_chapter"),
                          ("999-001-0020", "adopt", "chapter_not_mirrored")), cat)
    check("a rule no document here serves is not re-ingested", not picked)

    _, _, problems = select(
        _fixture_worklist(("999-001-0099", "amend", "held")), cat)
    check("a held rule the catalog cannot reach is a fault, not a quiet skip",
          any(f.rule == "the-catalog-names-the-rule" for f in problems))

    for bad in (None, {}, {"rules": []}, {"rules": None}, "not a mapping"):
        picked, _, problems = select(bad, cat)
        check(f"an unreadable notice is refused, not read as a quiet month ({bad!r})",
              any(f.rule == "the-notice-is-readable" for f in problems) and not picked)


def _proof_the_committed_selection(check) -> None:
    """THE SAME QUESTION AGAINST THE COMMITTED BULLETIN, because a selection proved only
    on fixtures is one nobody has watched run on the corpus it governs.

    Every number here is MEASURED from the committed worklist rather than written down, so
    a month that files different filings does not make this proof a lie -- but the SHAPE is
    asserted: the selection is non-empty, the refusals are non-empty, and the two together
    account for every held text action the bulletin filed."""
    catalog = yaml.safe_load(CATALOG.read_text())
    worklist = load_worklist()
    picked, refused, problems = select(worklist, catalog)
    filed = {r["number"] for r in (worklist.get("rules") or [])
             if r.get("corpus_state") == HELD and r.get("action") in TEXT_ACTIONS}
    force = set(legal_status.filed_force_actions(worklist))
    check("the committed bulletin selects rules to re-ingest at all", len(picked) > 0)
    check("...and every one of them is a text action the bulletin filed",
          {c.number for c in picked} <= filed)
    check("...and every held text action is either selected or refused by name",
          filed == {c.number for c in picked} | set(refused))
    check("the rules this bulletin took out of force are non-empty", len(force) > 0)
    check("...and NONE of them is selected", not (force & {c.number for c in picked}))
    check("...including the ones the same bulletin also amended, which is not vacuous",
          len(force & filed) > 0 and (force & filed) <= set(refused))
    check("nothing about the committed selection is reported as a fault", not problems)



def _fixture_doc() -> str:
    """A rule document in the shape all 36,955 of them are written in, with an
    `## At a glance` a curator could have edited, relationship edges another tool put
    there, and -- the case that matters -- a FULL TEXT containing the same strings the
    provenance lines are found by.

    KEPT INSIDE A FUNCTION so its `status:` line is proof code rather than a write of this
    module's own. `legal_status.py --check` scans `src/` for legal-status literals and
    excludes only `_fixture*`/`_proof_*`/`selftest` bodies; as a module-level constant this
    string made this file a SECOND WRITER of a claim about Oregon law, and the gate said so
    the first time it ran. That is the interlock working, and it is why this module can
    say it writes no legal status of its own and have it mean something."""
    return """---
id: oar-999-001-0010
title: "A Rule"
source_url: "https://example.invalid/999-001-0010"
retrieved: "2026-01-02"
source_sha256: "%s"
status: repealed
relationships:
  implements:
    - ors-1.100
tags: ["oar", "chapter-999", "division-001"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated copy, not the
> official text. Verify against OARD:
> <https://example.invalid/999-001-0010> (retrieved 2026-01-02).

# A Rule (OAR 999-001-0010)

## At a glance

A sentence a curator wrote by hand and nothing here may throw away.

## Full text

999-001-0010 A Rule. The old text. retrieved 2026-01-02 sha256 `%s`
- Source: <https://example.invalid/spoof> · retrieved 2026-01-02 · sha256 `%s`

## Provenance & change history

- Source: <https://example.invalid/999-001-0010> · retrieved 2026-01-02 · sha256 `%s`
- See [CHANGELOG](../../CHANGELOG.md).
""" % (("0" * 64,) * 4)


def _proof_refresh(check) -> None:
    """A RE-INGEST REFRESHES TEXT AND PROVENANCE, AND TOUCHES NOTHING ELSE.

    The criterion "the rule was re-ingested" is trivially satisfiable by REGENERATING the
    document from the ingest template, which passes while deleting the relationship edges,
    the curator's `## At a glance` and the upstream-tracking field that other tools put
    there. So what this function leaves alone is asserted here as hard as what it changes.

    THE LAST CASE IS THE ONE THAT BITES. A rule's own verbatim text can contain the
    literal strings the provenance lines are found by -- `sha256`, `retrieved`, a
    `- Source: <...>` bullet -- and a whole-document substitution rewrites the rule's TEXT
    while looking like it rewrote the provenance. `refresh()` splits the document at its
    section markers first, so the body is never scanned for either."""
    doc = _fixture_doc()
    new = refresh(doc, "999-001-0010 A Rule. The NEW text.", "a" * 64, "2026-08-23")
    check("the new text is what the document now serves",
          "The NEW text." in new)
    check("...and the old text is gone", "The old text." not in new)
    check("the frontmatter carries the new hash", 'source_sha256: "' + "a" * 64 in new)
    check("...and the new retrieval date", 'retrieved: "2026-08-23"' in new)
    check("the disclaimer carries the new retrieval date",
          "(retrieved 2026-08-23)." in new)
    check("the provenance bullet carries both",
          "- Source: <https://example.invalid/999-001-0010> · retrieved 2026-08-23 · "
          "sha256 `" + "a" * 64 + "`" in new)
    check("the curator's own sentence survives",
          "A sentence a curator wrote by hand" in new)
    check("the relationship edges survive", "- ors-1.100" in new)
    check("the legal status is not this function's to touch", "status: repealed" in new)
    check("a provenance-shaped line INSIDE the rule text is left as served",
          "- Source: <https://example.invalid/spoof> · retrieved 2026-01-02 · sha256 "
          "`" + "0" * 64 + "`" not in new)

    # RE-RUNNING PRODUCES BYTE-IDENTICAL OUTPUT, asserted on the function rather than
    # observed once by running a command twice.
    check("refreshing an already-refreshed document changes not one byte",
          refresh(new, "999-001-0010 A Rule. The NEW text.", "a" * 64, "2026-08-23") == new)
    check("...and the same inputs always give the same bytes",
          refresh(doc, "x", "b" * 64, "2026-08-23")
          == refresh(doc, "x", "b" * 64, "2026-08-23"))

    # A DOCUMENT THIS CANNOT PARSE IS REFUSED, NOT QUIETLY RETURNED UNCHANGED. Returning
    # the input is what makes a refresh that did nothing indistinguishable from one that
    # had nothing to do.
    for name, broken in (
            ("no full-text section", doc.replace("## Full text", "## Text")),
            ("no provenance section",
             doc.replace("## Provenance & change history", "## Notes")),
            ("no provenance bullet",
             doc.replace("- Source: <https://example.invalid/999-001-0010> · "
                                  "retrieved 2026-01-02 · sha256 `" + "0" * 64 + "`",
                                  "- Source: unknown")),
            ("no disclaimer date",
             doc.replace("(retrieved 2026-01-02).", "(retrieved unknown).")),
            ("no source_sha256", doc.replace("source_sha256: ", "sha: ")),
            ("no retrieved", doc.replace('retrieved: "2026-01-02"', "retrieved:")),
    ):
        check(f"a document with {name} is refused rather than returned unchanged",
              refresh(broken, "x", "a" * 64, "2026-08-23") is None)



def _marked(number, action="amend", notice=FIXTURE_NOTICE, **kw) -> dict:
    """A catalog row recording a re-ingest WHOLE -- both keys, the way `--run` writes it."""
    return _row(number, **{ACTION_KEY: action, NOTICE_KEY: notice}, **kw)


def _proof_the_record_a_row_keeps(check) -> None:
    """WHAT A RE-INGESTED ROW SAYS, and every way it can say it wrongly.

    `a-re-ingest-cites-its-notice` is counted rather than tested pairwise. Written as
    `bool(action) != bool(notice)` it would pass a row holding neither and a row holding
    both, which is right, and would also have to be re-derived for a third key -- counting
    is the shape that survives the key list growing."""
    both = check_rows(_fixture_catalog(_marked("999-001-0010")))
    check("a fully recorded row is not a finding", not both)
    for missing in REINGEST_KEYS:
        row = _marked("999-001-0010")
        row.pop(missing)
        found = check_rows(_fixture_catalog(row))
        check(f"a row recording a re-ingest with no {missing} is caught",
              any(f.rule == "a-re-ingest-cites-its-notice" for f in found))
    check("a row recording no re-ingest at all is not a finding",
          not check_rows(_fixture_catalog(_row("999-001-0010"))))

    # THE SPLIT, ONE LEVEL DOWN. A row is where a re-ingest is recorded, so a row that
    # records one for a repeal is the resurrection written down -- caught on the word
    # alone, without having to look at any bulletin.
    for action in sorted(FORCE_ACTIONS):
        found = check_rows(_fixture_catalog(_marked("999-001-0010", action=action)))
        check(f"a row recording a re-ingest of a {action} is caught",
              any(f.rule == "a-re-ingested-action-changes-text" for f in found))
    check("...and a verb no bulletin files is caught too",
          any(f.rule == "a-re-ingested-action-changes-text"
              for f in check_rows(_fixture_catalog(_marked("999-001-0010", action="tidy")))))

    # MARKED, NEVER RE-INGESTED. A row carrying a Bulletin-set legal status is a rule
    # somebody has to look at; this path writing to it is the failure the whole ticket is
    # about, and it is caught on the ROW rather than only on the document.
    out_of_force = _marked("999-001-0010", legal_status="repealed",
                           legal_status_action="repeal", legal_status_notice=FIXTURE_NOTICE)
    check("a row that is out of force AND recorded re-ingested is caught",
          any(f.rule == "a-force-marked-rule-is-not-re-ingested"
              for f in check_rows(_fixture_catalog(out_of_force))))
    check("...and the same row without the re-ingest record is not",
          not check_rows(_fixture_catalog(
              _row("999-001-0010", legal_status="repealed",
                   legal_status_action="repeal", legal_status_notice=FIXTURE_NOTICE))))


def _proof_the_notice_and_the_catalog_agree(check) -> None:
    """THE RULE THAT MAKES EVERY OTHER RULE HERE UNSATISFIABLE BY DOING NOTHING.

    Everything in `check_rows` checks a row that EXISTS. Strip the two keys off all 306 and
    every one of those rules passes on a corpus that re-ingested nothing -- so this reads
    the NOTICE and asks what the catalog is missing, in both directions."""
    cat = _fixture_catalog(_row("999-001-0010"), _row("999-001-0020"))
    wl = _fixture_worklist(("999-001-0010", "amend", HELD))
    found = check_recorded(cat, wl)
    check("a filed amendment nothing recorded is caught",
          any(f.rule == "a-filed-text-action-is-re-ingested" for f in found))
    check("...and is not a finding once it is recorded",
          not any(f.rule == "a-filed-text-action-is-re-ingested"
                  for f in check_recorded(_fixture_catalog(_marked("999-001-0010")), wl)))
    check("...nor is it demanded of a rule the bulletin did not name",
          not any(f.site == "999-001-0020" for f in found))

    # THE OTHER DIRECTION, and it fails differently: a row citing this month's bulletin for
    # a filing that bulletin does not contain is a claim whose citation does not support it,
    # which is worse than an uncited one because it looks checked.
    found = check_recorded(_fixture_catalog(_marked("999-001-0010"), _marked("999-001-0020")), wl)
    check("a row citing this bulletin for a rule it filed no text action against is caught",
          any(f.rule == "the-notice-names-the-re-ingest" and f.site == "999-001-0020"
              for f in found))
    check("a row citing an EARLIER bulletin is left alone -- this corpus keeps one month "
          "at a time and could not check is never reported as is not there",
          not check_recorded(
              _fixture_catalog(_marked("999-001-0010"),
                               _marked("999-001-0020", notice="July 2026 (bulltnRsn=1760)")),
              wl))

    # A ROW REACHABLE UNDER TWO NUMBERS IS ONE ROW. 484 catalog rows carry `served_as` --
    # the number OARD actually serves, which is the number the bulletin names and the
    # document is filed under, while the row's own `number` is what this corpus asked for.
    # 42 of this month's 306 amendments are reachable only that way. Asking the reverse
    # scan "is this NAME one we re-ingested" reported every one of them as citing a
    # bulletin that had not named it, and the gate said so on the committed catalog before
    # anything else did.
    served = _fixture_catalog(_marked("999-001-0777", served_as="999-001-0010"))
    check("a rule the catalog reaches only through `served_as` is re-ingested",
          not any(f.rule == "a-filed-text-action-is-re-ingested"
                  for f in check_recorded(served, wl)))
    check("...and its row is not ALSO reported as citing a bulletin that did not name it",
          not check_recorded(served, wl))

    # THE OVERLAP, END TO END. The bulletin amends AND repeals one rule; the re-ingest must
    # be demanded of neither and recorded for neither.
    wl2 = _fixture_worklist(("999-001-0010", "amend", HELD), ("999-001-0010", "repeal", HELD))
    check("a rule the same bulletin amended and repealed is not demanded of the catalog",
          not check_recorded(_fixture_catalog(_row("999-001-0010")), wl2))
    check("...and recording one against it is caught by the notice too",
          any(f.rule in ("the-notice-names-the-re-ingest",
                         "a-force-marked-rule-is-not-re-ingested")
              for f in check_recorded(_fixture_catalog(_marked("999-001-0010")), wl2)))


def _proof_documents(check) -> None:
    """PROVENANCE, AND THE BYTE-IDENTICAL RE-RUN, fired against COMMITTED documents.

    Both rules are about a real file on disk and a real snapshot beside it, so both are
    proved by mutating a COPY OF A COMMITTED DOCUMENT IN MEMORY rather than by inventing
    one -- a provenance rule proved on a fixture is one nobody has watched fire on the
    corpus it governs. Nothing here writes to the working tree."""
    catalog = yaml.safe_load(CATALOG.read_text())
    picked, _, _ = select(load_worklist(), catalog)
    check("there are committed documents to check at all", len(picked) > 0)
    check("...and every one of them verifies against its own snapshot, unmutated",
          not check_documents(picked))

    one = picked[0]
    doc_id = f"oar-{one.number}"
    text = one.path.read_text()
    snapshot = (SNAPSHOT_DIR / f"{doc_id}.txt").read_text()
    sha = hash_snapshot(doc_id, "html")
    check("...including the one the rest of this proof mutates",
          not check_document(one.number, text, snapshot, sha))

    # A document whose full text drifted from the snapshot it cites: provenance no longer
    # covers the text, and the re-ingest is no longer reproducible from its source.
    drifted = text.replace("\n\n## Provenance & change history\n",
                           "\nA line nobody fetched.\n\n## Provenance & change history\n")
    check("a document whose text drifted from its snapshot is caught",
          any(f.rule == "the-re-ingest-reproduces-its-document"
              for f in check_document(one.number, drifted, snapshot, sha)))
    # A document whose markers moved is one the refresh cannot parse, and it must be
    # reported rather than passed for want of anything to compare.
    unparseable = text.replace("## Full text", "## Text")
    check("...and so is one the refresh can no longer parse at all",
          any(f.rule == "the-re-ingest-reproduces-its-document"
              for f in check_document(one.number, unparseable, snapshot, sha)))
    # A document whose recorded hash is not the hash of the snapshot beside it.
    rehashed = re.sub(r'^source_sha256: "[0-9a-f]{64}"$',
                      'source_sha256: "' + "f" * 64 + '"', text, count=1, flags=re.M)
    check("a document whose recorded hash is not its snapshot's is caught",
          any(f.rule == "a-re-ingested-rule-matches-its-snapshot"
              for f in check_document(one.number, rehashed, snapshot, sha)))
    # ...and the snapshot moving under a document that did not is the same finding from
    # the other side, which is what an upstream edit nobody re-ingested looks like.
    check("...as is a snapshot that moved under a document that did not",
          any(f.rule == "a-re-ingested-rule-matches-its-snapshot"
              for f in check_document(one.number, text, snapshot, "e" * 64)))
    check("nothing in this proof wrote to the working tree",
          one.path.read_text() == text)



def _page(number, body="(1) Some rule text that is comfortably longer than the hundred "
                       "characters the slicer insists on before it will believe a page "
                       "carries a rule at all.") -> bytes:
    """An OARD rule page, in the shape `snapshot_slice` and `served_rule_number` read."""
    return (f"<html><body><h1>{number}</h1><div>{number} A Rule</div>"
            f"<div>{body}</div></body></html>").encode()


def _proof_the_run_refuses_what_is_not_an_amendment(check) -> None:
    """WHAT COMES BACK FROM OARD IS NOT ALWAYS THE FILING THE BULLETIN NAMED.

    The bulletin said this rule's TEXT changed. Every case here is a page that says
    something else happened -- the rule is gone, it moved, the site is down, the body is
    empty -- and each is a claim about FORCE or about identity that this path may not apply
    unattended. They are refusals rather than exceptions because one rule's outage must not
    stop the other 305 with the catalog half-written.

    NOTHING HERE WRITES: every case returns before the first write, and the last check
    reads the document back to say so."""
    catalog = yaml.safe_load(CATALOG.read_text())
    picked, _, _ = select(load_worklist(), catalog)
    one = picked[0]
    before = one.path.read_text()
    registry = load_registry_by_chapter()

    def run(page):
        return reingest_one(one, registry, "2026-08-23", fetch_page=page)

    def boom(_):
        raise OSError("connection reset")

    for name, page in (
            ("OARD cannot be reached", boom),
            ("the page names no rule number", lambda _: _page("").replace(b"<h1></h1>", b"")),
            ("the page says the rule was not found",
             lambda _: _page(one.number, f"{one.number} not found. " + "x" * 200)),
            ("the page serves a DIFFERENT rule number",
             lambda _: _page("999-999-9999")),
            ("the page carries no sliceable rule body",
             lambda _: _page(one.number, "short")),
            ("the page is a search-results list rather than a rule (#251)",
             lambda _: _page(one.number,
                             f"{one.number} returned 2 results. New Search | Modify "
                             f"Search Rows per page: 25 50 75 100 " + "x" * 200)),
    ):
        wrote, problems = run(page)
        check(f"a re-ingest is refused when {name}",
              problems and not wrote
              and all(f.rule in ("a-filed-text-action-is-re-ingested",
                                 "the-re-ingest-reproduces-its-document")
                      for f in problems))
    check("...and not one of those refusals wrote to the document",
          one.path.read_text() == before)

    # #245 -- A REFUSAL THE ROW CARRIES, watched being recorded and watched clearing the
    # gate that could not otherwise be cleared. Run against a COPY of the row so nothing
    # here reaches the committed catalog (#252).
    row = dict(one.row)
    probe = Candidate(one.number, one.action, row, one.path)
    notice = "August 2026 (bulltnRsn=1761)"
    wrote, problems = reingest_one(
        probe, registry, "2026-08-23", notice=notice,
        fetch_page=lambda _: _page("999-999-9999"))
    check("a permanent refusal is recorded on the row, in the ingest vocabulary",
          not wrote and row.get(REFUSED_KEY) == "renumbered"
          and row.get(REFUSED_NOTICE_KEY) == notice)
    check("...and it is NOT spellable as a re-ingest",
          row.get(ACTION_KEY) == one.row.get(ACTION_KEY)
          and row.get(NOTICE_KEY) == one.row.get(NOTICE_KEY))
    check("...and nothing was written to the committed row or the document",
          one.row.get(REFUSED_KEY) is None and one.path.read_text() == before)

    # THE GATE IT CLEARS, on this module's own fixtures rather than a hand-rolled catalog.
    # A row with neither the re-ingest keys nor a refusal is red; the same row carrying the
    # refusal is not; a refusal citing ANOTHER bulletin is red again, because a rule refused
    # in July says nothing about what August filed.
    wl = _fixture_worklist(("999-001-0010", "amend", HELD))

    def _found(row, rule="a-filed-text-action-is-re-ingested"):
        return any(f.rule == rule
                   for f in check_recorded(_fixture_catalog(row), wl))

    check("a filed action with neither a re-ingest nor a refusal is red",
          _found(_row("999-001-0010")))
    check("...and the same row carrying the refusal against THIS bulletin is not",
          not _found(_row("999-001-0010", **{REFUSED_KEY: "renumbered",
                                             REFUSED_NOTICE_KEY: FIXTURE_NOTICE})))
    check("...and a refusal citing a DIFFERENT bulletin is red again",
          _found(_row("999-001-0010", **{REFUSED_KEY: "renumbered",
                                         REFUSED_NOTICE_KEY: "July 2026 (bulltnRsn=1741)"})))
    check("...and a refusal reason outside the ingest vocabulary is reported",
          _found(_row("999-001-0010", **{REFUSED_KEY: "gave_up",
                                         REFUSED_NOTICE_KEY: FIXTURE_NOTICE}),
                 rule="a-refusal-is-recorded-in-the-ingest-vocabulary"))


def _proof_a_source_that_has_not_moved_is_left_alone_on_a_later_day(check) -> None:
    """THE FIXED POINT `reingest_one` IS BUILT AROUND, watched actually holding (#269).

    `refresh(old, full_text, sha, _retrieved(old)) == old` is the guard that stops a
    re-ingest from rewriting `retrieved` over a document whose source did not move -- the
    guard #252 found writing to a COMMITTED rule anyway, because the proof that exercised
    it fed a real candidate's committed path straight to `reingest_one` and asserted
    `not wrote` only AFTER the write it was testing for could already have happened. That
    proof was removed in #261 as collateral (`grep -c "2099"` now returns 0) and nothing
    replaced it: `the-re-ingest-reproduces-its-document` covers `refresh()` over all 306
    re-ingested documents, but it never calls `reingest_one`, so it says nothing about
    date handling on the WRITE PATH -- and the two calls to `reingest_one` still in this
    selftest (`_proof_the_run_refuses_what_is_not_an_amendment`) both feed REFUSAL pages,
    never a valid page fed back on a later date.

    BUILT ENTIRELY FROM SYNTHETIC FIXTURES so this can never touch a committed file even
    under the mutation it exists to catch (the lesson of #252, this time by construction
    rather than by care): the source page is `_page()`, the document it is fed back into
    is `_fixture_doc()` refreshed once so it already holds what that page computes, and
    the candidate's path is a file in a TEMPORARY directory that stops existing when this
    function returns -- `candidate.path.write_text()` can reach only that. `999-001-0010`
    is the number every OTHER fixture in this file already uses for exactly this reason:
    no committed snapshot carries it, so even the unconditional `SNAPSHOT_DIR` writes on
    the write path -- reached under the mutation below -- land on nothing real.

    THE INGEST ACTUALLY RUNS, rather than the proof passing because nothing was asked to
    run at all. `fetch_page` is a counting stub: this is `reingest_one` itself fetching,
    slicing, hashing and comparing and finding no change, not `select()` declining to
    re-select an already-recorded row. And THE CLOCK ACTUALLY MOVES -- `today` is
    2026-08-23 and the fixture's own `retrieved` is 2026-01-02, seven and a half months
    earlier, not a rerun inside the same second -- which is the specific shape of #252's
    failure: a re-run on a LATER DAY stamping today over bytes nobody re-fetched a change
    in.

    WATCHED FAILING. With the fixed-point guard at the top of `reingest_one` disabled, this
    exact fixture writes `retrieved: "2026-08-23"` over the document -- confirmed by hand
    against this fixture and reverted before commit. There is no `CHECK_RULES` entry for
    it: `reingest_one` raises no `Failure` of its own when the fixed point holds, so this
    proof is the only place in the module a regression here has anywhere to fail."""
    number = "999-001-0010"
    doc_id = f"oar-{number}"
    raw = _page(number, "(1) Text a re-fetch of an unmoved source would serve again, "
                        "comfortably past the hundred characters the slicer insists on "
                        "before it will believe a page carries a rule at all.")
    text = snapshot_text(raw)
    body = snapshot_slice(doc_id, doc_id, text)
    full_text = flow_to_lines(body)
    sha = content_hash(raw, "html")
    # THE DOCUMENT ALREADY HOLDS WHAT A RE-FETCH OF THE SAME PAGE WOULD COMPUTE -- built by
    # calling `refresh()` itself rather than hand-assembling frontmatter, so this fixture
    # cannot drift from what the function under test actually writes.
    old = refresh(_fixture_doc(), full_text, sha, "2026-01-02")
    check("the fixture document is buildable and dated before the re-ingest",
          old is not None and _retrieved(old) == "2026-01-02")
    # A REGISTRY THAT RESOLVES `999`, so that a REGRESSION reaching the write branch fails
    # THIS proof's own assertions rather than crashing on an unrelated missing chapter --
    # the fixed point is never exercised on the path this proof expects to take, but a
    # broken guard must still land somewhere this can see, not in a SystemExit from
    # `enrich_oar.derive()` three lines further in.
    fake_registry = {"999": {"slug": "test-agency", "oar_name": "Test Agency"}}

    calls = []

    def fetch_page(url):
        calls.append(url)
        return raw

    with tempfile.TemporaryDirectory() as d:
        # A FILE IN A TEMP DIRECTORY, NEVER A COMMITTED ONE (#252). Whatever this function
        # writes is invisible to the working tree whether or not the assertions below are
        # right.
        path = Path(d) / f"{doc_id}.md"
        path.write_text(old)
        candidate = Candidate(number, "amend", {}, path)
        wrote, problems = reingest_one(
            candidate, fake_registry, "2026-08-23", fetch_page=fetch_page)
        check("the fetch actually ran -- this is not a re-ingest skipped as "
              "already-present", len(calls) == 1)
        check("a source that has not moved, re-ingested on a LATER day, writes nothing "
              "and reports no problem", not wrote and not problems)
        check("...and the document on disk is byte-for-byte what it was before the run",
              path.read_text() == old)
        check("...specifically: the retrieved date the re-ingest almost overwrote",
              _retrieved(path.read_text()) == "2026-01-02")


def _proof_the_status_survives_the_call_this_path_makes(check) -> None:
    """LAYER TWO, AT THE EXACT CALL SITE. `select()` refuses every rule the Bulletin took
    out of force, so nothing here should ever hand one to the enricher -- and this proves
    that if something did, the status would still come back untouched.

    Fired through `enrich_oar.derive()` rather than through `legal_status.resolve()`
    directly, because the composition is what this module actually calls and a proof of the
    inner function alone would not notice this path passing the argument in the wrong
    place. The body says nothing about a repeal; the document says `current`; the Bulletin
    says `repealed`; the answer must be `repealed`."""
    registry = load_registry_by_chapter()
    chapter = next(iter(registry))
    body = "## Full text\n\n(1) Text that mentions no history at all.\n"
    for bulletin in ("repealed", "superseded"):
        d = enrich_derive(body, f"oar-{chapter}-001-0010", registry, bulletin, "current")
        check(f"a bulletin-set {bulletin!r} survives the enrich call this path makes",
              d["status"] == bulletin)
    d = enrich_derive(body, f"oar-{chapter}-001-0010", registry, None, "repealed")
    check("...and a rule the Bulletin has said nothing about keeps what its document says",
          d["status"] == "repealed")
    # THE RESURRECTION ITSELF, WATCHED HAPPENING. Every other proof here watches the
    # arrangement HOLD, and a guarantee only ever seen holding is one nobody can tell from
    # a guarantee that stopped being enforced. This is the mutation: drop the Bulletin
    # argument on the way in -- which is exactly what a re-ingest that forgot to pass it
    # does, and what `ingest_oar.py`'s hardcoded literal did to every rule it wrote -- and
    # a rule the Bulletin repealed comes back `current`, under provenance, silently.
    resurrected = enrich_derive(body, f"oar-{chapter}-001-0010", registry, None, "current")
    check("dropping the bulletin argument RESURRECTS a repealed rule -- the failure this "
          "path exists not to have, watched happening",
          resurrected["status"] == "current"
          and enrich_derive(body, f"oar-{chapter}-001-0010", registry,
                            "repealed", "current")["status"] == "repealed")


def selftest() -> int:
    check = Checks()
    _proof_the_split_is_exact(check)
    _proof_selection(check)
    _proof_the_committed_selection(check)
    _proof_refresh(check)
    _proof_the_record_a_row_keeps(check)
    _proof_the_notice_and_the_catalog_agree(check)
    _proof_documents(check)
    _proof_the_run_refuses_what_is_not_an_amendment(check)
    _proof_a_source_that_has_not_moved_is_left_alone_on_a_later_day(check)
    _proof_the_status_survives_the_call_this_path_makes(check)
    check("every rule this module can report is declared",
          legal_status.emitted_rules(Path(__file__).read_text()) == set(CHECK_RULES))
    check("...and every declared rule was watched firing, not merely listed",
          set(CHECK_RULES) <= _FIRED)
    return check.report(
        f"{len(CHECK_RULES)} rule(s) declared, every one both emitted by this module and "
        "watched firing here -- selftest")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.check:
        return cmd_check()
    if a.run:
        return cmd_run()
    return cmd_report()


if __name__ == "__main__":
    raise SystemExit(main())
