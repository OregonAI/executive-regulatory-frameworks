# Changelog — Statutes (ORS)

All notable changes to the curated copies in this directory. Format based on
[Keep a Changelog](https://keepachangelog.com/); change types: Added, Source-Updated,
Superseded, Repealed, Removed, Verified, Fixed, Security. This repo is non-authoritative;
dates below are repo-curation dates, not official effective dates (those live in each
file's frontmatter).

## [Unreleased]

### Fixed

- Catalog `title` divergences from their own printed catchline (#286): the TOC parser's
  `XREF_RE` widened to also mask "to"-joined section ranges, not just "and"-joined lists,
  fixing the truncation/heading-theft bug at its cause (`src/catalog_ors.py`). Of the 27
  already-ingested sections whose catalog title diverged from `anchor_ok`'s word-for-word
  check, 6 resolved by widening that check's own inflection tolerance and 18 more are
  hand-corrected here against each section's own body catchline
  (`src/backfill_ors_286_titles.py`), updating `title`, the `# {title}` heading, and the
  "At a glance" line in each affected `statutes/ors-*.md`. Three rows (341.305, 315.123,
  470.540) are deliberately left diverging: the printed source itself carries the defect
  (a typo; a line-wrap hyphenation artifact) and the catalog title was already correct —
  writing the source's own artifact into a curated field to make a mechanical check pass
  would be the fabrication this corpus's Access-failure/Upstream-drift split exists to
  prevent.

## [2026-07-18] (3)

### Added

- 9 more DAS-associated ORS chapters, full text per section, via the new
  `src/catalog_ors.py` (TOC discovery) + existing `src/ingest_ors.py` pipeline: 240
  (State Personnel Relations, 64), 276 (Public Facilities, 99), 278 (Insurance for
  Public Bodies, 22), 279A (Public Contracting — General Provisions, 51), 279B (Public
  Procurements, 46), 279C (Public Improvements, 104), 282 (Public Printing, 16), 283
  (Interagency Services, 45), 292 (Salaries and Expenses of State Officers and
  Employees, 54) — 501 sections. 10 further catalog entries marked `not_sliceable`
  (no section body in the chapter text). Corpus now spans every ORS chapter the
  Department of Administrative Services derives authority from or administers policy
  under. Verified-by @morficflux (machine verification; human review pending).

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
