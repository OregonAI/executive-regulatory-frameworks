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

Every `doc_type` has exactly one directory it may live in — `corpus-validate-frontmatter`
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
| `schedule` | `agencies/<agency>/schedules/` |

`schedule` is a **special records-retention schedule** issued by the Secretary of State
Archives Division. It is scoped under the agency it **binds**, not the one that issued it —
`issuing_body` stays "Secretary of State, Archives Division" on every one, while `agency` names
whose records it governs, which is the field `agency_profile` keys its views on and the
question a reader actually has. The **general** schedules are OAR chapter 166 and live in
`rules/166/`; a special schedule supplements them for one agency and cites them, so the two are
read together. Folded in from the retired `OregonAI/oregon-records-retention` (PLAN.md Phase 9).

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
`source_sha256` is the raw-byte hash of the uncommitted PDF — recoverable only
under the two-engine rule below. Orders are immutable: upstream checking watches
the listing for **new** orders only (`_meta/sources/executive-orders.yml`);
ingestion is `python3 src/ingest_eo.py --enumerate` / `--ingest`, catalog in
`_meta/catalog/eo.yml`.

### OCR into `## Full text` — the two-engine rule

This section supersedes the earlier blanket prohibition *"Never auto-OCR a scan
into `## Full text`."* That rule was written when the only option was a single
engine producing unverifiable garbage, and a single engine's output is still
never promotable. What changed is that **independent corroboration is now
available**: two OCR engines that share no model weights are vanishingly unlikely
to invent the *same* words, so high agreement between them is positive evidence
the words are physically on the page. That evidence — not a better engine — is
what makes promotion defensible.

#### The default stack is tesseract + PaddleOCR

Adopted from `oregon-kpm/AGENTS.md`, where the pair was chosen by measurement rather
than preference. Do not hand-roll a renderer and do not substitute a hosted model.

**Primary: `ocrmypdf` (tesseract).** Writes a text layer into a *copy* beside the
original, never over it. In this repo the committed `_meta/snapshots/<id>.txt` **is**
that reading — `cmd_ocr` in `src/ingest_eo.py` writes it from `ocrmypdf | pdftotext`
— so corroborating an already-recovered order does not require re-running tesseract.

**Cross-check: PaddleOCR (PP-OCRv6).** Reads the **original** scan, so the two engines
share nothing but the pixels. Corroborating against a copy of the first engine's output
would be an echo, not evidence. Measured word agreement against tesseract: 0.816–0.929
across the six oregon-kpm scans, 0.935–0.965 on the first executive orders measured here.

**Tiebreaker: docTR (DBNet + CRNN).** Not the default — it agrees with tesseract less
than Paddle does on every document measured (0.747–0.862), so making it the default
would lower every score. Reach for it when the primary pair disagrees, and when
orientation is in doubt: it straightens pages itself.

Three traps, each found by measurement, each of which turns a gate into theatre:

- **Verify every engine's orientation handling separately.** With Paddle's
  `use_doc_orientation_classify=False` a rotated scan scored **0.050** against
  tesseract; with it on, **0.929**. Same page, same engines. Forget it and the
  corroboration check quietly becomes an orientation check, failing documents that
  are fine.
- **Never build the quality-gate dictionary from a corpus that already contains OCR
  output.** The errors enter the vocabulary that judges them — `pernitted` becomes a
  recognised word — and every OCR'd document then scores 100% dictionary-recognizable
  however badly it was read. A gate that cannot fail is worse than no gate, because it
  looks like evidence. This repo uses the `wamerican` system wordlist, which cannot be
  contaminated this way; a corpus-derived vocabulary must exclude OCR-derived documents.
- **Score the figures separately from the words.** The agreement metric counts
  `[a-z]{2,}` and so excludes every digit. Measured on executive orders, word agreement
  runs 0.935–0.965 while agreement on the *figures* runs 0.789–0.923 — digits are
  exactly where two engines diverge, and the headline number hides it. Report both. A
  low figure score means human review, not rejection.

