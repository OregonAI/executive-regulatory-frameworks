# MCP server

An [MCP](https://modelcontextprotocol.io) server exposing this corpus to AI clients:
full-text search, document retrieval with provenance, citation resolution (including
OAR renumbering), and authority-graph traversal. **Everything it serves is
non-authoritative** — every response carries the disclaimer and the document's
`source_url`.

## Architecture

The generic engine and FastMCP wrapper live in [corpus-toolkit](https://github.com/OregonAI/corpus-toolkit)
(`corpus_toolkit.mcp.framework` / `corpus_toolkit.mcp.server`, pinned in
`requirements.txt`) — SQLite FTS5 index cached at `_meta/.cache/fts.db` (auto-rebuilt
when the repo changes), graph queries over `_meta/graph.json`. This corpus supplies
only its own data and three plugin modules (`_meta/corpus.yml`'s `plugins:` block):

- `src/citation_schemes.py` — ORS/OAR/EO/DAS citation regex, OAR renumbering-map
  lookup, ORS repealed-disposition annotation
- `src/snapshot_slice.py` — adapter for `repo_lib.snapshot_slice`'s ITCS/ORS-chapter/OAR
  shared-snapshot slicing rules
- `src/semantic_search.py` — the vector-search layer (see below)

Run `corpus-mcp-serve --config _meta/corpus.yml` (stdio by default, `--http` for
streamable-HTTP).

## Semantic search (optional, hybrid)

`search_corpus` supports `mode`: `keyword` (FTS5/BM25 only), `semantic` (vector
similarity only), or `hybrid` (default — fuse both with reciprocal-rank fusion).
Hybrid finds conceptually-related wording that keyword search misses (e.g. "kickback"
→ "unlawful gratuity", "telework" → "remote work").

The vector index is an **offline-built, gitignored artifact** under `_meta/embeddings/`
(`vectors.i8.npy` int8 + `chunks.jsonl` + `meta.json`) — build it locally to enable
semantic search; a fresh clone has none and the server starts up keyword-only. Produced by
`python3 src/build_embeddings.py` after any ingest (`--check` is a CI staleness gate that
soft-passes when the index isn't built). Documents are chunked (title-prefixed,
paragraph-boundary chunking — `chunk_text()`); each chunk is embedded and L2-normalized,
int8-quantized so cosine ≈ int32 dot ÷ 127². `--backend auto` picks the embedding model
based on available hardware: `sentence-transformers` (default `BAAI/bge-m3`, 1024-dim,
fp16 on GPU) when a CUDA GPU is present, else `model2vec` (static, CPU-fast, lower
quality) as the CPU-appropriate fallback. `--model` overrides the default to A/B another
model. `bge-m3`'s 8192-token context embeds a whole chunk; the `BAAI/bge-large-en-v1.5`
it replaced capped at 512 tokens and silently truncated ~40% of each one. Only bge-m3's
dense head is used — the lexical arm of the hybrid is FTS5/BM25, fused by RRF.

**Dependency policy:** the base install stays stdlib-only. Vector math (`numpy`) and the
embedding model (`sentence-transformers`/`torch` or `model2vec`) live in the optional
`requirements-embeddings.txt`. The query side (`src/semantic_search.py`) lazily imports
them and **falls back to keyword-only** search whenever the artifact, numpy, or the model
is absent — so a minimal install works unchanged, and semantic search "lights up" only
where the extras and a locally-built index are present. Building the full-corpus index
requires the extras; the query side additionally needs the same model to encode the
incoming query (its name is recorded in `meta.json` precisely so the query side always
reconstructs the same one the vectors were built with).

## Local setup (stdio)

```bash
git clone https://github.com/OregonAI/executive-regulatory-frameworks && cd executive-regulatory-frameworks
uv venv .venv --system-site-packages && uv pip install --python .venv/bin/python -r requirements.txt
# Claude Code:
claude mcp add executive-regulatory-frameworks -- "$PWD/.venv/bin/corpus-mcp-serve" --config "$PWD/_meta/corpus.yml"
```

Claude Desktop (`claude_desktop_config.json`):

```json
{"mcpServers": {"executive-regulatory-frameworks": {
  "command": "/path/to/executive-regulatory-frameworks/.venv/bin/corpus-mcp-serve",
  "args": ["--config", "/path/to/executive-regulatory-frameworks/_meta/corpus.yml"]}}}
```

First tool call after a repo change rebuilds the search index (~70 s at this corpus's
size); otherwise startup is instant. Starting `corpus-mcp-serve` itself pre-warms it too.

## HTTP / container

```bash
corpus-mcp-serve --config _meta/corpus.yml --http --port 8000   # serves http://127.0.0.1:8000/mcp
docker build -t executive-regulatory-frameworks-mcp . && docker run -p 8000:8000 executive-regulatory-frameworks-mcp
```

Client config for a remote server: `{"type": "http", "url": "https://host/mcp"}` (or
`claude mcp add --transport http executive-regulatory-frameworks https://host/mcp`).

**If exposed publicly**: the server has no auth — put it behind a reverse proxy with
TLS + access control, or accept that it's unauthenticated (fine for this corpus, since
everything served is public Oregon law/policy text). The container bakes the corpus in
at build time; rebuild to pick up new commits.

**`--public-hostname`**: the MCP SDK's DNS-rebinding protection rejects any `Host`
header it doesn't recognize (defaults to `127.0.0.1`/`localhost` only) — a reverse
proxy or tunnel that forwards a different Host will get `421 Invalid Host header`
until you pass `--public-hostname <your-hostname>`. This is not a secret (it's the
server's own public DNS name); it only widens the allow-list, never anything auth-like.

### Production deployment (Cloudflare Tunnel example)

This repo's own instance runs this way: `systemd` service running
`corpus-mcp-serve --config _meta/corpus.yml --http --host 127.0.0.1 --port 8000
--public-hostname <hostname>`, fronted by a Cloudflare Tunnel (`cloudflared tunnel run`)
that terminates TLS and proxies `<hostname>` to `127.0.0.1:8000`. Nothing about the
tunnel lives in this repo:

- `cloudflared tunnel create <name>` writes credentials to `~/.cloudflared/<uuid>.json`
  on the host — outside any repo checkout, by cloudflared's own default.
- The tunnel's `config.yml` (which references that credentials file by path) also
  lives under `~/.cloudflared/`, never in-repo.
- `.gitignore` has a belt-and-suspenders block (`.cloudflared/`, `*.pem`,
  `cloudflared-*.json`, `.env*`, etc.) in case a credentials file is ever created
  inside a checkout by habit — it should never need to fire, but it's there.
- Two systemd units (`executive-regulatory-frameworks-mcp.service`, `cloudflared-<name>.service`) run
  the app and the tunnel as ordinary host services; neither unit file nor its content
  is repo-tracked, since they're deploy-environment-specific (paths, the tunnel name)
  rather than portable application config.

Rotating credentials: `cloudflared tunnel delete <name>` invalidates the old
credentials file; create a new tunnel and update the systemd unit/DNS route.

## Tools

| Tool | Use for |
|---|---|
| `search_corpus(query, doc_type?, issuing_body?, limit?, mode?)` | Ranked search; `mode` = hybrid (default, keyword+semantic) / keyword / semantic; returns snippets, never whole docs |
| `get_document(doc_id, part?)` | One document with provenance; oversized docs return a section list — request `part="Full text"` etc. |
| `resolve_citation(citation)` | "ORS 276A.300" / "OAR 125-800-0020" (renumbering applied) / "EO 20-03" / "DAS 107-004-052" / "Or. Const. Art. VI, sec. 1" → ids |
| `authority_chain(doc_id, direction?, depth?)` | "What statute requires this policy?" (up) / "what implements this statute?" (down) |
| `graph_neighbors(doc_id)` | All edges of one document, one hop |
| `corpus_overview()` | Coverage: what's in the corpus, what's metadata-only |
| `issuing_body_profile(slug_or_query)` | Who an agency is, what this corpus holds for it, freshness |

Resources: `repo://llms.txt` (curated index). (The old `repo://REVIEW.md` resource isn't
carried over by the generic toolkit server — REVIEW.md is still generated and
CI-checked, just not exposed as an MCP resource for remote clients; read it directly in
a repo checkout.)

## Answering questions with it (expected agent flow)

1. `resolve_citation` or `search_corpus` to find the document.
2. `authority_chain` when the question is about what requires/implements something.
3. `get_document` to quote exact language — quote from `## Full text` and cite the
   `source_url`, never present repo text as the official version.
4. `corpus_overview` when a document seems missing (e.g. most executive orders are
   image-only scans: metadata + link in-repo, no text).
