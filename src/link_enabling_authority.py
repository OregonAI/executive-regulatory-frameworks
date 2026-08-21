#!/usr/bin/env python3
"""Attach enabling authorities to the agency registry.

  python3 src/link_enabling_authority.py --propose   # write a review sheet of candidates
  python3 src/link_enabling_authority.py --check     # verify the reviewed table against ORS

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
for the Blind program. It is a better signal because a catchline states what the section is
ABOUT, where proximity only states what words are nearby.

It is still not a verdict. Tier 2 widens to catchline subjects that merely contain the
agency's name, and that tier contains both `Department of State Police established`
(ORS 181A.015, correct) and `When support payment to be made to Department...` (ORS 25.020,
a child-support section that is not the Department of Justice's enabling authority).

SO THIS PROPOSES AND CHECKS; IT NEVER WRITES THE REGISTRY. `--propose` emits a review sheet
quoting the sentence that matched, so review is reading rather than research. A human moves
rows into MAPPED or UNMAPPED below. `--check` then verifies the committed table against the
mirrored corpus, in CI, from committed data alone.

UNMAPPED IS EXPLICIT, never implied by absence — "we looked and there is no counterpart" and
"nobody has looked yet" must not be the same state (CONTEXT.md; link_budget_codes.py).
82 of 189 bodies have no candidate at all, and several never will: the Secretary of State
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

from repo_lib import REPO_ROOT

CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"
STATUTES = REPO_ROOT / "statutes"
REVIEW_SHEET = REPO_ROOT / "_meta/catalog/enabling-authority-review.yml"

# ---------------------------------------------------------------- reviewed registry data
#
# slug -> authority. EVERY ROW HERE HAS BEEN READ BY A HUMAN against the cited text. Add a
# row only after reading the section; a row that was pattern-matched and not read belongs in
# the review sheet, not here.
MAPPED: dict[str, str] = {
    # e.g. "appraiser-certification-and-licensure-board": "ORS 674.305",
}

# slug -> why this body has no enabling authority recorded. A DECISION with a stated reason,
# never a blank.
UNMAPPED: dict[str, str] = {
    # e.g. "secretary-of-state": "Constitutional office — Or. Const. Art. VI, sec. 1. Not
    #                             created by statute, so no ORS section can be cited.",
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
    rows, unmatched = [], []

    for org in orgs:
        slug = org["slug"]
        if slug in MAPPED or slug in UNMAPPED:
            continue
        names = _variants(org["name"])
        hit = None
        for cite, title, subject, body, made in sections:    # tier 1: subject IS the body
            if made and subject in names:
                hit = (1, cite, title, _quote(body))
                break
        if hit is None:                                      # tier 2: subject contains it
            for cite, title, subject, body, made in sections:
                if not made or NOT_A_BODY.search(title) or len(subject) <= 12:
                    continue
                if subject in names or any(v in subject for v in names):
                    hit = (2, cite, title, _quote(body))
                    break
        if hit is None:                                      # tier 2: a later catchline clause
            for cite, title, subject, body, made in sections:
                if not made:
                    continue
                for clause in title.split(";")[1:]:
                    if not CLAUSE_CREATE.search(clause) or NOT_A_BODY.search(clause):
                        continue
                    if any(v in _norm(clause) for v in names if len(v) > 12):
                        hit = (2, cite, title, _quote(body))
                        break
                if hit:
                    break
        if hit is None:                                      # tier 3: named exactly, no verb
            for cite, title, subject, body, made in sections:
                if made or NOT_A_BODY.search(title) or len(subject) <= 12:
                    continue
                if subject in names:
                    hit = (3, cite, title, _first_sentence(body))
                    break
        if hit is None:
            unmatched.append({"slug": slug, "name": org["name"]})
        else:
            tier, cite, title, quote = hit
            rows.append({"slug": slug, "name": org["name"], "tier": tier,
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


def check() -> int:
    """Verify the reviewed table against the mirrored corpus, from committed data alone."""
    orgs = {o["slug"]: o for o in yaml.safe_load(CATALOG.read_text())["organizations"]}
    problems = []

    for slug in sorted(set(MAPPED) | set(UNMAPPED)):
        if slug not in orgs:
            problems.append(f"{slug}: named here but not in the registry")
    both = sorted(set(MAPPED) & set(UNMAPPED))
    for slug in both:
        problems.append(f"{slug}: is in BOTH mapped and unmapped — it cannot be both")

    # Every mirrored section is a valid target, not only those with creation language: a
    # tier-3 authority is a real section that happens not to use the verb, and requiring it
    # here would reject exactly the twelve rows tier 3 exists to let a human accept.
    by_cite = {c: (t, b) for c, t, _s, b, _m in _statute_sections()}
    for slug, authority in sorted(MAPPED.items()):
        if not authority.startswith("ORS "):
            continue                       # constitutional and EO authorities are not in ORS
        if authority not in by_cite:
            problems.append(
                f"{slug}: cites {authority}, which is not a mirrored ORS section. Either "
                f"the citation is wrong or upstream changed — both are worth knowing.")

    if problems:
        print("enabling-authority table does not match the corpus:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1

    decided = len(MAPPED) + len(UNMAPPED)
    print(f"enabling-authority table is consistent with the corpus: "
          f"{len(MAPPED)} mapped, {len(UNMAPPED)} unmapped, "
          f"{len(orgs) - decided} of {len(orgs)} bodies not yet reviewed.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--propose", action="store_true",
                   help="write a review sheet of candidates; writes nothing to the registry")
    g.add_argument("--check", action="store_true",
                   help="verify the reviewed table against the mirrored corpus")
    args = ap.parse_args()
    return propose() if args.propose else check()


if __name__ == "__main__":
    sys.exit(main())