OCR-derived text may enter `## Full text` only when **every** condition holds:

1. **The document has no text at all today.** OCR may *add* text where a stub has
   none; it may **never** replace or "improve" text already committed. (Measured:
   a 26-order bake-off found the alternative engines worse than the incumbent
   wherever the incumbent produces output — 0 of 18 improved, mean dictionary
   ratio 87.6% → 75.3%.)

   **Re-measured for Paddle, because the bake-off above never tested it.** That
   bake-off covered rapidocr and easyocr, so adopting Paddle as the default
   cross-check extended a rule to an engine its own evidence was silent about.
   Head to head on 60 orders spread across two decades of scan quality
   (`src/ocr_corroborate_eo.py --ab`), committed tesseract text versus Paddle's
   reading of the same scans:

   | | tesseract | Paddle |
   |---|---|---|
   | dictionary ratio (mean / median) | **0.969 / 0.973** | 0.963 / 0.968 |
   | per-document better | **28** | 7 (25 tie) |
   | glued letterhead tokens | **9** | 142 |
   | words captured | **43,797** | 43,419 |

   So the conclusion holds for Paddle too, and the mechanism is visible in the
   glued-token column: Paddle returns per-line `rec_texts` with no layout model,
   so wide-tracked letterhead and all-caps headings come back concatenated, where
   tesseract's output passes through `pdftotext -layout` and keeps its spacing.
   Replacing committed text with Paddle's reading would be a **regression**, not
   an improvement. This is not a verdict on Paddle as an engine — it is a good
   corroborator, which is precisely the job it holds here.
2. **Two independent, purpose-built OCR engines agree ≥80%** on the word sequence
   (`difflib.SequenceMatcher` over lowercased word tokens).
3. **The pre-existing quality gate passes unchanged** — ≥100 words,
   ≥80% dictionary-recognizable.
4. **Generative / VLM OCR is forbidden for transcription.** Purpose-built
   detector-recognizer engines only. A generative model asked to read a blurry
   legal scan will emit fluent, plausible, *wrong* statutory language; a
   purpose-built engine garbles visibly instead. Visible garbage is a safety
   property here — it fails the gate rather than passing as text.
