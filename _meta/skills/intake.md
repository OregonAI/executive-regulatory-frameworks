# Skill: document discovery & intake

A spec-driven, human-gated pipeline for bringing a document into the repository. Agents
follow this checklist exactly; the hard content rules in [AGENTS.md](../../AGENTS.md)
apply throughout.

## Phase 0 — Discover (agent proposes; human vets the LIST first)

0. **Check the coverage catalogs first**: `_meta/catalog/{ors,oar,oam,das-policies}.yml`
   are discovery/backlog maps built 2026-07-18 — every known ORS section, OAR division,
   OAM document, and DAS policy in scope, each flagged `ingested` or `not_ingested`. Pick
   candidates from there before doing fresh discovery, and update the relevant catalog
   entry's `status` (and add a `path`) once a document is ingested. The DAS policy and OAR
   division-level catalogs are best-effort (JS-rendered source pages have no public
   sitemap) — verify a candidate still exists and get its real title before ingesting;
   never trust a `(title TBD)` catalog entry as ground truth.
1. Seed from the authoritative index pages:
   - DAS policies: https://www.oregon.gov/das/Pages/policies.aspx
   - OARD single rules (works with plain fetch): https://secure.sos.state.or.us/oard/view.action?ruleNumber=XXX-XXX-XXXX
     (OARD chapter/division listing pages render via JavaScript and return empty shells to
     curl — use the per-rule URL, or oregon.public.law for discovery. DAS = chapter 125;
     State CIO = chapter 128, incl. Division 30 State Information Security, renumbered
     from 125-800 effective 5/1/2026.)
   - ORS chapter HTML: https://www.oregonlegislature.gov/bills_laws/ors/ors276A.html
     (pattern: orsNNN.html; windows-1252 encoded)
   - EIS/CSS standards: https://www.oregon.gov/eis/cyber-security-services/pages/guidance-for-state-agencies.aspx
2. Produce a **candidate source manifest**: for each document — citation, title, URL,
   doc_type, why-relevant, what-it-references. Submit as a PR editing
   the matching `_meta/sources/<group>.yml` update group.
3. **Follow outbound references**: when a policy points to a non-policy document (e.g.,
   107-004-052 → Statewide IT Control Standards), add that document as a candidate too.
4. **REVIEW GATE #1** — a maintainer approves/prunes the manifest PR. No content may be
   ingested for a source that is not in the approved manifest.

## Phase 1 — Spec & plan (per approved document)

Open an *intake request* issue capturing: which sections matter, the verbatim-vs-summary
policy for this document, and which relationships to assert. Draft the ingestion plan in
the issue.

## Phase 2 — Ingest (agent implements under supervision)

1. Fetch the pinned `url`; save the raw file as `_meta/snapshots/<id>.<ext>` and (for
   PDFs) an extracted text copy `_meta/snapshots/<id>.txt` (`pdftotext -layout`).
2. Record `retrieved` (ISO date) and `source_sha256` — the **content hash** computed by
   `content_hash()` in `src/repo_lib.py` (sha256 of normalized extracted text; raw-byte
   hash only for image-only sources). Never hash raw bytes of PDFs/HTML directly: several
   state servers stamp different bytes on every download. **Always commit the `.txt`
   extraction alongside the `.pdf`/`.html` snapshot** — CI verifies against that
   committed text via `hash_snapshot()`, never by re-running `pdftotext` at verification
   time, because poppler's output can differ by version across machines.
3. Copy the matching template from `_meta/templates/`; name the file by its citation slug
   (`das-107-004-052.md`, `oar-125-800-0020.md`, `ors-276A.300.md`). Place it via
   `output_dir_for(doc_type, agency)` in `src/ingest_lib.py` (AGENTS.md "Directory
   routing" has the full table) — don't hand-type the target directory; a
   procedure (`doc_type: procedure`, filename ends `_pr`) belongs in
   `agencies/<agency>/procedures/`, never `.../policies/`. `validate_frontmatter.py`
   will hard-fail CI if this is wrong, but getting it right the first time saves the
   round trip.
4. Transcribe header metadata (effective/reviewed dates, version string) exactly as
   printed in the source.
5. Write the body per the full-text-first policy (AGENTS.md Content policy): the
   COMPLETE source text under `## Full text` (conversion rules in the templates);
   curator content only under `## At a glance` / `## Curator notes` /
   `## Cross-references`. Third-party sources: summary + link only. If the source
   cannot be cleanly parsed, insert `<!-- TODO: human verification required -->` and stop.
6. Run `python3 src/link_graph.py` — relationship edges are derived mechanically from
   the document's authority citations (add hand-authored edges only for connections the
   citations don't capture); update the directory `_index.md`, `llms.txt`, and the
   knowledge body `CHANGELOG.md` (`Added`). Then run `python3 src/review_queue.py` — a
   rule/policy/procedure/standard that comes out with zero relationship edges is flagged
   under "Unlinked rules/policies/procedures/standards" in `REVIEW.md`; check the
   source's authority/reference text before merging.

## Phase 3 — Verify & merge (REVIEW GATE #2)

1. Run locally: `python3 src/validate_frontmatter.py && python3 src/verify_provenance.py`.
2. Open the PR; complete the checklist in the PR template.
3. A CODEOWNER for the knowledge body reviews against the source and merges.
4. Commits carry `Assisted-by: <agent> (supervised|autonomous)` trailers.
