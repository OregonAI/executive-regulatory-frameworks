# AGENTS.md — Canonical agent guide

This repository is a **non-authoritative**, AI-agent-friendly knowledge base of Oregon
executive-branch statutes, rules, policies, and standards (DAS pilot). Read this file
before doing anything else in the repo.

## What this repo is not

It is **not** the official text of Oregon law or policy. Never present its contents as
authoritative. Every answer you derive from it should cite the document's `source_url`.

## How to navigate

1. **Start at [`llms.txt`](llms.txt)** — the curated master index of every document, with
   one-line guidance on when to consult each.
2. **Drill into `_index.md`** in any content directory for a scoped map and a "how to find
   the right document" narrative.
3. **Walk the graph** via each file's frontmatter `relationships`:
   - `implements` / `legal_authority` — up to the authorizing statute or rule
   - `implemented_by` — down to procedures
   - `references_external` — out to non-policy documents agencies must uphold
   - `supersedes` / `related` — history and siblings
4. File names are citation-aligned and predictable: `ors-276A.300.md`,
   `oar-125-800-0020.md`, `das-107-004-052.md`, `oam-15-15-00.md`, `eo-YY-NN.md`.

## Content rules (HARD REQUIREMENTS — anti-fabrication)

Every substantive statement in a content file is labeled exactly one of:

- **`[VERBATIM]`** — an exact quote from the pinned source. It must be a literal
  (whitespace-normalized) substring of the source snapshot in `_meta/snapshots/`; CI diffs
  it and fails on any mismatch.
- **`[SUMMARY]`** — a paraphrase, placed under a heading tied to a cited section of the
  same source.

There is **no third category**. Model knowledge is not a source.

Absolute do-nots:

- **Never** state a rule number, dollar figure, date, deadline, or requirement that is not
  present in the cited source.
- **Never** infer or reconstruct a citation from memory. If you cannot verify it, write
  `TODO: verify` and leave it for human review.
- **Never** alter a `[VERBATIM]` quote — not even punctuation or capitalization.
- **Never** remove or weaken the non-authoritative disclaimer block at the top of any file.
- **Never** fill frontmatter provenance fields (`retrieved`, `source_sha256`,
  `effective_date`, `source_version`) with assumed values — transcribe them from the
  actually fetched source.
- **Never** reproduce third-party copyrighted standards (ISO, CIS, etc.) — summary + link
  only.

## Workflows

- **Ingesting a new document**: follow `_meta/skills/intake.md` (spec-driven, two human
  review gates: manifest approval before ingestion; CODEOWNER review before merge). Use the
  templates in `_meta/templates/` and register the source in `_meta/source-manifest.yml`.
- **Updating after an upstream change**: work the auto-opened `source-change` issue —
  re-fetch, update snapshot + hash + frontmatter dates, re-verify every quote, log a
  `Source-Updated` entry in that knowledge body's `CHANGELOG.md`.
- **Every PR**: run `python3 src/validate_frontmatter.py` and
  `python3 src/verify_provenance.py` locally; complete the PR checklist; update the
  relevant `CHANGELOG.md` and, for new documents, `llms.txt` and the directory `_index.md`.

## Commit conventions

Record agent authorship with a commit trailer, e.g.:

```
Assisted-by: Claude Code (supervised)
```

## Validation commands

```bash
python3 src/validate_frontmatter.py   # schema + relationship-graph check, all content files
python3 src/verify_provenance.py      # snapshot hash + [VERBATIM] quote diff
python3 src/detect_changes.py         # re-fetch manifest URLs, report hash drift
```

Dependencies: `pip install pyyaml jsonschema`.
