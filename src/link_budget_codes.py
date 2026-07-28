#!/usr/bin/env python3
"""Attach DAS budget agency codes to the agency registry.

  python3 src/link_budget_codes.py           # write budget_agency_code into agencies.yml
  python3 src/link_budget_codes.py --check   # verify the registry matches this table

WHY THIS EXISTS. `oregon-budget` reports spending against three-digit DAS agency codes
(`107` = Department of Administrative Services). This registry keys agencies on OAR chapter
assignment. Neither identifier appears in the other's source, and the NAME strings never
match — the budget dataset writes `ADMINISTRATIVE SRVCS, DEPT OF` where this registry writes
`Department of Administrative Services`. Without a stored mapping, joining spending to the
rules an agency issues means fuzzy-matching names at query time, forever, in both corpora.

WHY THE TABLE IS WRITTEN OUT LONGHAND. Every row below was proposed by a token-overlap
matcher and then reviewed by hand, and the review mattered: the matcher confidently paired
the *Legislative* Revenue Office with the Department of Revenue, the Commission on Judicial
Fitness and Disability with the Judicial Department, and the Legislative Commission on
Indian Services with DAS. Those are three fiscal claims that would have been attached to the
wrong legal entity. A generated mapping would have shipped them; a reviewed table does not.
It is also why UNMAPPED below is explicit rather than implied by absence — "we looked and
there is no counterpart" and "nobody has looked yet" must not be the same state.

THE MATCHER'S OWN BUGS, RECORDED because they are the reason not to trust one:
  * `HI-ED COORD CMSN` was split on the hyphen before abbreviation expansion, so the
    Higher Education Coordinating Commission scored near zero against a registry entry
    that is otherwise a perfect match.
  * expanding `REV` to `revenue` is what produced the Legislative Revenue Office error.
"""
from __future__ import annotations

import sys

import yaml

from repo_lib import REPO_ROOT

CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"

# code -> registry slug. Reviewed by hand, 2026-07-28.
MAPPING = {
    "100": "department-of-human-services",
    "104": None,
    "107": "department-of-administrative-services",
    "108": "mental-health-regulatory-agency",
    "109": "oregon-department-of-aviation",
    "114": "long-term-care-ombudsman",
    "115": "employment-relations-board",
    "119": None,
    "120": "oregon-board-of-accountancy",
    "121": None,
    "123": "oregon-business-development-department",   # "Business Oregon" is its trade name
    "124": "board-of-licensed-social-workers",
    "131": None,
    "137": "department-of-justice",
    "141": "department-of-state-lands",
    "142": None,
    "143": None,
    "144": None,
    "145": None,
    "150": "department-of-revenue",
    "155": None,
    "156": "legislative-administration-committee",
    "165": "secretary-of-state",
    "170": "oregon-state-treasury",
    "172": "oregon-facilities-authority",
    "175": None,
    "196": None,
    "198": "judicial-department",
    "199": "oregon-government-ethics-commission",
    "213": "oregon-criminal-justice-commission",
    "248": "oregon-military-department",
    "250": "oregon-state-marine-board",
    "255": "board-of-parole-and-post-prison-supervision",
    "257": "department-of-state-police",
    "258": "oregon-military-department-office-of-emergency-management",   # see REORGANIZED
    "259": "department-of-public-safety-standards-and-training",
    "260": "department-of-state-police-office-of-state-fire-marshal",     # see REORGANIZED
    "274": "department-of-veterans-affairs",
    "291": "department-of-corrections",
    "330": "department-of-energy",
    "340": "department-of-environmental-quality",
    "350": "columbia-river-gorge-commission",
    "399": "psychiatric-security-review-board",
    "404": None,
    "415": "oregon-youth-authority",
    "425": None,
    "440": "department-of-consumer-and-business-services",
    "443": "oregon-health-authority",
    "459": "oregon-public-employees-retirement-system",
    "471": "employment-department",
    "524": "chief-education-office",
    "525": "higher-education-coordinating-commission",
    "543": "oregon-state-library",
    "581": "oregon-department-of-education",
    "584": "teacher-standards-and-practices-commission",
    "585": "commission-for-the-blind",
    "588": "oregon-department-of-education-early-learning-division",      # see REORGANIZED
    "603": "department-of-agriculture",
    "628": "oregon-forest-resources-institute",
    "629": "department-of-forestry",
    "632": "department-of-geology-and-mineral-industries",
    "634": "parks-and-recreation-department",
    "635": "department-of-fish-and-wildlife",
    "660": "land-conservation-and-development-department",
    "662": "land-use-board-of-appeals",
    "690": "water-resources-department",
    "691": "oregon-watershed-enhancement-board",
    "730": "department-of-transportation",
    "811": "board-of-chiropractic-examiners",
    "833": None,
    "834": "oregon-board-of-dentistry",
    "839": "bureau-of-labor-and-industries",
    "845": "oregon-liquor-control-commission",   # code stable; upstream renamed it in FY2022
    "847": "oregon-medical-board",
    "851": "board-of-nursing",
    "855": "board-of-pharmacy",
    "860": "public-utility-commission",
    "862": "oregon-racing-commission",
    "914": "oregon-housing-and-community-services-department",
    "915": "construction-contractors-board",
    "919": "real-estate-agency",
    "999": None,
}

