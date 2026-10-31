#!/usr/bin/env python3
"""Attach enabling authorities to the agency registry.

  python3 src/link_enabling_authority.py --propose   # write a review sheet of candidates
  python3 src/link_enabling_authority.py --apply     # write enabling_authority into the registry
  python3 src/link_enabling_authority.py --check     # verify the table against the mirror
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

SO THE MATCHER PROPOSES AND A REVIEWER DECIDES. `--propose` emits a review sheet quoting the
sentence that matched, so review is reading rather than research; it writes nothing to the
registry. A reviewer moves rows into MAPPED or UNMAPPED below. `--check` then verifies the
committed table against the mirrored corpus, in CI, from committed data alone.

THE REVIEWER IS A HUMAN, OR AN AGENT WHOSE QUOTE IS MATCHED WORD FOR WORD (operator decision
2026-10-30, ADR 0003's amendment). Every row that predates that decision was read by a human
and records no quote, which is why a row's absence from QUOTE_CHECKS means "read by a human",
never "not reviewed". A row an agent reviewed is in QUOTE_CHECKS: the ORS section id and the
quotation the agent took from THIS CORPUS'S OWN MIRROR of it — never from memory, never from
another source — and `quote-in-the-cited-text` re-matches every quotation against the mirror
on every run, whitespace aside and nothing else, so a mirror that later changes fails loudly
instead of leaving a review record that no longer describes the text. The agent's review is
not weaker for being checkable; it is the only review in this file a machine can re-perform.
What it does NOT cover: an absence. "No section creates this body" is a finding about a
search, and CONTEXT.md's overriding rule lets a search stand for an absence only when it was
measured and is cited as such; a body no section was found for stays UNREVIEWED here (no key),
not `none: `, unless a quoted section shows the unit is internal structure of its parent.

AND THIS FILE IS THE REGISTRY FIELD'S SINGLE WRITER. `--apply` writes MAPPED and UNMAPPED
into `enabling_authority` on the registry rows, and nothing else writes that key — the same
arrangement `das_agency_number` has with link_budget_codes.py, for the reason #175 exists:
two writers of one field is drift that nothing reports. `--check` verifies the registry
against this table in both directions, so a row that acquired an authority some other way is
a failure rather than a fact.

WHAT THE FIELD MAY SAY is declared once, in catalog_agencies.AUTHORITY_FORMS — an ORS
citation, a constitutional article, an executive order, or (since #211) an uncodified
session law, or `none: ` and the reason there is none. This gate reads that grammar rather
than restating it, so a value cannot be legal in the table and illegal in the file the table
is written to. It checks the TABLE against the grammar; the registry's own contract check
(catalog_agencies.py --check) checks the ROWS. Same rule, two populations, and neither one
covers the other: an authority can be wrong in the table before it is ever written, and a row
can be hand-edited after.

AND SPELLED LIKE A CITATION IS NOT THE SAME AS NAMES SOMETHING. Three of the four forms are
RESOLVED here against a mirrored document — an ORS section, an executive order, and since
#196 a section of the Oregon Constitution — and the fourth, a session law, is CHECKED FOR
SHAPE ONLY, because this corpus mirrors no session laws for a citation to resolve against
(#211's own scope: expressible, not resolvable). The constitutional form was the last of the
resolved three taken on form alone, which mattered because an enabling authority is admitting
evidence: a class of it nothing could check meant `Or. Const. Art. XVII, sec. 99` admitted a
body, and Article XVII has two sections. `constitutional_resolver` is the half of that worth
reading — resolving to nothing is FIVE different findings about the Constitution and two more
about this corpus, and a reviewer has to be told which.

THE THREE STATES, and the reason MAPPED and UNMAPPED are both explicit. A row carrying
`ORS 576.062` has an authority; a row carrying `none: <reason>` was looked at and has none;
a row carrying no `enabling_authority` key at all has not been looked at — however many rows
that is today, which is `authority_census()`'s live count, printed by `catalog_agencies.py
--check` on every run rather than fixed here. Absence is never a claim that a body has no
enabling authority.

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
import pathlib
import re
import sys
import tempfile

import yaml

from catalog_agencies import (ENABLING_AUTHORITY_NAME, NAME_BASIS_KEY, NO_AUTHORITY,
                              UNVERIFIED_OAR_TITLE, authority_census, classify_authority,
                              name_census, no_authority_value, relation_entries)
from check_rule_ledger import RuleLedger
from repo_lib import REPO_ROOT

# A quotation shorter than this shows nothing about the section it is attached to.
MIN_QUOTE_WORDS = 4
# The relation source an ORS section's own statement of where a body sits is recorded under.
STATUTE_SOURCE = "statute"

CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"
STATUTES = REPO_ROOT / "statutes"
EXECUTIVE_ORDERS = REPO_ROOT / "executive-orders"
CONSTITUTION = REPO_ROOT / "constitution"
REVIEW_SHEET = REPO_ROOT / "_meta/catalog/enabling-authority-review.yml"

# EVERY RULE THIS MODULE CAN REPORT (#211/#220 adopt `check_rule_ledger` here — this module
# was the twelfth #319 missed counting: a `Problem` namedtuple with a `rule` string field and
# no declared table, no AST scan, and no record of which rules a run actually watched fire.
# Widening `audit_statutory_names` to dispatch across four forms instead of one is exactly
# the kind of change a hand-rolled rule name can go stale under silently — this table and the
# scan below are what `catalog_agencies.CHECK_RULES` already keeps honest one module over.
CHECK_RULES = (
    "slug-in-registry", "not-both-tables", "authority-form", "authority-resolves",
    "unmapped-has-reason", "unmapped-is-not-an-authority",
    "statutory-name-slug-in-registry", "statutory-name-is-a-name",
    "statutory-name-has-an-authority", "statutory-name-in-the-cited-text",
    "registry-agrees", "statutory-name-agrees",
    # an agent's quote-check (ADR 0003's amendment, operator decision 2026-10-30)
    "quote-slug-in-registry", "quote-has-a-reviewed-row", "quote-is-a-quote",
    "quote-in-the-cited-text", "statutory-name-in-a-quote", "statute-placement-has-a-quote",
)

_LEDGER = RuleLedger(CHECK_RULES, __file__)


class Failure(_LEDGER.Failure):
    """One thing wrong with the reviewed tables or with the registry they write: which rule,
    which body, and what is wrong — recorded on construction by the shared ledger
    (catalog_agencies.Failure, same lesson), so no proof has to remember to say a rule fired
    and a rule name not in CHECK_RULES refuses construction rather than passing an unmarked
    write through.

    `.slug` IS `.site` UNDER ITS LONG-STANDING NAME HERE. The shared ledger's `Failure` is a
    `namedtuple("Failure", "rule site detail")` — one field name for every adopting module,
    because the ledger cannot know a domain's own word for "the thing this finding is
    about". This module's own word has been `slug` since before the ledger existed, and
    every construction call and every `.slug` read below stays exactly as written; only the
    definition changes."""
    __slots__ = ()

    @property
    def slug(self):
        return self.site

# ---------------------------------------------------------------- reviewed registry data
#
# slug -> authority. EVERY ROW HERE HAS BEEN READ against the cited text, by a human or, since
# the operator's decision of 2026-10-30, by an agent whose quotation of the section is in
# QUOTE_CHECKS below and is re-matched against the mirror word for word on every run. Add a
# row only after reading the section; a row that was pattern-matched and not read belongs in
# the review sheet, not here.
MAPPED: dict[str, str] = {
    # READ BY A HUMAN AGAINST THE CITED TEXT, 2026-08-22. Six tier-1 candidates from the
    # #169 review population, each displayed with its creation sentence before acceptance,
    # plus one authority the maintainer supplied. Nothing here was accepted on a tier alone.
    "commission-on-judicial-fitness-and-disability": "ORS 1.410",
    "department-of-consumer-and-business-services": "ORS 705.105",
    "mental-health-regulatory-agency": "ORS 675.160",
    "oregon-advocacy-commissions-office": "ORS 185.005",
    "public-records-advocate": "ORS 192.461",
    "state-board-of-tax-practitioners": "ORS 673.725",
    # Supplied by the maintainer and verified end to end: both constitutional editions and
    # ORS chapter 8 are mirrored, and the citation resolves. Art. VII (Original) sec. 17
    # creates the office; the ORS chapter codifies it. The constitutional citation is the
    # one recorded because it is what created the office.
    "district-attorneys-and-deputies": "Or. Const. Art. VII (Original), sec. 17",
    # CONSTITUTIONAL OFFICES, read against the mirrored Constitution 2026-08-22. Each of
    # these vests power in, or elects, the body BY NAME -- the whole reason #196 mirrored the
    # document. Before it existed `--check` reported them as "form checked, not resolved".
    "office-of-the-governor": "Or. Const. Art. V, sec. 1",
    "legislative-assembly": "Or. Const. Art. IV, sec. 1",
    "secretary-of-state": "Or. Const. Art. VI, sec. 1",
    # ORS 656.752(1): "The State Accident Insurance Fund Corporation is created for the
    # purpose of transacting workers' compensation insurance and reinsurance business."
    "saif-corporation": "ORS 656.752",
    # FROM CHAPTERS MIRRORED IN THIS COMMIT. Both bodies were unrecordable until now not
    # because their authority was unknown but because the chapter was absent (#210).
    # ORS 151.213(1): "The Oregon Public Defense Commission is established in the executive
    # branch of state government." NOT 151.211, which the operator's range began at and which
    # is "Definitions for ORS 151.211 to ..." -- the range is right, its first section is not
    # the creating one. SB 337 (2023) renamed this body; the registry still calls it the
    # Office of Public Defense Services, which is #168's question, not this one.
    "office-of-public-defense-services": "ORS 151.213",
    # ORS 396.305(1): "The Oregon Military Department is established."
    "oregon-military-department": "ORS 396.305",
    # BATCH 1a, accepted 2026-08-22 as ONE decision. ORS 576.062 "Establishment of commodity
    # commissions" creates all nineteen BY NAME in a single enumerated list: 19 enumerated,
    # 19 in the registry, zero discrepancies. Reviewing them individually would be reviewing
    # one sentence nineteen times.
    "department-of-agriculture-oregon-albacore-commission": "ORS 576.062",
    "department-of-agriculture-oregon-blueberry-commission": "ORS 576.062",
    "department-of-agriculture-oregon-clover-seed-commission": "ORS 576.062",
    "department-of-agriculture-oregon-dairy-products-commission": "ORS 576.062",
    "department-of-agriculture-oregon-dungeness-crab-commission": "ORS 576.062",
    "department-of-agriculture-oregon-fine-fescue-commission": "ORS 576.062",
    "department-of-agriculture-oregon-hazelnut-commission": "ORS 576.062",
    "department-of-agriculture-oregon-hop-commission": "ORS 576.062",
    "department-of-agriculture-oregon-mint-commission": "ORS 576.062",
    "department-of-agriculture-oregon-potato-commission": "ORS 576.062",
    "department-of-agriculture-oregon-processed-vegetable-commission": "ORS 576.062",
    "department-of-agriculture-oregon-raspberry-and-blackberry-commission": "ORS 576.062",
    "department-of-agriculture-oregon-ryegrass-growers-seed-commission": "ORS 576.062",
    "department-of-agriculture-oregon-salmon-commission": "ORS 576.062",
    "department-of-agriculture-oregon-sheep-commission": "ORS 576.062",
    "department-of-agriculture-oregon-strawberry-commission": "ORS 576.062",
    "department-of-agriculture-oregon-sweet-cherry-commission": "ORS 576.062",
    "department-of-agriculture-oregon-tall-fescue-commission": "ORS 576.062",
    "department-of-agriculture-oregon-trawl-commission": "ORS 576.062",
    # BATCH 1b, accepted 2026-08-22. Each displayed with its creation sentence.
    # 684.130, 681.400 and 675.590 say "STATE Board of ..." where the registry says
    # "Board of ...". The authority is not in doubt; the NAME difference is #168's.
    "appraiser-certification-and-licensure-board": "ORS 674.305",
    "board-of-chiropractic-examiners": "ORS 684.130",
    "board-of-examiners-for-speech-language-pathology-and-audiology": "ORS 681.400",
    "board-of-licensed-social-workers": "ORS 675.590",
    "board-of-medical-imaging": "ORS 688.545",
    "board-of-parole-and-post-prison-supervision": "ORS 144.005",
    "bureau-of-labor-and-industries": "ORS 651.020",
    "citizens-initiative-review-commission": "ORS 250.137",
    "commission-for-the-blind": "ORS 346.120",
    "construction-contractors-board": "ORS 701.205",
    "department-of-administrative-services": "ORS 184.305",
    # BATCH 2, accepted 2026-08-21 after the maintainer read all thirty against the cited
    # text. Every row is tier 1 — the ORS catchline's SUBJECT is this body's name — and each
    # was displayed with its creation sentence before acceptance, the same bar as batch 1.
    "department-of-agriculture": "ORS 561.010",
    "department-of-agriculture-oregon-beef-council": "ORS 577.210",
    "department-of-agriculture-oregon-invasive-species-council": "ORS 570.770",
    "department-of-agriculture-oregon-wheat-commission": "ORS 578.030",
    "department-of-consumer-and-business-services-workers-compensation-board": "ORS 656.712",
    "department-of-corrections": "ORS 423.020",
    "department-of-energy": "ORS 469.030",
    "department-of-energy-energy-facility-siting-council": "ORS 469.450",
    "department-of-environmental-quality": "ORS 468.030",
    "department-of-fish-and-wildlife": "ORS 496.080",
    "department-of-human-services": "ORS 409.010",
    "department-of-human-services-home-care-commission": "ORS 410.602",
    "department-of-revenue": "ORS 305.025",
    "department-of-state-lands": "ORS 273.041",
    "department-of-state-police-oregon-state-athletic-commission": "ORS 463.113",
    "department-of-transportation": "ORS 184.615",
    "department-of-veterans-affairs": "ORS 406.005",
    "eastern-oregon-border-economic-development-board": "ORS 284.776",
    "employment-department": "ORS 657.601",
    "higher-education-coordinating-commission": "ORS 350.050",
    "higher-education-coordinating-commission-office-of-student-access-and-completion": "ORS 348.511",
    "land-use-board-of-appeals": "ORS 197.810",
    "mental-health-regulatory-agency-oregon-board-of-licensed-professional-counselors-and-therapists": "ORS 675.775",
    "mental-health-regulatory-agency-oregon-board-of-psychology": "ORS 675.100",
    "mortuary-and-cemetery-board": "ORS 692.300",
    "occupational-therapy-licensing-board": "ORS 675.310",
    "oregon-529-savings-board": "ORS 178.310",
    "oregon-board-of-accountancy": "ORS 673.410",
    "oregon-board-of-naturopathic-medicine": "ORS 685.160",
    "oregon-business-development-department": "ORS 285A.070",
    # BATCH 3, accepted 2026-08-21. The last thirty tier-1 candidates — the ORS
    # catchline's SUBJECT is the body's name — each read against the cited text.
    "oregon-criminal-justice-commission": "ORS 137.654",
    "oregon-department-of-aviation": "ORS 835.100",
    "oregon-department-of-education": "ORS 326.111",
    "oregon-department-of-education-fair-dismissal-appeals-board": "ORS 342.930",
    "oregon-department-of-education-youth-development-division": "ORS 417.852",
    "oregon-facilities-authority": "ORS 289.100",
    "oregon-film-and-video-office": "ORS 284.305",
    "oregon-forest-resources-institute": "ORS 526.610",
    "oregon-government-ethics-commission": "ORS 244.250",
    "oregon-health-authority-health-licensing-office-behavior-analysis-regulatory-board": "ORS 676.806",
    "oregon-health-authority-health-licensing-office-board-of-certified-advanced-estheticians": "ORS 676.650",
    "oregon-health-authority-health-licensing-office-board-of-cosmetology": "ORS 690.155",
    "oregon-health-authority-health-licensing-office-board-of-direct-entry-midwifery": "ORS 687.470",
    # #351, read 2026-09-10: ORS 691.485(1) "There is established, within the Health
    # Licensing Office, the Board of Licensed Dietitians to advise the office with regard
    # to the regulation of dietitians." Tier 1, catchline-subject -- surfaced by
    # regenerating the review sheet, unrelated pre-existing drift found while closing
    # #211/#220 (that PR reverted the regeneration to keep this candidate out of its diff).
    "oregon-health-authority-health-licensing-office-board-of-licensed-dietitians": "ORS 691.485",
    "oregon-health-authority-health-licensing-office-environmental-health-registration-board": "ORS 700.210",
    "oregon-health-authority-health-licensing-office-long-term-care-administrators-board": "ORS 678.800",
    "oregon-health-authority-oregon-prescription-drug-program": "ORS 414.312",
    "oregon-health-authority-public-employees-benefit-board": "ORS 243.061",
    # #281, read 2026-08-28. TIER 3, not tier 1: ORS 571.400 to 571.501 is the commission's
    # whole standalone act (definitions, purposes, department duties, powers, budget, even
    # abolishment), and none of its 37 catchlines puts "Oregon Hemp Commission" in CREATE's
    # subject position the way ORS 577.210 puts "Oregon Beef Council" in one — this act never
    # writes "there hereby is created". 571.406 is where the body is CONSTITUTED rather than
    # merely described, the same question tier 3 asks of ORS 677.235 for the Oregon Medical
    # Board: "In the same manner as that provided in ORS 576.206, the Director of Agriculture
    # shall appoint seven temporary members to the Oregon Hemp Commission" — before this
    # section the commission has no members and cannot act; subsection (6) of the same
    # section then appoints its permanent commissioners the same way. NOT ORS 576.062: 571.435
    # names "the Oregon Hemp Commission" separately from "commodity commissions created under
    # ORS 576.051 to 576.455", so the enumerated-list citation the other 21 Department of
    # Agriculture commissions carry does not reach this body — the issue's own suggested
    # citation was wrong on this point and is corrected here.
    "oregon-hemp-commission": "ORS 571.406",
    "oregon-investment-council": "ORS 293.706",
    "oregon-patient-safety-commission": "ORS 442.820",
    "oregon-racing-commission": "ORS 462.210",
    "oregon-state-marine-board": "ORS 830.105",
    "oregon-tourism-commission": "ORS 284.107",
    "oregon-utility-notification-center": "ORS 757.547",
    "oregon-watershed-enhancement-board": "ORS 541.900",
    "oregon-wine-board": "ORS 576.856",
    "psychiatric-security-review-board": "ORS 161.385",
    "public-utility-commission": "ORS 756.014",
    "public-utility-commission-oregon-board-of-maritime-pilots": "ORS 776.105",
    "real-estate-agency": "ORS 696.375",
    "water-resources-department": "ORS 536.039",
    # TIER 2, the ten accepted of eighteen. Tier 2 only means the catchline CONTAINS the
    # name, so it is not a bar by itself — each of these was accepted because its text
    # plainly CREATES the body ("is established", "there is created"). The other eight
    # were rejected or held; see the PR. That 10-of-18 split is why tier 2 is not a verdict.
    "board-of-nursing": "ORS 678.140",
    "department-of-state-police": "ORS 181A.015",
    "legislative-administration-committee": "ORS 173.710",
    "legislative-policy-and-research-committee": "ORS 173.605",
    "long-term-care-ombudsman": "ORS 441.403",
    "oregon-health-authority": "ORS 413.032",
    "oregon-health-authority-health-policy-and-analytics": "ORS 442.011",
    "oregon-housing-and-community-services-department": "ORS 456.555",
    "travel-information-council": "ORS 377.835",
    "veterinary-medical-examining-board": "ORS 686.210",
    # A SECOND INSTANCE OF THE SESSION-LAW FORM, read and verified 2026-08-22 — NOT #211's
    # own worked case (that is `legislative-fiscal-officer`, below); this one is a separate,
    # independently-supplied authority of the same shape. All seven sections of ORS
    # 173.800-173.855 are mirrored, and NONE creates the office: they cover appointment,
    # staffing, duties, funds, federal-program status, department assistance and
    # confidentiality — codifying the office's OPERATION, never its creation. The one hit for
    # creating language in the range is a false positive naming a different body entirely
    # ("173.800: '...if no Interim Committee on Revenue is created, means the Speaker of the
    # House...'" — an interim COMMITTEE, not the Office). The creating act is uncodified:
    # Oregon Laws 1975, chapter 789 (Senate Bill 1024), which separated tax research and
    # revenue forecasting from the Legislative Fiscal Office to create a standalone,
    # nonpartisan service agency. `statutes/ors-173.800.md` itself carries the Legislative
    # Counsel's own bracket citation of that act, `[1975 c.789 §1]`, at the very section
    # (173.800(2)) that names the appointing authority — corroborating the act without being
    # the creating sentence, which is exactly the distinction this form exists to record.
    "legislative-revenue-office": "Oregon Laws 1975, chapter 789",
    # #211's OWN WORKED CASE — the "case that found it" section of the issue itself, read and
    # verified 2026-08-22. Oregon Laws 1959, chapter 70 established the position of
    # Legislative Fiscal Officer and its nonpartisan staff; it is codified at ORS
    # 173.410-173.465, all five mirrored sections of which are read in the issue and NONE
    # creates the office: 173.410 defines "appointing authority", 173.420 states duties,
    # 173.450 covers staff employment, and 173.465 creates the FUND, not the office (173.430,
    # .440 and .460 are not mirrored — #210). The codification describes an office it assumes
    # already exists; the creating act is the session law. This is also one of the three
    # bodies #169 names as blocked on this form's absence, and #169's own review population
    # should be read as updated for it now that the form exists.
    "legislative-fiscal-officer": "Oregon Laws 1959, chapter 70",
    # #169's REMAINING POPULATION, read and verified 2026-08-30 against the mirrored text.
    # Each sat in `no_candidate` or as an unread tier-2 candidate; none was accepted on a
    # tier alone.
    #
    # ORS 172.100(1): "The State of Oregon shall establish a Commission on Indian Services
    # for the purposes of improving services to American Indians in this state..." The
    # matcher never proposed this one — the catchline is "Legislative policy", which names
    # no body, and the creating sentence sits inside the section's text instead. This is NOT
    # the same shape as ORS 576.062's enumerated commissions ("The following commodity
    # commissions ARE ESTABLISHED as state commissions") — that is present-tense operative
    # establishment, where 172.100 is a declaration of legislative policy directing that the
    # state "shall establish" one. The rest of the chapter (ORS 172.110 members, ORS 172.120
    # duties) has no closer candidate, so this is the section that constitutes the
    # commission, but the citation records that statute DIRECTS the establishment, not that
    # it performs one. The registry's name carries a "Legislative" prefix the statute does
    # not use; that is #168's question, not this one.
    "legislative-commission-on-indian-services": "ORS 172.100",
    # legislative-counsel-office was entered here as ORS 173.111 and reverted (code review,
    # 2026-08-31): the section's OPERATIVE text establishes only the Legislative Counsel
    # COMMITTEE ("The Legislative Counsel Committee is established as a joint committee of
    # the Legislative Assembly. The Legislative Counsel Committee shall select a Legislative
    # Counsel to serve as its executive officer."). "office of Legislative Counsel
    # established" is the section's CATCHLINE, which ORS 174.540 — mirrored in this repo —
    # states is not part of the law: "Title heads, chapter heads, division heads, section and
    # subsection heads or titles and explanatory notes ... do not constitute any part of the
    # law." Nothing else in the mirrored statutes uses that phrase outside this catchline. Not
    # re-guessed at a different citation — reverted to could-not-check, still `no_candidate`
    # in the review sheet, exactly as it stood before this entry.
    #
    # ORS 173.900(2): "The Legislative Equity Office is established as a nonpartisan office
    # of the Legislative Assembly that is independent of any other nonpartisan office."
    # Tier 2 in the review sheet (catchline CONTAINS the name, not merely names it as
    # subject) — read directly against the text rather than accepted on the tier: subsection
    # (1) creates a different body (the Joint Committee on Conduct) in the same section, and
    # subsection (2) is what creates this one.
    "legislative-equity-office": "ORS 173.900",
    # #212 — ORS 401.052(1), read and verified 2026-08-30: "The Oregon Department of
    # Emergency Management is established." [Formerly 401.257; 2021 c.539 §2; 2025 c.229
    # §1] — the 2021 bracket citation is HB 2927 (Oregon Laws 2021, chapter 539), which spun
    # the body out of the Oregon Military Department as a standalone department. Read, but
    # DELIBERATELY NOT ENTERED HERE: the registry carries this body as one row
    # (`oregon-military-department-office-of-emergency-management`, #212 — two rows for one
    # body that moved was rejected, not two bodies), and that row's only relation is the
    # scraped, stale OAR-index placement under the Military Department ORS 401.052 itself
    # abolished. Recording this citation as that row's `enabling_authority` would derive
    # `administered_by oregon-military-department` on that relation
    # (`src/derive_relation_kinds.py`) — a citation-backed claim of exactly the attachment
    # this statute ends. ADR 0004 has no third kind for a body an index page still places
    # under a parent statute has removed it from ("whether that is a third relation or an
    # absence of one is not decided here"), so entering it here would derive a wrong answer
    # rather than leave a true `undetermined` one. The citation is recorded as verified prose
    # on the row's own `curator_note` instead, until that gap is closed.
    #
    # #354 — SB 762 (2021) made the State Fire Marshal's office an independent agency,
    # operative 2023-07-01. NOT HB 2927, which this comment asserted until 2026-09-12: that act
    # is the Department of Emergency Management's, and the attribution was inherited from the
    # sibling row above rather than read for this body. What WAS read and verified 2026-09-02
    # is the codified text: ORS 476.020(1), read and verified
    # 2026-09-02: "The Department of the State Fire Marshal is established. The department is
    # under the supervision and control of the State Fire Marshal." Read, but DELIBERATELY NOT
    # ENTERED HERE, for exactly the reason given above for #212's row (see that comment: one
    # row not two, and recording the citation here would derive an `administered_by` relation
    # onto a link this statute ends). Recorded as verified prose on this row's
    # (`department-of-state-police-office-of-state-fire-marshal`) own `curator_note` instead.
    #
    # #354 — HB 3073 (2021 regular session), read and verified 2026-09-02, made the Early
    # Learning Division an independent agency, the Department of Early Learning and Care:
    # ORS 326.430(1)(a), "The Department of Early Learning and Care is established." Read, but
    # DELIBERATELY NOT ENTERED HERE for the identical reason given above for #212's row.
    # Recorded as verified prose on this row's
    # (`oregon-department-of-education-early-learning-division`) own `curator_note` instead.
    #
    # OAR CHAPTERS REGISTERED 2026-10-17 (ERF PR #452): bodies OARD lists a chapter for and
    # the registry had no row for. Each section was read in the mirrored statutes by the
    # agent that added the row, not yet by the maintainer; each creating sentence follows.
    # ORS 243.862(1): "There is established in the Oregon Health Authority an Oregon
    # Educators Benefit Board".
    "oregon-health-authority-oregon-educators-benefit-board": "ORS 243.862",
    # ORS 676.780(1): "There is established within the Health Licensing Office the State Board
    # of Sign Language Interpreters".
    "oregon-health-authority-health-licensing-office-state-board-of-sign-language-interpreters":
        "ORS 676.780",
    # ORS 243.812(1): "The Commission on Statewide Law Enforcement Standards of Conduct and
    # Discipline is established".
    "commission-on-statewide-law-enforcement-standards-of-conduct-and-discipline":
        "ORS 243.812",
    # ORS 822.250(1): "The State Board of Towing is established within the Department of
    # Transportation."
    "state-board-of-towing": "ORS 822.250",
    # ORS 646A.693(1): "The Prescription Drug Affordability Board is established in the
    # Department of Consumer and Business Services".
    "department-of-consumer-and-business-services-prescription-drug-affordability-board":
        "ORS 646A.693",
    # ORS 541.861(1): "The Environmental Restoration Council is established in the Oregon
    # Watershed Enhancement Board."
    "oregon-watershed-enhancement-board-environmental-restoration-council": "ORS 541.861",
    # AGENT QUOTE-CHECKED, 2026-10-30 (operator decision; ADR 0003's amendment). Bodies that were
    # "not looked at yet", each now the section a quotation in QUOTE_CHECKS (below) shows
    # creating or constituting it, matched word for word against the mirror by --check.
    # 12 of them are the tier-3 case this file's docstring describes: the section has no
    # creation verb and CONSTITUTES the body ("shall operate as a semi-independent state
    # agency subject to ORS 182.456 to 182.472", "consists of nine members appointed by the
    # Governor"), and the quotation is what a reader weighs. ERB's section "continues" the
    # Civil Service Commission "as a board ... to be known as" it, and the Department of
    # Justice's "constitutes" it; the Columbia River Gorge Commission is created by the
    # interstate compact ORS 196.150 ratifies.
    #
    # NOT RECORDED, AND WHY (a body no creating section was found for keeps no key at all):
    #   the State Fire Marshal, Early Learning and Emergency Management -- ORS 476.020,
    #   326.430 and 401.052 establish each as a standalone department, and recording that as
    #   its authority would derive `administered_by` against the parent the statute ended
    #   (CONTEXT.md, Undetermined; ADR 0004's amendment of this date);
    #   the Oregon State Lottery (ORS 461.100 creates the Oregon State Lottery COMMISSION),
    #   the Public Employees Retirement System (ORS 238.600 establishes the SYSTEM, not the
    #   board that administers it), the Legislative Counsel Office (ORS 173.111 establishes the
    #   Legislative Counsel COMMITTEE), the State Library (ORS 357.021 creates its BOARD),
    #   the Department of Geology and Mineral Industries and the Department of Public Safety
    #   Standards and Training (the sections found describe the governing board, not the
    #   department), the South Slough reserve (ORS 273.554 creates its Management
    #   Commission) and the Oregon State Treasury and Judicial Department (constitutional
    #   offices no mirrored section names as a body);
    #   and the Chief Education Office, the Economic Recovery Review Council, Office of
    #   Training, Investigations and Safety, Drug Treatment and Recovery Services and
    #   Vocational Rehabilitation Services, for which no mirrored section was found to
    #   create the body. "No section found" is a finding about a search, not an absence.

    "board-of-examiners-for-engineering-and-land-surveying": "ORS 672.240",
    "board-of-geologist-examiners": "ORS 672.615",
    "board-of-massage-therapists": "ORS 687.115",
    "board-of-optometry": "ORS 683.250",
    "board-of-pharmacy": "ORS 689.115",
    "columbia-river-gorge-commission": "ORS 196.150",
    "department-of-forestry": "ORS 526.008",
    "department-of-justice": "ORS 180.210",
    "employment-relations-board": "ORS 240.060",
    "land-conservation-and-development-department": "ORS 197.075",
    "landscape-architect-board": "ORS 671.459",
    "landscape-contractors-board": "ORS 671.630",
    "oregon-board-of-dentistry": "ORS 679.230",
    "oregon-board-of-physical-therapy": "ORS 688.160",
    "oregon-health-authority-health-licensing-office": "ORS 676.560",
    "oregon-liquor-control-commission": "ORS 471.705",
    "oregon-medical-board": "ORS 677.235",
    "oregon-youth-authority": "ORS 420A.010",
    "parks-and-recreation-department": "ORS 390.111",
    "southern-oregon-university": "ORS 352.002",
    "state-board-of-architect-examiners": "ORS 671.120",
    "teacher-standards-and-practices-commission": "ORS 342.350",
}

# slug -> why this body has no enabling authority TO RECORD. A DECISION with a stated reason,
# never a blank, and never a citation: a body whose authority is a constitutional article
# HAS one, and belongs in MAPPED above. That is what this example used to be — the Secretary
# of State, filed here as "constitutional office, so no ORS section can be cited", which was
# true of a field that could only hold statutes and became a false absence the day the field
# started accepting `Or. Const. Art. VI, sec. 1` (#170). The commonest legitimate reason is
# ADR 0004's: a `part_of` unit has nothing separate to enable.
UNMAPPED: dict[str, str] = {
    # THE 33 SUB-UNITS REVIEWED 2026-09-12 (#222). Every one is a division or office whose
    # slug extends its parent's and which carries an OAR chapter but no separate
    # constitution. The operator read them as a set and found nothing separately
    # constitutes any of them -- ADR 0004's *part of*. This is a REVIEWED ABSENCE, which
    # derive_relation_kinds.py turns into `kind: part_of`; it is NOT the matcher's silence,
    # which stays `undetermined` and is a statement about the matcher.
    #
    # THREE SIBLINGS OF THESE ARE DELIBERATELY ABSENT. The State Fire Marshal, Early
    # Learning and Emergency Management were each removed from their parent and made
    # their own agency; the OAR chapter registration simply lags. They are separately
    # constituted, so a reviewed ABSENCE would be the wrong finding for them -- see
    # link_budget_codes.REORGANIZED, which already carries their citations.
    "department-of-administrative-services-chief-financial-office":
        "Part of the Department of Administrative Services (ADR 0004): reviewed 2026-09-12 by "
        "@morficflux, who found nothing separately constitutes it, so there is no enabling "
        "authority to record.",
    "department-of-administrative-services-chief-human-resources-office":
        "Part of the Department of Administrative Services (ADR 0004): reviewed 2026-09-12 by "
        "@morficflux, who found nothing separately constitutes it, so there is no enabling "
        "authority to record.",
    "department-of-administrative-services-office-of-the-state-chief-information-officer":
        "Part of the Department of Administrative Services (ADR 0004): reviewed 2026-09-12 by "
        "@morficflux, who found nothing separately constitutes it, so there is no enabling "
        "authority to record.",
    "department-of-agriculture-oregon-alfalfa-seed-commission":
        "Part of the Department of Agriculture (ADR 0004): reviewed 2026-09-12 by "
        "@morficflux, who found nothing separately constitutes it, so there is no enabling "
        "authority to record.",
    "department-of-consumer-and-business-services-building-codes-division":
        "Part of the Department of Consumer and Business Services (ADR 0004): reviewed "
        "2026-09-12 by @morficflux, who found nothing separately constitutes it, so there is "
        "no enabling authority to record.",
    "department-of-consumer-and-business-services-director-s-office":
        "Part of the Department of Consumer and Business Services (ADR 0004): reviewed "
        "2026-09-12 by @morficflux, who found nothing separately constitutes it, so there is "
        "no enabling authority to record.",
    "department-of-consumer-and-business-services-finance-and-securities-regulation":
        "Part of the Department of Consumer and Business Services (ADR 0004): reviewed "
        "2026-09-12 by @morficflux, who found nothing separately constitutes it, so there is "
        "no enabling authority to record.",
    "department-of-consumer-and-business-services-health-insurance-marketplace":
        "Part of the Department of Consumer and Business Services (ADR 0004): reviewed "
        "2026-09-12 by @morficflux, who found nothing separately constitutes it, so there is "
        "no enabling authority to record.",
    "department-of-consumer-and-business-services-insurance-regulation":
        "Part of the Department of Consumer and Business Services (ADR 0004): reviewed "
        "2026-09-12 by @morficflux, who found nothing separately constitutes it, so there is "
        "no enabling authority to record.",
    "department-of-consumer-and-business-services-oregon-occupational-safety-and-health-division":
        "Part of the Department of Consumer and Business Services (ADR 0004): reviewed "
        "2026-09-12 by @morficflux, who found nothing separately constitutes it, so there is "
        "no enabling authority to record.",
    "department-of-consumer-and-business-services-workers-compensation-division":
        "Part of the Department of Consumer and Business Services (ADR 0004): reviewed "
        "2026-09-12 by @morficflux, who found nothing separately constitutes it, so there is "
        "no enabling authority to record.",
    "department-of-human-services-aging-and-people-with-disabilities-and-developmental-disabilities":
        "Part of the Department of Human Services (ADR 0004): reviewed 2026-09-12 by "
        "@morficflux, who found nothing separately constitutes it, so there is no enabling "
        "authority to record.",
    "department-of-human-services-child-welfare-programs":
        "Part of the Department of Human Services (ADR 0004): reviewed 2026-09-12 by "
        "@morficflux, who found nothing separately constitutes it, so there is no enabling "
        "authority to record.",
    "department-of-human-services-self-sufficiency-programs":
        "Part of the Department of Human Services (ADR 0004): reviewed 2026-09-12 by "
        "@morficflux, who found nothing separately constitutes it, so there is no enabling "
        "authority to record.",
    "department-of-transportation-driver-and-motor-vehicle-services-division":
        "Part of the Department of Transportation (ADR 0004): reviewed 2026-09-12 by "
        "@morficflux, who found nothing separately constitutes it, so there is no enabling "
        "authority to record.",
    "department-of-transportation-highway-division":
        "Part of the Department of Transportation (ADR 0004): reviewed 2026-09-12 by "
        "@morficflux, who found nothing separately constitutes it, so there is no enabling "
        "authority to record.",
    "department-of-transportation-motor-carrier-transportation-division":
        "Part of the Department of Transportation (ADR 0004): reviewed 2026-09-12 by "
        "@morficflux, who found nothing separately constitutes it, so there is no enabling "
        "authority to record.",
    "department-of-transportation-public-transit-division":
        "Part of the Department of Transportation (ADR 0004): reviewed 2026-09-12 by "
        "@morficflux, who found nothing separately constitutes it, so there is no enabling "
        "authority to record.",
    "department-of-transportation-rail-division":
        "Part of the Department of Transportation (ADR 0004): reviewed 2026-09-12 by "
        "@morficflux, who found nothing separately constitutes it, so there is no enabling "
        "authority to record.",
    "department-of-transportation-transportation-safety-division":
        "Part of the Department of Transportation (ADR 0004): reviewed 2026-09-12 by "
        "@morficflux, who found nothing separately constitutes it, so there is no enabling "
        "authority to record.",
    "higher-education-coordinating-commission-office-of-community-colleges-and-workforce-development":
        "Part of the Higher Education Coordinating Commission (ADR 0004): reviewed 2026-09-12 "
        "by @morficflux, who found nothing separately constitutes it, so there is no enabling "
        "authority to record.",
    "higher-education-coordinating-commission-office-of-degree-authorization":
        "Part of the Higher Education Coordinating Commission (ADR 0004): reviewed 2026-09-12 "
        "by @morficflux, who found nothing separately constitutes it, so there is no enabling "
        "authority to record.",
    "oregon-health-authority-equity-and-inclusion-division":
        "Part of the Oregon Health Authority (ADR 0004): reviewed 2026-09-12 by @morficflux, "
        "who found nothing separately constitutes it, so there is no enabling authority to "
        "record.",
    "oregon-health-authority-health-systems-division-addiction-services":
        "Part of the Oregon Health Authority (ADR 0004): reviewed 2026-09-12 by @morficflux, "
        "who found nothing separately constitutes it, so there is no enabling authority to "
        "record.",
    "oregon-health-authority-health-systems-division-behavioral-health-services":
        "Part of the Oregon Health Authority (ADR 0004): reviewed 2026-09-12 by @morficflux, "
        "who found nothing separately constitutes it, so there is no enabling authority to "
        "record.",
    "oregon-health-authority-health-systems-division-medical-assistance-programs":
        "Part of the Oregon Health Authority (ADR 0004): reviewed 2026-09-12 by @morficflux, "
        "who found nothing separately constitutes it, so there is no enabling authority to "
        "record.",
    "oregon-health-authority-public-health-division":
        "Part of the Oregon Health Authority (ADR 0004): reviewed 2026-09-12 by @morficflux, "
        "who found nothing separately constitutes it, so there is no enabling authority to "
        "record.",
    "oregon-watershed-enhancement-board-oregon-agricultural-heritage-program":
        "Part of the Oregon Watershed Enhancement Board (ADR 0004): reviewed 2026-09-12 by "
        "@morficflux, who found nothing separately constitutes it, so there is no enabling "
        "authority to record.",
    "secretary-of-state-archives-division":
        "Part of the Secretary of State (ADR 0004): reviewed 2026-09-12 by @morficflux, who "
        "found nothing separately constitutes it, so there is no enabling authority to "
        "record.",
    "secretary-of-state-audits-division":
        "Part of the Secretary of State (ADR 0004): reviewed 2026-09-12 by @morficflux, who "
        "found nothing separately constitutes it, so there is no enabling authority to "
        "record.",
    "secretary-of-state-business-services-division":
        "Part of the Secretary of State (ADR 0004): reviewed 2026-09-12 by @morficflux, who "
        "found nothing separately constitutes it, so there is no enabling authority to "
        "record.",
    "secretary-of-state-corporation-division":
        "Part of the Secretary of State (ADR 0004): reviewed 2026-09-12 by @morficflux, who "
        "found nothing separately constitutes it, so there is no enabling authority to "
        "record.",
    "secretary-of-state-elections-division":
        "Part of the Secretary of State (ADR 0004): reviewed 2026-09-12 by @morficflux, who "
        "found nothing separately constitutes it, so there is no enabling authority to "
        "record.",
    # e.g. "department-of-transportation-highway-division": "Part of the Department of
    #      Transportation (ADR 0004): nothing separately constitutes it, so there is no
    #      enabling authority to record.",
}

# ------------------------------------------------------- reviewed statutory names (#168)
#
# slug -> THE NAME THE BODY'S ENABLING AUTHORITY GIVES IT. ADR 0003 makes `name` the
# statutory name, and this is the only place one is decided: the authority is already
# reviewed in MAPPED above, and what that authority CALLS the body is the second question a
# reviewer answers while reading the same section. Two tables for one reading would be two
# places to be wrong.
#
# EVERY ROW HERE HAS BEEN READ AGAINST THE CITED TEXT (by a human, or by an agent whose
# quotation is in QUOTE_CHECKS), and unlike MAPPED it is also RESOLVED: `statutory-name-in-the-cited-text` below requires the recorded name to
# appear in the mirrored section MAPPED cites for that body. That is a weaker claim than "the
# statute names the body this" — a section can mention a name it does not confer — and it is
# the strongest claim a gate can make. What it rules out is the failure that matters: a name
# nobody read, sitting in `name` under a basis that says an authority gave it.
#
# THIS TABLE IS DELIBERATELY SMALL AND EXPECTED TO STAY THAT WAY FOR A WHILE. 114 rows carry a
# reviewed enabling authority and could have their names read off it (#279, re-measured for
# #281); five have been. The rest record `unverified-oar-title` and say so on every row, which
# is the honest state and the whole point of #168 — a registry that quietly promoted 190 OAR
# titles to statutory names would be 190 false statements about Oregon law, and one that
# promoted the 114 by pattern-matching would be an unknown number of them. A name that was
# matched and not read does not belong here, for the reason MAPPED gives about citations.
STATUTORY_NAMES: dict[str, str] = {
    # READ BY A HUMAN AGAINST THE CITED TEXT, 2026-08-22, EACH WITH THE SENTENCE IT WAS READ
    # OFF. The sentence is quoted here for the reason `--propose` quotes one into the review
    # sheet: it makes the next reader's job reading rather than research, and it is the only
    # thing that distinguishes a row somebody read from a row somebody agreed with. The first
    # three are the names MAPPED's own batch-1b note handed to #168 — "684.130, 681.400 and
    # 675.590 say `STATE Board of ...` where the registry says `Board of ...`. The authority
    # is not in doubt; the NAME difference is #168's."
    #
    # NOT CITABLE TEXT. These are whitespace-collapsed excerpts for review, the same caveat
    # `_quote()` carries; the mirrored section is the text.

    # ORS 684.130: "There is established the State Board of Chiropractic Examiners."
    "board-of-chiropractic-examiners": "State Board of Chiropractic Examiners",
    # ORS 681.400: "There is established a State Board of Examiners for Speech-Language
    # Pathology and Audiology."
    "board-of-examiners-for-speech-language-pathology-and-audiology":
        "State Board of Examiners for Speech-Language Pathology and Audiology",
    # ORS 675.590: "There is established a State Board of Licensed Social Workers."
    "board-of-licensed-social-workers": "State Board of Licensed Social Workers",
    # ORS 674.305: "The Appraiser Certification and Licensure Board is established."
    #
    # THE ONE WHERE THE STATUTE AND THE RULES INDEX AGREE, and it is here on purpose. This
    # row's `name` does not change and its BASIS does. Without it the registry would say, by
    # construction, that an established statutory name is one that DIFFERS from the OAR title
    # — and a reviewer who found the two agree would have nowhere to record that they had
    # looked. Agreement is a finding, not the absence of one.
    "appraiser-certification-and-licensure-board":
        "Appraiser Certification and Licensure Board",

    # #281, read 2026-08-28 against ORS 571.406, the tier-3 authority above: "the Director of
    # Agriculture shall appoint seven temporary members to the Oregon Hemp Commission."
    "oregon-hemp-commission": "Oregon Hemp Commission",

    # #220's OWN WORKED CASE, read 2026-08-30 against `Or. Const. Art. VI, sec. 1` — the
    # authority MAPPED already carried — and against the REST of Article VI beside it. Section
    # 1 creates the office by requiring an election and never once prints the words "Secretary
    # of State": "There shall be elected ... a Secretary, and Treasurer of State ...". Section
    # 2, "Duties of Secretary of State", prints them five times: "The Secretary of State shall
    # keep a fair record ... The Secretary of State shall be by virtue of holding the office,
    # Auditor of Public Accounts, and shall perform such other duties as shall be assigned to
    # the Secretary of State by law." Both sections are Article VI; the citation names the one
    # that CREATES the office (consistent with ADR 0004's own rule that a derived relation
    # cites the creating section and not the administering one), and the name it creates is
    # confirmed two sections later in the same article — which is why this gate resolves a
    # constitutional citation against its whole ARTICLE and not the one cited section alone
    # (#220's acceptance criterion; `constitution_article_texts()` below).
    "secretary-of-state": "Secretary of State",

    # AGENT QUOTE-CHECKED, 2026-10-30 (operator decision; ADR 0003's amendment). The name is
    # the one the cited section PRINTS, as it prints it (the typographic apostrophe included),
    # and the sentence that prints it is in QUOTE_CHECKS, matched word for word by --check.
    # Where this is not the OAR title the OAR title stays in `oar_name` and the former
    # spellings stay findable: the compound `Department of Agriculture, Oregon Albacore
    # Commission` of the OAR index becomes `Oregon Albacore Commission` (ORS 576.062 lists it
    # so), the Liquor Control Commission becomes the Liquor and Cannabis Commission, the
    # Office of Public Defense Services the Public Defense Commission, SAIF Corporation the
    # State Accident Insurance Fund Corporation, and ORS 468.030 names the Department of
    # Environmental Quality exactly as the index does.
    #
    # NOT PROMOTED, AND WHY: the Long Term Care Ombudsman (ORS 441.403 establishes "the office
    # of the Long Term Care Ombudsman", lower-case, and the registry's title is the officer's),
    # the Public Records Advocate (ORS 192.461 creates "the office of the Public Records
    # Advocate", likewise) and the Legislative Commission on Indian Services (the cited
    # ORS 172.100 is a policy declaration that does not print the name). Those keep
    # `unverified-oar-title`. The four constitutional offices were not part of this pass.
    "board-of-examiners-for-engineering-and-land-surveying": "State Board of Examiners for Engineering and Land Surveying",
    "board-of-geologist-examiners": "State Board of Geologist Examiners",
    "board-of-massage-therapists": "State Board of Massage Therapists",
    "board-of-medical-imaging": "Board of Medical Imaging",
    "board-of-nursing": "Oregon State Board of Nursing",
    "board-of-optometry": "Oregon Board of Optometry",
    "board-of-parole-and-post-prison-supervision": "State Board of Parole and Post-Prison Supervision",
    "board-of-pharmacy": "State Board of Pharmacy",
    "bureau-of-labor-and-industries": "Bureau of Labor and Industries",
    "citizens-initiative-review-commission": "Citizens’ Initiative Review Commission",
    "columbia-river-gorge-commission": "Columbia River Gorge Commission",
    "commission-for-the-blind": "Commission for the Blind",
    "commission-on-judicial-fitness-and-disability": "Commission on Judicial Fitness and Disability",
    "commission-on-statewide-law-enforcement-standards-of-conduct-and-discipline": "Commission on Statewide Law Enforcement Standards of Conduct and Discipline",
    "construction-contractors-board": "Construction Contractors Board",
    "department-of-administrative-services": "Oregon Department of Administrative Services",
    "department-of-agriculture": "State Department of Agriculture",
    "department-of-agriculture-oregon-albacore-commission": "Oregon Albacore Commission",
    "department-of-agriculture-oregon-beef-council": "Oregon Beef Council",
    "department-of-agriculture-oregon-blueberry-commission": "Oregon Blueberry Commission",
    "department-of-agriculture-oregon-clover-seed-commission": "Oregon Clover Seed Commission",
    "department-of-agriculture-oregon-dairy-products-commission": "Oregon Dairy Products Commission",
    "department-of-agriculture-oregon-dungeness-crab-commission": "Oregon Dungeness Crab Commission",
    "department-of-agriculture-oregon-fine-fescue-commission": "Oregon Fine Fescue Commission",
    "department-of-agriculture-oregon-hazelnut-commission": "Oregon Hazelnut Commission",
    "department-of-agriculture-oregon-hop-commission": "Oregon Hop Commission",
    "department-of-agriculture-oregon-invasive-species-council": "Invasive Species Council",
    "department-of-agriculture-oregon-mint-commission": "Oregon Mint Commission",
    "department-of-agriculture-oregon-potato-commission": "Oregon Potato Commission",
    "department-of-agriculture-oregon-processed-vegetable-commission": "Oregon Processed Vegetable Commission",
    "department-of-agriculture-oregon-raspberry-and-blackberry-commission": "Oregon Raspberry and Blackberry Commission",
    "department-of-agriculture-oregon-ryegrass-growers-seed-commission": "Oregon Ryegrass Growers Seed Commission",
    "department-of-agriculture-oregon-salmon-commission": "Oregon Salmon Commission",
    "department-of-agriculture-oregon-sheep-commission": "Oregon Sheep Commission",
    "department-of-agriculture-oregon-strawberry-commission": "Oregon Strawberry Commission",
    "department-of-agriculture-oregon-sweet-cherry-commission": "Oregon Sweet Cherry Commission",
    "department-of-agriculture-oregon-tall-fescue-commission": "Oregon Tall Fescue Commission",
    "department-of-agriculture-oregon-trawl-commission": "Oregon Trawl Commission",
    "department-of-agriculture-oregon-wheat-commission": "Oregon Wheat Commission",
    "department-of-consumer-and-business-services": "Department of Consumer and Business Services",
    "department-of-consumer-and-business-services-prescription-drug-affordability-board": "Prescription Drug Affordability Board",
    "department-of-consumer-and-business-services-workers-compensation-board": "Workers’ Compensation Board",
    "department-of-corrections": "Department of Corrections",
    "department-of-energy": "State Department of Energy",
    "department-of-energy-energy-facility-siting-council": "Energy Facility Siting Council",
    "department-of-environmental-quality": "Department of Environmental Quality",
    "department-of-fish-and-wildlife": "State Department of Fish and Wildlife",
    "department-of-forestry": "State Forestry Department",
    "department-of-human-services": "Department of Human Services",
    "department-of-human-services-home-care-commission": "Home Care Commission",
    "department-of-justice": "Department of Justice",
    "department-of-revenue": "Department of Revenue",
    "department-of-state-lands": "Department of State Lands",
    "department-of-state-police": "Department of State Police",
    "department-of-state-police-oregon-state-athletic-commission": "Oregon State Athletic Commission",
    "department-of-transportation": "Department of Transportation",
    "department-of-veterans-affairs": "Department of Veterans’ Affairs",
    "eastern-oregon-border-economic-development-board": "Eastern Oregon Border Economic Development Board",
    "employment-department": "Employment Department",
    "employment-relations-board": "Employment Relations Board",
    "higher-education-coordinating-commission": "Higher Education Coordinating Commission",
    "higher-education-coordinating-commission-office-of-student-access-and-completion": "Office of Student Access and Completion",
    "land-conservation-and-development-department": "Department of Land Conservation and Development",
    "land-use-board-of-appeals": "Land Use Board of Appeals",
    "landscape-architect-board": "State Landscape Architect Board",
    "landscape-contractors-board": "State Landscape Contractors Board",
    "legislative-administration-committee": "Legislative Administration Committee",
    "legislative-equity-office": "Legislative Equity Office",
    "legislative-policy-and-research-committee": "Legislative Policy and Research Committee",
    "mental-health-regulatory-agency": "Mental Health Regulatory Agency",
    "mental-health-regulatory-agency-oregon-board-of-licensed-professional-counselors-and-therapists": "Oregon Board of Licensed Professional Counselors and Therapists",
    "mental-health-regulatory-agency-oregon-board-of-psychology": "Oregon Board of Psychology",
    "mortuary-and-cemetery-board": "State Mortuary and Cemetery Board",
    "occupational-therapy-licensing-board": "Occupational Therapy Licensing Board",
    "office-of-public-defense-services": "Oregon Public Defense Commission",
    "oregon-529-savings-board": "Oregon 529 Savings Board",
    "oregon-advocacy-commissions-office": "Oregon Advocacy Commissions Office",
    "oregon-board-of-accountancy": "Oregon Board of Accountancy",
    "oregon-board-of-dentistry": "Oregon Board of Dentistry",
    "oregon-board-of-naturopathic-medicine": "Oregon Board of Naturopathic Medicine",
    "oregon-board-of-physical-therapy": "Oregon Board of Physical Therapy",
    "oregon-business-development-department": "Oregon Business Development Department",
    "oregon-criminal-justice-commission": "Oregon Criminal Justice Commission",
    "oregon-department-of-aviation": "Oregon Department of Aviation",
    "oregon-department-of-education": "Department of Education",
    "oregon-department-of-education-fair-dismissal-appeals-board": "Fair Dismissal Appeals Board",
    "oregon-department-of-education-youth-development-division": "Youth Development Division",
    "oregon-facilities-authority": "Oregon Facilities Authority",
    "oregon-film-and-video-office": "Oregon Film and Video Office",
    "oregon-forest-resources-institute": "Oregon Forest Resources Institute",
    "oregon-government-ethics-commission": "Oregon Government Ethics Commission",
    "oregon-health-authority": "Oregon Health Authority",
    "oregon-health-authority-health-licensing-office": "Health Licensing Office",
    "oregon-health-authority-health-licensing-office-behavior-analysis-regulatory-board": "Behavior Analysis Regulatory Board",
    "oregon-health-authority-health-licensing-office-board-of-certified-advanced-estheticians": "Board of Certified Advanced Estheticians",
    "oregon-health-authority-health-licensing-office-board-of-cosmetology": "Board of Cosmetology",
    "oregon-health-authority-health-licensing-office-board-of-direct-entry-midwifery": "State Board of Direct Entry Midwifery",
    "oregon-health-authority-health-licensing-office-board-of-licensed-dietitians": "Board of Licensed Dietitians",
    "oregon-health-authority-health-licensing-office-environmental-health-registration-board": "Environmental Health Registration Board",
    "oregon-health-authority-health-licensing-office-long-term-care-administrators-board": "Long Term Care Administrators Board",
    "oregon-health-authority-health-licensing-office-state-board-of-sign-language-interpreters": "State Board of Sign Language Interpreters",
    "oregon-health-authority-health-policy-and-analytics": "Health Policy and Analytics Division",
    "oregon-health-authority-oregon-educators-benefit-board": "Oregon Educators Benefit Board",
    "oregon-health-authority-oregon-prescription-drug-program": "Oregon Prescription Drug Program",
    "oregon-health-authority-public-employees-benefit-board": "Public Employees’ Benefit Board",
    "oregon-housing-and-community-services-department": "Housing and Community Services Department",
    "oregon-investment-council": "Oregon Investment Council",
    "oregon-liquor-control-commission": "Oregon Liquor and Cannabis Commission",
    "oregon-medical-board": "Oregon Medical Board",
    "oregon-military-department": "Oregon Military Department",
    "oregon-patient-safety-commission": "Oregon Patient Safety Commission",
    "oregon-racing-commission": "Oregon Racing Commission",
    "oregon-state-marine-board": "State Marine Board",
    "oregon-tourism-commission": "Oregon Tourism Commission",
    "oregon-utility-notification-center": "Oregon Utility Notification Center",
    "oregon-watershed-enhancement-board": "Oregon Watershed Enhancement Board",
    "oregon-watershed-enhancement-board-environmental-restoration-council": "Environmental Restoration Council",
    "oregon-wine-board": "Oregon Wine Board",
    "oregon-youth-authority": "Oregon Youth Authority",
    "parks-and-recreation-department": "State Parks and Recreation Department",
    "psychiatric-security-review-board": "Psychiatric Security Review Board",
    "public-utility-commission": "Public Utility Commission of Oregon",
    "public-utility-commission-oregon-board-of-maritime-pilots": "Oregon Board of Maritime Pilots",
    "real-estate-agency": "Real Estate Agency",
    "saif-corporation": "State Accident Insurance Fund Corporation",
    "southern-oregon-university": "Southern Oregon University",
    "state-board-of-architect-examiners": "State Board of Architect Examiners",
    "state-board-of-tax-practitioners": "State Board of Tax Practitioners",
    "state-board-of-towing": "State Board of Towing",
    "teacher-standards-and-practices-commission": "Teacher Standards and Practices Commission",
    "travel-information-council": "Travel Information Council",
    "veterinary-medical-examining-board": "Oregon State Veterinary Medical Examining Board",
    "water-resources-department": "Water Resources Department",
}

# ------------------------------------------- agent quote-checks (operator decision 2026-10-30)
#
# slug -> [(citation, quotation), ...]. THE REVIEW RECORD OF A ROW AN AGENT READ, in the form a
# human's record already takes here (the sentence a row was read off, set beside it) but as
# data, because an agent's reading is only worth counting if a machine can re-perform it. Each
# pair is a section id and a quotation taken from THIS CORPUS'S OWN MIRROR of that section;
# `quote-in-the-cited-text` matches it against the mirror word for word (whitespace is the
# only thing normalised) on every `--check`, so the record fails the day the mirrored text
# stops saying it.
#
# WHAT A QUOTATION HAS TO SHOW depends on what it is attached to, and no rule here can read
# meaning, so the agent who writes one is answerable for it and a reviewer re-reads it:
#   MAPPED       the section's own sentence that creates or constitutes the body;
#   a name       the sentence that PRINTS the name (`statutory-name-in-a-quote` requires the
#                recorded name to sit inside one of the slug's quotations);
#   UNMAPPED     the sentence that shows the unit is internal structure of its parent;
#   a placement  (`source: statute` on the registry row) the sentence that states where the
#                body sits, from the section the relation cites as its authority
#                (`statute-placement-has-a-quote`).
# A row with none of those in this table was read by a human (every row that predates the
# 2026-10-30 decision) and is not thereby unreviewed.
#
# A QUOTATION IS NOT CITABLE TEXT in the sense the mirror is: it is an excerpt, whitespace
# collapsed, subsection markers dropped. The mirrored section is the text.
QUOTE_CHECKS: dict[str, list[tuple[str, str]]] = {
    # THE ONE STATUTE PLACEMENT THE REGISTRY ALREADY CARRIED (#281, a human's reading of
    # 2026-08-28), recorded here so that `statute-placement-has-a-quote` holds for every
    # `source: statute` relation and not only the ones added after the decision. What the
    # section says is who appoints the commission's members — the Director of Agriculture —
    # which is the sentence the placement under the Department of Agriculture rests on.
    "oregon-hemp-commission": [
        ("ORS 571.406", "the Director of Agriculture shall appoint seven temporary members "
                        "to the Oregon Hemp Commission."),
    ],
    # AGENT QUOTE-CHECKED, 2026-10-30. For a body in the batch above that cites its own section
    # these are the sentences that create or constitute it and print its name; where a body's
    # section lists several bodies (ORS 576.062's commodity commissions, ORS 352.002's
    # universities) the pair is the sentence that introduces the list and the list item.
    "board-of-examiners-for-engineering-and-land-surveying": [
        ("ORS 672.240",
         "The State Board of Examiners for Engineering and Land Surveying shall operate as a "
         "semi-independent state agency subject to ORS 182.456 to 182.472"),
    ],
    "board-of-geologist-examiners": [
        ("ORS 672.615",
         "The State Board of Geologist Examiners shall operate as a semi-independent state "
         "agency subject to ORS 182.456 to 182.472"),
    ],
    "board-of-massage-therapists": [
        ("ORS 687.115",
         "The State Board of Massage Therapists operates as a semi-independent state agency "
         "subject to ORS 182.456 to 182.472"),
    ],
    "board-of-medical-imaging": [
        ("ORS 688.545",
         "There is created the Board of Medical Imaging."),
    ],
    "board-of-nursing": [
        ("ORS 678.140",
         "There is created an Oregon State Board of Nursing"),
    ],
    "board-of-optometry": [
        ("ORS 683.250",
         "The Oregon Board of Optometry operates as a semi-independent state agency subject to "
         "ORS 182.456 to 182.472"),
    ],
    "board-of-parole-and-post-prison-supervision": [
        ("ORS 144.005",
         "A State Board of Parole and Post-Prison Supervision of at least three but no more "
         "than five members hereby is created."),
    ],
    "board-of-pharmacy": [
        ("ORS 689.115",
         "The State Board of Pharmacy consists of nine members appointed by the Governor and "
         "subject to confirmation by the Senate"),
    ],
    "bureau-of-labor-and-industries": [
        ("ORS 651.020",
         "The Bureau of Labor and Industries hereby is established as a separate department of "
         "this state."),
    ],
    "citizens-initiative-review-commission": [
        ("ORS 250.137",
         "The Citizens’ Initiative Review Commission is established as a semi-independent "
         "state agency subject to ORS 182.456 to 182.472."),
    ],
    "columbia-river-gorge-commission": [
        ("ORS 196.150",
         "The States of Oregon and Washington establish by way of this interstate compact a "
         "regional agency known as the Columbia River Gorge Commission."),
    ],
    "commission-for-the-blind": [
        ("ORS 346.120",
         "There is created a commission for persons who are blind and for the prevention of "
         "blindness, to be known as the Commission for the Blind."),
    ],
    "commission-on-judicial-fitness-and-disability": [
        ("ORS 1.410",
         "There is created the Commission on Judicial Fitness and Disability consisting of:"),
    ],
    "commission-on-statewide-law-enforcement-standards-of-conduct-and-discipline": [
        ("ORS 243.812",
         "The Commission on Statewide Law Enforcement Standards of Conduct and Discipline is "
         "established for the purpose of adopting rules that prescribe uniform:"),
    ],
    "construction-contractors-board": [
        ("ORS 701.205",
         "The Construction Contractors Board is established"),
    ],
    "department-of-administrative-services": [
        ("ORS 184.305",
         "The Oregon Department of Administrative Services is created."),
    ],
    "department-of-agriculture": [
        ("ORS 561.010",
         "There is created a department of the government of this state to be known as the "
         "State Department of Agriculture."),
    ],
    "department-of-agriculture-oregon-albacore-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(5) The Oregon Albacore Commission."),
    ],
    "department-of-agriculture-oregon-beef-council": [
        ("ORS 577.210",
         "There hereby is created the Oregon Beef Council composed of:"),
    ],
    "department-of-agriculture-oregon-blueberry-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(8) The Oregon Blueberry Commission."),
    ],
    "department-of-agriculture-oregon-clover-seed-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(9) The Oregon Clover Seed Commission."),
    ],
    "department-of-agriculture-oregon-dairy-products-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(1) The Oregon Dairy Products Commission."),
    ],
    "department-of-agriculture-oregon-dungeness-crab-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(3) The Oregon Dungeness Crab Commission."),
    ],
    "department-of-agriculture-oregon-fine-fescue-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(10) The Oregon Fine Fescue Commission."),
    ],
    "department-of-agriculture-oregon-hazelnut-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(2) The Oregon Hazelnut Commission."),
    ],
    "department-of-agriculture-oregon-hop-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(11) The Oregon Hop Commission."),
    ],
    "department-of-agriculture-oregon-invasive-species-council": [
        ("ORS 570.770",
         "The Invasive Species Council is established within the State Department of "
         "Agriculture."),
    ],
    "department-of-agriculture-oregon-mint-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(12) The Oregon Mint Commission."),
    ],
    "department-of-agriculture-oregon-potato-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(7) The Oregon Potato Commission."),
    ],
    "department-of-agriculture-oregon-processed-vegetable-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(13) The Oregon Processed Vegetable Commission."),
    ],
    "department-of-agriculture-oregon-raspberry-and-blackberry-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(14) The Oregon Raspberry and Blackberry Commission."),
    ],
    "department-of-agriculture-oregon-ryegrass-growers-seed-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(15) The Oregon Ryegrass Growers Seed Commission."),
    ],
    "department-of-agriculture-oregon-salmon-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(4) The Oregon Salmon Commission."),
    ],
    "department-of-agriculture-oregon-sheep-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(6) The Oregon Sheep Commission."),
    ],
    "department-of-agriculture-oregon-strawberry-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(16) The Oregon Strawberry Commission."),
    ],
    "department-of-agriculture-oregon-sweet-cherry-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(17) The Oregon Sweet Cherry Commission."),
    ],
    "department-of-agriculture-oregon-tall-fescue-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(18) The Oregon Tall Fescue Commission."),
    ],
    "department-of-agriculture-oregon-trawl-commission": [
        ("ORS 576.062",
         "The following commodity commissions are established as state commissions:"),
        ("ORS 576.062",
         "(19) The Oregon Trawl Commission."),
    ],
    "department-of-agriculture-oregon-wheat-commission": [
        ("ORS 578.030",
         "There hereby is created the Oregon Wheat Commission."),
    ],
    "department-of-consumer-and-business-services": [
        ("ORS 705.105",
         "The Department of Consumer and Business Services is created."),
    ],
    "department-of-consumer-and-business-services-prescription-drug-affordability-board": [
        ("ORS 646A.693",
         "The Prescription Drug Affordability Board is established in the Department of "
         "Consumer and Business Services"),
    ],
    "department-of-consumer-and-business-services-workers-compensation-board": [
        ("ORS 656.712",
         "The Workers’ Compensation Board, composed of five members appointed by the Governor, "
         "is created within the Department of Consumer and Business Services."),
    ],
    "department-of-corrections": [
        ("ORS 423.020",
         "The Department of Corrections is created."),
    ],
    "department-of-energy": [
        ("ORS 469.030",
         "There is created the State Department of Energy."),
    ],
    "department-of-energy-energy-facility-siting-council": [
        ("ORS 469.450",
         "There is established in the State Department of Energy an Energy Facility Siting "
         "Council"),
    ],
    "department-of-environmental-quality": [
        ("ORS 468.030",
         "There is hereby established in the executive-administrative branch of the government "
         "of the state under the Environmental Quality Commission a department to be known as "
         "the Department of Environmental Quality."),
    ],
    "department-of-fish-and-wildlife": [
        ("ORS 496.080",
         "There is hereby established in the executive branch of the government of this state "
         "under the State Fish and Wildlife Commission a department to be known as the State "
         "Department of Fish and Wildlife."),
    ],
    "department-of-forestry": [
        ("ORS 526.008",
         "The State Forestry Department consists of the State Forester and the deputy, "
         "assistants and employees of the forester, acting under direction of the State Board "
         "of Forestry."),
    ],
    "department-of-human-services": [
        ("ORS 409.010",
         "The Department of Human Services is created."),
    ],
    "department-of-human-services-home-care-commission": [
        ("ORS 410.602",
         "The Home Care Commission is created, consisting of nine members appointed by the "
         "Governor and confirmed by the Senate as provided in ORS 171.562 and 171.565."),
    ],
    "department-of-justice": [
        ("ORS 180.210",
         "There hereby is constituted an executive department to be known as the Department of "
         "Justice."),
    ],
    "department-of-revenue": [
        ("ORS 305.025",
         "The Department of Revenue is established."),
    ],
    "department-of-state-lands": [
        ("ORS 273.041",
         "The Department of State Lands is created, and consists of the Director of the "
         "Department of State Lands and all officers and employees of the department acting "
         "under the State Land Board."),
    ],
    "department-of-state-police": [
        ("ORS 181A.015",
         "There is established a Department of State Police."),
    ],
    "department-of-state-police-oregon-state-athletic-commission": [
        ("ORS 463.113",
         "There is created in the Department of State Police the Oregon State Athletic "
         "Commission"),
    ],
    "department-of-transportation": [
        ("ORS 184.615",
         "The Department of Transportation is established."),
    ],
    "department-of-veterans-affairs": [
        ("ORS 406.005",
         "The Department of Veterans’ Affairs is established."),
    ],
    "eastern-oregon-border-economic-development-board": [
        ("ORS 284.776",
         "The Eastern Oregon Border Economic Development Board is established"),
    ],
    "employment-department": [
        ("ORS 657.601",
         "There is established an Employment Department."),
    ],
    "employment-relations-board": [
        ("ORS 240.060",
         "The Civil Service Commission that has functioned under this chapter shall be "
         "continued as a board of three members to be known as the Employment Relations Board."),
    ],
    "higher-education-coordinating-commission": [
        ("ORS 350.050",
         "There is established a Higher Education Coordinating Commission, consisting of 15 "
         "voting members appointed by the Governor."),
    ],
    "higher-education-coordinating-commission-office-of-student-access-and-completion": [
        ("ORS 348.511",
         "The Office of Student Access and Completion is established and shall operate under "
         "the direction and control of the Higher Education Coordinating Commission."),
    ],
    "land-conservation-and-development-department": [
        ("ORS 197.075",
         "The Department of Land Conservation and Development is established."),
    ],
    "land-use-board-of-appeals": [
        ("ORS 197.810",
         "There is hereby created a Land Use Board of Appeals consisting of not more than "
         "three positions."),
    ],
    "landscape-architect-board": [
        ("ORS 671.459",
         "The State Landscape Architect Board shall operate as a semi-independent state agency "
         "subject to ORS 182.456 to 182.472"),
    ],
    "landscape-contractors-board": [
        ("ORS 671.630",
         "The State Landscape Contractors Board shall operate as a semi-independent state "
         "agency subject to ORS 182.456 to 182.472"),
    ],
    "legislative-administration-committee": [
        ("ORS 173.710",
         "The Legislative Administration Committee hereby is established as a joint committee "
         "of the Legislative Assembly."),
    ],
    "legislative-equity-office": [
        ("ORS 173.900",
         "The Legislative Equity Office is established as a nonpartisan office of the "
         "Legislative Assembly"),
    ],
    "legislative-policy-and-research-committee": [
        ("ORS 173.605",
         "The Legislative Policy and Research Committee is established as a joint committee of "
         "the Legislative Assembly."),
    ],
    "mental-health-regulatory-agency": [
        ("ORS 675.160",
         "The Mental Health Regulatory Agency is created"),
    ],
    "mental-health-regulatory-agency-oregon-board-of-licensed-professional-counselors-and-therapists": [
        ("ORS 675.775",
         "The Oregon Board of Licensed Professional Counselors and Therapists is established."),
    ],
    "mental-health-regulatory-agency-oregon-board-of-psychology": [
        ("ORS 675.100",
         "There hereby is created the Oregon Board of Psychology"),
    ],
    "mortuary-and-cemetery-board": [
        ("ORS 692.300",
         "There is created the State Mortuary and Cemetery Board to carry out the purposes and "
         "enforce the provisions of this chapter."),
    ],
    "occupational-therapy-licensing-board": [
        ("ORS 675.310",
         "There is created the Occupational Therapy Licensing Board."),
    ],
    "office-of-public-defense-services": [
        ("ORS 151.213",
         "The Oregon Public Defense Commission is established in the executive branch of state "
         "government."),
    ],
    "oregon-529-savings-board": [
        ("ORS 178.310",
         "There is established the Oregon 529 Savings Board to administer ORS 178.300 to "
         "178.360, 178.375 and 178.380."),
    ],
    "oregon-advocacy-commissions-office": [
        ("ORS 185.005",
         "The Oregon Advocacy Commissions Office is established to provide administrative "
         "support to:"),
    ],
    "oregon-board-of-accountancy": [
        ("ORS 673.410",
         "There is created an Oregon Board of Accountancy consisting of seven members."),
    ],
    "oregon-board-of-dentistry": [
        ("ORS 679.230",
         "The Oregon Board of Dentistry consists of 10 members appointed by the Governor and "
         "subject to confirmation by the Senate"),
    ],
    "oregon-board-of-naturopathic-medicine": [
        ("ORS 685.160",
         "The Oregon Board of Naturopathic Medicine is created"),
    ],
    "oregon-board-of-physical-therapy": [
        ("ORS 688.160",
         "The Oregon Board of Physical Therapy operates as a semi-independent state agency "
         "subject to ORS 182.456 to 182.472"),
    ],
    "oregon-business-development-department": [
        ("ORS 285A.070",
         "The Oregon Business Development Department is established."),
    ],
    "oregon-criminal-justice-commission": [
        ("ORS 137.654",
         "There is established the Oregon Criminal Justice Commission consisting of 12 members "
         "as follows:"),
    ],
    "oregon-department-of-aviation": [
        ("ORS 835.100",
         "The Oregon Department of Aviation is established."),
    ],
    "oregon-department-of-education": [
        ("ORS 326.111",
         "The Department of Education is created and shall function under the direction and "
         "control of the State Board of Education"),
    ],
    "oregon-department-of-education-fair-dismissal-appeals-board": [
        ("ORS 342.930",
         "The Fair Dismissal Appeals Board is created"),
    ],
    "oregon-department-of-education-youth-development-division": [
        ("ORS 417.852",
         "The Youth Development Division is established in the Department of Education."),
    ],
    "oregon-facilities-authority": [
        ("ORS 289.100",
         "There is created a body politic and corporate to be known as the Oregon Facilities "
         "Authority."),
    ],
    "oregon-film-and-video-office": [
        ("ORS 284.305",
         "The Oregon Film and Video Office is created as a semi-independent state agency "
         "subject to ORS 284.300 to 284.375."),
    ],
    "oregon-forest-resources-institute": [
        ("ORS 526.610",
         "There is created the Oregon Forest Resources Institute."),
    ],
    "oregon-government-ethics-commission": [
        ("ORS 244.250",
         "The Oregon Government Ethics Commission is established, consisting of nine members."),
    ],
    "oregon-health-authority": [
        ("ORS 413.032",
         "The Oregon Health Authority is established."),
    ],
    "oregon-health-authority-health-licensing-office": [
        ("ORS 676.560",
         "the Health Licensing Office is created within the Oregon Health Authority."),
    ],
    "oregon-health-authority-health-licensing-office-behavior-analysis-regulatory-board": [
        ("ORS 676.806",
         "There is created, within the Health Licensing Office, the Behavior Analysis "
         "Regulatory Board consisting of nine members appointed by the Governor, including:"),
    ],
    "oregon-health-authority-health-licensing-office-board-of-certified-advanced-estheticians": [
        ("ORS 676.650",
         "There is established the Board of Certified Advanced Estheticians within the Health "
         "Licensing Office, consisting of:"),
    ],
    "oregon-health-authority-health-licensing-office-board-of-cosmetology": [
        ("ORS 690.155",
         "There is established within the Health Licensing Office the Board of Cosmetology "
         "consisting of seven members appointed by the Governor."),
    ],
    "oregon-health-authority-health-licensing-office-board-of-direct-entry-midwifery": [
        ("ORS 687.470",
         "There is established within the Health Licensing Office the State Board of Direct "
         "Entry Midwifery."),
    ],
    "oregon-health-authority-health-licensing-office-board-of-licensed-dietitians": [
        ("ORS 691.485",
         "There is established, within the Health Licensing Office, the Board of Licensed "
         "Dietitians to advise the office with regard to the regulation of dietitians."),
    ],
    "oregon-health-authority-health-licensing-office-environmental-health-registration-board": [
        ("ORS 700.210",
         "There is established within the Health Licensing Office the Environmental Health "
         "Registration Board to consist of seven members to be appointed by the Governor."),
    ],
    "oregon-health-authority-health-licensing-office-long-term-care-administrators-board": [
        ("ORS 678.800",
         "The Long Term Care Administrators Board is established within the Health Licensing "
         "Office."),
    ],
    "oregon-health-authority-health-licensing-office-state-board-of-sign-language-interpreters": [
        ("ORS 676.780",
         "There is established within the Health Licensing Office the State Board of Sign "
         "Language Interpreters consisting of seven members appointed by the Governor as "
         "follows:"),
    ],
    "oregon-health-authority-health-policy-and-analytics": [
        ("ORS 442.011",
         "There is created in the Oregon Health Authority the Health Policy and Analytics "
         "Division."),
    ],
    "oregon-health-authority-oregon-educators-benefit-board": [
        ("ORS 243.862",
         "There is established in the Oregon Health Authority an Oregon Educators Benefit "
         "Board consisting of at least 10 members appointed by the Governor, including:"),
    ],
    "oregon-health-authority-oregon-prescription-drug-program": [
        ("ORS 414.312",
         "The Oregon Prescription Drug Program is established in the Oregon Health Authority."),
    ],
    "oregon-health-authority-public-employees-benefit-board": [
        ("ORS 243.061",
         "There is created in the Oregon Health Authority the Public Employees’ Benefit Board"),
    ],
    "oregon-housing-and-community-services-department": [
        ("ORS 456.555",
         "The Housing and Community Services Department is established."),
    ],
    "oregon-investment-council": [
        ("ORS 293.706",
         "There is created the Oregon Investment Council, consisting of five voting members "
         "and one nonvoting member."),
    ],
    "oregon-liquor-control-commission": [
        ("ORS 471.705",
         "There is created the Oregon Liquor and Cannabis Commission, consisting of nine "
         "commissioners appointed by the Governor."),
    ],
    "oregon-medical-board": [
        ("ORS 677.235",
         "The Oregon Medical Board consists of 14 members appointed by the Governor and "
         "subject to confirmation by the Senate"),
    ],
    "oregon-military-department": [
        ("ORS 396.305",
         "The Oregon Military Department is established."),
    ],
    "oregon-patient-safety-commission": [
        ("ORS 442.820",
         "The Oregon Patient Safety Commission is established as a semi-independent state "
         "agency subject to ORS 182.456 to 182.472."),
    ],
    "oregon-racing-commission": [
        ("ORS 462.210",
         "There is created the Oregon Racing Commission to consist of five commissioners who "
         "shall be citizens, residents and electors of this state."),
    ],
    "oregon-state-marine-board": [
        ("ORS 830.105",
         "There hereby is created the State Marine Board consisting of five members to be "
         "appointed by the Governor"),
    ],
    "oregon-tourism-commission": [
        ("ORS 284.107",
         "There is established an Oregon Tourism Commission consisting of nine members "
         "appointed by the Governor."),
    ],
    "oregon-utility-notification-center": [
        ("ORS 757.547",
         "The Oregon Utility Notification Center is created as an independent not-for-profit "
         "public corporation."),
    ],
    "oregon-watershed-enhancement-board": [
        ("ORS 541.900",
         "The Oregon Watershed Enhancement Board is created."),
    ],
    "oregon-watershed-enhancement-board-environmental-restoration-council": [
        ("ORS 541.861",
         "The Environmental Restoration Council is established in the Oregon Watershed "
         "Enhancement Board."),
    ],
    "oregon-wine-board": [
        ("ORS 576.856",
         "The Oregon Wine Board is established as a semi-independent state agency subject to "
         "ORS 182.456 to 182.472."),
    ],
    "oregon-youth-authority": [
        ("ORS 420A.010",
         "The Oregon Youth Authority is established."),
    ],
    "parks-and-recreation-department": [
        ("ORS 390.111",
         "The State Parks and Recreation Department is created."),
    ],
    "psychiatric-security-review-board": [
        ("ORS 161.385",
         "There is hereby created a Psychiatric Security Review Board"),
    ],
    "public-utility-commission": [
        ("ORS 756.014",
         "There is created the Public Utility Commission of Oregon."),
    ],
    "public-utility-commission-oregon-board-of-maritime-pilots": [
        ("ORS 776.105",
         "The Oregon Board of Maritime Pilots is established within the Public Utility "
         "Commission of Oregon"),
    ],
    "real-estate-agency": [
        ("ORS 696.375",
         "The Real Estate Agency is established."),
    ],
    "saif-corporation": [
        ("ORS 656.752",
         "The State Accident Insurance Fund Corporation is created for the purpose of "
         "transacting workers’ compensation insurance and reinsurance business."),
    ],
    "southern-oregon-university": [
        ("ORS 352.002",
         "The following are established as public universities in the State of Oregon:"),
        ("ORS 352.002",
         "(6) Southern Oregon University."),
    ],
    "state-board-of-architect-examiners": [
        ("ORS 671.120",
         "The State Board of Architect Examiners shall operate as a semi-independent state "
         "agency subject to ORS 182.456 to 182.472"),
    ],
    "state-board-of-tax-practitioners": [
        ("ORS 673.725",
         "There is created a State Board of Tax Practitioners."),
    ],
    "state-board-of-towing": [
        ("ORS 822.250",
         "The State Board of Towing is established within the Department of Transportation."),
    ],
    "teacher-standards-and-practices-commission": [
        ("ORS 342.350",
         "There is created a Teacher Standards and Practices Commission consisting of 17 "
         "members appointed by the Governor"),
    ],
    "travel-information-council": [
        ("ORS 377.835",
         "The Travel Information Council is created as a semi-independent state agency."),
    ],
    "veterinary-medical-examining-board": [
        ("ORS 686.210",
         "There is created the Oregon State Veterinary Medical Examining Board, which shall "
         "carry out the purposes and enforce the provisions of this chapter."),
    ],
    "water-resources-department": [
        ("ORS 536.039",
         "There is hereby established in the executive-administrative branch of the government "
         "of the state under the Water Resources Commission a department to be known as the "
         "Water Resources Department."),
    ],
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

    The registry stores a sub-unit as `Parent, Child` — 81 of 190 bodies (#279, re-measured
    for #281) — because the OAR index nests by chapter. ORS catchlines name the CHILD ALONE,
    so matching the compound string finds nothing: `Department of Agriculture, Oregon Wheat
    Commission` never matches
    the catchline `Oregon Wheat Commission; members; appointment process; rules`. Measured,
    the tail segment recovers 21 tier-1 rows that were sitting in `no_candidate` looking
    like bodies statute forgot to create.
    """
    v = _spellings(name)
    if "," in name:
        # COMPOUND NAME — NAME: the tail segment is the body's OWN name, which is what an
        # ORS catchline prints, and it is used to match one. The head segment — the parent
        # — is discarded and nothing here records a placement: hierarchy lives in
        # `relations` (#174), and re-deriving it from this string would be a second,
        # unsourced answer to a question the registry already answers.
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
                 "A VERDICT NEED NOT BE AN ORS CITATION. This matcher only reads the "
                 "mirrored ORS, so a body created by the Oregon Constitution or by an "
                 "executive order reaches `no_candidate` below with nothing against it — "
                 "which is a statement about the matcher and not about the body. About "
                 "nine of them are constitutional offices (ADR 0005): the Office of the "
                 "Governor, the Secretary of State, the Oregon State Treasury, the "
                 "Judicial Department, District Attorneys and Deputies, the Legislative "
                 "Assembly. Since #196 a constitutional authority is CHECKABLE — "
                 "`Or. Const. Art. VI, sec. 1` is resolved against the mirrored "
                 "Constitution by --check exactly as an ORS citation is resolved against "
                 "the mirrored statutes, and a wrong article or section fails the build "
                 "with the reason it failed — so recording one is review whose output is "
                 "verified rather than taken on faith. A body this matcher cannot find "
                 "may also have been created by an UNCODIFIED SESSION LAW rather than by "
                 "the Constitution — #211's own worked case is the Legislative Fiscal "
                 "Office (Oregon Laws 1959, chapter 70): its codified range, ORS "
                 "173.410-173.465, mirrors the office's operation and never once "
                 "creates it. Since #211 "
                 "`Oregon Laws 1975, chapter 789` is a recordable form too, but it is "
                 "CHECKED FOR SHAPE ONLY — this corpus mirrors no session laws, so nothing "
                 "here can confirm the citation names the right chapter, and getting the "
                 "session law right is entirely on the human who verifies it. "
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
    """Every citation this corpus can resolve an authority against BY LOOKING IT UP IN A
    LIST: the mirrored ORS sections and the mirrored executive orders.

    THE CONSTITUTION IS NOT IN HERE, and since #196 that is a statement about the SHAPE of
    the answer rather than about coverage. An ORS citation either names a mirrored section
    or it does not, and a set says so. A constitutional citation that names nothing has
    SEVEN different things it can mean (see `constitutional_resolver`), and a set can only
    ever say "absent" — which is precisely the collapse ADR 0005 refuses. So the
    constitutional form is resolved by a function that can answer with a reason, and the
    other two by membership.

    A SESSION LAW IS NOT IN HERE EITHER (#211), and that is a statement about COVERAGE, not
    about shape: this corpus mirrors no session laws at all, so there is no list — however
    resolved — for a citation of this form to be looked up in. `audit_table()`'s own
    per-form dispatch is what keeps this set from ever being asked the question for that
    form; a set that returned False for every session-law citation would report every one of
    them as citing a document that does not exist, which is a different (and false) finding
    from "this corpus does not mirror the kind of document that would confirm it".
    """
    return {c for c, _t, _s, _b, _m in _statute_sections()} | _executive_order_citations()


