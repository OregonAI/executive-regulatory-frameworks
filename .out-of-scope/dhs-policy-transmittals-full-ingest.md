# Out of scope: the full ODHS Policy Transmittal SharePoint ingest

**Decided:** 2026-10-01, closing the pilot issue #79 opened for exactly this decision.
**Status:** excluded. A full ingest of any ODHS program's Policy Transmittal system is
not planned, on the pilot's own measured result below. This is a decided exclusion,
replacing the undocumented de-facto one `_meta/agency-profiles.yml` already recorded for
the 17 held DHS policies ("the separate program Transmittals system ... is out of scope").

## What #79 asked the pilot to measure

> Proceed to the full Policy Transmittal ingest only if **both** hold:
> 1. the pilot set resolves a supersession or effective date for **≥50%** of the DHS
>    policies it references, and
> 2. it surfaces **at least one** policy currently held that is demonstrably stale.

## What was ingested

25 real documents — the 25 most recent **Policy**-type Policy Transmittals from ODHS's
Aging and People with Disabilities (APD) program, an unbiased recency cut (not chosen for
topical closeness to the 17 held DHS policies) — as `doc_type: transmittal`,
`content_mode: verbatim`, full text, in
[`agencies/department-of-human-services/transmittals/`](../agencies/department-of-human-services/transmittals/).
Source manifest:
[`_meta/sources/department-of-human-services-transmittals.yml`](../_meta/sources/department-of-human-services-transmittals.yml).
`corpus-validate-frontmatter` and `corpus-verify-provenance` both pass on all 25.

## Measured result

Computed by [`src/build_dhs_transmittal_freshness.py`](../src/build_dhs_transmittal_freshness.py)
from each transmittal's own `announces` field (extracted only from its own "Policy/rule
numbers:" form field — never its subject line, per AGENTS.md's anti-fabrication rule):

| Row | Measured | Bar | Result |
|---|---|---|---|
| Policies referenced (the pilot set's own citations) | **0** | — | — |
| 1. % of DHS policies **it references** resolved | **0 / 0 (undefined)** | ≥ 50% | **FAIL (vacuous)** |
| 1b. for context: % of all 17 held DHS policies resolved | 0 / 17 (0%) | — | — |
| 2. policies surfaced as demonstrably stale | **0** | ≥ 1 | **FAIL** |

**Both legs fail.** All 25 ingested transmittals' `announces` field is `[]`: every one
cites an OAR rule chapter/division, a Collective Bargaining Agreement, or another APD
transmittal in its own "Policy/rule numbers:" field — never a `dhs-0XX-0XX` id. Leg 1 is
the issue's own bar (quoted above): because the pilot set references zero of the 17 held
policies, that leg fails vacuously (0/0), a stronger statement than "0/17" — row 1b is
reported only for context, not as a substitute denominator.

## Why, not just that

The issue's working assumption — recorded in the 2026-10-01 survey this pilot was scoped
from — was to pilot "the program owning the dhs-010-* series". That program does not
exist, verified directly against ODHS's own site before any document was fetched:

- The 17 DHS policies this corpus holds (8 of them `dhs-010-*`) are **all** agency-wide,
  Director's Office administrative policies — public records, bilingual services,
  equity/REALD, donated funds, access to records, employment accommodation. None is a
  case-service program policy.
- `_meta/sources/department-of-human-services-policies.yml` already records why: they
  come from the "policiesguidelines" SharePoint list filtered to `Agency_x0020_1 ==
  'ODHS'` exactly, "not the separate program Transmittals system".
- ODHS runs Policy Transmittals **per case-service program** — confirmed from
  `/odhs/transmittals`'s own navigation and each program's SharePoint `ListUrl`: APD, CW,
  ODDS, OEP, SSP, VR. There is no Director's-Office/"central" transmittals list (every
  plausible URL guessed for one returned 404).
- Across all six programs' Policy-type transmittals (924 total: APD 309, ODDS 344, SSP
  115, OEP 122, CW 34), a metadata-level scan found zero whose Title/Subject cites any of
  the 17 held policy numbers. The 25 ingested APD documents' own structured "Policy/rule
  numbers:" form field confirms this at the full-text level: APD's own numbering is OAR
  411/461 chapters, Collective Bargaining Agreements, and its own prior transmittals — a
  numbering scheme that does not share a namespace with the agency-wide `dhs-0XX-0XX`
  series at all.

So the pilot's premise and its measured result agree: there is no program whose Policy
Transmittals announce changes to the kind of DHS policy this corpus holds. A full ingest
of APD's ~1,600 transmittals (or any other program's) would add real, verbatim documents
with a working `announces` mechanism, but by the evidence above it would resolve close to
none of the 17 DHS policies — the thing the freshness signal exists to compute.

## What is NOT excluded

- The `transmittal` doc_type, the ingestion pipeline (`src/ingest_transmittals.py`), and
  the freshness join (`src/build_dhs_transmittal_freshness.py`) all stay. They are real,
  tested, working infrastructure; only the decision to pour ~1,600 more documents through
  them is declined.
- A **different** source of dates for the 17 DHS policies' freshness — e.g. the agency-wide
  "policiesguidelines" SharePoint list's own revision metadata, if it carries any beyond
  the PDF's own header — was not evaluated here and is a separate question from this
  pilot's.
- None of the 17 existing DHS policy documents were touched. Per #79's own scope and ADR
  0001, a stale-looking policy is a finding to report, not an edit to make; none was found
  stale by this join (0 `stale: true` entries in
  [`_meta/dhs_transmittal_freshness.json`](../_meta/dhs_transmittal_freshness.json)).
