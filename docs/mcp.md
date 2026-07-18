# MCP server

An [MCP](https://modelcontextprotocol.io) server exposing this corpus to AI clients:
full-text search, document retrieval with provenance, citation resolution (including
OAR renumbering), and authority-graph traversal. **Everything it serves is
non-authoritative** — every response carries the disclaimer and the document's
`source_url`.

## Architecture

- `src/mcp_lib.py` — query engine, stdlib-only (SQLite FTS5 index cached at
  `_meta/.cache/fts.db`, auto-rebuilt when the repo changes; graph queries over
  `_meta/graph.json`). CI smoke-tests it: `python3 src/mcp_lib.py --selftest`.
- `src/mcp_server.py` — FastMCP wrapper; stdio by default, `--http` for
  streamable-HTTP. Needs the `mcp` SDK (`requirements.txt`).

## Local setup (stdio)

```bash
git clone https://github.com/morficflux/oregon-policy-repo && cd oregon-policy-repo
uv venv .venv --system-site-packages && uv pip install --python .venv/bin/python "mcp[cli]"
# Claude Code:
claude mcp add oregon-policy -- "$PWD/.venv/bin/python" "$PWD/src/mcp_server.py"
```

Claude Desktop (`claude_desktop_config.json`):

```json
{"mcpServers": {"oregon-policy": {
  "command": "/path/to/oregon-policy-repo/.venv/bin/python",
  "args": ["/path/to/oregon-policy-repo/src/mcp_server.py"]}}}
```

First tool call after a repo change rebuilds the search index (~20 s); otherwise
startup is instant. `python3 src/mcp_lib.py --rebuild` pre-warms it.

## HTTP / container

```bash
python3 src/mcp_server.py --http --port 8000        # serves http://127.0.0.1:8000/mcp
docker build -t oregon-policy-mcp . && docker run -p 8000:8000 oregon-policy-mcp
```

Client config for a remote server: `{"type": "http", "url": "https://host/mcp"}` (or
`claude mcp add --transport http oregon-policy https://host/mcp`).

**If exposed publicly**: the server has no auth — put it behind a reverse proxy with
TLS + access control. The container bakes the corpus in at build time; rebuild to
pick up new commits.

## Tools

| Tool | Use for |
|---|---|
| `search_corpus(query, doc_type?, agency?, limit?)` | Ranked full-text search; returns snippets, never whole docs |
| `get_document(doc_id, part?)` | One document with provenance; oversized docs return a section list — request `part="Full text"` etc. |
| `resolve_citation(citation)` | "ORS 276A.300" / "OAR 125-800-0020" (renumbering applied) / "EO 20-03" / "DAS 107-004-052" → ids |
| `authority_chain(doc_id, direction?, depth?)` | "What statute requires this policy?" (up) / "what implements this statute?" (down) |
| `graph_neighbors(doc_id)` | All edges of one document, one hop |
| `corpus_overview()` | Coverage: what's in the corpus, what's metadata-only, review-queue counts |

Resources: `repo://llms.txt` (curated index), `repo://REVIEW.md` (human-review queue).

## Answering questions with it (expected agent flow)

1. `resolve_citation` or `search_corpus` to find the document.
2. `authority_chain` when the question is about what requires/implements something.
3. `get_document` to quote exact language — quote from `## Full text` and cite the
   `source_url`, never present repo text as the official version.
4. `corpus_overview` when a document seems missing (e.g. most executive orders are
   image-only scans: metadata + link in-repo, no text).
