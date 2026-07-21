#!/usr/bin/env python3
"""MCP server for the Oregon policy corpus — thin wrapper over src/mcp_lib.py.

  python3 src/mcp_server.py                  # stdio (Claude Code / Claude Desktop)
  python3 src/mcp_server.py --http           # streamable-HTTP on 127.0.0.1:8000
  python3 src/mcp_server.py --http --host 0.0.0.0 --port 8080
  python3 src/mcp_server.py --http --public-hostname mcp.example.com  # behind a
                                              # reverse proxy/tunnel (see docs/mcp.md)

Client setup, tool reference, and deploy notes: docs/mcp.md.
Requires the `mcp` SDK (see requirements.txt); the query engine itself (mcp_lib) is
stdlib-only and smoke-tested in CI via `python3 src/mcp_lib.py --selftest`."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.fastmcp import FastMCP

import mcp_lib
from repo_lib import REPO_ROOT

mcp = FastMCP(
    "oregon-policy",
    instructions=(
        "Non-authoritative knowledge base of Oregon executive-branch law and policy "
        "(ORS, OAR, executive orders, DAS policies/procedures, Oregon Accounting "
        "Manual, EIS standards) with full verbatim text for nearly all documents and "
        "a mechanically-derived authority graph. Start with search_corpus or "
        "resolve_citation; walk authority_chain for 'what requires/implements this' "
        "questions. ALWAYS cite each document's source_url when answering — this "
        "server is never the official text."))


@mcp.tool()
def search_corpus(query: str, doc_type: str = "", agency: str = "",
                  limit: int = 10, mode: str = "hybrid") -> list[dict]:
    """Search the whole corpus (tens of thousands of statutes, rules, executive orders,
    policies, procedures, standards, accounting manual). Returns ranked matches with
    ~snippets, never whole documents.

    mode: 'hybrid' (default) blends keyword (BM25) with semantic/vector similarity, so
    conceptually-related wording still matches (e.g. 'kickback' finds 'unlawful
    gratuity'); 'keyword' is exact-term BM25 only; 'semantic' is vector-only. Hybrid and
    semantic transparently fall back to keyword when the vector index isn't built.
    Optional filters: doc_type (statute, rule, executive_order, policy, procedure,
    standard, manual, external_reference) and agency (e.g.
    'department-of-administrative-services', 'statewide')."""
    return mcp_lib.search_corpus(query, doc_type or None, agency or None, limit, mode)


@mcp.tool()
def get_document(doc_id: str, part: str = "auto") -> dict:
    """Fetch one document by id (e.g. 'ors-276a.300', 'oar-128-030-0020',
    'das-107-004-052', 'eo-20-03') with provenance metadata and the non-authoritative
    disclaimer. Normal documents return their complete body; oversized ones return an
    At-a-glance summary plus a section list — pass part='<section heading>' (e.g.
    'Full text') to page in what you need."""
    return mcp_lib.get_document(doc_id, part)


@mcp.tool()
def resolve_citation(citation: str) -> dict:
    """Map a legal citation string to in-repo document id(s): 'ORS 276A.300',
    'OAR 125-800-0020' (renumbering applied automatically), 'OAR 125-055' (division ->
    its rules), 'EO 20-03', 'DAS 107-004-052', 'OAM 15.15.00'. Use this instead of
    guessing ids."""
    return mcp_lib.resolve_citation(citation)


@mcp.tool()
def authority_chain(doc_id: str, direction: str = "both", depth: int = 3) -> dict:
    """Walk the authority graph from a document: direction 'up' follows implements
    edges toward the authorizing rules/statutes, 'down' follows implemented_by toward
    policies/procedures, 'both' does both. THE tool for compliance questions like
    'what statute requires this policy?' or 'what implements ORS 279B?'."""
    return mcp_lib.authority_chain(doc_id, direction, depth)


@mcp.tool()
def graph_neighbors(doc_id: str) -> dict:
    """All graph edges of one document grouped by type (implements, implemented_by,
    related, references_external, supersedes) — one hop only."""
    return mcp_lib.graph_neighbors(doc_id)


@mcp.tool()
def corpus_overview() -> dict:
    """What this corpus contains and does not: document counts by type, coverage
    notes (which bodies have full text vs metadata-only), human-review-queue summary,
    and the repo commit the data comes from. Call this first when unsure whether a
    document should exist here."""
    return mcp_lib.corpus_overview()


@mcp.tool()
def agency_profile(slug_or_query: str) -> dict:
    """Context ABOUT an agency's data, not the data itself: who the agency is (proper
    name, OAR chapter, parent/sub-unit hierarchy), curated governance class
    (executive_branch / semi_independent / constitutional_elected, with the citation
    that supports it), where the agency publishes its policies (or that it doesn't),
    what this corpus actually holds for it (doc counts, verbatim vs summary,
    OCR-recovered counts, unrecoverable-scan exceptions), and when its sources were
    last checked for updates. Accepts a registry slug or a name fragment
    (e.g. 'administrative services', 'financial office'). Call this before relying
    on an agency's documents so you know the data's provenance and gaps."""
    return mcp_lib.agency_profile(slug_or_query)


@mcp.resource("repo://llms.txt", name="Corpus index (llms.txt)",
              description="Curated master index of every document with guidance on "
                          "when to consult each.")
def llms_txt() -> str:
    return (REPO_ROOT / "llms.txt").read_text()


@mcp.resource("repo://REVIEW.md", name="Human-review queue",
              description="Generated list of everything needing human verification "
                          "(unverifiable scans, catalog anomalies, pending drafts).")
def review_md() -> str:
    return (REPO_ROOT / "REVIEW.md").read_text()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true", help="streamable-HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--public-hostname", default="",
                    help="Host header to additionally allow (e.g. mcp.example.com) — "
                         "required when served through a reverse proxy or tunnel that "
                         "forwards a different Host header than --host; the MCP SDK's "
                         "DNS-rebinding protection rejects any Host it doesn't "
                         "recognize. Not a secret — it's the server's own public name.")
    args = ap.parse_args()
    mcp_lib.ensure_index()  # warm the FTS cache before serving
    if args.http:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        if args.public_hostname:
            from mcp.server.transport_security import TransportSecuritySettings
            mcp.settings.transport_security = TransportSecuritySettings(
                allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*",
                              args.public_hostname],
                allowed_origins=["http://127.0.0.1:*", "http://localhost:*",
                                 "http://[::1]:*", f"https://{args.public_hostname}"],
            )
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