def published_constitutional_sections(root=None) -> set[str]:
    """The document id of every constitutional section this corpus has PUBLISHED, read from
    the mirror on disk.

    It refuses to return an empty set for the same reason `_executive_order_citations` does,
    and CONTEXT.md's overriding rule is the reason: with no documents on disk every
    constitutional authority would be reported as citing a section that does not exist, and
    "could not check" is never reported as "is not there". That failure is the loudest one
    this ticket could produce — an unresolvable authority is admitting evidence withdrawn
    (ADR 0003), so an empty `constitution/` would report the Secretary of State as a body
    nothing created.
    """
    out = {p.stem for p in (CONSTITUTION if root is None else root).glob("orconst-*.md")}
    if not out:
        sys.exit("no mirrored constitutional sections were found — refusing to report a "
                 "constitutional authority as unresolvable. Is `constitution/` populated?")
    return out


def constitutional_resolver(published):
    """Build the function that resolves one constitutional authority: it returns None when
    the citation names a mirrored section, and WHY IT DOES NOT otherwise. `published` is the
    set `published_constitutional_sections` reads.

    A REASON RATHER THAN A BOOLEAN, because "it resolved to nothing" is SEVEN different
    findings and a registry reader has to be able to tell them apart. FIVE OF THEM ARE ABOUT
    THE CONSTITUTION (ADR 0005, #195), and the citation scheme is what tells them apart:

      * the source page prints no such article        — the citation is wrong
      * the article is printed and carries no sections — a repealed article, `no-sections`
      * the page prints no such section in it          — the citation is wrong, differently
      * the page prints the section and this corpus did not publish it — `history-only`, a
        repealed section printed as a leadline and a repeal bracket
      * the numeral names TWO operative articles, and this is NOT A FAILURE TO RESOLVE. A
        bare `Or. Const. Art. VII, sec. 1` names a numeral the page prints TWICE, as
        (Amended) and (Original). Resolving it would be a coin flip between articles with
        different text, so it resolves to nothing and says which two citations to choose
        between. A registry row may not carry it — not because the citation is wrong, but
        because it is not yet a citation to one article, and admitting evidence has to name
        the thing that admits.

    A row citing a repealed section and a row citing a section that never existed are
    different errors, and a reader who cannot tell which has been told the citation is bad
    and nothing else. THE CATALOG IS WHAT SAYS WHICH — `_meta/catalog/constitution.yml`
    records a status and a reason per article and per section — so none of the five is
    inferred from a file being missing.

    THE OTHER TWO ARE ABOUT THIS CORPUS AND ARE WORDED SO, because a reviewer sent back to
    re-read the Constitution over a missing file has been told the wrong thing: the catalog
    recording a section as published while `constitution/` does not carry it, and a string
    the scheme does not recognise as a constitutional citation at all.

    IT RESOLVES THROUGH THE `or-const` CITATION SCHEME, which is the same code path
    `resolve_citation` serves to an agent. Restating the lookup here would be the third
    declaration of what a constitutional citation means, after #195 retired the second.
    Imported inside the function because it pulls in the toolkit's scheme registry, which
    every other path through this file has no use for.
    """
    from citation_schemes import resolve as resolve_or_const

    def unresolved_reason(authority: str) -> str | None:
        ids, note = resolve_or_const(authority)
        if ids is None:
            # `--check` classifies the form first and cannot reach this, because
            # `AUTHORITY_FORMS` and the scheme are built from one token and gated at zero
            # disagreements (#195). This function is PUBLIC, though, and answering None for
            # a string it never recognised would say "resolved" about something it did not
            # look at — the one answer a gate on admitting evidence may never give. Proved
            # failing in `_proof_a_citation_the_scheme_refuses_is_not_called_resolved`.
            return ("the or-const citation scheme does not recognise it as a constitutional "
                    "citation, so there is nothing to resolve against the mirror")
        if not ids:
            return note or "it names no section of the mirrored Constitution"
        absent = sorted(i for i in ids if i not in published)
        if absent:
            # WHY THE MIRROR IS READ AT ALL when the catalog already says what is published:
            # without it, an empty `constitution/` would report every constitutional
            # authority as RESOLVED against documents that are not there, which is the worse
            # half of CONTEXT.md's rule and the one nothing else here would catch.
            # `ingest_constitution.py --check` owns the catalog-versus-disk gate; this one
            # declines to call the row resolved while that gate is failing.
            return (f"the Constitution catalog records it as published and "
                    f"{', '.join(f'constitution/{i}.md' for i in absent)} is not on disk. "
                    "That is a gap in this corpus, not a wrong citation — run "
                    "`python3 src/ingest_constitution.py --check`")
        return None

    return unresolved_reason


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


