# Changelog — DAS Statewide Policies

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
- Exceptions (content_exception, still summary): das-107-004-051 and das-107-004-100 (image-only scans; full text requires OCR + human verification).


## [2026-07-18] (2)

### Added

- 50-xxx HR batch (from `_meta/catalog/das-policies.yml`): das-50-000-01 (Drug Free
  Workplace), das-50-010-01 (Discrimination and Harassment Free Workplace), das-50-010-02
  (Violence-Free Workplace), das-50-010-03 (Maintaining a Professional Workplace),
  das-50-010-05 (Weapons in the Workplace), das-50-010-06 (Employee Health and Wellness),
  das-50-020-10 (ADA and Reasonable Accommodation in Employment), das-50-035-01
  (Performance Management Process), das-50-050-01 (Working Remotely), das-50-090-01
  (Managing Improper Governmental Conduct). All 10 catalog candidates confirmed to exist
  and ingested; titles corrected from "(title TBD)" to verified headers. Wired
  cross-references: 107-011-100 <-> 50-050-01 (space/remote work); 107-011-150 <->
  50-020-10 (service animals/ADA accommodation). Verified-by @morficflux.

## [2026-07-18]

### Added

- 107-011 batch (Facilities/Fleet/Asset Management/Surplus, from `_meta/catalog/das-policies.yml`):
  das-107-011-010 (Energy and Resource Conservation), das-107-011-050_pr (Sustainable
  Acquisition and Disposal of Electronic Equipment — completes the two-way edge with
  das-107-004-051), das-107-011-100 (Space Design and Utilization), das-107-011-115
  (Siting State-owned and Leased Office Space), das-107-011-150 (Service Animals),
  das-107-011-310 (Capitol Mall Area Parks and Grounds), das-107-011-330 (Vending
  Services). All fetched, hashed, and quote-verified 2026-07-18. Verified-by @morficflux.

### Fixed

- das-107-004-051: relationship edge to the e-waste procedure resolved from a bare
  citation (old number 107-009-0050) to the ingested slug das-107-011-050_pr.

### Removed

- Catalog candidate 107-011-111 dropped: the URL 404s, confirmed at verification. Never
  existed in the ingested corpus.

### Added

- Stage 2 batch (10 policies + 1 procedure): das-107-001-020 (Public Records Management),
  das-107-004-010 (IT Asset Inventory), das-107-004-050 (Asset Classification),
  das-107-004-051 (Removable Storage — image-only source, summary-only),
  das-107-004-052_pr (procedure), das-107-004-100 (Transporting Assets — image-only
  source, summary-only), das-107-004-110 (Acceptable Use), das-107-004-120 (Incident
  Response), das-107-004-140 (Privileged Access), das-107-004-150 (Cloud and Hosted),
  das-107-004-160 (Data Governance). All fetched, hashed, and quote-verified 2026-07-17.
  Verified-by @morficflux.

### Fixed

- das-107-004-052: relationship edges upgraded from citation strings to resolved slugs
  (ors-276a.300, oar-128-030-0020, das-107-004-052_pr, eis-css-itcs, eis-css-secplan).

### Changed

- Repo-wide: `source_sha256` migrated from raw-byte hashes to **content hashes**
  (sha256 of normalized extracted text; see `content_hash()` in `src/repo_lib.py`),
  because oregon.gov, OARD, and csrc.nist.gov all serve byte-different responses per
  download (PDF stamping, session ids, Cloudflare tokens). Hash prefixes in older
  changelog entries reflect the raw-byte scheme in force at the time.

- das-107-004-052 (Cyber and Information Security): initial ingest from
  https://www.oregon.gov/das/Policies/107-004-052.pdf (Effective 2/17/2026,
  Reviewed 12/2/2025; sha256 ff23504f…). Verified-by @morficflux.
