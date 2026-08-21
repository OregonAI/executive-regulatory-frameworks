#!/usr/bin/env python3
"""Decide each relation's KIND from what the registry knows about the body under it.

  python3 src/derive_relation_kinds.py --apply     # write kind/basis/authority onto relations
  python3 src/derive_relation_kinds.py --check     # CI: the registry matches the derivation
  python3 src/derive_relation_kinds.py --selftest  # CI: every rule --check enforces fires

WHAT DECIDES A KIND. ADR 0004 splits `parent_slug` into *part of* — nothing separately
constitutes the unit — and *administered by* — the unit is separately constituted and
attached to a department. Which one applies turns on whether the body carries its own
ADMITTING evidence (ADR 0003), and the sharpest available evidence of that is an enabling
authority: a statute that constitutes the Oregon Albacore Commission is a statute the
Highway Division does not have and never will.

THIS DERIVES KINDS FROM PROPOSALS, WHICH IS A DEVIATION FROM ADR 0004 AS WRITTEN, and ADR
0004 now records it. The registry holds no admitting evidence yet — all 189
`enabling_authority` keys are absent. What it holds is 126 CANDIDATES in
_meta/catalog/enabling-authority-review.yml, and link_enabling_authority.py is explicit that
"a row that was pattern-matched and not read belongs in the review sheet, not here". A
candidate is a proposal, not evidence. Deriving from one anyway is a decision taken to ship
the split now rather than wait on the review of 126 rows, and it is only defensible because
the file SAYS SO: every kind records the `basis` it was derived from, so a claim resting on
an unread proposal cannot be mistaken for one resting on a reviewed authority, and the row
upgrades visibly the day the review lands. Without that the registry would assert a
relationship on evidence it does not hold — which is exactly what `manual: true` was retired
for (ADR 0003: an assertion records that someone decided, never what decided it).

ONLY THE POSITIVE HALF IS DERIVED, AND THAT IS THE WHOLE OF CONTEXT.md'S OVERRIDING RULE.
A candidate is evidence that a body is separately constituted, so 44 of the 81 children
become `administered_by`. The other 37 stay `undetermined`. NOTHING here reads the ABSENCE
of a candidate as evidence of `part_of`: the matcher finding nothing is a statement about
the matcher, and this repository has watched that statement be wrong 55 times in one
session — the no-candidate list went 118 -> 95 -> 82 -> 63 as `_variants`, the enumerated-list
tier and the catchline tiers closed gaps in link_enabling_authority.py, each time turning
bodies "statute forgot to create" into bodies statute plainly created. "Could not check" is
never reported as "is not there", and 37 undetermined rows are the correct answer rather
than a gap.

A REVIEWED ABSENCE IS NOT A CANDIDATE FOR ANYTHING HERE EITHER. `none: <reason>` on a row
means a human looked and found no separate authority, which is ADR 0004's own description of
a *part of* unit — but turning that into a `part_of` kind is a second derivation, on the
other side of the line this ticket drew, and it is left to whoever takes it deliberately.
What the reviewed absence DOES do is retire the proposal: a candidate a human has ruled on
is not a proposal any more, so the row derives nothing rather than deriving
`administered_by` from a citation the reviewer rejected.

WHICH SECTION THE RELATION CITES. ADR 0004's worked example holds two, and they are
different facts: ORS 576.062 establishes the commodity commissions as state commissions, and
ORS 576.066 is the separate section the Department of Agriculture's administration of them
runs on. What this derives cites the FIRST — it is the evidence the kind rests on, and the
second is a section nobody in this repository has read, so writing it would be citing Oregon
law on nobody's authority. Both bases are named for an ENABLING authority for exactly that
reason. Recording the administering section stays available and stays curated: it needs a
basis this module does not produce, and `decision-not-ours` refuses to overwrite one.

AND THIS FILE IS THE SINGLE WRITER OF A RELATION'S DECISION — its `kind`, its `basis` and
its `authority` — the same arrangement `enabling_authority` has with
link_enabling_authority.py and `das_agency_number` with link_budget_codes.py, for the reason
#175 exists: two writers of one field is drift nothing reports. `--check` compares the
registry against the derivation in BOTH directions, so a kind that arrived some other way is
a failure rather than a fact.

WHERE A DERIVED KIND LIVES, since it cannot simply be set. The relation whose kind is being
decided is the one the OAR INDEX states, and --refresh rewrites that entry from the index
tree on every run. It survives because `catalog_agencies.preserve_relations()` merges
`relations` per KEY as well as per entry: the scrape owns the PLACEMENT (`target`,
`source`), this module owns the DECISION (`catalog_agencies.DECISION_KEYS`), and the
decision is carried onto the rebuilt entry that names the same parent. The alternative —
writing the kind onto a second relation entry — was rejected because a second entry is a
second PLACEMENT: no statute, DAS register or hand-written note places the Appraiser
Certification and Licensure Board under DCBS; the rules index does, and recording otherwise
would attribute a placement to a source that never made it in order to carry a fact about
its kind.
"""
from __future__ import annotations

