# Department of Human Services — transmittals — index

Policy Transmittals (`doc_type: transmittal`) issued by Department of Human Services
(`agency: department-of-human-services`). **Non-authoritative copies** — see [AGENTS.md](../../../AGENTS.md).

Pilot ingest per issue #79: the 25 most recent *Policy*-type transmittals from ODHS's
Aging and People with Disabilities (APD) program — one program's own change-announcement
system, distinct from the agency-wide policy list the 17 DHS policies in
[`../policies/`](../policies/) come from. A transmittal carries `announces`: the ids of
policies in this corpus it names a change to, read from its own "Policy/rule numbers:"
field — never its subject line. See [CHANGELOG](./CHANGELOG.md) and
[`.out-of-scope/dhs-policy-transmittals-full-ingest.md`](../../../.out-of-scope/dhs-policy-transmittals-full-ingest.md)
for the pilot's measured result against issue #79's bar.

The freshness this doc_type supplies is a build-time join
(`src/build_dhs_transmittal_freshness.py`), never a field on the policy — see
[`docs/adr/0001-transmittal-dates-are-computed-never-stored.md`](../../../docs/adr/0001-transmittal-dates-are-computed-never-stored.md).

| Number | Subject | Date | `announces` | Path |
|---|---|---|---|---|
| APD-PT-26-011 | Impacts of HR1 Non-Citizen Changes to OPI-M Consumers | 2026-09-11 | _(none)_ | `dhs-apd-pt-26-011.md` |
| APD-PT-26-010 | Biennial licensure of APD AFH | 2026-08-06 | _(none)_ | `dhs-apd-pt-26-010.md` |
| APD-PT-26-009 | Community Based, PACE & Nursing Facility Rates | 2026-06-29 | _(none)_ | `dhs-apd-pt-26-009.md` |
| APD-PT-26-008 | Collective Bargaining Agreement | 2026-05-13 | _(none)_ | `dhs-apd-pt-26-008.md` |
| APD-PT-26-007 | Home and Community-Based Services Waiver Compliance Requirements | 2026-05-12 | _(none)_ | `dhs-apd-pt-26-007.md` |
| APD-PT-24-028 | APS Screening Decisions: Documentation and Notification to Reporters | 2026-04-28 | _(none)_ | `dhs-apd-pt-24-028.md` |
| APD-PT-26-006 | APS Screening Decisions and Documentation | 2026-04-28 | _(none)_ | `dhs-apd-pt-26-006.md` |
| APD-PT-26-005 | Homecare Worker, Personal Support Worker and Personal Care Attendant Rural | 2026-04-17 | _(none)_ | `dhs-apd-pt-26-005.md` |
| APD-PT-26-004 | OPI-M Local Office Ancillary Approvals | 2026-03-06 | _(none)_ | `dhs-apd-pt-26-004.md` |
| APD-PT-26-003 | Staff Response to Immigration and Customs Enforcement (ICE) Activities | 2026-02-19 | _(none)_ | `dhs-apd-pt-26-003.md` |
| APD-PT-26-002 | The Work Number Changes for Oregon Project Independence - Medicaid | 2026-02-12 | _(none)_ | `dhs-apd-pt-26-002.md` |
| APD-PT-26-001 | Local Office Lift Chair Approvals | 2026-01-12 | _(none)_ | `dhs-apd-pt-26-001.md` |
| APD-PT-25-026 | Community Based, PACE & Nursing Facility Rates | 2025-12-22 | _(none)_ | `dhs-apd-pt-25-026.md` |
| APD-PT-25-025 | New Facility Safety Plan (FSP) Form for APS Investigations in Assisted Living Facilities | 2025-12-19 | _(none)_ | `dhs-apd-pt-25-025.md` |
| APD-PT-25-024 | Older Americans Act Policies and Procedures | 2025-12-17 | _(none)_ | `dhs-apd-pt-25-024.md` |
| APD-PT-25-023 | Rate Methodology Change for AFH and RCF Settings | 2025-12-12 | _(none)_ | `dhs-apd-pt-25-023.md` |
| APD-PT-25-022 | 2025-2027 HCW CBA Ratification | 2025-12-09 | _(none)_ | `dhs-apd-pt-25-022.md` |
| APD-PT-25-021 | Program of All-inclusive Care for the Elderly (PACE) participant liability | 2025-12-05 | _(none)_ | `dhs-apd-pt-25-021.md` |
| APD-PT-25-020 | Deidentifying licensor initials in licensing documents | 2025-12-01 | _(none)_ | `dhs-apd-pt-25-020.md` |
| APD-PT-25-019 | COAPS SAFELINE Screening Pilot Project | 2025-10-23 | _(none)_ | `dhs-apd-pt-25-019.md` |
| APD-PT-25-018 | Animal care and incidental activities as part of In-Home Services | 2025-10-10 | _(none)_ | `dhs-apd-pt-25-018.md` |
| APD-PT-25-017 | OPI-M Case Management Contacts and Risk Monitoring | 2025-10-03 | _(none)_ | `dhs-apd-pt-25-017.md` |
| APD-PT-25-016 | Long-term Care | 2025-09-12 | _(none)_ | `dhs-apd-pt-25-016.md` |
| APD-PT-25-015 | Emergency Response Management (ERM) system use | 2025-07-24 | _(none)_ | `dhs-apd-pt-25-015.md` |
| APD-PT-25-014 | Changes to Extended Waiver Eligibility process | 2025-07-03 | _(none)_ | `dhs-apd-pt-25-014.md` |

`announces` is empty on all 25: each one's own "Policy/rule numbers:" field cites an OAR
chapter/division, a Collective Bargaining Agreement, or another APD transmittal — never a
`dhs-0XX-0XX` id.
