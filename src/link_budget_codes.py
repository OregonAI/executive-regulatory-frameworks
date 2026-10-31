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

import os
import re
import sys

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
#    chapter — the Governor's office, the legislative-branch offices, the judicial-conduct
#    commission. They appropriate and spend money, so oregon-budget
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
    # BODIES A STATUTE CREATES THAT THE REGISTRY LACKED (operator decision 2026-10-30). None
    # holds an OAR chapter, so the chapter scrape cannot produce them, and none has a DAS
    # number mapped, so `None` is the code. Each is admitted by its enabling authority (ADR
    # 0003) -- the section and the quotation that shows it creating or constituting the body
    # are in link_enabling_authority.py's MAPPED and QUOTE_CHECKS -- and its name is the one
    # that section prints (STATUTORY_NAMES). Two boards the same search turned up are NOT
    # here: the governing board of the Department of Geology and Mineral Industries (ORS
    # 516.080 provides for "a governing board", a description and not a name) and the Veterans'
    # Affairs advisory committee (ORS 406.210 says "to constitute the Advisory Committee"), as
    # is the State Workforce and Talent Development Board, which ORS 660.321 says "shall be
    # created under" a federal act.
    ("environmental-quality-commission", "Environmental Quality Commission", None),
    ("state-fish-and-wildlife-commission", "State Fish and Wildlife Commission", None),
    ("state-board-of-forestry", "State Board of Forestry", None),
    ("board-on-public-safety-standards-and-training", "Board on Public Safety Standards and Training", None),
    ("state-land-board", "State Land Board", None),
    ("oregon-transportation-commission", "Oregon Transportation Commission", None),
    ("land-conservation-and-development-commission", "Land Conservation and Development Commission", None),
    ("oregon-business-development-commission", "Oregon Business Development Commission", None),
    ("state-aviation-board", "State Aviation Board", None),
    ("state-board-of-education", "State Board of Education", None),
    ("state-parks-and-recreation-commission", "State Parks and Recreation Commission", None),
    ("water-resources-commission", "Water Resources Commission", None),
    ("state-board-of-denture-technology", "State Board of Denture Technology", None),
    ("board-of-athletic-trainers", "Board of Athletic Trainers", None),
    ("board-of-electrologists-and-body-art-practitioners", "Board of Electrologists and Body Art Practitioners", None),
    ("respiratory-therapist-and-polysomnographic-technologist-licensing-board", "Respiratory Therapist and Polysomnographic Technologist Licensing Board", None),
    ("advisory-council-on-hearing-aids", "Advisory Council on Hearing Aids", None),
    ("sexual-offense-treatment-board", "Sexual Offense Treatment Board", None),
    ("commission-on-hispanic-affairs", "Commission on Hispanic Affairs", None),
    ("commission-on-black-affairs", "Commission on Black Affairs", None),
    ("commission-for-women", "Commission for Women", None),
    ("commission-on-asian-and-pacific-islander-affairs", "Commission on Asian and Pacific Islander Affairs", None),
    ("early-learning-council", "Early Learning Council", None),
    ("youth-development-council", "Youth Development Council", None),
    ("oregon-health-policy-board", "Oregon Health Policy Board", None),
    ("oregon-housing-stability-council", "Oregon Housing Stability Council", None),
    ("oregon-cannabis-commission", "Oregon Cannabis Commission", None),
    ("state-library-board", "State Library Board", None),
    ("oregon-retirement-savings-board", "Oregon Retirement Savings Board", None),
    ("oregon-agricultural-heritage-commission", "Oregon Agricultural Heritage Commission", None),
    ("oregon-geographic-information-council", "Oregon Geographic Information Council", None),
    ("residential-ombudsman-and-public-guardianship-advisory-board", "Residential Ombudsman and Public Guardianship Advisory Board", None),
    ("council-on-optometric-nontopical-formulary", "Council on Optometric Nontopical Formulary", None),
    ("board-of-trustees-of-southern-oregon-university", "Board of Trustees of Southern Oregon University", None),
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
#
#    AN ACRONYM IS AN ALIAS ONLY WITH A QUOTATION (operator decision 2026-10-30, ADR 0003's
#    amendment): ALIAS_EVIDENCE below holds, for each one, the id of a document in this corpus
#    that pairs it with the body's name and the sentence that does, and
#    `audit_alias_evidence` re-matches the sentence against the document word for word on
#    every --check. The older aliases here (former names after a rename, the budget dataset's
#    spellings) were reviewed by a human and carry no quotation.
ALIASES = {
    "department-of-forestry": ["State Forestry Department", "ODF"],
    "land-conservation-and-development-department": [
        "Department of Land Conservation and Development", "DLCD"],
    "department-of-state-police-office-of-state-fire-marshal": [
        "State Fire Marshal", "Department of the State Fire Marshal",
        "Office of State Fire Marshal", "OSFM"],
    # "Oregon Department of Emergency Management" IS an alias of this row (#212): HB 2927
    # (Oregon Laws 2021, ch.539) renamed the body and made it standalone, but the registry
    # carries this as ONE row, not two ("it is one body that moved, not two bodies," #212) —
    # the current statutory name is recorded as an alias so DAS budget code 258 still
    # resolves it, until this row's own `name` is promoted (see its `curator_note`).
    "oregon-military-department-office-of-emergency-management": [
        "Office of Emergency Management", "Oregon Department of Emergency Management",
        "ODEM", "OEM"],
    "oregon-department-of-education-early-learning-division": [
        "Early Learning Division of the Department of Education",
        "Department of Early Learning and Care", "Early Learning Division", "DELC"],
    "oregon-department-of-education-youth-development-division": [
        "Youth Development Division"],
    "oregon-state-treasury": ["State Treasurer", "Office of the State Treasurer", "OST"],
    # The 845 rename: Liquor Control Commission became the Liquor and Cannabis Commission.
    # The budget dataset already shows both across FY2019-FY2025; the code never changed.
    "oregon-liquor-control-commission": [
        "Oregon Liquor and Cannabis Commission", "Liquor and Cannabis Commission", "OLCC"],
    # SB 337 (2023) renamed the public defense body: ORS 151.213(1) (2025 edition)
    # establishes "the Oregon Public Defense Commission", and OARD prints chapter 404 under
    # that name. One row, the OLCC and OEM pattern above: the current statutory name is an
    # alias and the slug is unchanged, because oregon-budget and oregon-kpm resolve it.
    "office-of-public-defense-services": [
        "Public Defense Services Commission", "Oregon Public Defense Commission"],
    # OARD prints chapter 180 as "Office of the Public Records Advocate"; ORS 192.461(1)
    # creates "the office of the Public Records Advocate".
    "public-records-advocate": ["Office of the Public Records Advocate"],
    "higher-education-coordinating-commission": ["Higher Education Coordinating Commission",
                                                  "HECC"],
    # ACRONYMS (operator decision 2026-10-30). Each one below is paired with its body's name by a
    # quotation from a corpus document in ALIAS_EVIDENCE, matched word for word on every run.
    "appraiser-certification-and-licensure-board": ["ACLB"],
    "board-of-medical-imaging": ["OBMI"],
    "board-of-nursing": ["OSBN"],
    "board-of-parole-and-post-prison-supervision": ["BOPPPS"],
    "bureau-of-labor-and-industries": ["BOLI"],
    "commission-for-the-blind": ["OCB"],
    "construction-contractors-board": ["CCB"],
    "department-of-administrative-services": ["DAS"],
    "department-of-administrative-services-chief-human-resources-office": ["CHRO"],
    "department-of-administrative-services-office-of-the-state-chief-information-officer": ["OSCIO"],
    "department-of-agriculture-oregon-potato-commission": ["OPC"],
    "department-of-agriculture-oregon-sheep-commission": ["OSC"],
    "department-of-agriculture-oregon-wheat-commission": ["OWC"],
    "department-of-consumer-and-business-services": ["DCBS"],
    "department-of-consumer-and-business-services-building-codes-division": ["BCD"],
    "department-of-consumer-and-business-services-prescription-drug-affordability-board": ["PDAB"],
    "department-of-consumer-and-business-services-workers-compensation-board": ["WCB"],
    "department-of-consumer-and-business-services-workers-compensation-division": ["WCD"],
    "department-of-corrections": ["DOC", "ODOC"],
    "department-of-energy": ["ODOE"],
    "department-of-energy-energy-facility-siting-council": ["EFSC"],
    "department-of-environmental-quality": ["DEQ", "ODEQ"],
    "department-of-fish-and-wildlife": ["ODFW", "ODF&W"],
    "department-of-geology-and-mineral-industries": ["DOGAMI"],
    "department-of-human-services": ["ODHS", "DHS"],
    "department-of-human-services-home-care-commission": ["OHCC"],
    "department-of-human-services-vocational-rehabilitation-services": ["OVRS"],
    "department-of-justice": ["DOJ"],
    "department-of-public-safety-standards-and-training": ["DPSST"],
    "department-of-revenue": ["DOR"],
    "department-of-state-lands": ["DSL"],
    "department-of-state-lands-south-slough-national-estuarine-research-reserve": ["SSNERR"],
    "department-of-state-police": ["OSP"],
    "department-of-transportation": ["ODOT"],
    "department-of-transportation-driver-and-motor-vehicle-services-division": ["DMV"],
    "department-of-transportation-motor-carrier-transportation-division": ["MCTD"],
    "department-of-veterans-affairs": ["ODVA"],
    "economic-recovery-review-council": ["ERRC"],
    "employment-department": ["OED"],
    "employment-relations-board": ["ERB"],
    "judicial-department": ["OJD"],
    "land-use-board-of-appeals": ["LUBA"],
    "legislative-commission-on-indian-services": ["LCIS"],
    "office-of-training-investigations-and-safety": ["OTIS"],
    "oregon-business-development-department": ["OBDD"],
    "oregon-criminal-justice-commission": ["CJC"],
    "oregon-department-of-education": ["ODE"],
    "oregon-film-and-video-office": ["OFVO"],
    "oregon-forest-resources-institute": ["OFRI"],
    "oregon-government-ethics-commission": ["OGEC"],
    "oregon-health-authority": ["OHA"],
    "oregon-health-authority-health-licensing-office": ["HLO"],
    "oregon-health-authority-oregon-educators-benefit-board": ["OEBB"],
    "oregon-health-authority-public-employees-benefit-board": ["PEBB"],
    "oregon-housing-and-community-services-department": ["OHCS"],
    "oregon-investment-council": ["OIC"],
    "oregon-military-department": ["OMD"],
    "oregon-patient-safety-commission": ["OPSC"],
    "oregon-public-employees-retirement-system": ["PERS"],
    "oregon-racing-commission": ["ORC"],
    "oregon-watershed-enhancement-board": ["OWEB"],
    "oregon-youth-authority": ["OYA"],
    "parks-and-recreation-department": ["OPRD"],
    "psychiatric-security-review-board": ["PSRB"],
    "public-utility-commission": ["PUC"],
    "real-estate-agency": ["OREA"],
    "secretary-of-state": ["SOS"],
    "southern-oregon-university": ["SOU"],
    "teacher-standards-and-practices-commission": ["TSPC"],
    "water-resources-department": ["OWRD", "WRD"],
}