import argparse
import collections
import sys

import yaml

from catalog_agencies import (ADMINISTERED_BY, DECISION_KEYS, PROPOSED_AUTHORITY,
                              RELATION_KEY, REVIEWED_AUTHORITY, UNDETERMINED,
                              classify_authority, relation_census, relation_entries)
from repo_lib import REPO_ROOT

CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"
REVIEW_SHEET = REPO_ROOT / "_meta/catalog/enabling-authority-review.yml"

# THE BASES THIS MODULE PRODUCES, which is not the same list as the bases the registry
# ACCEPTS. They hold the same two values today, and naming them separately is for the day
# they stop: `catalog_agencies.RELATION_BASES` is widened by whoever adds a kind decided some
# other way — ADR 0004's own example is a statute that establishes the ADMINISTRATION
# (ORS 576.066), which nothing here reads and no derivation can produce — and on that day
# `--apply` must leave such an entry alone rather than overwrite a curated decision with a
# proposal. A curated fact silently downgraded to a proposal is the exact failure the `basis`
# exists to prevent, done by the thing that introduced it.
DERIVED_BASES = (PROPOSED_AUTHORITY, REVIEWED_AUTHORITY)

# One thing wrong with the derivation or with the registry it writes: which rule, which body,
# and what is wrong. A type rather than a formatted string, so --selftest asserts on the RULE
# that fired instead of pattern-matching prose — the way a proof starts passing for the wrong
# reason (catalog_agencies.Failure, link_enabling_authority.Problem, same lesson).
Problem = collections.namedtuple("Problem", "rule slug detail")

# What one row's kind was decided to be, and on what. `authority` is the citation the
# relation carries; `basis` is which of the two strengths it came from.
Decision = collections.namedtuple("Decision", "kind basis authority")


# The review sheet split the one way this module cares about: the rows that are still
# proposals, and the rows a human has already ruled on. A pair rather than two functions
# reading the sheet separately — they are one traversal answering one question, and two of
# them can disagree about which side a row falls on.
Sheet = collections.namedtuple("Sheet", "proposed verdicts")


def read_sheet(sheet) -> Sheet:
    """The committed review sheet, split into the candidates that are still PROPOSALS and
    the candidates a human has already ruled on.

    The sheet is what link_enabling_authority.py --propose writes, and it says of itself:
    "PROPOSED, NOT DECIDED. Each row is a candidate an automated match produced; none has
    been read."

    A ROW CARRYING A VERDICT IS NOT A PROPOSAL, so it lands on the other side rather than
    among the proposals. Someone has read it: a kind derived from it would be recorded as
    resting on an unread candidate, which is a basis that is simply false, and if the verdict
    was a rejection the kind would rest on a citation a human threw out. `verdict-not-applied`
    reports the ones that matter, because such a row belongs in link_enabling_authority.py's
    MAPPED or UNMAPPED and this module cannot put it there.

    THE SHEET IS PASSED IN, NEVER DEFAULTED TO THE COMMITTED FILE. Every proof below runs on
    a synthetic sheet, and a default that read the real one is a proof that starts reading
    committed data the day someone forgets an argument."""
    proposed, verdicts = {}, {}
    for row in (sheet.get("candidates") or []):
        if not isinstance(row, dict) or not row.get("slug"):
            continue
        verdict = str(row.get("verdict") or "").strip()
        if verdict:
            verdicts[row["slug"]] = verdict
        else:
            proposed[row["slug"]] = str(row.get("candidate") or "").strip()
    return Sheet(proposed, verdicts)


