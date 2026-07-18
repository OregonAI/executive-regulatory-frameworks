# Changelog — Administrative Rules (OAR)

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

- oar-128-030-0005, oar-128-030-0010, oar-128-030-0020: initial ingest from OARD.
  Discovery: these rules were renumbered from OAR 125-800-xxxx effective 05/01/2026
  (AON "DAS 2-2026") — chapter 128 is the Office of the State Chief Information Officer.
  DAS policies citing "OAR 125-800" now resolve here. Verified-by @morficflux.
