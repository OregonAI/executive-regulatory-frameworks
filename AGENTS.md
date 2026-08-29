# AGENTS.md — Canonical agent guide

This repository is a **non-authoritative**, AI-agent-friendly knowledge base of Oregon
executive-branch statutes, rules, policies, and standards (DAS pilot). Read this file
before doing anything else in the repo.

## What this repo is not

It is **not** the official text of Oregon law or policy. Never present its contents as
authoritative. Every answer you derive from it should cite the document's `source_url`.

## The overriding rule: could not check is never reported as is not there

**Not having been able to determine something is never written down, printed, or returned as
having determined it is absent.** This outranks every other rule in this file and every
convention in the codebase. When the two conflict, this wins.

It applies to the same substitution in all its forms:

- A fetch that failed, a file that could not be read, a parse that raised — none of these is
  a measurement of zero. A source that could not be fetched is a source that was **not
  compared**, never a source that **did not change**.
- A field a scraper's response did not carry is not a field the upstream lacks. A `get()`
  that returns nothing cannot tell "absent upstream" from "not in this response".
- A record nobody has looked at yet is not a record reviewed and found empty. Ingestion
  writes `last_verified` and `verified_by` as empty strings for exactly this reason: an
  empty string says *unverified*, and any value there would be a verification nobody did.
- A count that omits a category because it happened to be zero cannot be told apart from a
  count that was never asked. **Name every category, the zeroes included.**
- A gate that could not run has not passed. A skipped check is not a green one.

**What to do instead.** Report the state you are actually in, with a name for it — the
corpus's published reports carry a literal `## Could not check` section for this. An absence
may be asserted only when it was **measured**: a search that ran to completion and found
none, cited as such. "Could not check" and "found none" are different findings, and this
repository never lets the first be served as the second.

This is why an unfixed defect gets an issue rather than silence (see *Found a bug you are
not fixing right now?*), and why a summary may never stand in for text nobody read (see
*Content policy*). Both are this rule applied to a particular surface.

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
| `constitutional_provision` | `constitution/` |
| `statute` | `statutes/` |
| `rule` | `rules/` |
| `executive_order` | `executive-orders/` |
| `external_reference` | `external-references/` |
| `policy` | `agencies/<agency>/policies/` |
| `procedure` | `agencies/<agency>/procedures/` (filename ends `_pr`) |
| `manual` | `agencies/<agency>/accounting-manual/` |
| `standard` | `agencies/<agency>/standards/` |
| `schedule` | `agencies/<agency>/schedules/` |

