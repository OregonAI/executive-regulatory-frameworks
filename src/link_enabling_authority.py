#!/usr/bin/env python3
"""Attach enabling authorities to the agency registry.

  python3 src/link_enabling_authority.py --propose   # write a review sheet of candidates
  python3 src/link_enabling_authority.py --apply     # write enabling_authority into the registry
  python3 src/link_enabling_authority.py --check     # verify the reviewed table against ORS
  python3 src/link_enabling_authority.py --selftest  # CI: every rule --check enforces fires

WHY THIS IS NOT A GENERATOR. CONTEXT.md defines an *enabling authority* as what created a
body, and ADR 0003 makes it ADMITTING evidence — a statute alone is enough to put a body in
the registry. So a wrong citation here is not a bad label, it is a false statement about
Oregon law published under provenance, and possibly a body admitted on evidence that does
not exist.

The first attempt searched the mirrored ORS for creation language near an agency's name. It
matched 78 of 189 bodies and **37% of those establish a Treasury ACCOUNT rather than the
body**:

    Board of Chiropractic Examiners  -> ORS 684.171  "...Account which is hereby established"
    Board of Licensed Social Workers -> ORS 675.597  "...Account is established in the State Treasury"
    Board of Medical Imaging         -> ORS 688.585  "...Account. (1) The ... Account is established"

Every one of those looks right at a glance and cites the wrong section. This is
`link_budget_codes.py`'s lesson on a corpus that mirrors statute: a matcher that is
confidently wrong produces claims a reviewer would have caught and a generator ships.

WHAT ACTUALLY WORKS IS THE CATCHLINE. An ORS section's `title` is its catchline, and the
segment before the first semicolon is its SUBJECT:

    674.305  Appraiser Certification and Licensure Board; appointment; term; compensation
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Anchoring on that instead of on body proximity finds 77 bodies with ZERO account
false positives, and fixes all three cases above (684.130, 675.590, 688.545 — the boards,
not their accounts).

AND CREATION LANGUAGE IS A TIER, NOT A FILTER. Requiring it of every section was the
largest single cause of `no_candidate`: ORS 677.235 is titled `Oregon Medical Board;
membership; confirmation; terms` and never says the board is created — it simply
constitutes it. Twelve licensing boards were reported as having no candidate for that
reason alone. They are now tier 3, which asks the reviewer a different question than tier
1 does: not "is this citation right" but "does this section constitute the body, or
describe one constituted elsewhere". ORS 346.180 shows why that must stay a question — it
reached tier 3 for the DHS vocational-rehabilitation division and is about a Commission
for the Blind program.

AND A BODY CAN BE CREATED WITHOUT EVER APPEARING IN A CATCHLINE. ORS 576.062 is titled
`Establishment of commodity commissions` and reads "The following commodity commissions are
established as state commissions: (1) The Oregon Dairy Products Commission. …". Nineteen
bodies are created there and named there, and catchline anchoring found none of them,
because the catchline names the CATEGORY. That was 19 of the 82 remaining no-candidate
rows — the largest single block left — and every one is now tier 1 on `enumerated-list`.
Only items following the creating phrase count: a section enumerates duties and exemptions
as readily as bodies. It is a better signal because a catchline states what the section is
ABOUT, where proximity only states what words are nearby.

It is still not a verdict. Tier 2 widens to catchline subjects that merely contain the
agency's name, and that tier contains both `Department of State Police established`
(ORS 181A.015, correct) and `When support payment to be made to Department...` (ORS 25.020,
a child-support section that is not the Department of Justice's enabling authority).

SO THE MATCHER PROPOSES AND A HUMAN DECIDES. `--propose` emits a review sheet quoting the
sentence that matched, so review is reading rather than research; it writes nothing to the
registry. A human moves rows into MAPPED or UNMAPPED below. `--check` then verifies the
committed table against the mirrored corpus, in CI, from committed data alone.

AND THIS FILE IS THE REGISTRY FIELD'S SINGLE WRITER. `--apply` writes MAPPED and UNMAPPED
into `enabling_authority` on the registry rows, and nothing else writes that key — the same
arrangement `das_agency_number` has with link_budget_codes.py, for the reason #175 exists:
two writers of one field is drift that nothing reports. `--check` verifies the registry
against this table in both directions, so a row that acquired an authority some other way is
a failure rather than a fact.

WHAT THE FIELD MAY SAY is declared once, in catalog_agencies.AUTHORITY_FORMS — an ORS
citation, a constitutional article, or an executive order (ADR 0003), or `none: ` and the
reason there is none. This gate reads that grammar rather than restating it, so a value
cannot be legal in the table and illegal in the file the table is written to. It checks the
TABLE against the grammar; the registry's own contract check (catalog_agencies.py --check)
checks the ROWS. Same rule, two populations, and neither one covers the other: an authority
can be wrong in the table before it is ever written, and a row can be hand-edited after.

THE THREE STATES, and the reason MAPPED and UNMAPPED are both explicit. A row carrying
`ORS 576.062` has an authority; a row carrying `none: <reason>` was looked at and has none;
a row carrying no `enabling_authority` key at all has not been looked at. All 189 are in the
third state today. Absence is never a claim that a body has no enabling authority.

UNMAPPED IS EXPLICIT, never implied by absence — "we looked and there is no counterpart" and
"nobody has looked yet" must not be the same state (CONTEXT.md; link_budget_codes.py).
63 of 189 bodies have no candidate at all, and several never will: the Secretary of State
and the State Treasurer are CONSTITUTIONAL offices, which is why the field is an authority
rather than a statute. That number was 118 until a run of the proposer showed the gap was
the registry's own `Parent, Child` name format rather than silent statutes — see
`_variants`. A no-candidate list is a claim about the corpus, so it is worth distrusting
before it is worth reviewing.
"""
from __future__ import annotations

