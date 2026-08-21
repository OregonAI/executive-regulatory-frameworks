# Changelog — Oregon Constitution

All notable changes to the curated copies in this directory. Format based on
[Keep a Changelog](https://keepachangelog.com/); change types: Added, Source-Updated,
Superseded, Repealed, Removed, Verified, Fixed, Security. This repo is non-authoritative;
dates below are repo-curation dates, not official effective dates (those live in each
file's frontmatter).

## [Unreleased]

## [2026-08-21]

### Added

- **Article VI (Administrative Department), 10 of the 11 sections the source page prints**,
  full text per section, via the new `src/ingest_constitution.py` — the first article
  mirrored under ADR 0005 (#194). Section 9a is cataloged and NOT published: the page
  prints its leadline and its legislative-history bracket and no text between them (it was
  repealed in 1958), so there is no text to mirror. The reason is recorded beside it in
  [`_meta/catalog/constitution.yml`](../_meta/catalog/constitution.yml).
  Verified-by @morficflux (machine verification; human review pending).
- The other 17 articles are **not** mirrored (#195). A citation into one of them resolves
  to nothing and says it is not mirrored — which is not a statement that the section does
  not exist.