def audit_table(orgs, mapped, unmapped, citations, why_unresolved) -> list[Failure]:
    """Everything wrong with the reviewed tables themselves, as Failures.

    Separate from `audit_registry` below because `--apply` must run this one and not that
    one: the registry disagreeing with the table is precisely what --apply is for, while a
    bad row in the TABLE is a thing that must never be written to the registry at all.

    `why_unresolved` is `constitutional_resolver`'s function: it takes a constitutional
    citation and returns None, or the reason it names no mirrored section. IT HAS NO DEFAULT
    on purpose. A default would let a caller resolve the ORS and executive-order forms and
    take the constitutional one on faith without writing a line that says so — which is the
    state #196 exists to leave, and it would look exactly like a clean run.
    """
    by_slug = {o["slug"]: o for o in orgs if isinstance(o, dict) and o.get("slug")}
    problems = []

    for slug in sorted(set(mapped) | set(unmapped)):
        if slug not in by_slug:
            problems.append(Failure("slug-in-registry", slug,
                                    "named here but not in the registry"))
    for slug in sorted(set(mapped) & set(unmapped)):
        problems.append(Failure("not-both-tables", slug,
                                "is in BOTH MAPPED and UNMAPPED — a body either has an "
                                "enabling authority or has a reason it has none, and "
                                "whichever table a reader consults would be the answer"))

    for slug, authority in sorted(mapped.items()):
        form, detail = classify_authority(authority)
        if form is None:
            problems.append(Failure("authority-form", slug, detail))
        elif form == "reviewed-none":
            problems.append(Failure(
                "authority-form", slug,
                f"{authority!r} records that there is no authority, which is UNMAPPED's "
                "job — MAPPED holds authorities, and a row in the wrong table is a body "
                "reported as having one"))
        elif form == "constitution":
            # THE THIRD FORM RESOLVES TOO, since #196. It is checked here rather than by
            # membership of `citations` because a constitutional citation that names nothing
            # has seven meanings and the resolver is the only thing that can say which — see
            # `constitutional_resolver`. Same rule, same failure, a longer answer.
            why = why_unresolved(authority)
            if why:
                problems.append(Failure(
                    "authority-resolves", slug,
                    f"cites {authority}, which resolves to no section of the mirrored "
                    f"Oregon Constitution. {why}"))
        elif form == "session-law":
            # THE FOURTH FORM DOES NOT RESOLVE, AND SAYS SO (#211). Unlike the three above,
            # this corpus mirrors no session laws — there is nothing on disk for a citation to
            # name, so there is nothing membership of `citations` or a resolver could check
            # existence against. `classify_authority` already confirmed the value is SPELLED
            # like a session-law citation; that is the whole of what this rule can verify for
            # this form, and `check()` below reports the count as "form-checked, not
            # resolved" rather than folding it into the resolved counts beside it — never the
            # same "verified" a citation this corpus can actually look up earns.
            pass
        elif authority not in citations:
            # Not "not a mirrored ORS section": an executive order is an authority too
            # (ADR 0003) and this corpus mirrors 526 of them, so ORS and executive-order
            # citations both resolve against something mirrored — the constitution resolves
            # above, by its own five-answer resolver, and a session law does not resolve at
            # all (the branch above this one).
            problems.append(Failure(
                "authority-resolves", slug,
                f"cites {authority}, which no document in this corpus carries. Either the "
                "citation is wrong or upstream changed — both are worth knowing"))

    for slug, reason in sorted(unmapped.items()):
        form, detail = classify_authority(no_authority_value(reason))
        if form != "reviewed-none":
            problems.append(Failure("unmapped-has-reason", slug, detail))
        # THE MIRROR IMAGE OF THE RULE ABOVE, and the one this table walked into once: a
        # reason that IS a citation says the body has an authority while filing it as a body
        # that has none. Constitutional offices are how it happens — the field could hold
        # only statutes when this table was written, so `Or. Const. Art. VI, sec. 1` was a
        # reason rather than a value. It is a value now.
        elif classify_authority(str(reason).strip())[0] is not None:
            problems.append(Failure(
                "unmapped-is-not-an-authority", slug,
                f"the reason recorded here IS an authority ({str(reason).strip()!r}) — a "
                "body with one belongs in MAPPED, and filing it here reports it as a body "
                "nothing created"))
    return problems