import argparse
import collections
import re
import sys

import yaml

from catalog_agencies import (NO_AUTHORITY, authority_census, classify_authority,
                              no_authority_value)
from repo_lib import REPO_ROOT

CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"
STATUTES = REPO_ROOT / "statutes"
EXECUTIVE_ORDERS = REPO_ROOT / "executive-orders"
REVIEW_SHEET = REPO_ROOT / "_meta/catalog/enabling-authority-review.yml"

# One thing wrong with the reviewed table or with the registry it writes: which rule, which
# body, and what is wrong. A type rather than a formatted string, so --selftest asserts on
# the RULE that fired instead of pattern-matching prose — the way a proof starts passing for
# the wrong reason (catalog_agencies.Failure, same lesson).
Problem = collections.namedtuple("Problem", "rule slug detail")

# ---------------------------------------------------------------- reviewed registry data
#
# slug -> authority. EVERY ROW HERE HAS BEEN READ BY A HUMAN against the cited text. Add a
# row only after reading the section; a row that was pattern-matched and not read belongs in
# the review sheet, not here.
MAPPED: dict[str, str] = {
    # e.g. "appraiser-certification-and-licensure-board": "ORS 674.305",
}

# slug -> why this body has no enabling authority TO RECORD. A DECISION with a stated reason,
# never a blank, and never a citation: a body whose authority is a constitutional article
# HAS one, and belongs in MAPPED above. That is what this example used to be — the Secretary
# of State, filed here as "constitutional office, so no ORS section can be cited", which was
# true of a field that could only hold statutes and became a false absence the day the field
# started accepting `Or. Const. Art. VI, sec. 1` (#170). The commonest legitimate reason is
# ADR 0004's: a `part_of` unit has nothing separate to enable.
UNMAPPED: dict[str, str] = {
    # e.g. "department-of-transportation-highway-division": "Part of the Department of
    #      Transportation (ADR 0004): nothing separately constitutes it, so there is no
    #      enabling authority to record.",
}

CREATE = re.compile(
    r"\b(?:there (?:is|are) (?:hereby )?(?:created|established)"
    r"|(?:is|are) (?:hereby )?(?:created|established))\b", re.I)

# A catchline naming one of these is describing money, not a body. Measured: without this,
# 37% of proximity matches were Treasury accounts.
NOT_A_BODY = re.compile(r"\b(accounts?|funds?|subaccounts?|trusts?)\b", re.I)

