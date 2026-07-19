# Backlog

Hand-maintained list of known improvements deliberately deferred. (Distinct from
[REVIEW.md](REVIEW.md), which is generated and tracks content needing human review.)

## Deferred until a second agency's documents expose the need

- **Per-agency PDF page-furniture patterns** — `clean_pdf_text()` in
  `src/ingest_lib.py` strips furniture with one shared regex tuned to DAS/OAM
  layouts ("Statewide Policy", "OAM NN.NN.NN", "Level 1, Published"). Failure mode
  is benign (unmatched headers stay in the verbatim text), but each new agency's
  PDFs will have their own furniture. Move the patterns to data (per-agency lists
  the ingest scripts load) instead of growing one regex forever. Trigger: first
  agency whose extracted full text shows repeating page headers.

- **Per-agency policy-header patterns for the citation linker** —
  `authority_text()` in `src/link_graph.py` finds a policy's authority block via
  the DAS layout (`PURPOSE|POLICY STATEMENT` boundary). Other agencies' policy
  formats may differ, so their docs would get no edges. Detection is already
  in place (REVIEW.md's "Unlinked rules/policies/procedures/standards" section
  lights up); when it does, add that agency's header pattern rather than
  hand-authoring edges.

## Other known deferrals

- Docker image smoke test (blocked: local user lacks docker socket permission —
  `sudo docker build -t oregon-policy-mcp . && sudo docker run -p 8000:8000
  oregon-policy-mcp`).
- OCR + human-verification pass over the ~507 image-only executive orders
  (per-order detail: `_meta/catalog/eo.yml` `text_layer` field).
- CI runtime: verify only changed files on PRs, full corpus on main pushes,
  once the suite passes ~10 minutes (~2.5 min at 2,409 files).
- Semantic/embedding search for the MCP server (FTS5 keyword+rank first).