def recordable(citation) -> bool:
    """Whether a proposed citation is one the registry can put in a relation's `authority`.

    THE ONE PLACE THE QUESTION IS ASKED, because two callers act on the answer differently
    and must not disagree about it: `decide()` derives no kind from an unrecordable citation,
    and `audit()` REPORTS the same row — and a body silently left undetermined by a form
    problem looks exactly like one the matcher found nothing for."""
    return bool(citation) and classify_authority(citation)[0] is not None


def decide(org, proposed) -> Decision | None:
    """The kind this body's relations carry, and what decided it — or None for a body whose
    kind nothing here establishes.

    THE ONE PLACE THE RULE IS STATED, so `--apply` writes and `--check` compares the same
    answer rather than two spellings of it.

    It is a fact about the BODY, not about any one parent: what is being decided is whether
    Oregon law constitutes this unit separately from the one it sits under, and the answer is
    the same for every parent a source places it under. So the decision goes onto every
    relation the row holds.

    THE REVIEWED AUTHORITY WINS WHEREVER THERE IS ONE, which is what makes the upgrade
    visible: the day link_enabling_authority.py writes a reviewed citation onto the row, the
    basis moves from `proposed-enabling-authority` to `reviewed-enabling-authority` and the
    authority moves to the citation a human actually read.
    """
    if not relation_entries(org):
        return None                       # a body under nothing has no kind to decide
    if "enabling_authority" in org:
        form, _detail = classify_authority(org["enabling_authority"])
        if form is None:
            # An unreadable value is `enabling-authority-form`'s failure in
            # catalog_agencies.py --check, and deriving from it would build a kind on a value
            # that gate is about to refuse. Nothing is decided from it here.
            return None
        if form == "reviewed-none":
            # A HUMAN LOOKED AND FOUND NOTHING SEPARATE. That is ADR 0004's *part of*, and
            # deriving it is a decision this ticket did not take (see the module docstring).
            # What it does settle is that the proposal below has been ruled on, so it may not
            # be used.
            return None
        return Decision(ADMINISTERED_BY, REVIEWED_AUTHORITY, org["enabling_authority"])
    citation = proposed.get(org.get("slug"))
    if not citation:
        # NOT `part_of`. The absence of a candidate is a statement about the matcher, and
        # this repository has watched that statement be wrong 55 times in one session.
        return None
    if not recordable(citation):
        # REPORTED BY `candidate-form`, NEVER SILENTLY DROPPED. A candidate the registry
        # cannot record is a body whose kind goes undecided for a reason nobody would see,
        # which is the substitution CONTEXT.md forbids.
        return None
    return Decision(ADMINISTERED_BY, PROPOSED_AUTHORITY, citation)


def ours(entry) -> bool:
    """Whether this module is the writer of that relation's decision.

    An entry recording no basis has no decision yet and is this module's to write; an entry
    recording one of DERIVED_BASES was written here; anything else is a decision reached some
    other way, and --apply leaves it exactly as it is while `decision-not-ours` reports it. A
    curated decision overwritten with a proposal would be a stronger claim replaced by a
    weaker one, by the machinery introduced to keep those apart."""
    return entry.get("basis") in (None, *DERIVED_BASES)


def derived(orgs, proposed) -> dict:
    """slug -> Decision, for every body whose kind this module establishes."""
    out = {}
    for org in orgs:
        if not isinstance(org, dict) or not org.get("slug"):
            continue
        decision = decide(org, proposed)
        if decision is not None:
            out[org["slug"]] = decision
    return out


