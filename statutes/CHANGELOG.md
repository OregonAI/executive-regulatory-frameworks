# Changelog — Statutes (ORS)

All notable changes to the curated copies in this directory. Format based on
[Keep a Changelog](https://keepachangelog.com/); change types: Added, Source-Updated,
Superseded, Repealed, Removed, Verified, Fixed, Security. This repo is non-authoritative;
dates below are repo-curation dates, not official effective dates (those live in each
file's frontmatter).

## [Unreleased]

### Fixed

- `repo_lib.snapshot_slice` no longer anchors an ORS section on a later citation of it: a number
  right after "ORS", "and", "to", "or", "section(s)" or a comma is skipped as a heading
  candidate (74A.1030, 74A.1040, 31.262 and 105.462 were anchored on a citation and refused or
  mis-sliced). Measured against all 39,224 catalog rows: the slice of no already-ingested
  section changes. 105.462 is ingested. 74A.1030, 74A.1040 and 31.262 stay not ingested on
  purpose, for a different reason now recorded in their `note`: `snapshot_slice` does not end
  a section at the next one in a chapter numbered below 100 (and, in the UCC chapters, for
  four-digit section numbers), so their slices carry 8, 5 and 4 later sections' text. The
  same defect is already in the committed text of other documents in those chapters.
- `src/catalog_ors.py`: a section-group heading printed with a colon ("PERFORMANCE OF LEASE
  CONTRACT: REPUDIATED, SUBSTITUTED AND EXCUSED") was not recognized as a heading and was glued
  onto the preceding title. 72A.3100 and five chapter 77 titles are corrected in the catalog and
  in their documents (`src/backfill_ors_titles.py`). Admitting ":" changes exactly those six
  titles across all committed chapter snapshots; chapters 74A and 131A carry no such text.

- `src/ingest_ors.py` no longer refuses a short, complete section as "no section body found":
  24.335 (111 characters) and 587.010 (102) were withheld by a flat 120-character floor and
  are now ingested. A short slice is accepted only when ORS's catchline terminator and text
  after it are present; a TOC row stays refused. Refusals by the anchor check now quote the
  catalog title and the catchline words the anchor found (31.262, 67.042 and 67.600 stay
  refused; see their `note` in `_meta/catalog/ors.yml`).

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
