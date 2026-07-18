# Changelog — Oregon Accounting Manual (OAM)

All notable changes to the curated copies in this directory. Format based on
[Keep a Changelog](https://keepachangelog.com/); change types: Added, Source-Updated,
Superseded, Repealed, Removed, Verified, Fixed, Security. This repo is non-authoritative;
dates below are repo-curation dates, not official effective dates (those live in each
file's frontmatter).

## [Unreleased]

## [2026-07-18] — full-text-first migration

### Changed

- All state-authored documents in this knowledge body migrated to the full-text-first
  content policy: complete verbatim source text now lives under each file's
  `## Full text` section (generated from the committed source snapshots; page furniture
  stripped and recorded in `conversion_notes`); inline [VERBATIM]/[SUMMARY] tags retired;
  curator content confined to At a glance / Curator notes / Cross-references;
  `content_mode: verbatim`. Source hashes unchanged (snapshots were fetched 2026-07-17/18;
  not re-fetched). CI now verifies every full-text line against the snapshot in order,
  plus a completeness coverage check.
- Exceptions (content_exception, still summary): oam-55-30-00-appendix-b, oam-75-35-12-fo, oam-75-40-01-fo (binary .xls/.xlsx forms).


## [2026-07-18] (2) — scope fix: rebuilt from the listing of record

### Fixed

- **Scope bug**: the initial OAM ingest was built from the static HTML of
  Acctng/Pages/OAM.aspx, which exposes only ~40 documents and mixes in pending
  comment-period drafts. The actual OAM listing of record — the 16 "OAM Chapter NN"
  SharePoint views rendered by das/financial/osc/pages/oam.aspx — carries **175 rows
  across 16 chapters**, including chapters 25 (Management accounting), 35 (Accounts
  receivable management), and 40 (Travel) that were missing entirely. The listing is now
  consumed directly from its anonymous REST data source (endpoint + view GUIDs + row
  snapshot in `_meta/snapshots/oam-listing.json`).
- Corrected source URLs for oam-10-75-00, oam-30-40-00, oam-60-30-00 (the listing points
  to different filenames than previously fetched; 60.30.00 had been ingested from a
  draft file).
- 12 previously-ingested documents are **not in the listing of record** (pending
  comment-period drafts from the old page): 15.92.00, 15.95.00, 15.97.00, 45.10.00,
  45.15.00, 45.25.00, 45.35.00, 50.10.00, 50.30.00, 50.50.00, 50.60.00, 75.30.02. Kept
  with prominent warnings; current-status ones demoted to `proposed`. The listing instead
  carries the older split .po/.pr documents as current.
- Date-typo notes added to oam-15-60-20, oam-15-60-25, oam-45-20-00 where the listing's
  date differs from the date the document itself prints (documents win).

### Added

- 132 documents from the listing of record, including all of chapters 25, 35 (19 AR
  docs), 40 (Travel), the split .po/.pr pairs for chapters 10–75, 24 more chapter-75
  forms, and oam-15-60-30-draft (the pending GASB 87 Leases rewrite, which the listing
  carries alongside the current 2012 policy under the same document id).
- `detect_changes.py` now re-queries the 16 chapter views on every run (manifest id
  `oam-listing`) and diffs rows by (id | effective date | file path) — adds, removals,
  and date changes are all flagged.
- 3 non-PDF forms (.xls/.xlsx) snapshotted raw with raw-byte hashes; schema
  `source_format` extended with xls/xlsx/docx.

### Removed

- Not ingested by design: the 12 "NN Complete Chapter" compiled PDFs (duplicate
  per-document content) and 2 form rows with no document id — all cataloged in
  `_meta/catalog/oam.yml`.

Verified-by @morficflux.

## [2026-07-18]

### Added

- Full OAM ingest from `_meta/catalog/oam.yml`: 40 documents across 12 chapters (05, 10,
  15, 20, 30, 45, 50, 55, 60, 65, 70, 75). 10 candidates 404'd at their catalog-listed
  URL and were re-fetched from corrected filenames found in the OAM.aspx page's raw HTML
  (15.92.00, 15.95.00, 45.10.00, 45.15.00, 45.25.00, 45.35.00, 50.10.00, 50.30.00,
  50.50.00, 50.60.00). Two documents (20.20.00, 70.20.00) not shown on the listing page
  at discovery time were fetched directly and confirmed to exist; 75.30.02's real
  filename also differed from the catalog guess.
- 6 documents (chapters 60, 65, 75 — chart-of-accounts lookup tables, glossary, and a
  sample form) ingested as `content_mode: summary` with no verbatim quotes: they are
  large reference tables/lists, not prose policy.
- 9 documents (chapter 45.05/06/17/20/30/37/40/42/45, older numbered-outline format with
  no PURPOSE heading) quoted from their first substantive numbered provision instead of
  a purpose statement.
- 8 documents genuinely marked `status: draft`: their own printed effective date is a
  template placeholder (`MM/DD/YYYY`, `XX/XX/XXXX`, or `TBD`) — 15.95.00, 45.10.00,
  45.15.00, 45.25.00, 45.35.00, 50.10.00, 50.30.00, 50.50.00, 50.60.00. (15.92.00 has a
  real printed date, 07/01/2019, despite its filename saying "draft" — ingested as
  `current` since the document text itself prints no draft marker.)

Verified-by @morficflux.