# A CATCHLINE is a noun phrase, not a sentence, so it says "Legislative Equity Office
# established" where the body of the section says "is established". `CREATE` requires the
# verb and therefore never matches a catchline clause. Matching the bare participle is safe
# HERE and only here: it is applied to one `;`-separated clause that already had to name the
# body, not to running statutory text where "established" appears constantly.
CLAUSE_CREATE = re.compile(r"\b(created|established)\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())).strip()


def _spellings(name: str) -> set[str]:
    b = _norm(name)
    return {v for v in (b, _norm("state " + name), _norm("oregon " + name),
                        b.replace("state ", ""), b.replace("oregon ", "")) if v}


def _variants(name: str) -> set[str]:
    """Spellings of one body. ORS writes `State Board of X` where the rules index writes
    `Board of X`, and `Oregon` floats to either end.

    The registry stores a sub-unit as `Parent, Child` — 81 of 189 bodies — because the OAR
    index nests by chapter. ORS catchlines name the CHILD ALONE, so matching the compound
    string finds nothing: `Department of Agriculture, Oregon Wheat Commission` never matches
    the catchline `Oregon Wheat Commission; members; appointment process; rules`. Measured,
    the tail segment recovers 21 tier-1 rows that were sitting in `no_candidate` looking
    like bodies statute forgot to create.
    """
    v = _spellings(name)
    if "," in name:
        v |= _spellings(name.rsplit(",", 1)[1].strip())
    return {x for x in v if x}


def _statute_sections() -> list[tuple[str, str, str, str, bool]]:
    """(citation, catchline, catchline subject, body, says_created) for EVERY mirrored ORS
    section. Read from the MIRRORED corpus, never fetched.

    This used to return only sections whose body carried creation language, and that
    prefilter was the single largest cause of `no_candidate`. Oregon does not draft
    licensing boards with a creation verb — ORS 677.235 is titled `Oregon Medical Board;
    membership; confirmation; terms` and never says the board is created, it simply
    constitutes it. Twelve boards were reported as having no candidate for that reason
    alone, each with a catchline naming it exactly.

    So the flag is carried rather than filtered on, and tier 3 uses it. 2,061 of 37,465
    sections say `created`/`established`; the other 35,404 were previously invisible.
    """
    out = []
    for path in sorted(STATUTES.rglob("ors-*.md")):
        text = path.read_text(errors="replace")
        fm = text.split("---", 2)[1] if text.startswith("---") else ""
        title = (re.search(r'(?m)^title:\s*"?([^"\n]+)', fm) or [None, ""])[1].strip()
        cite = (re.search(r'(?m)^citation:\s*"?([^"\n]+)', fm) or [None, path.stem])[1].strip()
        body = " ".join(text.split("---", 2)[-1].split())
        out.append((cite, title, _norm(title.split(";")[0]), body, bool(CREATE.search(body))))
    if not any(o[4] for o in out):
        sys.exit("no ORS sections with creation language were found — refusing to report "
                 "zero candidates as a finished job. Is `statutes/` populated?")
    return out


ENUMERATED = re.compile(r"\(\d+\)\s*The ([A-Z][^.;]{4,90}?)\.")


def _enumerated(body: str) -> set[str]:
    """Bodies named as items of a creating list, normalised.

    ORS 576.062 is titled `Establishment of commodity commissions` and reads "The following
    commodity commissions are established as state commissions: (1) The Oregon Dairy
    Products Commission. (2) The Oregon Hazelnut Commission. …". Every one of those IS
    created by statute and named in it, but no catchline names any of them, so catchline
    anchoring reports nineteen bodies as having no candidate while the section that creates
    them sits in the mirror. Nineteen of the registry's twenty-three commodity rows match
    this list exactly.

    Only items AFTER the creation phrase count. A section may enumerate duties, members or
    exemptions as readily as bodies, and a list that precedes the creating words is not a
    list of things being created.
    """
    m = CREATE.search(body)
    if not m:
        return set()
    return {_norm(x) for x in ENUMERATED.findall(body[m.start():])}


def _quote(body: str) -> str:
    """The sentence that matched, so a reviewer reads rather than researches.

    NOT CITABLE TEXT. The body it slices has had its whitespace collapsed, so this is an
    excerpt for review and not the verbatim ORS text this repo's content policy governs.
    Read the cited section itself before accepting a row.
    """
    m = CREATE.search(body)
    if not m:
        return ""
    start = body.rfind(".", 0, max(0, m.start() - 1)) + 1
    end = body.find(".", m.end())
    return body[start:end + 1 if end > 0 else len(body)].strip()


def _first_sentence(body: str) -> str:
    """The section's opening sentence, for a tier-3 row.

    `_quote` anchors on the creation verb, and a tier-3 section has none — that is what
    makes it tier 3. The opening sentence is what a reviewer needs instead, because the
    question tier 3 asks is whether this section CONSTITUTES the body or merely describes
    a body constituted elsewhere. `ORS 677.235` opens by composing the Oregon Medical
    Board of members; whether that is its enabling authority is a judgment, not a match.

    Slices after the `## Full text` heading. Without that the excerpt is the mirror's
    NON-AUTHORITATIVE banner, which every document carries and which tells a reviewer
    nothing — the first version of this function quoted the disclaimer for all twelve rows.

    NOT CITABLE TEXT — same whitespace-collapsed excerpt caveat as `_quote`.
    """
    marker = "## Full text"
    text = body.split(marker, 1)[1] if marker in body else body
    end = text.find(".", 220)
    return text[:end + 1 if end > 0 else min(len(text), 420)].strip()


def propose() -> int:
    orgs = yaml.safe_load(CATALOG.read_text())["organizations"]
    sections = _statute_sections()
    # Enumerations are extracted ONCE. Doing it inside the per-body loop is 189 x 37,465
    # regex passes over full section text for a match that changes for neither.
    enumerations = [(c, t, b, _enumerated(b)) for c, t, _s, b, made in sections if made]
    rows, unmatched = [], []

    for org in orgs:
        slug = org["slug"]
        if slug in MAPPED or slug in UNMAPPED:
            continue
        # NAME READER — JOIN, and one that matches the STATUTORY name on purpose. The
        # strings on the other side are ORS catchlines and creating clauses — statute text,
        # which spells a body the way the statute that created it does. `name` is that name
        # after ADR 0003, so this join gets MORE accurate when #168 lands, not less; moving
        # it to `oar_name` would match the rules index's spelling against statute text.
        names = _variants(org["name"])
        hit = None
        for cite, title, subject, body, made in sections:    # subject IS the body
            if made and subject in names:
                hit = (1, "catchline-subject", cite, title, _quote(body))
                break
        if hit is None:                                      # named in a creating list
            for cite, title, body, items in enumerations:
                if names & items:
                    hit = (1, "enumerated-list", cite, title, _quote(body))
                    break
        if hit is None:                                      # subject contains the name
            for cite, title, subject, body, made in sections:
                if not made or NOT_A_BODY.search(title) or len(subject) <= 12:
                    continue
                if subject in names or any(v in subject for v in names):
                    hit = (2, "catchline-contains", cite, title, _quote(body))
                    break
        if hit is None:                                      # named in a later clause
            for cite, title, subject, body, made in sections:
                if not made:
                    continue
                for clause in title.split(";")[1:]:
                    if not CLAUSE_CREATE.search(clause) or NOT_A_BODY.search(clause):
                        continue
                    if any(v in _norm(clause) for v in names if len(v) > 12):
                        hit = (2, "catchline-clause", cite, title, _quote(body))
                        break
                if hit:
                    break
        if hit is None:                                      # named exactly, no creation verb
            for cite, title, subject, body, made in sections:
                if made or NOT_A_BODY.search(title) or len(subject) <= 12:
                    continue
                if subject in names:
                    hit = (3, "catchline-subject-no-verb", cite, title,
                           _first_sentence(body))
                    break
        if hit is None:
            # NAME READER — DISPLAY: the name a human reads on the proposal sheet beside
            # the slug they are being asked to rule on.
            unmatched.append({"slug": slug, "name": org["name"]})
        else:
            tier, basis, cite, title, quote = hit
            rows.append({"slug": slug, "name": org["name"], "tier": tier, "basis": basis,
                         "candidate": cite, "catchline": title, "text": quote,
                         "verdict": ""})

    REVIEW_SHEET.write_text(yaml.safe_dump({
        "note": ("PROPOSED, NOT DECIDED. Each row is a candidate an automated match "
                 "produced; none has been read. Set `verdict` to `accept`, or to a "
                 "different ORS citation, or to a reason it cannot be mapped — then move "
                 "the row into MAPPED or UNMAPPED in src/link_enabling_authority.py. "
                 "Tier 1 means the section's catchline subject IS this body AND the "
                 "section says it is created or established. Tier 2 means the catchline "
                 "merely contains the name, or names it in a later clause. Tier 3 means "
                 "the catchline subject IS the body but NO creation language appears "
                 "anywhere in the section — Oregon does not draft licensing boards with a "
                 "creation verb, so tier 3 is not weaker than tier 2, it asks a DIFFERENT "
                 "question: does this section CONSTITUTE the body, or describe one "
                 "constituted elsewhere? Tiers 2 and 3 are where the wrong answers live. "
                 "`basis` says HOW the row matched, which tier alone does not: "
                 "catchline-subject, enumerated-list, catchline-contains, "
                 "catchline-clause, or catchline-subject-no-verb. A tier-1 row matched "
                 "on an enumerated list is as strong as one matched on a catchline, but "
                 "it is checked differently — read the list item, not the catchline. "
                 "`text` is the excerpt that matched, quoted so review is "
                 "reading rather than research — an EXCERPT with whitespace collapsed, "
                 "NOT citable verbatim text. Read the cited section itself before "
                 "accepting a row."),
        "generated_from": "the mirrored ORS in statutes/, never fetched",
        "candidates": rows,
        "no_candidate": unmatched,
    }, sort_keys=False, allow_unicode=True, width=100))

    n = collections.Counter(r["tier"] for r in rows)
    print(f"wrote {REVIEW_SHEET.relative_to(REPO_ROOT)}")
    print(f"  candidates to review : {len(rows)}  "
          f"(tier 1: {n[1]}, tier 2: {n[2]}, tier 3: {n[3]})")
    print(f"  no candidate found   : {len(unmatched)}")
    print(f"  already decided      : {len(MAPPED)} mapped, {len(UNMAPPED)} unmapped")
    print("\nNothing was written to the registry. Read the rows, then move them into "
          "MAPPED/UNMAPPED in this script.")
    return 0


def _executive_order_citations() -> set[str]:
    """The citation every mirrored executive order carries — `Executive Order 20-03`.

    Read from the MIRROR, never fetched, exactly as `_statute_sections` reads the ORS. It
    refuses to return an empty set for the same reason that function refuses to report zero
    candidates: with no orders on disk, every executive-order authority would be reported as
    citing an order that does not exist, and "could not check" is never reported as "is not
    there" (CONTEXT.md).
    """
    out = set()
    for path in sorted(EXECUTIVE_ORDERS.glob("eo-*.md")):
        m = re.search(r'(?m)^citation:\s*"?([^"\n]+)', path.read_text(errors="replace"))
        if m:
            out.add(m.group(1).strip().rstrip('"'))
    if not out:
        sys.exit("no mirrored executive orders were found — refusing to report an "
                 "executive-order authority as unresolvable. Is `executive-orders/` "
                 "populated?")
    return out


def resolvable_citations() -> set[str]:
    """Every citation this corpus can resolve an authority against: the mirrored ORS
    sections and the mirrored executive orders.

    THE OREGON CONSTITUTION IS NOT IN HERE, because it is not mirrored. ADR 0005 states
    that hole rather than working around it — `Or. Const. Art. XVII, sec. 99` is well-formed
    and nothing can say it is wrong — so a constitutional authority is checked for FORM and
    reported as unverified, never silently counted as verified.
    """
    return {c for c, _t, _s, _b, _m in _statute_sections()} | _executive_order_citations()


def reviewed(mapped=None, unmapped=None) -> dict[str, str]:
    """slug -> the exact value `enabling_authority` should hold on that registry row.

    THE ONE PLACE THE VALUE IS DERIVED, so `--apply` writes and `--check` compares the same
    string rather than two spellings of it. An UNMAPPED reason becomes `none: <reason>`
    because the registry has to carry the finding itself: three sibling corpora read
    agencies.yml as YAML from their own repos and cannot see a Python dict.
    """
    mapped = MAPPED if mapped is None else mapped
    unmapped = UNMAPPED if unmapped is None else unmapped
    out = {slug: no_authority_value(reason) for slug, reason in unmapped.items()}
    out.update(mapped)   # a slug in both tables is REPORTED below, never resolved here
    return out


def audit_table(orgs, mapped, unmapped, citations) -> list[Problem]:
    """Everything wrong with the reviewed tables themselves, as Problems.

    Separate from `audit_registry` below because `--apply` must run this one and not that
    one: the registry disagreeing with the table is precisely what --apply is for, while a
    bad row in the TABLE is a thing that must never be written to the registry at all.
    """
    by_slug = {o["slug"]: o for o in orgs if isinstance(o, dict) and o.get("slug")}
    problems = []

    for slug in sorted(set(mapped) | set(unmapped)):
        if slug not in by_slug:
            problems.append(Problem("slug-in-registry", slug,
                                    "named here but not in the registry"))
    for slug in sorted(set(mapped) & set(unmapped)):
        problems.append(Problem("not-both-tables", slug,
                                "is in BOTH MAPPED and UNMAPPED — a body either has an "
                                "enabling authority or has a reason it has none, and "
                                "whichever table a reader consults would be the answer"))

    for slug, authority in sorted(mapped.items()):
        form, detail = classify_authority(authority)
        if form is None:
            problems.append(Problem("authority-form", slug, detail))
        elif form == "reviewed-none":
            problems.append(Problem(
                "authority-form", slug,
                f"{authority!r} records that there is no authority, which is UNMAPPED's "
                "job — MAPPED holds authorities, and a row in the wrong table is a body "
                "reported as having one"))
        elif form != "constitution" and authority not in citations:
            # Not "not a mirrored ORS section": an executive order is an authority too
            # (ADR 0003) and this corpus mirrors 526 of them, so both forms resolve against
            # something. Only the constitutional form has nothing to resolve against.
            problems.append(Problem(
                "authority-resolves", slug,
                f"cites {authority}, which no document in this corpus carries. Either the "
                "citation is wrong or upstream changed — both are worth knowing"))

    for slug, reason in sorted(unmapped.items()):
        form, detail = classify_authority(no_authority_value(reason))
        if form != "reviewed-none":
            problems.append(Problem("unmapped-has-reason", slug, detail))
        # THE MIRROR IMAGE OF THE RULE ABOVE, and the one this table walked into once: a
        # reason that IS a citation says the body has an authority while filing it as a body
        # that has none. Constitutional offices are how it happens — the field could hold
        # only statutes when this table was written, so `Or. Const. Art. VI, sec. 1` was a
        # reason rather than a value. It is a value now.
        elif classify_authority(str(reason).strip())[0] is not None:
            problems.append(Problem(
                "unmapped-is-not-an-authority", slug,
                f"the reason recorded here IS an authority ({str(reason).strip()!r}) — a "
                "body with one belongs in MAPPED, and filing it here reports it as a body "
                "nothing created"))
    return problems


def audit_registry(orgs, mapped=None, unmapped=None) -> list[Problem]:
    """Every way the registry and the reviewed table disagree, in BOTH directions.

    THIS FILE IS THE FIELD'S SINGLE WRITER, so the second direction is the one that matters:
    a row carrying an `enabling_authority` no table accounts for was written by something
    else, and two writers of one field is the drift #175 exists to prevent. It is also the
    reason this gate can fail while both tables are empty — a hand-edited row fails it today.
    """
    want = reviewed(mapped, unmapped)
    # A row with no slug is skipped here and reported by catalog_agencies.py --check, whose
    # `required-field` rule owns it: nothing in this table can name such a row, so there is
    # no reviewed value to compare it against. Two gates stating one fact is how the fact
    # becomes true in one and false in the other.
    by_slug = {o["slug"]: o for o in orgs if isinstance(o, dict) and o.get("slug")}
    problems = []
    for slug, value in sorted(want.items()):
        if slug not in by_slug:
            continue                      # `slug-in-registry` above already reported it
        got = by_slug[slug].get("enabling_authority")
        if got != value:
            problems.append(Problem("registry-agrees", slug,
                                    f"registry has {got!r}, this table says {value!r} — "
                                    "run --apply"))
    for slug, o in sorted(by_slug.items()):
        if "enabling_authority" in o and slug not in want:
            problems.append(Problem(
                "registry-agrees", slug,
                f"registry carries enabling_authority {o['enabling_authority']!r} and this "
                "table does not. This file is the field's single writer: either the row was "
                "written by something else, or a reviewed row was deleted from the table"))
    return problems


def apply_reviewed(cat, mapped=None, unmapped=None) -> int:
    """Write the reviewed values onto the registry rows. Returns the rows changed.

    RE-RUNNABLE AND BYTE-IDENTICAL, which the value assignment gives for free: a key that is
    already present keeps its position and its value, so the second run changes nothing and
    dumps the same bytes. `_proof_apply_writes_the_same_bytes_twice` keeps that permanent.

    It writes only the rows the table decides. A row the table says nothing about is LEFT
    ALONE rather than cleared, because clearing it would silently un-review a body — and
    `registry-agrees` reports that row instead, which is a human's question to answer.
    """
    want = reviewed(mapped, unmapped)
    changed = 0
    for o in cat.get("organizations") or []:
        value = want.get(o.get("slug")) if isinstance(o, dict) else None
        if value is None or o.get("enabling_authority") == value:
            continue
        o["enabling_authority"] = value
        changed += 1
    return changed


def _report(problems) -> None:
    for p in problems:
        print(f"  FAIL [{p.rule}] {p.slug}: {p.detail}", file=sys.stderr)


def cmd_apply() -> int:
    """Write MAPPED/UNMAPPED into the registry. The only writer of `enabling_authority`."""
    cat = yaml.safe_load(CATALOG.read_text())
    orgs = cat["organizations"]
    problems = audit_table(orgs, MAPPED, UNMAPPED, resolvable_citations())
    if problems:
        print("refusing to write: the reviewed table does not match the corpus",
              file=sys.stderr)
        _report(problems)
        return 1

    changed = apply_reviewed(cat)
    if changed:
        CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True,
                                          width=100))
    print(f"enabling_authority: {changed} row(s) written "
          f"({authority_census(orgs)})")
    # A row the table cannot account for is left where it is and reported. --apply is not
    # allowed to resolve it by deleting a field a human may have put there deliberately.
    left = [p for p in audit_registry(orgs) if p.rule == "registry-agrees"]
    _report(left)
    return 1 if left else 0


