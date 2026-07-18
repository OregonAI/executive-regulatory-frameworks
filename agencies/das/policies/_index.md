# DAS statewide policies — index

Administrative policies (not law) binding Oregon executive-branch agencies, published as
PDFs at oregon.gov/das/Policies. Numbering encodes program area (107-001 general/records;
107-004 IT/information security; 107-011 asset management/facilities; 50-xxx HR).
Procedures carry a `_PR` suffix. **Non-authoritative copies.**

| Citation | Title | Status | Effective | Path |
|---|---|---|---|---|
| DAS 107-001-020 | Public Records Management | current | 2025-06-01 | [das-107-001-020.md](das-107-001-020.md) |
| DAS 107-004-010 | IT Asset Inventory & Management | current | 2008-09-08 | [das-107-004-010.md](das-107-004-010.md) |
| DAS 107-004-050 | Information Asset Classification | current | 2023-07-12 | [das-107-004-050.md](das-107-004-050.md) |
| DAS 107-004-051 | Controlling Portable and Removable Storage Devices | current | 2007-07-30 | [das-107-004-051.md](das-107-004-051.md) |
| DAS 107-004-052 | Cyber and Information Security | current | 2026-02-17 | [das-107-004-052.md](das-107-004-052.md) |
| DAS 107-004-052_PR | Cyber and Information Security Procedure | current | 2026-02-17 | [das-107-004-052_pr.md](das-107-004-052_pr.md) |
| DAS 107-004-100 | Transporting Information Assets | current | 2008-01-31 | [das-107-004-100.md](das-107-004-100.md) |
| DAS 107-004-110 | Acceptable Use of State Information Assets | current | 2010-01-01 | [das-107-004-110.md](das-107-004-110.md) |
| DAS 107-004-120 | Cyber and Information Security Incident Response | current | 2020-11-16 | [das-107-004-120.md](das-107-004-120.md) |
| DAS 107-004-140 | Privileged Access to Information Systems | current | 2013-07-10 | [das-107-004-140.md](das-107-004-140.md) |
| DAS 107-004-150 | Cloud and Hosted Systems | current | 2019-05-01 | [das-107-004-150.md](das-107-004-150.md) |
| DAS 107-004-160 | Data Governance | current | 2022-02-09 | [das-107-004-160.md](das-107-004-160.md) |

## How to find the right policy

- **Overall security program, roles, baseline, offshoring:** 107-004-052 (+ procedure
  107-004-052_PR for CSS assessments and offshore exceptions).
- **What classification level applies to data:** 107-004-050; data governance programs:
  107-004-160.
- **Acceptable use of state devices/systems:** 107-004-110; admin/root access at the
  State Data Center: 107-004-140.
- **Incident response:** 107-004-120. **Cloud contracts:** 107-004-150. **Removable
  media:** 107-004-051; transporting media: 107-004-100. **Asset inventory:** 107-004-010.
- **Public records:** 107-001-020.
- **For the underlying control requirements** a policy points to, see
  [../standards/](../standards/_index.md).
- ⚠️ 107-004-051 and 107-004-100 are image-only scans: summary-only files, no verbatim
  quotes.

## Full coverage map

DAS's policy index page (oregon.gov/das/Pages/policies.aspx) renders its list via
client-side JavaScript with no public sitemap, so no single authoritative source
enumerates every policy. [`_meta/catalog/das-policies.yml`](../../../_meta/catalog/das-policies.yml)
is a best-effort discovery map — compiled from search-engine indexing of individual
policy PDFs on 2026-07-18 — covering 12 ingested policies plus ~24 discovered-but-not-ingested
across General/Records, IT & Security, Procurement, Facilities/Fleet/Surplus, and HR. It is
almost certainly incomplete (Publishing, Risk Management, and most HR sub-categories have no
confirmed policy numbers yet); treat gaps as "not yet discovered," not "doesn't exist," and
never assume a "(title TBD)" entry's title without checking the source at ingestion time.