def apply_decisions(cat, proposed) -> int:
    """Write the derivation onto every relation of every row. Returns the rows changed.

    RE-RUNNABLE AND BYTE-IDENTICAL. The keys are assigned rather than re-inserted, so a
    relation that already carries the decision keeps its key order and its values, and the
    second run changes nothing and dumps the same bytes
    (`_proof_apply_writes_the_same_bytes_twice`).

    A ROW THE DERIVATION NO LONGER DECIDES IS RETURNED TO `undetermined` rather than left
    holding a stale kind. This module is the decision's single writer, so what it does not
    derive today is a decision nothing stands behind — and `undetermined` is a value that
    says so, where a stale `administered_by` says the opposite with nobody behind it. That is
    the one way this differs from link_enabling_authority.py --apply, which leaves an
    unaccounted row alone: there the field's absence is a THIRD state a human may have
    reached by hand, and here the third state is `undetermined` and this file writes it.
    """
    decisions = derived(cat.get("organizations") or [], proposed)
    changed = 0
    for org in cat.get("organizations") or []:
        if not isinstance(org, dict):
            continue
        decision = decisions.get(org.get("slug"))
        touched = False
        for entry in relation_entries(org):
            if not isinstance(entry, dict) or not ours(entry):
                continue
            if decision is None:
                was = (entry.get("kind"), "basis" in entry, "authority" in entry)
                entry["kind"] = UNDETERMINED
                for key in DECISION_KEYS:
                    if key != "kind":
                        entry.pop(key, None)
                touched = touched or was != (UNDETERMINED, False, False)
                continue
            want = dict(zip(DECISION_KEYS, decision))
            if {k: entry.get(k) for k in DECISION_KEYS} != want:
                entry.update(want)
                touched = True
        changed += bool(touched)
    return changed


def audit(orgs, proposed, verdicts) -> list:
    """Every way the registry and this derivation disagree, in BOTH directions, plus the
    candidates the derivation had to refuse.

    THE SECOND DIRECTION IS THE ONE THAT MATTERS. This file is the single writer of a
    relation's decision, so an entry carrying a kind the derivation does not produce was
    written by something else — a hand edit, or a derivation someone ran and did not commit
    — and two writers of one field is the drift #175 exists to prevent. It is also what lets
    this gate fail while the registry is entirely `undetermined`.
    """
    problems = []
    decisions = derived(orgs, proposed)
    by_slug = {o["slug"]: o for o in orgs if isinstance(o, dict) and o.get("slug")}

    # ONLY THE BODIES THIS MODULE DERIVES FOR. A sheet row for a body that sits under no
    # other is link_enabling_authority.py's to answer for — 45 of the 126 candidates name
    # such a body — and reporting them here would fail this gate over work that is not its
    # own, which is the shape of a gate nobody can act on.
    decides_for = {slug for slug, o in by_slug.items() if relation_entries(o)}
    for slug, citation in sorted(proposed.items()):
        if slug not in decides_for:
            continue
        if not citation:
            problems.append(Problem("candidate-form", slug,
                                    "the review sheet proposes an empty citation for this "
                                    "body, which is a candidate nothing can be derived from "
                                    "and is not the same as having none"))
        elif not recordable(citation):
            problems.append(Problem(
                "candidate-form", slug,
                f"the proposed candidate {citation!r} is not an authority this registry can "
                "record, so no kind was derived for this body — REPORTED rather than "
                "dropped, because a body left `undetermined` by a form problem looks exactly "
                "like one the matcher found nothing for. Either the citation is wrong or "
                "catalog_agencies.AUTHORITY_FORMS has to be widened deliberately, and both "
                "are a human's decision"))

    for slug, verdict in sorted(verdicts.items()):
        if slug in decides_for:
            problems.append(Problem(
                "verdict-not-applied", slug,
                f"the review sheet carries verdict {verdict!r} on this candidate, so it has "
                "been READ and is no longer a proposal — move it into MAPPED or UNMAPPED in "
                "src/link_enabling_authority.py and run that --apply. Until then no kind is "
                "derived for this body: one derived here would be recorded as resting on an "
                "unread candidate, which is a basis that is simply false"))

    for slug, org in sorted(by_slug.items()):
        want = decisions.get(slug)
        for entry in relation_entries(org):
            if not isinstance(entry, dict):
                continue                  # `relation-shape` in catalog_agencies owns this
            if not ours(entry):
                problems.append(Problem(
                    "decision-not-ours", slug,
                    f"the relation under {entry.get('target')!r} records basis "
                    f"{entry.get('basis')!r}, which this module does not produce — its kind "
                    "was decided some other way, so --apply leaves it alone rather than "
                    "overwriting a curated decision with a proposal. Whatever writes that "
                    "basis is the thing that has to keep it current"))
                continue
            got = Decision(entry.get("kind"), entry.get("basis"), entry.get("authority"))
            if want is None:
                if got.kind not in (None, UNDETERMINED):
                    problems.append(Problem(
                        "kind-agrees", slug,
                        f"the relation under {entry.get('target')!r} records kind "
                        f"{got.kind!r} on basis {got.basis!r} and this derivation decides "
                        "nothing for this body. Either the evidence it was derived from is "
                        "gone, or the kind was written by something else — this module is "
                        "the decision's single writer"))
            elif got != want:
                problems.append(Problem(
                    "kind-agrees", slug,
                    f"the relation under {entry.get('target')!r} records "
                    f"{tuple(got)!r}, this derivation says {tuple(want)!r} — run --apply"))
    return problems