def check() -> int:
    """Verify the reviewed table AND the registry it writes, from committed data alone."""
    orgs = yaml.safe_load(CATALOG.read_text())["organizations"]
    citations = resolvable_citations()
    problems = (audit_table(orgs, MAPPED, UNMAPPED, citations)
                + audit_registry(orgs, MAPPED, UNMAPPED))
    if problems:
        print("enabling-authority table does not match the corpus:", file=sys.stderr)
        _report(problems)
        return 1

    # WHAT WAS RESOLVED AND WHAT WAS ONLY READ, reported apart. A constitutional authority
    # is checked for form and nothing else — the Oregon Constitution is not mirrored (ADR
    # 0005) — and folding it into one "verified" count would report an unverifiable claim
    # as a verified one.
    forms = collections.Counter(classify_authority(a)[0] for a in MAPPED.values())
    print(f"enabling-authority table is consistent with the corpus: "
          f"{authority_census(orgs)}.")
    print(f"  resolved against the mirror : {forms['ors']} ORS, "
          f"{forms['executive-order']} executive order(s)")
    print(f"  form checked, not resolved  : {forms['constitution']} constitutional "
          "(the Oregon Constitution is not mirrored — ADR 0005)")
    return 0


# ------------------------------------------------------------------------------ selftest
#
# THE PROOF THAT THE GATE ABOVE CAN FAIL, on a synthetic table and a synthetic registry: no
# network, no read of the committed registry, no read of the mirror. Every rule --check
# enforces is exercised by a case built to break exactly one of them, because a check nobody
# has watched fail is not known to work — it is only known to be quiet. This gate went into
# CI with both tables EMPTY, which is precisely when that distinction matters.


