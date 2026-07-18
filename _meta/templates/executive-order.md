---
# ---- Identity ----
id: eo-YY-NN                            # required; from the FILENAME (listing metadata is wrong for some rows)
title: "TITLE"                          # required; the listing-of-record description, verbatim
doc_type: executive_order               # required
citation: "Executive Order YY-NN"
# ---- Authority ----
authority_level: executive_order        # required
issuing_body: "Office of the Governor, State of Oregon"
agency: statewide
legal_authority: []
# ---- Provenance (anti-fabrication core) ----
source_url: "https://www.oregon.gov/gov/eo/eo-YY-NN.pdf"   # required; the FileRef verbatim
source_format: pdf
retrieved: YYYY-MM-DD                   # required
source_sha256: "TODO"                   # required; normalized-text sha256 when a .txt is committed, else raw-byte sha256 of the (uncommitted) PDF
snapshot_policy: hash-only              # EO-specific: PDFs (~700 MB of scans) are never committed
# ---- Versioning ----
effective_date: null                    # only from a cleanly-parsed "Dated this ..." line; else null (HC-1: never guess from the image)
last_reviewed: null
source_version: null
status: current                         # orders are immutable; new orders may supersede old ones
supersedes: null
# ---- Repo curation metadata ----
content_mode: verbatim                  # only when the text layer passed the ingest quality gate; else summary + content_exception
conversion_notes: ""
last_verified: YYYY-MM-DD               # required
verified_by: "@handle"                  # required
maintainer: "@handle"
# ---- Relationships (graph edges) ----
relationships:
  implements: []
  implemented_by: []
  references_external: []
  related: []                           # companion files (-letter/-amended) point at their base order
  supersedes: []
tags: ["executive-order", "year-20YY"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** Verify against the official
> source: <{source_url}> (retrieved {retrieved}).

# {title} ({citation})

## At a glance

_{citation}: the listing-of-record description, verbatim. For scan stubs this is the
only content — say so plainly._

## Full text

_Only when the PDF's text layer passed the mechanical quality gate (>=100 words, >=80%
dictionary words — rejects garbage OCR). NEVER auto-OCR a scan into this section; that
would put unverified text under a verbatim heading (HC-1)._

## Provenance & change history

- Source: <{source_url}> · retrieved {retrieved} · sha256 `{source_sha256}`
- Snapshot policy: **hash-only** — executive-order PDFs are not committed; gated
  text extractions live at `_meta/snapshots/{id}.txt`.
- See this knowledge body's [CHANGELOG](./CHANGELOG.md).
