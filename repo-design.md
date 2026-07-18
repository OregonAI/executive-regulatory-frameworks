# Scaffolding an AI-Agent-Friendly Oregon Executive-Branch Knowledge Repository for DAS

## TL;DR
- **Build a single public GitHub repo organized by *authority tier* (statute → rule → policy → standard → referenced external doc) and, within the policy/standard tiers, by *agency* — starting with DAS — using per-document Markdown files that each carry a strict YAML provenance header (source URL, authority level, effective/retrieval dates, version, status, relationships).** Pair it with an `AGENTS.md` canonical agent guide, a machine-readable `llms.txt` index, per-knowledge-body `CHANGELOG.md` files, and a spec-driven, human-reviewed intake/update pipeline enforced by GitHub Actions.
- **The law itself is safe to republish** — Oregon Administrative Rules and statutes are uncopyrightable "government edicts," and Oregon's Legislative Counsel Committee voted unanimously on June 19, 2008 that it "will not assert copyright on the Oregon Revised Statutes" — but the repo must loudly, repeatedly disclaim that it is **unofficial** and always link back to the authoritative source, because Oregon's own databases warn their online text "is not the official text of Oregon law." [Oregon Legislature](https://www.oregonlegislature.gov/bills_laws/pages/ors.aspx)
- **Anti-fabrication is a workflow, not a wish**: require verbatim quotes to be diffable against a pinned source, forbid AI-generated substance without a cited source, gate every change through PR review with CODEOWNERS, and run automated checks (frontmatter schema validation, link checking, quote/provenance verification, upstream change detection) so the repo stays accurate and current.

## Key Findings

### The Oregon legal/policy hierarchy the repo must model
Oregon's executive-branch "rules and processes" are not one corpus but a layered stack, each layer published by a different body on a different cadence and with different versioning conventions. Mirroring this hierarchy is the single most important design decision, because it drives directory structure, the `authority_level` metadata field, and the update cadence.

1. **Oregon Revised Statutes (ORS)** — the codified state laws, enacted by the Legislative Assembly, published by the Legislative Counsel Committee at `oregonlegislature.gov/bills_laws`. Structure: **Title → Chapter → Section** (e.g., ORS 276A.300; the number before the decimal is the chapter, after is the section). Published as a **new edition every two years** (odd-year sessions); the 2023 edition, 2025 edition, etc. The online database carries an explicit disclaimer (verbatim): *"The official text is the printed published copy of the Oregon Revised Statutes. The text in the database is not the official text of Oregon law… Users should verify the legal accuracy of all legal text against official sources of Oregon law."* The most relevant IT/administrative chapters for DAS include ORS 183 (Administrative Procedures Act), ORS 184 (Administrative Services Dept.), ORS 276A (Information Technology), ORS 291/293 (financial administration), and ORS 192 (public records).

2. **Oregon Administrative Rules (OAR)** — regulations with the force of law, adopted by agencies under ORS 183, compiled and published by the **Secretary of State's Administrative Rules Unit (Archives Division)** in the **Oregon Administrative Rules Database (OARD)** at `secure.sos.state.or.us/oard`. Structure: **Chapter (3 digits) → Division (3 digits) → Rule (4 digits)**, [Oregon Secretary of State](https://sos.oregon.gov/archives/administrative-rules/pages/oard-faq.aspx) e.g., 125-800-0020 (DAS is chapter 125; Division 800 is State Information Security). Each rule carries a **history section with Administrative Order Numbers (AONs)** [Oregon Secretary of State](https://sos.oregon.gov/archives/Pages/oregon_administrative_rules.aspx) — e.g., "DAS 8-2006, f. & cert. ef. 12-28-06" — which encode the filing agency, filing sequence, and year, plus filing and effective dates. The compilation is republished **annually** (reflecting rules effective as of the prior year's December Bulletin), and updated **monthly by the Oregon Bulletin**, published on the first business day of each month, which also carries notices of proposed rulemaking, Governor's Executive Orders, and Attorney General opinions.