def _fixture():
    """A table, a registry that agrees with it, and a mirror the citations resolve against.

    EVERY BODY AND EVERY CITATION HERE IS MADE UP, and has to be. A row in this table pairs
    a body with what created it — a claim about Oregon law, admitting evidence under ADR
    0003 — and a fixture is not review. ORS has no chapter 999 and no executive order is
    numbered 99-99, so nothing here can be mistaken for a reviewed row or copied into one.
    `Or. Const. Art. XVII, sec. 99` is ADR 0005's own example of a constitutional citation
    that is well-formed and unverifiable, and it is here to prove the gate accepts it.
    """
    mapped = {"board-of-imaginary-affairs": "ORS 999.999",
              "office-of-imagined-orders": "Executive Order 99-99",
              "imaginary-constitutional-office": "Or. Const. Art. XVII, sec. 99"}
    unmapped = {"imaginary-affairs-inspection-division":
                "Part of the Board of Imaginary Affairs; nothing separately constitutes "
                "it (ADR 0004), so there is no enabling authority to record."}
    want = reviewed(mapped, unmapped)
    orgs = [{"slug": slug, "name": slug.replace("-", " ").title(),
             "enabling_authority": want[slug]} for slug in sorted(want)]
    # THE THIRD STATE, carried by the fixture itself: a body no table mentions and whose row
    # holds no `enabling_authority` key. It is the state all 189 committed rows are in, and
    # the fixture has to pass cleanly with it — a gate that treated "nobody has looked yet"
    # as a violation would make the honest default impossible to hold.
    orgs.append({"slug": "board-nobody-has-reviewed", "name": "Board Nobody Has Reviewed"})
    return {"mapped": mapped, "unmapped": unmapped, "orgs": orgs,
            "citations": {"ORS 999.999", "Executive Order 99-99"}}


