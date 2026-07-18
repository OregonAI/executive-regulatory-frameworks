# Changelog — Oregon Accounting Manual (OAM)

All notable changes to the curated copies in this directory. Format based on
[Keep a Changelog](https://keepachangelog.com/); change types: Added, Source-Updated,
Superseded, Repealed, Removed, Verified, Fixed, Security. This repo is non-authoritative;
dates below are repo-curation dates, not official effective dates (those live in each
file's frontmatter).

## [Unreleased]

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