3. **DAS statewide policies (the 107-xxx series and others)** — administrative policies (not law) that apply to executive-branch agencies, published as PDFs at `oregon.gov/das/Policies/`. Numbering encodes program area: e.g., **107-001-xxx** (general/records — public records management is 107-001-020), **107-004-xxx** (IT/information security — Cyber and Information Security is 107-004-052, Information Asset Classification is 107-004-050, Acceptable Use is 107-004-110, Cloud/Hosted Systems is 107-004-150), **107-011-xxx** (enterprise asset management/facilities), and HR series like **50-xxx**. Procedures use a `_PR` suffix (e.g., 107-004-052_PR). Each PDF carries **"Policy No / Effective / Reviewed" dates** in its header (e.g., 107-004-052 is Effective 2/17/2026, Reviewed 12/2/2025) [Oregon](https://www.oregon.gov/das/Policies/107-004-052.pdf) — the exact metadata the repo schema should capture. The DAS policy page groups policies by program area (Facilities; Fleet; HR; Information Technology and Security → Assets/General/Security; Procurement; Risk; Surplus) — a natural taxonomy for the repo.

4. **Oregon Accounting Manual (OAM)** — statewide financial policy published by the DAS Chief Financial Office / Office of the State Controller at `oregon.gov/das/financial/osc/pages/oam.aspx`. Structure: **Chapter.Part.Section** numbering (e.g., OAM 15.15.00), with suffixes `PO` (policy), `PR` (procedure), `FO` (form), `RF` (reference); each document states Effective date, Division, Authority (ORS + GASB references), and Applicability. The OSC publishes **track-changes versions** alongside current documents — a ready-made change signal.

5. **EIS Cyber Security Services statewide standards** — the *"documents outside of policy but still relevant"* the user named. EIS/CSS maintains, under authority of **ORS 276A.300**, the **Statewide Information and Cyber Security Standards** (the current set is aligned to NIST SP 800-53 Rev. 5 and mapped to the CIS Critical Security Controls; published January 2024 as "Statewide Information Technology (IT) Control Standards"), the **Statewide Information Security Plan** (dated 8/1/2018) and the **2023 Statewide Information Security Program Plan**. Policy 107-004-052 explicitly requires agencies to "comply with … statewide policies and security standards" [Oregon](https://www.oregon.gov/das/Policies/107-004-052.pdf) and says EIS "developed the Statewide Information Technology Control Standards which define baseline security controls." [Oregon](https://www.oregon.gov/das/Policies/107-004-052.pdf) This is the canonical example of a policy *pointing outward* to a non-policy document — the repo must represent that edge as a first-class relationship.

6. **Executive Orders** — issued by the Governor, published at `oregon.gov/gov` (EOs from 2003 to present are available), and also noticed in the Oregon Bulletin.

**DAS's own internal structure** (useful for the agency-scaling taxonomy): DAS is organized into the Chief Operating Office, Office of Strategic Initiatives and Enterprise Accountability, Chief Financial Office (with SARS, SFMS, OSC), Chief Human Resources Office, Enterprise Goods and Services (procurement, risk, publishing), Enterprise Asset Management (facilities, fleet, surplus), and **Enterprise Information Services (EIS)** [OLIS](https://olis.oregonlegislature.gov/liz/2025R1/Downloads/CommitteeMeetingDocument/296426) — which itself contains Cyber Security Services, Data Center Services, Data Governance and Transparency, Project Portfolio Performance, Shared Services, Strategy and Design, and Administrative Services. The State CIO leads EIS.

### The copyright/public-records picture is favorable — but "unofficial" disclaimers are mandatory
- **The text of laws and rules is not copyrightable.** Under the federal *government edicts doctrine* (U.S. Copyright Office *Compendium*, Third Ed., § 313.6(C)(2): "Edicts of government, such as judicial opinions, administrative rulings, legislative enactments, public ordinances, and similar official legal documents are not copyrightable for reasons of public policy … whether they are Federal, State, or local"), [Law.Resource.Org](https://law.resource.org/pub/edicts.html) confirmed and extended by *Georgia v. Public.Resource.Org, Inc.*, 590 U.S. 255 (2020) ("officials empowered to speak with the force of law cannot be the authors of — and therefore cannot copyright — the works they create in the course of their official duties"). [Supreme Court of the United States](https://www.supremecourt.gov/opinions/19pdf/18-1150_7m58.pdf) OAR text and ORS text fall squarely within this.
- **Oregon does not assert ORS copyright.** On June 19, 2008 the Legislative Counsel Committee [Resource](https://public.resource.org/oregon.gov/index.html) voted unanimously; the recorded resolution reads: *"RESOLVED: The Legislative Counsel Committee will not assert copyright on the Oregon Revised Statutes."* Its earlier (pre-2008) claim was narrow even then: per Legislative Counsel Dexter Johnson's April 7, 2008 letter to Justia's Tim Stanley, Oregon claimed no copyright in the "text of the law itself," only in "the arrangement and subject-matter compilation" — i.e., "the organizational structure, lead lines and that kind of thing," which it had copyrighted since 1953 (as reported by the *Washington Times*, Apr. 19, 2008). It never reached the statutory text.
- **The Secretary of State asserts no copyright on OAR text** in OARD. Annual *compilation* PDFs carry a boilerplate "Copyright … Office of the Secretary of State" [Oregon Secretary of State](https://secure.sos.state.or.us/oard/viewCompDocument.action;JSESSIONID_OARD=dis1feDKtuMawptE5fHy7v4pKbWIXw4iN9DGK8W_Wa7TsNBKCLvi!48253970?compDocRsn=1103) cover line, but this cannot lock up the underlying uncopyrightable rule text and is legally weak even as to compilation formatting.
- **DAS 107-series policy PDFs** carry no copyright notice or republication restriction; they are public records and are agency *policy* (not law). Excerpting and summarizing them for an informational, non-authoritative resource is a strong posture; the government-edicts doctrine does not automatically apply to policies, so rely on absence of restriction + public-records status + fair use.
- **Oregon's Open Data law (ORS 276A.356)** requires state-published data be available "without registration or license requirements or restrictions on the use." [Oregon Public Law](https://oregon.public.law/statutes/ors_276a.356) The general Oregon.gov Terms & Conditions contain an "as is"/indemnity disclaimer and a DMCA complaint process but **no blanket republication ban**; watch for *agency-specific sub-site* terms (e.g., PERS asserts "personal, non-commercial use only") [PERS](https://www.oregon.gov/pers/Pages/Terms-of-Use.aspx) when the repo later expands.
- **Mandatory mitigation:** Because Oregon's own databases warn that online text "is not the official text," [Oregon Legislature](https://www.oregonlegislature.gov/bills_laws/pages/ors.aspx) every document and the repo root must carry a conspicuous non-authoritative disclaimer and a link to the official source. This directly serves the user's requirement #2.

### AI-agent-friendly repo conventions (2025–2026 state of practice)
- **`AGENTS.md`** is the now-dominant, tool-agnostic "README for AI agents" placed at repo root (and optionally in subdirectories, closest-file-wins), read by GitHub Copilot, Claude Code/Claude, OpenAI Codex, Cursor, Gemini CLI and others. It is adopted by more than 60,000 GitHub repositories and, as of December 2025, is stewarded by the Linux Foundation's Agentic AI Foundation (alongside Anthropic's MCP and Block's Goose), with 28–30+ tools natively supporting it as of June 2026. This is the user's canonical agent guide. `CLAUDE.md` can coexist as a Claude-specific pointer that simply defers to `AGENTS.md`.
- **`llms.txt`** is a Markdown index file (H1 title, a blockquote summary, then `## ` sections of annotated links) that gives an LLM a curated map of the corpus. It was proposed by Jeremy Howard, co-founder of Answer.AI, on September 3, 2024; per the spec, *"We propose adding a /llms.txt markdown file to websites to provide LLM-friendly content. This file offers brief background information, guidance, and links to detailed markdown files."* Best practice is *curation over dumps*: models perform better with a focused index plus links than with a giant file. [llms-txt](https://llmstxt.org/) **Caveat:** llms.txt remains an unratified proposal — no W3C/IETF ratification and no confirmed normative adoption by OpenAI, Google, Anthropic or Perplexity as of mid-2026 — so treat it as a helpful convention, not a guaranteed-consumed standard. It is the machine-readable table of contents the user asked for (requirement #9).
- **YAML frontmatter** per Markdown file is the standard metadata carrier. Comparable law-as-Markdown projects (nickvido/us-code, timlabs/uscode, legalize-dev/legalize) all use per-file YAML frontmatter with title/chapter/section/**source URL** [GitHub](https://github.com/nickvido/us-code) and store each law as one Markdown file with git history providing diffs — a directly reusable pattern. `legalize` explicitly licenses "legislative content: public domain … repository structure, metadata, and tooling: MIT," a good licensing model.
- **Chunking/file-size:** one document (or one rule/one policy) per file keeps files inside LLM context windows and makes `git blame`/diffs meaningful; very large documents (e.g., the full IT Control Standards) should be split by control family with an index file.
- **Naming conventions:** stable, citation-aligned filenames (e.g., `oar-125-800-0020.md`, `das-107-004-052.md`, `ors-276A.300.md`) so agents and humans can predict paths.

### Changelog and upstream-change-detection practice
- **Keep a Changelog** (CHANGELOG.md, reverse-chronological, ISO dates, `Added/Changed/Deprecated/Removed/Fixed/Security` groupings, an `[Unreleased]` section) is the de-facto standard and is Markdown-native. The repo should keep one per knowledge body (requirement #8), plus adapt the change types to this domain (e.g., `Source-Updated`, `Superseded`, `Verified`).
- **Upstream change signals that exist today:** the **Oregon Bulletin** (monthly, first business day) for OAR/EO changes; the **biennial ORS edition** cycle; **OAM track-changes** postings; **effective/reviewed dates** printed on each DAS policy PDF and EIS standard; the SoS **GovDelivery** email bulletins; and OARD's **Search Filings** by chapter/date-range. [Oregon Secretary of State](https://sos.oregon.gov/archives/Pages/oard-faq.aspx) There is no official RSS for OARD, so detection is best done by scheduled GitHub Actions that re-fetch pinned source URLs and diff content hashes.
- **Automation building blocks:** GitHub Actions on `schedule` (cron) plus `workflow_dispatch`; Markdown link-checkers (e.g., `lycheeverse/lychee` or `gaurav-nelson/github-action-markdown-link-check`) [GitHub](https://github.com/marketplace/actions/markdown-link-check) run weekly; `CODEOWNERS` + a CODEOWNERS validator; and OIDC-based auth for any workflow that needs cloud credentials (no long-lived secrets).

## Details — The Recommended Design

### (a) Repository directory structure
Organize primarily by **authority tier**, and within the policy/standard tiers by **agency**, so the structure both mirrors Oregon's legal hierarchy and scales cleanly from DAS to other agencies. Recommended layout:

```
oregon-exec-knowledge/                 (public repo)
├── README.md                          # human overview + prominent non-authoritative disclaimer
├── AGENTS.md                          # canonical agent guide (see (e)/(f))
├── CLAUDE.md                          # 3-line pointer: "read AGENTS.md"
├── llms.txt                           # machine-readable curated index (see (c))
├── DISCLAIMER.md                      # full non-authoritative statement + copyright notes
├── LICENSE                            # e.g., CC0/public-domain for content, MIT for tooling
├── CONTRIBUTING.md                    # PR workflow, review gates, DoD
├── .github/
│   ├── CODEOWNERS                     # review gates per directory
│   ├── ISSUE_TEMPLATE/
│   │   ├── intake-request.md          # "propose a document for ingestion"
│   │   └── source-change.md           # "upstream source changed"
│   ├── pull_request_template.md       # verification checklist (see (f))
│   └── workflows/
│       ├── validate-frontmatter.yml   # schema + required-fields check
│       ├── check-links.yml            # scheduled + PR link checking
│       ├── verify-provenance.yml      # retrieval-date/version/quote checks
│       ├── detect-upstream-changes.yml# scheduled re-fetch + hash diff (see (g))
│       └── codeowners-validate.yml
├── _meta/
│   ├── schema/
│   │   ├── document.frontmatter.schema.json   # JSON Schema for YAML header
│   │   └── source-manifest.schema.json
│   ├── source-manifest.yml            # every upstream source: URL, hash, last-checked
│   ├── skills/
│   │   └── intake.md                  # the discovery/intake "skill" prompt + checklist
│   └── templates/
│       ├── statute.md
│       ├── rule.md
│       ├── policy.md
│       ├── standard.md
│       └── external-reference.md
├── statutes/                          # ORS (jurisdiction-wide; not agency-scoped)
│   ├── _index.md
│   ├── CHANGELOG.md
│   └── ors-276A.300.md
├── rules/                             # OAR (by chapter → division)
│   ├── _index.md
│   ├── CHANGELOG.md
│   └── 125/                           # DAS chapter
│       └── 800/                       # division
│           └── oar-125-800-0020.md
├── executive-orders/
│   ├── _index.md
│   ├── CHANGELOG.md
│   └── eo-YY-NN.md
├── agencies/
│   └── das/
│       ├── _index.md                  # DAS map: divisions, contacts, scope
│       ├── policies/
│       │   ├── _index.md
│       │   ├── CHANGELOG.md
│       │   ├── das-107-001-020.md
│       │   └── das-107-004-052.md
│       ├── accounting-manual/
│       │   ├── _index.md
│       │   ├── CHANGELOG.md
│       │   └── oam-15-15-00.md
│       └── standards/                 # EIS/CSS statewide standards (referenced-out docs)
│           ├── _index.md
│           ├── CHANGELOG.md
│           └── eis-css-it-control-standards/
│               ├── _index.md          # splits the big standard by control family
│               ├── access-control-ac.md
│               └── incident-response-ir.md
└── external-references/               # non-policy docs referenced by policy
    ├── _index.md
    ├── CHANGELOG.md
    └── nist-sp-800-53-r5.md           # summary + link only (see caution below)
```

**Rationale:** Authority tier is the stable top level because it maps to how a policy drafter reasons ("what statute authorizes this? what rule implements it? what policy operationalizes it? what standard must we uphold?"). Statutes, rules, and executive orders are jurisdiction-wide and live at the top; policies, accounting manual, and standards are agency-scoped and live under `agencies/<agency>/`, so adding a second agency (e.g., `agencies/oha/`) is a copy-paste of the sub-structure with no schema change (requirement #5). The `external-references/` and per-agency `standards/` trees satisfy requirement #3 (documents outside policy that policy tells agencies to uphold). Splitting the large EIS control standards by control family keeps each file inside context windows.

### (b) Document template + frontmatter metadata schema
Every content file begins with a validated YAML header. Fields marked **required** are enforced by `validate-frontmatter.yml`.

```yaml
---
# ---- Identity ----
id: das-107-004-052                    # required; stable slug = filename
title: "Cyber and Information Security" # required
doc_type: policy                        # required; enum: statute|rule|executive_order|policy|procedure|standard|manual|external_reference
citation: "DAS Statewide Policy 107-004-052"  # required; human citation
# ---- Authority ----
authority_level: state_policy           # required; enum ranked: statute > administrative_rule > executive_order > state_policy > agency_procedure > standard > external_reference
issuing_body: "DAS Enterprise Information Services / Cyber Security Services"  # required
agency: das                             # required for agency-scoped docs; "statewide" for ORS/OAR
legal_authority: ["ORS 276A.300", "OAR 125-800-0020"]  # upstream authority this doc rests on
# ---- Provenance (anti-fabrication core) ----
source_url: "https://www.oregon.gov/das/Policies/107-004-052.pdf"   # required
source_format: pdf                      # required; pdf|html|xml
retrieved: 2026-07-18                    # required; ISO date the source was fetched
source_sha256: "b1946ac9…"              # required; hash of the fetched source file
# ---- Versioning (mirrors the source's own version signals) ----
effective_date: 2026-02-17              # from the PDF header "Effective"
last_reviewed: 2025-12-02               # from the PDF header "Reviewed"
source_version: "Effective 2/17/2026"   # verbatim version string as printed
status: current                         # required; enum: current|superseded|repealed|proposed|draft
supersedes: null
# ---- Repo curation metadata ----
content_mode: mixed                     # required; enum: verbatim|summary|mixed
last_verified: 2026-07-18               # required; date a human confirmed vs. source
verified_by: "@handle"                  # required; reviewer
maintainer: "@team-eis-policy"          # CODEOWNERS handle
# ---- Relationships (graph edges) ----
relationships:
  implements: ["ORS 276A.300"]
  implemented_by: ["das-107-004-052_pr"]
  references_external: ["eis-css-it-control-standards"]   # requirement #3 edge
  related: ["das-107-004-050", "das-107-004-110"]
  supersedes: []
tags: ["information-security", "cybersecurity", "eis", "css"]
---
```

The body then follows a fixed section template:

```markdown
> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated copy/summary,
> not the official text. Verify against the official source: {source_url} (retrieved {retrieved}).

# {title} ({citation})

## At a glance
_1–3 sentence plain-language summary of what this document requires and who it applies to._

## Scope & applicability
_Who it binds; exceptions._

## Key provisions
### {Provision heading}
> **[VERBATIM]** "Exact quoted text from the source…"   <!-- diffable against source -->

**[SUMMARY]** Paraphrase of the provision in agent-friendly form.

## Definitions
## Authority & references
- Rests on: {legal_authority}
- References out to: {references_external}

## Cross-references (in-repo)
- [DAS 107-004-050 Information Asset Classification](../policies/das-107-004-050.md)

## Provenance & change history
- Source: {source_url} · retrieved {retrieved} · sha256 {source_sha256}
- See this knowledge body's [CHANGELOG](./CHANGELOG.md).
```

**Labeling rule (requirement #7):** every substantive statement is tagged `[VERBATIM]` (must be an exact, diffable quote from the pinned source) or `[SUMMARY]` (paraphrase — allowed, but must be traceable to a cited section of the same source). No third category — nothing may appear that is neither quoted nor sourced.

### (c) Index / table-of-contents design
Three complementary layers so an agent can navigate at any granularity:
1. **`llms.txt` at root** — the machine-readable master map: H1 title, blockquote describing the repo's purpose and non-authoritative status, then `## Statutes`, `## Rules`, `## Executive Orders`, `## DAS Policies`, `## EIS Standards`, `## External References` sections, each a bulleted list of `[citation — title](path): one-line description of when an agent should consult it`. Keep it curated and under a few hundred lines; link to per-section `_index.md` files for depth.
2. **`_index.md` per directory** — a scoped map with a Markdown table (`citation | title | status | effective_date | applies_to | path`) plus a "How to find the right document" narrative that tells an agent, e.g., *"For questions about what data classification level applies, see 107-004-050; for acceptable use of state devices, 107-004-110; for the underlying control requirements, the EIS IT Control Standards."*
3. **Frontmatter `relationships` graph** — machine-traversable edges so an agent starting at any policy can walk up to its authorizing statute/rule and out to referenced standards.

### (d) Per-knowledge-body changelog format
One `CHANGELOG.md` per knowledge body (`rules/`, `agencies/das/policies/`, `agencies/das/standards/`, etc.), Keep a Changelog format with ISO dates and an `[Unreleased]` section, extended with domain-specific change types:

```markdown
# Changelog — DAS Statewide Policies
All notable changes to the curated copies in this directory are documented here.
Format based on Keep a Changelog. This repo is non-authoritative; dates below are
repo-curation dates, not official effective dates (those live in each file's frontmatter).

## [Unreleased]

## [2026-07-18]
### Source-Updated
- das-107-004-052: refreshed to Effective 2026-02-17 / Reviewed 2025-12-02 source;
  re-verified verbatim quotes (source_sha256 b1946ac9…). Verified-by @handle.
### Added
- das-107-004-052_pr: added procedure companion.
### Superseded
- (none)
### Verified
- das-107-004-050: quarterly re-verification, no source change.
```

Change types: `Added`, `Source-Updated`, `Superseded`, `Repealed`, `Removed`, `Verified`, `Fixed`, `Security`.

### (e) Document discovery / intake "skill" or process
Model this as a **spec-driven, human-gated pipeline** aligned to GitHub Spec Kit's `/specify → /plan → /tasks → /implement` pattern (the toolkit the user already uses with Copilot/Claude), with humans approving at each checkpoint. Concretely, implement it as a repeatable, documented "skill" (a prompt + checklist stored in the repo at `_meta/skills/intake.md`, referenced from `AGENTS.md`):

**Phase 0 — Discover (agent proposes, human vets the *list first*, per requirement #4):**
1. Seed the agent with the authoritative index pages (DAS policies page, OARD chapter 125, ORS chapters 183/184/276A, EIS/CSS standards page).
2. Agent produces a **candidate source manifest** — a table of every relevant document (citation, title, URL, doc_type, why-relevant, what-it-references) — as a PR editing `_meta/source-manifest.yml`. Crucially the agent also **follows outbound references** (e.g., 107-004-052 → "Statewide IT Control Standards") to surface the non-policy documents required by requirement #3.
3. **Human review gate #1:** a maintainer approves/prunes the manifest *before any content is ingested*. This is the "build/vet the list, then consume" sequencing the user specified.

**Phase 1 — Spec & plan (per approved document):** the intake issue template captures the spec (which document, which sections matter, verbatim-vs-summary policy for it, which relationships to assert). Agent drafts a `/plan`.

**Phase 2 — Ingest (agent implements under supervision):** agent fetches the pinned URL, records `source_sha256` and `retrieved`, fills the template, tags every statement `[VERBATIM]`/`[SUMMARY]`, and populates frontmatter.

**Phase 3 — Verify & merge (Human review gate #2):** automated checks run (below); a CODEOWNER for that agency/knowledge body reviews against the checklist and merges. Commit trailers record agent authorship (e.g., `Assisted-by: GitHub Copilot (autonomous|supervised)`), [GitHub](https://github.com/github/spec-kit/blob/main/AGENTS.md) a practice drawn from Spec Kit's own AGENTS.md.

### (f) Accuracy guardrails & anti-fabrication workflow
Layered defense so "content is accurate and new content is not fabricated" (requirement #7):
- **Provenance is mandatory** — `validate-frontmatter.yml` fails any file missing `source_url`, `retrieved`, `source_sha256`, `content_mode`, `last_verified`, `verified_by`, or `status`.
- **Verbatim must be diffable** — `verify-provenance.yml` re-fetches the pinned source (or the stored snapshot in `_meta/snapshots/`) and checks that every `[VERBATIM]` block is a literal substring; any mismatch fails the build. This mechanically prevents quote fabrication.
- **Summary must be sourced** — every `[SUMMARY]` must sit under a heading tied to a cited section; PR review confirms it. No un-cited assertions permitted; there is no "model knowledge" content category.
- **Human review gates** — branch protection requires PR + at least one CODEOWNER approval; `CODEOWNERS` assigns each directory to the responsible team (e.g., EIS policy team owns `agencies/das/standards/`).
- **PR verification checklist** (in `pull_request_template.md`): source URL reachable and pinned; retrieval date and hash recorded; effective/review/version dates transcribed from the source header; every quote verified verbatim; relationships checked; non-authoritative disclaimer present; changelog updated.
- **AGENTS.md hard rules** — explicit "do nots": *never state a rule/number/date not present in the cited source; never infer a citation; if unsure, insert a `TODO: verify` and leave it for human review rather than guessing; preserve agent-authorship commit trailers.*
- **Snapshots** — store a hash (and optionally a dated text snapshot) of each source in `_meta/` so verification and change-detection are reproducible even if the upstream page moves.

### (g) Ongoing update / maintenance workflow with upstream change detection
- **Scheduled detection** — `detect-upstream-changes.yml` runs on cron (e.g., weekly, and monthly right after the first-business-day Oregon Bulletin drop), re-fetches every `source_url` in `_meta/source-manifest.yml`, recomputes the hash, and for any changed source **opens an issue** (using the `source-change.md` template) tagged with the affected file(s) and assigned to the CODEOWNER. This turns "did the law change?" into an automated alert.
- **Source-specific cadence** built into the manifest as a `recheck` field: OARs/EOs monthly (Oregon Bulletin); ORS on the biennial edition cycle; OAM whenever a track-changes doc posts; DAS policies/EIS standards by their printed review dates plus a periodic re-crawl.
- **Human refresh** — a maintainer works the auto-opened issue through the same intake Phases 2–3 (re-fetch, re-verify quotes, update frontmatter dates/hash, log in the knowledge body's CHANGELOG with a `Source-Updated` or `Superseded` entry).
- **Link hygiene** — `check-links.yml` runs weekly (`workflow_dispatch` + `schedule`) to catch dead source URLs.
- **Quarterly re-verification** — even unchanged docs get a periodic `Verified` changelog stamp so `last_verified` never goes stale (stale docs correlate strongly with poor agent retrieval quality).
- **Secrets posture** — any workflow needing external credentials uses GitHub OIDC federation rather than stored long-lived secrets.

### (h) Additional suggestions, better approaches, and cautions
- **Consider an MCP server later.** Comparable projects (kaerez/US-law-mcp) expose curated legal corpora to Claude/Copilot/Cursor via the Model Context Protocol. Once the Markdown corpus is stable, wrapping it in a small MCP server (or publishing an `llms.txt` + Markdown variants) would let agents query it directly inside the user's existing tools — a natural phase 2.
- **Keep it a mirror, not a fork of the law.** The strongest guardrail against scope creep and accuracy drift is to summarize + link rather than re-host entire documents. For large third-party standards you may *not* freely republish (e.g., NIST is public domain but ISO 27001/27002 and CIS Controls are copyrighted), store a *summary + official link only*, never the full copyrighted text. Flag this explicitly in `external-references/`.
- **Disclaimer everywhere.** Root README, `DISCLAIMER.md`, `llms.txt` blockquote, and every file header must state non-authoritative status and link to the official source — mirroring Oregon's own "not the official text" language.
- **License split.** Follow the `legalize`/`us-code` model: content as public-domain/CC0 (it's largely government material), tooling/structure as MIT.
- **Watch agency-specific terms when scaling.** When expanding beyond DAS, re-check each agency sub-site's terms (some Oregon sub-sites assert "personal, non-commercial use only").
- **Governance of the graph.** As relationships grow, add a lightweight CI check that every `relationships` target resolves to an existing file, so the cross-reference graph never rots.

## Recommendations (staged)

**Stage 1 — Stand up the skeleton (week 1–2).** Create the public repo; add `README`, `DISCLAIMER.md`, `AGENTS.md`, `llms.txt`, `LICENSE` (CC0 content / MIT tooling), `CODEOWNERS`, the five `_meta/templates/`, and the `document.frontmatter.schema.json`. Turn on branch protection (PR + 1 CODEOWNER). *Benchmark to proceed:* schema validation and link-check workflows pass on a single hand-built sample file (`das-107-004-052.md`).

**Stage 2 — Pilot on DAS/EIS security (week 3–6).** Run the discovery skill against the DAS policy page, OARD chapter 125, ORS 276A/183, and the EIS/CSS standards; vet the manifest (gate #1); ingest ~10–15 documents including the 107-004 security cluster and the EIS IT Control Standards (split by control family) to prove the referenced-external-document pattern. *Benchmark:* every file passes `verify-provenance.yml`; a Copilot/Claude agent, given only `llms.txt`, can correctly answer "what standard must an agency uphold for information security, and what policy requires it?" citing the right files.

**Stage 3 — Automate maintenance (week 6–8).** Enable `detect-upstream-changes.yml` on the monthly Bulletin cadence and weekly link checks; process the first auto-generated source-change issue end to end. *Benchmark:* a deliberately changed source hash opens an issue and routes to the right CODEOWNER.

**Stage 4 — Scale to a second agency (when Stage 2–3 are stable).** Clone the `agencies/das/` sub-structure to a second agency; confirm no schema changes are needed. *Threshold to expand:* provenance-verification pass rate ≥ 99% and zero unresolved stale-verification issues on DAS content for one full monthly cycle.

**What would change these recommendations:** if legal review objects to hosting even verbatim excerpts of *policies* (as opposed to rules/statutes), fall back to summary-plus-link only for the policy tier; if the corpus grows past what an `llms.txt` index can usefully map, graduate to an MCP server with search rather than a flat index.

## Caveats
- **This is a functional/structural design, not legal advice.** The copyright analysis (government-edicts doctrine; Oregon's 2008 ORS waiver; absence of republication restrictions on DAS policy PDFs) is well-supported, but have DAS counsel bless the plan before publishing, especially regarding verbatim reproduction of *policies* and any third-party standards.
- **"Non-authoritative" is load-bearing.** Oregon's own systems disclaim their online text as unofficial; the repo inherits that limitation and must never be represented as a source of truth for compliance decisions.
- **`llms.txt` is a convention, not a ratified standard**, and is not guaranteed to be consumed by every agent; `AGENTS.md` (broadly adopted and now Linux Foundation–stewarded) is the more dependable entry point, with `llms.txt` as the navigational index.
- **Third-party copyrighted standards (ISO, CIS) must not be republished in full** — summary-plus-link only.
- **No official machine feed exists for OARD**, so change detection relies on scheduled re-crawls and hash diffs plus the human-readable Oregon Bulletin; there is inherent lag (up to a month) between an upstream change and detection.
- **Effective-date nuance:** a document's frontmatter dates are transcribed from the source and can themselves be stale or in-transition (e.g., a policy "Effective" in the near future); reviewers must record what the source actually prints, not what they assume.
- **AI drift risk remains** even with guardrails; the verbatim-diff check catches quote fabrication but not subtle summary distortion, which is why human review gates and periodic re-verification are non-negotiable.