# Why each unmapped code has no counterpart here. Absence of a mapping is a finding, not a
# gap to be filled later by guessing — most of these are agencies that issue no
# administrative rules, so they have no OAR chapter and correctly do not appear.
UNMAPPED = {
    "104": "Public Records Advocate — no OAR chapter in the registry.",
    "119": "State Board of Tax Practitioners — not present in the registry.",
    "121": "Office of the Governor — executive orders are a separate doc_type here; the "
           "office holds no OAR chapter.",
    "131": "Oregon Advocacy Commissions Office — not present in the registry.",
    "142": "Legislative Counsel Office — legislative branch; issues no administrative rules.",
    "143": "Legislative Policy and Research Committee — legislative branch. NOT the "
           "Legislative Administration Committee (code 156), which the matcher proposed.",
    "144": "Legislative Revenue Office — legislative branch. NOT the Department of Revenue "
           "(code 150), which the matcher proposed with high confidence.",
    "145": "Legislative Fiscal Officer — legislative branch.",
    "155": "Legislative Assembly — legislative branch.",
    "175": "Commission on Judicial Fitness and Disability — a separate body from the "
           "Judicial Department (code 198), which the matcher proposed.",
    "196": "District Attorneys and Deputies — county-level officers.",
    "404": "Office of Public Defense Services — not present in the registry.",
    "425": "Legislative Commission on Indian Services — legislative branch. The matcher "
           "proposed the Department of Administrative Services on the shared word "
           "'services' alone.",
    "833": "Health Related Licensing Boards is a combined BUDGET unit covering several "
           "small boards, not one legal entity. The Health Licensing Office (OAR 331) "
           "administers many of them but is not the same thing, and mapping a budget "
           "aggregate onto one registry entry would attribute other boards' spending to it.",
    "999": "Central Agency / State General Fund / back-up withholding — an accounting "
           "construct, not an agency.",
}

# Codes whose agency has been reorganized since the registry's OAR chapter assignment was
# made. The chapter — and so the registry entry — still sits under the predecessor parent,
# while the budget dataset already reports the successor as a standalone department. The
# mapping is on the functional entity and the chapter it carries; the registry NAME is the
# older one, and an answer that quotes it should say so.
REORGANIZED = {
    "258": "Budget reports 'EMERGENCY MANAGEMENT, DEPT OF' as its own department; OAR "
           "chapter 104 is still registered under the Oregon Military Department.",
    "260": "Budget reports 'STATE FIRE MARSHAL, DEPT OF' as its own department; OAR "
           "chapter 837 is still registered under the Department of State Police.",
    "588": "Budget reports 'EARLY LEARNING & CARE, DEPT OF' as its own department; OAR "
           "chapter 414 is still registered under the Department of Education.",
}


def load():
    return yaml.safe_load(CATALOG.read_text())


def audit(cat) -> list[str]:
    """Faults that make the mapping unsafe, not merely incomplete."""
    slugs = {o["slug"] for o in cat["organizations"]}
    problems = []

    for code, slug in MAPPING.items():
        if not (code.isdigit() and len(code) == 3):
            problems.append(f"{code}: not a three-digit agency code")
        if slug is None:
            if code not in UNMAPPED:
                problems.append(f"{code}: unmapped with no recorded reason — "
                                f"'no counterpart' and 'not yet looked at' must differ")
        elif slug not in slugs:
            problems.append(f"{code}: '{slug}' is not a slug in the registry")

    # Two agencies sharing one code would silently merge their spending.
    seen = {}
    for code, slug in MAPPING.items():
        if slug is None:
            continue
        if slug in seen:
            problems.append(f"{slug}: claimed by both {seen[slug]} and {code}")
        seen[slug] = code

    for code in UNMAPPED:
        if MAPPING.get(code) is not None:
            problems.append(f"{code}: listed in UNMAPPED but has a mapping")
    for code in REORGANIZED:
        if MAPPING.get(code) is None:
            problems.append(f"{code}: listed in REORGANIZED but has no mapping")
    return problems


def main() -> int:
    check = "--check" in sys.argv
    cat = load()
    problems = audit(cat)
    if problems:
        for p in problems:
            print(f"  ERROR {p}", file=sys.stderr)
        print(f"{len(problems)} problem(s) in the mapping table", file=sys.stderr)
        return 1

    by_slug = {o["slug"]: o for o in cat["organizations"]}
    want = {slug: code for code, slug in MAPPING.items() if slug}

    if check:
        bad = 0
        for slug, code in want.items():
            got = by_slug[slug].get("budget_agency_code")
            if got != code:
                print(f"  FAIL {slug}: registry has {got!r}, table says {code!r}")
                bad += 1
        for slug, o in by_slug.items():
            if o.get("budget_agency_code") and slug not in want:
                print(f"  FAIL {slug}: has budget_agency_code {o['budget_agency_code']!r} "
                      f"but the table does not map it")
                bad += 1
        print(f"\n{len(want)} codes mapped, {len(UNMAPPED)} deliberately unmapped"
              if not bad else f"\n{bad} discrepancy(ies)")
        return 1 if bad else 0

    for slug, code in want.items():
        by_slug[slug]["budget_agency_code"] = code
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    print(f"wrote budget_agency_code for {len(want)} of {len(cat['organizations'])} "
          f"organizations")
    print(f"  {len(UNMAPPED)} budget agency codes have no registry counterpart, by review")
    print(f"  {len(REORGANIZED)} map to a predecessor parent unit — see REORGANIZED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