def _report(problems) -> None:
    for p in problems:
        print(f"  FAIL [{p.rule}] {p.slug}: {p.detail}", file=sys.stderr)


def cmd_apply() -> int:
    cat = yaml.safe_load(CATALOG.read_text())
    proposed, verdicts = read_sheet(yaml.safe_load(REVIEW_SHEET.read_text()))
    changed = apply_decisions(cat, proposed)
    if changed:
        CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True,
                                          width=100))
    orgs = cat["organizations"]
    print(f"relation kinds: {changed} row(s) written")
    print(f"  {relation_census([o for o in orgs if isinstance(o, dict)])}")
    left = [p for p in audit(orgs, proposed, verdicts) if p.rule != "kind-agrees"]
    _report(left)
    return 1 if left else 0


def check() -> int:
    """Verify the registry against the derivation, from committed data alone."""
    orgs = yaml.safe_load(CATALOG.read_text())["organizations"]
    proposed, verdicts = read_sheet(yaml.safe_load(REVIEW_SHEET.read_text()))
    problems = audit(orgs, proposed, verdicts)
    if problems:
        print("the registry's relation kinds do not match this derivation:", file=sys.stderr)
        _report(problems)
        return 1
    decisions = derived(orgs, proposed)
    bases = collections.Counter(d.basis for d in decisions.values())
    # THE TWO POPULATIONS, NAMED APART AND BOTH COUNTED, on every run. The number that would
    # be easiest to print is "44 bodies administered by their parent", and it is the one this
    # module may not print alone: 44 of those rest on candidates nobody has read, and the
    # count of bodies left `undetermined` is not a backlog to be quiet about — it is the
    # answer for every body no evidence speaks to.
    children = [o for o in orgs if isinstance(o, dict) and relation_entries(o)]
    print(f"{len(decisions)} of {len(children)} bodies under another have a kind derived; "
          f"{len(children) - len(decisions)} stay {UNDETERMINED} — no kind is derived from "
          "the ABSENCE of evidence")
    print(f"  derived from a PROPOSED candidate nobody has read : "
          f"{bases[PROPOSED_AUTHORITY]}")
    print(f"  derived from a REVIEWED enabling authority        : "
          f"{bases[REVIEWED_AUTHORITY]}")
    return 0


# ------------------------------------------------------------------------------ selftest
#
# THE PROOF THAT THE GATE ABOVE CAN FAIL, on a synthetic registry and a synthetic review
# sheet: no network, no read of the committed registry, no read of the mirror. A check nobody
# has watched fail is not known to work — it is only known to be quiet.
#
# EVERY BODY AND EVERY CITATION HERE IS MADE UP, and has to be, for the reason
# link_enabling_authority's fixture gives: a row here pairs a body with what constitutes it,
# which is a claim about Oregon law, and a fixture is not review. ORS has no chapter 999.


def _row(slug, parent=None, **extra):
    org = {"slug": slug, "parent_slug": parent, RELATION_KEY: []}
    if parent:
        org[RELATION_KEY] = [{"target": parent, "source": "oar-index",
                              "kind": UNDETERMINED}]
    org.update(extra)
    return org


