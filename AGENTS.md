# AGENTS.md — Canonical agent guide

This repository is a **non-authoritative**, AI-agent-friendly knowledge base of Oregon
executive-branch statutes, rules, policies, and standards (DAS pilot). Read this file
before doing anything else in the repo.

## What this repo is not

It is **not** the official text of Oregon law or policy. Never present its contents as
authoritative. Every answer you derive from it should cite the document's `source_url`.

## How to navigate

1. **Start at [`llms.txt`](llms.txt)** — the master index of every document, with
   one-line guidance on when to consult each. It is **generated** by
   `python3 src/build_llms.py` (counts/coverage derived from the corpus and
   catalogs; CI fails when stale) — curated titles, consult-prose, and highlighted
   documents live in `_meta/llms-curated.yml`; never edit llms.txt directly.
2. **Drill into `_index.md`** in any content directory for a scoped map and a "how to find
   the right document" narrative.
3. **Walk the graph** via each file's frontmatter `relationships`:
   - `implements` / `legal_authority` — up to the authorizing statute or rule
   - `implemented_by` — down to procedures
   - `references_external` — out to non-policy documents agencies must uphold
   - `supersedes` / `related` — history and siblings
4. File names are citation-aligned and predictable: `ors-276A.300.md`,
   `oar-125-800-0020.md`, `das-107-004-052.md`, `oam-15-15-00.md`, `eo-YY-NN.md`.

## Directory routing (CI-enforced)

Every `doc_type` has exactly one directory it may live in — `validate_frontmatter.py`
hard-fails CI if a document is in the wrong place, or if a `_pr` filename and
`doc_type: procedure` disagree. Jurisdiction-wide types sit at repo root; the rest are
agency-scoped under `agencies/<agency>/`:

| doc_type | Directory |
|---|---|
| `statute` | `statutes/` |
| `rule` | `rules/` |
| `executive_order` | `executive-orders/` |
| `external_reference` | `external-references/` |
| `policy` | `agencies/<agency>/policies/` |
| `procedure` | `agencies/<agency>/procedures/` (filename ends `_pr`) |
| `manual` | `agencies/<agency>/accounting-manual/` |
| `standard` | `agencies/<agency>/standards/` |

New ingestion code should call `output_dir_for(doc_type, agency)` in
`src/ingest_lib.py` rather than hand-typing a path — it's the single source of truth
(shared with the CI check via `repo_lib.DIR_DOC_TYPE`), so a new pipeline is correct
by construction instead of relying on the check to catch a mistake after the fact.

## Content policy (HARD REQUIREMENTS — full-text-first, anti-fabrication)

**Default: every Oregon state-authored document (ORS, OAR, executive orders, DAS
policies/procedures, OAM, EIS/CSS standards) carries its complete verbatim text in a
`## Full text` section** (`content_mode: verbatim`). Summary-plus-link is reserved for
third-party references (`doc_type: external_reference`, `content_mode: summary`) — ISO,
CIS, vendor material, and (by scope choice) NIST are **never** reproduced in full.

Everything under `## Full text` is verbatim by definition — CI checks every line appears
in the source snapshot in order and that coverage of the source is complete. Curator-
authored content may appear **only** under these headings:

- `## At a glance` — 1–3 sentence plain-language summary
- `## Curator notes` — optional; conversion caveats, context (renumbering, date typos)
- `## Cross-references` — in-repo relative links

A state-authored doc may be non-verbatim only with a frontmatter `content_exception`
(written justification, e.g. image-only scan with no text layer) or a legacy
`migration_pending: true` — CI warns instead of failing on those.

**Executive-order exception — hash-only snapshots**: the 500+ EO source PDFs are
~700 MB of mostly image-only scans, so they are **not** committed to
`_meta/snapshots/` (frontmatter `snapshot_policy: hash-only`). Orders whose text
layer passes the ingest quality gate (≥100 words, ≥80% dictionary-recognizable —
rejects garbage OCR) carry verbatim full text verified against their committed
small `.txt` extraction; the rest are metadata stubs (`content_exception`) whose
`source_sha256` is the raw-byte hash of the uncommitted PDF. Never auto-OCR a scan
into `## Full text`. Orders are immutable: upstream checking watches the listing
for **new** orders only (`_meta/sources/executive-orders.yml`); ingestion is
`python3 src/ingest_eo.py --enumerate` / `--ingest`, catalog in
`_meta/catalog/eo.yml`.

Absolute do-nots:

- **Never** paraphrase, summarize, or "clean up" anything inside `## Full text`; never
  summarize in place of transcription. Preserve numbering/hierarchy (e.g. `(1)(a)(A)`),
  punctuation, capitalization, and defined-term casing exactly. Strip only page
  headers/footers/page numbers, recorded in the `conversion_notes` frontmatter field.
- **Never** write content that does not exist in the pinned source. If a source cannot be
  fetched or cleanly parsed, insert `<!-- TODO: human verification required -->` and stop
  — do not reconstruct text from model knowledge.
- **Never** state a rule number, dollar figure, date, deadline, or requirement that is not
  present in the cited source; never infer a citation from memory — write `TODO: verify`.
- **Never** remove or weaken the non-authoritative disclaimer block at the top of any file.
- **Never** fill frontmatter provenance fields (`retrieved`, `source_sha256`,
  `effective_date`, `source_version`) with assumed values — transcribe them from the
  actually fetched source.

