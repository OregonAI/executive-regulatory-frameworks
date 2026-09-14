# Changelog — DAS Statewide Procedures

All notable changes to the curated copies in this directory. Format based on
[Keep a Changelog](https://keepachangelog.com/); change types: Added, Source-Updated,
Superseded, Repealed, Removed, Verified, Fixed, Security. This repo is non-authoritative;
dates below are repo-curation dates, not official effective dates (those live in each
file's frontmatter).

## [Unreleased]

### Superseded

- `das-107-009-0030_pr` (Business Equity, Inclusion and Engagement in Public Procurement
  Procedure): dropped from every live DAS policies view in the August 2026 re-issue.
  Marked `status: superseded` on the evidence of the replacing policy
  `das-107-009-0030`'s own masthead (`SUPERSEDES: Policy 107-009-0030 and Procedure
  107-009-0030_PR`) — not on its absence from the listing alone. Kept, not deleted; see
  `../policies/CHANGELOG.md` and #387 for the full account.

## [2026-07-18]

### Added

- New directory. Split out of `agencies/das/policies/` because procedures
  (`doc_type: procedure`, filenames ending `_pr.md`) are not policies. 14 documents
  moved with full history preserved via `git mv` (no content, hash, or provenance
  changes — only file location and cross-reference paths):
  das-107-001-002_pr, das-107-004-015_pr, das-107-004-030_pr, das-107-004-052_pr,
  das-107-004-130_pr, das-107-004-150_pr, das-107-004-155_pr, das-107-004-180_pr,
  das-107-004-190_pr, das-107-004-200_pr, das-107-009-0030_pr, das-107-009-0060_pr,
  das-107-011-050_pr, das-107-011-115_pr.

### Fixed

- das-107-009-0030_pr: `doc_type` corrected from `policy` to `procedure` (mislabeled at
  ingestion despite its `_pr` filename and procedure content).
