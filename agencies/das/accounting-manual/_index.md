# Oregon Accounting Manual (OAM) — index

Statewide financial policy from the DAS Chief Financial Office / Office of the State
Controller (oregon.gov/das/financial/osc). Numbering: Chapter.Part.Section with suffixes
`PO` (policy), `PR` (procedure), `FO` (form), `RF` (reference). The suffix is dropped once
a policy and procedure are combined into a single document (all documents here already
follow that combined form). **Non-authoritative copies.**

| Chapter | Topic | Documents |
|---|---|---|
| 05 | R*STARS | [05.20.00](oam-05-20-00.md) Fund and Appropriation Structure |
| 10 | Internal Control | [10.75.00](oam-10-75-00.md) ACH Security |
| 15 | Accounting & Financial Reporting | [15.40.00](oam-15-40-00.md) Expenditures · [15.41.00](oam-15-41-00.md) Withholding from Non-State Entities · [15.45.10](oam-15-45-10.md) Interfund Transactions · [15.60.10](oam-15-60-10.md) Capital Asset Classification · [15.60.20](oam-15-60-20.md) Depreciation · [15.60.25](oam-15-60-25.md) Capital Asset Impairments · [15.60.30](oam-15-60-30.md) Capital Leases · [15.60.40](oam-15-60-40.md) Intangible Assets · [15.80.00](oam-15-80-00.md) Commitments · [15.92.00](oam-15-92-00.md) Fiduciary Activities · [15.95.00](oam-15-95-00.md) Year-End Closing (⚠️ draft) · [15.97.00](oam-15-97-00.md) Agency Financial Reporting |
| 20 | Budgetary Accounting and Reporting | [20.20.00](oam-20-20-00.md) Encumbrances |
| 30 | Federal Compliance | [30.40.00](oam-30-40-00.md) Subrecipient Monitoring |
| 45 | Payroll | [45.05.00](oam-45-05-00.md) Regular Pay Days · [45.06.00](oam-45-06-00.md) Sick Leave at Retirement · [45.10.00](oam-45-10-00.md) Voluntary Deductions (⚠️ draft) · [45.15.00](oam-45-15-00.md) Payroll Accounts Reimbursement (⚠️ draft) · [45.17.00](oam-45-17-00.md) Payroll Data Integrity · [45.20.00](oam-45-20-00.md) Cash Insurance Payments · [45.25.00](oam-45-25-00.md) Salary Advances (⚠️ draft) · [45.30.00](oam-45-30-00.md) Dual Update Access · [45.35.00](oam-45-35-00.md) Review of Gross Pay Adjustments (⚠️ draft) · [45.37.00](oam-45-37-00.md) Review of Month-End Leave Reports · [45.40.00](oam-45-40-00.md) Reimbursement of Employee Expenses · [45.42.00](oam-45-42-00.md) Distributions with Payroll · [45.45.00](oam-45-45-00.md) Separation of Duties |
| 50 | Tax Issues | [50.10.00](oam-50-10-00.md) Education Assistance Payments (⚠️ draft) · [50.30.00](oam-50-30-00.md) Fringe Benefits—Vehicles (⚠️ draft) · [50.50.00](oam-50-50-00.md) 1099-MISC (⚠️ draft) · [50.60.00](oam-50-60-00.md) Mass Transit Tax (⚠️ draft) |
| 55 | Other Programs | [55.30.00](oam-55-30-00.md) SPOTS Purchase Card Program |
| 60 | Chart of Accounts | [60.10.00](oam-60-10-00.md) General Ledger Accounts · [60.20.00](oam-60-20-00.md) Comptroller Objects by Classification · [60.30.00](oam-60-30-00.md) Comptroller Objects, Numeric Sequence |
| 65 | Glossary | [65.00.00](oam-65-00-00.md) Definitions |
| 70 | (agency numbering reference) | [70.20.00](oam-70-20-00.md) Current Agencies, Numeric Sequence |
| 75 | Forms | [75.30.02](oam-75-30-02.md) Sample Completion Letter (Subrecipient Single Audit) |

## How to find the right document

- **Capital assets** (classification, depreciation, impairment, leases, intangibles): the
  15.60.xx cluster.
- **Payroll**: the 45.xx cluster; several (⚠️-marked) are unfinished drafts on DAS's own
  site — their printed effective date is a template placeholder (`MM/DD/YYYY`,
  `XX/XX/XXXX`, or `TBD`), so `status: draft` in frontmatter, never `current`.
- **Chart of accounts / account lookup tables**: chapter 60 (`content_mode: summary` —
  these are large reference tables, not prose policy, and are not reproduced verbatim).
- **Glossary**: 65.00.00.

## Full coverage map

[`_meta/catalog/oam.yml`](../../../_meta/catalog/oam.yml) is now a completeness
cross-check (all 40 discovered documents are ingested) rather than a to-do list — use
`src/detect_changes.py` against `_meta/source-manifest.yml` to check for upstream
freshness instead.