# slug -> {acronym: (document id, quotation)}. THE REVIEW RECORD OF AN ACRONYM ALIAS: the id of a
# document in THIS CORPUS (an OAR rule, an agency policy, a records-retention schedule, an
# executive order) that pairs the acronym with the body's name, and the sentence in it that
# does — "Oregon Department of Human Services (ODHS)" is the shape — taken from that
# document's `## Full text` and matched against it word for word on every run
# (`audit_alias_evidence`: whitespace is the only thing normalised). The acronym has to be
# inside the quotation and so does one of the body's own names, which is the gate's whole
# reading of "pairs"; whether the document means THIS body by it is what the person or agent
# who chose the quotation answers for.
#
# AN ACRONYM TWO BODIES BOTH USE IS NOT RECORDED FOR EITHER. ODA is the Oregon Department of
# Agriculture in 27 documents and the Oregon Department of Aviation in 4, and DOE and OSAC are
# each two bodies' too; an alias is an assertion of identity, and one the corpus itself uses
# for two bodies would make a search for it depend on which row a reader reached first.
ALIAS_EVIDENCE: dict[str, dict[str, tuple[str, str]]] = {
    "appraiser-certification-and-licensure-board": {
        "ACLB": ("oar-161-002-0000",
                 "“ACLB” means the Oregon Appraiser Certification and Licensure Board"),
    },
    "board-of-medical-imaging": {
        "OBMI": ("oar-337-010-0011",
                 "Oregon Board of Medical Imaging (OBMI)"),
    },
    "board-of-nursing": {
        "OSBN": ("oar-581-022-2220",
                 "Oregon State Board of Nursing (OSBN)"),
    },
    "board-of-parole-and-post-prison-supervision": {
        "BOPPPS": ("oar-859-400-0005",
                 "“BOPPPS” means the Oregon Board of Parole and Post-Prison Supervision"),
    },
    "bureau-of-labor-and-industries": {
        "BOLI": ("oar-812-025-0005",
                 "“BOLI” means Bureau of Labor and Industries"),
    },
    "commission-for-the-blind": {
        "OCB": ("oar-165-005-0055",
                 "Oregon Commission for the Blind (OCB)"),
    },
    "construction-contractors-board": {
        "CCB": ("oar-330-070-0026",
                 "Construction Contractors Board (CCB)"),
    },
    "department-of-administrative-services": {
        "DAS": ("oar-125-155-0010",
                 "\"DAS\" means Department of Administrative Services"),
    },
    "department-of-administrative-services-chief-human-resources-office": {
        "CHRO": ("oar-105-050-0025",
                 "Chief Human Resources Office (CHRO)"),
    },
    "department-of-administrative-services-office-of-the-state-chief-information-officer": {
        "OSCIO": ("das-107-004-150_pr",
                 "Office of the State Chief Information Officer (OSCIO)"),
    },
    "department-of-agriculture-oregon-potato-commission": {
        "OPC": ("oar-658-020-0005",
                 "Oregon Potato Commission (OPC)"),
    },
    "department-of-agriculture-oregon-sheep-commission": {
        "OSC": ("oar-644-005-0005",
                 "Oregon Sheep Commission (OSC)"),
    },
    "department-of-agriculture-oregon-wheat-commission": {
        "OWC": ("oar-678-005-0005",
                 "Oregon Wheat Commission (OWC)"),
    },
    "department-of-consumer-and-business-services": {
        "DCBS": ("oar-409-036-0010",
                 "\"DCBS” means the Department of Consumer and Business Services"),
    },
    "department-of-consumer-and-business-services-building-codes-division": {
        "BCD": ("oar-333-060-1000",
                 "Building Codes Division (BCD)"),
    },
    "department-of-consumer-and-business-services-prescription-drug-affordability-board": {
        "PDAB": ("oar-925-200-0010",
                 "Prescription Drug Affordability Board (PDAB)"),
    },
    "department-of-consumer-and-business-services-workers-compensation-board": {
        "WCB": ("schedule-consumer-business",
                 "Workers' Compensation Board (WCB)"),
    },
    "department-of-consumer-and-business-services-workers-compensation-division": {
        "WCD": ("schedule-consumer-business",
                 "Workers’ Compensation Division (WCD)"),
    },
    "department-of-corrections": {
        "DOC": ("oar-309-091-0005",
                 "“DOC” means the Oregon Department of Corrections"),
        "ODOC": ("doc-20-5-4",
                 "Oregon Department of Corrections (ODOC)"),
    },
    "department-of-energy": {
        "ODOE": ("oar-330-067-0020",
                 "“ODOE” means the Oregon Department of Energy"),
    },
    "department-of-energy-energy-facility-siting-council": {
        "EFSC": ("oar-141-087-0015",
                 "Energy Facility Siting Council (EFSC)"),
    },
    "department-of-environmental-quality": {
        "DEQ": ("oar-340-200-0025",
                 "\"DEQ\" means Department of Environmental Quality"),
        "ODEQ": ("oar-603-111-0010",
                 "“ODEQ” means the Oregon Department of Environmental Quality"),
    },
    "department-of-fish-and-wildlife": {
        "ODFW": ("oar-340-056-0100",
                 "“ODFW” means the Oregon Department of Fish and Wildlife"),
        "ODF&W": ("oar-736-060-0010",
                 "“ODF&W” means the Oregon Department of Fish and Wildlife"),
    },
    "department-of-forestry": {
        "ODF": ("oar-629-048-0005",
                 "Oregon Department of Forestry (ODF)"),
    },
    "department-of-geology-and-mineral-industries": {
        "DOGAMI": ("oar-690-078-0010",
                 "“DOGAMI” means Department of Geology and Mineral Industries"),
    },
    "department-of-human-services": {
        "ODHS": ("oar-414-075-0010",
                 "“ODHS” means the Oregon Department of Human Services"),
        "DHS": ("oar-411-004-0010",
                 "\"DHS\" means the Department of Human Services"),
    },
    "department-of-human-services-home-care-commission": {
        "OHCC": ("oar-411-003-0005",
                 "Oregon Home Care Commission (OHCC)"),
    },
    "department-of-human-services-vocational-rehabilitation-services": {
        "OVRS": ("oar-582-075-0010",
                 "Vocational Rehabilitation Services (OVRS)"),
    },
    "department-of-justice": {
        "DOJ": ("oar-137-055-5035",
                 "Department of Justice (DOJ)"),
    },
    "department-of-public-safety-standards-and-training": {
        "DPSST": ("oar-259-008-0005",
                 "“DPSST” means the Department of Public Safety Standards and Training"),
    },
    "department-of-revenue": {
        "DOR": ("oar-735-030-0005",
                 "“DOR” means the Oregon Department of Revenue"),
    },
    "department-of-state-lands": {
        "DSL": ("oar-690-385-0100",
                 "“DSL” means the Department of State Lands"),
    },
    "department-of-state-lands-south-slough-national-estuarine-research-reserve": {
        "SSNERR": ("schedule-state-lands",
                 "South Slough National Estuarine Research Reserve (SSNERR)"),
    },
    "department-of-state-police": {
        "OSP": ("oar-257-100-0005",
                 "“OSP” means the Oregon Department of State Police"),
    },
    "department-of-state-police-office-of-state-fire-marshal": {
        "OSFM": ("oar-837-035-0060",
                 "Oregon State Fire Marshal (OSFM)"),
    },
    "department-of-transportation": {
        "ODOT": ("oar-731-017-0010",
                 "“ODOT” means the Oregon Department of Transportation"),
    },
    "department-of-transportation-driver-and-motor-vehicle-services-division": {
        "DMV": ("oar-735-018-0010",
                 "“DMV” means the Driver and Motor Vehicle Services Division"),
    },
    "department-of-transportation-motor-carrier-transportation-division": {
        "MCTD": ("oar-345-060-0004",
                 "Motor Carrier Transportation Division (MCTD)"),
    },
    "department-of-veterans-affairs": {
        "ODVA": ("oar-274-020-0200",
                 "“ODVA\" means the Oregon Department of Veterans’ Affairs"),
    },
    "economic-recovery-review-council": {
        "ERRC": ("oar-966-100-0200",
                 "“ERRC” means the Economic Recovery Review Council"),
    },
    "employment-department": {
        "OED": ("oar-471-007-0210",
                 "Oregon Employment Department (OED)"),
    },
    "employment-relations-board": {
        "ERB": ("oar-411-002-0155",
                 "Employment Relations Board (ERB)"),
    },
    "higher-education-coordinating-commission": {
        "HECC": ("oar-817-005-0005",
                 "“HECC” means Higher Education Coordinating Commission"),
    },
    "judicial-department": {
        "OJD": ("oar-257-010-0060",
                 "Oregon Judicial Department (OJD)"),
    },
    "land-conservation-and-development-department": {
        "DLCD": ("oar-660-041-0010",
                 "\"DLCD\" means the Department of Land Conservation and Development"),
    },
    "land-use-board-of-appeals": {
        "LUBA": ("oar-340-018-0020",
                 "“LUBA” means the Land Use Board of Appeals"),
    },
    "legislative-commission-on-indian-services": {
        "LCIS": ("oar-736-051-0010",
                 "Legislative Commission on Indian Services (LCIS)"),
    },
    "office-of-training-investigations-and-safety": {
        "OTIS": ("oar-419-240-0100",
                 "Office of Training, Investigations and Safety (OTIS)"),
    },
    "oregon-business-development-department": {
        "OBDD": ("oar-123-670-0001",
                 "Oregon Business Development Department (OBDD)"),
    },
    "oregon-criminal-justice-commission": {
        "CJC": ("schedule-criminal-justice",
                 "Oregon Criminal Justice Commission (CJC)"),
    },
    "oregon-department-of-education": {
        "ODE": ("oar-581-051-0305",
                 "\"ODE\" means the Oregon Department of Education"),
    },
    "oregon-department-of-education-early-learning-division": {
        "DELC": ("oar-414-210-0100",
                 "\"DELC\" means the Department of Early Learning and Care"),
    },
    "oregon-film-and-video-office": {
        "OFVO": ("oar-951-003-0001",
                 "“OFVO” means the Oregon Film and Video Office"),
    },
    "oregon-forest-resources-institute": {
        "OFRI": ("oar-628-010-0005",
                 "“OFRI” means the Oregon Forest Resources Institute"),
    },
    "oregon-government-ethics-commission": {
        "OGEC": ("schedule-government-ethics",
                 "Oregon Government Ethics Commission (OGEC)"),
    },
    "oregon-health-authority": {
        "OHA": ("oar-340-245-0022",
                 "“OHA” means Oregon Health Authority"),
    },
    "oregon-health-authority-health-licensing-office": {
        "HLO": ("oar-816-005-0000",
                 "“HLO” means the Health Licensing Office"),
    },
    "oregon-health-authority-oregon-educators-benefit-board": {
        "OEBB": ("oar-409-025-0100",
                 "“OEBB” means the Oregon Educators Benefit Board"),
    },
    "oregon-health-authority-public-employees-benefit-board": {
        "PEBB": ("oar-459-035-0001",
                 "“PEBB” means the Public Employees’ Benefit Board"),
    },
    "oregon-housing-and-community-services-department": {
        "OHCS": ("oar-813-230-0000",
                 "“OHCS” means the Housing and Community Services Department"),
    },
    "oregon-investment-council": {
        "OIC": ("oar-459-050-0001",
                 "“OIC” means the Oregon Investment Council"),
    },
    "oregon-liquor-control-commission": {
        "OLCC": ("oar-845-002-0210",
                 "“OLCC” means the Oregon Liquor and Cannabis Commission"),
    },
    "oregon-military-department": {
        "OMD": ("das-60-000-01",
                 "Oregon Military Department (OMD)"),
    },
    "oregon-military-department-office-of-emergency-management": {
        "OEM": ("oar-128-030-0020",
                 "Office of Emergency Management (OEM)"),
        "ODEM": ("oar-104-010-0005",
                 "Oregon Department of Emergency Management (ODEM)"),
    },
    "oregon-patient-safety-commission": {
        "OPSC": ("oar-325-011-0045",
                 "Oregon Patient Safety Commission (OPSC)"),
    },
    "oregon-public-employees-retirement-system": {
        "PERS": ("oar-459-001-0000",
                 "Public Employees Retirement System (PERS)"),
    },
    "oregon-racing-commission": {
        "ORC": ("oar-462-220-0010",
                 "Oregon Racing Commission (ORC)"),
    },
    "oregon-state-treasury": {
        "OST": ("oar-170-055-0001",
                 "“OST” means the Office of the State Treasurer"),
    },
    "oregon-watershed-enhancement-board": {
        "OWEB": ("oar-695-004-0020",
                 "“OWEB” means the Oregon Watershed Enhancement Board"),
    },
    "oregon-youth-authority": {
        "OYA": ("oar-411-346-0110",
                 "\"OYA\" means Oregon Youth Authority"),
    },
    "parks-and-recreation-department": {
        "OPRD": ("oar-736-004-0015",
                 "\"OPRD\" means the Oregon Parks and Recreation Department"),
    },
    "psychiatric-security-review-board": {
        "PSRB": ("oar-309-035-0105",
                 "\"PSRB” means the Oregon Psychiatric Security Review Board"),
    },
    "public-utility-commission": {
        "PUC": ("oar-166-150-0185",
                 "Oregon Public Utility Commission (PUC)"),
    },
    "real-estate-agency": {
        "OREA": ("oar-863-015-0245",
                 "Oregon Real Estate Agency (OREA)"),
    },
    "secretary-of-state": {
        "SOS": ("oar-340-200-0025",
                 "\"SOS\" means Secretary of State"),
    },
    "southern-oregon-university": {
        "SOU": ("oar-573-050-0005",
                 "Southern Oregon University (SOU)"),
    },
    "teacher-standards-and-practices-commission": {
        "TSPC": ("oar-581-055-0001",
                 "“TSPC” means the Oregon Teacher Standards and Practices Commission"),
    },
    "water-resources-department": {
        "OWRD": ("oar-123-039-0010",
                 "“OWRD” means the Oregon Water Resources Department"),
        "WRD": ("oar-340-056-0100",
                 "“WRD” means Water Resources Department"),
    },
}