def statute_texts() -> dict[str, str]:
    """{ORS citation: its catchline and mirrored body, as one string}.

    THE MIRROR, READ ONCE, so `statutory-name-in-the-cited-text` resolves a recorded name
    against the same corpus the citation itself is resolved against. The catchline is
    included because that is where Oregon most often prints the body's name in full — ORS
    684.130 is titled `State Board of Chiropractic Examiners` — and a check that read only
    the section body would refuse a name the section's own title states.
    """
    return {cite: f"{title} {body}" for cite, title, _, body, _ in _statute_sections()}


def eo_texts(root=None) -> dict[str, str]:
    """{Executive Order citation: its mirrored title and body, as one string} — the
    executive-order half of #220.

    THE WHOLE ORDER, because an executive order has no narrower or wider unit to check a
    name against the way an ORS chapter or a constitutional article does: the order IS its
    own enabling authority, in full. Read from the mirror, never fetched, the same discipline
    `_executive_order_citations()` keeps for the citations themselves — this is that same
    directory read a second time, for TEXT rather than for the citation string alone.
    `root` is the executive-orders directory, parameterised the way
    `constitution_article_texts`'s already is, so a proof can point this at a directory
    holding fewer or differently-shaped documents than the committed one without touching
    disk.

    CONCATENATED WHEN TWO FILES SHARE ONE CITATION, the same way `constitution_article_texts`
    concatenates two sections of one article, and for the same reason: 526 mirrored orders
    carry only 523 distinct citations — `Executive Order 03-03` and `08-16` each have a
    companion `-letter.md` file, and `Executive Order 24-15` has an `-amended.md` one. A
    last-write-wins dict would silently drop whichever file sorts first, which for `24-15`
    is the AMENDED text — a name introduced by the amendment would then be checked against
    the unamended order alone and reported absent from an authority whose full mirrored text
    was never read. Refuses an empty result for the reason `_executive_order_citations`
    does: with no orders on disk this would silently make every name-against-text check
    report "not found" rather than "could not check" (CONTEXT.md)."""
    parts: dict[str, list[str]] = collections.defaultdict(list)
    for path in sorted((EXECUTIVE_ORDERS if root is None else root).glob("eo-*.md")):
        text = path.read_text(errors="replace")
        fm = text.split("---", 2)[1] if text.startswith("---") else ""
        title = (re.search(r'(?m)^title:\s*"?([^"\n]+)', fm) or [None, ""])[1].strip()
        cite = (re.search(r'(?m)^citation:\s*"?([^"\n]+)', fm) or [None, ""])[1].strip()
        cite = cite.rstrip('"')
        if not cite:
            continue
        body = " ".join(text.split("---", 2)[-1].split())
        parts[cite].append(f"{title} {body}")
    if not parts:
        sys.exit("no mirrored executive orders were found — refusing to report a statutory "
                 "name checked against executive-order text as unresolvable. Is "
                 "`executive-orders/` populated?")
    return {cite: " ".join(chunks) for cite, chunks in parts.items()}


