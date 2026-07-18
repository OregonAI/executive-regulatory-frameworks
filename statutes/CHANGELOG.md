# Changelog — Statutes (ORS)

All notable changes to the curated copies in this directory. Format based on
[Keep a Changelog](https://keepachangelog.com/); change types: Added, Source-Updated,
Superseded, Repealed, Removed, Verified, Fixed, Security. This repo is non-authoritative;
dates below are repo-curation dates, not official effective dates (those live in each
file's frontmatter).

## [Unreleased]

## [2026-07-18] (2)

### Added

- Whole-chapter ingestion via the new `src/ingest_ors.py` pipeline: 567 section
  documents across chapters 183 (48), 184 (114), 192 (126), 291 (86), 293 (157), and
  the remainder of 276A (36) — full text per section, sliced from the Legislature's
  chapter HTML (2025 Edition) with the same shared slicing the verifier uses. 5 catalog
  entries marked `not_sliceable` (no section body in the chapter text — renumbered/
  repealed or TOC-noise entries) and intentionally not ingested. Verified-by
  @morficflux (machine verification; human review pending).

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

- ors-276a.300, ors-276a.303, ors-276a.306 (2025 Edition): initial ingest from the
  chapter 276A HTML (shared snapshot ors-chapter-276a.html, sha256 b4adecc9…).
  Verified-by @morficflux.
