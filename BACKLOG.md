# Backlog

Hand-maintained list of known improvements deliberately deferred. (Distinct from
[REVIEW.md](REVIEW.md), which is generated and tracks content needing human review.)

## Second-agency generalizations — DONE (DOC + OHA-OSH)

- **Per-agency PDF page-furniture patterns** — DONE: `clean_pdf_text(raw, agency)` in
  `src/ingest_lib.py` takes per-agency furniture via the `AGENCY_FURNITURE` dict.
- **Per-agency policy-header patterns for the citation linker** — DONE: `link_graph.py`
  `authority_text()` scans the full text for OHA policies (their references sit in a body
  section, not a header block), and `policy_xrefs()` recognizes DAS/DOC/OSH policy numbers.

## Agency-policy coverage

- **DHS Transmittals** — out of scope for the DHS import (which took only the clean
  administrative/agency policies). The per-program Transmittals system (`/odhs/transmittals/*`
  — Policy Transmittals, Action Requests, Info Memoranda) is a large SharePoint set,
  anonymously queryable via `RenderListDataAsStream`, but the items are change-*announcements*.
  Open question before ingesting: do they belong as `policy` docs or a new doc_type? Revisit
  as a separate body.
- **Remaining OHA divisions** — the policy import covers the divisions that publish policy
  listings (OSH, OEI, ISPO, IRB). Other OHA sub-units are rules-only licensing boards; add a
  `POLICY_PROFILES` entry only if one turns out to publish internal policies.

## Mass-OAR-import scale deferrals

- **OAR freshness at scale** — mass-imported chapters get NO per-rule entries in the
  `oar` update group (`ingest_oar.py --skip-group`): per-rule content-hash rechecking
  is impractical at ~20k rules. Interim freshness story: re-run
  `catalog_oar.py --discover --redo` periodically and diff the catalog (new/removed
  rule numbers), then re-ingest changes. Proper design someday: drive re-checks from
  the monthly Oregon Bulletin's list of filed rule changes instead.
- **CI runtime at ~20k+ files** — DONE: `verify_provenance.py` and
  `validate_frontmatter.py` take `--changed [ref]` (git-diff scope vs the PR base) and
  `-j N` (multiprocessing). CI runs changed-files-only on PRs and full corpus on
  push-to-main + a nightly cron. `repo_lib.changed_content_files()` is the shared scope
  helper. Not yet scoped: the global `--check` generators (`link_graph`, `review_queue`,
  `build_llms`) still recompute corpus-wide, but they carry no snapshot line-matching so
  they stay cheap; revisit if they dominate.

## Visualization

All five vizzes from this brainstorm are now **built** (each a self-contained generator +
`--check` gate, wired into the Pages site via `src/build_site.py`):

- ✅ **Agency authority graph** — `src/build_agency_graph.py` → `viz/agency-authority-graph.html`
  + `_meta/agency-graph.json`. Agencies linked by ORS chapters their rules both implement,
  ubiquity-discounted.
- ✅ **Authority-chain ego explorer** — `src/build_authority_explorer.py` →
  `viz/authority-explorer.html`. Pick any of the 68k docs; layered N-hop up/down neighborhood
  from a compact inlined adjacency (implements edges only), per-node fan-out capped at 60.
- ✅ **Statute-operationalization fan** — `src/build_statute_fan.py` →
  `viz/statute-operationalization.html`. All 404 implemented ORS chapters ranked by
  implementing-rule count, bars segmented by agency; dormant tail toggle.
- ✅ **Policy documentation gap** — `src/build_policy_gap.py` → `viz/policy-documentation-gap.html`.
  Of 93 rule-writing agencies, only 9 have any policy/procedure document ingested into the
  corpus — ranked bars of rules vs. ingested policies per agency, explicitly framed as an
  ingestion-coverage gap (see "Agency-policy coverage" above), never as a claim that an
  agency lacks internal policies.
- ✅ **Semantic topic map** — `src/build_topic_map.py` → `viz/topic-map.html`, over a cached
  UMAP from `src/build_topic_projection.py` → `_meta/embeddings/projection.2d.json` (computed
  once with a fixed seed; needs `requirements-embeddings.txt` + `umap-learn`). 68k points,
  colored by doc_type with per-type filtering.