# A single token with two or more capitals is an acronym for this table's purposes.
ACRONYM = re.compile(r"(?=(?:.*[A-Z]){2})[A-Z][A-Za-z&]{1,9}")
CORPUS_ROOTS = ("rules", "agencies", "executive-orders", "statutes", "constitution",
                "external-references")
MIN_ALIAS_QUOTE_WORDS = 3

_DOCUMENT_INDEX: dict[str, str] | None = None


def corpus_document_text(doc_id: str):
    """The `## Full text` of the corpus document whose id is `doc_id`, whitespace collapsed,
    or None when this corpus holds no such document (or none whose text can be read) — which
    is 'could not check', never 'the document does not say it'.

    The index of ids is built once, from the file names, because ERF names every document
    file after its id and walks 80,000 of them."""
    global _DOCUMENT_INDEX
    if _DOCUMENT_INDEX is None:
        _DOCUMENT_INDEX = {}
        for root in CORPUS_ROOTS:
            for dirpath, _dirs, files in os.walk(REPO_ROOT / root):
                for name in files:
                    if name.endswith(".md"):
                        _DOCUMENT_INDEX.setdefault(name[:-3], os.path.join(dirpath, name))
    path = _DOCUMENT_INDEX.get(doc_id)
    if path is None:
        return None
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    i = text.find("## Full text")
    return " ".join((text[i:] if i >= 0 else text).split())


