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
- ✅ **Corpus coverage map** — `src/build_coverage_map.py` → `viz/corpus-coverage.html`.
  Squarified treemap of body → agency → doc_type sized by count.
- ✅ **Semantic topic map** — `src/build_topic_map.py` → `viz/topic-map.html`, over a cached
  UMAP from `src/build_topic_projection.py` → `_meta/embeddings/projection.2d.json` (computed
  once with a fixed seed; needs `requirements-embeddings.txt` + `umap-learn`). 68k points,
  colored by doc_type with per-type filtering.
- **Do NOT** rebuild the *directed* "agency A cites agency B" graph: 98% of `implements`
  edges point to statewide ORS statutes (not agency-owned), so only ~150 true inter-agency
  citation edges exist — the directed graph is a near-empty statewide hub. The
  shared-authority projection above is the data-supported alternative.

## Other known deferrals

- Docker image smoke test (blocked: local user lacks docker socket permission —
  `sudo docker build -t oregon-policy-mcp . && sudo docker run -p 8000:8000
  oregon-policy-mcp`).
- OCR + human-verification pass over the ~507 image-only executive orders
  (per-order detail: `_meta/catalog/eo.yml` `text_layer` field).
- CI runtime: verify only changed files on PRs, full corpus on main pushes,
  once the suite passes ~10 minutes (~2.5 min at 2,409 files).
- Semantic/embedding search for the MCP server — infrastructure DONE (hybrid
  BM25+vector `search_corpus` with RRF, `src/build_embeddings.py`, int8 committed-vector
  format, optional-dep lazy fallback to keyword-only, CI soft-gate). Remaining: build and
  commit the production index over the full corpus with a real local model
  (`pip install -r requirements-embeddings.txt`; the default `hashing` fallback backend
  has NO semantic quality and is for wiring/tests only). Best done after the ORS
  mass-ingest so the vectors cover the expanded corpus.
