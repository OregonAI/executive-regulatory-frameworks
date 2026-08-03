# Changelog — Oregon Executive Regulatory Frameworks

Keep a Changelog format; ISO dates. Change types: Added, Source-Updated,
Superseded, Repealed, Removed, Verified, Fixed, Security.
Repo-curation dates only — official effective dates live in frontmatter.

Per-body change history predates this file and lives in each content root's own
`CHANGELOG.md` (e.g. `executive-orders/CHANGELOG.md`); this root file tracks
corpus-wide changes from 2026-08-02 forward.

## [Unreleased]

### Added
- 2026-08-02 — Scheduled upstream drift detection reinstated (M4 stage 3;
  cron retired 2026-07-18 had left the platform's largest corpus with no
  automatic freshness checking at all). `.github/workflows/scheduled.yml`:
  monthly check of the 13 bulletin/monthly-cadence source groups (5th of each
  month, via `corpus-detect-changes --group`, tolerant of isolated fetch
  failures) plus a quarterly full sweep of all 18 groups through the reusable
  workflow. Requires corpus-toolkit >= v1.22.0.
- 2026-08-02 — `upstream_tracking` honesty field on all 36,953 OAR rule
  documents (#78): `manifest` (484 rules with per-source entries in
  `_meta/sources/oar.yml`, re-hashed by the scheduled drift jobs) vs `none`
  (36,469 mass-imported rules that nothing re-checks against upstream).
  Maintained by `src/mark_upstream_tracking.py`, CI-gated with `--check`,
  served on MCP `get_document` via `mcp.extra_document_fields`.
- 2026-08-02 — `STATUS.md` bootstrapped (`corpus-generate-status`) and gated
  per-PR in the `generated-views` job; this root `CHANGELOG.md` created.
- 2026-08-02 — Oregon Bulletin pilot (#78): `src/check_bulletin.py` fetches the
  current monthly Bulletin from the OARD index and extracts the amended /
  adopted / repealed / renumbered / suspended OAR rule numbers into
  `_meta/bulletin-worklist.yml`, marking which are held in this corpus — the
  O(1-document-a-month) alternative to hashing 36k rules.
- 2026-08-02 — `_meta/eo-review-queue.md`: operator queue for the 25
  fallback-OCR executive orders that have never been human-verified (#77),
  ordered by cross-engine agreement (weakest first), signature blocks / names /
  dates called out as the priority fields.

### Fixed
- 2026-08-02 — `src/ocr_promote.py` and `src/ocr_fallback_eo.py` no longer
  stamp `last_verified` with the run date: machine promotion is not
  verification (AGENTS.md rule 6). The field now stays `""` until a human
  review is recorded via corpus-verify (corpus-toolkit >= v1.22.0) — the same
  fabrication class PR #109 removed corpus-wide, which these two writers would
  have silently reintroduced on their next run.
- 2026-08-02 — `REVIEW.md` regenerated: the executive-orders no-machine-
  verification row said 12 documents; ground truth after PR #105's ten OCR
  recoveries is 2 (`eo-12-09`, `eo-16-15`).