def _name_forms(name) -> set:
    """The spellings of one body name a corpus document may print it as, folded: the name, the
    name without a leading `Oregon `, `State ` or `the `, and — for the OAR index's compound
    `Parent, Child` — the child alone, which is what a rule prints when it names the body
    inside its own chapter. Folded for the 'is it in the quotation' test only."""
    if not isinstance(name, str) or not name.strip():
        return set()
    forms = {name}
    if "," in name:
        # COMPOUND NAME — NAME: the tail segment is the body's OWN name, the string a rule in
        # its own chapter prints. The head segment — the parent — is discarded and no
        # placement is derived from the string: hierarchy lives in `relations` (#174).
        forms.add(name.rsplit(",", 1)[1].strip())
    for form in list(forms):
        for prefix in ("Oregon ", "State ", "the ", "The "):
            if form.startswith(prefix):
                forms.add(form[len(prefix):])
    return {_fold(f) for f in forms if len(f.split()) >= 2}


def _fold(text) -> str:
    """A name or quotation folded for the 'is one of the body's names in it' test only: case
    and the typographic apostrophe, nothing else. The word-for-word match of the quotation
    against its document is NOT folded."""
    return " ".join(str(text).replace("\u2019", "'").split()).casefold()


def audit_alias_evidence(cat, aliases, evidence, doc_text, fallback_names=None) -> list[str]:
    """Faults in ALIAS_EVIDENCE and in the acronym aliases it is the record of.

    `doc_text` is `corpus_document_text` and has NO DEFAULT, for the reason
    `link_enabling_authority.audit_statutory_names` has none: a default would let a caller
    check the table's shape and take the quotations on faith."""
    by_slug = {o["slug"]: o for o in cat["organizations"]}
    # A body MANUAL_ENTRIES is about to add has no row yet; its name is the one it will be
    # added under (`fallback_names`), so the check does not need the row to exist first.
    fallback_names = fallback_names or {}
    problems = []
    for slug, names in sorted(aliases.items()):
        for alias in names:
            if ACRONYM.fullmatch(alias) and alias not in (evidence.get(slug) or {}):
                problems.append(
                    f"{slug}: acronym alias {alias!r} has no ALIAS_EVIDENCE — an acronym "
                    "enters `aliases` only with a quotation from a corpus document that "
                    "pairs it with the body's name")
    for slug, by_alias in sorted(evidence.items()):
        if slug not in aliases:
            problems.append(f"{slug}: ALIAS_EVIDENCE names a body ALIASES does not")
            continue
        row = by_slug.get(slug) or {"name": fallback_names.get(slug)}
        # NAME READER — JOIN: a corpus document's quotation matched against EVERY name the
        # body is known by — the statutory `name`, the OAR `oar_name` and its non-acronym
        # aliases — to decide whether the document is talking about this body. A document
        # prints whichever spelling its source used, so matching either is the point.
        own_names = set()
        for n in ([row.get("name"), row.get("oar_name")]
                  + [a for a in aliases[slug] if not ACRONYM.fullmatch(a)]):
            own_names |= _name_forms(n)
        for alias, pair in sorted(by_alias.items()):
            if alias not in aliases[slug]:
                problems.append(f"{slug}: ALIAS_EVIDENCE holds evidence for {alias!r}, which "
                                "ALIASES does not carry for it")
                continue
            if (not isinstance(pair, tuple) or len(pair) != 2
                    or not all(isinstance(x, str) and x.strip() for x in pair)):
                problems.append(f"{slug}: evidence for {alias!r} is not a (document id, "
                                f"quotation) pair: {pair!r}")
                continue
            doc_id, quote = pair
            if len(quote.split()) < MIN_ALIAS_QUOTE_WORDS:
                problems.append(f"{slug}: evidence for {alias!r} is under "
                                f"{MIN_ALIAS_QUOTE_WORDS} words, too short to pair a name "
                                "with an acronym")
                continue
            text = doc_text(doc_id)
            if text is None:
                problems.append(
                    f"{slug}: evidence for {alias!r} cites document {doc_id!r}, which this "
                    "corpus does not hold (or whose text could not be read) — could not "
                    "check, which is not the same as 'the document does not say it'")
                continue
            if " ".join(quote.split()) not in text:
                problems.append(
                    f"{slug}: evidence for {alias!r} quotes {doc_id!r} as {quote!r}, which "
                    "does not appear word for word in that document's full text")
                continue
            if not re.search(r"(?<![A-Za-z&])" + re.escape(alias) + r"(?![A-Za-z&])", quote):
                problems.append(f"{slug}: the quotation for {alias!r} does not contain it")
            if not any(n and n in _fold(quote) for n in own_names):
                problems.append(f"{slug}: the quotation for {alias!r} contains none of the "
                                "body's own names, so it does not pair the two")
    return problems


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
    # CORRECTED 2026-09-12. This row previously read "Cause confirmed (#354, same act as
    # #212): ORS 476.020(1), HB 2927". HB 2927 created the Department of Emergency
    # Management -- row 258 below, and correct there. Nobody confirmed it for the Fire
    # Marshal; "same act as #212" was an INFERENCE from the two reorganizations sharing a
    # session, recorded in the word "confirmed". That is the substitution this file exists
    # to refuse, so the wrong act is named here explicitly rather than quietly replaced.
    "260": "Budget reports 'STATE FIRE MARSHAL, DEPT OF' as its own department; OAR "
           "chapter 837 is still registered under the Department of State Police. Governing "
           "statute: ORS 476.020, which establishes the Department of the State Fire Marshal "
           "and its powers and enforcement duties (original enabling legislation HB 226, "
           "1917). The DETACHMENT is SB 762 (2021), which granted the office independent "
           "cabinet-level agency status separate from the Oregon State Police, effective "
           "2023-07-01 -- NOT HB 2927, which this row asserted until 2026-09-12. Operator "
           "determination, @morficflux, 2026-09-12; not machine-verified against the "
           "legislative corpus, which is unreachable from this checkout.",
    # REFINED 2026-09-12. HB 3073 was right and stays. What changed is the statute and the
    # NAME: this row cited ORS 326.430(1)(a) -- an ORS chapter 326 provision, which is the
    # Department of EDUCATION's chapter and was the division's authority only while it sat
    # under ODE. The standalone agency's own authority is ORS chapter 329A. The body is also
    # no longer called the Early Learning Division, which the registry slug still says.
    "588": "Budget reports 'EARLY LEARNING & CARE, DEPT OF' as its own department; OAR "
           "chapter 414 is still registered under the Department of Education. Created under "
           "ODE by HB 4165 (2012) and HB 3233 (2013) as the Early Learning Division, under "
           "the Early Learning Council, with ORS 326.430(1)(a) its authority in that era. "
           "DETACHED by HB 3073 (2021), which elevated it to the standalone cabinet-level "
           "Department of Early Learning and Care (DELC), launched 2023-07-01. Its own "
           "governing statute is ORS chapter 329A -- child care licensing and program "
           "administration. Operator determination, @morficflux, 2026-09-12; not "
           "machine-verified against the legislative corpus, which is unreachable here.",
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
    by_slug = {o["slug"]: o for o in cat["organizations"]}
    for slug, name, code in MANUAL_ENTRIES:
        # A BODY THAT HOLDS AN OAR CHAPTER IS NOT ONE THAT ISSUES NO RULES. This list is for
        # bodies the chapter scrape cannot see because they have no chapter; a row carrying
        # one contradicts the reason it is here. Remove it from MANUAL_ENTRIES (its row is
        # kept across a refresh by `absent_from_index_as_of`, not by this list). See
        # _proof_audit_refuses_a_manual_entry_that_holds_a_chapter().
        if (by_slug.get(slug) or {}).get("oar_chapter"):
            problems.append(f"{slug}: in MANUAL_ENTRIES (agencies that issue no rules) but "
                            f"its registry row holds oar_chapter "
                            f"{by_slug[slug]['oar_chapter']!r} -- remove it from "
                            f"MANUAL_ENTRIES")
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


