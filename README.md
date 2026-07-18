# Oregon Executive-Branch Knowledge Repository (DAS pilot)

> ## ⚠️ NON-AUTHORITATIVE — AI-friendly reference only
> This repository contains **curated full-text copies** of Oregon statutes, administrative
> rules, executive-branch policies, and standards. It is **not the official text of Oregon law
> or policy** and must never be used as a source of truth for compliance decisions. Every
> document links to its authoritative source — always verify there. Oregon's own online
> databases carry the same warning: the official ORS text is the printed published copy.
> See [DISCLAIMER.md](DISCLAIMER.md).

## What this is

A public, AI-agent-friendly knowledge base of the rules and processes that govern Oregon
executive-branch agencies, starting with the Department of Administrative Services (DAS).
Each document is one Markdown file with a strict YAML provenance header (source URL,
authority level, effective/retrieval dates, content hash, verification record) and a body in
which the complete source text lives under a `## Full text` section (every line diffed
against the pinned source snapshot by CI). Curator-authored content is confined to
`## At a glance`, `## Curator notes`, and `## Cross-references`. Third-party standards
(ISO, CIS, NIST) are summary + official link only.

The full design rationale lives in [repo-design.md](repo-design.md).

## How to navigate

| Entry point | For |
|---|---|
| [llms.txt](llms.txt) | Machine-readable master index — start here if you are an AI agent |
| [AGENTS.md](AGENTS.md) | Canonical agent guide: repo rules, anti-fabrication requirements |
| [REVIEW.md](REVIEW.md) | Generated queue of everything needing human review/intervention |
| `*/_index.md` | Per-directory scoped maps ("how to find the right document") |
| Frontmatter `relationships` | Graph edges: walk from any policy up to its statute or out to referenced standards |
| [docs/mcp.md](docs/mcp.md) | MCP server: search, citation resolution, and authority-graph tools over this corpus (stdio or HTTP) |

## Structure

```
statutes/            ORS — Oregon Revised Statutes (jurisdiction-wide)
rules/               OAR — Oregon Administrative Rules (chapter/division)
executive-orders/    Governor's executive orders
agencies/administrative-services-department/   DAS-scoped: policies/ · procedures/ · accounting-manual/ · standards/
external-references/ Non-policy documents that policies require agencies to uphold
_meta/               Schemas, templates, intake skill, source manifest, snapshots
src/                 Validation tooling (frontmatter, provenance, change detection)
```

Organized by **authority tier** (statute → rule → executive order → policy → standard →
external reference), with agency-scoped material under `agencies/<agency>/` so new agencies
can be added without schema changes.

## Guarantees (enforced by CI)

- Every content file has complete provenance frontmatter (`validate-frontmatter`).
- Every `[VERBATIM]` quote is diffed against a pinned source snapshot (`verify-provenance`).
- Upstream sources are re-fetched on a schedule; hash changes open an issue automatically
  (`detect-upstream-changes`).
- All changes go through PR review with CODEOWNERS. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Content (curated government material): **CC0-1.0**. Tooling, structure, and metadata: **MIT**.
See [LICENSE](LICENSE).