def _registry():
    """One parent and four children, one for each state the derivation distinguishes, with
    NOTHING derived onto them yet — every relation `undetermined`, which is where the
    committed registry stood before this module ran.

    SEPARATE FROM `_fixture()` BELOW, which is this with the derivation applied. The split is
    not tidiness: `_proof_apply_writes_the_same_bytes_twice` has to dump the file BEFORE the
    first write and after the second, and a fixture that had already been written to would
    compare two dumps of the same post-write state — a byte comparison that passes by
    construction and can never disagree with the writer."""
    parent = "board-of-imaginary-affairs"
    orgs = [
        _row(parent),
        # NO CANDIDATE AND NO REVIEW: stays undetermined. This is the 37.
        _row("imaginary-affairs-inspection-division", parent),
        # A PROPOSED CANDIDATE NOBODY HAS READ: administered_by, on the weaker basis. The 44.
        _row("board-of-imagined-standards", parent),
        # A REVIEWED AUTHORITY, WITH A PROPOSAL STILL IN THE SHEET: the reviewed one wins,
        # and the basis says so. This is the upgrade, and the row it happens on.
        _row("office-of-imagined-orders", parent, enabling_authority="ORS 999.997"),
        # A REVIEWED ABSENCE: a human ruled on the proposal, so it is not used, and the
        # `part_of` this would support is a derivation this ticket did not take.
        _row("imaginary-affairs-records-unit", parent,
             enabling_authority="none: Part of the Board of Imaginary Affairs; nothing "
                                "separately constitutes it (ADR 0004)."),
    ]
    sheet = {"candidates": [
        {"slug": "board-of-imagined-standards", "candidate": "ORS 999.999", "verdict": ""},
        {"slug": "office-of-imagined-orders", "candidate": "ORS 999.998", "verdict": ""},
        {"slug": "imaginary-affairs-records-unit", "candidate": "ORS 999.996", "verdict": ""},
    ]}
    return {"cat": {"organizations": orgs}, "sheet": sheet}


def _fixture():
    """The registry above with this module's derivation already written onto it — the state
    the committed registry is in after --apply, and the one every rule below is checked
    against."""
    f = _registry()
    apply_decisions(f["cat"], read_sheet(f["sheet"]).proposed)
    return f


def _audit(f) -> list:
    return audit(f["cat"]["organizations"], *read_sheet(f["sheet"]))


def _org(f, slug):
    return next(o for o in f["cat"]["organizations"] if o["slug"] == slug)


def _case_kind_written_by_something_else(f):
    """A kind on a body this derivation decides nothing for. Nothing about the row looks
    wrong — it carries a kind, a basis and a citation — and no evidence in this repository
    stands behind it. That is the drift a single writer exists to prevent."""
    _org(f, "imaginary-affairs-inspection-division")[RELATION_KEY][0].update(
        kind=ADMINISTERED_BY, basis=PROPOSED_AUTHORITY, authority="ORS 999.995")


def _case_registry_still_holds_the_proposed_basis_after_review(f):
    """A row reviewed since the last --apply. The registry says the kind rests on a candidate
    nobody has read; the reviewed authority on the same row says a human has. This is
    criterion 4's failure state — the upgrade that has not been run — and it must be a red
    build rather than a stale basis nobody notices."""
    _org(f, "board-of-imagined-standards")["enabling_authority"] = "ORS 999.994"


def _case_candidate_that_is_not_a_recordable_authority(f):
    """A proposed candidate the registry cannot record — an ORS RANGE is the real case, and
    ADR 0004's eight semi-independent boards are declared under exactly one (`ORS 182.456 to
    182.472`). AUTHORITY_FORMS refuses it deliberately, so no kind is derived; the row must
    be REPORTED, because a body left undetermined by a form problem looks exactly like one
    the matcher found nothing for, and telling those apart is the whole discipline here."""
    f["sheet"]["candidates"][0]["candidate"] = "ORS 182.456 to 182.472"


def _case_candidate_with_no_citation_at_all(f):
    """A candidate row proposing nothing. It is a row in the sheet, so the body reads as one
    the matcher spoke about, and there is nothing in it to derive from."""
    f["sheet"]["candidates"][0]["candidate"] = ""


def _case_verdict_that_never_reached_the_reviewed_table(f):
    """A candidate a human has ruled on, still sitting in the sheet. It is no longer a
    proposal, so a kind derived from it would record a basis that is false — and if the
    verdict was a rejection, a citation the reviewer threw out. The row belongs in MAPPED or
    UNMAPPED, which this module cannot put it in."""
    f["sheet"]["candidates"][0]["verdict"] = "reject: this section is about an account"


def _case_decision_reached_some_other_way(f):
    """A relation whose kind was decided on a basis this module does not produce. ADR 0004's
    own worked example is one: the section that establishes the ADMINISTRATION (ORS 576.066
    has the Department of Agriculture appoint members, review budgets and approve plans) is
    not an enabling authority and nothing here reads it, so a kind resting on it can only
    have been curated. --apply must leave such an entry exactly as it is — overwriting it
    with a proposal would replace a stronger claim with a weaker one, by the machinery
    introduced to keep the two apart — and this is what says the gate reports it instead."""
    _org(f, "board-of-imagined-standards")[RELATION_KEY][0].update(
        basis="statute-establishes-the-administration", authority="ORS 999.992")