def constitution_article_texts(root=None) -> dict[str, str]:
    """{article slug: the concatenated title and mirrored body of EVERY section in that
    article} — the constitutional half of #220, and RESOLVED AGAINST THE ARTICLE rather than
    the one cited section, which is the acceptance criterion this function exists to meet.

    WHY THE ARTICLE AND NOT THE SECTION. An ORS citation names one section and that section's
    own text is the whole of what it has to say (`statute_texts` reads one section). A
    constitutional article is not shaped that way: Article VI is split across ten sections by
    the source page's own layout, and a body it creates can be NAMED in a different section
    than the one that creates it. Article VI section 1 creates the Secretary of State's
    office by requiring an election ("a Secretary, and Treasurer of State") and never once
    prints the words "Secretary of State"; section 2, two sections later in the same article,
    prints them five times ("Duties of Secretary of State. The Secretary of State shall keep
    a fair record..."). Checking section 1 alone would refuse a name the SAME enabling
    authority states — `AUTHORITY_FORMS` still requires the citation to name one section
    (#170's own form, unchanged by this); this is what TEXT that citation is checked against,
    not what a row may cite.

    Read from the mirror, never fetched, the same discipline `_statute_sections` keeps.
    `root` is the constitution directory, parameterised the way
    `published_constitutional_sections` already is, so a selftest can point this at a
    directory holding fewer documents than the committed one without touching disk.

    Refuses an empty result for the reason `published_constitutional_sections` does: an
    empty `by_slug` here would make every constitutional statutory-name check silently read
    as "the article does not print that name" rather than "there was no article to check
    against" — an answer about Oregon law drawn from a directory that was never read."""
    from repo_lib import ORCONST_ID_RE
    by_slug: dict[str, list[str]] = collections.defaultdict(list)
    for path in sorted((CONSTITUTION if root is None else root).glob("orconst-art-*-sec-*.md")):
        m = ORCONST_ID_RE.match(path.stem)
        if not m:
            continue
        text = path.read_text(errors="replace")
        fm = text.split("---", 2)[1] if text.startswith("---") else ""
        title = (re.search(r'(?m)^title:\s*"?([^"\n]+)', fm) or [None, ""])[1].strip()
        body = " ".join(text.split("---", 2)[-1].split())
        by_slug[m.group(1)].append(f"{title} {body}")
    if not by_slug:
        sys.exit("no mirrored constitutional sections were found — refusing to report a "
                 "statutory name checked against constitutional text as unresolvable. Is "
                 "`constitution/` populated?")
    return {slug: " ".join(parts) for slug, parts in by_slug.items()}


def constitution_name_lookup(article_texts=None):
    """Build the function that answers, for one constitutional `enabling_authority` value,
    the text its recorded statutory name is checked against — `constitution_article_texts()`
    read back through the citation's own article, the way `statute_texts().get` answers the
    same question for one ORS section.

    A CLOSURE, NOT A DICT, unlike `statute_texts`/`eo_texts`: those two are keyed by the exact
    citation MAPPED holds, one document per citation. This one is keyed by ARTICLE, and more
    than one section citation can name the same article (Article VI section 1 and section 2
    both resolve to the SAME combined text) — parsing the citation on lookup is what lets a
    single `article_texts` dict serve every section citation of an article rather than
    duplicating the combined text once per section it could have named."""
    from citation_schemes import OR_CONST_C
    from repo_lib import orconst_article_slug
    article_texts = constitution_article_texts() if article_texts is None else article_texts

    def lookup(authority: str):
        m = OR_CONST_C.search(authority)
        if not m:
            return None
        try:
            slug = orconst_article_slug(m.group(1))
        except ValueError:
            return None
        return article_texts.get(slug)

    return lookup


def name_text_lookups(ors_texts=None, eo=None, constitution=None) -> dict:
    """{form: the function `audit_statutory_names` calls to get the text a recorded name of
    that form is checked against} — the single place the three RESOLVABLE forms' text
    lookups are assembled, for `check()` and `cmd_apply()` to build once and pass down rather
    than each re-deriving its own answer to "what may a name be checked against".

    ONLY THE THREE FORMS THIS CORPUS MIRRORS ARE HERE (#220). A session law (#211) is not,
    deliberately: `audit_statutory_names` reads a form's ABSENCE from this mapping as "this
    gate cannot read the text of this form" and reports it as such — so adding a form here
    is a claim that this corpus holds something to check a name against, and a session law is
    exactly the form that claim is false for."""
    ors_texts = statute_texts() if ors_texts is None else ors_texts
    eo = eo_texts() if eo is None else eo
    constitution_lookup = (constitution_name_lookup() if constitution is None
                           else constitution_name_lookup(constitution))
    return {"ors": ors_texts.get, "executive-order": eo.get, "constitution": constitution_lookup}