def _set(f, slug, authority):
    """Put one authority in the table AND on its registry row, so a case breaks exactly one
    rule. Changing only one of the two would also trip `registry-agrees`, and a case that
    fires two rules stops saying which one it is about."""
    f["mapped"][slug] = authority
    for o in f["orgs"]:
        if o["slug"] == slug:
            o["enabling_authority"] = authority


def _audit(f) -> list[Problem]:
    return (audit_table(f["orgs"], f["mapped"], f["unmapped"], f["citations"])
            + audit_registry(f["orgs"], f["mapped"], f["unmapped"]))


def _case_authority_that_cites_nothing(f):
    """Prose where a citation belongs. `--check` used to skip every value that did not begin
    with `ORS `, so this passed and reported the table as consistent with the corpus."""
    _set(f, "board-of-imaginary-affairs", "chapter 999 somewhere")


def _case_authority_that_records_an_absence(f):
    """A `none: <reason>` row filed in MAPPED. It is a well-formed value in the wrong
    table, so every count of bodies WITH an enabling authority includes a body that has
    none — and the two tables stop meaning what their names say."""
    _set(f, "board-of-imaginary-affairs", NO_AUTHORITY + "nothing constitutes it here")


def _case_ors_citation_that_resolves_to_nothing(f):
    """A citation to a section this corpus does not carry. Either it is wrong or upstream
    moved it; both are worth knowing, and neither may be published as admitting evidence."""
    _set(f, "board-of-imaginary-affairs", "ORS 998.998")