def _absent_entry(slug, name, observation):
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

    `observation` IS A REAL, RECORDED FETCH -- `catalog_agencies.load_index_observation()`'s
    return value, never `None` and never manufactured here (code review of #353: an earlier
    version of this function stamped `date.today()` with no fetch and no observation behind
    it, a second, silent writer of a field this module's own REGISTRY_NOTE claims only
    `--refresh` ever writes -- exactly the substitution CONTEXT.md's overriding rule forbids,
    "could not check" printed as "checked, and it's gone" the day nothing had actually looked
    at the index at all). `main()` refuses to call this at all when no observation is on
    disk. The date this writes is `observation["retrieved"]` -- the day THAT fetch actually
    happened -- never today's date, which would be dishonest about a fetch that did not run
    today.

    VERIFIED GENUINELY ABSENT, NOT ASSUMED. These bodies are chapterless by construction (no
    OAR chapter exists for the Governor's office, the Legislative Assembly, and so on), so
    `raw_index_name` is the name itself, and the one thing worth checking against a REAL
    observation is that the mirror has not started listing this exact name as a chapterless
    group -- if it has, the mirror caught up and this is no longer a body the scrape cannot
    see; refuse to write a stale claim over that instead of silently asserting it."""
    if name in observation["groups"]:
        sys.exit(f"{slug}: {name!r} IS listed in the recorded index observation's "
                 "chapterless groups -- the mirror now carries this name, so it is no "
                 "longer one this constructor may claim absent. Review by hand instead "
                 "of adding it here.")
    return dict(catalog_agencies.scraped_entry(
        oar_name=name, oar_chapter=None, raw_index_name=name, source_url=None),
        slug=slug,
        **{catalog_agencies.ABSENT_FROM_INDEX_KEY: observation["retrieved"]})


def _require_observation_or_exit(missing, observation) -> None:
    """Refuse to proceed when `main()` has MANUAL_ENTRIES rows to add and no real, recorded
    index observation exists to date them from. Extracted from `main()` so --selftest can
    prove the refusal directly, with no CATALOG on disk and no call into `_absent_entry()`
    at all -- watched red the moment the old code called `_absent_entry(slug, name)`
    unconditionally, with no observation and no gate in front of it."""
    if missing and observation is None:
        sys.exit(f"no recorded index observation on disk (run "
                 "`catalog_agencies.py --refresh` first) -- refusing to invent an "
                 f"absent_from_index_as_of date for {len(missing)} missing MANUAL_ENTRIES "
                 "row(s) with no real observation behind them")


def _proof_main_refuses_missing_entries_with_no_observation() -> int:
    """`main()`, via `_require_observation_or_exit()`, must refuse outright when there is a
    MANUAL_ENTRIES row to add and no real index observation on disk -- and must NOT refuse
    when nothing is missing, even with no observation on disk, since nothing would be dated
    in that run at all."""
    bad = 0
    try:
        _require_observation_or_exit(["some-missing-slug"], None)
        print("FAIL main-refuses-missing-entries-with-no-observation: no SystemExit raised",
              file=sys.stderr)
        bad += 1
    except SystemExit:
        pass
    try:
        _require_observation_or_exit([], None)
    except SystemExit:
        print("FAIL main-only-refuses-when-something-is-missing: refused with nothing to "
              "add", file=sys.stderr)
        bad += 1
    return bad


def _proof_absent_entry_dates_the_observations_own_date_not_today() -> int:
    """`_absent_entry()` (#169/#353 review) writes `observation["retrieved"]`, the day a
    REAL fetch happened -- never `manual`, the flag this constructor used to write with no
    admitting evidence behind it, and never `date.today()`, which would be dishonest about a
    fetch that may have happened long before this script ran.

    WATCHED FAILING before this fix existed: this proof is what turned red the moment
    `_absent_entry()` stamped `date.today()` instead of the observation's own date -- restated
    here so a future reader does not have to git-log this file to find that out."""
    bad = 0
    observation = {"chapters": set(), "groups": {"Some Other Group"}, "retrieved": "2026-01-01"}
    entry = _absent_entry("test-slug", "Test Body", observation)
    if entry.get(catalog_agencies.ABSENT_FROM_INDEX_KEY) != "2026-01-01":
        print("FAIL absent-entry-dates-the-observations-own-date: "
              f"{entry.get(catalog_agencies.ABSENT_FROM_INDEX_KEY)!r}", file=sys.stderr)
        bad += 1
    if "manual" in entry:
        print(f"FAIL absent-entry-does-not-write-manual: {entry!r}", file=sys.stderr)
        bad += 1
    # THE OTHER HALF: a name the observation DOES list must be refused, not written.
    observation2 = {"chapters": set(), "groups": {"Test Body"}, "retrieved": "2026-01-01"}
    try:
        _absent_entry("test-slug", "Test Body", observation2)
        print("FAIL absent-entry-refuses-a-name-the-observation-lists: no SystemExit raised",
              file=sys.stderr)
        bad += 1
    except SystemExit:
        pass
    return bad


def _proof_audit_refuses_a_manual_entry_that_holds_a_chapter() -> int:
    """`audit()` must refuse a MANUAL_ENTRIES slug whose registry row carries an
    `oar_chapter`. MANUAL_ENTRIES is the list of bodies that issue NO rules; a row holding a
    chapter says the opposite, and the two cannot both be true. The State Board of Tax
    Practitioners sat in this list for months while OARD served its 800 chapter, and because
    catalog_oar.registry_chapters() walks only rows that carry `oar_chapter`, chapter 800 was
    never discovered or ingested. The rule cannot see a chapter the row does not record
    (that needs OARD's dropdown), but it stops the row from claiming both at once."""
    slug = MANUAL_ENTRIES[0][0]
    cat = {"organizations": [{"slug": s, "name": n} for s, n, _ in MANUAL_ENTRIES]}
    for o in cat["organizations"]:
        if o["slug"] == slug:
            o["oar_chapter"] = "999"
    hit = [p for p in audit(cat) if p.startswith(f"{slug}:") and "oar_chapter" in p]
    if not hit:
        print(f"FAIL audit-refuses-a-manual-entry-that-holds-a-chapter: {slug} given "
              "oar_chapter '999' and audit() said nothing", file=sys.stderr)
        return 1
    return 0


def _proof_an_acronym_alias_needs_a_quotation_that_pairs_it_with_the_name() -> int:
    """Every way an acronym alias's record can be wrong is refused, and the one valid record is
    not. The corpus here is two synthetic documents, so the proof reads nothing real and
    asserts nothing about any real body."""
    docs = {"doc-a": "Purpose The Imaginary Bureau of Affairs (IBA) licenses imagined things. "
                     "The Imaginary Bureau of Affairs also inspects them.",
            "doc-b": "Definitions IBA means something else entirely."}
    cat = {"organizations": [{"slug": "imaginary-bureau", "name": "Imaginary Bureau of Affairs",
                              "oar_name": "Imaginary Bureau of Affairs"}]}
    good = ("doc-a", "The Imaginary Bureau of Affairs (IBA) licenses imagined things.")
    cases = [
        ("an acronym with no evidence at all", {}, None),
        ("a quotation the document does not say",
         {"imaginary-bureau": {"IBA": ("doc-a", "The Imaginary Bureau of Affairs (IBA) "
                                                 "licenses real things.")}}, "word for word"),
        ("a document this corpus does not hold",
         {"imaginary-bureau": {"IBA": ("doc-z", good[1])}}, "could not check"),
        ("a quotation that does not contain the acronym",
         {"imaginary-bureau": {"IBA": ("doc-a", "The Imaginary Bureau of Affairs also "
                                                 "inspects them.")}}, "does not contain it"),
        ("a quotation that names none of the body's own names",
         {"imaginary-bureau": {"IBA": ("doc-b", "IBA means something else entirely.")}},
         "none of the body's own names"),
    ]
    bad = 0
    aliases = {"imaginary-bureau": ["IBA"]}
    for label, evidence, phrase in cases:
        problems = audit_alias_evidence(cat, aliases, evidence, docs.get)
        if not problems or (phrase and not any(phrase in p for p in problems)):
            print(f"FAIL acronym-alias-{label.replace(' ', '-')}: {problems!r}",
                  file=sys.stderr)
            bad += 1
    held = audit_alias_evidence(cat, aliases, {"imaginary-bureau": {"IBA": good}}, docs.get)
    if held:
        print(f"FAIL acronym-alias-with-a-true-quotation-passes: {held!r}", file=sys.stderr)
        bad += 1
    # A FORMER NAME IS NOT AN ACRONYM and needs no quotation: older aliases here carry none.
    if audit_alias_evidence(cat, {"imaginary-bureau": ["Bureau of Imagined Affairs"]}, {},
                            docs.get):
        print("FAIL a-former-name-needs-no-quotation", file=sys.stderr)
        bad += 1
    return bad


def selftest() -> int:
    bad = _proof_an_acronym_alias_needs_a_quotation_that_pairs_it_with_the_name()
    bad += _proof_absent_entry_dates_the_observations_own_date_not_today()
    bad += _proof_main_refuses_missing_entries_with_no_observation()
    bad += _proof_audit_refuses_a_manual_entry_that_holds_a_chapter()
    if bad:
        print(f"{bad} proof(s) did not hold", file=sys.stderr)
        return 1
    print("4 proofs held: _absent_entry() dates the observation's own date (never "
          "today()/manual) and refuses a name the observation already lists; main() "
          "refuses to add anything when no observation is recorded at all; audit() "
          "refuses a MANUAL_ENTRIES body whose row holds an OAR chapter; "
          "audit_alias_evidence() refuses an acronym alias with no quotation, a quotation "
          "its document does not say, a document the corpus does not hold, and a quotation "
          "that does not pair the acronym with one of the body's names")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    check = "--check" in sys.argv
    cat = load()
    problems = audit(cat) + audit_alias_evidence(
        cat, ALIASES, ALIAS_EVIDENCE, corpus_document_text,
        {slug: name for slug, name, _code in MANUAL_ENTRIES})
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
        acronyms = sum(1 for names in ALIASES.values() for a in names if ACRONYM.fullmatch(a))
        print(f"\n{len(want)} codes mapped, {len(UNMAPPED)} deliberately unmapped, "
              f"{len(MANUAL_ENTRIES)} manual entries, "
              f"{sum(len(v) for v in ALIASES.values())} aliases, of which {acronyms} "
              "acronym(s), each paired with its body's name by a quotation matched word for "
              "word against the corpus document it names"
              if not bad else f"\n{bad} discrepancy(ies)")
        return 1 if bad else 0

    missing = [(slug, name) for slug, name, _code in MANUAL_ENTRIES if slug not in by_slug]
    # REFUSE OUTRIGHT RATHER THAN INVENT A DATE (#353 review): a MANUAL_ENTRIES row missing
    # from the registry needs `absent_from_index_as_of` stamped on it, and that field is a
    # dated observation of a REAL fetch, never a value this script may manufacture. See
    # `_require_observation_or_exit()` and `_absent_entry()`.
    observation = catalog_agencies.load_index_observation() if missing else None
    _require_observation_or_exit(missing, observation)
    added = 0
    for slug, name in missing:
        # BUILT BY THE REGISTRY'S OWN CONSTRUCTOR, not by a second hand-written copy of the
        # row shape. These rows sit in the same file as the scraped ones and must carry the
        # same keys, and the two spellings of that shape had already drifted apart: adding
        # `oar_name` to catalog_agencies.FIELDS left this dict a field short, so the row it
        # rebuilt failed --check's required-field rule. One constructor means the next field
        # cannot repeat that. The declared slug still wins over the derived one, because
        # MANUAL_ENTRIES is where a body the scrape cannot see gets its identity (the two
        # agree on all 11 today).
        #
        # The OAR name (CONTEXT.md) it ends up with is the body's own name. These bodies
        # hold no OAR chapter — that is why the scrape cannot see them — so there is no
        # chapter title to differ from it, and copying it asserts nothing about what the
        # rules index prints. It is written because `oar_name` is the string consumers
        # join on from here (ADR 0003), and a row without one is a row those joins lose.
        entry = _absent_entry(slug, name, observation)
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
