# Changelog — Oregon Executive Regulatory Frameworks

Keep a Changelog format; ISO dates. Change types: Added, Source-Updated,
Superseded, Repealed, Removed, Verified, Fixed, Security.
Repo-curation dates only — official effective dates live in frontmatter.

Per-body change history predates this file and lives in each content root's own
`CHANGELOG.md` (e.g. `executive-orders/CHANGELOG.md`); this root file tracks
corpus-wide changes from 2026-08-02 forward.

## [Unreleased]

### Added
- 2026-08-21 — the in-repo consumers of the agency registry moved onto `oar_name`, and
  every remaining reader of `name` is classified where it sits (#187). ADR 0003 makes
  `name` the statutory name and leaves the rules index's title in `oar_name`; because the
  two hold identical bytes on all 189 rows today, a consumer that should have moved and did
  not is invisible in the data, so every measurement below was ALSO run against a
  fault-injected registry — `name` replaced with a synthetic statutory name, `oar_name`
  untouched. The two OAR-derived joins now match `oar_name`: `src/enrich_oar.py`, which
  stamps `issuing_body` into rule frontmatter, and `src/catalog_oar.py`, which discovers
  chapters. NO DOCUMENT CHANGED and the corpus was not re-enriched — measured across all
  36,953 already-enriched rule documents, 0 carry an `issuing_body` that differs from their
  body's `oar_name` — and `enrich_oar.py --check` now COMPARES that field, which was
  written by the enricher and checked by nothing, so a future split is reported rather than
  assumed to be nil. Agency search spans every name a body is known by (statutory name, OAR
  name, curated aliases) in both places it is served, `catalog_agencies.find()` and the MCP
  `agency_profile` tool, and `resolve()` matches both names in every tier: against the
  committed registry the 76 recorded retention-schedule resolutions are unchanged, and
  against the fault-injected one matching `name` alone loses 32 of 72 while matching both
  loses none. New gate `python3 src/name_readers.py --check` (CI, every PR) refuses a
  registry-`name` read carrying no JOIN / DISPLAY / MACHINERY classification beside it; its
  `--selftest` demonstrates all five of its rules failing. The audit found 38 sites across
  17 modules — six more modules than the issue's own census named.
- 2026-08-21 — `enabling_authority` on the agency registry (#170): the field that
  records what created a body — an ORS citation, a constitutional article, or an
  executive order, because ADR 0003 records an AUTHORITY rather than a statute so
  that constitutional offices have somewhere true to sit. It is CURATED and
  survives `--refresh`, and its single writer is
  `python3 src/link_enabling_authority.py --apply`, driven by the hand-reviewed
  `MAPPED` / `UNMAPPED` tables in that file. THE TABLES ARE STILL EMPTY and no
  registry row changed: this lands the field and its gate, not the data — the 126
  proposed candidates in `_meta/catalog/enabling-authority-review.yml` are
  proposals, and each becomes a row only after a human reads the section. Three
  states stay distinguishable: an authority recorded, `none: ` and a reason when
  someone looked and there is none, and an absent key — all 189 rows today —
  meaning nobody has looked yet. A blank value is a contract violation, because it
  asserts absence with nobody behind it. `link_enabling_authority.py --check` now
  runs in the `generated-views` CI job and can fail while the tables are empty (a
  row carrying an authority no table accounts for), alongside a new `--selftest`:
  ten cases covering all seven of its rules, plus a proof that `--apply` writes
  the same bytes on a second run.
- 2026-08-21 — `das_agency_number` on all 80 agency-registry rows that carry a
  DAS agency number (#175): ADR 0003 renames `budget_agency_code`, because the
  number identifies a body in the state's financial administration and says
  nothing about whether it spends money — thirteen semi-independent bodies carry
  one and are outside the state's accounting system entirely. This is the EXPAND
  half: both keys hold the same value, no consumer breaks mid-flight, and #177
  removes the old one once the 474 published documents keyed on it are
  regenerated (#163). Both keys are curated and survive `--refresh`; both are
  written together by `python3 src/link_budget_codes.py`, whose `--check` now
  verifies the registry against `das_agency_number`; and
  `catalog_agencies.py --check` fails any row carrying one key without the other
  or the two holding different numbers, proved by three `--selftest` cases.
- 2026-08-20 — `oar_name` on all 189 agency-registry rows (#166): the OAR name
  (CONTEXT.md) — the chapter page's own title — now has its own field instead of
  sharing `name`, which ADR 0003 turns into the statutory name. It is SCRAPED, so
  an upstream chapter retitle moves it. `name` is byte-identical on every row and
  nothing resolving against it moves, which is the point — sibling crosswalks
  move onto `oar_name` and are verified there BEFORE `name` changes meaning.
  Landed by
  `src/expand_oar_name.py` (re-runnable, idempotent), written from now on by
  `catalog_agencies.py --refresh`, and required on every row by
  `catalog_agencies.py --check`.
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