5. **Artifacts are disclosed, never repaired.** Lost word spacing in letterhead
   (`OfficeoftheGovernor`) is counted and reported, not fixed — re-inserting word
   boundaries means writing text the OCR did not resolve, which
   [the content policy](#content-policy-hard-requirements--full-text-first-anti-fabrication)
   forbids.
6. **Provenance is recorded in `conversion_notes`**: both engine names, the
   agreement rate, the dictionary ratio, and the words `NOT human-verified`.
7. **The reader is warned in the document itself** — the non-authoritative banner
   states the text is OCR-derived and unverified, and `## Curator notes` explains
   that signature blocks, names, and dates are the least reliable part of an OCR'd
   scan.
8. **The human review gate is unchanged.** CODEOWNER review before merge, exactly
   as for any other content change.

Anything failing any bar stays a stub and stays in REVIEW.md, with the failed
attempt recorded in `_meta/catalog/eo.yml`'s `text_layer` so a later run can
distinguish "tried and failed" from "never tried". Implementation:
`python3 src/ocr_fallback_eo.py --report` / `--apply`.

#### Corroborating orders that were recovered before this rule existed

479 orders were recovered by tesseract alone and say so in `conversion_notes`; the
two-engine rule was written afterwards. Rule 1 forbids re-OCRing them to *replace*
that text, but it does not forbid gathering the evidence that was never gathered.
`python3 src/ocr_corroborate_eo.py --measure` reads each original scan with Paddle
and scores it against the committed text; `--apply` records both engines and both
agreement rates in `conversion_notes` and changes nothing else. In particular it does
**not** recompute `source_sha256`, because that hashes the committed text and the
committed text does not change.

A document scoring below the bar is **reported, not edited and not withdrawn**. It
keeps its original single-engine note — claiming corroboration it does not have would
be worse than claiming none — and goes to a human.

Because executive-order PDFs are `snapshot_policy: hash-only`, this begins with a
re-fetch: `python3 src/fetch_eo_pdfs.py` restores them into `_meta/.cache/eo-pdfs/`,
which is gitignored, throttled, and resumable. The committed `.txt` files are OCR
*output* and cannot be fed back into an OCR engine, so there is no way to re-run the
stack without the images.

**This text is not verbatim in the sense the rest of the corpus is.** Everywhere
else, `## Full text` means a human-authored source was transcribed and every line
is diffed against a pinned snapshot. Here the snapshot *is* the machine's reading
of an image, so the hash proves only that the file matches what OCR produced — not
that OCR read the page correctly. Treat these documents as the best available
reconstruction, cite them with that caveat, and verify anything load-bearing
against the source PDF.

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

## Found a bug you are not fixing right now? Open an issue. Period.

This is not optional and has no size threshold.

If you discover a defect and do not fix it in the change you are working on, **open a
GitHub issue before you finish the task**. Not a note in the commit message, not a
paragraph in the PR body, not a line in your summary to the user. Those are not a work
queue — nobody greps closed PRs six months later, and the next agent rediscovers the same
bug from scratch, usually the expensive way.

This applies to every one of these, not just crashes:

- a check that passes without checking anything
- a documented command, flag, or path that does not exist or does not work
- a claim in a README, docstring, or catalog note that is no longer true
- data known to be wrong, stale, or incomplete
- a guard that cannot fire, or fires on the wrong condition
- something you worked around instead of fixing

**File it in the repo that owns the fix, which may not be the repo you are in.** A parser
defect here, a registry gap in a sibling corpus, and a validator gap in `corpus-toolkit`
are three different issues in three different repos. Say plainly in each which repo the
work belongs to.

An issue must answer four things, because an issue that only says "X is broken" costs the
next person the whole investigation again:

1. **What is wrong** — the specific behaviour, not a category
2. **How it was found** — the command, the data, the failing case
3. **What it breaks** — who or what gets a wrong answer, and how silently
4. **What would fix it**, or what still needs measuring before anyone can know

Prefer counts and reproductions over adjectives. "126 appropriations unjoined, of which 59
are an extraction gap and 41 are correct" is actionable; "agency matching needs work" is
not, and will be re-derived by someone else.

**Every issue you open gets at least one label.** No exceptions, and not "later" — pass
`--label` on the `gh issue create` call that opens it. An unlabelled issue is invisible to
every filter anyone actually uses to triage, so it costs the same as not filing it. Use a
label that already exists in the repo you are filing in (`gh label list`); in this repo
that is:

- `bug` — it is wrong, stale, or does not do what it claims
- `enhancement` — it works, but a capability or coverage gap remains
- `documentation` — a README, docstring, catalog note, or this guide is out of date
- `question` — a scope or design decision a human has to make before work can start

Apply more than one when they genuinely both hold. If nothing fits, pick the closest and
say so in the body — do not invent a label on the fly, since a one-off label nobody else
filters on is the same as no label.

If you genuinely cannot open one — no network, no permission — say so explicitly in your
final message to the user and hand them the text to file. Silently dropping it is the one
outcome that is never acceptable.

## Agent skills

### Issue tracker

GitHub Issues on `OregonAI/executive-regulatory-frameworks`, via the `gh` CLI. See
`docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, each label string equal to its name. See
`docs/agents/triage-labels.md`. These track issue *state* and are a separate axis
from the topic labels above — every issue still gets a topic label on creation.

### Domain docs

Single-context — `CONTEXT.md` and `docs/adr/` at the repo root. See
`docs/agents/domain.md`.

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
  `corpus-validate-frontmatter` hard-fails otherwise. Its contract is gated by
  `python3 src/catalog_agencies.py --check` (CI, every PR): reading committed data only,
  it replays a `--refresh` in simulation and fails when a row or a curated field would not
  survive one, plus the slug/chapter/parent rules of ADR 0003 and ADR 0004. A curated field
  is declared ONCE in that file's `FIELDS` table — `CURATED_KEYS` is derived from it, so a
  field cannot be curated in one place and forgotten in the other. `--selftest` proves every
  one of those rules can fail.
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
  are tracked as GitHub issues, not a file in the repo -- `BACKLOG.md` was retired
  2026-07-30 and its live items became issues #76-#79.
- **Checking for / applying upstream changes**: use the `/check-updates` skill
  (`.claude/skills/check-updates`) — group-scoped, token-efficient, driven by
  `src/check_updates.py` over the update groups in `_meta/sources/`. Log a
  `Source-Updated` entry in the affected body's `CHANGELOG.md`.
- **Every PR**: run `corpus-validate-frontmatter --config _meta/corpus.yml` and
  `corpus-verify-provenance --config _meta/corpus.yml` locally; complete the PR checklist; update the
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

**Agency graph visualization**: `python3 src/build_agency_graph.py` derives an
agency-level *shared-statutory-authority* graph from `_meta/graph.json` (agencies linked
by the ORS chapters their rules both implement, ubiquity-discounted) and emits
[`_meta/agency-graph.json`](_meta/agency-graph.json) plus a self-contained interactive
page [`viz/agency-authority-graph.html`](viz/agency-authority-graph.html) (data inlined,
no external assets). Regenerate after any ingest; `--check` gates it in CI. Both are
generated — never hand-edit.

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

`corpus-mcp-serve --config _meta/corpus.yml` (from corpus-toolkit) serves this corpus
over MCP (stdio or `--http`): search (`search_corpus`, `mode` = hybrid/keyword/semantic),
`get_document` with provenance, citation resolution incl. OAR renumbering, and
authority-chain traversal over `_meta/graph.json`. Setup, tool reference, and deploy
notes: [docs/mcp.md](docs/mcp.md). The generic query engine
(`corpus_toolkit.mcp.framework`) is stdlib-only; this corpus's citation/renumbering
logic and snapshot-slicing rules plug in via `src/citation_schemes.py` and
`src/snapshot_slice.py` (see `_meta/corpus.yml`'s `plugins:` block). Its FTS cache lives
in `_meta/.cache/` (gitignored) and rebuilds automatically when the repo changes.
Semantic/vector search is optional and additive, wired in via `src/semantic_search.py`:
it uses an int8 vector index under `_meta/embeddings/` (built offline by
`src/build_embeddings.py`, refreshed after ingests). **The index is NOT committed** —
`.gitignore` excludes it, so a fresh clone and CI both lack it and the `--check` gate
soft-passes rather than verifying anything. Rebuild it by hand after an ingest; nothing
will tell you it is stale. It needs the
extras in `requirements-embeddings.txt` (numpy + a local embedding model); when those are
absent the engine transparently falls back to keyword-only. Never hand-edit the vector
artifact.

## Validation commands

```bash
corpus-validate-frontmatter --config _meta/corpus.yml   # schema + relationship-graph check
corpus-verify-provenance --config _meta/corpus.yml   # snapshot hash + full-text containment/coverage
corpus-detect-changes --config _meta/corpus.yml      # re-fetch manifest URLs, report hash drift
```

(All three are console entry points installed from corpus-toolkit — see
`requirements.txt` — not local `src/` scripts.)

At corpus scale both validators support `--changed [ref]` (verify only files in the git
diff vs `ref`, default merge-base with `origin/main`) and `-j N` (parallel workers,
default all CPUs). CI uses `--changed` on PRs **and on push-to-main** (the reusable workflow branches on
`github.event_name`; the push arm passes `--changed "${{ github.event.before }}"`). Only
the nightly cron and manual dispatch validate the full corpus — so between a merge and
08:00 UTC, anything the diff did not touch is unverified. The relationship-resolution universe in `--changed` mode is read from
`_meta/graph.json`'s nodes, so scoped PR runs still resolve targets against the whole corpus.

Dependencies: `pip install -r requirements.txt` (installs corpus-toolkit, pinned in
that file, plus pyyaml/jsonschema for the local scripts under `src/`).
