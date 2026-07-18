# Skill: document discovery & intake

A spec-driven, human-gated pipeline for bringing a document into the repository. Agents
follow this checklist exactly; the hard content rules in [AGENTS.md](../../AGENTS.md)
apply throughout.

## Phase 0 — Discover (agent proposes; human vets the LIST first)

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
   `_meta/source-manifest.yml`.
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
   state servers stamp different bytes on every download.
3. Copy the matching template from `_meta/templates/`; name the file by its citation slug
   (`das-107-004-052.md`, `oar-125-800-0020.md`, `ors-276A.300.md`).
4. Transcribe header metadata (effective/reviewed dates, version string) exactly as
   printed in the source.
5. Write the body: every statement labeled `[VERBATIM]` (exact quote) or `[SUMMARY]`
   (paraphrase under a heading tied to a cited section). If uncertain, `TODO: verify`.
6. Populate `relationships`; update the directory `_index.md`, `llms.txt`, and the
   knowledge body `CHANGELOG.md` (`Added`).

## Phase 3 — Verify & merge (REVIEW GATE #2)

1. Run locally: `python3 src/validate_frontmatter.py && python3 src/verify_provenance.py`.
2. Open the PR; complete the checklist in the PR template.
3. A CODEOWNER for the knowledge body reviews against the source and merges.
4. Commits carry `Assisted-by: <agent> (supervised|autonomous)` trailers.
