# Changelog — Executive Orders

All notable changes to the curated copies in this directory. Format based on
[Keep a Changelog](https://keepachangelog.com/); change types: Added, Source-Updated,
Superseded, Repealed, Removed, Verified, Fixed, Security. This repo is non-authoritative;
dates below are repo-curation dates, not official effective dates (those live in each
file's frontmatter).

## [Unreleased]

### Added
- 2026-07-18 — Ingested all 526 executive orders (2003–present) from the listing of
  record (SharePoint list `/gov/eo` behind gov/pages/executive-orders.aspx, Public view,
  527 rows; one byte-identical-id collapse). 19 orders with clean PDF text layers carry
  verbatim `## Full text` (quality gate: ≥100 words, ≥80% dictionary); 507 are image-only
  scans ingested as metadata stubs with `content_exception`. Snapshot policy is
  **hash-only** (PDFs ~700 MB of scans, not committed; `snapshot_policy: hash-only`).
  Catalog: `_meta/catalog/eo.yml`; new-order detection via the `executive-orders` update
  group (listing ADDED rows only — orders are immutable). 7 listing anomalies recorded
  for human review (6 wrong Year/Number metadata rows, 1 duplicate-row byte mismatch).