_CASES = [
    ("kind-written-by-something-else", _case_kind_written_by_something_else, "kind-agrees"),
    ("registry-still-holds-the-proposed-basis-after-review",
     _case_registry_still_holds_the_proposed_basis_after_review, "kind-agrees"),
    ("candidate-that-is-not-a-recordable-authority",
     _case_candidate_that_is_not_a_recordable_authority, "candidate-form"),
    ("candidate-with-no-citation-at-all", _case_candidate_with_no_citation_at_all,
     "candidate-form"),
    ("verdict-that-never-reached-the-reviewed-table",
     _case_verdict_that_never_reached_the_reviewed_table, "verdict-not-applied"),
    ("decision-reached-some-other-way", _case_decision_reached_some_other_way,
     "decision-not-ours"),
]


def _proof_only_the_positive_half_is_derived() -> int:
    """The derivation decides `administered_by` and NOTHING ELSE. The fixture holds two
    children no candidate speaks for — one the matcher missed, one a human reviewed as having
    no separate authority — and both must come out `undetermined`, because neither an absent
    candidate nor a reviewed absence is a decision this module takes.

    The expected values are written out from the fixture ABOVE rather than re-derived the way
    the derivation derives them, which would pass whatever it said."""
    f = _fixture()
    expected = {
        "imaginary-affairs-inspection-division": (UNDETERMINED, None, None),
        "imaginary-affairs-records-unit": (UNDETERMINED, None, None),
        "board-of-imagined-standards": (ADMINISTERED_BY, PROPOSED_AUTHORITY, "ORS 999.999"),
        "office-of-imagined-orders": (ADMINISTERED_BY, REVIEWED_AUTHORITY, "ORS 999.997"),
    }
    bad = 0
    for slug, want in expected.items():
        entry = _org(f, slug)[RELATION_KEY][0]
        got = tuple(entry.get(k) for k in DECISION_KEYS)
        if got != want:
            print(f"FAIL only-the-positive-half-is-derived: {slug} -> {got!r}, expected "
                  f"{want!r}", file=sys.stderr)
            bad += 1
    if any(e.get("kind") == "part_of" for o in f["cat"]["organizations"]
           for e in relation_entries(o)):
        print("FAIL no-part-of-is-derived: a kind was derived from the absence of evidence",
              file=sys.stderr)
        bad += 1
    return bad


def _proof_review_upgrades_the_basis() -> int:
    """Criterion 4: re-running after a candidate is reviewed upgrades that row's basis, and
    the change is visible.

    The upgrade is measured as a DIFF of the dumped registry rather than as an assertion
    about the row, because "visible in the diff" is the claim — a human reading the PR is who
    the basis is for. The reviewed citation deliberately DIFFERS from the proposed one: a
    review that merely confirms the candidate would leave the authority unchanged, and a
    proof that could not tell the two apart would pass on a module that never upgraded
    anything."""
    f = _fixture()
    before = yaml.safe_dump(f["cat"], sort_keys=False, allow_unicode=True, width=100)
    # What link_enabling_authority.py --apply does when the candidate is reviewed and a
    # different section turns out to be the one that constitutes the body.
    _org(f, "board-of-imagined-standards")["enabling_authority"] = "ORS 999.993"
    if not _audit(f):
        print("FAIL review-is-a-red-build-until-it-is-applied: the registry still records "
              "the proposed basis and this derivation is content with it", file=sys.stderr)
        return 1
    changed = apply_decisions(f["cat"], read_sheet(f["sheet"]).proposed)
    after = yaml.safe_dump(f["cat"], sort_keys=False, allow_unicode=True, width=100)
    entry = _org(f, "board-of-imagined-standards")[RELATION_KEY][0]
    bad = 0
    if changed != 1 or tuple(entry.get(k) for k in DECISION_KEYS) != (
            ADMINISTERED_BY, REVIEWED_AUTHORITY, "ORS 999.993"):
        print(f"FAIL review-upgrades-the-basis: wrote {changed} row(s), entry is {entry!r}",
              file=sys.stderr)
        bad += 1
    # THE WHOLE FILE, not a slice of it. The fixture's only proposal-derived kind is the row
    # just reviewed, so after the upgrade the word may not appear anywhere in the registry —
    # which is a stronger statement than "not on that row" and does not have to find the row
    # by cutting up dumped YAML.
    if PROPOSED_AUTHORITY not in before or PROPOSED_AUTHORITY in after:
        print(f"FAIL the-upgraded-row-still-records-a-proposal: {PROPOSED_AUTHORITY!r} "
              f"{'was not in' if PROPOSED_AUTHORITY not in before else 'is still in'} the "
              "registry", file=sys.stderr)
        bad += 1
    if before == after:
        print("FAIL the-upgrade-is-visible-in-the-diff: the file did not change",
              file=sys.stderr)
        bad += 1
    if _audit(f):
        print(f"FAIL the-upgrade-settles-the-gate: {_audit(f)}", file=sys.stderr)
        bad += 1
    return bad