def _case_executive_order_that_resolves_to_nothing(f):
    """The same failure for the executive-order form. It is checked because the orders ARE
    mirrored — 526 of them — so taking an EO citation on faith would be a choice, not a
    limitation like the unmirrored constitution."""
    _set(f, "office-of-imagined-orders", "Executive Order 98-98")


def _case_unmapped_with_no_reason(f):
    """"We looked and there is none", with nothing behind it. ADR 0004 calls a `part_of`
    unit's missing authority "a decision with a reason and not a gap"; without the reason
    the two are the same string."""
    f["unmapped"]["imaginary-affairs-inspection-division"] = ""
    for o in f["orgs"]:
        if o["slug"] == "imaginary-affairs-inspection-division":
            o["enabling_authority"] = NO_AUTHORITY


def _case_unmapped_reason_that_is_an_authority(f):
    """A citation filed as a reason there is no citation. The row reads as reviewed and
    reports the body as one nothing created, while the value sitting in it says what did —
    which is how a constitutional office ends up recorded as having no enabling authority."""
    f["unmapped"]["imaginary-affairs-inspection-division"] = "Or. Const. Art. XVII, sec. 99"
    for o in f["orgs"]:
        if o["slug"] == "imaginary-affairs-inspection-division":
            o["enabling_authority"] = no_authority_value("Or. Const. Art. XVII, sec. 99")


def _case_slug_that_is_not_in_the_registry(f):
    """A reviewed row for a body this registry does not carry. The review is real and the
    body it names is unreachable, so the authority is recorded nowhere a reader can find."""
    f["mapped"]["board-of-bodies-that-do-not-exist"] = "ORS 999.999"


