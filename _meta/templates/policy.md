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
source_sha256: "TODO"                   # required; content hash (src/repo_lib.py content_hash)
# ---- Versioning (mirrors the source's own version signals) ----
effective_date: YYYY-MM-DD              # from the PDF header "Effective"
last_reviewed: YYYY-MM-DD               # from the PDF header "Reviewed"
source_version: "Effective M/D/YYYY"    # verbatim version string as printed
status: current                         # required
supersedes: null
# ---- Repo curation metadata ----
content_mode: verbatim                 # required: full text for state-authored docs
conversion_notes: ""                    # what conversion stripped (page furniture, lossy tables)                     # required
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

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated copy of the
> official text. Verify against the official source: {source_url} (retrieved {retrieved}).

# {title} ({citation})

## At a glance

_1–3 sentence plain-language summary. Curator-authored content may appear ONLY here,
under Curator notes, and under Cross-references._

## Full text

_The COMPLETE source text, converted to Markdown. Conversion rules:_
_- preserve the source's numbering and hierarchy exactly (e.g. (1)(a)(A));_
_- preserve original punctuation, capitalization, and defined-term casing;_
_- strip page headers/footers/page numbers and record what was stripped in the_
_  `conversion_notes` frontmatter field;_
_- convert tables to Markdown tables; if lossy, keep the text and note it;_
_- NEVER paraphrase, summarize, or reconstruct from model knowledge — if the source_
_  cannot be fetched or cleanly parsed, insert `<!-- TODO: human verification required -->`_
_  and stop (HC-1)._

## Curator notes

_Optional: conversion caveats, context (e.g. renumbering notes, date discrepancies)._

## Cross-references

- _In-repo relative links: authorizing statute/rule, implementing procedures, related docs._

## Provenance & change history

- Source: {source_url} · retrieved {retrieved} · sha256 {source_sha256}
- Snapshot: `_meta/snapshots/{id}.*`
- See this knowledge body's [CHANGELOG](./CHANGELOG.md).
