---
# ---- Identity ----
id: das-XXX-XXX-XXX                     # required; stable slug = filename
title: "TITLE"                          # required
doc_type: policy                        # required (or: procedure)
citation: "DAS Statewide Policy XXX-XXX-XXX"
# ---- Authority ----
authority_level: state_policy           # required (agency_procedure for _PR docs)
issuing_body: "ISSUING DIVISION"        # required
agency: das                             # required
legal_authority: []                     # e.g., ["ORS 276A.300", "OAR 125-800"]
# ---- Provenance (anti-fabrication core) ----
source_url: "https://www.oregon.gov/das/Policies/XXX-XXX-XXX.pdf"   # required
source_format: pdf                      # required
retrieved: YYYY-MM-DD                   # required; date the source was fetched
source_sha256: "TODO"                   # required; sha256 of the fetched file
# ---- Versioning (mirrors the source's own version signals) ----
effective_date: YYYY-MM-DD              # from the PDF header "Effective"
last_reviewed: YYYY-MM-DD               # from the PDF header "Reviewed"
source_version: "Effective M/D/YYYY"    # verbatim version string as printed
status: current                         # required
supersedes: null
# ---- Repo curation metadata ----
content_mode: mixed                     # required
last_verified: YYYY-MM-DD               # required
verified_by: "@handle"                  # required
maintainer: "@handle"
# ---- Relationships (graph edges) ----
relationships:
  implements: []
  implemented_by: []
  references_external: []
  related: []
  supersedes: []
tags: []
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated copy/summary,
> not the official text. Verify against the official source: {source_url}
> (retrieved {retrieved}).

# {title} ({citation})

## At a glance

_1–3 sentence plain-language summary of what this document requires and who it applies to._

## Scope & applicability

_Who it binds; exceptions._

## Key provisions

### {Provision heading}

> **[VERBATIM]** "Exact quoted text from the source…"

**[SUMMARY]** Paraphrase of the provision in agent-friendly form (cite the source section).

## Definitions

## Authority & references

- Rests on: {legal_authority}
- References out to: {references_external}

## Cross-references (in-repo)

- [Related document](./related.md)

## Provenance & change history

- Source: {source_url} · retrieved {retrieved} · sha256 {source_sha256}
- Snapshot: `_meta/snapshots/{id}.pdf` / `.txt`
- See this knowledge body's [CHANGELOG](./CHANGELOG.md).