def audit_statutory_names(orgs, mapped, names, text_lookups) -> list[Failure]:
    """Everything wrong with STATUTORY_NAMES itself, as Failures.

    ITS OWN FUNCTION RATHER THAN A BLOCK INSIDE `audit_table`, because it needs a different
    thing from the corpus: `audit_table` asks whether a citation names a mirrored document,
    and this asks what that document SAYS. `text_lookups` is `{form: text-of-authority
    function}` (`name_text_lookups()`) and has NO DEFAULT, for the reason `why_unresolved`
    has none — a default would let a caller check the table's shape and take the names on
    faith, which would look exactly like a clean run and is the state this table exists to
    leave.

    A NAME NEEDS AN AUTHORITY, AND THE AUTHORITY HAS TO SAY IT. Those are the two rules, and
    they are separate: the first is a claim about this repository's own tables (a body whose
    enabling authority nobody has reviewed cannot have had its name read off one), the second
    is a claim about Oregon law, resolved against the mirror. The registry's own contract
    check states the first over the committed rows too (`statutory-name-basis` in
    catalog_agencies.py) — same rule, two populations, and neither covers the other: a name
    can be wrong in the table before it is ever written, and a row can be hand-edited after.

    THREE FORMS RESOLVE AND ONE DOES NOT (#211/#220), and `text_lookups` is what tells them
    apart: a form present as a key is checked against real text — ORS, an executive order, or
    (since #220) a constitutional article read WHOLE, not just the cited section — and a form
    absent from it (a session law, until this corpus mirrors one) is reported as unchecked
    rather than passed over, because "could not check" is never reported as "is correct".
    """
    by_slug = {o["slug"] for o in orgs if isinstance(o, dict) and o.get("slug")}
    problems = []
    for slug, name in sorted(names.items()):
        if slug not in by_slug:
            # REPORTED AND NOT EVALUATED FURTHER. There is no row for the rules below to be
            # about, and stacking "and its authority is wrong" onto a body this registry does
            # not carry would report two faults where there is one.
            problems.append(Failure("statutory-name-slug-in-registry", slug,
                                    "named here but not in the registry"))
            continue
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            problems.append(Failure(
                "statutory-name-is-a-name", slug,
                f"{name!r} is not a name — a blank, a null or a string with stray "
                "whitespace becomes the value three sibling corpora read as what Oregon "
                "law calls this body"))
            continue
        authority = mapped.get(slug)
        if authority is None:
            problems.append(Failure(
                "statutory-name-has-an-authority", slug,
                f"records the statutory name {name!r} and MAPPED records no enabling "
                "authority for this body — the statutory name is the name a body's "
                "ENABLING AUTHORITY gives it (ADR 0003), so there is nothing here it "
                "could have been read off"))
            continue
        form = classify_authority(authority)[0]
        text_of = text_lookups.get(form)
        if text_of is None:
            # ALLOWLIST, NOT BLOCKLIST, as everywhere in this file. A form this corpus does
            # not mirror (a session law, #211) — or does not yet have a lookup wired in for —
            # is a name nobody checked, which must not be the same state as a name that
            # passed. Before #220 this branch caught the constitution and executive-order
            # forms too, both mirrored and neither reachable as TEXT by citation here; now it
            # catches exactly the one form the acceptance criterion says must STAY here.
            problems.append(Failure(
                "statutory-name-in-the-cited-text", slug,
                f"cites {authority}, whose form ({form}) this gate cannot read the text of "
                "— so the recorded name could not be checked against it. That is 'could "
                "not check', not 'is correct'"))
        elif (text := text_of(authority)) is None:
            # THE THIRD LEG, AND THE ONE THAT LOOKS LIKE THE SECOND. A citation naming no
            # mirrored document has no text, and comparing a name against nothing would
            # report "the authority does not print that name" — an answer about Oregon law
            # drawn from a file this corpus does not hold. "Could not check" is never
            # reported as "is not there" (CONTEXT.md). `authority-resolves` in audit_table()
            # is what says the citation itself resolves to nothing; this says what that cost
            # THIS rule, so a reviewer is not left to infer that the name was checked and
            # failed.
            problems.append(Failure(
                "statutory-name-in-the-cited-text", slug,
                f"records the statutory name {name!r} and cites {authority}, whose text "
                f"this corpus does not mirror — so there was no text to check the name "
                "against. That is 'could not check', not 'the authority does not print it'"))
        elif name not in text:
            problems.append(Failure(
                "statutory-name-in-the-cited-text", slug,
                f"records the statutory name {name!r}, which does not appear anywhere in "
                f"the mirrored text of {authority} — the authority this registry says "
                "created the body does not print that name"))
    return problems


def _good_pairs(pairs) -> list:
    """The (citation, quotation) pairs among `pairs` that are well formed — the rest are
    `quote-is-a-quote`'s to report, and every other reader must keep going without them."""
    return [p for p in (pairs if isinstance(pairs, list) else [])
            if isinstance(p, tuple) and len(p) == 2 and all(isinstance(x, str) for x in p)]


def _squash(text) -> str:
    """Whitespace collapsed to single spaces — the ONLY normalisation a quotation gets. Case,
    punctuation and the typographic apostrophe the mirror prints all have to match."""
    return " ".join(str(text).split())


def audit_quote_checks(orgs, mapped, unmapped, names, quotes, text_lookups) -> list[Failure]:
    """Everything wrong with QUOTE_CHECKS, as Failures: the record of what an agent read.

    `text_lookups` is `name_text_lookups()` and has NO DEFAULT, for the reason
    `audit_statutory_names` has none: a default would let a caller check the table's shape and
    take the quotations on faith, which looks exactly like a clean run.

    A QUOTATION THAT COULD NOT BE CHECKED IS NOT ONE THAT DID NOT MATCH (CONTEXT.md). Three
    different things can stand between a quotation and the text it claims to be from, and the
    detail says which: the citation's form is one this gate cannot read the text of (a session
    law), the citation names a section this corpus does not hold, or the section is held and
    does not say it. The last is a wrong or stale record; the first two are a record nobody
    could re-perform, and neither may be reported as the third.
    """
    by_slug = {o["slug"]: o for o in orgs if isinstance(o, dict) and o.get("slug")}
    problems = []
    for slug, pairs in sorted(quotes.items()):
        if slug not in by_slug:
            problems.append(Failure("quote-slug-in-registry", slug,
                                    "named in QUOTE_CHECKS but not in the registry"))
            continue
        statute_placed = any(isinstance(e, dict) and e.get("source") == STATUTE_SOURCE
                             for e in relation_entries(by_slug[slug]))
        if not (slug in mapped or slug in unmapped or slug in names or statute_placed):
            problems.append(Failure(
                "quote-has-a-reviewed-row", slug,
                "has a quotation on record and nothing for it to be the review OF: the body "
                "is in none of MAPPED, UNMAPPED and STATUTORY_NAMES and carries no "
                f"`source: {STATUTE_SOURCE}` relation, so the record supports no claim"))
        pairs = pairs if isinstance(pairs, list) else []
        if not pairs:
            problems.append(Failure("quote-is-a-quote", slug,
                                    "QUOTE_CHECKS holds no (citation, quotation) pair for it"))
            continue
        for pair in pairs:
            if (not isinstance(pair, tuple) or len(pair) != 2
                    or not all(isinstance(x, str) for x in pair)):
                problems.append(Failure("quote-is-a-quote", slug,
                                        f"{pair!r} is not a (citation, quotation) pair"))
                continue
            citation, quote = pair
            if len(_squash(quote).split()) < MIN_QUOTE_WORDS:
                problems.append(Failure(
                    "quote-is-a-quote", slug,
                    f"{quote!r} is under {MIN_QUOTE_WORDS} words — a fragment that short "
                    "appears in a great many sections and shows nothing about this one"))
                continue
            form = classify_authority(citation)[0]
            text_of = text_lookups.get(form)
            if text_of is None:
                problems.append(Failure(
                    "quote-in-the-cited-text", slug,
                    f"quotes {citation!r}, whose form ({form}) this gate cannot read the "
                    "text of — so the quotation could not be checked. That is 'could not "
                    "check', not 'matches'"))
            elif (text := text_of(citation)) is None:
                problems.append(Failure(
                    "quote-in-the-cited-text", slug,
                    f"quotes {citation!r}, whose text this corpus does not mirror — so "
                    "there was no text to match the quotation against. That is 'could not "
                    "check', not 'the section does not say it'"))
            elif _squash(quote) not in _squash(text):
                problems.append(Failure(
                    "quote-in-the-cited-text", slug,
                    f"quotes {citation!r} as {quote!r}, which does not appear word for word "
                    "in the mirrored text of that section — a wrong quotation, or a section "
                    "that has changed since it was taken"))
        name = names.get(slug)
        if name is not None and not any(name in _squash(q) for _, q in _good_pairs(pairs)):
            problems.append(Failure(
                "statutory-name-in-a-quote", slug,
                f"records the statutory name {name!r} and none of its quotations prints it — "
                "an agent's review of a name is the sentence that PRINTS the name, and "
                "without one the name rests on a reading nobody can re-perform"))
    # EVERY STATUTE PLACEMENT HAS THE SENTENCE THAT STATES IT. The relation's `authority` is
    # written by derive_relation_kinds.py and is the body's OWN enabling authority, so the
    # section it cites is the body's constituting section — and a placement is only a
    # quotation-checked claim when that section is the one that says where the body sits.
    for slug, o in sorted(by_slug.items()):
        for entry in relation_entries(o):
            if not isinstance(entry, dict) or entry.get("source") != STATUTE_SOURCE:
                continue
            cited = [c for c, _ in _good_pairs(quotes.get(slug))]
            want = entry.get("authority")
            if not cited or (want is not None and want not in cited):
                problems.append(Failure(
                    "statute-placement-has-a-quote", slug,
                    f"is placed under {entry.get('target')!r} by `source: {STATUTE_SOURCE}` "
                    f"(authority {want!r}) and QUOTE_CHECKS holds "
                    f"{'no quotation' if not cited else 'no quotation from that section'} "
                    "for it — a statute placement is the sentence that states it, set "
                    "beside the relation"))
    return problems


def audit_registry(orgs, mapped=None, unmapped=None, names=None) -> list[Failure]:
    """Every way the registry and the reviewed tables disagree, in BOTH directions.

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
            problems.append(Failure("registry-agrees", slug,
                                    f"registry has {got!r}, this table says {value!r} — "
                                    "run --apply"))
    for slug, o in sorted(by_slug.items()):
        if "enabling_authority" in o and slug not in want:
            problems.append(Failure(
                "registry-agrees", slug,
                f"registry carries enabling_authority {o['enabling_authority']!r} and this "
                "table does not. This file is the field's single writer: either the row was "
                "written by something else, or a reviewed row was deleted from the table"))

    # THE SAME TWO DIRECTIONS OVER THE STATUTORY NAME (#168). `name` has two writers by
    # design — the scrape writes the OAR title onto a row nobody has reviewed, and this file
    # writes the reviewed statutory name — and what keeps that from being the drift #175
    # warns about is that the ROW says which of the two it is holding. So the pair is checked
    # against the basis, not against the value alone: a row claiming `enabling-authority`
    # that this table does not name was written by something else, and a row this table names
    # that does not claim it is a review that never landed.
    # NAME READER — MACHINERY: the reviewed table checked against the field it writes, in
    # both directions. It compares `name` to the value this table says belongs there and
    # matches it against nothing else — the same reading `registry-agrees` does one field
    # over, and unaffected by what the name means.
    names = STATUTORY_NAMES if names is None else names
    for slug, name in sorted(names.items()):
        o = by_slug.get(slug)
        if o is None:
            continue                      # `statutory-name-slug-in-registry` reported it
        if o.get("name") != name or o.get(NAME_BASIS_KEY) != ENABLING_AUTHORITY_NAME:
            problems.append(Failure(
                "statutory-name-agrees", slug,
                f"registry has name {o.get('name')!r} on basis "
                f"{o.get(NAME_BASIS_KEY)!r}, this table says {name!r} was read off the "
                "body's enabling authority — run --apply"))
    for slug, o in sorted(by_slug.items()):
        if o.get(NAME_BASIS_KEY) == ENABLING_AUTHORITY_NAME and slug not in names:
            problems.append(Failure(
                "statutory-name-agrees", slug,
                f"registry records name {o.get('name')!r} as the statutory name and this "
                "table does not name the body at all. This file is the only thing that "
                "establishes a statutory name: either the row was written by something "
                "else, or a reviewed name was deleted from the table"))
    return problems


def apply_reviewed(cat, mapped=None, unmapped=None, names=None) -> int:
    """Write the reviewed values onto the registry rows. Returns the rows changed.

    RE-RUNNABLE AND BYTE-IDENTICAL, which the value assignment gives for free: a key that is
    already present keeps its position and its value, so the second run changes nothing and
    dumps the same bytes. `_proof_apply_writes_the_same_bytes_twice` keeps that permanent.

    It writes only the rows the table decides. A row the table says nothing about is LEFT
    ALONE rather than cleared, because clearing it would silently un-review a body — and
    `registry-agrees` reports that row instead, which is a human's question to answer.
    """
    want = reviewed(mapped, unmapped)
    names = STATUTORY_NAMES if names is None else names
    changed = 0
    for o in cat.get("organizations") or []:
        if not isinstance(o, dict):
            continue
        value = want.get(o.get("slug"))
        touched = False
        if value is not None and o.get("enabling_authority") != value:
            o["enabling_authority"] = value
            touched = True
        # THE NAME AND ITS BASIS, WRITTEN TOGETHER (#168). A `name` written without its basis
        # is a statutory name the registry still labels as the rules index's title, and a
        # basis written without its name is an OAR title claiming a statute gave it — the
        # false statement about Oregon law the field exists to make unwriteable. Both are
        # assigned rather than inserted, so a row that already holds them keeps its key order
        # and the second run dumps the same bytes.
        # NAME READER — MACHINERY: --apply writing the reviewed value into the field. It
        # operates on the key, not on the body's identity; WHICH name belongs there was
        # decided by a human reading the cited section, and is recorded in STATUTORY_NAMES.
        name = names.get(o.get("slug"))
        if name is not None and (o.get("name") != name
                                 or o.get(NAME_BASIS_KEY) != ENABLING_AUTHORITY_NAME):
            o["name"] = name
            o[NAME_BASIS_KEY] = ENABLING_AUTHORITY_NAME
            touched = True
        changed += bool(touched)
    return changed


def _report(problems) -> None:
    for p in problems:
        print(f"  FAIL [{p.rule}] {p.slug}: {p.detail}", file=sys.stderr)


def cmd_apply() -> int:
    """Write MAPPED/UNMAPPED into the registry. The only writer of `enabling_authority`."""
    cat = yaml.safe_load(CATALOG.read_text())
    orgs = cat["organizations"]
    text_lookups = name_text_lookups()
    problems = (audit_table(orgs, MAPPED, UNMAPPED, resolvable_citations(),
                            constitutional_resolver(published_constitutional_sections()))
                + audit_statutory_names(orgs, MAPPED, STATUTORY_NAMES, text_lookups)
                + audit_quote_checks(orgs, MAPPED, UNMAPPED, STATUTORY_NAMES, QUOTE_CHECKS,
                                     text_lookups))
    if problems:
        print("refusing to write: the reviewed tables do not match the corpus",
              file=sys.stderr)
        _report(problems)
        return 1

    changed = apply_reviewed(cat)
    if changed:
        CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True,
                                          width=100))
    print(f"{changed} row(s) written ({authority_census(orgs)})")
    print(f"  name: {name_census(orgs)}")
    # A row the tables cannot account for is left where it is and reported. --apply is not
    # allowed to resolve it by deleting a field a human may have put there deliberately.
    left = [p for p in audit_registry(orgs)
            if p.rule in ("registry-agrees", "statutory-name-agrees")]
    _report(left)
    return 1 if left else 0


def check() -> int:
    """Verify the reviewed table AND the registry it writes, from committed data alone."""
    orgs = yaml.safe_load(CATALOG.read_text())["organizations"]
    citations = resolvable_citations()
    # READ ONCE, and reported from the same read. The count in the report below is the
    # population the rule above resolved against, not a second scan that could differ.
    published = published_constitutional_sections()
    # READ ONCE TOO, for the same reason: `checked`/`could_not_check` below reports which
    # forms THIS read could resolve a name against, not a second read that could disagree.
    text_lookups = name_text_lookups()
    problems = (audit_table(orgs, MAPPED, UNMAPPED, citations,
                            constitutional_resolver(published))
                + audit_statutory_names(orgs, MAPPED, STATUTORY_NAMES, text_lookups)
                + audit_quote_checks(orgs, MAPPED, UNMAPPED, STATUTORY_NAMES, QUOTE_CHECKS,
                                     text_lookups)
                + audit_registry(orgs, MAPPED, UNMAPPED))
    if problems:
        print("the reviewed tables do not match the corpus:", file=sys.stderr)
        _report(problems)
        return 1

    # THREE FORMS RESOLVE, ONE DOES NOT, AND THE COUNTS SAY WHICH IS WHICH — never collapsed
    # into one "verified" figure (#211/#220). There used to be a permanent "form checked, not
    # resolved" line here, for the constitutional authorities, because nothing could resolve
    # them; since #196 the constitution resolves too, so that line retired — and #211 gives
    # it a real successor rather than leaving the retirement permanent: a session-law
    # authority is admitting evidence ADR 0003 accepts and this corpus cannot look up, so it
    # is counted on its own line, not folded into "resolved against the mirror" beside it.
    forms = collections.Counter(classify_authority(a)[0] for a in MAPPED.values())
    print(f"enabling-authority table is consistent with the corpus: "
          f"{authority_census(orgs)}.")
    print(f"  resolved against the mirror  : {forms['ors']} ORS, "
          f"{forms['executive-order']} executive order(s), "
          f"{forms['constitution']} constitutional")
    print(f"  form-checked, not resolved   : {forms['session-law']} session law(s) — this "
          f"corpus mirrors no session laws, so these are verified for SHAPE only "
          "(CONTEXT.md: 'could not check' is never reported as 'is correct')")
    print(f"  resolved against the {len(published)} mirrored sections of the Oregon "
          "Constitution (#196), the same way an ORS citation is; a constitutional statutory "
          "name is checked against its WHOLE article, not the one cited section (#220)")
    # THE NAMES, COUNTED SEPARATELY FROM THE AUTHORITIES, because carrying an authority is
    # not the same as having read a name off it (#168): 107 rows could have their statutory
    # name established and a much smaller number has. Reporting the two as one number would
    # present the population that COULD be reviewed as the one that HAS been.
    #
    # AND, SEPARATELY, HOW MANY OF THOSE COULD BE CHECKED AGAINST TEXT (#220's acceptance
    # criterion 4: "The report states how many names were checked and how many could not
    # be"). A name is only ever admitted to STATUTORY_NAMES once `audit_statutory_names` has
    # passed it — so on a green run every one here was in fact checked against mirrored text,
    # and `could_not_check` is structurally zero today; it stops being zero the day a name is
    # recorded for a form `name_text_lookups` cannot read (a session law, #211), which is
    # exactly the case this line exists to make visible rather than silently implied.
    checkable_forms = frozenset(text_lookups.keys())
    name_forms = collections.Counter(
        classify_authority(MAPPED[slug])[0] for slug in STATUTORY_NAMES if slug in MAPPED)
    checked = sum(v for form, v in name_forms.items() if form in checkable_forms)
    could_not_check = len(STATUTORY_NAMES) - checked
    print(f"statutory names read off those authorities: {len(STATUTORY_NAMES)} of "
          f"{len(MAPPED)} reviewed authorities ({checked} checked against mirrored text, "
          f"{could_not_check} could not be); registry: {name_census(orgs)}")
    # THE AGENT QUOTE-CHECKS, COUNTED BY WHAT THEY ARE THE RECORD OF (operator decision
    # 2026-10-30). Every quotation below was re-matched word for word against the mirror by
    # the audit above, which is why this line can be printed at all on a green run; the
    # rows reviewed by a human before that decision carry no quotation and are the remainder.
    quoted = {slug for slug, pairs in QUOTE_CHECKS.items()}
    placements = sum(1 for o in orgs for e in relation_entries(o)
                     if isinstance(e, dict) and e.get("source") == STATUTE_SOURCE)
    print(f"agent quote-checks: {sum(len(v) for v in QUOTE_CHECKS.values())} quotation(s) "
          f"for {len(quoted)} body(ies), each matched word for word against the mirrored "
          f"section on this run — {len(quoted & set(MAPPED))} reviewed authorities, "
          f"{len(quoted & set(UNMAPPED))} reviewed absences, "
          f"{len(quoted & set(STATUTORY_NAMES))} statutory names, {placements} statute "
          f"placement(s) (every one of them quoted)")
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

    EVERY BODY IS MADE UP, and has to be. A row in this table pairs a body with what created
    it — a claim about Oregon law, admitting evidence under ADR 0003 — and a fixture is not
    review. ORS has no chapter 999 and no executive order is numbered 99-99, so nothing here
    can be mistaken for a reviewed row or copied into one.

    THE CONSTITUTIONAL CITATION IS THE EXCEPTION, and #196 is why it had to become one. It
    used to be `Or. Const. Art. XVII, sec. 99` — ADR 0005's own example of a citation that is
    well-formed and unverifiable — and it sat here to prove the gate ACCEPTED it. It cannot
    be a made-up citation any more, because a made-up one no longer passes: the whole
    Constitution is mirrored, so the only constitutional citations that resolve are the real
    ones. `Or. Const. Art. XVII, sec. 1` is a real section of the Constitution attached to a
    body that does not exist, which is still not a reviewed row and still cannot be copied
    into one.
    """
    mapped = {"board-of-imaginary-affairs": "ORS 999.999",
              "office-of-imagined-orders": "Executive Order 99-99",
              "imaginary-constitutional-office": "Or. Const. Art. XVII, sec. 1",
              # THE FOURTH FORM (#211). Session laws are not resolved against anything, so
              # this citation does not need to be well-formed-but-fake the way the other
              # three do to avoid being mistaken for a reviewed row — it only needs to be
              # SPELLED like one, and no session law of Oregon 1899 created anything, because
              # Oregon did not hold a 1899 regular session under this numbering.
              "legislative-imaginary-office": "Oregon Laws 1899, chapter 999"}
    unmapped = {"imaginary-affairs-inspection-division":
                "Part of the Board of Imaginary Affairs; nothing separately constitutes "
                "it (ADR 0004), so there is no enabling authority to record."}
    want = reviewed(mapped, unmapped)
    orgs = [{"slug": slug, "name": slug.replace("-", " ").title(),
             "enabling_authority": want[slug]} for slug in sorted(want)]
    # THE THIRD STATE, carried by the fixture itself: a body no table mentions and whose row
    # holds no `enabling_authority` key. It is the state every not-yet-reviewed committed row
    # is in, however many that is today (`authority_census()`, printed by `--check`), and
    # the fixture has to pass cleanly with it — a gate that treated "nobody has looked yet"
    # as a violation would make the honest default impossible to hold.
    orgs.append({"slug": "board-nobody-has-reviewed", "name": "Board Nobody Has Reviewed"})
    # THE STATUTORY NAME, READ OFF ONE OF THOSE AUTHORITIES (#168), and the mirrored text it
    # was read off — for one body of each RESOLVABLE form (#220 widens this fixture from one
    # body to three, matching the widened gate: ORS, executive order and constitution each
    # get a name that is genuinely present in their synthetic text, so the base fixture
    # proves the TRUE POSITIVE for every resolvable form on every single case run via the
    # "fixture passes cleanly" assertion below, not only in a dedicated case). The rest carry
    # their OAR title under `unverified-oar-title`, which is the state 185 of the 189
    # committed rows are in and the one a fixture holding only reviewed rows would make
    # impossible to hold. `legislative-imaginary-office` (session law) is deliberately NOT
    # among them: #211's form does not resolve, so there is no text a name could be checked
    # against, and giving it one here would test a mechanism this form does not have.
    #
    # THE TEXT IS SYNTHETIC AND THE CITATIONS ARE IMPOSSIBLE, for the reason every other
    # value here is: this proves the gate reads the cited text and refuses a name it does not
    # print, and real mirrored text quoted here would read as a verdict on what it names.
    names = {"board-of-imaginary-affairs": "Board of Imaginary Affairs",
             "office-of-imagined-orders": "Office of Imagined Orders",
             "imaginary-constitutional-office": "Board of Imaginary Amendments"}
    texts = {"ORS 999.999": "Board of Imaginary Affairs; appointment. There is established "
                            "the Board of Imaginary Affairs. The board consists of seven "
                            "members appointed by the Governor."}
    eo_texts_ = {"Executive Order 99-99": "Office of Imagined Orders; established. There is "
                                          "established the Office of Imagined Orders."}
    # KEYED BY ARTICLE SLUG, not by citation — `constitution_name_lookup()` parses the
    # citation and looks up its ARTICLE, so one entry here serves any section citation of
    # Article XVII (#220's own acceptance criterion: resolved against the article, not the
    # one cited section). "xvii" is `orconst_article_slug("XVII")`.
    const_texts = {"xvii": "Board of Imaginary Amendments; established. There is "
                          "established the Board of Imaginary Amendments."}
    for o in orgs:
        if o["slug"] in names:
            o["name"] = names[o["slug"]]
            o[NAME_BASIS_KEY] = ENABLING_AUTHORITY_NAME
        else:
            o[NAME_BASIS_KEY] = UNVERIFIED_OAR_TITLE
    # THE CONSTITUTIONAL CITATION'S OWN RESOLUTION (does `Or. Const. Art. XVII, sec. 1` name
    # a mirrored section at all) IS STILL CHECKED AGAINST THE REAL MIRROR, and the ORS and
    # executive-order citations still against made-up strings. That asymmetry is a decision.
    # A synthetic `citations` set keeps those two proofs off a 37,465-file scan and costs
    # nothing, because membership of a set is the whole of what the rule does. The
    # constitutional rule is not a membership test — it is the resolver in
    # `citation_schemes`, reading the committed catalog — and a synthetic stand-in for it
    # would be a second implementation of the thing under proof, which is how a proof starts
    # passing for the wrong reason. Still no network and still no read of the committed
    # registry; what it reads is one catalog and the 339 committed section documents.
    #
    # THE NAME-TEXT LOOKUPS ARE SYNTHETIC FOR ALL THREE FORMS, including the constitutional
    # one, unlike the resolution above — `name_text_lookups()` composes them from plain
    # {key: text} dicts (`texts`, `eo_texts_`, `const_texts`), and reading a name off text
    # already fetched is not the resolver `constitutional_resolver` is; a synthetic stand-in
    # for THIS half is not a second implementation of anything under proof.
    # THE AGENT QUOTE-CHECK (2026-10-30), and the one STATUTE PLACEMENT the fixture carries so
    # `statute-placement-has-a-quote` has something to refuse. The quotation is a true
    # excerpt of the synthetic text above, with the fixture's name in it.
    quotes = {"board-of-imaginary-affairs": [("ORS 999.999",
                                              "There is established the Board of "
                                              "Imaginary Affairs.")]}
    for o in orgs:
        if o["slug"] == "board-of-imaginary-affairs":
            o["relations"] = [{"target": "office-of-imagined-orders", "source": "statute",
                               "kind": "administered_by",
                               "basis": "reviewed-enabling-authority",
                               "authority": "ORS 999.999"}]
    return {"mapped": mapped, "unmapped": unmapped, "orgs": orgs, "names": names,
            "quotes": quotes,
            "texts": texts, "eo_texts": eo_texts_, "const_texts": const_texts,
            "text_lookups": name_text_lookups(ors_texts=texts, eo=eo_texts_,
                                              constitution=const_texts),
            "citations": {"ORS 999.999", "Executive Order 99-99"},
            "why_unresolved": constitutional_resolver(published_constitutional_sections())}


