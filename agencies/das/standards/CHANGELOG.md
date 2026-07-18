# Changelog — EIS/CSS Statewide Standards

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

## [2026-07-17]

### Added

- eis-css-itcs (Statewide IT Control Standards, January 2024): parent document plus 18
  per-control-family inventory files under eis-css-it-control-standards/ (321 control
  entries, generated from the source text; summary-mode). sha256 a4b76d6a….
- eis-css-secplan (Statewide Information Security Plan, 8/1/2018). sha256 58075cec….
- eis-css-program-plan-2023 (2023 Statewide Information Security Program Plan, July 2023
  v1.2). sha256 b5645776….
- All fetched and hashed 2026-07-17. Verified-by @morficflux.