def _case_slug_in_both_tables(f):
    """One body with an authority AND a reason it has none. Whichever table a reader
    consults is the answer they get."""
    f["unmapped"]["board-of-imaginary-affairs"] = "Nothing constitutes it separately."


def _case_registry_missing_a_reviewed_authority(f):
    """A reviewed row that never reached the registry. The table says a human read the
    section; the file says nobody has looked at this body — and the file is what three
    sibling corpora read."""
    for o in f["orgs"]:
        if o["slug"] == "board-of-imaginary-affairs":
            del o["enabling_authority"]


def _case_registry_carrying_an_authority_no_table_has(f):
    """A row that acquired an authority some other way — the drift a single writer exists
    to prevent. Nothing about the row looks wrong; it is simply a claim about Oregon law
    that no reviewed table stands behind."""
    for o in f["orgs"]:
        if o["slug"] == "board-nobody-has-reviewed":
            o["enabling_authority"] = "ORS 999.999"


_CASES = [
    ("authority-that-cites-nothing", _case_authority_that_cites_nothing, "authority-form"),
    ("authority-that-records-an-absence", _case_authority_that_records_an_absence,
     "authority-form"),
    ("ors-citation-that-resolves-to-nothing", _case_ors_citation_that_resolves_to_nothing,
     "authority-resolves"),
    ("executive-order-that-resolves-to-nothing",
     _case_executive_order_that_resolves_to_nothing, "authority-resolves"),
    ("unmapped-with-no-reason", _case_unmapped_with_no_reason, "unmapped-has-reason"),
    ("unmapped-reason-that-is-an-authority", _case_unmapped_reason_that_is_an_authority,
     "unmapped-is-not-an-authority"),
    ("slug-that-is-not-in-the-registry", _case_slug_that_is_not_in_the_registry,
     "slug-in-registry"),
    ("slug-in-both-tables", _case_slug_in_both_tables, "not-both-tables"),
    ("registry-missing-a-reviewed-authority", _case_registry_missing_a_reviewed_authority,
     "registry-agrees"),
    ("registry-carrying-an-authority-no-table-has",
     _case_registry_carrying_an_authority_no_table_has, "registry-agrees"),
]


def _proof_apply_writes_the_same_bytes_twice() -> int:
    """--apply is a migration, and a migration that is not re-runnable is one nobody can
    replay against the committed file to check what it did. Run twice over the same rows:
    the second run must change nothing and dump the same bytes."""
    f = _fixture()
    want = reviewed(f["mapped"], f["unmapped"])
    cat = {"organizations": [{"slug": o["slug"], "name": o["name"]} for o in f["orgs"]]}
    first = apply_reviewed(cat, f["mapped"], f["unmapped"])
    once = yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100)
    again = apply_reviewed(yaml.safe_load(once), f["mapped"], f["unmapped"])
    twice = yaml.safe_dump(yaml.safe_load(once), sort_keys=False, allow_unicode=True,
                           width=100)
    # The row no table mentions must come out of a write with NO key, not with a null one:
    # --apply may not turn "nobody has looked yet" into a blank assertion of absence.
    untouched = [o for o in cat["organizations"] if o["slug"] not in want]
    if (first != len(want) or again != 0 or once != twice
            or any("enabling_authority" in o for o in untouched)):
        print(f"FAIL apply-writes-the-same-bytes-twice: wrote {first} of {len(want)} "
              f"row(s), rewrote {again} on the second run, bytes "
              f"{'match' if once == twice else 'differ'}, "
              f"{sum('enabling_authority' in o for o in untouched)} unreviewed row(s) "
              "touched", file=sys.stderr)
        return 1
    return 0


def selftest() -> int:
    bad = _proof_apply_writes_the_same_bytes_twice()
    for name, mutate, rule in _CASES:
        f = _fixture()
        assert not _audit(f), f"fixture does not pass cleanly ({name}): {_audit(f)}"
        mutate(f)
        problems = _audit(f)
        if not any(p.rule == rule for p in problems):
            print(f"FAIL {name}: expected a [{rule}] problem, got {problems}",
                  file=sys.stderr)
            bad += 1
    print(f"{len(_CASES) + 1} violation(s) demonstrated failing"
          if not bad else f"{bad} rule(s) did not fire")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--propose", action="store_true",
                   help="write a review sheet of candidates; writes nothing to the registry")
    g.add_argument("--apply", action="store_true",
                   help="write the reviewed table into the registry's enabling_authority")
    g.add_argument("--check", action="store_true",
                   help="verify the reviewed table and the registry against the corpus")
    g.add_argument("--selftest", action="store_true",
                   help="prove every rule --check enforces can fail")
    args = ap.parse_args()
    if args.propose:
        return propose()
    if args.apply:
        return cmd_apply()
    if args.selftest:
        return selftest()
    return check()


if __name__ == "__main__":
    sys.exit(main())
