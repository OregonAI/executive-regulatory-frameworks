# Changelog — Oregon Executive Regulatory Frameworks

Keep a Changelog format; ISO dates. Change types: Added, Source-Updated,
Superseded, Repealed, Removed, Verified, Fixed, Security.
Repo-curation dates only — official effective dates live in frontmatter.

Per-body change history predates this file and lives in each content root's own
`CHANGELOG.md` (e.g. `executive-orders/CHANGELOG.md`); this root file tracks
corpus-wide changes from 2026-08-02 forward.

## [Unreleased]

### Removed
- 2026-08-31 — **`budget_agency_code` retired from the agency registry** (#177, the
  contract half of the two-step rename #175 began; parent #164 / ADR 0003). Deleted from
  all 80 rows that carried it, along with the sentence in the registry's own top-level
  `note` describing the pair. `das_agency_number` is now the only key the number is
  written under: `write_das_agency_number()` (`src/catalog_agencies.py`) writes one key,
  not two, and `link_budget_codes.py` writes and checks only that field. The equality
  assertion the deprecation cycle depended on (`deprecated-key-agrees`) is gone with the
  second key it compared; in its place, `catalog_agencies.py --check` gained
  `budget-agency-code-retired`, which fails any row where the old key reappears — proved
  by `--selftest`'s `budget-agency-code-reappears` case, which writes the key back onto a
  fixture row and asserts the rule fires.

  Confirmed safe before deleting: every one of the 80 rows carried both keys with equal
  values on the committed registry (verified directly against `_meta/catalog/agencies.yml`
  before this change), so no data was lost and no side was silently chosen. Re-verified the
  fleet against each sibling repo's `origin/main` immediately before this change
  (`git grep -l budget_agency_code origin/main`, run from a fresh clone of each repo):
  `oregon-budget` carries it only in its #37 dual-key detection guard
  (`build_joins.py:112,116`, which reads either key on purpose and needs no change), a code
  comment explaining the absence of a fallback (`link_agency_registry.py:375`), its own
  CHANGELOG, and tests asserting the deprecated key resolves to nothing
  (`test_agency_crosswalk.py`, `test_registry_join.py`); `oregon-kpm` carries it only in a
  comment pointing readers at `das_agency_number`; `oregon-stories` carries it only in
  comments and `test_the_deprecated_budget_agency_code_joins_nothing`, which asserts the
  deprecated key joins nothing. `oregon-counties`, `oregon-audits`, `federal-reference`,
  `oregon-legislature`, `oregon-collective-bargaining`, `corpus-gateway` and `corpus-chat`
  carry no occurrence at all. No repo reads the key for a live join.

### Fixed
- 2026-09-02 — **#338: a renumbered OAR row whose served target's file already existed on
  disk never got its `path` recorded.** `ingest_oar.py`'s `out.exists()` branch gated the
  `r["path"]` write on `served == num`, so a row like 125-800-0005 (served as
  128-030-0005, whose file another row already wrote) recorded `served_as` but not where
  the document lives. `path` is now stamped from `out` in that branch regardless of the
  `served == num` status gate. Fixture in `--selftest` (`_renumbered_out_exists_stamps_path`)
  runs `cmd_ingest` itself against a temporary catalog/group/rules tree rather than
  re-deriving the expected path by hand, and delegates to the real `repo_lib.oar_rule_path`
  via its documented `root=` parameter (#334) instead of a hand-rolled copy.

  In wiring the fixture through the real `cmd_ingest`, found it calling
  `repo_lib.division_status` without that name ever being imported into `ingest_oar.py` —
  a pre-existing `NameError` on any live nonempty-chapter `--ingest` run, invisible until
  now because nothing had exercised that path through the real function. Added the
  missing import as part of this fix. The 3 catalog rows this bug had already left with a
  stale or missing `path` (`_meta/catalog/oar.yml`) were hand-corrected to match what the
  fixed code writes.
- 2026-08-30 — **#341: `stated_census.py --check` had no floor, so a document's tagged-figure
  coverage could drop to zero and the run stayed green.** A stated figure, or a whole
  glossary entry, deleted outright removes it from `glossary_blocks()`'s scan — not an
  untagged-figure failure, since there is no longer a figure there to call untagged. Per
  AGENTS.md's "before gating a figure, ask whether it should exist," the floor is not a
  hand-maintained expected-count in prose; it is derived: the new `coverage-has-not-regressed`
  rule compares each PATH's accounted-for figure count (tagged or marked, matching or not)
  against that same path's text as of `repo_lib.resolve_base_ref()` (merge-base with
  origin/main, else HEAD~1 — now shared with `changed_content_files`'s own resolution rather
  than a second copy) and refuses a run whose coverage dropped. A path new since that ref, or
  a ref git cannot read, has nothing to compare against and is reported as such rather than
  left indistinguishable from a floor that held. `--selftest` proves it against the exact
  mutation #341's own repro used (a `**Term**:` header reworded to plain prose) and against a
  grown-coverage case that must NOT fail.

  Two gaps closed by code review before this landed further. (1) `repo_lib.committed_text()`
  used to report "nothing to compare against" for a path RENAMED in the same commit range —
  measured: copying `CONTEXT.md` to a new name and deleting a whole glossary entry from the
  copy, then `--check`ing the new name, exited 0 with "no comparison available," the exact
  silence this rule exists to close; the same edit in place correctly failed. Fixed: it now
  asks `git diff -M` for a committed rename pairing the miss, and reads the OLD name's text
  at the base ref instead of giving up (`--selftest` proves it against a disposable git repo,
  never the real corpus). (2) the failure message named a specific cause — a reworded or
  deleted `**Term**:` header — that is USUALLY not what actually happened: measured over
  every one of CONTEXT.md's 47 `**Term**:` headers and all 5 `##` section breaks, rewording or
  deleting one leaves the accounted count unchanged in every case tried, because
  `glossary_blocks()` merges that content into the PRECEDING entry rather than dropping it
  (real exception, not exercised by today's content: a term that is the FIRST one after a
  `##` break, with no earlier sibling to absorb the overflow). The message and both
  docstrings now say what is actually likely (a figure or an entry's whole body deleted) and
  name the header case as the narrower exception it is.
- 2026-08-30 — **#346: `catalog_ors.py`'s `parse_toc` could drop a chapter's own last TOC
  entry.** The TOC/body boundary is found by density — the first >600-char gap between
  section-number matches — and the match at that boundary was always excluded as though it
  were a body reoccurrence of an earlier entry. When a chapter's genuinely last TOC entry is
  itself followed by a large gap (no nearby cross-reference to its own number keeps density
  high past it), that exclusion silently dropped the entry instead. Measured against all 569
  committed `_meta/snapshots/ors-chapter-*.txt`: 4 chapters affected — 171 (`171.992`), 186
  (`186.520`), 221 (`221.928`), 306 (`306.815`) — with 565 chapters producing byte-identical
  catalogs before and after. Fixed by only excluding the boundary match when its own section
  number is already claimed by an earlier bound; when it is not, it becomes one more entry,
  bounded by its own catchline's end (`_catchline_end`) — the first of an ALL-CAPS
  part/subpart heading or a standalone "Note" marking editorial marginalia — rather than
  running on into chapter furniture the way an earlier, rejected version of this fix did
  (documented in #346's own thread). `_meta/catalog/ors.yml` gains the two entries this
  latent bug had kept out of a fresh catalog run entirely (`186.520`, `306.815`).
  `171.992` and `221.928` were ALREADY in the catalog (`catalog_ors.py` only ever adds a
  section not already known to a chapter, so this fix's own diff to `ors.yml` never touched
  either row) — code review measured that claiming they were "hand-verified" was false: both
  carried the exact garbage-suffixed title (heading and/or "Note" marginalia glued onto the
  real catchline) this fix's own `--selftest` now asserts must not exist, and neither is in
  `backfill_ors_286_titles.FIXES`, the repo's actual record of a hand-verified row. Backfilled
  those two titles alongside this fix, from the same corrected `parse_toc`, the same way
  `backfill_ors_titles.py` (unrelated, pre-existing, and untouched by this fix) would for any
  other stale catalog title — `_meta/catalog/ors.yml`, and `statutes/ors-171.992.md` /
  `statutes/ors-221.928.md`'s `title:` frontmatter, `#` heading, and "At a glance" line, are
  all now the clean, `anchor_ok`-agreeing title. `backfill_ors_titles.py --check` still fails
  on 1443 unrelated stale catalog titles (unchanged by this fix, present before it too) — a
  pre-existing backlog outside this issue's scope, tracked separately (#348).
- 2026-08-30 — **#288: `generated-views-nightly`'s six gates no longer rolled up into any
  aggregate check.** After #268's shard split, the nightly-only job ran under its own name
  with nothing depending on it, so a nightly gate failure was visible only to whoever opened
  the Actions run. `generated-views` now depends on `generated-views-nightly` too, with its
  schedule-vs-PR skip handled deliberately in the fan-in step (a `skipped` result is accepted
  ONLY for that one job, and ONLY on a non-schedule/workflow_dispatch event — every other
  result, and every other dependency, keeps the original uniform rule) rather than folded into
  the per-shard loop. `shard_generated_views.py`'s stale-`needs:` check used to compare
  against shard jobs only, which would have flagged this exact, legitimate dependency as
  nonexistent; a new rule requires the fan-in to depend on `generated-views-nightly`
  whenever that job exists. `check_all.py` already covered the nightly job's six gates
  locally (#329, confirmed here); this closes the CI-side gap.

  Code review measured what the stale-`needs:` check's first fix admitted: comparing
  `needs:` against every real job the workflow defines (not just shard jobs) accepted the
  ONE dependency #288 actually needed, but also silently accepted a `needs:` entry naming
  any other real job — including the fan-in depending on ITSELF (a cycle GitHub would
  refuse to even run) or on `frontmatter` (real, but completely unrelated) — three of the
  four shapes the original rule caught, gone. Narrowed to the actual allowed set: a shard
  job, or `generated-views-nightly` while it exists, nothing else. Also fixed: the fan-in's
  own green-summary line counted a correctly-skipped `generated-views-nightly` among the
  jobs that "succeeded" ("all 2 dependency job(s) succeeded" when only 1 ran), and its
  qualifying clause was split across two `echo` statements, printing as a truncated
  sentence — now one accurate line either way. Also recorded: the job-level
  `timeout-minutes: 80` cap had no
  measured basis — `gh run list`/`gh run view` against the only real history the job has (it
  did not exist as a separate job before #268's split) finds 3 scheduled runs since then, two
  completing all six steps in 13.2 and 19.5 minutes and one failing partway at 19.7 minutes;
  the cap comfortably covers that with the generous, rarely-firing margin #268 asks for, so it
  is left unchanged with the measurement now recorded in its comment.

- 2026-08-30 — **#295 found `ingest_ors.py`, `ingest_eo.py`, `ingest_policies.py` and
  `ingest_constitution.py` writing a fabricated `last_verified`/`verified_by` value at
  ingestion time (AGENTS.md rule 6: those fields are the human reviewer's alone to set, at
  approval); this closes it with a fix AND a gate, not just the fix.** All four generators
  now write both fields empty, matching the two OCR scripts (`ocr_fallback_eo.py`,
  `ocr_promote.py`) that already did it correctly. Every document across the affected
  content roots carrying the fabricated value from those four generators is un-stamped back
  to empty — a verification claim nobody made is worse than an honestly empty one, whatever
  the count.

  The gate is `src/verification_stamp.py` (`--check`/`--selftest`, wired into CI): an AST
  scan of every `src/*.py` except itself for a write to either field that is not the
  literal empty string. A review of this fix found and closed three gaps in the gate before
  it landed: (1) its field-value regex matched only `"..."`, missing the single-quoted
  spelling this corpus's own retention-schedule generator (780b192a53) already writes and a
  bare-unquoted spelling nothing stops a future generator from using — proved live with two
  synthetic evasion scripts that passed `--check` clean before the fix; (2) its population
  was `SRC.glob("ingest_*.py")`, a name-prefix filter that excluded `ocr_promote.py` and
  `ocr_fallback_eo.py` — the gate's own docstring names them as the correct exemplars — and
  a live mutation of `ocr_promote.py` to write a fabricated stamp passed `--check` clean
  under that population; the population is now every `src/*.py`, with the gate excluding
  only itself (the one file whose job is to talk ABOUT this shape); (3) widening the AST
  walk to a bare-value match introduced a false-positive path of its own (an f-string's
  interpolation boundary visited twice by `ast.walk()`, `_joinedstr_child_ids()`), caught
  by this fix's own adversarial testing and closed before landing, not left for a later
  review. `--selftest` now proves all of the above, including that a module explaining this
  rule in its own docstring cannot fail it by quoting the forbidden shape in prose.

- 2026-08-28 — **Code review of #281 found five fabricated or inverted figures in the
  commit that added the Oregon Hemp Commission's registry row, two of them load-bearing
  evidence quoted in the commit's own message and therefore uncorrectable there** (this
  repo's convention, established by prior commits in this cluster, is a new commit, never
  an amend). The row itself and its `enabling_authority: ORS 571.406` were sound and are
  unchanged; every correction below is to PROSE that mis-stated a re-measurement, not to
  the registry's own data.

  **Restated, because it cannot be corrected in place.** `180bb020b9`'s message states its
  evidence that the Hemp Commission has no OAR chapter as "`grep -in hemp
  _meta/catalog/oar.yml` returns nothing." Run against the mirrored catalog, that command
  returns THREE hits — `MARIJUANA AND HEMP TESTING`, `INDUSTRIAL HEMP`, and `CANNABIS
  CONCENTRATION LIMITS & HEMP PRODUCT REGISTRY` — none of them a `chapter:` title, and no
  chapter numbered 609 exists in `oar.yml` at all. The conclusion (`oar_chapter: null`) is
  correct; the quoted command is not the one that supports it. The evidence that does: no
  `chapter:` entry in `_meta/catalog/oar.yml` is titled for the Oregon Hemp Commission. The
  same message's opening paragraph also inverts the OAM 70.10.00 join it answers — it says
  21 of 22 OAM-named commissions have a registry row "(the 22nd, Alfalfa Seed, also carries
  one)". OAM 70.10.00's `60310` heading names exactly 22 commissions and Hemp (609) is one
  of them; `grep -i alfalfa` over the mirrored OAM returns nothing, so Alfalfa Seed is not
  in OAM's list at all and cannot be its 22nd name. Issue #281 and ADR 0003's amendment
  both state the join correctly ("21 that match OAM's list plus the Invasive Species
  Council"); the commit is the one place it reads backwards. A third commit-message claim
  does not survive re-measurement either: the message calls the `--propose` regeneration of
  `_meta/catalog/enabling-authority-review.yml` "required to confirm the matcher's own read
  of the new row" — `propose()` skips every slug already in `MAPPED` (`src/
  link_enabling_authority.py:522`), and the same commit put `oregon-hemp-commission` into
  `MAPPED` first, so the regenerated sheet carries no Hemp entry in either `candidates` or
  `no_candidate` and never produced an independent read. The tier-3 determination rests
  entirely on the implementer's manual reading, which is permitted for a `MAPPED` entry —
  the corroboration claim just did not happen. And the same message undercounts what
  `--propose` dropped: it says "5 already-decided entries," a direct diff of the sheet
  before and after shows 6 (`secretary-of-state` out of `candidates`, plus
  `legislative-assembly`, `office-of-public-defense-services`, `office-of-the-governor`,
  `oregon-military-department` and `saif-corporation` out of `no_candidate`) — legitimate
  drops, every one already carrying a reviewed `enabling_authority` on the base branch, so
  this is a miscount and not a lost review item, but worth naming because `secretary-of-
  state` is the one that left `candidates` on a `verdict: ''` row, which reads at a glance
  like an undecided item being discarded.

  **Fixed in place**, because these live in files rather than in commit-message prose:
  `_meta/catalog/agencies.yml`'s top-level note stated "null on 14 of the 19 chapterless
  rows" through a whitespace-only re-wrap of that exact sentence in the same commit that
  made the true count 15 of 20 — measured directly (20 rows carry `oar_chapter: null`, 15
  of those carry no `source_url`) and confirmed against `--check`'s own live "(20
  chapterless)" report, which the note contradicted in the same run that printed it. Fixed
  at the source of truth, `REGISTRY_NOTE` in `src/catalog_agencies.py`, and carried into the
  committed YAML by re-serializing the same `cat` dict through the same `yaml.safe_dump`
  call `cmd_refresh()` uses (diff against the previous commit: one line). The `FIELDS`
  doc-comment on `oar_chapter` carried the identical stale "19" one screen up in the same
  module, fixed alongside it. `src/link_enabling_authority.py`'s new `#281` comment claimed
  "none of its 34 catchlines" for ORS 571.400 to 571.501; the mirror holds 37 sections in
  that range (`ors-571.400.md` … `ors-571.501.md`), every one bracketed to the same 2021
  session law, so all 37 belong to the act — fixed to 37.

  **The wider sweep AGENTS.md already applied.** The commit correctly moved AGENTS.md's two
  inline counts from 189/4 to 190/5, which is the discipline this cluster of tickets keeps
  asking for — it just did not reach the other places carrying the same live counts.
  Re-measured and corrected in the same modules `#279` already fixed once for the shape of
  this exact drift: `src/expand_oar_name.py` ("189 is `len(organizations)`" → 190, "19 of
  those rows" → 20; its gated "170 chapter pages" sentence is untouched, since the chaptered
  count did not move), `src/catalog_oar.py` (two sites: "186 of the 189" → "187 of the 190",
  and the `--selftest` fixture docstring's "19 rows hold none" → 20), `src/agency_profile.py`
  and `src/name_readers.py` ("186 of the 189" → "187 of the 190" in both), `src/
  enrich_oar.py` ("all 189 rows today" → "187 of the 190" — this one was already inaccurate
  before #281, predating the three rows #168 gave an established name that differs from the
  OAR title; corrected to the true figure rather than just bumped), `src/
  record_name_basis.py` (two sites: "189 rows are carrying..." → 190, and its own "189 total
  rows" cross-reference to the gated sentence → 190), `src/build_policy_gap.py` ("returned
  for all 189" → 190), and `src/link_enabling_authority.py` (three further sites: "107 rows
  carry a reviewed enabling authority... four have been" → 114 and five, matching the live
  `MAPPED`/`STATUTORY_NAMES` table sizes; "189 OAR titles... 189 false statements... the 107
  by pattern-matching" → 190/190/114; "81 of 189 bodies" → "81 of 190" — the compound-name
  count itself did not move, since the new row's name carries no comma). Left alone as dated
  narrative, per this repo's own convention for text that records what was true at a
  specific past point rather than a live claim (`docs/adr/0004`'s two Amendment sections,
  and this file's own older entries): `link_enabling_authority.py:16`'s "matched 78 of 189
  bodies" describing the module's very first matcher attempt, and `:100`'s "63 of 189
  bodies have no candidate" describing the review sheet's state before three later tickets
  each closed part of that gap — both are history, not a claim about today's registry.

  **`note-numbers-current`, a new `check_registry()` rule**, closes the gap that let the
  "14 of the 19" sentence pass: `note-covers-fields` (#185) only proves every `FIELDS` name
  is mentioned somewhere in the registry's own top-level `note`, and `note-agrees-with-
  refresh` only proves the committed note matches the `REGISTRY_NOTE` literal — neither
  reads a number, so `REGISTRY_NOTE` going stale on its own, as it did here, passed both.
  The new rule extracts the note's "null on N of the M chapterless" claim
  (`NOTE_CHAPTERLESS_RE`) and checks it against `chapterless_source_url_census()`, computed
  from the committed rows the same run — the same shape as `#279`'s
  `chapter-page-count-current`, one field over. OPTIONAL, not required: the phrase is
  checked only when present, so the synthetic `--selftest` fixture (built to name every
  `FIELDS` key, never to be the real prose) does not need to carry it. Watched failing
  first: temporarily disabled the new check, re-ran `--selftest`, and got `FAIL
  note-chapterless-count-stale: expected a [note-numbers-current] failure, got
  [Failure(rule='note-agrees-with-refresh', ...)]` — confirming the new `_case_` actually
  exercises the new rule rather than piggybacking on an existing one — then restored it.

  **Two decisions recorded on the new row itself, in `curator_note`, rather than left
  silent.** First: the row's slug carries no `department-of-agriculture-` prefix (ADR 0003:
  no compound `Parent, Child` OAR name to split), so after this row the registry has 23
  rows matching that slug prefix and 24 rows whose `relations` target
  `department-of-agriculture` — measured, and no longer the same number; ADR 0003's
  amendment reasons in terms of "the registry's 23 Department-of-Agriculture rows" and a
  future reader re-deriving that sentence needs to know which join it meant. Second: OAM
  70.10.00 numbers this body 609 — stated in the same commit's own first paragraph — but
  `das_agency_number` stays unset, because `link_budget_codes.py` (the field's single
  writer) has not reviewed it and #281 closes only the OAR-index name gap, deliberately
  leaving the `das_agency_number` join at ADR 0003's standing "23 numbers matching no body"
  report (confirmed unchanged: `link_budget_codes.py --check` still reports 80 codes
  mapped; mapping 609 would drop that to 22, contradicting the ADR's own "still 23" claim
  from earlier the same day).

  **One pointer added to `docs/adr/0003`**, as a new dated `## Amendment` section rather
  than an edit to existing text, per that file's own append-beside convention: its
  2026-08-28 amendment says, in the present tense, that nothing has admitted the Oregon
  Hemp Commission "because the registry carries no row for it to admit" — true when
  written, false a few hours later the same day once `180bb020b9` landed. The new section
  says so and points at the citation that actually applies (ORS 571.406, not 576.062); the
  original sentence is left exactly as drafted.

  Gates, all re-run on this change:

      python3 src/catalog_agencies.py --check          -> 190 rows against 16 declared
                                                            fields; 287 curated value(s) and
                                                            18 manual row(s) survive a
                                                            simulated --refresh; chapter
                                                            pages: 170 of 190 (20
                                                            chapterless); enabling authority:
                                                            114 recorded, 76 not looked at
                                                            yet; name: 5 enabling-authority,
                                                            185 unverified-oar-title
      python3 src/catalog_agencies.py --selftest        -> 77 violation(s) demonstrated
                                                            failing, 18 name resolution(s)
                                                            proven (was 76; +1 is
                                                            `note-numbers-current`'s new
                                                            case, not a second copy of an
                                                            existing one)
      python3 src/link_enabling_authority.py --check    -> 114 recorded, 0 reviewed with
                                                            none to record, 76 of 190 not
                                                            looked at yet; 5 of 114 reviewed
                                                            authorities carry a read
                                                            statutory name
      python3 src/link_enabling_authority.py --selftest -> 29 violation(s) demonstrated
                                                            failing (unchanged)
      python3 src/derive_relation_kinds.py --check      -> 45 of 82 bodies have a kind
                                                            derived, 37 undetermined; 3
                                                            proposed / 42 reviewed
                                                            (unchanged)
      python3 src/derive_relation_kinds.py --selftest   -> 6 violation(s) demonstrated
                                                            failing, 4 derivation proof(s)
                                                            held (unchanged)
      python3 src/link_budget_codes.py --check          -> 80 codes mapped, 2 deliberately
                                                            unmapped, 14 manual entries, 17
                                                            aliases (unchanged)
      python3 src/catalog_oar.py --selftest             -> selftest OK
      python3 src/name_readers.py --check / --selftest  -> both OK (unchanged census)
      python3 src/enrich_oar.py --selftest              -> selftest OK
      python3 src/agency_profile.py --selftest          -> selftest OK
      python3 src/build_policy_gap.py --check           -> policy-documentation-gap.html is
                                                            current
      python3 src/shard_generated_views.py --check      -> manifest and workflow agree: 68
                                                            gate(s) across 5 shard(s) (no
                                                            gate added or renamed — the new
                                                            rule lives inside an existing
                                                            gated step)

  Refs #281


- 2026-08-28 — **`AGENTS.md` and `CONTEXT.md` said all 44 decided relation kinds rest on
  `proposed-enabling-authority`, the CANDIDATE basis "nobody has read"; `--check` measures
  the opposite majority** (#277). Re-measured rather than trusted the ticket's own figures,
  per this cluster of tickets' standing rule that a number in a filing is a lead and not a
  fact: `python3 src/catalog_agencies.py --check` on this branch reports "the 44 decided
  kind(s) rest on: 3 proposed-enabling-authority, 41 reviewed-enabling-authority" — the
  ticket's own re-measurement confirmed, not superseded. 44 is the correct count of DECIDED
  kinds (`kinds: 37 undetermined, 0 part_of, 44 administered_by`, also unchanged), but both
  documents attached it to the wrong half of the proposed/reviewed split: `AGENTS.md:482`
  said "All 44 rest on `proposed-enabling-authority`"; `CONTEXT.md`'s **Relation basis**
  entry said "44 of the 81 kinds rest on the second today" (the second = `proposed-
  enabling-authority`, the weaker, unread basis). Both understated the registry's own
  quality: a reader trusting either sentence would conclude 44 of 44 decided kinds are
  still waiting on review, when 41 have already cleared it — the third time this cluster of
  tickets has found a hand-typed count going stale in prose (#219, #279, now this).

  Followed #219's own precedent exactly rather than re-deriving it: reworded both sites to
  drop the number rather than update it to today's, pointing at `relation_census()` — already
  live, already printed by `catalog_agencies.py --check` on every run — as the one place the
  split is counted, instead of adding a third hand-maintained copy for a future review to
  leave behind. Swept the same shape into `src/derive_relation_kinds.py`'s module docstring
  in the same pass (found while reading it, not part of the ticket's own two named sites):
  its "so 44 of the 81 children become `administered_by`. The other 37 stay `undetermined`"
  (line 32) and "37 undetermined rows are the correct answer" (line 39, seven lines later —
  measured with `git show dc59fec:src/derive_relation_kinds.py | grep -n`, not estimated)
  carried the same present-tense count-in-prose risk one level down, in the module CONTEXT.md
  itself names as the field's only writer; both are now number-free, pointing at the same
  `relation_census()`. Code review of #277 found the sweep still incomplete — a single grep
  for the ticket's own sentence would have surfaced it — and this commit closes the rest:
  `.github/workflows/validate-frontmatter.yml:563`, a hand-editable CI comment carrying the
  ticket's exact sentence ("44 of the 81 are derived from candidates NOBODY HAS READ") in a
  third live site — `shard_generated_views.py --check` gates the shard job NAMES there, not
  the comment's wording, so nothing blocked the edit; two more pins in
  `src/derive_relation_kinds.py` itself (the `_registry()` selftest fixture's "This is the
  37."/"The 44." row labels, and an illustrative "44 bodies administered by their parent" in
  `--check`'s own docstring, both pinning the exact counts the module docstring just stopped
  naming); and one in an inline comment inside `src/catalog_agencies.py`'s
  `relation_census()` ('A census reporting only "44 administered_by"'), inside the function
  the other three sites now point readers at. Each is reworded to describe the shape without
  pinning today's count, the same fix already applied to `AGENTS.md`/`CONTEXT.md` above.
  Left alone: `docs/adr/0004`'s own "so 44 of the 81 children become `administered_by`" (its
  Amendment section, 2026-08-21) and `CHANGELOG.md`'s existing 2026-08-21 entry for #173 —
  both read as dated decision/history narrative describing the state that motivated a
  decision already made, the same register as this file's own dated entries, which this
  repo does not rewrite for later data drift (#219's own stated distinction, applied here
  rather than re-litigated).

  **No new `check_registry()` or `derive_relation_kinds.py --check` rule.** Nothing in this
  tree parses `AGENTS.md`, `CONTEXT.md`, or a Python module docstring the way
  `note-covers-fields` (#185) parses the registry's own committed YAML — there is no seam a
  gate could attach to without building a markdown/docstring scanner from nothing to watch
  three sentences, and the split isn't a bounded invariant to assert (a review landing can
  move it in either direction on the census, not toward a fixed target `--check` could
  compare against). Removing the hand-typed number is the durable fix available today: with
  no digit left in the prose, there is no fact left to drift, and the next reader is pointed
  at the one live count rather than asked to trust a pinned one.

  Gates, all re-run on this change:

      python3 src/catalog_agencies.py --check         -> unchanged census, including
                                                           "the 44 decided kind(s) rest on:
                                                           3 proposed-enabling-authority,
                                                           41 reviewed-enabling-authority"
      python3 src/catalog_agencies.py --selftest       -> 76 violation(s) demonstrated
                                                           failing, 18 name resolution(s)
                                                           proven (unchanged — no rule added)
      python3 src/derive_relation_kinds.py --check     -> unchanged: 44 of 81 derived, 37
                                                           undetermined, 3 proposed / 41
                                                           reviewed
      python3 src/derive_relation_kinds.py --selftest  -> 6 violation(s) demonstrated
                                                           failing, 4 derivation proof(s)
                                                           held (unchanged)
      python3 src/shard_generated_views.py --check     -> manifest and workflow agree: 68
                                                           gate(s) across 5 shard(s) (no gate
                                                           added or renamed)

- 2026-08-28 — **AC4 of #185 ("the note is not regenerated wholesale on every write")
  closed as out of scope, not implemented** (#278). #278 was filed on the theory that the
  registry's own top-level `note` (`agencies.yml`, the prose above `organizations`) might
  carry hand-appended curator prose that `cmd_refresh()`'s wholesale rewrite would silently
  destroy, by analogy to `catalog_oar.py`'s genuinely different case (`INITIAL_NOTE`, #241:
  4,425 committed characters today against a 1,875-character floor, from real appended
  paragraphs). A first pass at the fix froze the whole note once any content existed and
  retired the regression guard `note-agrees-with-refresh` — reviewed and found to reproduce
  #185's own root cause one level up: **measured, not assumed, by walking every one of the 23
  commits that have ever touched `_meta/catalog/agencies.yml` and comparing each commit's
  committed `note` against that same revision's module literal, the committed field has
  NEVER once exceeded its era's literal** — byte-identical at HEAD and at the commit
  immediately before #185's own fix (5,260 == 5,260). No curator prose has ever lived in this
  field; the two rows people point to when describing "curator prose on the note" are
  `curator_note` entries (#178, chapters 419/950), a different, already-protected field.
  AC4 is closed by #278's own second named option instead: `cmd_refresh()` keeps writing
  `REGISTRY_NOTE` wholesale, `note-agrees-with-refresh` is restored exactly as #185 left it,
  and the decision — the top-level `note` is scrape-only and never a place for curator
  prose — is now explicit in `AGENTS.md` and `CONTEXT.md` (a new **Registry note** glossary
  entry), not merely implied by an equality check nobody explained.

  Gates, all re-run on this change:

      python3 src/catalog_agencies.py --check     -> 189 rows against 16 declared fields;
                                                       285 curated value(s) and 17 manual
                                                       row(s) survive a simulated --refresh
      python3 src/catalog_agencies.py --selftest  -> 76 violation(s) demonstrated failing,
                                                       18 name resolution(s) proven

- 2026-08-28 — **`assert_scrape_declared()` excluded `SCRAPED_KEYS` and `MERGED_KEYS` but
  not `PER_ROW_KEYS`, so a real `--refresh` `sys.exit`'d before writing anything, every
  invocation, on unmodified main** (#275). `scraped_entry()` writes `name`/`name_basis` on
  every row it builds — the PER_ROW pair that lets an established statutory name survive
  `preserve_name()` untouched while an unverified OAR title gets rebuilt — but the exclusion
  guard only knew about SCRAPED and MERGED, so `{'name', 'name_basis'}` came back
  "undeclared" every time, before any row could be written. Fixed by deriving the exclusion
  from `FIELDS` (`admitted = set(FIELDS) - CURATED_KEYS - MANUAL_FLAG_KEYS`) rather than
  naming SCRAPED_KEYS/MERGED_KEYS/PER_ROW_KEYS by hand at the one call site that needed
  their union — the same shape #182 fixed for `preserve_curated()`'s key order, and the
  shape this function itself had already gone stale under once, the day PER_ROW joined the
  other two origins and this list did not. Verified live, not only against the fixture:
  `--refresh` against oregon.public.law completed end to end, 189 rows in `organizations`,
  106.48s wall-clock (2026-08-28, this branch); the committed registry was restored
  unchanged afterward, since a network-dependent refresh's output is not this ticket's data
  to commit. A follow-up code review of this fix found a fabricated timing figure and two
  falsified claims elsewhere in the same commit and corrected them in place (no separate
  CHANGELOG entry — folded into this one, since nothing it changed is user-visible beyond
  what this entry already describes).

  Gates, both re-run on this change (before the #278 entry above, which changed the
  `--selftest` figure further):

      python3 src/catalog_agencies.py --check     -> chapter pages: 170 of 189 row(s)
                                                       carry oar_chapter (19 chapterless)
      python3 src/catalog_agencies.py --selftest  -> 75 violation(s) demonstrated failing,
                                                       18 name resolution(s) proven

- 2026-08-28 — **170 vs 189: `expand_oar_name.py` and `record_name_basis.py` still said a
  full `--refresh` re-fetches 189 chapter pages** (#279). `CHANGELOG.md` and
  `catalog_agreement.py` already said 170 — measured, not copied forward: **170 is
  `sum(1 for o in orgs if o.get("oar_chapter"))` over the committed `agencies.yml`, and
  the OAR catalog's own 170 `chapters` (`_meta/catalog/oar.yml`) is the SAME 170 chapter
  numbers, set-equal, measured directly rather than assumed**. 189 is `len(organizations)`,
  this registry's total row count; 19 of those rows carry no `oar_chapter` (a body sits in
  the registry because it EXISTS, not because it issues rules — CONTEXT.md) and are never
  fetched by a refresh. Re-derived from first principles rather than trusting either
  figure, because the ticket's own premise needed correcting too: OARD's `ruleSearch.action`
  dropdown lists 181 chapters — not the 362 #270 quoted for that same dropdown, which
  counted raw `<option>` tags rather than chapters; OARD prints two identical `<select>`
  elements (`catalog_oar.py`'s own `chapter_id_map()` fixture, measured 2026-08-27), so 362
  raw options over 181 chapters is 2 per chapter, and `chapter_id_map()`'s dict
  comprehension dedupes them to one entry per chapter — reconciled here (code review of
  #279), not merely noted as a coincidence: `CHAPTER_OPTION_RE.findall()` returns 2 matches
  per chapter over that exact fixture, collapsing to 1 in the resulting map, so 181 is
  `len(id_map)` (`catalog_oar.py:616`'s `ChapterNotListed(ch, len(id_map))`) and is the
  correct chapter count either way. 181 sounded like a candidate for "the real number"
  — but that dropdown is a fact about a THIRD thing (`catalog_oar.py`'s discovery source,
  OARD itself, since #283) and has no bearing on what `catalog_agencies.py --refresh`
  fetches, which still scrapes `oregon.public.law` (a 2026-07-19 decision, unchanged by
  #283 — the two catalogs serve different jobs and #283 only moved rule-content discovery).
  **The harder question — should a count like this live in prose at all (#219's shape,
  four files over)** — answered *no* for these two files: `check_registry()` gains
  `chapter-page-count-current`, reading the real text of both scripts (injected as a
  parameter, defaulting to the real files, the same shape `refresh_note` already uses) and
  refusing either a stale count or a rewording that drops the checked phrase entirely; the
  live figure is now also `chapter_census()`, printed by `--check` on every run beside the
  other censuses (`authority_census`, `name_census`) rather than pinned into two scripts'
  docstrings to go stale independently again. `CHANGELOG.md`'s own 170 (a dated historical
  entry, like the rest of this file) and `catalog_agreement.py`'s printed count (already
  computed live, `len(cat.get('chapters', []))`, never hardcoded) needed no change.
  `--selftest` grew from 74 to 75 demonstrations (three assertions under one:
  `chapter-page-count-current` stays quiet on a true count, fires on a stale one, and fires
  when the checked phrase is dropped entirely). Found and NOT fixed here, opened as
  #299: the same docstring in `record_name_basis.py` carries two more stale counts (189
  vs. the measured 185 `unverified-oar-title` rows; 107 vs. the measured 113 rows carrying
  a reviewed enabling authority) — a different pair of fields, outside this ticket's own
  acceptance criteria.

  Gates, all re-run on this change:

      python3 src/catalog_agencies.py --check     -> chapter pages: 170 of 189 row(s)
                                                       carry oar_chapter (19 chapterless)
      python3 src/catalog_agencies.py --selftest  -> 75 violation(s) demonstrated failing,
                                                       18 name resolution(s) proven
      python3 src/catalog_oar.py --selftest        -> selftest OK (unchanged)
      python3 src/catalog_agreement.py --selftest  -> 3 rule(s) declared, every one watched
                                                       firing; 2 guard(s) held (unchanged)
      python3 src/catalog_agreement.py --check     -> 170 chapter(s), 42,615 rule row(s)
                                                       (unchanged)
      python3 src/shard_generated_views.py --check -> manifest and workflow agree: 68
                                                       gate(s) across 5 shard(s) (no gate
                                                       added or renamed)
- 2026-08-28 — **A two-axis review of #268's own split found the fix strands every PR on a
  check that cannot report — the exact failure #268 exists to end.** Shards 1-4 lost the
  `corpus-toolkit` checkout and install that the pre-split job ran before every gate (only
  shard-5 kept it), so `citation_schemes.py`, `snapshot_identity.py` (x2), and
  `bulletin_report.py` (x2) die on `ModuleNotFoundError` / import-time failures across all
  four of those shards on every PR — reproduced by running the exact CI commands with
  `corpus_toolkit` import-blocked. Root cause was six jobs hand-repeating the same
  toolchain preamble, so a re-shard could (and did) leave one shard subtly less capable
  than its siblings; fixed by hoisting the preamble into one composite action
  (`.github/actions/generated-views-setup`) every shard and the nightly job now call, and
  by teaching `shard_generated_views.py --check` to assert every shard's non-gate setup
  steps are identical (`setup_steps_by_shard()`) and that the fan-in job carries
  `if: always()` — the two drifts that were invisible to the gate/manifest-parity checks
  #268 shipped. Also fixed: every shard's job-level `timeout-minutes` was smaller than the
  sum of its own step-level `timeout-minutes` (shard-5 by 1 minute on day one; shards 1-4
  by 16–39 minutes once the toolkit-install fix restored their real running time), so a
  broad slowdown — the "wall-clock grows with the gate count" scenario #268 is about —
  would trip the job cap before any single step could and report `cancelled` with no gate
  named, exactly the outcome #268's last acceptance criterion forbids; job caps are now
  comfortably above their step sums (shard-1/2: 45m, shard-3: 35m, shard-4: 55m, shard-5:
  20m) and nightly's own cap (30m → 80m) got the same treatment plus per-step timeouts on
  all six of its gates, none of which had any before. The `...and what we publish must
  name every chapter we mirror` step — an unconditional `echo`, unable to fail since the
  proof it named moved into the neighboring step — is deleted; the neighboring step is
  renamed `llms.txt must be current, and name every chapter we mirror` so it keeps
  reporting both proofs under one name instead of one gate satisfied vacuously by an echo
  (AGENTS.md: "A gate that cannot fail is worse than no gate"). The fan-in's six
  hand-duplicated shard-result blocks are now one loop over `${{ toJSON(needs) }}`, so a
  future re-shard only ever needs to edit the job's `needs:` list. Net effect on the
  manifest: 65 gates → 64 (the two llms.txt entries merged into the one step that actually
  runs), 760.4s → 673.5s serial; `shard_generated_views.py --check` and `--selftest` both
  pass against the committed files. Declined: rolling `generated-views-nightly`'s result
  into the `generated-views` required check, which the base job did on scheduled runs —
  out of scope per #268's own words ("nightly-only gates... not what a PR waits on") and
  reintroduces the skip-vs-fail handling the fan-in design deliberately keeps out of the
  PR-tier path; filed as #288 instead.

- 2026-08-28 — **`generated-views` was one 38.8-minute serial job against a 60-minute cap,
  headroom that only shrank as the gate count grew (55 to 71 in two days)** (#268).
  Branch protection requires a check named literally `generated-views`, so the fix keeps
  that name as a FAN-IN job — `needs: [generated-views-shard-1..5]`, `if: always()`,
  asserting every shard's `needs.*.result == 'success'` explicitly, so it goes red on
  shard failure, cancellation, AND skip alike (a plain `needs:` job is silently SKIPPED
  when an upstream fails, which is the "cancellation reads as somebody's choice" failure
  this exists to end, one layer up). The 65 PR-tier gates are bin-packed by measured
  seconds (longest-processing-time-first) into 5 parallel shards, committed as
  `.github/generated-views-manifest.yml`; `src/shard_generated_views.py --check` (a new
  gate, itself sharded in) fails the run if a gate in the workflow has no manifest entry,
  if a manifest entry names a gate nothing runs, if a manifest's stated shard disagrees
  with where the gate actually lives, or if a shard job exists that the fan-in does not
  depend on — enforced rather than reviewed. The two llms.txt gates
  (`llms.txt must be current` / `...and what we publish must name every chapter we
  mirror`) are co-located in one shard and now run as a single `build_llms.py --check
  --selftest` invocation, sharing the one full-corpus `build()` call both proofs need
  (measured ~86.7s combined vs ~173.6s as two separate steps); `build_llms.py`'s
  `selftest()` now accepts a pre-built text instead of re-walking the corpus itself.
  Every gate step carries its own `timeout-minutes` (computed from its measured seconds,
  generous margin) so a gate that runs long fails under its own name rather than the
  whole shard timing out anonymously; job-level `timeout-minutes` stays only as a
  backstop, per the ticket's "a hidden expiry date is what #267 bought time on." Also
  fixed in passing: four different steps in the old job shared the literal name
  `...and that rule must be able to fail` (after `provenance_spelling.py`,
  `results_page_documents.py`, `oar_watch_coverage.py`, and `seed_oar_watch.py`'s
  respective `--check` steps) — harmless to GitHub Actions, which does not require step
  names to be unique, but it broke the manifest's own use of step name as a gate's
  identity, so each now carries a distinguishing parenthetical. Measured, this branch,
  2026-08-28: 65 PR-tier gates (63 timed individually, all passing, plus the two
  shard-manifest-coverage gates below at their own ~0.1s, added after the timing pass),
  760.4s serial;
  bin-packed makespan 141.9s local, ~4.0 CI-minutes at the measured 1.7x slowdown — down
  from the old job's 38.8 CI-minutes, and flat as gates are added, since wall-clock is now
  set by the slowest shard rather than the sum of all of them. Nightly-only gates
  (`generated-views-nightly`; schedule/workflow_dispatch) are out of scope for the
  manifest by design and untouched in substance, only relocated to their own
  conditioned job.

- 2026-08-27 — **`CONTEXT.md` and the registry's own comments said all 189 rows carry no
  `enabling_authority`** (#219). The claim was written when the field landed empty (#170,
  2026-08-21) and never re-measured since: on this branch 113 of 189 rows carry a reviewed
  authority, not the 0 that five of the six sites first found implied, nor the 107 that
  both the ticket's own body and the sixth — `catalog_agencies.py:119`, rewritten in this
  same change — quoted, two stale snapshots of a count that moves every time a review lands
  (measured via `python3 src/catalog_agencies.py --check`). `catalog_agencies.py` already
  computes this figure live, in `authority_census()`, and prints it on every `--check` run;
  rather than pin a second, hand-maintained copy of it in CONTEXT.md's "Enabling authority"
  entry and five comments across `catalog_agencies.py` (the `FIELDS` declaration among
  them, which the ticket names directly), every one of those is reworded to state the
  three-state reasoning — an absent key never means a body has no enabling authority —
  without a number, pointing at `authority_census()` as the one live source instead. A
  two-axis review of that change found the identical present-tense claim standing,
  unmeasured, at six more sites across three more files: `src/link_enabling_authority.py`
  — the module CONTEXT.md itself names as the field's only writer — in both its module
  docstring and a `--selftest` fixture comment, `src/derive_relation_kinds.py`'s module
  docstring and an `audit()` comment, and `docs/adr/0004`'s amendment section, twice. All
  six are reworded the same way, except the ADR's two, which read as a decision record
  rather than a description of today's registry and are dated (2026-08-21, when the
  amendment landed) instead of stripped of a figure. The same review also caught a second
  defect the first pass had introduced in `catalog_agencies.py`'s RELATION_KINDS comment:
  its replacement sentence, "sits as a PROPOSED candidate," is false for 57 of the 76
  not-yet-reviewed rows, which sit in the review sheet's `no_candidate` list instead — a
  matcher finding nothing is a statement about the matcher, never a proposal (the sheet's
  own note, AGENTS.md, and CONTEXT.md's "Undetermined" entry all say so), and the comment
  now names both states rather than only the stronger one. No new `check_registry()` rule:
  nothing in this tree parses CONTEXT.md, an ADR, or a Python comment the way
  `note-covers-fields` (#185) parses the registry's own committed YAML, so there is no seam
  for a gate to watch prose through, and building one to watch twelve sentences across five
  files would be new, disproportionate machinery for a fact `--check` already reports on
  every run. `--selftest` is unchanged (74 demonstrations) — no rule was added or changed,
  only the prose describing existing ones.
- 2026-08-27 — **The agency registry's own `note` was stale, and nothing checked it** (#185).
  The top-level prose above `organizations` in `agencies.yml` — this file's self-description,
  read by three sibling corpora — drifted from 669 characters naming 4 of the then-14 row
  fields, through two more revisions that each still fell short (4,299 naming 9 of 13, then
  5,260 naming 11 of 15), to a field set that had since grown to 16 with `curator_note`
  (#178) while the note stayed at 5,260, unchanged: measured on this branch, `oar_chapter`,
  `source_url`, `aliases`, `note` and `curator_note` were declared in `FIELDS` and named
  nowhere in the note. Only a full `--refresh` — which re-fetches all 170 chapter pages
  `rules/` mirrors — rewrites the committed copy, so each prior ticket that
  changed the field set updated the note text in `cmd_refresh()`'s source but left the
  committed file behind, and nothing compared the two. `check_registry()` gains
  `note-covers-fields`: every key `FIELDS` declares must be named somewhere in the registry's
  own `note`, checked against `fields` itself rather than a second hand-maintained list, the
  same reason `CURATED_KEYS` is derived rather than restated. Both the committed note and the
  code-side literal `cmd_refresh()` writes are corrected to name all 16 fields and are now
  byte-identical, so a future `--refresh` costs this paragraph a zero-line diff rather than a
  reversion. `--selftest` grew from 71 to 72 demonstrations
  (`note-missing-a-declared-field`, watched failing against the real gap — `curator_note` —
  before the fix landed).
- 2026-08-27 — **`note-requires-manual` refused the scrape's own fetch report** (#178). The
  guard #178 added to stop a hand-typed `note` from being silently rebuilt away by the next
  `--refresh` fired on the wrong condition: it refused ANY `note` on a row that was not
  `manual`, including the three sentences `cmd_refresh()` itself writes onto ordinary
  scraped rows (a chapter page's title not parsing, its fetch failing, a chapterless
  group's children disagreeing on a name prefix) — so the first refresh to hit a parse or
  fetch failure would produce a registry `--check` rejects, with no correct fix short of
  deleting the scrape's own report of its failure or freezing the row `manual`. `note` is
  split by origin instead: it stays SCRAPED and holds only the three sentences the scrape
  writes (`note-scrape-shape` refuses anything else), and curator prose about a row gets a
  field of its own, `curator_note` (CURATED), carried across a refresh on ANY row by
  `CURATED_KEYS` — no `manual: true` required. The two hand-typed notes committed today
  (chapters 419, 950) move to `curator_note`. `--selftest` grew from 69 to 71 demonstrations
  (one existing case corrected to the new rule, two new proofs that `curator_note` — unlike
  `manual` — needs no whole-row protection to survive a refresh).
- 2026-08-27 — **43 DHS/OHA sources are being watched again** (#140, #264, ADR 0007).
  `sharedsystems.dhsoha.state.or.us` serves its leaf certificate without the intermediate
  linking it to a root, so every fetch failed strictly and, at 3.2% of the run, sat under the
  20% systemic guard: from 2026-08-05 those sources had **no drift detection at all** while
  every scheduled run reported `success`. `_meta/tls-chain/sharedsystems.dhsoha.state.or.us.pem`
  now supplies the intermediate for **that host only**. Verification is not relaxed —
  measured, the same certificate ALONE is refused, because the path must still terminate at a
  root the system already trusts. The 43 documents are unchanged: their `source_url` is
  correct, and each already carries `source_sha256` plus a committed snapshot. The `check-links`
  URL exclusion for the host is removed. First comparison after the outage: **all 43 unchanged**
  against their recorded baselines. Needs corpus-toolkit v1.31.0 (ADR 0012); all pins move.

### Changed
- 2026-08-23 — The Bulletin runs monthly, files one issue, and reports what disagrees with
  the hash (#231, ADR 0006). The last of #226–#231 and **the only one that acts outward**:
  `.github/workflows/bulletin-report.yml` runs `python3 src/bulletin_report.py` on the 6th
  of each month — the Bulletin's first **business** day is as late as the 4th — and files
  **ONE issue per run, never one per rule**. August 2026
  named 549 rule actions against a 25-issue cap, so per-rule filing is a way of reporting 25
  of them and dropping 524 on stderr, which is corpus-toolkit#67. The issue carries the
  counts by action and by corpus state, every filing the reader could not open, every
  renumber with no stated destination, **all 121 rules missing from a chapter this corpus
  mirrors BY NUMBER** rather than as a total, and the disagreement with hashing.
  **HASHING IS NOT REPLACED.** ADR 0006 rejected replacement because a silent upstream
  correction files no notice, so `scheduled.yml`'s `monthly-drift` job is untouched and
  `hash-drift-still-runs` fails if the `oar` group ever stops being hashed on that cron.
  **THE LOUD CASE IS GUARDED, AND THE GUARD IS DOING WORK RIGHT NOW.** *Moved with no
  filing* is the finding this whole series exists for and it is exactly what a stale
  baseline manufactures in bulk. A full `corpus-detect-changes --config _meta/corpus.yml
  --group oar` run on 2026-08-23 reported **484 changed, 0 fetch failures, of 484 checked**
  — #244, the OARD page footer's app version inside the hashed text. Named per rule that is
  **484 confident "changed with nobody announcing it" claims, none of them about a rule's
  text**; measured, the naive report emits exactly 484. So when more than a fifth of a
  group's compared sources move together the run reports **ONE group-wide move**, says how
  many rules it declined to name and why, and emits **0** per-rule claims — corpus-toolkit's
  ADR 0010 one level up, and the manufactured-absence failure inverted. The threshold is
  watched from both sides: 100 of 100 withholds, 1 of 100 is still named.
  **THE TWO SIGNALS WATCH DISJOINT SETS, AND THE REPORT SAYS SO INSTEAD OF GUESSING.**
  `_meta/sources/oar.yml` watches 484 **individual rule pages** in chapters 105, 122, 125
  and 128; the August bulletin named 534 rules in 35 other chapters; **the overlap is zero**
  (#247). So *filed but not yet served* is claimed only for a rule the manifest watches and
  the run compared, and the other **534 are reported as NOT CHECKED** — an absence from
  `changed-sources.tsv` is never read as an observation that the hash held still, and an
  absent drift file is reported as *the disagreement was not computed* rather than as no
  disagreement. **A run with nothing to report files no issue**, and `--check` fires that
  rule in both directions: a `should_file` that always says no satisfies the criterion by
  reporting nothing ever. **16 rules, every one watched failing** in `--selftest`, and the
  two the gate cannot be satisfied by reporting less — the body must NAME every unread
  filing and every one of the 121 coverage gaps — are fired against the committed worklist.
  **WHAT IT MAY DO IS BOUNDED**: `contents: read`, so it cannot push a commit; it writes no
  file in the repository and fetches nothing itself; it files at most one issue, idempotent
  by title against an exact scan of every issue in the repo (a full scan window is reported
  as *cannot tell* and refuses to file, rather than risking a duplicate); and `--file-issue`
  is the default of nothing, so every command typed by hand is a dry run and
  `workflow_dispatch` defaults to one.
  **A MONTH NOBODY RE-READ IS ITS LOUDEST FINDING.** The module reads the *committed*
  worklist and `check_bulletin.py` — the thing that fetches a new one — writes a file this
  job may not commit. Left alone, the September run would rebuild August's report, match
  August's issue title, print `already filed` and exit 0: a green run for a month nobody
  read, which is what a month with nothing in it looks like. `months_unread()` counts the
  bulletins published since the committed one and the issue **leads with the count**. It is
  deliberately a finding and not a `--check` rule — a gate that went red the moment the
  month turned would block every unrelated PR, which is #245's shape. Its proof was written
  and never called, and **the selftest reported OK anyway**: the two rules that compare
  `CHECK_RULES` with what the module emits cannot see an uncalled proof, because a finding
  raises no `Failure` and so no rule name goes missing. `orphaned_proofs()` closes that —
  it reads `selftest()`'s own syntax tree and fails on a proof nothing calls, watched
  failing on the very proof that went missing.
  Two gaps found and filed rather than worked around: the `oar` hash watch covers 484
  individual rule pages in four chapters, **disjoint from every rule the Bulletin names**
  (#247), and `changed-sources.tsv` lists only what changed, so a consumer cannot tell
  *unchanged* from *fetch failed* (corpus-toolkit#160) — the without-alarm section carries
  that hedge in writing rather than claiming an observation it does not have.
- 2026-08-23 — Amendments re-ingest automatically, and cannot reach a rule out of force
  (#230, ADR 0006). **The August 2026 bulletin (bulltnRsn 1761) filed 318 amendments against
  rules this corpus holds**, and one issue per rule was rejected against a 25-issue cap. ADR
  0006 splits the Bulletin's actions on whether they change a rule's TEXT or its FORCE: an
  amendment is a text refresh the provenance chain already verifies, so a human adds nothing
  by approving each one. `python3 src/reingest_oar.py --run` is that path — **306 rules
  re-ingested, 306 documents rewritten, 0 refused mid-run**.
  **THE 12 RULES THIS BULLETIN AMENDED *AND* TOOK OUT OF FORCE ARE REFUSED BY NAME**, not
  quietly skipped: 8 repealed, 4 suspended. `ingest_oar.py` used to write `status: current`
  as a hardcoded literal, and run over one of those it would resurrect the rule — a false
  statement about Oregon law, published under provenance with a source URL and a hash beside
  it. #228 moved that decision into `legal_status.resolve()`; this is the caller that made
  the gate necessary, and it cannot reach those rules by **three independent means**:
  `TEXT_ACTIONS` and `legal_status.FORCE_ACTIONS` partition `check_bulletin.ACTIONS` exactly
  (a new verb upstream STOPS this path rather than defaulting into it); the status arrives
  from the one writer and **there is no legal-status literal in the module**, which
  `legal_status.py --check` enforces against the syntax tree; and `refresh()` replaces the
  `## Full text` section and its provenance and **leaves every other field** — regenerating
  the document from the ingest template would satisfy "the rule was re-ingested" by deleting
  the 1,187 authority citations and relationship entries other tools put into just these 306
  documents.
  **THE 100 ROWS #229 MARKED ARE UNTOUCHED — 0 of their documents changed**, and
  `legal_status.py --check` still reports all 100 served by a document that agrees with them.
  `reingest_oar.py --check` reads the committed worklist and demands a re-ingest record for
  every text action filed against a held rule, so **it cannot be satisfied by a corpus that
  re-ingested nothing** — it was red on 306 rules before this ran. Every re-ingested document
  is verified against the snapshot committed beside it and **reproduced byte for byte** by
  re-running `refresh()` over that snapshot, so "re-running produces byte-identical output" is
  a gate rather than an observation. A page that has not moved is **not rewritten at all** —
  `retrieved` is the date those bytes were taken, not the date somebody last looked, which is
  `_meta/sources/oar.yml`'s `last_checked` — so a re-run is a no-op **on any later day and
  not only before midnight**. Two further full runs rewrote 0 documents and left the whole
  working tree hashing to the same git tree object.
- 2026-08-22 — A repealed or suspended rule is marked, never deleted (#229, ADR 0006).
  **The August 2026 bulletin (bulltnRsn 1761) filed 66 repeals and 34 suspensions against
  rules this corpus holds, and all 100 were served `current`.** Deleting them breaks every
  citation pointing at them — this corpus mirrors ORS sections that cite administrative
  rules — and leaving them publishes a repealed rule as current under provenance.
  `python3 src/legal_status.py --mark` derives each one from `_meta/bulletin-worklist.yml`
  onto its OAR catalog row and `python3 src/enrich_oar.py` stamps the documents from there,
  so **the catalog writes and the document reads**: 100 catalog rows written, **86 rule
  documents rewritten** (the other 14 already read `repealed`, derived from their own OARD
  History line before the Bulletin was ever read). Nothing was deleted — every row keeps its
  path and its ingest status, and `a-marked-rule-is-still-served` fails if one stops naming a
  served document.
  **A SUSPENSION IS NOT A REPEAL, and the shared schema enum cannot say what one is.** Its
  five words are `current | superseded | repealed | proposed | draft`; `repealed` is the only
  one that names a loss of force and it means a PERMANENT one, while every suspension Oregon
  files carries an end date — **185** History lines in this corpus read `temporary suspend
  filed …, effective … through …`, so writing `repealed` for one is a claim the corpus can
  disprove from its own committed text. Leaving `current` is worse in the other direction:
  CONTEXT.md defines the field as whether the rule is IN FORCE, and corpus-toolkit prints
  `current` with no warning while printing anything else as "not current text". So a
  suspension is stamped **`superseded`** — the strongest thing the enum can truthfully say —
  and the half it cannot say is carried beside it on the catalog row in
  **`legal_status_action`** (`repeal` | `suspend`), with **`legal_status_notice`** naming the
  bulletin a human opens to check the claim. The three keys arrive together or
  `legal-status-cites-its-notice` refuses the row, and `legal-status-derives-from-the-action`
  gates their agreement, because the status and the action are one fact written twice.
  The missing enum member is filed upstream as **corpus-toolkit#159** rather than papered
  over here.
  **A REPEAL OR SUSPENSION REACHES A PERSON.** ADR 0006 splits actions on whether they change
  text or force: an amendment is a text refresh the provenance chain already verifies and
  #230 re-ingests without asking, while a claim about force is not applied silently. `--mark`
  names every rule it changes, and REVIEW.md — the repo's standing list of items needing human
  intervention — gains all 100 under *Rules the Oregon Bulletin took out of force*, gated by
  `review_queue.py --check`.
  **THE RULE THAT CANNOT BE SATISFIED BY DELETING INFORMATION.** Every other rule here checks
  a row that exists, so stripping the three keys off all 100 rows would leave them all passing
  on a corpus publishing 66 repealed rules as current. `a-filed-force-action-is-recorded`
  reads the committed worklist instead and asks what the catalog is missing — measured on
  `main` it fires **100 times**, which is what retired the vacuity: `legal-status-agrees`
  shipped in #228 honestly reported as running over **0 rows**, and it now covers **100**.
  Its converse, `the-notice-names-the-filing`, refuses a row citing this month's bulletin for
  a filing that bulletin does not contain — a citation that does not support its claim is
  worse than none, because it looks checked.
  **THE CENSUS ALSO SEES A DECISION TABLE NOW.** `legal_status.py`'s scan found a legal status
  written to a key named `status`; a dict mapping something else ONTO one —
  `{"repeal": "repealed", "suspend": "superseded"}` — named no such key and was invisible,
  and that is the exact shape the next second writer takes. A mapping TO a legal status is now
  a site; a mapping keyed BY one is still a lookup that writes nothing. `--selftest` proves
  both directions, and `FORCE_ACTIONS` — this ticket's own table — is the second site the
  census reports against `src/legal_status.py`, the one writer.
  WHAT MARKING THEM COST IN THE DERIVED GRAPH, MEASURED RATHER THAN LEFT QUIET.
  `link_graph.py` has dropped a non-current rule's `implements` edges since long before this
  ticket, so marking the 100 removed **113** of them (57 from 26 repealed rules, 56 from 33
  suspended ones) and the **113** reciprocal `implemented_by` lines from **37** ORS statute
  documents. **No node was removed and no document was deleted** — all 76,313 graph nodes
  survive, every marked rule among them, and `resolve_citation` still returns each one with
  its full text. But that rule tests `status != "current"`, so in the graph a suspension is
  now indistinguishable from a repeal — the collapse this ticket forbids, one layer below
  where its proofs look. It is `link_graph`'s decision to revisit, not this ticket's, and it
  is filed as **#242** with the numbers rather than fixed here. One second-order effect came
  with it: ORS 456.625's rule fan-in fell from 90 to 74, crossing
  `build_freshness_data.UBIQUITY_MAX`, so `rule_predates_statute_amendment` went **4,603 →
  4,630** — 27 rules joined a review queue because a different rule was suspended.
  Not touched, deliberately: the **49** rules the catalog marks `not_served` with the note
  *"OARD page contains no rule number (rule likely repealed)"*. They are inference from
  absence, they predate this, and #225 keeps them as the acceptance test for this mechanism
  rather than part of it.

- 2026-08-22 — The Bulletin worklist stops collapsing two states into one (#227, #233,
  ADR 0006). Three places in `src/check_bulletin.py` reported one thing where there were
  two, all the same failure shape.
  **`in_corpus: true|false` becomes `corpus_state`, with three values.** A rule this
  corpus does not hold in a chapter it MIRRORS is a coverage gap; a rule in a chapter
  outside the selection is a boundary. The old field said "not held" to both. #227 was
  written believing the third state had never occurred — the measurement behind that
  built the mirrored-chapter set with a pattern matching `oar-*.md` against `rules/`,
  which holds chapter DIRECTORIES, so the set was empty and every rule fell outside it.
  **Re-measured against the 170 chapters `rules/` actually mirrors, 121 of August's 131
  not-in-corpus rules are missing from chapters this corpus mirrors: 74 adoptions, 43
  AMENDMENTS, 1 repeal, 3 suspensions.** An amendment means the rule existed and its text
  changed, so those 43 are a live gap in chapters this corpus claims to hold, and
  `--check` now prints all three counts on every run instead of one number over the last
  two. The field is RENAMED rather than widened: every value of a two-state field is
  truthy, so a consumer reading the new spelling off the old name would find every row
  held. The chapter set that decides between the last two states is itself checked
  against the corpus's own held rules — a chapter listing that cannot account for the
  documents on disk makes the gate REFUSE rather than file every missing rule as one
  this corpus never wanted, which is the exact measurement error above, caught.
  **A renumber records where the text went, or records that it could not.** `RENUMBER: X
  to Y` paired every number on the line with every verb (#233), so Y — where the text
  WENT — was filed as a rule that had itself been renumbered, and the move X made had no
  target at all; under `AMEND & RENUMBER: X to Y`, Y was additionally reported as
  amended. Rows now carry `renumbered_to`, holding the destination or the literal
  `unknown`, which is deliberately not spellable as an action: renumbered, renumbered
  with an unknown target and repealed are three states and only the last means the text
  is gone. Two filings naming different destinations for one rule used to be resolved
  silently in favour of whichever the table listed first; that is now recorded.
  The destination comes from the filing line and never from the OAR catalog's `served_as`:
  that field is ingest status, a record of the number OARD served THIS MIRROR a document
  under, and filling the Bulletin's silence from it would publish a mirror's bookkeeping
  as a thing the Secretary of State said.
  August filed **0 renumbers**, so this half is proved on fixtures alone and reported as
  such — July filed 64, 32 against rules held here.
  **The worklist says how much of the month it is.** `filings` and `unread_filings` are
  new, and they are what keeps a month whose filings could not be fetched from reading as
  a month in which little was filed — the substitution ADR 0006 exists to prevent, which
  the file itself had no field to record. An unread filing is NAMED, with the link a
  human would follow where there is one, and with the `reason` its rules are unknown:
  a filing the records app would not serve is re-fetched, a table row with no link is
  looked up by hand, an action line that ran off its own end is read by eye. All three
  ways of losing rules reach the FILE — a loss reported only on stderr is the notice
  corpus-toolkit#67 exists because nobody read.
  **Also fixed, both from #233 and both latent rather than occurring**: an action line
  wrapping onto the next line lost everything after the trailing comma, and a `<tr>` in
  the operative table that carried cells but no filing link was dropped where nobody could
  see it. Wrapped lines are followed; a promise the parser cannot keep and a row it cannot
  read are both recorded. And a filings table that yields ZERO filings now refuses, which
  `filing-table` could not catch — the mark stays in place while the row layout moves,
  and zero filings is also what a quiet month looks like.
  **A missed month is an error.** The Bulletin is monthly, so the months between the OAR
  group's last look upstream and the bulletin a worklist names are countable, and a
  worklist that skipped one is not stale by anything the file itself carries: it names the
  newest bulletin and every row in it is correct.
  `--selftest` proves **40 violations across 26 rules**, with **14 reader proofs held**
  (was 25 across 16, with 7). Every new rule was watched failing before it existed and
  again with its condition removed. Synthetic fixtures throughout — every OAR number is in
  chapter 999 or 998, which Oregon does not have — and the clean-month must-not-fire guard
  still holds, now over a fixture carrying all three corpus states and both kinds of
  renumber, because a fixture whose rules were all held could not tell a reader that keeps
  a gap and a boundary apart from one that collapses them.
  `_meta/bulletin-worklist.yml` was regenerated from bulletin 1761 rather than migrated,
  so its bytes come from the one writer: 549 rule actions from 159 filings, 0 unread.

- 2026-08-22 — A rule's legal status has one writer, and a gate that fails if a second appears
  (#228, ADR 0006). A rule document's `status` is corpus-toolkit's `current | superseded |
  repealed | proposed | draft` and it is a claim about Oregon law. It had **two writers**:
  `ingest_oar.py` wrote `status: current` as a hardcoded literal onto every one of the
  **36,953** rule documents it created, and `enrich_oar.py` derived the field from the newest
  action in the rule's own OARD History line — which is where the **2,031** documents reading
  `repealed` came from — and then COMPARED it in a nightly gate. That second writer was also
  an enforcer: once #229 records a repeal the Bulletin filed against a rule whose History line
  does not print one yet, the old enricher would have restamped the document `current` and
  failed the build for the Bulletin being right. And once #230 re-ingests amendments
  automatically, the ingester's literal would resurrect a repealed rule silently, publishing a
  false statement about Oregon law under provenance.
  THE DECISION MOVES TO ONE FUNCTION, `legal_status.resolve()`, and both modules become
  readers of it. The order of authority is fixed and asserted rather than described: a status
  **the Bulletin set** — carried on the OAR catalog row's own `legal_status` key — then a
  repeal in **the rule's own served History**, then **what the document already says** — the
  state **39** of the 36,953 rules are in, because OARD prints no History line inside them and
  "read no history" is a different thing from "read one that is not a repeal" — then
  `current`, which a fresh ingest may assert only where nothing better is known. **Nothing
  below the first step may override it**, which is the whole safety property #229 and #230 are
  blocked on.
  `legal_status.py --check` (CI, every PR, ~4 s) enforces it against committed data: exactly
  one module in `src/` may be marked WRITER, every other write of one of those five words says
  which corpus it belongs to, the two fields spelled `status` hold each other's vocabulary
  nowhere across all **37,007** OAR catalog rule entries, and where the catalog states a
  Bulletin-set status the document must agree. `--selftest` fires **9 unmarked or mismarked
  writes across 4 rules** and leaves **7 clean modules alone**, and it gates two things a
  second copy of a fact could otherwise hide: this module's copy of the ingest vocabulary is
  compared against what `ingest_oar.py` actually writes, read out of its syntax tree, and only
  a document's FRONTMATTER is read for a status — a rule's verbatim text can print `status:`
  at the start of a line.
  THE TWO THAT COULD ONLY BE SHOWN BY BREAKING SOMETHING were watched failing: reintroducing
  the ingester's literal makes the gate exit 1 naming both writers, and with the Bulletin step
  deleted from `resolve()` a
  real run of the enricher over a real committed rule turned `repealed` back into `current` —
  caught by `--check`, and **not** caught by `enrich_oar.py --check`, which agreed with the
  resurrection. **This change rewrites no rule documents**: `enrich_oar.py --check` reports 0
  drift across all 36,953, and the ingester's template renders byte-identical output.
- 2026-08-22 — `name` is the statutory name, and every registry row says whether it holds one
  (#168, ADR 0003). ADR 0003 calls this the risky half and took it deliberately: the
  registry's subject is the body, and a body's name is the one its enabling authority gives
  it. It is safe to land now because no consumer resolves against `name` any more — #187
  moved the two OAR-derived joins onto `oar_name` — and because `_meta/corpus.yml` now
  declares `plugins.issuing_body_name_fields: [name, oar_name, aliases]`
  (corpus-toolkit#128, shipped in v1.29.0, which this repo is pinned to). Without that
  declaration `issuing_body_profile` matches `name` alone: measured against this registry with
  every name promoted, **189 of 189 bodies become unfindable by their OAR name; with the three
  fields declared, 0**. The declaration lands in the same change as the promotion, which is
  what the toolkit's MIGRATION.md requires.
  THIS CHANGE INVENTS NO STATUTORY NAMES, and the point of it is as much the provenance as the
  values. Every row carries `name_basis`, which is one of two words and never absent:
  `enabling-authority` — a human read the body's enabling authority and recorded what it calls
  the body — or `unverified-oar-title`, which says nobody has established a statutory name and
  `name` still holds the OAR chapter title it was scraped with, unchanged. **4 of 189 rows are
  established and 185 retain an unverified OAR title**, against 107 rows that carry a reviewed
  enabling authority and could be read next. A row that quietly kept its OAR title while the
  field's documented meaning changed would be a false statement about Oregon law published
  under provenance, and it would be invisible, because the string does not move — so the two
  states are named, `catalog_agencies.py --check` reports both counts on every run, and they
  can never be the same state.
  THE CLAIM IS GATED IN BOTH DIRECTIONS. `statutory-name-basis` fails a row claiming an
  established statutory name with no enabling authority to support it — and a reviewed absence
  (`none: <reason>`) does not support it either, because a body reviewed as having no enabling
  authority has no section a name could be read off. The other half is what makes "no row's
  name is blanked" checkable rather than promised: a row recording `unverified-oar-title` must
  hold exactly its `oar_name`, so a blank, a truncation or a hand-written guess in `name` is a
  contract violation rather than something a reader has to notice.
  A STATUTORY NAME IS RESOLVED, NOT ASSERTED. `link_enabling_authority.py` gains
  `STATUTORY_NAMES`, the single writer of an established `name`, and `--check` requires the
  recorded name to appear in the mirrored text of the ORS section that body's reviewed
  authority cites. The four established today are the three the enabling-authority review
  itself handed to this ticket — ORS 684.130, 681.400 and 675.590 each open "There is
  established [the|a] **State** Board of ...", where the rules index prints "Board of ..." —
  plus ORS 674.305's Appraiser Certification and Licensure Board, where the statute and the
  rules index agree and the row's BASIS changes while its name does not. An authority form
  whose text this gate cannot read is REPORTED as unchecked rather than passed over.
  `name` IS NEITHER SCRAPED NOR CURATED, because neither is true of it: an established name is
  curation `--refresh` must carry across, and an unverified one is rebuilt from the chapter
  page so an upstream retitle still reaches it. `FIELDS` gains a `PER_ROW` origin for the case,
  `preserve_name()` reads the row's own basis to decide, and `name-origin` refuses any
  whole-field declaration of `name` or `name_basis` — declared SCRAPED, the survival
  comparison would skip the key and a reviewed statutory name would be replaced by a
  publisher's spelling with nothing reporting it. `scraped_entry()` now takes `oar_name`
  rather than `name`, and the refresh simulation replays the scrape from `oar_name`, because
  the chapter page's title is the only name the scrape can see.
  `src/record_name_basis.py` is the one-time migration that recorded `unverified-oar-title` on
  all 189 rows, re-runnable and idempotent in the shape `expand_oar_name.py` established.
  CONTEXT.md carries the final meaning of all three name fields plus the new *name basis*
  term, and `raw_index_name` gets an entry of its own rather than a mention in someone else's
  _Avoid_ line.

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
- 2026-08-22 — The Oregon Bulletin reader joins the gated modules (#226, ADR 0006).
  47 modules under `src/` carried the house `--check`/`--selftest` pair and
  `src/check_bulletin.py` carried neither, so the nine rules it already applied — three
  refusals, three reported filing failures, and the parsing distinctions that keep a rule
  number CITED in a filing's justification from being read as a rule the filing CHANGED —
  had never been watched fail. **`--selftest` now proves 16 rules able to fail across 25
  cases, with 7 reader proofs held**, against synthetic bulletin pages and synthetic filing
  text: no network, no read of the committed worklist, no read of the mirrored rules.
  Every OAR number in the fixtures is in chapter 999, which Oregon does not have, so a
  fixture can never be mistaken for a claim about a real rule's legal force.
  `--check` audits `_meta/bulletin-worklist.yml` offline, the way `review_queue.py --check`
  audits `REVIEW.md`: every rule it marks held has a document in `rules/` and is named by
  `_meta/catalog/oar.yml` (requested number or `served_as`), every rule it marks not-held
  has neither, the file says which bulletin produced it and when, and the `bulltnRsn` it
  writes twice — in the `bulletin` line and inside `bulletin_url` — must agree with itself.
  **The rule with teeth is staleness**: a worklist whose bulletin predates the OAR source
  group's own `last_checked` has left filings unread, and a repeal among them is served here
  as though nothing had happened. It fails on the July worklist this repo was carrying.
  THE MUST-NOT-FIRE GUARD IS PART OF THE PROOF. A month that read cleanly and the worklist
  it wrote must produce nothing at all, so a blanket "always report" cannot pass — and the
  fixture is the reader's OWN output, rendered and parsed back, so the writer and the checker
  cannot drift into two spellings of one file format.
  TWO THINGS IT REFUSES TO ANSWER rather than answering confidently. An index page whose
  layout moved and a bulletin page with no filings table both yield "no filings", which is
  also what a quiet month yields; and a checkout with no mirrored rules gets a refusal
  instead of every held row reported as drift. Could not check is never is not there.
  A systemic failure — more than a fifth of a month's filings unreadable — now writes
  NOTHING. It previously wrote the short worklist and then exited 1, so a run that knew it
  was missing an unknown share of the month overwrote the last worklist that was whole.
  Neither gate touches the network; fetching stays behind the mode that already did it,
  and both were verified with every socket blocked.
- 2026-08-22 — `_meta/bulletin-worklist.yml` regenerated against the **August 2026**
  Bulletin (bulltnRsn 1761), replacing July's: 549 rule actions from 159 filings, 418
  against rules this corpus holds, 0 filing fetch or parse failures. 84 adopt, 361 amend,
  67 repeal, 37 suspend.
- 2026-08-21 — The Oregon Constitution's drift signal names WHICH sections moved
  (#197, ADR 0005). The group is one source and one sha256 for the whole document, because the
  Legislature publishes all 18 articles on one page — so any amendment anywhere moves the hash
  and the raw signal says that SOMETHING changed and never what. That limitation is recorded
  once, in `_meta/sources/constitution.yml`'s `upstream_signal`, and
  `ingest_constitution.py --drift PAGE` is the diff it says has to do the work. It slices every
  one of the catalog's **371 section numbers** out of the candidate page and out of the
  committed snapshot through `repo_lib.snapshot_slice` — the same function the ingest published
  through and `corpus-verify-provenance` verifies through, so a difference is a difference in
  the section's text and never in how two callers cut it out. THE VALUE IS ENTIRELY IN THE
  DIFFERENCE: a section whose text is unchanged is not reported at all, because a report that
  named every section on any change would tell an operator exactly what the one hash already
  told them. THREE ANSWERS PER SECTION, which may never be collapsed into two — CHANGED,
  unchanged, and COULD NOT CHECK. The third is CONTEXT.md's overriding rule on the population
  where breaking it is worst: a section that cannot be sliced out of the candidate page is NOT
  a section Oregon deleted, and a heading that stopped parsing and a repeal look identical from
  here, so the report says which reasons it has (`no-slice-on-the-candidate-page`,
  `no-slice-on-the-committed-snapshot`) and refuses to guess between them. Its honest second
  half is reported alongside: a slice runs heading to heading, so a heading that stops matching
  drops its text into the PRECEDING section, and that neighbour really did change. The run
  exits non-zero whenever the page moved, including when no sliced section accounts for it —
  a page that moved with every section intact means the change is outside the text this mirror
  publishes, and reporting that as `ok` would be the quiet pass this closes. THE BASELINE IS
  THE SNAPSHOT THE SECTIONS ARE SLICED FROM, never the group file's copy of its hash: read
  the other way round, the report run against the committed snapshot itself would say
  `page CHANGED` with no section to account for it, sending an operator to diff a snapshot
  against itself. That the group records a different number is a real disagreement — the
  update-check cycle would be comparing fetches against a hash this mirror does not hold —
  and it is reported as its own finding. The committed
  DOCUMENTS are read as well as the committed snapshot, for the reason
  `link_enabling_authority.py --check` reads them: against a `constitution/` that is not there
  every section still compares equal, and the report would be a clean bill of health for
  documents that do not exist, so a mirror missing what the catalog claims makes the run REFUSE
  rather than answer. The catalog is the ALLOWLIST — the filesystem never defines the
  population. Given a path (the page an operator already fetched, or the committed snapshot)
  nothing touches the network. Four rules are proved failing in `--selftest`, and CI runs the
  report against the committed snapshot, where the honest answer is that nothing moved: a drift
  report that always fires is not a drift report. Also: the content hash of a page is now
  declared ONCE, `repo_lib.normalized_text_hash`, which `content_hash`, `hash_snapshot` and
  this report all read — a second spelling would let the report and the group's recorded
  sha256 disagree about whether the page moved.
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
  nothing (CONTEXT.md) — the mirror is read as well as the catalog for exactly that reason,
  since an empty directory would otherwise report every constitutional authority as RESOLVED
  against documents that are not there — and that refusal is proved failing rather than
  asserted. A seventh answer guards the resolver as a PUBLIC function: `--check` classifies
  the form first and cannot reach it, but answering "it resolves" about a string nothing
  recognised is the one thing a gate on admitting evidence may never say. `--selftest` holds
  20 demonstrated-failing proofs, five of them constitutional citations that must fire
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