def _set(f, slug, authority):
    """Put one authority in the table AND on its registry row, so a case breaks exactly one
    rule. Changing only one of the two would also trip `registry-agrees`, and a case that
    fires two rules stops saying which one it is about."""
    f["mapped"][slug] = authority
    for o in f["orgs"]:
        if o["slug"] == slug:
            o["enabling_authority"] = authority


def _set_name(f, slug, name):
    """Put one statutory name in the table AND on its registry row, so a case breaks exactly
    one rule — the same reason `_set` above writes both halves.

    NAME READER — MACHINERY: a selftest helper writing the field on a synthetic fixture. No
    body here is real (see `_fixture`), so nothing it writes is a claim about any name."""
    f["names"][slug] = name
    for o in f["orgs"]:
        if o["slug"] == slug:
            o["name"] = name
            o[NAME_BASIS_KEY] = ENABLING_AUTHORITY_NAME


def _audit(f) -> list[Failure]:
    return (audit_table(f["orgs"], f["mapped"], f["unmapped"], f["citations"],
                        f["why_unresolved"])
            + audit_statutory_names(f["orgs"], f["mapped"], f["names"], f["text_lookups"])
            + audit_quote_checks(f["orgs"], f["mapped"], f["unmapped"], f["names"],
                                 f["quotes"], f["text_lookups"])
            + audit_registry(f["orgs"], f["mapped"], f["unmapped"], f["names"]))


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


def _case_session_law_malformed(f):
    """A session-law citation one punctuation mark from the accepted spelling (#211) —
    `catalog_agencies._proof_session_law_form_boundary` proves the same boundary at the
    `classify_authority` level directly, over nine near misses; this proves this file's OWN
    table-audit rule fires on one of them too, the same way `authority-that-cites-nothing`
    above proves `enabling-authority-that-is-not-an-authority` does in
    `catalog_agencies.py`."""
    _set(f, "legislative-imaginary-office", "Oregon Laws 1899, Chapter 999")


def _case_constitutional_section_the_page_does_not_print(f):
    """`Or. Const. Art. XVII, sec. 99` — ADR 0005's own example, and the citation this
    fixture used to CARRY as a passing row. The article is real, the section is not, and
    until #196 there was nothing to resolve it against: it was checked for form, and a form
    check is what it passed. It is admitting evidence under ADR 0003, so passing it admitted
    a body on evidence that does not exist."""
    _set(f, "imaginary-constitutional-office", "Or. Const. Art. XVII, sec. 99")


def _case_constitutional_article_the_page_does_not_print(f):
    """`Or. Const. Art. XX, sec. 1` — well-formed, and there is no Article XX. The other
    half of the same failure as the case above, and a DIFFERENT finding: the section case
    says the citation is wrong about a real article, this one says the article itself is
    not in the document."""
    _set(f, "imaginary-constitutional-office", "Or. Const. Art. XX, sec. 1")


def _case_constitutional_section_printed_but_not_published(f):
    """`Or. Const. Art. VI, sec. 9a` — one of the 32 sections the source page prints as a
    leadline and a repeal bracket with no text between them (ADR 0005). This is the case
    that must not be worded like the two above: the citation is RIGHT about what the page
    prints, and the corpus published nothing to point it at. A row citing a repealed
    section is a different error from a row citing a section that never existed."""
    _set(f, "imaginary-constitutional-office", "Or. Const. Art. VI, sec. 9a")


def _case_constitutional_article_with_no_sections(f):
    """`Or. Const. Art. XI-B, sec. 1` — the article is printed and carries no sections at
    all, which the catalog records as `no-sections`. A third wording, because a repealed
    ARTICLE and a repealed SECTION are not the same statement about the Constitution."""
    _set(f, "imaginary-constitutional-office", "Or. Const. Art. XI-B, sec. 1")


def _case_constitutional_numeral_that_names_two_articles(f):
    """`Or. Const. Art. VII, sec. 1` — the page prints that numeral TWICE, as (Amended) and
    (Original), and both are operative. It resolves to nothing BY REFUSING TO GUESS, which
    is not the same finding as the four above and must not be reported as one: the citation
    is not wrong, it is not yet a citation to one article. It may not stand as admitting
    evidence for that reason — evidence has to name the thing that admits — and the answer
    tells the reviewer which two citations to choose between."""
    _set(f, "imaginary-constitutional-office", "Or. Const. Art. VII, sec. 1")


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


def _case_statutory_name_for_a_body_with_no_reviewed_authority(f):
    """A statutory name for a body whose enabling authority nobody has recorded. The
    statutory name is the name a body's ENABLING AUTHORITY gives it (ADR 0003), so a name
    recorded against a body with no authority in MAPPED was read off nothing — and the body
    chosen here is in UNMAPPED, which is the sharper version: someone looked and found there
    is no enabling authority at all, so there is no section that could name it."""
    _set_name(f, "imaginary-affairs-inspection-division",
              "Imaginary Affairs Inspection Division")


def _case_statutory_name_the_cited_section_does_not_print(f):
    """A name the authority does not name the body. This is what separates a reviewed name
    from a plausible one: the row cites a section, the section is mirrored, and the name does
    not appear in it. Without this rule the value is an assertion that someone decided —
    which is what `manual: true` was retired for (ADR 0003) — sitting in the field three
    sibling corpora read as what Oregon law calls the body."""
    _set_name(f, "board-of-imaginary-affairs", "Bureau of Imaginary Affairs")


def _case_statutory_name_the_executive_order_does_not_print(f):
    """The same failure, on the executive-order form (#220). Before #220 this form could not
    be checked at all; now it is checked exactly as the ORS form is, and a name the mirrored
    order does not print must be refused the same way — a passing base fixture that never
    exercised a WRONG executive-order name would prove the form is read, not that it is
    read CORRECTLY."""
    _set_name(f, "office-of-imagined-orders", "Bureau of Imagined Orders")


def _case_statutory_name_the_constitution_does_not_print(f):
    """The same failure, on the constitutional form (#220), resolved against the WHOLE
    article this fixture's synthetic text stands in for. Before #220 this form could not be
    checked at all — see `_case_statutory_name_on_an_authority_this_gate_cannot_read`'s
    history, now told about a form this corpus genuinely cannot check instead."""
    _set_name(f, "imaginary-constitutional-office", "Board of Imaginary Repeals")


def _case_statutory_name_on_an_authority_this_gate_cannot_read(f):
    """A name recorded against an authority whose text this gate cannot reach. A session law
    is an enabling authority (ADR 0003, #211) and this corpus mirrors none — unlike the
    executive order and the constitutional article beside it, BOTH resolvable and BOTH
    text-checkable since #220 — so a name recorded against one is a name nobody checked. It
    is REPORTED as unchecked rather than passed over, because "could not check" is never
    reported as "is not there" (CONTEXT.md). This is the third form in that state; it used to
    be the executive order, until #220 closed that gap."""
    _set(f, "board-of-imaginary-affairs", "Oregon Laws 1899, chapter 1")


def _case_statutory_name_cited_to_a_section_the_mirror_does_not_hold(f):
    """A name recorded against an ORS citation whose section this corpus does not carry.
    There is no text to check the name against, and the wrong answer — the one this case
    exists to refuse — is "the statute does not print that name", which is a statement about
    Oregon law drawn from a file that is not here. "Could not check" is never reported as "is
    not there" (CONTEXT.md).

    THE RULE IS NOT ENOUGH HERE, and `_STATUTORY_NAME_ANSWERS` below is the half that is.
    This case and `statutory-name-the-cited-section-does-not-print` fire the SAME rule, so
    asserting on the rule keeps passing when the two collapse into one message — which is
    exactly what the code did before #168's review: the missing document was coerced to an
    empty string and reported as a statute that does not print the name.

    The citation is added to `citations` as well as to the table, so the case breaks exactly
    one rule: a citation the corpus does not carry AT ALL would also trip
    `authority-resolves`. What is missing here is the TEXT, which is the state a fetch
    failure or a half-ingested chapter leaves behind."""
    f["citations"].add("ORS 999.997")
    _set(f, "board-of-imaginary-affairs", "ORS 999.997")


def _case_statutory_name_that_is_not_a_name(f):
    """A blank where the name should be. The value becomes `name` on a registry row, which
    three sibling corpora read as what Oregon law calls the body — and a whitespace string
    passes every "is the key present" test while making the body unfindable by the only name
    it has. The registry's own contract refuses it too (`findable-by-both-names`); this
    refuses it before it can be written."""
    _set_name(f, "board-of-imaginary-affairs", "   ")


def _case_statutory_name_for_a_slug_that_is_not_in_the_registry(f):
    """A name for a body this registry does not carry. There is no row for it to be written
    onto, so --apply would report success having written nothing — the silent no-op that
    `slug-in-registry` already refuses one table over."""
    f["names"]["board-of-nowhere-in-particular"] = "Board of Nowhere in Particular"


def _case_registry_name_no_table_establishes(f):
    """A registry row claiming its name is the statutory one, which this table does not name.
    This file is the only thing that establishes a statutory name, so the row was written by
    something else — the drift #175 exists to prevent, on the field ADR 0003 calls the risky
    half. It is the mirror of `registry-agrees` one field over, and it can fire while this
    table is empty, which is exactly when it matters."""
    for o in f["orgs"]:
        if o["slug"] == "board-nobody-has-reviewed":
            o[NAME_BASIS_KEY] = ENABLING_AUTHORITY_NAME


def _case_registry_name_that_did_not_follow_the_table(f):
    """A reviewed name that never reached the row. The table says the statute calls this body
    one thing and the registry publishes another, and every consumer reads the registry — so
    the review is recorded in a place nobody joins on and the file states the name it was
    supposed to replace."""
    for o in f["orgs"]:
        if o["slug"] == "board-of-imaginary-affairs":
            o["name"] = "Board Of Imaginary Affairs"


def _case_quote_for_a_slug_that_is_not_in_the_registry(f):
    """A quotation for a body this registry does not carry — a review record with no row to
    be the record of."""
    f["quotes"]["board-of-nowhere-in-particular"] = [
        ("ORS 999.999", "There is established the Board of Imaginary Affairs.")]


def _case_quote_with_nothing_to_be_the_review_of(f):
    """A quotation on a body that is in no table and carries no statute placement. The
    quotation is true and supports no claim, which is how a record outlives the decision it
    was taken for."""
    f["quotes"]["board-nobody-has-reviewed"] = [
        ("ORS 999.999", "There is established the Board of Imaginary Affairs.")]


def _case_quote_that_is_a_fragment(f):
    """Three words that appear in a great many sections. A fragment that short matches
    anything, so matching it proves nothing about the section it is attached to."""
    f["quotes"]["board-of-imaginary-affairs"] = [("ORS 999.999", "There is established")]


def _case_quote_the_section_does_not_say(f):
    """A quotation the mirrored section does not contain word for word — the record of an
    agent's reading that no longer, or never did, match the text."""
    f["quotes"]["board-of-imaginary-affairs"] = [
        ("ORS 999.999", "There is established the Bureau of Imaginary Affairs.")]


def _case_quote_from_a_form_this_gate_cannot_read(f):
    """A quotation from a session law. This corpus mirrors none, so there is no text to match
    it against — 'could not check', which must not read as 'matches'."""
    f["quotes"]["board-of-imaginary-affairs"] = [
        ("Oregon Laws 1899, chapter 1", "There is established the Board of Imaginary Affairs.")]


def _case_quote_from_a_section_the_mirror_does_not_hold(f):
    """A quotation cited to an ORS section this corpus does not carry. Absent text is not text
    that disagrees."""
    f["quotes"]["board-of-imaginary-affairs"] = [
        ("ORS 999.997", "There is established the Board of Imaginary Affairs.")]


def _case_statutory_name_no_quotation_prints(f):
    """A name whose slug has quotations, none of which prints it: the sentence an agent
    quoted is about something else in the section."""
    f["quotes"]["board-of-imaginary-affairs"] = [
        ("ORS 999.999", "The board consists of seven members appointed by the Governor.")]