- ✅ **Conflict candidates (pilot)** — `src/build_conflict_candidates.py` →
  `viz/conflict-candidates.html`, over `_meta/catalog/conflict-candidates.yml` (curated,
  AI-assisted, NOT mechanically derived or legally reviewed — see that file's note).
  For each of 12 piloted ORS chapters (of 245 in the shared-authority set), an LLM read the
  full statute + implementing-rule text in one pass and flagged candidate inconsistencies
  with quotes and citations; ~15 candidates found across 9 chapters chosen for high agency
  overlap + staleness (0 in the first 3 chosen without that bias — selection criteria
  matters). Every cited document id is mechanically verified against `_meta/graph.json` by
  `build_conflict_candidates_data.py` before the cache is trusted. Scaling to more of the
  245 chapters, or fixing the citation-metadata/title-truncation bugs the pilot surfaced
  along the way, are natural next steps — not done here.
- **Do NOT** rebuild the *directed* "agency A cites agency B" graph: 98% of `implements`
  edges point to statewide ORS statutes (not agency-owned), so only ~150 true inter-agency
  citation edges exist — the directed graph is a near-empty statewide hub. The
  shared-authority projection above is the data-supported alternative.

## Corpus data-quality bugs surfaced by the conflict-candidates pilot — DONE (2026-07-24)

Two systemic patterns turned up repeatedly across independent chapters during the 60-chapter
conflict-candidates pilot (`_meta/catalog/conflict-candidates.yml`) — frequently enough, and
mechanically similar enough each time, that they read as pipeline bugs rather than one-off
curation slips. Both are now fixed:

- **`relationships.implements` contamination** — DONE. `src/link_graph.py`'s
  `authority_text()` now derives a rule's implements-relevant text from its already-parsed
  `statutes_implemented` frontmatter ONLY (never `legal_authority`, never the raw
  "Statutory/Other Authority:" body text). `compute()` also stopped seeding `implements`/
  `implemented_by` from existing frontmatter before unioning in newly-resolved citations —
  those two fields are never hand-authored anywhere in the pipeline, so always recomputing
  them fresh each run makes future derivation fixes self-migrating (no separate reset
  script needed). One `link_graph.py` run after the fix dropped total `implements` edges
  from ~122,717 to 81,284 and correctly re-derived every rule's edges corpus-wide.
- **Repealed rules still `status: current`** — DONE. `src/enrich_oar.py`'s `parse_history()`
  now also reports whether a rule's *newest* History action is a repeal (reusing the
  existing newest-action boundary slicing, so an older "repealed by ... enacted in lieu of"
  note on a still-live rule doesn't false-positive); `derive()`/`apply()`/
  `expected_mismatch()` propagate `status: repealed` accordingly. A corpus-wide
  `enrich_oar.py` run corrected 2,031 rules (of 36,953 — ~5.5%, matching the original
  estimate almost exactly). Combined with the implements fix above (a repealed rule now
  contributes zero `implements` edges), the corresponding stale `implemented_by` entries
  on statutes were removed automatically, with no separate migration pass needed.

Original bug report, preserved for reference:

- **`relationships.implements` is built from `legal_authority` instead of
  `statutes_implemented`, producing implements-graph edges that contradict a rule's own
  frontmatter.** A rule's `statutes_implemented` field (and its own body-text "Statutes/Other
  Implemented" line, when present) is the rule's self-declared claim about what it
  implements; `legal_authority` (its "Statutory/Other Authority" line) is a *different*,
  broader list — the rulemaking authority the agency is acting under, which routinely
  includes statutes the rule doesn't substantively implement (a general rulemaking-authority
  statute, an adjacent statute cited only for context, etc.). In several rules, the curated
  `relationships.implements` array was evidently derived from `legal_authority` rather than
  `statutes_implemented`, so it both includes statutes the rule doesn't claim to implement
  and *omits* ones it does. Confirmed instances (chapter → rule → mismatch):
  - ORS 190: `oar-125-090-0000` — `statutes_implemented` leads with `"ORS 98.805"`, but
    `relationships.implements` omits `ors-98.805` entirely while including `ors-184.340`,
    `ors-276.601`, `ors-283.100` (present only in `legal_authority`). Same pattern in
    `oar-125-090-0002`, `oar-735-030-0055`, `oar-735-030-0057`, `oar-735-062-0080`.
  - ORS 131: all five `oar-416-150-00xx` rules — `statutes_implemented` says `"ORS 420.014"`
    (matching the rules' own body text) but `relationships.implements` points to
    `ors-420.081` instead — identical across all five sibling rules, so likely one upstream
    mapping error rather than five independent ones.
  - ORS 153: `oar-738-140-0010/-0015/-0020/-0025/-0030` and `oar-740-100-0100` — each rule's
    own text keeps "Statutory/Other Authority" and "Statutes/Other Implemented" as two
    distinct lists, but `relationships.implements` merges both into one array. Net effect:
    `ors-153.022`'s `implemented_by` list claims six rules implement it, but none of those
    six rules' own "Statutes/Other Implemented" line actually includes ORS 153.022 — it
    appears only as authority in every one of them.
  - ORS 693: `oar-918-695-0040` and `oar-918-780-0030` — both cite their target statute
    (`ORS 693.030`, `ORS 693.135` respectively) in `legal_authority` only, per their own
    verbatim "Statutory/Other Authority" vs. "Statutes/Other Implemented" split, yet
    `relationships.implements` (and the statute's own `implemented_by`) treat them as
    implementing that statute.
  - Also seen (asymmetric but same root cause) in ORS 271 (`oar-125-045-0205`), ORS 106
    (`oar-411-049-0102`, disagrees across all three of `legal_authority`/
    `statutes_implemented`/`relationships.implements` simultaneously), and ORS 205/419A/814
    clusters.
  Suspected fix location: whatever step in the ingestion/enrichment pipeline populates
  `relationships.implements` for OAR rules (likely in `src/enrich_oar.py` or
  `src/link_graph.py`) — should source strictly from `statutes_implemented`, never
  `legal_authority`. Worth a corpus-wide audit script comparing the two fields once fixed,
  not just a fix for future ingests, since ~69k existing rule docs may carry the bug.

- **Rules repealed per their own "History" line are still tagged `status: current` and left
  wired into a statute's `implemented_by` graph as if live.** The rule's frontmatter
  (`status: current`, and often `effective_date` set to the *repeal* date rather than a real
  effective date) contradicts its own body text, which shows a `repeal filed .../ effective
  ...` entry as the most recent history item and has no operative rule text beyond the
  title/authority/history block. A reader or downstream tool trusting `status`/
  `implemented_by` would believe obsolete rule text still governs. Confirmed instances
  (chapter → rule(s) → repeal date per the rule's own History line):
  - ORS 244: `oar-199-001-0040` (repealed 2021-12-30); `oar-199-010-0085`, `-0090`, `-0100`
    (all repealed 2021-12-30) — all four still listed in their respective statutes'
    `implemented_by`.
  - ORS 171: same three `oar-199-010-00xx` rules (shared with ORS 244 above, both statutes
    cite them), plus `oar-855-010-0016` (repealed 2024-02-29, Oregon Medical Board).
  - ORS 419A: the entire `oar-413-350-0100/-0110/-0120/-0130/-0140` division (all repealed
    2021-11-01) — the *only* rules ORS 419A.260/419A.262 list as implementers, even though
    both statutes were substantively re-amended in 2025, four years after the repeal.
  - ORS 340: the entire `oar-581-017-0640/-0642/-0644/-0646/-0648/-0650` division
    implementing ORS 340.320 (five repealed 2025-04-02, one 2025-06-16).
  - ORS 578: `oar-678-030-0000/-0010/-0020` (all repealed 2022-03-04) — the rules ORS
    578.060(3)'s "shall adopt" per-diem/expense mandate depends on.
  - ORS 205: `oar-813-001-0060` (repealed 2026-07-06, the day before this pilot's own
    retrieval date) — ORS 205.125's sole implementer.
  - ORS 280: `oar-123-042-0165` (repealed 2026-06-18) — ORS 280.518's sole implementer.
  - ORS 131: `oar-461-135-0440` (repealed 2023-07-01, same date as its own
    `effective_date` field) — ORS 131.715's sole implementer.
  - ORS 107: eight `oar-416-100-00xx` OYA rules (all repealed 2022-01-03), still listed in
    ORS 107.108's `implemented_by`.
  - ORS 163: `oar-333-015-0210` (repealed 2022-02-10) — ORS 163.575's sole implementer.
  This is frequent enough (10 chapters independently hit it) that it's very likely a gap in
  how repeal filings are detected/applied during OAR re-ingestion, not ten unrelated
  curation misses — worth checking whatever step sets `status` from the OARD "History" text
  in `src/ingest_oar.py`/`src/enrich_oar.py`. A cheap mechanical detector: any rule whose
  full text is empty (title + authority/history block only) AND whose most recent History
  entry contains "repeal" should never carry `status: current`.

## Semantic vector index — deferred after the 2026-07-26 rebuild

The index was rebuilt at chunk granularity in #32 (`CHUNK_CHARS` 1600 → 3200, 167,844
chunks, 82.0 MiB). It had previously become unreproducible: the committed artifact was
document-level while the code produced chunk-level, and a fresh build at 1600 came to
112.5 MiB — over GitHub's hard 100 MiB per-file limit, so it could not be pushed even
once rebuilt. `build_embeddings.py` now fails loudly at that ceiling. Two related
things were deliberately NOT done in that PR:

- ~~**`_meta/embeddings/projection.2d.json` was computed from the OLD document-level
  vectors.**~~ **REBUILT 2026-07-27** from the bge-m3 chunk index (211,102 points, 28
  clusters; `build_topic_projection.py` took 3m23s, `build_topic_map.py` regenerated
  `viz/topic-map.html`).

  **Still open — the staleness check itself.** It compares the projection cache against
  its own contents, so it could not see that the vectors it was derived from had changed
  shape (69,395 document vectors → 167,844 chunk vectors → now 211,102 chunk vectors at
  dim 1024). It should key on the vector artifact's `fingerprint` in
  `_meta/embeddings/meta.json` instead. This is the same latent-staleness pattern that
  let the index itself drift unnoticed, and it will silently recur on the next re-embed.

- ~~**The embedding backend is still `model2vec` (`potion-retrieval-32M`, dim 512).**~~
  **DONE (2026-07-27):** the transformer default is now `BAAI/bge-m3` (dim 1024), selected
  by `--backend auto` on this CUDA host. The 100 MiB blocker described here dissolved
  rather than being solved: `_meta/embeddings/` is now gitignored (`.gitignore:36`), so
  the 164 MiB artifact is never pushed and the size check in `build_embeddings.py` is
  guarded by `_is_tracked_by_git` — advisory, not fatal. The model chosen was bge-m3 over
  the bge-large-en-v1.5 contemplated here because bge-large caps at **512 tokens** while
  `CHUNK_CHARS = 3200` produces chunks past it. Measured over an 11,449-chunk sample:
  **34.3% of chunks exceed 512 tokens and 16.9% of all tokens** fell outside the window
  (median chunk is 267 tokens, so most were unaffected — an earlier note here said "~40%
  of every chunk", which was wrong). bge-m3's 8192-token context embeds them whole, and
  it needs no query-instruction prefix — which the serve side never applied, and which
  measurement showed cost nothing anyway. Dense head only; BM25 remains the lexical arm.
  `--model` now exists for before/after A/B, and produced the numbers above.

## Semantic query latency — ~365 ms/query, brute-force scan (open)

**Symptom.** Every `search_corpus` call in `hybrid` or `semantic` mode costs ~365 ms in
the vector arm. Measured end-to-end over 6 queries against the built index.

**It is not the model.** Breakdown of a single query against the 211,102 × 1024 int8
artifact:

| stage | time |
|---|---|
| encode the query (bge-m3 forward pass) | 14.8 ms |
| `vecs.astype(np.float32) @ q` | 293–460 ms |
| `argsort` over 211k scores | 6.1 ms |

**Root cause.** `rank()` in `src/semantic_search.py` (the line
`scores = vecs.astype(np.float32) @ q`) converts the *entire* 206 MiB int8 matrix to
float32 on **every query**, allocating an 864 MB temporary each time. The vectors are
already held resident as int8 by `_semantic_index()`'s module-global cache; only the
conversion repeats.

This is pre-existing, not introduced by the bge-m3 switch — but the switch made it
~2.5× worse in absolute terms by moving from 167,844 × 512 (86 MiB) to 211,102 × 1024
(206 MiB). Note bge-large would have cost exactly the same: it is also 1024-dim. The
real cause is the move off the 512-dim model2vec index, which predates both.

**Already tried and ruled out — do not repeat.** Blocked matmul, to cap the temporary
allocation, at three block sizes. It does not help; the work is memory-bandwidth-bound
on 216M int8 values, not allocation-bound:

    current (one 864 MB temp)  293.8 ms
    8,192-row blocks           300.0 ms
    32,768-row blocks          291.4 ms
    65,536-row blocks          294.3 ms

**Options, cheapest first.** None measured yet:

1. **Keep a float32 copy resident** instead of converting per query. Eliminates the
   `astype` entirely and is a few lines. Costs ~864 MB RSS per MCP server process,
   which may be the real objection — the Docker image and any multi-worker deployment
   pay it per process.
2. **float16 resident matrix** — 432 MB instead of 864 MB. Needs measuring rather than
   assuming: numpy upcasts float16 internally for matmul, so it may buy memory without
   buying speed.
3. **int8 dot with int32 accumulation.** `build_embeddings.py`'s own artifact note says
   "cosine ≈ int32 dot / 127^2", so this was the intended arithmetic and nothing does
   it. numpy has no int8 GEMM, so this likely needs a different primitive to be worth
   anything.
4. **An ANN index** (hnswlib / faiss). The only option that is sublinear and the only
   one that keeps working as the corpus grows. Costs a new dependency, and the serve
   side is deliberately lazy-import-and-degrade so the base install stays stdlib-only —
   it would have to live in `requirements-embeddings.txt` and fall back cleanly.
5. **Fewer vectors** by raising `CHUNK_CHARS`. Cheapest to try, but trades retrieval
   granularity for latency and changes results — measure recall before and after.

**Decide whether it matters first.** 365 ms inside an MCP tool call may be entirely
acceptable; the agent is already waiting on an LLM turn. Establish a target before
optimizing — if the answer is "fine as is", close this rather than carrying it. The
number worth watching is not latency today but its growth: this is O(corpus), so it
doubles when the corpus does.

## Other known deferrals

- Docker image smoke test (blocked: local user lacks docker socket permission —
  `sudo docker build -t oregon-policy-mcp . && sudo docker run -p 8000:8000
  oregon-policy-mcp`).
- Human-verification pass over the OCR'd executive orders. Machine recovery is
  effectively finished: 514 of 526 orders now carry full text, and only **12** remain
  metadata stubs (`content_exception`) — a two-engine fallback pass (#32,
  `src/ocr_fallback_eo.py`) recovered 15 of the 27 orders that had no machine-readable
  text at all, and a 26-document bake-off found no engine that beats the incumbent
  where the incumbent already produces output. What is NOT done is a human reading any
  of the recovered text against its source PDF: those 15 documents are marked
  `NOT human-verified` in `conversion_notes` and in their own Curator notes, and
  signature blocks/names/dates are their least reliable part. Per-order detail:
  `_meta/catalog/eo.yml` `text_layer` field; the amended promotion rule lives in
  AGENTS.md ("OCR into `## Full text` — the two-engine rule").
- CI runtime: verify only changed files on PRs, full corpus on main pushes,
  once the suite passes ~10 minutes (~2.5 min at 2,409 files).
- Semantic/embedding search for the MCP server — DONE. Infrastructure (hybrid
  BM25+vector `search_corpus` with RRF, `src/build_embeddings.py`, int8 committed-vector
  format, optional-dep lazy fallback to keyword-only, CI soft-gate) plus a committed
  production index over the full corpus with a real local model: `model2vec`
  (`potion-retrieval-32M`, dim 512), chunk granularity, 167,844 vectors covering all
  69,395 documents. The `hashing` fallback backend has NO semantic quality and remains
  wiring/tests only. Model and granularity follow-ups are tracked under "Semantic vector
  index" above. (That entry describes the state at the time; the model has since moved to
  `BAAI/bge-m3` and the artifact is no longer committed — see above.)
