# Oregon Accounting Manual (OAM) — index

Statewide financial policy from the DAS Chief Financial Office / Office of the State
Controller. **Non-authoritative copies.** Contents mirror the OAM **listing of record**
(the 16 chapter tables on oregon.gov/das/financial/osc/pages/oam.aspx, consumed via
their SharePoint REST data source; normalized snapshot:
[`oam-listing.json`](../../../_meta/snapshots/oam-listing.json), retrieved 2026-07-18).
Numbering: Chapter.Part.Section; suffixes `.po` policy, `.pr` procedure, `.fo` form.

| Chapter | Title | Listed | Ingested |
|---|---|---|---|
| 01 | Introduction | 3 | 2 |
| 05 | R*STARS | 7 | 6 |
| 10 | Internal control | 22 | 21 |
| 15 | Accounting & financial reporting | 30 | 29 |
| 20 | Budgetary accounting & reporting | 7 | 6 |
| 25 | Management accounting | 3 | 2 |
| 30 | Federal compliance | 8 | 7 |
| 35 | Accounts receivable management | 20 | 19 |
| 40 | Travel | 5 | 4 |
| 45 | Payroll | 21 | 20 |
| 50 | Tax issues | 10 | 9 |
| 55 | Other programs | 3 | 3 |
| 60 | Chart of accounts | 4 | 3 |
| 65 | Glossary | 1 | 1 |
| 70 | Agency lists | 4 | 4 |
| 75 | Forms | 27 | 25 |
| **all** | | **175** | **161** |

Not-ingested rows are the 12 chapter-wide compiled PDFs ("NN Complete Chapter") and 2
form rows with no document id — see [`_meta/catalog/oam.yml`](../../../_meta/catalog/oam.yml)
for every row with its status and path.

## How to find the right document

- **Internal control** (incl. ACH security, statewide controls): chapter 10.
- **Accounting & financial reporting** (capital assets 15.60.xx, closing, CAFR): chapter 15.
- **Budgetary accounting**: chapter 20. **Management accounting**: chapter 25.
- **Federal compliance / Single Audit**: chapter 30. **Accounts receivable**: chapter 35.
- **Travel** (incl. rates and expense rules): chapter 40. **Payroll**: chapter 45.
- **Tax issues** (1099, fringe benefits, transit tax): chapter 50.
- **SPOTS purchase cards**: chapter 55. **Chart of accounts**: chapter 60.
- **Glossary**: chapter 65. **Agency number lists**: chapter 70. **Forms**: chapter 75.
- Many older documents exist as split `.po` (policy) + `.pr` (procedure) pairs — both are
  ingested separately, named `oam-NN-NN-NN-po.md` / `-pr.md`.
- ⚠️ 12 additional files under this directory are **pending drafts not in the listing of
  record** (status `proposed`/`draft`, prominently annotated) — kept because DAS still
  serves them from its older OAM page.

## Freshness

`python3 src/detect_changes.py` re-queries the 16 chapter views and diffs rows
(id | effective date | file path) against the committed listing snapshot, plus checks
every document's content hash.
