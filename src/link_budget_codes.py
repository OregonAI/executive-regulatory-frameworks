#!/usr/bin/env python3
"""Attach DAS agency numbers to the agency registry.

  python3 src/link_budget_codes.py           # write das_agency_number into agencies.yml
  python3 src/link_budget_codes.py --check   # verify the registry matches this table

THE FIELD IS `das_agency_number` (CONTEXT.md). It used to also carry the same value under a
deprecated `budget_agency_code` key, for one deprecation cycle (#175); #177 removed that key,
and catalog_agencies.py now refuses it (`budget-agency-code-retired`) if it ever reappears.
catalog_agencies.py writes the field in one place (write_das_agency_number). The number
identifies a body in the state's financial administration and is not evidence that the body
spends money; the names below (`MAPPING`, `UNMAPPED`, `REORGANIZED`) still read "code" because
they are keyed by the budget dataset's own vocabulary.

WHY THIS EXISTS. `oregon-budget` reports spending against three-digit DAS agency numbers
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
from datetime import date

import yaml

import catalog_agencies
from repo_lib import REPO_ROOT

CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"

# ---------------------------------------------------------------- curated registry data
#
# The registry is SCRAPED from OAR chapter assignment, which by construction can only
# describe bodies that issue administrative rules. Two things it therefore cannot produce,
# both curated here and both preserved across `catalog_agencies.py --refresh`:

# 1. AGENCIES THAT ISSUE NO RULES. Real state bodies with real budgets that hold no OAR
#    chapter — the Governor's office, the legislative-branch offices, the public-defense
#    and judicial-conduct commissions. They appropriate and spend money, so oregon-budget
#    needs to name them, but a chapter-keyed scrape will never see them.
#
#    DELIBERATELY EXCLUDED, because they are not agencies:
#      999  Central Agency / State General Fund / back-up withholding — an accounting
#           construct, confirmed with the maintainer
#      833  Health Related Licensing Boards — a combined BUDGET unit over several small
#           boards; mapping it to one entry would attribute other boards' spending to it
#      —    the Emergency Board — a contingency fund that disburses THROUGH other
#           agencies, confirmed with the maintainer as not an agency
MANUAL_ENTRIES = [
    ("public-records-advocate", "Public Records Advocate", "104"),
    ("state-board-of-tax-practitioners", "State Board of Tax Practitioners", "119"),
    ("office-of-the-governor", "Office of the Governor", "121"),
    ("oregon-advocacy-commissions-office", "Oregon Advocacy Commissions Office", "131"),
    ("legislative-counsel-office", "Legislative Counsel Office", "142"),
    ("legislative-policy-and-research-committee",
     "Legislative Policy and Research Committee", "143"),
    ("legislative-revenue-office", "Legislative Revenue Office", "144"),
    ("legislative-fiscal-officer", "Legislative Fiscal Officer", "145"),
    ("legislative-assembly", "Legislative Assembly", "155"),
    ("commission-on-judicial-fitness-and-disability",
     "Commission on Judicial Fitness and Disability", "175"),
    ("district-attorneys-and-deputies", "District Attorneys and Deputies", "196"),
    ("office-of-public-defense-services", "Office of Public Defense Services", "404"),
    ("legislative-commission-on-indian-services",
     "Legislative Commission on Indian Services", "425"),
    # NO BUDGET CODE, and the first entry here without one. Every row above exists because a
    # DAS code needed somewhere to point; this one exists because oregon-kpm's agency
    # crosswalk needs an identity to resolve into, and the Legislative Equity Office appears
    # in no appropriation this repo has mapped. `None` is the same value UNMAPPED uses for a
    # code with no counterpart, read in the other direction: an organization with no code.
    #
    # It is a legislative-branch office (ORS 173.480) and issues no administrative rules, so
    # it holds no OAR chapter and the chapter scrape can never produce it -- the same reason
    # the Governor's office and the Legislative Assembly are hand-written above.
    ("legislative-equity-office", "Legislative Equity Office", None),
]

# 2. ALIASES. The same body is named differently by different sources, and matching on the
#    registry's single canonical `name` forced every consumer to either miss the variant or
#    invent fuzzy matching — which is how the Legislative Revenue Office got matched to the
#    Department of Revenue during the first pass at this file.
#
#    An alias is an ASSERTION OF IDENTITY, reviewed once here, rather than a similarity
#    score computed at query time. It also absorbs renames: when a body is renamed, its old
#    name becomes an alias and every historical citation keeps resolving.
#
#    Sourced from the names Oregon appropriation bills actually use, measured in
#    oregon-budget (_meta/unresolved-agencies.md).
ALIASES = {
    "department-of-forestry": ["State Forestry Department"],
    "land-conservation-and-development-department": [
        "Department of Land Conservation and Development"],
    "department-of-state-police-office-of-state-fire-marshal": [
        "State Fire Marshal", "Department of the State Fire Marshal",
        "Office of State Fire Marshal"],
    # "Oregon Department of Emergency Management" IS an alias of this row (#212): HB 2927
    # (Oregon Laws 2021, ch.539) renamed the body and made it standalone, but the registry
    # carries this as ONE row, not two ("it is one body that moved, not two bodies," #212) —
    # the current statutory name is recorded as an alias so DAS budget code 258 still
    # resolves it, until this row's own `name` is promoted (see its `curator_note`).
    "oregon-military-department-office-of-emergency-management": [
        "Office of Emergency Management", "Oregon Department of Emergency Management"],
    "oregon-department-of-education-early-learning-division": [
        "Early Learning Division of the Department of Education",
        "Department of Early Learning and Care", "Early Learning Division"],
    "oregon-department-of-education-youth-development-division": [
        "Youth Development Division"],
    "oregon-state-treasury": ["State Treasurer", "Office of the State Treasurer"],
    # The 845 rename: Liquor Control Commission became the Liquor and Cannabis Commission.
    # The budget dataset already shows both across FY2019-FY2025; the code never changed.
    "oregon-liquor-control-commission": [
        "Oregon Liquor and Cannabis Commission", "Liquor and Cannabis Commission"],
    "office-of-public-defense-services": ["Public Defense Services Commission"],
    "higher-education-coordinating-commission": ["Higher Education Coordinating Commission"],
}


# code -> registry slug. Reviewed by hand, 2026-07-28.
MAPPING = {
    "100": "department-of-human-services",
    "104": "public-records-advocate",
    "107": "department-of-administrative-services",
    "108": "mental-health-regulatory-agency",
    "109": "oregon-department-of-aviation",
    "114": "long-term-care-ombudsman",
    "115": "employment-relations-board",
    "119": "state-board-of-tax-practitioners",
    "120": "oregon-board-of-accountancy",
    "121": "office-of-the-governor",
    "123": "oregon-business-development-department",   # "Business Oregon" is its trade name
    "124": "board-of-licensed-social-workers",
    "131": "oregon-advocacy-commissions-office",
    "137": "department-of-justice",
    "141": "department-of-state-lands",
    "142": "legislative-counsel-office",
    "143": "legislative-policy-and-research-committee",
    "144": "legislative-revenue-office",
    "145": "legislative-fiscal-officer",
    "150": "department-of-revenue",
    "155": "legislative-assembly",
    "156": "legislative-administration-committee",
    "165": "secretary-of-state",
    "170": "oregon-state-treasury",
    "172": "oregon-facilities-authority",
    "175": "commission-on-judicial-fitness-and-disability",
    "196": "district-attorneys-and-deputies",
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
    "404": "office-of-public-defense-services",
    "415": "oregon-youth-authority",
    "425": "legislative-commission-on-indian-services",
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
           "chapter 104 is still registered under the Oregon Military Department. Cause "
           "confirmed (#212): ORS 401.052(1), HB 2927 (Oregon Laws 2021, ch. 539).",
    "260": "Budget reports 'STATE FIRE MARSHAL, DEPT OF' as its own department; OAR "
           "chapter 837 is still registered under the Department of State Police. Cause "
           "confirmed (#354, same act as #212): ORS 476.020(1), HB 2927 (Oregon Laws 2021, "
           "ch. 539).",
    "588": "Budget reports 'EARLY LEARNING & CARE, DEPT OF' as its own department; OAR "
           "chapter 414 is still registered under the Department of Education. Cause "
           "confirmed (#354): ORS 326.430(1)(a), HB 3073 (2021 regular session).",
}


def load():
    return yaml.safe_load(CATALOG.read_text())


def manual_slugs_present(cat) -> set:
    """Slugs the registry currently records as absent from the OAR index --
    `absent_from_index_as_of` (#353), the field that carries a row whole across
    `catalog_agencies.py --refresh` now that `manual: true` is retired (#169). Read
    through the field's own name rather than re-declared here, so this module cannot
    drift from what `catalog_agencies.py` actually preserves a row on."""
    return {o["slug"] for o in cat["organizations"]
            if o.get(catalog_agencies.ABSENT_FROM_INDEX_KEY)}


def audit(cat) -> list[str]:
    """Faults that make the mapping unsafe, not merely incomplete."""
    # MANUAL_ENTRIES slugs count as known: main() creates them in the same run, so
    # validating MAPPING against the pre-insert registry would reject every code this
    # change exists to map.
    slugs = {o["slug"] for o in cat["organizations"]} | {s for s, _, _ in MANUAL_ENTRIES}
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
    for code, slug in MAPPING.items():
        if slug is None and code not in UNMAPPED:
            problems.append(f"{code}: unmapped with no recorded reason")

    manual_slugs = {slug for slug, _, _ in MANUAL_ENTRIES}
    if len(manual_slugs) != len(MANUAL_ENTRIES):
        problems.append("MANUAL_ENTRIES contains a duplicate slug")
    # WHETHER THE MIRROR NOW INDEXES A SLUG, READ OFF `absent_from_index_as_of` (#353), NOT
    # `manual` (#169 retires it). Before #353 this compared against `not o.get("manual")` --
    # true until every MANUAL_ENTRIES slug also carried `manual: true`, which stopped being
    # so the day #169 removed the flag: reading `not o.get("manual")` today would call every
    # one of them "scraped" and fire a false collision here for all fourteen, since nothing
    # sets that key on any row any more. `absent_from_index_as_of` is what a real --refresh
    # now dates on a row it did not reproduce (`catalog_agencies.record_absence_
    # observations()`), so a MANUAL_ENTRIES slug missing that field is one the mirror
    # actually produced this run -- genuinely the collision this check exists to catch.
    scraped = {o["slug"] for o in cat["organizations"]
              if not o.get(catalog_agencies.ABSENT_FROM_INDEX_KEY)}
    for slug, name, code in MANUAL_ENTRIES:
        # Collision means the SCRAPE now produces this slug — the upstream mirror has
        # caught up and the manual entry is redundant. Compare against scraped entries
        # only; `slugs` deliberately includes the manual ones so MAPPING validates.
        if slug in scraped:
            problems.append(f"{slug}: MANUAL_ENTRIES collides with a SCRAPED entry — the "
                            f"mirror now indexes it, so remove the manual one by hand "
                            f"after comparing names")
        # A None code means the organization exists in its own right and no appropriation
        # this repo has mapped points at it -- so there is nothing for MAPPING to agree with,
        # and requiring an entry would mean inventing a code. The registry is a catalogue of
        # Oregon agencies, not only of the ones that spend money through a mapped code.
        if code is not None and MAPPING.get(code) != slug:
            problems.append(f"{slug}: MANUAL_ENTRIES says code {code}, MAPPING disagrees")

    # An alias must name a slug that exists, and must never be ambiguous — two slugs
    # claiming one alias would make identity depend on iteration order.
    seen_alias = {}
    known = slugs | manual_slugs
    for slug, names in ALIASES.items():
        if slug not in known:
            problems.append(f"aliases: '{slug}' is not a registry slug")
        for n in names:
            k = n.strip().lower()
            if k in seen_alias and seen_alias[k] != slug:
                problems.append(f"alias {n!r} claimed by both {seen_alias[k]} and {slug}")
            seen_alias[k] = slug
            # NAME READER — JOIN: a DAS-published alias compared against the registry's
            # canonical name, to refuse an alias that is really another body's name. It
            # matches `name` only, which is what it matched before ADR 0003 — after #168
            # promotes `name`, an alias colliding with another body's OAR NAME would be
            # equally ambiguous and would not be caught here. Widening it is a decision for
            # #168, where the hand-reviewed ALIASES table is re-verified; recorded here so
            # the gap is a known one rather than a silence.
            if any(k == o["name"].lower() and o["slug"] != slug
                   for o in cat["organizations"]):
                problems.append(f"alias {n!r} on {slug} is another entry's canonical name")
    for code in REORGANIZED:
        if MAPPING.get(code) is None:
            problems.append(f"{code}: listed in REORGANIZED but has no mapping")
    return problems


def _absent_entry(slug, name, today=None):
    """The row `main()` writes for a MANUAL_ENTRIES slug missing from the registry -- a
    body that holds no OAR chapter, so the chapter scrape structurally cannot produce it,
    ever, regardless of what oregon.public.law's index says on any given day.

    CARRIED ACROSS `catalog_agencies.py --refresh` BY `absent_from_index_as_of` (#353), NOT
    `manual: true` (#169 retires it): that flag used to be the only signal
    `preserve_manual()` read to keep such a row whole, and this constructor was its other
    writer -- the one place besides `cmd_refresh()` itself that put a row into the
    committed file needing that whole-row protection. Retiring the flag without also
    fixing this constructor would not have removed manual entries from the file; it would
    have made this the one place still writing `manual: true` with no admitting evidence
    behind it, which is exactly the substitution #169 exists to close off, and the very
    next `--refresh` after this ran would have deleted every entry it wrote, un-noticed
    until the next run silently re-added them in the same rejected state (this ticket's own
    trigger).

    `today` is a PARAMETER, not read from `date.today()` inline, so --selftest can pin a
    date and assert against it instead of racing the clock."""
    today = date.today().isoformat() if today is None else today
    return dict(catalog_agencies.scraped_entry(
        oar_name=name, oar_chapter=None, raw_index_name=name, source_url=None),
        slug=slug,
        **{catalog_agencies.ABSENT_FROM_INDEX_KEY: today})


def _proof_absent_entry_writes_the_dated_field_not_manual() -> int:
    """`_absent_entry()` (#169) writes `absent_from_index_as_of`, dated, on the row it
    builds for a missing MANUAL_ENTRIES slug -- and never `manual`, the flag this
    constructor used to write with no admitting evidence behind it (this ticket's own
    trigger: a real --refresh would drop such a row, and the next run of this script would
    silently re-add it in the same state --check rejects).

    WATCHED FAILING before this fix existed: this proof is the one that turned red the
    moment `_absent_entry()` still read `manual=True` -- restated in its own docstring so a
    future reader does not have to git-log this file to find that out."""
    bad = 0
    entry = _absent_entry("test-slug", "Test Body", today="2026-09-12")
    if entry.get(catalog_agencies.ABSENT_FROM_INDEX_KEY) != "2026-09-12":
        print("FAIL absent-entry-dates-the-new-field: "
              f"{entry.get(catalog_agencies.ABSENT_FROM_INDEX_KEY)!r}", file=sys.stderr)
        bad += 1
    if "manual" in entry:
        print(f"FAIL absent-entry-does-not-write-manual: {entry!r}", file=sys.stderr)
        bad += 1
    return bad


def selftest() -> int:
    bad = _proof_absent_entry_writes_the_dated_field_not_manual()
    if bad:
        print(f"{bad} proof(s) did not hold", file=sys.stderr)
        return 1
    print("1 proof held: _absent_entry() writes absent_from_index_as_of, dated, and never "
          "manual")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
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
        # AGAINST `das_agency_number`, THE FIELD OF RECORD and, since #177, the only key the
        # registry carries the number under. What this gate owns is whether the number
        # matches the REVIEWED TABLE below.
        for slug, code in want.items():
            got = by_slug[slug].get("das_agency_number")
            if got != code:
                print(f"  FAIL {slug}: registry has {got!r}, table says {code!r}")
                bad += 1
        for slug, o in by_slug.items():
            if o.get("das_agency_number") and slug not in want:
                print(f"  FAIL {slug}: has das_agency_number {o['das_agency_number']!r} "
                      f"but the table does not map it")
                bad += 1
        for slug, name, _c in MANUAL_ENTRIES:
            if slug not in by_slug:
                print(f"  FAIL {slug}: manual entry missing from the registry")
                bad += 1
        for slug, names in ALIASES.items():
            got = by_slug.get(slug, {}).get("aliases") or []
            if sorted(names) != sorted(got):
                print(f"  FAIL {slug}: aliases are {got!r}, table says {sorted(names)!r}")
                bad += 1
        print(f"\n{len(want)} codes mapped, {len(UNMAPPED)} deliberately unmapped, "
              f"{len(MANUAL_ENTRIES)} manual entries, "
              f"{sum(len(v) for v in ALIASES.values())} aliases"
              if not bad else f"\n{bad} discrepancy(ies)")
        return 1 if bad else 0

    added = 0
    for slug, name, _code in MANUAL_ENTRIES:
        if slug in by_slug:
            continue
        # BUILT BY THE REGISTRY'S OWN CONSTRUCTOR, not by a second hand-written copy of the
        # row shape. These rows sit in the same file as the scraped ones and must carry the
        # same keys, and the two spellings of that shape had already drifted apart: adding
        # `oar_name` to catalog_agencies.FIELDS left this dict a field short, so the row it
        # rebuilt failed --check's required-field rule. One constructor means the next field
        # cannot repeat that. The declared slug still wins over the derived one, because
        # MANUAL_ENTRIES is where a body the scrape cannot see gets its identity (the two
        # agree on all 14 today).
        #
        # The OAR name (CONTEXT.md) it ends up with is the body's own name. These bodies
        # hold no OAR chapter — that is why the scrape cannot see them — so there is no
        # chapter title to differ from it, and copying it asserts nothing about what the
        # rules index prints. It is written because `oar_name` is the string consumers
        # join on from here (ADR 0003), and a row without one is a row those joins lose.
        entry = _absent_entry(slug, name)
        cat["organizations"].append(entry)
        by_slug[slug] = entry
        added += 1

    # WRITTEN BY THE REGISTRY'S OWN WRITER, not assigned here by hand — one place that owns
    # the field's name.
    for slug, code in want.items():
        catalog_agencies.write_das_agency_number(by_slug[slug], code)
    for slug, names in ALIASES.items():
        if slug in by_slug:
            by_slug[slug]["aliases"] = sorted(names)

    cat["organizations"].sort(key=lambda o: o["slug"])
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    print(f"wrote das_agency_number for "
          f"{len(want)} of {len(cat['organizations'])} organizations")
    print(f"  added {added} manual entry(ies) for agencies that issue no OAR rules")
    print(f"  wrote aliases on {sum(1 for s in ALIASES if s in by_slug)} entry(ies)")
    print(f"  {len(UNMAPPED)} budget agency codes have no registry counterpart, by review")
    print(f"  {len(REORGANIZED)} map to a predecessor parent unit — see REORGANIZED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
