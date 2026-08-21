# Changelog — Oregon Executive Regulatory Frameworks

Keep a Changelog format; ISO dates. Change types: Added, Source-Updated,
Superseded, Repealed, Removed, Verified, Fixed, Security.
Repo-curation dates only — official effective dates live in frontmatter.

Per-body change history predates this file and lives in each content root's own
`CHANGELOG.md` (e.g. `executive-orders/CHANGELOG.md`); this root file tracks
corpus-wide changes from 2026-08-02 forward.

## [Unreleased]

### Removed
- 2026-08-21 — `parent_slug` is retired from the agency registry (#174). Hierarchy lives in
  `relations` and nowhere else: the pointer is off all 189 rows, `FIELDS` no longer declares
  it, and because rows are checked against an ALLOWLIST, `catalog_agencies.py --check`
  refuses it under `declared-field` if it ever comes back — a permanent proof of that is in
  `--selftest` (`the-retired-pointer-comes-back`). Every in-repo consumer moved first.
  `build_policy_gap.py` rolls sub-divisions up to their root agency and
  `build_agency_graph.py` groups a sub-unit with its department, both now through
  `catalog_agencies.root_body()` / `parent_targets()` — the one place hierarchy is walked, so
  a rollup carrying rule counts and a rollup carrying a node colour cannot place one body two
  ways. THE ROLLED-UP TOTALS AND THE GRAPH ARE UNCHANGED: 93 agencies, 36,953 OAR rules and
  690 policy documents before and after, and 166 nodes / 8,088 edges / 15 coloured groups
  before and after. A BODY ITS SOURCES DISAGREE ABOUT IS NOT ROLLED UP — a body may hold more
  than one relation and ADR 0003 keeps that disagreement, so neither rollup picks one
  reading; the body stands as its own root and the count is published beside the totals (zero
  today). `agency_profile.py` no longer reads the pointer, which is an OUTPUT SCHEMA CHANGE:
  its `registry` block no longer carries `parent_slug`, and carries `relations` in its place.
  `src/expand_relations.py` is DELETED — its only input was `parent_slug`, so it cannot run
  once the field is gone, and ADR 0004's new amendment is where the record of what it
  derived, and how, now lives. `parent_chapter` stays, as the different fact it is (the
  parent's OAR chapter, scraped from the same tree), and `parent-agrees` now states it
  against the body the relations name — including the case one chapter cannot express, where
  two sources name two parents. `name_readers.py --check` gained a second gate: nothing may
  derive hierarchy by splitting the compound `Parent, Child` name, and a site that takes a
  registry name apart on a comma fails unless it is classified as deriving a NAME.
  A body the walk CANNOT roll up says so on its own record — `not_a_root` on the policy-gap
  row, `parents_disagree` on the graph node — because a total of zero is exactly what would
  hide the first one, and a row that looked like a top-level agency would be a wrong number.
  What the pointer used to witness is now COUNTED on every `--check` run: 65 of the 81
  placements are still stated twice (`parent_chapter` names the parent's OAR chapter), and
  16 rest on the relation alone because their parent holds no chapter — a deleted entry
  there is rebuilt by the next `--refresh` and reported by nothing in the file, which is
  said out loud rather than left to be discovered.

### Added
- 2026-08-21 — A constitutional enabling authority is RESOLVED against the mirror, not merely
  read for shape (#196, ADR 0005's amendment). `link_enabling_authority.py --check` resolves
  all three of ADR 0003's forms against a mirrored document now: an ORS citation against the
  mirrored statutes, an executive order against the mirrored orders, and a constitutional
  article against the **339 mirrored sections** of the Oregon Constitution. The
  `form checked, not resolved` line is GONE from the report and the constitutional count moved
  onto `resolved against the mirror` — the class that line counted is empty rather than small.
  `Or. Const. Art. XVII, sec. 99`, ADR 0005's own example of a citation that was well-formed
  and unverifiable, no longer passes: under ADR 0003 an enabling authority is ADMITTING
  evidence, so a class of it nothing could check was a hole in the rule rather than a
  formatting inconvenience. WHAT TOOK THE WORK IS NOT "DOES IT RESOLVE" — it is that an
  authority resolving to nothing says WHICH nothing, because a row citing a section Oregon
  repealed and a row citing a section that never existed are different errors and send a
  reviewer to re-read different documents. Five answers, none of them worded like another and
  none inferred from a missing file (`_meta/catalog/constitution.yml` records a status and a
  reason per article and per section): the page prints no such article; the article is printed
  and carries no sections (XI-A, XI-B, XI-C); the page prints no such section in it; the page
  prints the section and this corpus published no text for it (the 32 `history-only` sections);
  and the numeral names TWO operative articles, where resolving to nothing is a REFUSAL TO
  GUESS rather than a failure — a bare `Or. Const. Art. VII, sec. 1` is answered with the two
  citations to choose between, because the page prints that numeral only as (Amended) and
  (Original). A sixth answer is a statement about this corpus rather than about the
  Constitution — the catalog recording a section as published while `constitution/` does not
  carry it — and it points at `ingest_constitution.py --check`, whose gate that is. Resolution
  runs through the `or-const` citation scheme, the same code path `resolve_citation` serves to
  an agent, so the gate and the answer an agent gets cannot disagree; an empty `constitution/`
  makes the gate REFUSE TO ANSWER rather than report every constitutional authority as citing
  nothing (CONTEXT.md), and that refusal is proved failing rather than asserted. `--selftest`
  holds 19 demonstrated-failing proofs, five of them constitutional citations that must fire
  `authority-resolves` and one that no two of the five answers are the same string.
  **NO AUTHORITY IS RECORDED**: `MAPPED` and `UNMAPPED` are untouched, all 189 rows still read
  "nobody has looked yet", and the ~9 bodies whose authority is a constitutional article stay
  in #169's review population.
- 2026-08-21 — A recheck cadence for the BALLOT-MEASURE cycle, and one place a cadence is
  declared (#193). ADR 0005 reads **ACCEPTED**: the decision to mirror the Oregon
  Constitution is taken, nothing is ingested yet (#194), and the cadence that ADR argues
  about is now expressible. `even_year_general_election` = **765 days**, and it is NOT a
  second spelling of `biennial`: the two are the same length and two years apart in phase —
  `ors.yml`'s `biennial` means the edition published after the ODD-year legislative session,
  while constitutional amendments are decided at the general election in November of
  EVEN-numbered years. Measured over every anchor in the month after an election and every
  consecutive pair of general elections to 2100, a group comes due 30–67 days after the next
  election on the new cadence and between 5 days BEFORE it and 32 days after on `biennial` —
  so from the natural anchor, a check made promptly after an election, `biennial` lands on
  the wrong side of the event it exists to catch. 765 = 735 (the longest span between
  consecutive general elections, since the first-Tuesday-after-the-first-Monday rule slides
  election day between November 2 and 8) + 30 (the vote is canvassed and an approved
  amendment takes effect). The window is a ONE-HOP property: each check re-anchors
  `last_checked` on the day it ran, so the due date walks 30–37 days later per cycle —
  FORWARD by choice, since a shorter interval walks backward into a state it cannot leave
  (due before the election, finds nothing, re-anchors earlier, reports `ok` forever).
  THE CADENCE WAS DECLARED TWICE — `CADENCE_DAYS` in `src/check_updates.py` and the `recheck`
  enum in `_meta/schema/source-group.schema.json` — with nothing gating their agreement, the
  same shape as `CURATED_KEYS` in #165. The schema's `recheck` node is now DERIVED from the
  `CADENCES` table (`python3 src/check_updates.py --sync-schema` writes it; `--check` fails
  when the committed one has drifted), so a cadence cannot exist on one side only, and the
  schema now PRINTS each value's interval where a curator reads it. A group declaring a
  cadence nobody declared is REPORTED against that group — by `--check`, and by `--due` as a
  third state, `UNKNOWN CADENCE`, which is neither DUE nor ok (CONTEXT.md: "could not check"
  is never "is not there") — where it used to be a bare `KeyError` from a dict lookup inside
  `report_due()` that named the dict instead of the file and took every other group's
  due-state down with it; a `last_checked` nothing can date — the unquoted YAML `2026-08-01`
  parses to a date object, not a string — is the same third state rather than a ValueError.
  `--selftest` holds five demonstrated-failing rules and four measured behaviours; both
  gates run in CI. What the interval CANNOT do is hold its phase (#198), and nothing
  validates a group against the REST of that schema (#199). Every existing group's `--due`
  reading is byte-for-byte unchanged.
- 2026-08-21 — Relation KINDS on the agency registry, each recording what it was derived
  from (#173): 44 of the 81 children now record `administered_by` and 37 record
  `undetermined`. Every derived kind carries a new `basis` key, which is NOT the same fact as
  `source` — the source says who places the body under that parent, the basis says what
  settled which of ADR 0004's two kinds it is, and a relation the OAR index discovered can
  have its kind decided by a statute. THE TWO BASES ARE DIFFERENT STRENGTHS AND ALL 44 REST
  ON THE WEAKER ONE: `proposed-enabling-authority` means the kind was derived from a
  candidate in `_meta/catalog/enabling-authority-review.yml` that NOBODY HAS READ, where
  `reviewed-enabling-authority` means it was derived from the authority the row itself
  carries. ADR 0004 derives the kind from ADMITTING evidence and an unreviewed candidate is a
  proposal rather than evidence, so this deviates from that ADR as written and the ADR now
  records the deviation and its reasoning: the split was worth shipping before the review of
  126 candidates, and it is only defensible because the file says which strength each kind
  rests on and upgrades visibly when the review lands. NO KIND IS DERIVED FROM THE ABSENCE OF
  A CANDIDATE — the 37 stay `undetermined` because a matcher finding nothing is a statement
  about the matcher, and that list has already been wrong for 55 bodies in one session
  (118 → 95 → 82 → 63 as matcher gaps were closed), so 37 undetermined relations are the
  answer rather than a gap. `part_of` is derived by nothing at all, and a reviewed
  `none: <reason>` retires its row's proposal rather than becoming one. Written by ONE thing,
  `python3 src/derive_relation_kinds.py --apply` — re-runnable and byte-identical on a second
  run — whose `--check` compares the registry with the derivation in BOTH directions, so a
  kind that arrived any other way, or a row whose candidate has been reviewed since the last
  apply, is a red build. A derived kind lives on the relation whose kind it decides,
  INCLUDING the `oar-index` entry `--refresh` regenerates: `relations` now merges per KEY as
  well as per entry (`DECISION_KEYS`), so the scrape owns the placement and the derivation
  owns the decision, and the decision is carried only onto a rebuilt entry naming the same
  parent. Putting the kind on a second relation entry was rejected — a second entry is a
  second PLACEMENT, and no statute, DAS register or hand-written note places these bodies
  where the rules index does. Six new rules of the registry's contract, each demonstrated
  failing in `--selftest`: a kind with no basis; a basis this registry has no meaning for; a
  basis on a relation that decided nothing; an `administered_by` citing no authority; a
  *part of* relation that cites one; and `part-of-has-nothing-to-enable`, for a row asserting
  both a *part of* relation and an enabling authority of its own. THE CITATION A DERIVED
  RELATION CARRIES IS THE CONSTITUTING SECTION — ORS 576.062, the evidence its kind rests on
  — and never the section the department's administration runs on (ORS 576.066), which
  nobody in this repository has read; both bases are named for an *enabling authority* for
  exactly that reason, and recording the administering section stays a curated decision on a
  basis nothing derives, which `decision-not-ours` refuses to overwrite with a proposal.
  `AUTHORITY_FORMS` was NOT widened: every one of the 44 candidates is a single ORS section,
  so the range form ADR 0004's eight semi-independent boards are declared under
  (`ORS 182.456 to 182.472`) is still refused, and a candidate the registry cannot record is
  REPORTED under `candidate-form` rather than left quietly undetermined.
  `catalog_agencies.py --selftest` grew from 48 demonstrated failures to 55, and the new
  module's own proves six rules failing beside four derivation proofs.

- 2026-08-21 — `relations` on all 189 agency-registry rows (#171): every one of the 81
  children now carries a relation naming its parent, beside the `parent_slug` that still
  says the same thing (#174 retires the pointer). A relation records a `target` slug, the
  `source` whose evidence places the body there, a `kind`, and — where one has been
  established — the `authority` that makes it true (ADR 0004). THE KIND IS `undetermined`
  on every one of the 81 and is never guessed: choosing between *part of* and *administered
  by* turns on evidence the registry does not carry yet (#173), 25 of the 81 children have
  their own statutory authority and 56 do not, and writing either kind today would be
  dozens of false statements about Oregon law. `catalog_agencies.py --check` REPORTS the
  census — kinds and sources, zeroes included — on every run rather than letting the state
  go quiet. A body may hold several relations, because the OAR index, DAS and statute may
  place it under different parents and ADR 0003 keeps that disagreement rather than
  reconciling it; three-level nesting (`Health Licensing Office → Board of Cosmetology`)
  needs no special case, being two ordinary relations between three bodies. `relations` is
  the first field with a MIXED ORIGIN and is declared `MERGED`: `--refresh` regenerates the
  `oar-index` entries from the index tree, so an upstream re-filing still reaches the
  registry, while `preserve_relations()` carries every other entry across ENTRY BY ENTRY —
  the per-field origins could only be wrong about half of what the field holds, and
  declaring it SCRAPED would drop curated entries behind a rule that passed, which is #178
  (`note`, two origins, no way to tell them apart, a hand-written note destroyed by a
  refresh with nothing to report it). The source is never claimed falsely: the registry's
  one manual child — `oregon-health-authority-equity-and-inclusion-division`, a body the
  rules index does not carry — records `source: registry`, because the index placed it
  nowhere and no refresh can rebuild the entry. Six new rules of the registry's contract —
  `relation-shape`, `relation-unique`, `relation-resolves`, `relation-names-the-parent`,
  `index-relation-is-regenerated`, `relation-origin`, and the survival comparison now run
  per ENTRY for a merged field — each demonstrated failing in `--selftest`, which grew from
  28 demonstrations to 48.
  Landed by `src/expand_relations.py` (re-runnable, idempotent: a second run writes
  byte-identical output and never re-derives a list that may hold curation). `parent_slug`
  is unchanged on every row and no consumer changes.
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
  loses none, and every one of the 189 rows is reachable by both of its names under a
  registry with `name` already promoted — a new `findable-by-both-names` rule of
  `catalog_agencies.py --check`, which runs that promotion in memory on every PR so the
  measurement is repeated rather than remembered. New gate
  `python3 src/name_readers.py --check` (CI, every PR) refuses a registry-`name` read
  carrying no JOIN / DISPLAY / MACHINERY classification beside it; its `--selftest`
  demonstrates all three of its rules failing, over six cases. The audit read 38 sites
  across 17 modules on `main` — six more modules than the issue's own census named — and
  classified the 33 that still read `name` once the two joins had moved. Three decisions
  beyond the letter of the issue, each recorded where the code is: aliases are spanned by
  search (the issue asked for the judgement), `resolve()` matches both names because the
  fault-injected measurement showed it losing 32 of 72 resolutions otherwise, and an empty
  query now matches NOTHING rather than every row — the missing-argument-as-wildcard hole
  the platform closed on its own MCP surface in corpus-toolkit#122.
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