`constitutional_provision` is one section of the Oregon Constitution (ADR 0005). It is a
doc_type this corpus DECLARES rather than one the shared schema ships — `_meta/corpus.yml`'s
`schema.doc_types` block adds it to the frontmatter enum and marks it `verbatim: true`, which
is what puts it under the same line-by-line provenance verification as a statute. The WHOLE
document is mirrored (#194 landed Article VI, #195 the rest): 339 sections across the 40
article headings the page prints, and 32 sections cataloged and not published because the
page prints them as a leadline and a repeal bracket with no text between them.

AN ARTICLE'S IDENTITY CARRIES ITS PARENTHETICAL, because that is how Oregon cites it. The
page prints ARTICLE VII twice — `(Amended)` and `(Original)`, both operative and both cited
by Oregon courts — so `Or. Const. Art. VII (Amended), sec. 1` and `Or. Const. Art. VII
(Original), sec. 1` are TWO documents (`orconst-art-vii-amended-sec-1`,
`orconst-art-vii-original-sec-1`) and `Or. Const. Art. VII, sec. 1` resolves to neither and
says which two it could have meant. `XI-F(1)` and `XI-F(2)` are two designations, not one
printed twice, and their slugs are `xi-f-1` and `xi-f-2`. An article with no parenthetical
keeps the slug it always had, which is why Article VI's ten documents did not move.

WHAT A CONSTITUTIONAL CITATION LOOKS LIKE IS DECLARED ONCE, in `repo_lib`'s
`ORCONST_ARTICLE_TOKEN` and `ORCONST_SECTION_TOKEN`. The `or-const` citation scheme
(`src/citation_schemes.py`) and the `constitution` form in `AUTHORITY_FORMS`
(`src/catalog_agencies.py`) both interpolate them, so the resolver and the enabling-authority
allowlist cannot answer that question differently — they used to, in both directions.
`citation_schemes.article_form_disagreements()` gates it over every designation the catalog
holds and `--selftest` proves the gate can fail. Same shape as `CADENCES` versus the `recheck`
enum (#193).

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

## Found a defect? Fix it. Filing an issue is the exception, and it has a cost.

**The default is to fix it in the change you are already making.** You are in the file with
the context loaded, which is the cheapest this fix will ever be. Filing an issue converts a
ten-minute fix into a future session that has to rebuild everything you currently know.

**Open an issue only when one of these is true:**

1. **It needs a decision you are not allowed to make** — a judgement about what the corpus
   means, a trade-off with a real cost, anything a grilling session would have put to the
   operator. Label it `ready-for-human`.
2. **It is large enough to need its own review** — if fixing it would make this change's diff
   hard for a reviewer to follow, it is separate work.
3. **It is in a file this change does not touch**, and reaching into it would widen the change
   beyond what its own review covers.

**If none of those is true, fix it now.** "I noticed it while doing something else" is not a
reason to defer; it is the reason it is cheap.

### An issue must name its trigger

Every issue states **what would make this matter** — the condition under which it stops being
latent. "Nothing currently escapes this" with no trigger is not a ticket. It is a comment at
the site, where the next person who can act on it will actually be standing.

**A comment in the code beats a ticket in a queue** whenever the person who would fix it is
the next person reading that code. Reserve the queue for work that has to be found by someone
who is *not* already in that file.

### Review findings are not issues

A code-review finding applied in the same change is already tracked by that review. Do not
also file it. An issue opened and closed within the hour adds a row to the backlog and tells
nobody anything.

### At most two issues per task

If you found more than two things worth another person's attention, the finding is that this
module needs work — and that is **one** issue naming the pattern, not five naming instances.
Ranking is the point: the third-most-important thing you noticed is usually a comment.

### Why this replaced "open an issue, period"

Measured in `executive-regulatory-frameworks` on 2026-08-29: **49 issues opened in two days,
20 closed, the backlog 19 → 48.** Of the 20 closures, 8 were review findings filed and fixed
inside the same hour — tracked already, and pure ceremony. Of the 29 left open, 3 needed a
human decision and roughly 12 were things the agent could have fixed while it was already in
the file.

The old rule's justification was that "nobody greps closed PRs six months later." True — and
nobody greps a 48-issue backlog either. A backlog nobody works is not a record; it is where a
defect goes to be forgotten with a clear conscience, and it buries the few issues that
genuinely need a person.

These all count as a defect, not just crashes:

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
  one of those rules can fail. Every row carries an `oar_name` — the OAR name (CONTEXT.md),
  which is the string OAR-derived joins match on, distinct from `raw_index_name`'s
  abbreviated spelling — landed by `src/expand_oar_name.py` and written from then on by
  `--refresh`. THE IN-REPO CONSUMERS HAVE MOVED (#187): the two OAR-derived joins match
  `oar_name` — `enrich_oar.py`, which stamps `issuing_body` into 36,953 rule documents, and
  `catalog_oar.py`, which discovers chapters — while agency SEARCH (the command line's
  `find()` and the MCP server's `agency_profile`) spans every name a body is known by:
  statutory name, OAR name and curated aliases, so promoting `name` cannot make a body
  unfindable by the name a reader knows. Every remaining read of a registry `name` is
  classified where it sits, as JOIN, DISPLAY or MACHINERY, and
  `python3 src/name_readers.py --check` (CI, every PR) refuses one that is not.
  A RULE'S LEGAL STATUS HAS ONE WRITER, `legal_status.resolve()` (#228, ADR 0006). The
  document's `status` field is corpus-toolkit's `current | superseded | repealed | proposed |
  draft` and it is a claim about Oregon law, so it is not the same field as the OAR catalog's
  `rules[].status`, which is INGEST status and says only whether this mirror holds a copy
  (CONTEXT.md keeps an entry for each). It had two writers: `ingest_oar.py` hardcoded
  `status: current` on every rule it created and `enrich_oar.py` derived the field from the
  rule's own History line, so an automatic re-ingest of an amended rule would have resurrected
  one the Bulletin marked repealed. Both are readers now. The order is fixed: a status the
  Bulletin set (the OAR catalog row's `legal_status`), then a repeal in the rule's own served
  History, then what the document already says — the state **39** rules are in, because OARD
  prints no History line inside them and "read no history" is not "read one that is not a
  repeal" — then `current`, which a fresh ingest may assert ONLY where nothing better is
  known. Any site in `src/` that writes one of those five words must say, where it sits, which
  it is — WRITER, READER, NOT-A-RULE or NOT-A-LEGAL-STATUS — and
  `python3 src/legal_status.py --check` (CI, every PR) fails on an unmarked one, on a second
  module marked WRITER, on a "reader" that kept a literal of its own, on either field named
  `status` holding the other's vocabulary across the 42,615 catalog rule entries, and on a
  document that stopped agreeing with the catalog row it was stamped from. `--selftest` proves
  every one of those can fail, the two mutations included.
  A REPEALED OR SUSPENDED RULE IS MARKED, NEVER DELETED (#229, ADR 0006). The August 2026
  bulletin filed **66 repeals and 34 suspensions** against rules this corpus holds, and every
  one was served `current`. `python3 src/legal_status.py --mark` derives them from
  `_meta/bulletin-worklist.yml` onto the catalog row — `legal_status`, `legal_status_action`
  and `legal_status_notice`, none of which may appear without the others — and
  `python3 src/enrich_oar.py` stamps the documents from there, so the catalog writes and the
  document reads. **Nothing is deleted**: path, ingest status and file are untouched, because
  this corpus mirrors ORS sections that cite administrative rules and a deleted rule breaks
  every citation pointing at it. **A SUSPENSION IS NOT A REPEAL** — the shared schema enum has
  one word for a loss of force and it means a permanent one, so a suspension is stamped
  `superseded` (the strongest true thing the enum can say) and `legal_status_action` carries
  the part it cannot — the gap in the shared enum is filed as corpus-toolkit#159 rather
  than papered over. `--check` also reads the worklist and fails if a filed repeal or
  suspension is not recorded, which is the only rule here that deleting information cannot
  satisfy. The 100 rules are listed in REVIEW.md, because a claim about legal force reaches a
  person rather than being applied silently.
  THE MONTHLY REPORT FILES ONE ISSUE, AND IT RUNS BESIDE HASHING (#231, ADR 0006).
  `python3 src/bulletin_report.py` reads the committed worklist and the drift run's
  `changed-sources.tsv` and prints ONE issue's worth of finding — counts by action and by
  corpus state, every filing the reader could not open, every renumber with no stated
  destination, all 121 rules missing from a chapter this corpus mirrors BY NUMBER, and the
  disagreement between the two signals. `.github/workflows/bulletin-report.yml` runs it on
  the 6th of each month — the Bulletin's first BUSINESS day is as late as the 4th (the 1st
  a Saturday, the 2nd a Sunday, the 3rd a Monday holiday) — and produces its own hash
  observation in a step before the report. A MONTH NOBODY HAS RE-READ IS ITS LOUDEST
  FINDING: the module reads the COMMITTED worklist and holds `contents: read`, so it cannot
  fetch a new bulletin, and `months_unread()` counts the ones published since and puts the
  count at the top of the issue — without it the September run rebuilds August's report,
  matches August's issue title and exits 0 having filed nothing.
  ONE ISSUE PER RUN, NEVER ONE PER RULE: 549 rule
  actions against a 25-issue cap makes per-rule filing a way of reporting 25 of them
  (corpus-toolkit#67). A RUN WITH NOTHING TO REPORT FILES NO ISSUE, and `--check` fires that
  rule in BOTH directions — a `should_file` that always says no satisfies the criterion by
  reporting nothing ever. HASHING IS NOT REPLACED: ADR 0006 keeps it for the one job it
  alone can do, so `hash-drift-still-runs` fails if `scheduled.yml` stops hashing the `oar`
  group. THE LOUD CASE IS GUARDED. `moved with no filing` is the finding this series exists
  for and it is exactly what a stale baseline manufactures in bulk — #244 is doing it now —
  so when more than a fifth of a group's compared sources move together the run reports ONE
  GROUP-WIDE MOVE, says how many rules it declined to name, and emits no per-rule claim
  (corpus-toolkit's ADR 0010, one level up). And THE TWO SIGNALS DID NOT OVERLAP AT #247's
  WRITING: the manifest then watched 484 rule pages in four chapters while the August 2026
  bulletin named 534 rules in 35 other chapters, overlap ZERO, so every rule that bulletin
  named was reported as NOT CHECKED rather than as one whose hash held still (#247). The
  manifest has since grown (#306 fixed CONTEXT.md's own copy of this figure after finding
  it stale the same way) — the CURRENT watched/named/overlap counts are gated against the
  measurement, not restated by hand here a second time to go stale again, and live in
  CONTEXT.md's *Hash observation* entry. This module ACTS
  OUTWARD and nothing else in the series does: it holds `contents: read`, writes no file,
  pushes no commit, files at most one issue, is idempotent by title, and files nothing at
  all unless `--file-issue` is passed — every command typed by hand is a dry run.
  `name` IS THE STATUTORY NAME since #168 (ADR 0003), and every row states in `name_basis`
  whether it actually holds one: `enabling-authority` — read off the body's enabling
  authority by a human, written only by `src/link_enabling_authority.py`'s `STATUTORY_NAMES`
  and resolved by `--check` against the mirrored text of the section it cites — or
  `unverified-oar-title`, which says nobody has established one and `name` still holds the
  OAR chapter title, unchanged. 5 of 190 rows are established and 185 are not, and
  `--check` prints both counts on every run: "established" and "not yet established" may
  never be the same state. `statutory-name-basis` fails a row claiming the first with no
  enabling authority behind it, and fails a row claiming the second whose `name` is not its
  `oar_name` — which is what makes "no row's name was blanked by the promotion" a checkable
  claim. The field is neither scraped nor curated but `PER_ROW`, because the row's own basis
  decides what `--refresh` does to it: an established name is carried across by
  `preserve_name()`, an unverified one is rebuilt from the chapter page.
  `_meta/corpus.yml` declares `plugins.issuing_body_name_fields: [name, oar_name, aliases]`
  (corpus-toolkit>=1.29.0), without which `issuing_body_profile` matches `name` alone and a
  fully promoted registry leaves 190 of 190 bodies unfindable by their OAR name.
  Every row also carries `relations` (CONTEXT.md), and since #174 it is the ONLY place a
  body's placement under another is recorded — `parent_slug` is retired, and the allowlist
  in `FIELDS` refuses it if it comes back. Each entry names the
  body this one is under, the source whose evidence places it there (`oar-index`,
  `statute`, `das`, or `registry` for a placement this registry recorded by hand — the one
  manual child, whose body the rules index does not carry), a kind, and — where one has
  been established — the authority (ADR 0004). The `oar-index` entries are written by
  `--refresh` from the index tree (`set_index_relations`); everything else is curation the
  refresh carries across. HIERARCHY IS WALKED IN ONE PLACE,
  `catalog_agencies.root_body()` / `parent_targets()`, which `build_policy_gap.py` and
  `build_agency_graph.py` both use: a body whose sources place it under MORE THAN ONE parent
  is not rolled up at all and is reported, because ADR 0003 keeps that disagreement and a
  rollup that picked one reading would publish it as the answer. Nothing derives hierarchy
  by splitting the compound `Parent, Child` name — `name_readers.py --check` refuses an
  unclassified site that takes a registry name apart on a comma.
  `parent_chapter` survives as a different fact (the parent's OAR chapter, scraped from the
  same tree) and `parent-agrees` states that it may not disagree with the body the relations
  name. THE KIND IS DERIVED AND NEVER GUESSED, by `python3
  src/derive_relation_kinds.py --apply`, its single writer, into `administered_by` or
  `undetermined` — never `part_of` (ADR 0004). Every derived kind also records the
  `basis` it came from, which is NOT the same fact as the source — the source says who
  places the body there, the basis says what settled the kind — and the two bases are
  different strengths: `proposed-enabling-authority`, a candidate in the review sheet that
  NOBODY HAS READ, or `reviewed-enabling-authority`, once the review lands (ADR 0004's
  amendment records that deviation). The split between kinds and the split between bases
  both move as scrapes and reviews land, so neither is pinned here — `relation_census()`
  prints both live, on every `catalog_agencies.py --check` run, rather than a figure this
  guide would leave to go stale. NO kind is derived from the ABSENCE of a candidate: the
  rest stay `undetermined` because a matcher finding nothing is a statement about the
  matcher, and that list has already been wrong for 55 bodies. `--check`
  REPORTS the census — kinds, sources and bases, zeroes included — on every run, refuses a
  kind with no basis, an `administered_by` citing no authority, a `part_of` relation that
  cites one, and a `part_of` row carrying an enabling authority of its own;
  `derive_relation_kinds.py --check` compares the registry with the derivation in BOTH
  directions. The citation a derived relation carries is the section that CONSTITUTES the
  body (ORS 576.062, the evidence its kind rests on), never the one the department's
  administration runs on (ORS 576.066) — nobody here has read the latter, and both bases are
  named for an *enabling authority* to say which of the two is in the key. A derived kind survives `--refresh` because `relations`
  merges per KEY as well as per entry: the scrape rebuilds the placement and
  `DECISION_KEYS` ride across onto it. A body may hold several relations, because the OAR index, DAS and statute may place
  it under different parents and ADR 0003 keeps that disagreement. The field is the first
  with a MIXED ORIGIN, declared `MERGED` rather than SCRAPED or CURATED: `--refresh`
  regenerates the `oar-index` entries from the index tree and `preserve_relations()`
  carries every other entry across ENTRY BY ENTRY, and `--check`'s `relation-origin` rule
  refuses any other declaration of it — declaring the whole field SCRAPED would drop
  curated entries behind a rule that passed, which `note` used to risk too until #178 split
  it: `note` (SCRAPED) now holds only the three sentences `cmd_refresh()` itself writes, and
  `curator_note` (CURATED) holds hand-typed prose about a row, carried across a refresh by
  `CURATED_KEYS` on any row and needing none of `manual`'s whole-row protection.
  `catalog_agencies.py --check`'s `note-scrape-shape` refuses a `note` that is not one of
  those three sentences. THE FILE'S OWN TOP-LEVEL `note` (the prose above `organizations`,
  read by three sibling corpora) is a THIRD, unrelated field of the same name, and it
  drifted stale — measured across its own git history: 669 characters naming 4 of the
  then-14 row fields for a month, then two more revisions that each still fell short
  (4,299 naming 9 of 13, then 5,260 naming 11 of 15), then #178 grew the field set to 16
  with `curator_note` while the note stayed at 5,260 — before anything compared it
  against `FIELDS` (#185) — `--check`'s
  `note-covers-fields` now refuses a registry whose top-level `note` does not name every
  field `FIELDS` declares, derived from the declaration itself rather than a second list.
  Naming every field is not the same as AGREEING with what `cmd_refresh()` would write, and
  #185's own follow-up commit added a second rule for that, `note-agrees-with-refresh`,
  comparing the committed `note` byte-for-byte against `REGISTRY_NOTE` (the one place that
  literal string lives, read by `cmd_refresh()`). AC4 of #185 asked, further, that the note
  "not be regenerated wholesale on every write" — reasoning by analogy to `catalog_oar.py`'s
  own top-level note, which genuinely does carry hand-appended curator prose an unconditional
  rewrite would destroy (4,425 committed characters today against an `INITIAL_NOTE` of
  1,875, #241). #278 tested that analogy against this registry's own history rather than
  assuming it transferred, and found it does not: every one of the 23 commits that have ever
  touched `agencies.yml` shows the committed top-level `note` never exceeding its era's
  module literal, so no curator prose has ever lived in this field — the two rows people
  point to when describing "curator prose on the note" are `curator_note` entries (#178,
  CONTEXT.md), a different field entirely. AC4 is therefore closed as OUT OF SCOPE rather
  than given a preservation mechanism nothing has ever needed: `note-agrees-with-refresh`
  stays exactly as #185 left it, `cmd_refresh()` keeps writing `REGISTRY_NOTE` wholesale, and
  the full reasoning (including the walked commit history) lives at its extraction site in
  `catalog_agencies.py`, above `REGISTRY_NOTE`, rather than restated here a second time.
  Neither `note-covers-fields` nor `note-agrees-with-refresh` reads a NUMBER inside the
  note's prose, only whether every field is named and whether the two copies match each
  other — so a hand-typed count beside a field name (the "null on N of the M chapterless
  rows" sentence) could go stale on its own, in `REGISTRY_NOTE` itself, and both rules
  would still pass (#281's own code review: it did, surviving a whitespace-only re-wrap of
  that exact sentence in the commit that made it wrong). `note-numbers-current` closes that
  gap: it extracts the note's own chapterless claim and checks it against
  `chapterless_source_url_census()`, computed from the committed rows the same run.
  The DAS agency number (CONTEXT.md) lives in `das_agency_number`, written by
  `python3 src/link_budget_codes.py` from the hand-reviewed table in that file, whose
  `--check` verifies the registry against that table. The deprecated `budget_agency_code`
  holds the same number for one more cycle (ADR 0003, removed by #177); that the two agree
  is a rule of the registry's contract, so it is `catalog_agencies.py --check` that fails a
  row where they disagree or where only one of them is present.
  The enabling authority (CONTEXT.md) lives in `enabling_authority`, written by
  `python3 src/link_enabling_authority.py --apply` from the hand-reviewed `MAPPED` /
  `UNMAPPED` tables in that file — its single writer, the same arrangement the DAS number
  has — and gated by that script's `--check` (CI, every PR): every citation is resolved
  against the mirrored ORS, executive orders and — since #196 — the mirrored Oregon
  Constitution, and the registry is compared with the table in BOTH directions, so a row
  that acquired an authority any other way fails. All three of ADR 0003's forms now resolve
  against a document; none is taken on form alone. A constitutional citation that resolves
  to nothing is told WHICH nothing it hit — the page prints no such article, the article
  carries no sections, the page prints no such section in it, the section is printed and
  this corpus published no text for it (ADR 0005's 32 `history-only` sections), or the
  numeral names two operative articles and choosing one would be a guess. `--propose`
  writes a review sheet of candidates and never touches the registry; `--selftest` proves
  every one of those rules can fail. An ABSENT `enabling_authority` means nobody has
  reviewed that body yet — never that the body has none; a reviewed body with no separate
  authority carries `none: ` and the reason.
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
  `Source-Updated` entry in the affected body's `CHANGELOG.md`. A group's `recheck` cadence
  is declared ONCE, in that script's `CADENCES` table with the interval it means; the
  `recheck` enum in `_meta/schema/source-group.schema.json` is DERIVED from it
  (`--sync-schema` writes it, `--check` gates it in CI) so a cadence cannot exist on one side
  only, and `--selftest` proves every one of those rules can fail. `--check` also validates
  every group in `_meta/sources/` against `source-group.schema.json` (#199), prints the
  count checked, and FAILS — rather than passing on a silent `0 of 19` — if `jsonschema` is
  not importable; `seed_oar_watch.py` calls the same function rather than running a second
  copy. A group declaring a cadence nobody declared is reported against the group — by
  `--check`, and by `--due` as `UNKNOWN CADENCE`, which is neither DUE nor ok.
  `even_year_general_election` (765 days) is the ballot-measure cycle and is deliberately
  NOT `biennial`, which is the odd-year legislative session two years out of phase with it
  (ADR 0005's amendment). A cadence also declares — opt-in, per cadence, via
  `Cadence.phase_capable` — whether it ADMITS a phase (#198): a group may state
  `recheck_phase`, the date its own cycle is known to land on, so two groups sharing an
  interval but on opposite halves of it are distinguishable, and `due_state()` schedules a
  phased group against the next occurrence of that anchor rather than raw days since
  `last_checked`. Only `biennial` opted in; `even_year_general_election` deliberately did
  not become `biennial` + a phase — the 765-day interval is a different number from
  `biennial`'s 730, not the same interval with a phase overlaid (CADENCES's own comment
  records why). A group declaring `recheck_phase` on a cadence nothing marked
  phase-capable is reported — by `--check`'s `group-phase` rule and by `--due` as
  `PHASE NOT ADMITTED`; a `recheck_phase` nothing can parse as `YYYY-MM-DD` is reported by
  `--due` as `UNREADABLE PHASE`. Both are neither DUE nor ok, same discipline as
  `UNKNOWN CADENCE`. The
  `constitution` group is ONE source and ONE sha256 for the whole document, so a `CHANGED`
  line there says only that something moved: `python3 src/ingest_constitution.py --drift
  PAGE` is the diff that names WHICH sections' text moved, says nothing about the ones that
  did not, and reports a section it could not slice out of the new page as COULD NOT CHECK
  rather than as one that was deleted (#197).
- **Every PR**: run `corpus-validate-frontmatter --config _meta/corpus.yml` and
  `corpus-verify-provenance --config _meta/corpus.yml` locally; complete the PR checklist; update the
  relevant `CHANGELOG.md` and, for new documents, the directory `_index.md`, and run
  `python3 src/build_llms.py` (llms.txt regenerates itself from the corpus).

## Commit conventions

Record agent authorship with commit trailers, e.g.:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_...
```

(This replaces an earlier documented convention, `Assisted-by: Claude Code (supervised)`,
which none of this branch's or main's recent commits carry — a document describing a
convention nobody follows is a claim that stopped being true, and this is the actual one.)

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

## Before pushing: run every generated-view gate locally (#318)

```bash
python3 src/check_all.py            # every gate the workflow runs, one command, no push
python3 src/check_all.py --list     # what would run, without running it
```

Run this **before pushing, by default** — not only when you suspect something broke.

WHY. **GitHub stops a job at its first failing step.** `generated-views` is a fan-in over
five `generated-views-shard-N` jobs (#268), and each shard can hold a dozen-plus gates —
but CI only ever reports exactly one failure per shard, however many it actually holds. `main`
went red three times from a single ingest (#238) because of this: #302 fixed the views that
ingest regenerated, by hand; #309 fixed five more once CI reported them, one shard-failure
at a time; #318 found CI naming three more and a manual sweep of the workflow YAML turning
up two beyond that. Each round only ever surfaced the *next* layer — fixing shard-2's
reported failure just let shard-2 run far enough to hit its *next* one, on the *next* push.
**A push that turns one shard green can still be hiding three more failures in that same
shard**, invisible until the next round-trip to CI.

`src/check_all.py` is the local mirror of the entire sweep: it derives its gate list from
`src/shard_generated_views.py` (never a second parse of the workflow YAML — see that
module's own docstring) and runs every gate in every shard, PLUS `generated-views-nightly`'s
(the schedule/workflow_dispatch-only job, out of scope for that module's PR-tier manifest by
design but still a job CI runs — #329), without stopping at the first failure, so **all** of
them are named together instead of one shard-failure at a time across however many pushes it
takes to surface the rest. A gate that could not even be run (missing command, timeout) is
reported as its own status, not folded into a pass or a silent skip.