def _case_statute_placement_with_no_quotation(f):
    """A `source: statute` relation whose authority names a section QUOTE_CHECKS holds no
    sentence from. The placement is a claim about Oregon law with nothing set beside it."""
    for o in f["orgs"]:
        if o["slug"] == "board-of-imaginary-affairs":
            o["relations"][0]["authority"] = "ORS 999.998"


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
    ("session-law-malformed", _case_session_law_malformed, "authority-form"),
    ("constitutional-section-the-page-does-not-print",
     _case_constitutional_section_the_page_does_not_print, "authority-resolves"),
    ("constitutional-article-the-page-does-not-print",
     _case_constitutional_article_the_page_does_not_print, "authority-resolves"),
    ("constitutional-section-printed-but-not-published",
     _case_constitutional_section_printed_but_not_published, "authority-resolves"),
    ("constitutional-article-with-no-sections",
     _case_constitutional_article_with_no_sections, "authority-resolves"),
    ("constitutional-numeral-that-names-two-articles",
     _case_constitutional_numeral_that_names_two_articles, "authority-resolves"),
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
    # THE STATUTORY NAME'S OWN RULES (#168). The name is a second fact read off the same
    # section during the same review, and each of these is a way it can be wrong that leaves
    # a row looking entirely healthy from the outside.
    ("statutory-name-for-a-body-with-no-reviewed-authority",
     _case_statutory_name_for_a_body_with_no_reviewed_authority,
     "statutory-name-has-an-authority"),
    ("statutory-name-the-cited-section-does-not-print",
     _case_statutory_name_the_cited_section_does_not_print,
     "statutory-name-in-the-cited-text"),
    ("statutory-name-the-executive-order-does-not-print",
     _case_statutory_name_the_executive_order_does_not_print,
     "statutory-name-in-the-cited-text"),
    ("statutory-name-the-constitution-does-not-print",
     _case_statutory_name_the_constitution_does_not_print,
     "statutory-name-in-the-cited-text"),
    ("statutory-name-on-an-authority-this-gate-cannot-read",
     _case_statutory_name_on_an_authority_this_gate_cannot_read,
     "statutory-name-in-the-cited-text"),
    ("statutory-name-cited-to-a-section-the-mirror-does-not-hold",
     _case_statutory_name_cited_to_a_section_the_mirror_does_not_hold,
     "statutory-name-in-the-cited-text"),
    ("statutory-name-that-is-not-a-name", _case_statutory_name_that_is_not_a_name,
     "statutory-name-is-a-name"),
    ("statutory-name-for-a-slug-that-is-not-in-the-registry",
     _case_statutory_name_for_a_slug_that_is_not_in_the_registry,
     "statutory-name-slug-in-registry"),
    ("registry-name-no-table-establishes", _case_registry_name_no_table_establishes,
     "statutory-name-agrees"),
    ("registry-name-that-did-not-follow-the-table",
     _case_registry_name_that_did_not_follow_the_table, "statutory-name-agrees"),
    # THE AGENT QUOTE-CHECK'S OWN RULES (operator decision 2026-10-30, ADR 0003's amendment).
    # An agent's reading counts as the review only because a machine can re-perform it, and
    # each of these is a way the record can stop being that while the row beside it looks fine.
    ("quote-for-a-slug-that-is-not-in-the-registry",
     _case_quote_for_a_slug_that_is_not_in_the_registry, "quote-slug-in-registry"),
    ("quote-with-nothing-to-be-the-review-of", _case_quote_with_nothing_to_be_the_review_of,
     "quote-has-a-reviewed-row"),
    ("quote-that-is-a-fragment", _case_quote_that_is_a_fragment, "quote-is-a-quote"),
    ("quote-the-section-does-not-say", _case_quote_the_section_does_not_say,
     "quote-in-the-cited-text"),
    ("quote-from-a-form-this-gate-cannot-read", _case_quote_from_a_form_this_gate_cannot_read,
     "quote-in-the-cited-text"),
    ("quote-from-a-section-the-mirror-does-not-hold",
     _case_quote_from_a_section_the_mirror_does_not_hold, "quote-in-the-cited-text"),
    ("statutory-name-no-quotation-prints", _case_statutory_name_no_quotation_prints,
     "statutory-name-in-a-quote"),
    ("statute-placement-with-no-quotation", _case_statute_placement_with_no_quotation,
     "statute-placement-has-a-quote"),
]


# The five constitutional citations above all produce ONE rule, `authority-resolves`, and
# `_CASES` asserts on the rule. That is not enough here and it is the whole point of #196:
# the rule firing says the row is not admitted, and the DETAIL is the only thing that says
# whether the reviewer wrote the wrong article, wrote the wrong section, cited a section
# Oregon repealed, cited an article Oregon repealed, or wrote a numeral that names two
# operative articles. Collapsing any pair of those into one message would keep every case
# above passing. Each row is a citation, a phrase its answer MUST carry, and a phrase it must
# NOT — the second half is what stops a message from being made vaguer until it fits
# everything.
#
# THE PHRASES ARE AUTHORED IN `citation_schemes._resolve_or_const`, which is where the five
# answers are written, so rewording one there fails this proof. That is the intended
# coupling and not an accident of matching prose: `citation_schemes._selftest` asserts on
# the same phrases from the other side, and a message may not stop distinguishing what it
# distinguishes without a gate noticing. The distinctness check below is the half that does
# NOT depend on the wording — it fails on any two answers being the same string, whatever
# they say.
_KINDS_OF_NOTHING = [
    ("Or. Const. Art. XVII, sec. 99", "prints no section 99", "not published"),
    ("Or. Const. Art. XX, sec. 1", "prints no Article XX", "not published"),
    ("Or. Const. Art. VI, sec. 9a", "was not published by this corpus", "prints no section"),
    ("Or. Const. Art. XI-B, sec. 1", "carries no sections", "prints no Article"),
    ("Or. Const. Art. VII, sec. 1", "Choosing one would be a guess", "prints no Article"),
]


# THE SAME PROBLEM ONE RULE OVER, AND THE SAME ANSWER (#168). Three different things can go
# wrong with a statutory name recorded against a mirrored section, and two of them produce
# `statutory-name-in-the-cited-text` — so `_CASES`, which asserts on the RULE, passes whether
# or not the two are told apart. They were not: a citation naming no mirrored document was
# coerced to an empty string and reported as a statute that does not print the name, which is
# a claim about Oregon law drawn from a file this corpus does not hold.
#
# Each row is (the authority the table cites, a phrase the answer MUST carry, a phrase it
# must NOT). The second half is what stops a message from being made vaguer until it fits
# both — the same discipline `_KINDS_OF_NOTHING` keeps above, for the same reason.
_STATUTORY_NAME_ANSWERS = [
    ("ORS 999.999", "does not appear anywhere in the mirrored text", "could not check"),
    ("ORS 999.997", "could not check", "does not appear anywhere"),
    # THE THIRD ROW MOVED FROM AN EXECUTIVE-ORDER CITATION TO A SESSION-LAW ONE (#211/#220).
    # Before #220 an executive order sat here as the exemplar of "a form this gate cannot
    # read the text of"; #220 closes that gap, so the exemplar moves to the one form #211
    # opened that is STILL in that state by design — this corpus mirrors no session laws.
    ("Oregon Laws 1899, chapter 1", "cannot read the text of", "does not appear anywhere"),
]


# THE SAME PROBLEM AS ABOVE, FOR A QUOTATION (operator decision 2026-10-30). Three different
# things stand between a quotation and the text it claims to be from, and two of them produce
# `quote-in-the-cited-text` — so `_CASES`, which asserts on the RULE, passes whether or not
# they are told apart. Each row is (the citation, a phrase the answer MUST carry, a phrase it
# must NOT).
_QUOTE_ANSWERS = [
    ("ORS 999.999", "does not appear word for word", "could not check"),
    ("ORS 999.997", "could not check", "does not appear word for word"),
    ("Oregon Laws 1899, chapter 1", "cannot read the", "does not appear word for word"),
]


def _proof_the_ways_a_quote_goes_unchecked_are_told_apart() -> int:
    """A quotation the section does not say, one the mirror cannot supply the section for and
    one whose form this gate cannot read each say which they are, and no two say the same
    thing — a reviewer re-reads a wrong quotation, but a record nobody could re-perform is a
    different finding, and 'could not check' is never reported as 'matches' or as 'differs'."""
    bad, answers = 0, []
    for citation, must, must_not in _QUOTE_ANSWERS:
        f = _fixture()
        f["quotes"]["board-of-imaginary-affairs"] = [
            (citation, "There is established the Bureau of Imaginary Affairs."
             if citation == "ORS 999.999"
             else "There is established the Board of Imaginary Affairs.")]
        details = [p.detail for p in _audit(f) if p.rule == "quote-in-the-cited-text"]
        if len(details) != 1:
            print(f"FAIL quote-answers-{citation}: expected one answer, got {details}",
                  file=sys.stderr)
            bad += 1
            continue
        answers.append(details[0])
        if must not in details[0] or must_not in details[0]:
            print(f"FAIL quote-answers-{citation}: {details[0]!r} must carry {must!r} and "
                  f"must not carry {must_not!r}", file=sys.stderr)
            bad += 1
    if len(set(answers)) != len(answers):
        print("FAIL quote-answers-are-distinct: two ways of not matching a quotation read "
              "alike", file=sys.stderr)
        bad += 1
    return bad


def _proof_the_ways_a_name_goes_unchecked_are_told_apart() -> int:
    """Each way `statutory-name-in-the-cited-text` fires says WHICH it is, and no two of them
    say the same thing.

    A reviewer acts differently on each: a name the section does not print is a wrong name, a
    citation with no mirrored text is a corpus to fix before the name can be judged, and an
    authority form this gate cannot read is a gate to extend. One message for two of those
    would send a reviewer to rewrite a name that was never checked."""
    bad = 0
    answers = []
    for authority, must, must_not in _STATUTORY_NAME_ANSWERS:
        f = _fixture()
        f["citations"].add(authority)
        # The name stays what the table already records; only the authority moves, so the
        # section cited is the only thing that differs between the three runs.
        _set(f, "board-of-imaginary-affairs", authority)
        f["names"]["board-of-imaginary-affairs"] = "Bureau of Imaginary Affairs" \
            if authority == "ORS 999.999" else "Board of Imaginary Affairs"
        for o in f["orgs"]:
            if o["slug"] == "board-of-imaginary-affairs":
                o["name"] = f["names"]["board-of-imaginary-affairs"]
        got = [p for p in audit_statutory_names(f["orgs"], f["mapped"], f["names"],
                                                f["text_lookups"])
               if p.rule == "statutory-name-in-the-cited-text"]
        if len(got) != 1:
            print(f"FAIL statutory-name-answer for {authority}: expected one answer, got "
                  f"{got!r}", file=sys.stderr)
            bad += 1
            continue
        detail = got[0].detail
        answers.append(detail)
        if must not in detail:
            print(f"FAIL statutory-name-answer for {authority}: {detail!r} does not say "
                  f"{must!r}", file=sys.stderr)
            bad += 1
        if must_not in detail:
            print(f"FAIL statutory-name-answer for {authority}: {detail!r} says {must_not!r},"
                  " which is a different finding", file=sys.stderr)
            bad += 1
    # THE HALF THAT DOES NOT DEPEND ON THE WORDING: no two answers may be the same string,
    # whatever they say.
    if len(set(answers)) != len(answers):
        print(f"FAIL statutory-name-answers-are-distinct: {answers!r}", file=sys.stderr)
        bad += 1
    return bad


def _proof_the_kinds_of_nothing_are_told_apart() -> int:
    """Five citations that resolve to nothing, and five different answers.

    ADR 0005 established three kinds of "nothing" and #195 found the fourth; a registry row
    is where they matter most, because an enabling authority is ADMITTING evidence and
    withdrawing it for the wrong reason sends a reviewer to re-read the wrong document.
    """
    why_unresolved = constitutional_resolver(published_constitutional_sections())
    bad, seen = 0, {}
    for citation, must, must_not in _KINDS_OF_NOTHING:
        why = why_unresolved(citation)
        if why is None:
            print(f"FAIL kinds-of-nothing: {citation} resolved to a mirrored section",
                  file=sys.stderr)
            bad += 1
            continue
        if must not in why:
            print(f"FAIL kinds-of-nothing: {citation} was answered with {why!r}, which "
                  f"does not say {must!r}", file=sys.stderr)
            bad += 1
        if must_not in why:
            print(f"FAIL kinds-of-nothing: {citation} was answered with {why!r}, which "
                  f"says {must_not!r} — that is a different finding", file=sys.stderr)
            bad += 1
        if why in seen:
            print(f"FAIL kinds-of-nothing: {citation} and {seen[why]} were given the same "
                  f"answer, {why!r}", file=sys.stderr)
            bad += 1
        seen[why] = citation
    return 1 if bad else 0


def _proof_an_unreadable_mirror_is_not_an_absent_one() -> int:
    """CONTEXT.md's overriding rule, on the population where breaking it is worst: with no
    documents in `constitution/`, every constitutional authority would resolve to nothing
    and be reported as a citation to a section that does not exist — admitting evidence
    withdrawn from the Secretary of State because a directory was empty.

    It must refuse to answer instead, the way `_executive_order_citations` does.
    """
    with tempfile.TemporaryDirectory() as empty:
        try:
            published_constitutional_sections(pathlib.Path(empty))
        except SystemExit as exit_:
            if "refusing" in str(exit_):
                return 0
            print(f"FAIL unreadable-mirror-is-not-an-absent-one: exited with {exit_!s}",
                  file=sys.stderr)
            return 1
    print("FAIL unreadable-mirror-is-not-an-absent-one: an empty constitution/ was read as a "
          "mirror, so every constitutional authority resolves against documents that are "
          "not there", file=sys.stderr)
    return 1


def _proof_a_catalogued_section_with_no_document_is_not_resolved() -> int:
    """The catalog saying a section is published and `constitution/` not carrying it. It is
    an answer about THIS CORPUS rather than about the Constitution, and it must not be
    worded like the five that are — a reviewer sent to re-read Article XVII because a file
    is missing has been told the wrong thing.

    Proved against a mirror holding one document, because no committed state can produce it:
    `ingest_constitution.py --check` is the gate that keeps the catalog and the directory in
    agreement, and this proof exists for the window in which that gate is failing.
    """
    why = constitutional_resolver({"orconst-art-i-sec-1"})("Or. Const. Art. XVII, sec. 1")
    if why and "is not on disk" in why and "ingest_constitution.py --check" in why:
        return 0
    print("FAIL catalogued-section-with-no-document-is-not-resolved: a section the catalog "
          f"records as published and the mirror does not carry was answered with {why!r}",
          file=sys.stderr)
    return 1


def _proof_a_citation_the_scheme_refuses_is_not_called_resolved() -> int:
    """A string that is not a constitutional citation at all. `--check` classifies the form
    before it gets here, so this is the guard for the function being PUBLIC: answering None
    means "it resolves", and saying that about a string nothing looked at is the one answer
    a gate on admitting evidence may never give (CONTEXT.md — "could not check" is never
    "is not there", and its mirror image is just as false).

    `ORS 183.310` is the sharpest case, because it is a real citation to a real section of
    something else.
    """
    why_unresolved = constitutional_resolver(published_constitutional_sections())
    bad = 0
    for other in ("ORS 183.310", "Article VI, section 1", "U.S. Const. Art. VI, sec. 1", ""):
        why = why_unresolved(other)
        if why is None or "does not recognise it" not in why:
            print(f"FAIL citation-the-scheme-refuses-is-not-called-resolved: {other!r} was "
                  f"answered with {why!r}", file=sys.stderr)
            bad += 1
    return 1 if bad else 0


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


def _proof_article_texts_actually_concatenate() -> int:
    """`constitution_article_texts()` ITSELF, called for real — not the synthetic
    `const_texts` dict `_fixture()` substitutes for it everywhere else in this file's
    selftest. That substitution is deliberate (see `_fixture`'s own comment: the concatenation
    is what is under proof, and a synthetic stand-in for it would be a second implementation
    of the thing being tested), but it means nothing here previously called the real function
    at all — the acceptance criterion it exists to meet (#220: resolved against the WHOLE
    article, not the one cited section) was covered only by `--check` against the one
    committed row that happens to exercise it. This proof builds a two-section article in a
    temp directory — the shape the docstring says `root` was added for — and checks that a
    name printed only in the second section is found when the citation names the first."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / "orconst-art-xix-sec-1.md").write_text(
            "---\ntitle: \"Creation of the Imaginary Council\"\n---\n"
            "There is created the Imaginary Council of Oregon.\n")
        (root / "orconst-art-xix-sec-2.md").write_text(
            "---\ntitle: \"Duties\"\n---\n"
            "The Board of Imaginary Amendments Overseers shall advise the Council.\n")
        texts = constitution_article_texts(root=root)
    if "xix" not in texts:
        print("FAIL article-texts-actually-concatenate: no 'xix' key in "
              f"{sorted(texts)!r}", file=sys.stderr)
        return 1
    if "Imaginary Council" not in texts["xix"] or "Overseers" not in texts["xix"]:
        print("FAIL article-texts-actually-concatenate: section 1's citation must resolve "
              f"to BOTH sections' text; got {texts['xix']!r}", file=sys.stderr)
        return 1
    return 0


def _proof_eo_texts_concatenate_on_collision() -> int:
    """`eo_texts()`, called for real against the committed mirror: 526 files carry only 523
    distinct citations (`Executive Order 03-03`, `08-16` and `24-15` each have a companion
    file), and a dict built by last-write-wins would silently drop one text per collision —
    for `24-15`, the AMENDED one, because `eo-24-15-amended.md` sorts before `eo-24-15.md`.
    Proves the fix reads as text from BOTH files, not the sort order's winner alone."""
    texts = eo_texts()
    combined = texts.get("Executive Order 24-15", "")
    amended_only = pathlib.Path(
        EXECUTIVE_ORDERS, "eo-24-15-amended.md").read_text(errors="replace")
    base_only = pathlib.Path(EXECUTIVE_ORDERS, "eo-24-15.md").read_text(errors="replace")
    # A marker string unlikely to appear in the other file: the last dozen non-whitespace
    # characters of each file's body, past its front matter.
    amended_tail = " ".join(amended_only.split("---", 2)[-1].split())[-40:]
    base_tail = " ".join(base_only.split("---", 2)[-1].split())[-40:]
    if amended_tail not in combined or base_tail not in combined:
        print("FAIL eo-texts-concatenate-on-collision: 'Executive Order 24-15' must read "
              "as the text of BOTH eo-24-15.md and eo-24-15-amended.md, not the winner of "
              "a last-write-wins collision", file=sys.stderr)
        return 1
    return 0


def _proof_text_lookups_refuse_an_empty_mirror() -> int:
    """The refuse-on-empty guard `eo_texts()` and `constitution_article_texts()` each carry,
    proved directly rather than left to depend on `check()`/`cmd_apply()` always calling a
    guarded citation-set function first — which is ALL that protected them before this proof
    existed: nothing stopped a future caller from asking either for text against an empty
    mirror and quietly getting `{}`, which would make every name-against-text check read as
    "the authority does not print that name" instead of "there was nothing to check"
    (CONTEXT.md), the same failure `_proof_an_unreadable_mirror_is_not_an_absent_one` proves
    against for the constitution's CITATION half."""
    bad = 0
    with tempfile.TemporaryDirectory() as empty:
        for label, fn in (("eo_texts", lambda: eo_texts(root=pathlib.Path(empty))),
                          ("constitution_article_texts",
                           lambda: constitution_article_texts(root=pathlib.Path(empty)))):
            try:
                fn()
            except SystemExit as exit_:
                if "refusing" not in str(exit_):
                    print(f"FAIL text-lookups-refuse-an-empty-mirror ({label}): exited with "
                          f"{exit_!s}", file=sys.stderr)
                    bad += 1
                continue
            print(f"FAIL text-lookups-refuse-an-empty-mirror ({label}): an empty directory "
                  "was read as a mirror, so every name checked against this form would "
                  "read as absent from text that was never there", file=sys.stderr)
            bad += 1
    return 1 if bad else 0


_PROOFS = [_proof_apply_writes_the_same_bytes_twice,
           _proof_the_kinds_of_nothing_are_told_apart,
           _proof_the_ways_a_name_goes_unchecked_are_told_apart,
           _proof_the_ways_a_quote_goes_unchecked_are_told_apart,
           _proof_an_unreadable_mirror_is_not_an_absent_one,
           _proof_a_catalogued_section_with_no_document_is_not_resolved,
           _proof_a_citation_the_scheme_refuses_is_not_called_resolved,
           _proof_article_texts_actually_concatenate,
           _proof_eo_texts_concatenate_on_collision,
           _proof_text_lookups_refuse_an_empty_mirror]


def selftest() -> int:
    bad = sum(proof() for proof in _PROOFS)
    for name, mutate, rule in _CASES:
        f = _fixture()
        assert not _audit(f), f"fixture does not pass cleanly ({name}): {_audit(f)}"
        mutate(f)
        problems = _audit(f)
        if not any(p.rule == rule for p in problems):
            print(f"FAIL {name}: expected a [{rule}] problem, got {problems}",
                  file=sys.stderr)
            bad += 1
    # THE DECLARATION, GATED FROM BOTH SIDES (check_rule_ledger.py, adopted here by
    # #211/#220 — matching `catalog_agencies.py`'s own `_LEDGER.gaps()` call). A rule can go
    # undetected by being DECLARED WITH NO PROOF (did it fire during this run) or by being
    # EMITTED WITH NO DECLARATION (does the AST agree with CHECK_RULES); this module carried
    # neither direction before this ticket, the same state #320 found in `catalog_agencies`.
    gaps = _LEDGER.gaps()
    if gaps.emitted_but_undeclared or gaps.unemitted_but_declared:
        print("FAIL every-rule-this-module-can-report-is-declared: "
              f"emitted-not-declared={sorted(gaps.emitted_but_undeclared)} "
              f"declared-not-emitted={sorted(gaps.unemitted_but_declared)}", file=sys.stderr)
        bad += 1
    if gaps.unfired:
        print(f"FAIL every-declared-rule-was-watched-firing: unfired={sorted(gaps.unfired)}",
              file=sys.stderr)
        bad += 1
    print(f"{len(_CASES) + len(_PROOFS)} violation(s) demonstrated failing, "
          f"{_LEDGER.demonstrated_count} rule(s) declared, every one both emitted by this "
          "module and watched firing here"
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
