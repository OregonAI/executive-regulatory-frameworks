# Changelog — DAS Statewide Policies

All notable changes to the curated copies in this directory. Format based on
[Keep a Changelog](https://keepachangelog.com/); change types: Added, Source-Updated,
Superseded, Repealed, Removed, Verified, Fixed, Security. This repo is non-authoritative;
dates below are repo-curation dates, not official effective dates (those live in each
file's frontmatter).

## [Unreleased]

## [2026-07-17]

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