def _proof_apply_writes_the_same_bytes_twice() -> int:
    """--apply is a migration, and a migration that is not re-runnable is one nobody can
    replay against the committed file to check what it did. Run twice over the same rows: the
    second run must change nothing and dump the same bytes."""
    f = _registry()
    proposed = read_sheet(f["sheet"]).proposed
    first = apply_decisions(f["cat"], proposed)
    once = yaml.safe_dump(f["cat"], sort_keys=False, allow_unicode=True, width=100)
    reloaded = yaml.safe_load(once)
    again = apply_decisions(reloaded, proposed)
    twice = yaml.safe_dump(reloaded, sort_keys=False, allow_unicode=True, width=100)
    # The two rows the derivation decides are the two it may write. A run that touched the
    # other three wrote `undetermined` over `undetermined` and would churn the file forever.
    if first != 2 or again != 0 or once != twice:
        print(f"FAIL apply-writes-the-same-bytes-twice: wrote {first} of 2 row(s), rewrote "
              f"{again} on the second run, bytes "
              f"{'match' if once == twice else 'differ'}", file=sys.stderr)
        return 1
    return 0


def _proof_a_withdrawn_candidate_returns_the_row_to_undetermined() -> int:
    """A candidate that goes away takes its kind with it. This module is the decision's
    single writer, so a kind it no longer derives is one nothing stands behind — and
    `undetermined` says that, where a stale `administered_by` says the opposite with nobody
    behind it."""
    f = _fixture()
    f["sheet"]["candidates"] = [c for c in f["sheet"]["candidates"]
                               if c["slug"] != "board-of-imagined-standards"]
    apply_decisions(f["cat"], read_sheet(f["sheet"]).proposed)
    entry = _org(f, "board-of-imagined-standards")[RELATION_KEY][0]
    if tuple(entry.get(k) for k in DECISION_KEYS) != (UNDETERMINED, None, None):
        print(f"FAIL withdrawn-candidate-returns-the-row-to-undetermined: {entry!r}",
              file=sys.stderr)
        return 1
    return 0


def selftest() -> int:
    bad = (_proof_only_the_positive_half_is_derived()
           + _proof_review_upgrades_the_basis()
           + _proof_apply_writes_the_same_bytes_twice()
           + _proof_a_withdrawn_candidate_returns_the_row_to_undetermined())
    for name, mutate, rule in _CASES:
        f = _fixture()
        assert not _audit(f), f"fixture does not pass cleanly ({name}): {_audit(f)}"
        mutate(f)
        problems = _audit(f)
        if not any(p.rule == rule for p in problems):
            print(f"FAIL {name}: expected a [{rule}] problem, got {problems}",
                  file=sys.stderr)
            bad += 1
    print(f"{len(_CASES)} violation(s) demonstrated failing, 4 derivation proof(s) held"
          if not bad else f"{bad} rule(s) did not fire")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true",
                   help="write the derived kind, basis and authority onto every relation")
    g.add_argument("--check", action="store_true",
                   help="verify the registry's relation kinds against this derivation")
    g.add_argument("--selftest", action="store_true",
                   help="prove every rule --check enforces can fail")
    args = ap.parse_args()
    if args.apply:
        return cmd_apply()
    if args.selftest:
        return selftest()
    return check()


if __name__ == "__main__":
    sys.exit(main())