**Answering policy questions**: quote directly from the relevant document's `## Full
text` section and cite the file path plus the source's own section number (e.g.
`agencies/department-of-administrative-services/policies/das-107-004-052.md`, General
Information (4)). No external fetch
is needed for state-authored content.

## Workflows

- **Ingesting a new document**: follow `_meta/skills/intake.md` (spec-driven, two human
  review gates: manifest approval before ingestion; CODEOWNER review before merge). Use the
  templates in `_meta/templates/` and register the source in its update group under `_meta/sources/`.
- **Agency registry**: `_meta/catalog/agencies.yml` is the canonical list of
  agencies and their sub-units, keyed on the OAR chapter assignment scheme as
  presented by oregon.public.law/rules (proper names from each chapter page;
  parent/sub-unit hierarchy from the index tree), refreshed via
  `python3 src/catalog_agencies.py --refresh`. Every content file's `agency:` field
  must be `statewide`, `external`, or a slug from this registry —
  `validate_frontmatter.py` hard-fails otherwise.
- **Agency profiles**: `_meta/agency-profiles.yml` carries curated context ABOUT each
  agency's data — governance class (citation basis REQUIRED; 'unclassified' is the
  only uncited value allowed), where the agency publishes policies (or that it
  doesn't), quality caveats. Derived stats (doc counts, OCR-recovered counts,
  last-checked) are computed fresh by `src/agency_profile.py` (also the MCP
  `agency_profile` tool) and rendered into the generated `agencies/_index.md`
  (`src/build_agency_index.py`; CI-checked). Every content-bearing agency must have
  a profile entry; stub values are flagged in REVIEW.md as curation debt.
- **Onboarding a new agency**: look up its registry slug
  (`python3 src/catalog_agencies.py "<search term>"`), then
  `python3 src/new_agency.py <slug>` scaffolds the `agencies/<slug>/` tree and
  update-group stub, and prints the onboarding checklist; then follow the intake
  skill per knowledge body. Known deferred generalizations for multi-agency scale
  live in [BACKLOG.md](BACKLOG.md).
- **Checking for / applying upstream changes**: use the `/check-updates` skill
  (`.claude/skills/check-updates`) — group-scoped, token-efficient, driven by
  `src/check_updates.py` over the update groups in `_meta/sources/`. Log a
  `Source-Updated` entry in the affected body's `CHANGELOG.md`.
- **Every PR**: run `python3 src/validate_frontmatter.py` and
  `python3 src/verify_provenance.py` locally; complete the PR checklist; update the
  relevant `CHANGELOG.md` and, for new documents, the directory `_index.md`, and run
  `python3 src/build_llms.py` (llms.txt regenerates itself from the corpus).

## Commit conventions

Record agent authorship with a commit trailer, e.g.:

```
Assisted-by: Claude Code (supervised)
```

## Relationship graph

Every document's frontmatter `relationships` (implements / implemented_by /
references_external / related / supersedes) forms a traversable authority graph,
compiled into [`_meta/graph.json`](_meta/graph.json) (nodes + typed edges — the
artifact an MCP server or any tool should load instead of parsing 1,900
frontmatters). Edges are **mechanically derived** by `python3 src/link_graph.py`
from authority citations inside each document (OARD's Statutory/Other Authority
lines, policy REFERENCE headers, `legal_authority` frontmatter, the `_PR`
procedure↔policy naming rule) — never from model judgment. Run it after any
ingest; reruns are idempotent; CI fails when graph.json is stale. Hand-authored
edges are preserved, and mirrors (implements ⇄ implemented_by) are kept
symmetric automatically.

## Human-review queue

[`REVIEW.md`](REVIEW.md) is the single place listing everything that needs human
intervention (unverifiable scans, TODO markers, pending drafts, catalog anomalies,
enumeration gaps, unlinked documents). It is **generated** by `python3
src/review_queue.py` from ground truth in the repo — never edit it by hand; resolve
items at their source and regenerate. Regenerate it after any batch that adds/changes
content; CI fails when it is stale.

Every `rule`, `policy`, `procedure`, or `standard` is expected to come out of
`link_graph.py` with at least one relationship edge (an authority citation, or —
for procedures — a `_PR` naming match). If it doesn't, `review_queue.py` flags it
under "Unlinked rules/policies/procedures/standards" — check the source's
authority/reference text for wording the citation extractor doesn't recognize, or
add a hand-authored relationship if the document really has no in-repo authority.

## MCP server

`src/mcp_server.py` serves this corpus over MCP (stdio or `--http`): full-text
search (SQLite FTS5), `get_document` with provenance, citation resolution incl. OAR
renumbering, and authority-chain traversal over `_meta/graph.json`. Setup, tool
reference, and deploy notes: [docs/mcp.md](docs/mcp.md). The query engine
(`src/mcp_lib.py`) is stdlib-only and CI-tested (`--selftest`); its FTS cache lives
in `_meta/.cache/` (gitignored) and rebuilds automatically when the repo changes.

## Validation commands

```bash
python3 src/validate_frontmatter.py   # schema + relationship-graph check, all content files
python3 src/verify_provenance.py      # snapshot hash + full-text containment/coverage
python3 src/detect_changes.py         # re-fetch manifest URLs, report hash drift
```

Dependencies: `pip install pyyaml jsonschema`.
