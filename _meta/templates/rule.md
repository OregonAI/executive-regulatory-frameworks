---
id: oar-XXX-XXX-XXXX
title: "TITLE"
doc_type: rule
citation: "OAR XXX-XXX-XXXX"
authority_level: administrative_rule
issuing_body: "OWNING AGENCY per the chapter registry (_meta/catalog/agencies.yml)"
agency: OWNING-AGENCY-SLUG                # chapter -> registry lookup; enrich_oar.py fills this
legal_authority: []                     # from the rule's "Statutory/Other Authority:" line (enrich_oar.py)
statutes_implemented: []                # from "Statutes/Other Implemented:" (enrich_oar.py)
source_url: "https://secure.sos.state.or.us/oard/view.action?ruleNumber=XXX-XXX-XXXX"
source_format: html
retrieved: YYYY-MM-DD
source_sha256: "TODO"
effective_date: YYYY-MM-DD              # from the rule's history (latest AON cert. ef. date)
last_reviewed: null
source_version: "AON e.g. DAS 8-2006, f. & cert. ef. 12-28-06"
status: current
supersedes: null
content_mode: verbatim                 # required: full text for state-authored docs
conversion_notes: ""                    # what conversion stripped (page furniture, lossy tables)
last_verified: YYYY-MM-DD
verified_by: "@handle"
maintainer: "@handle"
relationships:
  implements: []                        # the authorizing ORS
  implemented_by: []                    # policies operationalizing this rule
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
