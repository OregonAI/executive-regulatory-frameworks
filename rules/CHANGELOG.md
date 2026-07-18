# Changelog — Administrative Rules (OAR)

All notable changes to the curated copies in this directory. Format based on
[Keep a Changelog](https://keepachangelog.com/); change types: Added, Source-Updated,
Superseded, Repealed, Removed, Verified, Fixed, Security. This repo is non-authoritative;
dates below are repo-curation dates, not official effective dates (those live in each
file's frontmatter).

## [Unreleased]

## [2026-07-18] (3)

### Added

- OAR chapter 128 division 20 (State IT Asset Protection — Covered Vendors), 7 rules
  (128-020-0005 through -0035): enumerated by direct OARD probing (the division is not
  mirrored on oregon.public.law), full text each. Closes the last known OAR enumeration
  gap.

### Fixed

- Removed a garbage document (rules/999/999/) created by an earlier catalog placeholder
  row hitting OARD's not-found page, which echoes the requested rule number and
  masqueraded as a served rule. ingest_oar.py now detects the not-found shell and marks
  such rows not_served instead of ingesting them.

## [2026-07-18] (2)

### Added

- Chapter-wide ingestion via the new `src/ingest_oar.py` pipeline: 433 rules across all
  35 divisions of chapter 125 (DAS) and chapter 128 divisions 10/40/50 — enumerated from
  oregon.public.law's server-rendered listings, every rule fetched from the
  authoritative OARD page, full text per rule. The renumbering guard filed 13 rows under
  the numbers OARD actually serves, discovering that old 125-600 (Identity
  Authentication/E-Signatures) now serves as 128-050 and 128-040 (Geographic
  Information), and that 7 parking rules (125-090) were internally renumbered — all
  mappings recorded in `_meta/catalog/oar.yml`. Chapter 128 division 20 (Covered
  Vendors) remains an enumeration gap (not mirrored on public.law).
  Verified-by @morficflux (machine verification; human review pending).

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

- oar-128-030-0005, oar-128-030-0010, oar-128-030-0020: initial ingest from OARD.
  Discovery: these rules were renumbered from OAR 125-800-xxxx effective 05/01/2026
  (AON "DAS 2-2026") — chapter 128 is the Office of the State Chief Information Officer.
  DAS policies citing "OAR 125-800" now resolve here. Verified-by @morficflux.
