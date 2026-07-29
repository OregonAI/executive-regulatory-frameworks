#!/usr/bin/env python3
"""Operationalize the conflict-candidates analysis that the 2026-07 pilot ran by hand.

The pilot's output was already LLM-generated; only the *process* was manual. This makes
it repeatable, attributable, and safe to re-run. It never runs at CI time — like
build_embeddings.py, it produces a committed artifact offline and CI validates that
artifact deterministically (build_conflict_candidates_data.py).

UNIT OF ANALYSIS. The pilot fed one whole ORS chapter per request. That does not scale:
ORS 409's implementing rules come to ~1.09M tokens, past any context window, and ORS 179
is ~662k. It is exactly why batch 3 sampled the 40 SMALLEST chapters and left the bias
this tool exists to fix. So the analysis unit here is the ORS SECTION plus the rules
implementing it, which keeps intact the two relationships where conflicts actually live:
statute-provision vs implementing rule, and rule vs rule under the same provision. The
REPORTING unit stays the chapter, so the catalog schema is unchanged.

TIERS, because most sections cannot produce the finding we are looking for. 'Shared
authority' — 2+ agencies under one statute — is the precondition for an inter-agency
conflict, and the pilot tested it per CHAPTER. Measured per SECTION, only 627 of 5,482
sections in the unanalyzed chapters have rules from 2+ agencies. Sending all the rules of
the other ~4,855 as clusters pays cluster prices for a comparison that structurally cannot
yield an inter-agency finding.

  --tier cluster   (default) multi-agency sections, all their rules together.
                   667 requests, ~19.0M tokens, ~$47 batch. This is the ENTIRE
                   inter-agency class — the highest-value third of the naive cost.
  --tier pairwise  one rule + its statute section, for the rest. 57,077 requests,
                   ~$236 before caching. Statute-vs-rule divergence only.
  --tier all       both.

  Cost of the section unit, stated plainly: a conflict spanning two DIFFERENT sections of
  the same chapter will not be seen. The pilot's whole-chapter pass could in principle
  catch those; it simply could not run at all on the chapters that matter most.

25 multi-agency sections still exceed one bundle and are split into parts, each carrying
the full statute with a slice of the rules. Rule-vs-rule comparison ACROSS parts does not
happen, and every candidate from a split section records `partial: true` so the gap is
visible in the data rather than implied by its absence.

BACKENDS, one interface (`analyze(bundles) -> {custom_id: [candidate, ...]}`):
  --backend claude   Batch API (50% off list, <=100k requests, usually <1hr). Results are
                     keyed by custom_id and read back by custom_id, NEVER by position —
                     the API does not promise result order.
  --backend local    Any OpenAI-compatible local server (ollama, llama.cpp --server).
                     stdlib HTTP only, no extra dependency.

                     A REASONING model is the difference between usable and not.
                     Measured on identical bundles (see src/eval_conflicts.py):
                       qwen2.5-7b   28% of quotes grounded, 12 of 25 citations
                                    pointing at document ids that do not exist,
                                    0/6 known candidates found, 11 flags per hit
                       gemma4-12b   100% grounded, ZERO nonexistent ids,
                                    4/6 found, 1.8 flags per hit
                     Gemma's reasoning channel costs ~636s per bundle against Qwen's
                     ~20s on an 8 GB card, because 7.2 GB of weights leaves nothing for
                     KV cache and generation partly falls back to CPU. Quality is there;
                     throughput is the blocker, and it is hardware, not the model.

  python3 src/analyze_conflicts.py --dry-run                 # what would run, and cost
  python3 src/analyze_conflicts.py --backend local --limit 3 # iterate on the prompt
  python3 src/analyze_conflicts.py --backend claude --submit # create the batch
  python3 src/analyze_conflicts.py --backend claude --collect BATCH_ID   # merge results
"""
import argparse
import collections
import json
import os
import hashlib
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT, extract_fulltext, parse_frontmatter
from enrich_oar import load_registry_by_chapter
from build_conflict_candidates_data import (candidate_fingerprint, candidate_pairs,
                                            declared_authority, fold, quote_is_grounded)

CATALOG = REPO_ROOT / "_meta/catalog/conflict-candidates.yml"
GRAPH = REPO_ROOT / "_meta/graph.json"
STATE = REPO_ROOT / "_meta/.cache/conflict-runs"      # gitignored; batch bookkeeping

PROMPT_VERSION = "conflict-v2-2026-07"
# v3 names all eight semantic checks and disqualifies the mechanical ones (see SYSTEM_V3).
# Both are kept so a rewrite can be MEASURED against the prompt it replaces rather than
# swapped in on the strength of its own reasoning; --prompt selects, and the choice is
# recorded per candidate so mixed catalogs stay attributable.
PROMPT_VERSIONS = {"v2": "conflict-v2-2026-07", "v3": "conflict-v3-2026-07",
                   "v4": "conflict-v4-escape-2026-07",
                   # ...-07b, not -07: #62 changed BOTH the instruction and the way
                   # render_user prints the declaration, and the rendering is part of the
                   # arm even though nothing else records it. Candidates already stored
                   # under `conflict-v5-authority-2026-07` were produced against a bundle
                   # that put the label and the value on one line, which is why one of
                   # them quotes the label. Leaving the string alone would have made two
                   # different experiments indistinguishable in the catalog.
                   "v5": "conflict-v5-authority-2026-07b"}
# Opus is the PRODUCTION path only — a full --tier section pass is 7,464 requests and
# ~$154 of input at batch pricing, so it is not something to spend on an experiment.
# EVALUATE WITH HAIKU instead (see EVAL_MODEL): measuring whether a prompt change helps
# does not need the expensive model, and the comparison is against the pilot's recorded
# candidates either way. eval_conflicts.py --from-raw scores any model's output through
# the same grounding and recall code, so a Haiku run is directly comparable to a local one.
DEFAULT_MODEL = "claude-opus-5"
EVAL_MODEL = "claude-haiku-4-5"
# Well inside every current context window, leaving room for the instructions and a long
# reply. Bundles above this are split.
MAX_BUNDLE_TOKENS = 150_000

# What each --tier actually SELECTS, printed with every estimate (#51).
#
# The trap this exists to close: `--tier cluster` and `--tier section` cover populations
# that differ by 8.7x — 657 multi-agency sections against all 5,716 sections — and BOTH
# emit bundles whose `mode` is the string "cluster". So a `--tier section` estimate prints
# "requests: N (N cluster)", which reads as though the cluster tier produced it. Two
# estimates taken at different tiers look like two measurements of the same thing, and the
# dollar figure someone approves is attached to whichever one they happened to run.
TIERS = ("section", "cluster", "pairwise", "all")
TIER_MEANING = {
    "cluster": "sections implemented by 2+ AGENCIES ONLY — the inter-agency class. "
               "Single-agency sections are NOT included",
    "section": "EVERY section that has implementing rules, single-agency ones included "
               "(a superset of --tier cluster)",
    "pairwise": "one rule against the statute section it implements, for sections the "
                "cluster tier skips",
    "all": "cluster where a section is multi-agency, pairwise elsewhere",
}
CHARS_PER_TOKEN = 4          # rough, and only used for splitting/estimating


# --------------------------------------------------------------------------- bundles

def _text(doc_id: str, paths: dict) -> str:
    p = paths.get(doc_id)
    if not p:
        return ""
    _, body = parse_frontmatter(REPO_ROOT / p)
    return extract_fulltext(body) or ""


def _title(doc_id: str, paths: dict) -> str:
    p = paths.get(doc_id)
    if not p:
        return ""
    fm, _ = parse_frontmatter(REPO_ROOT / p)
    return fm.get("title", "")


def _declared_authority(doc_id: str, paths: dict) -> str:
    """The statutes a rule DECLARES it implements, from frontmatter, as the one line the
    bundle shows the model.

    Not cosmetic metadata: a rule claiming authority under a provision that excludes its
    subject, or listing a statute its operative text never engages, is a real and
    reviewable inconsistency — and 26 of the catalog's 148 candidates (18%) rest on
    exactly this evidence. The bundle used to carry only `extract_fulltext(body)`, so the
    model was asked to find contradictions in a declaration it was never shown. Two of the
    misses in the Haiku v4 run are this shape, including OAR 581-026-0600 declaring
    'ORS 332.158' while ORS 332.158(4) expressly excludes public charter schools.

    Built by `declared_authority()`, the same function the grounding check reads, so the
    string the model is shown and the string its quote is checked against cannot drift
    apart (#62)."""
    p = paths.get(doc_id)
    if not p:
        return ""
    fm, _ = parse_frontmatter(REPO_ROOT / p)
    return declared_authority(fm)


def shared_authority_chapters(graph: dict) -> dict:
    """ORS chapter -> set of agency slugs with a rule implementing it. A chapter is in the
    'shared authority' set when 2+ distinct agencies regulate under it — that overlap is
    the structural precondition for an inter-agency inconsistency.

    Note this set is currently 223 chapters, not the 245 quoted in the pilot's own notes:
    the implements-contamination and repealed-rule fixes (BACKLOG.md, 2026-07-24) removed
    a lot of spurious edges, and some chapters fell out of the set as a result."""
    reg = load_registry_by_chapter()
    by_chapter = collections.defaultdict(set)
    for e in graph["edges"]:
        if (e["type"] != "implemented_by" or not e["from"].startswith("ors-")
                or not e["to"].startswith("oar-")):
            continue
        org = reg.get(e["to"].split("-")[1])
        if org:
            by_chapter[e["from"].split("-", 1)[1].split(".")[0]].add(org["slug"])
    return {c: a for c, a in by_chapter.items() if len(a) >= 2}


def split_rules(rules: list, statute_chars: int, max_tokens: int, registry: dict) -> list:
    """Split a section's rules into sub-clusters that each fit `max_tokens`.

    The statute rides in EVERY sub-cluster — it is the thing the rules are compared
    against, so a part without it can only find rule-vs-rule and would silently lose
    the statute-vs-rule class that is 81% of the known candidates.

    Rules are interleaved BY AGENCY rather than taken in id order. Ids sort by OAR
    chapter, which means one agency's rules are contiguous, so a naive fill puts a
    single agency in each part — and inter-agency conflict, the highest-value class
    and the entire reason 'shared authority' is the selection criterion, becomes
    structurally undiscoverable. Round-robin gives every part a mix.

    A single rule larger than the budget still gets its own part. Truncating it would
    silently hide text the model was told it had read, and a candidate quoting a
    passage that was never shown is exactly the fabrication this pipeline exists to
    avoid. An oversized part is visible in the size report; a truncated one is not.
    """
    budget = max_tokens * CHARS_PER_TOKEN - statute_chars
    if budget <= 0:                       # statute alone exceeds the window
        return [[r] for r in rules]
    if sum(len(r["text"]) for r in rules) <= budget:
        return [rules]                    # the common case: whole section fits

    by_agency: dict = collections.defaultdict(list)
    for r in rules:
        by_agency[registry.get(r["id"].split("-")[1], {}).get("slug")].append(r)
    queues = [collections.deque(v) for _, v in sorted(by_agency.items(),
                                                     key=lambda kv: str(kv[0]))]
    parts, cur, size = [], [], 0
    while any(queues):
        for q in queues:
            if not q:
                continue
            r = q.popleft()
            if cur and size + len(r["text"]) > budget:
                parts.append(cur)
                cur, size = [], 0
            cur.append(r)
            size += len(r["text"])
    if cur:
        parts.append(cur)
    return parts


def build_bundles(chapters: list, graph: dict, tier: str = "cluster",
                  max_tokens: int = MAX_BUNDLE_TOKENS) -> list:
    """Bundles to analyze, scoped by tier.

    WHY TWO TIERS. 'Shared authority' — 2+ agencies regulating under one statute — is what
    makes an inter-agency conflict possible, and the pilot applied that test per CHAPTER.
    Measured per SECTION, only 627 of 5,482 sections in the unanalyzed chapters actually
    have rules from 2+ agencies. Bundling all the rules of the other ~4,855 sections buys
    nothing a cheaper pairing would not: one agency's rules under one provision cannot
    produce an INTER-agency finding, which is the class this analysis exists to surface.

      cluster   (default) statute section + ALL its rules, but only where 2+ agencies
                implement it. 627 requests, ~19.0M tokens, ~$47 batch. Rule-vs-rule
                comparison is possible here, and this is the entire inter-agency class.
      pairwise  one rule + the statute section it implements. 37,742 requests. Catches
                statute-vs-rule divergence only, and repeats the statute per rule — but
                the statute sits in the cached prefix, so the repeat costs ~0.1x.
      all       both.
    """
    paths = {n["id"]: n["path"] for n in graph["nodes"]}
    registry = load_registry_by_chapter()
    wanted = set(chapters)
    by_section = collections.defaultdict(set)
    for e in graph["edges"]:
        if (e["type"] != "implemented_by" or not e["from"].startswith("ors-")
                or not e["to"].startswith("oar-")):
            continue
        if e["from"].split("-", 1)[1].split(".")[0] in wanted:
            by_section[e["from"]].add(e["to"])

    bundles = []
    for section in sorted(by_section):
        chapter = section.split("-", 1)[1].split(".")[0]
        statute = _text(section, paths)
        if not statute:
            continue                      # nothing to compare rules against
        rules = []
        for rid in sorted(by_section[section]):
            t = _text(rid, paths)
            if t:
                rules.append({"id": rid, "title": _title(rid, paths), "text": t,
                              "declares": _declared_authority(rid, paths)})
        if not rules:
            continue

        agencies = {registry.get(r["id"].split("-")[1], {}).get("slug") for r in rules}
        agencies.discard(None)
        multi = len(agencies) >= 2
        # `section` clusters EVERY section with rules, not just multi-agency ones. The
        # multi-agency filter is a cost optimisation for a paid API — it targets the
        # inter-agency class and skips sections that structurally cannot produce one.
        # For a local model, where compute is free and the question is "what can this
        # model find at all", that filter throws away most of the evidence: only 57 of
        # the eval set's 479 sections are multi-agency, leaving 18 of 137 known
        # candidates reachable and the measurement meaningless.
        want_cluster = tier == "section" or (multi and tier in ("cluster", "all"))
        want_pairs = tier in ("pairwise", "all") and not (multi and tier == "all")

        common = {"ors_chapter": chapter, "section": section,
                  "section_title": _title(section, paths), "statute": statute,
                  "n_agencies": len(agencies)}

        if want_cluster:
            parts = split_rules(rules, len(statute), max_tokens, registry)
            for i, part in enumerate(parts):
                bundles.append({**common, "custom_id": f"{section}#{i}", "mode": "cluster",
                                "rules": part, "partial": len(parts) > 1,
                                "part": i, "n_parts": len(parts),
                                "agencies_in_part": sorted(
                                    {registry.get(r["id"].split("-")[1], {}).get("slug")
                                     for r in part} - {None}),
                                "co_present": [r["id"] for r in part],
                                "est_tokens": (len(statute) + sum(len(r["text"]) for r in part))
                                // CHARS_PER_TOKEN})
        elif want_pairs:
            for r in rules:
                bundles.append({**common, "custom_id": f"{section}@{r['id']}",
                                "mode": "pairwise", "rules": [r], "partial": False,
                                "part": 0, "n_parts": 1,
                                "est_tokens": (len(statute) + len(r["text"])) // CHARS_PER_TOKEN})
    return bundles


# --------------------------------------------------------------------------- prompt

SYSTEM = """You are assisting a public, non-authoritative reference corpus of Oregon law.

You will be given one ORS statute section and the full text of every Oregon Administrative
Rule that implements it. Identify CANDIDATE inconsistencies for human legal review.

Absolute requirements — these override any instinct to be helpful or comprehensive:

1. NEVER assert that a conflict exists. Everything you produce is a candidate for review.
2. NEVER quote text that is not present verbatim in the document you attribute it to. Every
   quote is mechanically checked against the source; an invented quote is the single worst
   failure mode here. Copy exactly, including punctuation and capitalization. Use "..." for
   elision. If you cannot quote it exactly, do not raise the candidate.
3. NEVER cite a document id that was not given to you.
4. Report NOTHING rather than something marginal. A chapter with no real inconsistency is a
   valid and useful result. Do not manufacture findings to seem thorough.

What counts as a candidate:
- A rule imposes a threshold, deadline, scope, or duty that differs from the statute's.
- Two rules implementing the same provision impose requirements that cannot both be met,
  or that treat the same regulated party differently without statutory basis.
- A rule omits a mandate the statute makes non-discretionary, or adds a requirement with no
  apparent statutory hook.

What does NOT count (the pilot wasted review time on these):
- A rule being more specific or detailed than the statute. That is what rules are for.
- Differences in wording that carry the same legal meaning.
- A rule that is stale or repealed — that is a data-quality observation, not a conflict.

Grade every candidate:
- confidence: how sure you are the tension is real, not an artifact of your reading.
- severity: the practical consequence if it is real — does someone face contradictory
  obligations, or is it a drafting untidiness?

Reply with ONLY a fenced ```json block, no prose before or after:

```json
{"candidates": [
  {"summary": "one sentence, plain language, no legal conclusion",
   "confidence": "low|medium|high",
   "severity": "low|medium|high",
   "documents": [
     {"id": "<exact document id given to you>",
      "citation": "<e.g. ORS 291.047(1)-(2) or OAR 137-045-0030(1)(a)>",
      "quote": "<verbatim from that document>"}
   ]}
]}
```

An empty list is the correct answer when nothing qualifies."""


# ---------------------------------------------------------------------------------
# conflict-v3. Written against a hand-labelled taxonomy of all 137 pilot candidates
# (_meta/eval/pilot-taxonomy.json), not against intuition. Two measurements drove it:
#
#   1. 40 of 137 (29%) are decidable by code and are now detect_mechanical.py's job.
#      v2 spent model attention on them anyway and, on the dead-citation class, found
#      21 where a regex finds 486. They are DISQUALIFIED below, explicitly.
#   2. Of the 97 that genuinely need reading, v2 cued only 63. The four types with no
#      cue at all -- redefines (11), wrong_pointer (15), discretion (5), internal (3)
#      -- are 35% of the semantic work, and wrong_pointer is the second-largest
#      semantic type in the whole pilot.
#
# So v3 names all eight semantic checks, each with the question that DISCRIMINATES it
# (not just a label), and each anchored to a real pilot finding so the model is matching
# a pattern it can see rather than guessing at an abstraction. It also emits `type`,
# which is what makes per-type recall measurable -- without it, tuning is guesswork.
SYSTEM_V3 = """You are assisting a public, non-authoritative reference corpus of Oregon law.

You will be given one ORS statute section and the full text of every Oregon Administrative
Rule that implements it. Find CANDIDATE inconsistencies for human legal review.

Absolute requirements — these override any instinct to be helpful or comprehensive:

1. NEVER assert that a conflict exists. Everything you produce is a candidate for review.
2. NEVER quote text that is not present verbatim in the document you attribute it to. Every
   quote is mechanically checked against the source; an invented quote is the single worst
   failure mode here. Copy exactly, including punctuation and capitalization. Use "..." for
   elision. If you cannot quote it exactly, do not raise the candidate.
3. NEVER cite a document id that was not given to you.
4. Report NOTHING rather than something marginal. A statute whose rules are consistent is a
   valid and useful result. Do not manufacture findings to seem thorough.

DO NOT REPORT THESE — separate tooling already finds them, and reporting them here costs
review time without adding anything:
- A citation to a statute or rule that does not exist, or a repealed one. (dead reference)
- A rule marked current whose own text declares a sunset that has passed. (repealed)
- A rule older than the statute it implements, with no other discrepancy. Age alone is not
  a conflict. Only report it if you can point to specific text the amendment changed.
- Frontmatter, metadata, or relationship-list disagreements. You are reading the TEXT.

THE EIGHT CHECKS. Run each against every rule. The question is what discriminates the
type — apply it literally.

1. NARROWS — does the rule restrict something the statute states more broadly?
   Ask: is there an item in a statutory list, a qualifying phrase, or a condition that the
   rule's restatement drops or shrinks?
   e.g. a rule restated the statute's "immediate family" definition but dropped one of its
   four listed categories; another narrowed an exemption from "any building or premises" to
   "residential building" only.

2. BROADENS — does the rule reach parties, situations, or authority the statute does not?
   Ask: could someone be covered by the rule but not by the statute?
   e.g. a rule extended a statutory licensee-only immunity to delivery-facilitator
   permittees, a class the statute never names; another expanded program-review criteria to
   "community colleges", a class the statute never mentions.

3. REDEFINES — does the rule give a term the statute defines a DIFFERENT meaning?
   Ask: does the statute have a definitions section for this term, and does the rule's
   version change its substance rather than just its wording?
   e.g. a rule redefined "Governing Body" as a closed list of state boards, incompatible
   with the statute's political-subdivision definition; another defined "harm" as "limited
   to monetary loss" where the statute left it undefined and broader.

4. NUMERIC — do a threshold, deadline, fee, cap, count, or date differ?
   Ask: do the two numbers govern the SAME trigger? Different numbers for different
   triggers are not a conflict.
   e.g. a risk-assessment deadline of 60 days by rule vs 90 by statute for the same
   trigger; a $10 biennial fee where the statute sets $3.

5. WRONG_POINTER — does a cross-reference point at a provision that does not contain what
   the citing text claims? The target EXISTS; it is about something else.
   Ask: read the cited subsection. Does it actually say what the citing document implies?
   e.g. a rule cited ORS 153.012 for dollar amounts, but 153.012 contains no dollar figures
   (they are in 153.018); another cited subsection (3)(a) for a fund's revenue source, but
   (3)(a) is a mining-claim exemption.

6. DISCRETION — does the rule change whether something is mandatory?
   Ask: does "shall" become "may", or an absolute standard become a balanceable one, or a
   fixed deadline become open-ended?
   e.g. a rule converted the statute's absolute "no injury to other water rights" standard
   into one mitigable at Department discretion; another replaced a mandatory 90-day
   approve/reject deadline with an open-ended process.

7. RULE_VS_RULE — do two rules implementing this same statute disagree?
   This needs no statutory conflict at all: the statute may be silent. Compare the rules
   against EACH OTHER, especially rules from different agencies or different decades.
   Ask: would a regulated party get different answers depending on which rule they read?
   e.g. two rule sets tagged to the same statute set 120-day and 30-day deadlines for the
   identical step; two agencies set different reapplication waiting periods where the
   statute is silent.

8. INTERNAL — does a single rule contradict itself?
   Ask: do two clauses of the same rule give different answers to one question?
   e.g. one rule set two different acreage caps for an identical trigger phrase; another
   set a "no less than" floor pegged to a floating rate immediately followed by a hard cap.

NOT a candidate — the pilot wasted review time on these:
- A rule being more specific, more detailed, or procedurally elaborate than the statute.
  That is what rules are for.
- Differences in wording that carry the same legal meaning.
- A rule filling a gap the statute leaves open, where the statute grants rulemaking
  authority to do so.

Grade every candidate:
- confidence: how sure you are the tension is real, not an artifact of your reading.
- severity: the practical consequence if it is real — does someone face contradictory
  obligations, or is it a drafting untidiness?

Reply with ONLY a fenced ```json block, no prose before or after:

```json
{"candidates": [
  {"summary": "one sentence, plain language, no legal conclusion",
   "type": "narrows|broadens|redefines|numeric|wrong_pointer|discretion|rule_vs_rule|internal",
   "confidence": "low|medium|high",
   "severity": "low|medium|high",
   "documents": [
     {"id": "<exact document id given to you>",
      "citation": "<e.g. ORS 291.047(1)-(2) or OAR 137-045-0030(1)(a)>",
      "quote": "<verbatim from that document>"}
   ]}
]}
```

An empty list is the correct answer when nothing qualifies."""


# A SECOND prompt, for small local models, because the full SYSTEM prompt above is
# written for a frontier model and a 7B does better with a short contract.
#
# CORRECTION, recorded because the wrong version of this comment nearly shipped: an
# earlier measurement claimed a hard ~3,000-token instruction-following ceiling on
# qwen2.5-7b (valid JSON at 223/1,489/2,933 tokens, prose above). That was NOT a model
# property. ollama defaults OLLAMA_CONTEXT_LENGTH to 4096, so every larger bundle was
# being SILENTLY TRUNCATED before the model saw it — the "ceiling" was exactly the
# default window. Re-run with OLLAMA_CONTEXT_LENGTH=32768, the same model holds the
# contract at 14,288 tokens. Always check `ollama ps` for the CONTEXT column before
# concluding anything about a local model's capability.
#
# So this keeps only the guardrails that cannot be given up, and drops the rest:
#   - quotes must be copied, never composed  (the grounding check depends on it)
#   - an empty list is a CORRECT answer      (or the model manufactures findings)
#   - candidates, not conclusions            (the corpus's whole framing)
# Scope lists, severity/confidence grading and the near-miss guidance are gone. They are
# real losses — graded output is simply unavailable from this model — and the evaluation
# reports confidence/severity as null rather than inventing them.
LOCAL_SYSTEM = """Compare the Oregon statute below against the rules that implement it.

Find places where a rule CONTRADICTS the statute: a different dollar amount, deadline,
scope, or duty. Report candidates for a human to review, never conclusions.

- Copy every quote EXACTLY from the text you were given. Never write text that is not
  there. Quotes are checked mechanically against the source.
- Only cite an id that appears above.
- If nothing contradicts, reply {"candidates":[]}. That is a correct and useful answer.
  Do not invent a finding to seem thorough.

Reply with ONLY this JSON and nothing else:
{"candidates":[{"summary":"one sentence","documents":[{"id":"exact id","citation":"e.g. ORS 291.047(1)","quote":"exact words"}]}]}"""


# The local twin of SYSTEM_V3. Gemma 4 12B held the JSON contract and grounded 100% of
# its quotes on the pilot subset, so it can carry the eight checks; it cannot reliably
# produce confidence/severity, so those stay out rather than being invented. The checks
# are compressed to one line each — a 12B follows a short list far better than prose, and
# the worked examples that help a frontier model mostly cost context here.
LOCAL_SYSTEM_V3 = """Compare the Oregon statute below against the rules that implement it.

Report a candidate ONLY if one of these is true. Name which one in "type".

narrows       the rule drops an item, condition, or qualifier the statute states
broadens      the rule covers a party or situation the statute does not
redefines     the rule gives a term the statute defines a different meaning
numeric       a threshold, deadline, fee, cap, or date differs FOR THE SAME TRIGGER
wrong_pointer a cross-reference points at a provision that does not say what is claimed
discretion    the rule makes a statutory "shall" optional, or an absolute standard flexible
rule_vs_rule  two rules here disagree with each other (the statute may be silent)
internal      one rule contradicts itself

IGNORE these — other tooling handles them:
- a citation to something that does not exist, or was repealed
- a rule being older than the statute, with nothing else wrong
- a rule simply being more detailed or specific than the statute

- Copy every quote EXACTLY from the text you were given. Never write text that is not
  there. Quotes are checked mechanically against the source.
- Only cite an id that appears above.
- If nothing matches, reply {"candidates":[]}. That is a correct and useful answer.
  Do not invent a finding to seem thorough.

Reply with ONLY this JSON and nothing else:
{"candidates":[{"summary":"one sentence","type":"one of the eight above","documents":[{"id":"exact id","citation":"e.g. ORS 291.047(1)","quote":"exact words"}]}]}"""



# v4 = v3 with an ESCAPE HATCH. Identical checks, identical prohibitions, one difference:
# a finding that fits none of the eight may still be reported, typed "other".
#
# THE HYPOTHESIS THIS ISOLATES. v3 says "Report a candidate ONLY if one of these is true."
# A model that sees something wrong but cannot map it onto a label has exactly two options
# under that instruction — mislabel it, or stay silent — and a careful model stays silent.
# Haiku produced ONE candidate from nine bundles under v3, and it was correct. That is the
# signature of suppression rather than blindness.
#
# If recall rises under v4 while grounding holds, the taxonomy was the constraint and the
# fix is free. If recall does not move, the eight labels are not what is limiting recall
# and only a stronger model will help — which is a much more expensive answer, and worth
# knowing before paying for it.
LOCAL_SYSTEM_V4 = LOCAL_SYSTEM_V3.replace(
    'Report a candidate ONLY if one of these is true. Name which one in "type".',
    'Report a candidate if one of these is true. Name which one in "type".\n\n'
    'If you find a real inconsistency that fits NONE of them, report it anyway with\n'
    'type "other" and say plainly what the inconsistency is. Do not force it into a\n'
    'label that does not fit, and do not stay silent because no label matches.'
).replace(
    '"type":"one of the eight above"', '"type":"one of the eight above, or other"')

# v5 = v4 plus the class the bundle could not previously show. `render_user` now carries
# each rule's declared `statutes_implemented`, and a ninth check names what to do with it.
#
# WHY THIS IS NOT JUST ANOTHER LABEL. 26 of the catalog's 148 candidates (18%) turn on a
# rule's DECLARED authority, and until this change the bundle contained only
# extract_fulltext(body) — the model was asked to find a contradiction in a declaration it
# had never seen. Two of the Haiku v4 misses are exactly this, including OAR 581-026-0600
# declaring "ORS 332.158" where ORS 332.158(4) expressly excludes public charter schools.
# So v5 changes the EVIDENCE first and the instruction second; a prompt-only v5 would have
# measured nothing.
#
# The IGNORE list needs amending in the same breath. It says to skip "a citation to
# something that does not exist, or was repealed", which is detect_mechanical.py's job —
# but a model reading that can reasonably conclude that anything about a citation is out
# of scope, and suppress the very class this version adds. The statute here EXISTS; the
# problem is what it says.
LOCAL_SYSTEM_V5 = LOCAL_SYSTEM_V4.replace(
    "internal      one rule contradicts itself",
    "internal      one rule contradicts itself\n"
    "wrong_authority the rule DECLARES it implements a statute that excludes its own\n"
    "              subject, or that its operative text never engages at all. The\n"
    "              declaration is the line of statute numbers under 'declared\n"
    "              statutes_implemented' above each rule. Quote THAT LINE and nothing\n"
    "              else -- not the heading above it, not the rule title -- and cite it\n"
    "              as statutes_implemented, not as rule text"
).replace(
    "- a citation to something that does not exist, or was repealed",
    "- a citation to something that does not exist, or was repealed (but a declared\n"
    "  statute that EXISTS and contradicts the rule IS in scope — see wrong_authority)"
).replace(
    '"type":"one of the eight above, or other"',
    '"type":"one of the nine above, or other"')

PROMPT_TEXTS = {"v2": LOCAL_SYSTEM, "v3": LOCAL_SYSTEM_V3,
                "v4": LOCAL_SYSTEM_V4, "v5": LOCAL_SYSTEM_V5}


def render_user(bundle: dict) -> str:
    parts = [f"# ORS statute section: {bundle['section']} — {bundle['section_title']}", "",
             bundle["statute"], "",
             f"# Implementing rules ({len(bundle['rules'])})"]
    if bundle["partial"]:
        parts.insert(0, (
            f"NOTE: this is part {bundle['part'] + 1} of {bundle['n_parts']} for this "
            "section — it carries a SUBSET of the implementing rules. Compare rules within "
            "this set and against the statute; do not speculate about rules not shown."))
        parts.insert(1, "")
    for r in bundle["rules"]:
        parts += [f"\n## {r['id']} — {r['title']}", ""]
        # The rule's own claim about what it implements. Labelled as a DECLARATION so a
        # quote drawn from it is attributable to `statutes_implemented` rather than being
        # mistaken for operative text — the two are different kinds of evidence and a
        # candidate must cite which one it means.
        #
        # THE LABEL IS ON ITS OWN LINE, and says so (#62). When label and value shared a
        # line, Haiku quoted the whole line — "declared statutes_implemented (frontmatter,
        # not operative text): ORS 332.158, ORS 338" — and that quote can never ground,
        # because half of it is scaffolding this file wrote rather than anything the
        # corpus says. Grounding must not be taught to accept our own words, so the
        # rendering has to make the quotable content be the VALUE.
        if r.get("declares"):
            parts += ["declared statutes_implemented (frontmatter, not operative text). "
                      "If you quote this, quote ONLY the line below, not this heading:",
                      r["declares"], ""]
        parts += [r["text"]]
    return "\n".join(parts)


_JSON_RE = re.compile(r"```json\s*(.+?)\s*```", re.S)


def parse_reply(text: str) -> list:
    """Tolerant extraction. A model that wraps its JSON in prose, or emits a bare object,
    should not cost a whole bundle — but a reply we cannot parse must be loud, never
    silently treated as 'no candidates found'. That distinction matters: absence of
    findings is itself a reported result here."""
    m = _JSON_RE.search(text)
    raw = m.group(1) if m else text.strip()
    if not raw.startswith("{"):
        i, j = raw.find("{"), raw.rfind("}")
        if i == -1 or j == -1:
            raise ValueError(f"no JSON object in reply: {text[:200]!r}")
        raw = raw[i:j + 1]
    return json.loads(raw).get("candidates", [])


# --------------------------------------------------------------------------- backends

def api_custom_id(custom_id: str) -> str:
    """A bundle's custom_id in the form the Batch API accepts: `^[a-zA-Z0-9_-]{1,64}$`.

    Our ids are `ors-183.341#0` — section, then part — and both the '.' and the '#'
    are rejected, so **the batch path had never successfully submitted anything**; it
    400'd on request 0 after building every bundle. The sync path was unaffected
    because it never sends a custom_id at all, which is why nine months of measurement
    happened on the expensive-per-token path.

    Applied on BOTH sides. collect() maps results back through this same function
    rather than inverting it, so no reverse parse is needed and no assumption is made
    about which characters survived. Long ids keep a hash tail because truncation alone
    would collide `ors-183.341#0` with `ors-183.341#1` at exactly the wrong moment —
    silently merging two parts of one oversized section."""
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", custom_id)
    if len(safe) > 64:
        safe = safe[:55] + "_" + hashlib.sha256(custom_id.encode()).hexdigest()[:8]
    return safe


class ClaudeBatchBackend:
    """Anthropic Batch API. 50% off list, <=100k requests per batch."""
    name = "claude"

    def __init__(self, model: str, system: str | None = None,
                 prompt_version: str | None = None, thinking: int = 0):
        self.model = model
        try:
            import anthropic
        except ImportError:
            sys.exit("--backend claude needs the Anthropic SDK: pip install anthropic")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("--backend claude needs ANTHROPIC_API_KEY in the environment.")
        self.anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.system = system or SYSTEM
        self.prompt_version = prompt_version or PROMPT_VERSION
        # Accepted as a parameter but never stored, so `--backend claude --thinking N`
        # raised AttributeError inside submit() — after the bundles were built and
        # immediately before the paid call. The batch path had never been run with
        # thinking on; the sync path had the mirror-image defect (#59).
        self.thinking = thinking

    def submit(self, bundles: list) -> str:
        # EXTENDED THINKING, off unless asked for. The conflict question is exactly the
        # shape reasoning helps with — hold a statute provision and several rules in mind
        # at once and decide whether they actually contradict — and the pilot's recorded
        # weakness was a cheap model UNDER-reporting rather than hallucinating.
        #
        # Two API constraints, both enforced here rather than discovered as a 400:
        #   * max_tokens must exceed budget_tokens, since thinking is drawn from the same
        #     budget as the reply
        #   * temperature must be 1 when thinking is on, so it is simply not sent
        #
        # collect() already keeps only `type == "text"` blocks, so thinking blocks are
        # dropped rather than parsed as JSON.
        extra = {}
        if self.thinking:
            extra["thinking"] = {"type": "enabled", "budget_tokens": self.thinking}
        max_tokens = max(8000, self.thinking + 4000) if self.thinking else 8000
        reqs = [{
            "custom_id": api_custom_id(b["custom_id"]),
            "params": {
                "model": self.model,
                "max_tokens": max_tokens,
                **extra,
                # Cache the shared instruction prefix across every request in the batch.
                "system": [{"type": "text", "text": self.system,
                            "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": render_user(b)}],
            },
        } for b in bundles]
        batch = self.client.messages.batches.create(requests=reqs)
        return batch.id

    def collect(self, batch_id: str, bundles: list | None = None) -> dict:
        # Results come back under the SANITISED id, so map each one home through the
        # same function that produced it. Without `bundles` the raw api id is returned
        # and every downstream lookup by real custom_id misses.
        home = {api_custom_id(b["custom_id"]): b["custom_id"] for b in (bundles or [])}
        out, failed = {}, []
        # Keyed by custom_id, never by position — the API makes no ordering promise.
        for result in self.client.messages.batches.results(batch_id):
            cid = home.get(result.custom_id, result.custom_id)
            if result.result.type != "succeeded":
                failed.append((cid, result.result.type))
                continue
            text = "".join(b.text for b in result.result.message.content
                           if getattr(b, "type", "") == "text")
            try:
                out[cid] = parse_reply(text)
            except (ValueError, json.JSONDecodeError) as e:
                failed.append((cid, f"unparseable: {e}"))
        if failed:
            print(f"WARNING: {len(failed)} request(s) did not yield usable output; those "
                  "sections are NOT analyzed and are left absent rather than recorded as "
                  "clean:", file=sys.stderr)
            for cid, why in failed[:20]:
                print(f"  {cid}: {why}", file=sys.stderr)
        return out



class ClaudeSyncBackend:
    """Claude over the ordinary Messages API, one request at a time.

    WHY THIS EXISTS ALONGSIDE THE BATCH BACKEND. Batch is half price and right for a bulk
    pass, but it is submit-then-collect with no latency guarantee — useless for an
    experiment where the whole point is a fast read on whether a prompt change moved
    recall. This runs inline, so a 9-bundle eval answers in a minute.

    Same interface, same parsing, same retry-once-with-force-JSON behaviour as the local
    backend, so results are directly comparable across backends rather than confounded by
    how the reply was extracted.
    """
    name = "claude-sync"

    def __init__(self, model: str, system: str | None = None,
                 prompt_version: str | None = None, thinking: int = 0,
                 max_tokens: int = 8000):
        try:
            import anthropic
        except ImportError:
            sys.exit("--backend claude-sync needs the Anthropic SDK: pip install anthropic")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("--backend claude-sync needs ANTHROPIC_API_KEY in the environment.")
        self.client = anthropic.Anthropic()
        self.system = system or SYSTEM
        self.model = model
        self.prompt_version = prompt_version or PROMPT_VERSION
        self.thinking = thinking
        # Thinking draws on the same budget as the reply, so the ceiling must clear it.
        self.max_tokens = max(max_tokens, thinking + 4000) if thinking else max_tokens

    def submit(self, bundles):
        raise SystemExit("--backend claude-sync runs inline; use it without --submit/--collect.")

    def _once(self, bundle: dict) -> str:
        kw = {"model": self.model, "max_tokens": self.max_tokens,
              # Cached so repeated arms of an experiment do not pay for the prefix each time.
              "system": [{"type": "text", "text": self.system,
                          "cache_control": {"type": "ephemeral"}}],
              "messages": [{"role": "user", "content": render_user(bundle)}]}
        if self.thinking:
            # temperature must be 1 with thinking on, so it is simply not sent.
            kw["thinking"] = {"type": "enabled", "budget_tokens": self.thinking}
        msg = self.client.messages.create(**kw)
        # Keep TEXT blocks only: with thinking on the reply also carries thinking blocks,
        # and concatenating those would hand unparseable prose to the JSON parser.
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    def analyze(self, bundles: list):
        out, status = {}, {}
        for i, b in enumerate(bundles, 1):
            cid = b["custom_id"]
            try:
                text = self._once(b)
                out[cid] = parse_reply(text)
                status[cid] = {"state": "ok", "attempts": 1,
                               "n_candidates": len(out[cid])}
            except (ValueError, json.JSONDecodeError) as e:
                status[cid] = {"state": "parse_failed", "detail": str(e)[:160],
                               "attempts": 1}
            except Exception as e:                                   # noqa: BLE001
                status[cid] = {"state": "error", "detail": f"{type(e).__name__}: {e}"[:160]}
            st = status[cid]["state"]
            print(f"  [{i}/{len(bundles)}] {cid} ({b['est_tokens']:,} tok) "
                  f"{status[cid].get('n_candidates', 0)} cand"
                  + ("" if st == "ok" else f"  <-- {st}"), file=sys.stderr)
        return out, status


# Backends that do their work in one invocation. `claude` is the odd one out — it is
# submit-then-collect, so with no --submit/--collect there is genuinely nothing to do but
# price the run. Anything not listed here is treated as batch, and that default is what
# made `--backend claude-sync` print a cost estimate and exit 0 having called nothing:
# a run indistinguishable from a successful one, except that no analysis happened.
# Module-level so selftest can check it against what the classes actually do.
INLINE_BACKENDS = {"local", "claude-sync"}


class LocalBackend:
    """Any OpenAI-compatible local server (ollama, llama.cpp --server, vLLM).

    stdlib HTTP on purpose: the point of this backend is free prompt iteration, so it must
    not drag in a dependency the Claude path doesn't need."""
    name = "local"

    def __init__(self, model: str, base_url: str, max_tokens: int = 8000,
                 timeout: int = 900, system: str | None = None):
        self.model = model
        self.system = system or LOCAL_SYSTEM
        self.url = base_url.rstrip("/") + "/chat/completions"
        # Without a cap a small model can ramble past the useful answer and burn minutes
        # per bundle. 4k is generous for the JSON this prompt asks for.
        self.max_tokens = max_tokens
        self.timeout = timeout

    def submit(self, bundles):
        raise SystemExit("--backend local runs inline; use it without --submit/--collect.")

    def _once(self, bundle: dict, force_json: bool) -> str:
        payload = {
            "model": self.model, "temperature": 0,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "system", "content": self.system},
                         {"role": "user", "content": render_user(bundle)}],
        }
        if force_json:
            # ollama and most OpenAI-compatible servers honour this; a server that does
            # not simply ignores it, so it is safe to send unconditionally on a retry.
            payload["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]

    def run(self, bundles: list) -> tuple[dict, dict]:
        """(results, status). Returns BOTH, and that is the point.

        The previous version swallowed every failure into a stderr line and dropped the
        bundle from `results` entirely — which makes a section that errored
        indistinguishable from a section the model read and found clean. For a
        measurement run that is fatal: failures would silently inflate the clean rate and
        deflate the denominator, and the summary would look better the more often the
        model broke. Status is now recorded per bundle so failed sections can be excluded
        from rates rather than counted as findings of nothing.

        Small models break strict JSON often enough that one retry with an explicit
        json_object request is worth it; beyond that the bundle is recorded as
        parse_failed rather than retried indefinitely."""
        out: dict = {}
        status: dict = {}
        for i, b in enumerate(bundles, 1):
            cid = b["custom_id"]
            for attempt, force_json in enumerate((False, True)):
                try:
                    text = self._once(b, force_json)
                except Exception as e:                   # noqa: BLE001 — recorded, not hidden
                    status[cid] = {"state": "error", "detail": str(e)[:160],
                                   "attempts": attempt + 1}
                    break
                try:
                    out[cid] = parse_reply(text)
                    status[cid] = {"state": "ok", "attempts": attempt + 1,
                                   "n_candidates": len(out[cid])}
                    break
                except (ValueError, json.JSONDecodeError) as e:
                    status[cid] = {"state": "parse_failed", "detail": str(e)[:160],
                                   "attempts": attempt + 1, "raw_head": text[:200]}
            st = status[cid]["state"]
            mark = "" if st == "ok" else f"  <-- {st}"
            print(f"  [{i}/{len(bundles)}] {cid} ({b['est_tokens']:,} tok) "
                  f"{status[cid].get('n_candidates', 0)} cand{mark}", file=sys.stderr)
        return out, status


def _report_status(status: dict) -> None:
    """Say plainly how many bundles the model actually answered.

    Printed even when everything succeeded, because the number that matters to a reader
    of the results is not "how many candidates" but "out of how many sections the model
    genuinely read". A run that errored on half its bundles and found nothing is not a
    clean corpus."""
    by = collections.Counter(v["state"] for v in status.values())
    total = len(status)
    ok = by.get("ok", 0)
    print(f"\nbundles: {total} · ok {ok} · parse_failed {by.get('parse_failed', 0)} · "
          f"error {by.get('error', 0)}", file=sys.stderr)
    if ok < total:
        print("  NOT-ok bundles are excluded from any rate computed downstream — they are "
              "sections the model did not read, not sections it found clean.",
              file=sys.stderr)
        for cid, v in list(status.items())[:10]:
            if v["state"] != "ok":
                print(f"    {cid}: {v['state']} — {v.get('detail', '')[:90]}", file=sys.stderr)


# --------------------------------------------------------------------------- merge

def _contained_match(new_pairs: frozenset, prior: list) -> tuple:
    """Find the prior candidate that is the SAME finding as `new_pairs`, cited with a
    different amount of supporting detail. Returns (candidate, extra_pairs) or (None, []).

    Why containment and not overlap (#58). Two runs found the identical public-indecency
    conflict in ORS 163.465; one cited the two operative provisions, the other cited those
    plus a supporting definition. Exact-set identity stored them twice and, worse, gave the
    duplicate a fresh `unreviewed` triage — the precise outcome candidate_fingerprint's
    docstring says it exists to prevent. Mere overlap would be too loose: sharing one
    citation is common between genuinely distinct findings in the same section.

    Three rules keep this from over-merging:

    1. One set must CONTAIN the other. This is what protects the case that refuted the
       original id-only design — ORS 435's two findings over the same document pair,
       (3) vs (6) and (1)(c) vs (1)(c). Neither contains the other, so they stay distinct.
    2. THE SHARED SET MUST BE AT LEAST TWO PAIRS. Containment says nothing when the
       smaller set has one element, because a one-element set is a subset of every set
       that happens to contain it — that is not containment, it is the bare overlap this
       function refuses on purpose. Reproduced, not hypothesised: gemma4:e2b v3 reported
       "the implementing rule provides specific procedural details regarding complaints
       and fund withholding" citing ORS 332.158(4) ALONE, and merge_into_catalog folded it
       into the pilot's separate wrong-authority finding over the same subsection — stamped
       `corroborated_by` and handed it the pilot record's `dismissed` verdict. Two
       independent models agreeing is the strongest signal this pipeline has; manufacturing
       it from a vague single-citation candidate poisons the one number that matters.
       A statute-vs-rule conflict IS a pair of provisions, so agreeing on two is the
       weakest evidence of sameness worth acting on.
    3. AMBIGUITY DECLINES TO MERGE. If more than one prior candidate is in a containment
       relation with the new one, we cannot tell which finding it corroborates, and
       picking arbitrarily would attach a human's triage decision to the wrong claim.
       Returning None costs a duplicate, which is visible; guessing costs a wrong
       dismissal, which is not.

    Containment here is non-strict (<=), and that matters only to `dedupe_catalog`. Since
    #63 dropped citation prose from the key, two records ALREADY in the catalog can have
    identical pair sets — the three ORS 332.158 / OAR 581-026-0600 records do. Nothing
    else can fold those: `merge_into_catalog` catches an equal set by fingerprint before
    it ever gets here, but `dedupe_catalog` has no fingerprint path, and an unfolded pair
    trips `validate_envelope`'s duplicate-fingerprint gate and takes the whole cache
    build down. Strict `<` was tried first and left the catalog unbuildable.

    Measured before adopting: over the whole catalog — 153 candidates, 60 chapters — this
    produces exactly the two ORS 332 folds #63 describes, and no others. Rule 2 changes
    none of them; it was added because dropping citation prose is what let a one-citation
    candidate become a subset of a two-citation one in the first place.
    """
    if not new_pairs:
        return None, []
    hits = [c for pairs, c in prior
            if len(pairs) >= 2 and len(new_pairs) >= 2
            and (pairs <= new_pairs or new_pairs <= pairs)]
    if len(hits) != 1:
        return None, []
    kept = next(pairs for pairs, c in prior if c is hits[0])
    return hits[0], sorted(new_pairs - kept)


def dedupe_catalog(cat: dict) -> list:
    """Retro-apply containment merging to candidates ALREADY stored (#58, #63).

    Fixing the merge stops new duplicates; it does not repair the ones written before the
    fix, and a duplicate that stays in the catalog keeps its second, independent triage
    slot — the exact harm. This walks each chapter in stored order, which is discovery
    order, and folds a later entry into the earlier one it contains, is contained by, or
    now equals.

    "Now equals" is the #63 case and it is not optional housekeeping: once citation prose
    left the key, three ORS 332 records became one fingerprint, and an unfolded duplicate
    fingerprint is a hard SystemExit in `validate_envelope`. The two causes are reported
    separately — a merge caused by extra citations and a merge caused by reworded prose
    are different claims, and a reader should not have to diff pair sets to tell which
    one just happened.

    It REFUSES to absorb an entry carrying a human verdict. Two records that a person
    triaged separately are two decisions; silently keeping one of them is a data loss no
    reviewer asked for. Those are reported and left alone for a human to resolve."""
    merges = []
    for ch in cat.get("chapters") or []:
        keep: list = []
        for c in ch.get("candidates") or []:
            pairs = candidate_pairs(c)
            hit, extra = _contained_match(
                pairs, [(candidate_pairs(k), k) for k in keep])
            status = ((c.get("triage") or {}).get("status") or "unreviewed").lower()
            if hit is None:
                keep.append(c)
                continue
            if status != "unreviewed":
                keep.append(c)
                merges.append((ch["ors_chapter"], "DECLINED — carries a human verdict "
                               f"({status})", str(c.get("summary", ""))[:70]))
                continue
            corr = hit.setdefault("corroborated_by", [])
            stamp = {"run_id": c.get("run_id"), "model": c.get("model")}
            if extra:
                stamp["also_cited"] = sorted(extra)
            if stamp not in corr:
                corr.append(stamp)
            why = ("merged (same provisions, reworded citation)"
                   if candidate_pairs(hit) == pairs else
                   "merged (same finding, extra supporting citation)")
            merges.append((ch["ors_chapter"], why, str(c.get("summary", ""))[:70]))
        ch["candidates"] = keep
    return merges


def merge_into_catalog(results: dict, bundles: list, run_id: str, model: str,
                       prompt_version: str | None = None, supersede: bool = False) -> dict:
    """Fold new candidates into the catalog, PRESERVING existing triage.

    Triage carries over by fingerprint (chapter + the set of cited document/subsection
    pairs). Without that, a second pass re-surfaces everything a human already dismissed,
    and the review queue never converges — which is the whole reason B2 came before this.
    A candidate that a human confirmed or dismissed keeps that verdict even when the new
    run words its summary differently."""
    cat = yaml.safe_load(CATALOG.read_text())
    by_id = {b["custom_id"]: b for b in bundles}

    prior = {}
    for ch in cat["chapters"]:
        for cand in ch.get("candidates") or []:
            prior[candidate_fingerprint(ch["ors_chapter"], cand)] = cand.get("triage")

    fresh = collections.defaultdict(list)
    for cid, cands in results.items():
        b = by_id.get(cid)
        if b is None:
            continue
        for c in cands:
            entry = {
                "summary": c.get("summary", ""),
                # v3 asks which of the eight checks fired; v2 has no such field.
                "type": c.get("type"),
                "documents": c.get("documents") or [],
                "run_id": run_id,
                "model": model,
                "prompt_version": prompt_version or PROMPT_VERSION,
                "confidence": c.get("confidence"),
                "severity": c.get("severity"),
                "section": b["section"],
                "triage": {"status": "unreviewed", "note": None, "by": None, "date": None},
            }
            if b["partial"]:
                entry["partial"] = True
                entry["note"] = (
                    f"Found in part {b['part'] + 1} of {b['n_parts']} for {b['section']}: "
                    "this section's implementing rules exceeded one context window, so "
                    "rules were compared within a subset only.")
            fp = candidate_fingerprint(b["ors_chapter"], entry)
            if fp in prior and prior[fp]:
                entry["triage"] = prior[fp]          # human verdict survives re-analysis
            fresh[b["ors_chapter"]].append(entry)

    existing = {str(ch["ors_chapter"]): ch for ch in cat["chapters"]}
    analyzed_chapters = {b["ors_chapter"] for b in bundles if b["custom_id"] in results}
    for chapter in sorted(analyzed_chapters):
        cands = fresh.get(chapter, [])
        ch = existing.get(chapter)
        if ch is None:
            cat["chapters"].append({
                "ors_chapter": chapter, "run_id": run_id,
                "rules_reviewed": sum(len(b["rules"]) for b in bundles
                                      if b["ors_chapter"] == chapter),
                "candidates": cands,
            })
        elif supersede:
            # EXPLICIT, DESTRUCTIVE. Only for a deliberate supersession of a weaker run by
            # a stronger one — the catalog's own history has a real instance: batch 3
            # (Sonnet) superseding batch 2 (Haiku) on 13 chapters after a measured recall
            # gap. Everything this run did not rediscover is DROPPED.
            ch["run_id"] = run_id
            ch["candidates"] = cands
        else:
            # UNION — a re-run may ADD but never REMOVE.
            #
            # This branch used to be `ch["candidates"] = cands`, which silently dropped
            # every prior finding the new run failed to rediscover. That is a data-loss
            # bug whenever a WEAKER model re-covers a chapter, and the recall gap making
            # it likely is documented in this file's own methodology: Haiku found ~3x
            # fewer candidates than Sonnet on identical chapters. A planned 12B local pass
            # over 12 already-covered chapters would have destroyed 25 of the catalog's
            # 137 candidates, with no error anywhere and the run reporting success.
            #
            # Deduping is by fingerprint, so re-running the SAME analysis is idempotent —
            # which was the original comment's stated worry ("appending would duplicate
            # every finding") and is handled without paying for it in lost data.
            prior_by_fp, prior_pairs = {}, []
            for c in ch.get("candidates") or []:
                prior_by_fp.setdefault(candidate_fingerprint(chapter, c), c)
                p = candidate_pairs(c)
                if p:
                    prior_pairs.append((p, c))
            added = []
            for c in cands:
                fp = candidate_fingerprint(chapter, c)
                hit = prior_by_fp.get(fp)
                extra: list = []
                if hit is None:
                    hit, extra = _contained_match(candidate_pairs(c), prior_pairs)
                if hit is None:
                    added.append(c)
                    continue
                # Independently rediscovered. Keep the ORIGINAL entry — its provenance and
                # triage are the ones a human reviewed — and record the corroboration,
                # because two models arriving at the same finding is real signal.
                corr = hit.setdefault("corroborated_by", [])
                stamp = {"run_id": run_id, "model": model}
                if extra:
                    # Cited the same conflict with extra support. Record what it added,
                    # but do NOT merge it into hit["documents"]: those pairs ARE the
                    # fingerprint, so editing them would change the entry's identity and
                    # detach the triage this branch exists to preserve.
                    stamp["also_cited"] = sorted(extra)
                if stamp not in corr:
                    corr.append(stamp)
            ch["candidates"] = (ch.get("candidates") or []) + added
            # Chapter-level run_id is the LAST run to touch the chapter. Per-candidate
            # run_id/model is the authoritative provenance; nothing reads this one.
            ch["run_id"] = run_id
    cat["chapters"].sort(key=lambda c: str(c["ors_chapter"]))
    return cat


# --------------------------------------------------------------------------- cli

def selftest() -> int:
    """Prove the merge cannot silently drop a prior run's candidates.

    The regression this guards: `ch["candidates"] = cands` replaced an already-covered
    chapter's findings wholesale, so any re-run that failed to rediscover something
    deleted it — no error, run reports success. A 12B local pass over 12 covered chapters
    would have destroyed 25 of the catalog's 137 candidates.

    Runs against synthetic bundles/results, so it needs no model, no network and no
    catalog write, and is safe in CI.
    """
    import copy, tempfile, os
    global CATALOG
    fails = []

    def candidate(doc, cite):
        return {"summary": f"finding about {doc}", "documents": [{"id": doc, "citation": cite}]}

    base = {"schema_version": 2, "chapters": [
        {"ors_chapter": "291", "run_id": "pilot", "candidates": [
            {**candidate("oar-125-055-0010", "OAR 125-055-0010(3)"),
             "run_id": "pilot", "model": "sonnet",
             "triage": {"status": "dismissed", "note": "checked", "by": "@dzinck", "date": "2026-07-01"}},
            {**candidate("oar-125-055-0020", "OAR 125-055-0020(1)"),
             "run_id": "pilot", "model": "sonnet", "triage": {"status": "unreviewed"}},
        ]}]}

    def run(results_for_291, supersede=False):
        """Merge `results_for_291` into a fresh copy of `base` and return that chapter."""
        fd, path = tempfile.mkstemp(suffix=".yml"); os.close(fd)
        Path(path).write_text(yaml.safe_dump(copy.deepcopy(base)))
        saved = CATALOG
        try:
            globals()["CATALOG"] = Path(path)
            bundles = [{"custom_id": "c1", "ors_chapter": "291", "section": "ors-291.047",
                        "partial": False, "rules": []}]
            cat = merge_into_catalog({"c1": results_for_291}, bundles, "gemma-run",
                                     "gemma4:12b", "v2", supersede=supersede)
            return next(c for c in cat["chapters"] if c["ors_chapter"] == "291")
        finally:
            globals()["CATALOG"] = saved
            os.unlink(path)

    # 1. THE REGRESSION. A weak run that finds nothing must not delete anything.
    ch = run([])
    if len(ch["candidates"]) != 2:
        fails.append(f"empty re-run dropped candidates: {len(ch['candidates'])} left, want 2")

    # 2. A human verdict survives a re-run that did not rediscover the candidate.
    ch = run([])
    kept = ch["candidates"][0] if ch["candidates"] else None
    if kept is None or (kept.get("triage") or {}).get("status") != "dismissed":
        fails.append("triage lost on a candidate the re-run did not rediscover")

    # 3. A genuinely new finding is added.
    ch = run([candidate("oar-125-055-0030", "OAR 125-055-0030(2)")])
    if len(ch["candidates"]) != 3:
        fails.append(f"new candidate not added: {len(ch['candidates'])} present, want 3")

    # 4. Rediscovering an existing finding does not duplicate it, and is recorded.
    ch = run([candidate("oar-125-055-0010", "OAR 125-055-0010(3)")])
    if len(ch["candidates"]) != 2:
        fails.append(f"rediscovery duplicated a candidate: {len(ch['candidates'])}, want 2")
    elif not ch["candidates"][0].get("corroborated_by"):
        fails.append("rediscovery not recorded as corroboration")

    # 5. Rediscovery must not overwrite the ORIGINAL run's provenance or triage.
    ch = run([candidate("oar-125-055-0010", "OAR 125-055-0010(3)")])
    c0 = ch["candidates"][0] if ch["candidates"] else {}
    if c0.get("model") != "sonnet" or (c0.get("triage") or {}).get("status") != "dismissed":
        fails.append("rediscovery overwrote the stronger run's provenance or triage")

    # 6. --supersede still replaces, because deliberate supersession is a real need.
    ch = run([], supersede=True)
    if ch["candidates"]:
        fails.append("--supersede did not replace")

    # 7. THE SILENT NO-OP. `--backend claude-sync` printed a cost estimate and exited 0
    #    for its entire existence, because the dry-run guard treated every backend except
    #    `local` as submit-then-collect. Nothing failed; the run simply analyzed nothing
    #    and said so in words easy to read as a successful dry-run you asked for.
    #    A backend that REFUSES --submit is by definition inline, so that fact and the
    #    INLINE_BACKENDS set are checked against each other here rather than both being
    #    maintained by hand and left to drift the next time a backend is added.
    import inspect
    for cls in (ClaudeSyncBackend, LocalBackend, ClaudeBatchBackend):
        refuses = "runs inline" in inspect.getsource(cls.submit)
        listed = cls.name in INLINE_BACKENDS
        if refuses != listed:
            fails.append(
                f"{cls.name}: submit() {'refuses' if refuses else 'works'}, but it is "
                f"{'' if listed else 'NOT '}in INLINE_BACKENDS. If the set is the wrong "
                "one, the run reports success having analyzed nothing")

    # 8. An inline branch must actually CALL its backend. Fixing #7 exposed the next
    #    layer: the claude-sync branch constructed ClaudeSyncBackend and never invoked
    #    analyze(), so `results` was unbound. The crash was the lucky outcome — had
    #    `results` been bound anywhere earlier, the run would have merged an empty
    #    result set into the catalog and reported success.
    src = inspect.getsource(main)
    branch = src.split('== "claude-sync"')
    if len(branch) > 1 and ".analyze(" not in branch[1][:400]:
        fails.append("main()'s claude-sync branch builds a backend but never calls "
                     "analyze(); the run cannot produce candidates")

    # 9. #58: the same finding cited with one EXTRA supporting provision must corroborate,
    #    not duplicate. Exact-set identity stored ORS 163.465's public-indecency conflict
    #    twice and handed the copy a fresh `unreviewed` triage.
    def cand2(a, b, extra=None):
        docs = [{"id": "ors-163.465", "citation": "ORS 163.465(2)(a)"} if a is None else a,
                {"id": "oar-736-010-0040", "citation": b}]
        if extra:
            docs.append({"id": "oar-736-010-0040", "citation": extra})
        return {"summary": "public indecency classification", "documents": docs}

    base163 = {"schema_version": 2, "chapters": [
        {"ors_chapter": "163", "run_id": "gemma", "candidates": [
            {**cand2(None, "oar-736-010-0040(1)"), "run_id": "gemma", "model": "gemma4:12b",
             "triage": {"status": "dismissed", "note": "checked", "by": "@dzinck",
                        "date": "2026-07-27"}}]}]}

    def run163(new_cands):
        fd, path = tempfile.mkstemp(suffix=".yml"); os.close(fd)
        Path(path).write_text(yaml.safe_dump(copy.deepcopy(base163)))
        saved = CATALOG
        try:
            globals()["CATALOG"] = Path(path)
            bundles = [{"custom_id": "c1", "ors_chapter": "163", "section": "ors-163.465",
                        "partial": False, "rules": []}]
            cat = merge_into_catalog({"c1": new_cands}, bundles, "haiku", "haiku-4-5", "v4")
            return next(c for c in cat["chapters"] if c["ors_chapter"] == "163")
        finally:
            globals()["CATALOG"] = saved
            os.unlink(path)

    ch = run163([cand2(None, "OAR 736-010-0040(1)", extra="OAR 736-010-0040(11)(l)")])
    if len(ch["candidates"]) != 1:
        fails.append(f"an extra supporting citation duplicated the finding: "
                     f"{len(ch['candidates'])} candidates, want 1")
    elif (ch["candidates"][0].get("triage") or {}).get("status") != "dismissed":
        fails.append("the extra-citation re-run resurrected a dismissed finding")
    elif not any(s.get("also_cited") for s in ch["candidates"][0].get("corroborated_by") or []):
        fails.append("the extra citation was merged away without being recorded")

    # 10. Distinct findings must STILL not merge. Two fixtures, because the obvious one
    #     does not discriminate:
    #
    #     (a) the case that refuted the original id-only design — ORS 435's two findings
    #         over the same document pair, (3) vs (6) and (1)(c) vs (1)(c).
    #     (b) two findings that SHARE one cited provision and differ on the other.
    #
    #     Only (b) catches a containment test loosened to mere overlap. In (a) the
    #     subsections differ on BOTH sides, so the pair-sets are disjoint and even an
    #     overlap rule leaves them alone — writing only (a) yields a guard that passes
    #     whether the implementation is right or wrong. Verified by loosening
    #     `_contained_match` to `pairs & new_pairs` and confirming (b) fails.
    p = lambda a, b: {"summary": f"{a} vs {b}", "documents": [
        {"id": "ors-435.254", "citation": f"ORS 435.254{a}"},
        {"id": "oar-333-505-0120", "citation": f"OAR 333-505-0120{b}"}]}

    def distinct_stay_separate(prior_c, new_c, label):
        base = {"schema_version": 2, "chapters": [
            {"ors_chapter": "435", "run_id": "pilot", "candidates": [
                {**prior_c, "run_id": "pilot", "model": "sonnet",
                 "triage": {"status": "unreviewed"}}]}]}
        fd, path = tempfile.mkstemp(suffix=".yml"); os.close(fd)
        Path(path).write_text(yaml.safe_dump(base))
        saved = CATALOG
        try:
            globals()["CATALOG"] = Path(path)
            cat = merge_into_catalog(
                {"c1": [new_c]},
                [{"custom_id": "c1", "ors_chapter": "435", "section": "ors-435.254",
                  "partial": False, "rules": []}], "haiku", "haiku-4-5", "v4")
            ch = next(c for c in cat["chapters"] if c["ors_chapter"] == "435")
            if len(ch["candidates"]) != 2:
                fails.append(f"{label}: two distinct findings merged into "
                             f"{len(ch['candidates'])}; the match is over-broad")
        finally:
            globals()["CATALOG"] = saved
            os.unlink(path)

    distinct_stay_separate(p("(3)", "(6)"), p("(1)(c)", "(1)(c)"), "ORS 435 disjoint")
    distinct_stay_separate(p("(3)", "(6)"), p("(3)", "(9)"), "shared statute provision")

    # 11. Ambiguity must DECLINE to merge. With two priors each in a containment relation
    #     with the newcomer, there is no way to tell which finding it corroborates, and
    #     attaching a human's dismissal to the wrong claim is worse than a duplicate.
    #
    #     BOTH PRIORS CITE TWO PROVISIONS. They cited one each until the two-pair floor
    #     went in, at which point this fixture stopped being able to fail: the floor
    #     declined the merge before the ambiguity rule was ever consulted, so deleting
    #     `len(hits) != 1` outright still gave 17/17. Caught by running exactly that.
    amb = {"schema_version": 2, "chapters": [
        {"ors_chapter": "700", "run_id": "pilot", "candidates": [
            {"summary": "A", "documents": [{"id": "ors-700.1", "citation": "(1)"},
                                           {"id": "oar-700-1", "citation": "(2)"}],
             "run_id": "pilot", "model": "sonnet", "triage": {"status": "unreviewed"}},
            {"summary": "B", "documents": [{"id": "oar-700-1", "citation": "(2)"},
                                           {"id": "oar-700-2", "citation": "(3)"}],
             "run_id": "pilot", "model": "sonnet", "triage": {"status": "unreviewed"}}]}]}
    fd, path = tempfile.mkstemp(suffix=".yml"); os.close(fd)
    Path(path).write_text(yaml.safe_dump(amb))
    saved = CATALOG
    try:
        globals()["CATALOG"] = Path(path)
        cat = merge_into_catalog(
            {"c1": [{"summary": "A+B", "documents": [
                {"id": "ors-700.1", "citation": "(1)"},
                {"id": "oar-700-1", "citation": "(2)"},
                {"id": "oar-700-2", "citation": "(3)"}]}]},
            [{"custom_id": "c1", "ors_chapter": "700", "section": "ors-700.1",
              "partial": False, "rules": []}], "haiku", "haiku-4-5", "v4")
        ch = next(c for c in cat["chapters"] if c["ors_chapter"] == "700")
        if len(ch["candidates"]) != 3:
            fails.append(f"an ambiguous containment merged instead of declining: "
                         f"{len(ch['candidates'])} candidates, want 3")
    finally:
        globals()["CATALOG"] = saved
        os.unlink(path)

    # 12. #51: the tiers select different POPULATIONS, and every --tier choice must say
    #     which. Asserted as invariants rather than fixed counts, so a corpus refresh
    #     cannot turn this into a guard that only passed on one day's data.
    #     A tier with no stated meaning needs no check here: --tier builds its own help
    #     text from TIER_MEANING, so adding one without an entry raises KeyError while the
    #     parser is being constructed, before any command can run. Asserting it again in
    #     selftest would be a guard that cannot fire — it was written that way first, and
    #     the proof run showed the KeyError arriving before selftest was ever reached.
    graph = json.loads(GRAPH.read_text())
    cl = build_bundles(["163", "328", "332"], graph, "cluster")
    se = build_bundles(["163", "328", "332"], graph, "section")
    if not all(b["n_agencies"] >= 2 for b in cl):
        fails.append("--tier cluster returned a single-agency section; it is defined as "
                     "the inter-agency class and its cost estimate assumes that")
    if not {b["custom_id"] for b in cl} <= {b["custom_id"] for b in se}:
        fails.append("--tier cluster is not a subset of --tier section; the two tiers no "
                     "longer nest and no estimate taken at one bounds the other")

    # 13. Prompt versions are built by .replace() off the previous version, and a replace
    #     whose anchor text has drifted returns the string UNCHANGED. There is no error:
    #     the new version silently becomes a copy of the old one, the arm runs, and it is
    #     recorded under a version string promising a change it does not contain. Every
    #     measurement taken against it would be a rerun wearing a new label.
    if set(PROMPT_VERSIONS) != set(PROMPT_TEXTS):
        fails.append(f"PROMPT_VERSIONS and PROMPT_TEXTS disagree on which prompts exist: "
                     f"{set(PROMPT_VERSIONS) ^ set(PROMPT_TEXTS)}")
    seen: dict = {}
    for name, text in PROMPT_TEXTS.items():
        if text in seen:
            fails.append(f"prompt {name} is byte-identical to {seen[text]} — a .replace() "
                         "anchor no longer matches, so this version is a silent rerun")
        seen[text] = name
    #     Each replace is asserted by its OWN effect. Testing for the bare string
    #     "wrong_authority" was the first attempt and it could not fail: the IGNORE-list
    #     amendment mentions the type by name, so that substring is present even when the
    #     replace defining the type never matched. The proof run caught it.
    for effect, why in (
            ("wrong_authority the rule DECLARES", "the type definition"),
            ("IS in scope — see wrong_authority", "the IGNORE-list amendment that stops "
                                                  "the new class being suppressed"),
            ("one of the nine above", "the reply-shape update")):
        if effect not in PROMPT_TEXTS["v5"]:
            fails.append(f"v5 is missing {why}; a .replace() anchor did not match and "
                         "that part of the version silently did not happen")

    # 14. v5's evidence change is the point of it — the declared authority must actually
    #     reach the model. A prompt naming a check over text the bundle never carries
    #     measures nothing, which is what v4 was unknowingly doing.
    declared = declared_authority({"statutes_implemented": ["ORS 332.158", "ORS 338"]})
    probe = {"section": "ors-332.158", "section_title": "t", "statute": "S", "partial": False,
             "part": 0, "n_parts": 1,
             "rules": [{"id": "oar-581-026-0600", "title": "r", "text": "body",
                        "declares": declared}]}
    rendered = render_user(probe)
    if "ORS 332.158, ORS 338" not in rendered:
        fails.append("render_user drops declared statutes_implemented; the wrong_authority "
                     "check would run against evidence the model cannot see")
    if "not operative text" not in rendered:
        fails.append("declared authority is rendered without distinguishing it from "
                     "operative text; a quote from it would be attributed to the rule body")

    # 15. #62: a faithful quote of that declaration must GROUND, and the label printed
    #     above it must not. The whole wrong_authority class was unverifiable by
    #     construction — quote_is_grounded searched extract_fulltext(body) only, which
    #     excludes frontmatter — so 26 candidates' worth of correct evidence read as
    #     fabricated, in the one metric used to decide whether a model can be trusted.
    #
    #     THE FULL TEXT IS DELIBERATELY EMPTY in every call below. Rules routinely recite
    #     their own authority in their operative text, so passing real rule text would let
    #     these pass with the frontmatter haystack removed — a guard that cannot fail.
    hay = fold(declared)
    if declared not in [ln.strip() for ln in rendered.splitlines()]:
        fails.append("the declared authority is not on a line of its own, so the model's "
                     "faithful quote includes the label we injected and can never ground "
                     "(#62: Haiku quoted exactly that label)")
    if not quote_is_grounded(declared, "", hay):
        fails.append("a verbatim quote of a rule's declared statutes_implemented does not "
                     "ground; every wrong_authority candidate reads as fabricated")
    if not quote_is_grounded("ORS 332.158", "", hay):
        fails.append("quoting ONE declared statute does not ground — the evidence-length "
                     "floor is rejecting a faithful quote of a short structured field")
    label = next((ln for ln in rendered.splitlines() if "not operative text" in ln), "")
    if quote_is_grounded(label, "", hay):
        fails.append("the injected 'declared statutes_implemented' label grounds; the "
                     "check is verifying a quote against words this pipeline wrote, not "
                     "against the corpus")
    if quote_is_grounded("ORS 999.999, ORS 111.111", "", hay):
        fails.append("a statute the rule does not declare grounds against its declaration; "
                     "the declared haystack matches anything")

    # 16. #63: the same conflict, in the same two provisions, cited with different PROSE
    #     must corroborate rather than duplicate. The pilot wrote "statutes_implemented",
    #     v5 wrote "declared statutes_implemented and rule title"; the pair-sets overlapped
    #     without either containing the other, so #58's containment guard correctly
    #     declined and the rediscovery was scored as a MISS (v5 4/7 instead of 5/7).
    def cand158(rule_citation):
        return {"summary": "charter schools excluded from ORS 332.158",
                "documents": [{"id": "ors-332.158", "citation": "ORS 332.158(4)"},
                              {"id": "oar-581-026-0600", "citation": rule_citation}]}

    def run332(new_cands, prior_citation="OAR 581-026-0600, statutes_implemented"):
        base = {"schema_version": 2, "chapters": [
            {"ors_chapter": "332", "run_id": "pilot", "candidates": [
                {**cand158(prior_citation), "run_id": "pilot", "model": "sonnet",
                 "triage": {"status": "dismissed", "note": "checked", "by": "@dzinck",
                            "date": "2026-07-28"}}]}]}
        fd, path = tempfile.mkstemp(suffix=".yml"); os.close(fd)
        Path(path).write_text(yaml.safe_dump(base))
        saved = CATALOG
        try:
            globals()["CATALOG"] = Path(path)
            cat = merge_into_catalog(
                {"c1": new_cands},
                [{"custom_id": "c1", "ors_chapter": "332", "section": "ors-332.158",
                  "partial": False, "rules": []}], "haiku-v5", "haiku-4-5", "v5")
            return next(c for c in cat["chapters"] if c["ors_chapter"] == "332")
        finally:
            globals()["CATALOG"] = saved
            os.unlink(path)

    ch = run332([cand158("OAR 581-026-0600, declared statutes_implemented and rule title")])
    if len(ch["candidates"]) != 1:
        fails.append(f"a reworded citation duplicated the finding: "
                     f"{len(ch['candidates'])} candidates, want 1")
    elif (ch["candidates"][0].get("triage") or {}).get("status") != "dismissed":
        fails.append("the reworded re-run resurrected a dismissed finding")
    elif not ch["candidates"][0].get("corroborated_by"):
        fails.append("the rediscovery was folded away without being recorded as "
                     "corroboration — the recall it proves is invisible")
    #     And the other direction, or the rule is just 'ignore the citation': a DIFFERENT
    #     subsection of the same rule is a different provision and must stay separate.
    ch = run332([cand158("OAR 581-026-0600(2)")])
    if len(ch["candidates"]) != 2:
        fails.append("citing a different subsection of the same rule merged into the "
                     "existing finding; the citation key has stopped carrying subsections")

    # 17. #63, retro half. Records ALREADY in the catalog whose pair sets became identical
    #     when prose left the key can only be folded by dedupe_catalog — merge_into_catalog
    #     never sees them. Leaving them is not cosmetic: two candidates sharing a
    #     fingerprint is a hard SystemExit in validate_envelope, so the cache build stops.
    cat17 = {"chapters": [{"ors_chapter": "332", "candidates": [
        {**cand158("OAR 581-026-0600, statutes_implemented"), "run_id": "pilot",
         "model": "sonnet", "triage": {"status": "unreviewed"}},
        {**cand158("OAR 581-026-0600 (entire rule)"), "run_id": "haiku-v4",
         "model": "haiku-4-5", "triage": {"status": "unreviewed"}}]}]}
    merges17 = dedupe_catalog(cat17)
    if len(cat17["chapters"][0]["candidates"]) != 1:
        fails.append("dedupe_catalog left two stored records with an identical pair set; "
                     "build_conflict_candidates_data.py cannot build this catalog")
    elif not any("reworded" in m[1] for m in merges17):
        fails.append("dedupe_catalog folded a reworded duplicate but reported it as an "
                     "extra-citation merge; the two causes are different claims")

    # 18. A candidate citing ONE provision must not be absorbed by a two-provision
    #     finding. Its pair set is a subset of every finding that cites that provision, so
    #     containment proves nothing about it — and #63's key change widened the exposure
    #     by removing the citation prose that used to keep such a candidate distinct.
    #     Real output, not invented: gemma4:e2b v3 on ors-332.158#0 reported a different
    #     claim about the same subsection, cited it alone, and was recorded as
    #     corroborating the pilot's wrong-authority finding while inheriting its verdict.
    ch = run332([{"summary": "the rule adds procedural detail about complaints",
                  "documents": [{"id": "ors-332.158", "citation": "ORS 332.158(4)"}]}])
    if len(ch["candidates"]) != 2:
        fails.append("a one-citation candidate was folded into a two-provision finding; "
                     "it inherits a human verdict it was never judged against, and "
                     "manufactures the corroboration signal the pipeline trusts most")
    elif any(s.get("run_id") == "haiku-v5"
             for s in ch["candidates"][0].get("corroborated_by") or []):
        fails.append("a one-citation candidate was stamped as corroborating a finding it "
                     "shares a single provision with")

    # 19. Every backend must actually STORE the constructor arguments it accepts.
    #     `ClaudeBatchBackend` took `thinking` and dropped it, so
    #     `--backend claude --thinking N` raised AttributeError inside submit() — after
    #     bundle assembly, one line before the paid call. Nothing caught it because the
    #     batch path had never been run with thinking on. Checked by construction rather
    #     than by calling submit(), so this needs no API key and no network.
    #     Checked by READING __init__, not by constructing one. The first version
    #     instantiated the backend and asked `hasattr`, which cannot work: both
    #     constructors `sys.exit` when ANTHROPIC_API_KEY is absent, and the handler for
    #     that skipped the assertion — so the guard passed identically whether the bug
    #     was present or not. It was caught by reverting the fix and seeing 19/19.
    import inspect
    for cls in (ClaudeBatchBackend, ClaudeSyncBackend, LocalBackend):
        src = inspect.getsource(cls.__init__)
        for p in set(inspect.signature(cls.__init__).parameters) - {"self"}:
            if not re.search(rf"self\.\w+\s*=[^=].*\b{re.escape(p)}\b", src):
                fails.append(f"{cls.__name__}.__init__ accepts `{p}` and never stores it "
                             "— the option is silently ignored, or raises at the point "
                             "of use, which for a paid backend is after the bundles are "
                             "built")

    # 20. Batch custom_ids must satisfy the API's `^[a-zA-Z0-9_-]{1,64}$`, and must stay
    #     DISTINCT after sanitising. Our real ids carry '.' and '#', so the batch path
    #     400'd on request 0 and had never submitted anything; the bug survived because
    #     every measurement to date ran on the sync path, which sends no custom_id.
    #     Collision matters as much as shape: `ors-183.341#0` and `#1` are two parts of
    #     one oversized section, and merging them would drop half a section's rules
    #     while reporting success.
    probe_ids = ["ors-183.341#0", "ors-183.341#1", "ors-279a.065#0",
                 "ors-98.410@oar-125-055-0010", "ors-" + "9" * 80 + ".100#12"]
    seen_api: dict = {}
    for cid in probe_ids:
        api = api_custom_id(cid)
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", api):
            fails.append(f"api_custom_id({cid!r}) -> {api!r}, which the Batch API rejects")
        if api in seen_api:
            fails.append(f"api_custom_id collides: {cid!r} and {seen_api[api]!r} both -> "
                         f"{api!r}; two bundles would share one result")
        seen_api[api] = cid
    if 'api_custom_id(b["custom_id"])' not in inspect.getsource(ClaudeBatchBackend.submit):
        fails.append("ClaudeBatchBackend.submit does not sanitise custom_id; the batch "
                     "will 400 before any request runs")
    if "api_custom_id" not in inspect.getsource(ClaudeBatchBackend.collect):
        fails.append("ClaudeBatchBackend.collect does not map the sanitised id back; "
                     "every result would be filed under an id no bundle has")

    for f in fails:
        print(f"FAIL {f}")
    print(f"merge selftest: {20 - len(fails)}/20 passed")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prompt", choices=sorted(PROMPT_VERSIONS), default="v2",
                    help="v2 = original; v3 = eight named semantic checks; v4 = v3 plus "
                         "an 'other' escape hatch; v5 = v4 plus wrong_authority, and the "
                         "bundle carries each rule's declared statutes_implemented")
    ap.add_argument("--backend", choices=["claude", "claude-sync", "local"],
                    default="claude",
                    help="claude = Batch API (half price, submit/collect); "
                         "claude-sync = ordinary Messages API, inline, for "
                         "experiments where latency matters more than cost")
    ap.add_argument("--model", default=None, help=f"default: {DEFAULT_MODEL} (claude)")
    ap.add_argument("--local-url", default="http://localhost:11434/v1",
                    help="OpenAI-compatible base url for --backend local")
    ap.add_argument("--max-context-tokens", type=int, default=MAX_BUNDLE_TOKENS,
                    help="per-bundle input budget. Default suits a frontier model; a "
                         "local 7B at 32k context wants roughly 24000, leaving room "
                         "for the instructions and the reply.")
    ap.add_argument("--tier", choices=TIERS, default="cluster",
                    help="; ".join(f"{t}: {TIER_MEANING[t]}" for t in TIERS))
    ap.add_argument("--chapters", help="comma-separated ORS chapters (default: all unanalyzed)")
    ap.add_argument("--limit", type=int, help="cap the number of bundles (dev)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would run — bundles, tokens, cost — and call nothing")
    ap.add_argument("--submit", action="store_true", help="create a Claude batch and exit")
    ap.add_argument("--collect", metavar="BATCH_ID", help="merge a finished Claude batch")
    ap.add_argument("--thinking", type=int, default=0, metavar="TOKENS",
                    help="extended-thinking budget for --backend claude (0 = off). The "
                         "conflict question is the shape reasoning helps with, and the "
                         "pilot's recorded weakness in a cheap model was UNDER-reporting, "
                         "not hallucination. Recorded per candidate so a thinking run "
                         "stays distinguishable from one without.")
    ap.add_argument("--run-id", default=f"run-{date.today().isoformat()}")
    ap.add_argument("--supersede", action="store_true",
                    help="DESTRUCTIVE: replace an already-covered chapter's candidates "
                         "instead of adding to them. Everything this run does not "
                         "rediscover is dropped. Only for a deliberate supersession of a "
                         "weaker run by a stronger one; the default is a safe union.")
    ap.add_argument("--selftest", action="store_true",
                    help="prove the merge cannot drop a prior run's candidates")
    ap.add_argument("--dedupe", action="store_true",
                    help="fold duplicates already in the catalog into their originals "
                         "(#58), print what changed and exit. Use --dry-run to preview.")
    args = ap.parse_args()

    if args.dedupe:
        cat = yaml.safe_load(CATALOG.read_text())
        before = sum(len(c.get("candidates") or []) for c in cat["chapters"])
        merges = dedupe_catalog(cat)
        after = sum(len(c.get("candidates") or []) for c in cat["chapters"])
        for chn, what, summary in merges:
            print(f"  ch {chn}: {what}\n      {summary}")
        print(f"\ncandidates: {before} -> {after}  "
              f"({sum(1 for m in merges if m[1].startswith('merged'))} folded, "
              f"{sum(1 for m in merges if m[1].startswith('DECLINED'))} declined)")
        if args.dry_run:
            print("nothing written — this is --dry-run.")
        elif before != after:
            CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True,
                                              width=100))
            print(f"wrote {CATALOG.relative_to(REPO_ROOT)}")
        else:
            print("no duplicates found; catalog unchanged.")
        sys.exit(0)

    if args.selftest:
        # sys.exit, NOT return: main() is called bare at the bottom of this module, so a
        # returned code is discarded and the gate would report failures while exiting 0 —
        # a check that cannot fail. Matches ingest_eo.py's convention.
        sys.exit(selftest())

    graph = json.loads(GRAPH.read_text())
    shared = shared_authority_chapters(graph)
    done = {str(ch["ors_chapter"]).lower() for ch in
            yaml.safe_load(CATALOG.read_text())["chapters"]}

    if args.chapters:
        chapters = [c.strip().lower() for c in args.chapters.split(",")]
    else:
        chapters = sorted(set(shared) - done)
    bundles = build_bundles(chapters, graph, args.tier, args.max_context_tokens)
    if args.limit:
        bundles = bundles[:args.limit]

    model = args.model or (DEFAULT_MODEL if args.backend.startswith("claude")
                           else "llama3.1:8b")

    if args.dry_run or not (args.submit or args.collect
                            or args.backend in INLINE_BACKENDS):
        tok = sum(b["est_tokens"] for b in bundles)
        split = [b for b in bundles if b["partial"]]
        print(f"shared-authority chapters: {len(shared)}  already analyzed: "
              f"{len(set(shared) & done)}  to analyze: {len(chapters)}")
        modes = collections.Counter(b["mode"] for b in bundles)
        # Say what this tier SELECTED, not just its name. `mode` is the bundle's SHAPE and
        # is the string "cluster" under --tier section too, so printing it alone invites
        # exactly the cross-tier comparison that produced #51.
        print(f"tier: {args.tier} — {TIER_MEANING[args.tier]}")
        n_multi = sum(1 for b in bundles if b.get("n_agencies", 0) >= 2)
        print(f"requests: {len(bundles):,}  "
              f"[{n_multi:,} multi-agency, {len(bundles) - n_multi:,} single-agency]  "
              f"shapes: {', '.join(f'{v:,} {k}' for k, v in sorted(modes.items()))}")
        print(f"input tokens (rough, 4 chars/token): {tok:,}")
        print(f"oversized sections split into parts: "
              f"{len({b['section'] for b in split})} sections -> {len(split)} bundles "
              "(rule-vs-rule comparison does not cross a split)")
        if bundles:
            big = max(bundles, key=lambda b: b["est_tokens"])
            print(f"largest single bundle: {big['custom_id']} at {big['est_tokens']:,} tokens")
        # Batch API is 50% off list; Opus 5 list input is $5/1M.
        print(f"\nrough Claude Batch input cost at $2.50/1M (Opus 5, batch): "
              f"${tok * 2.50 / 1e6:,.2f} (output extra)")
        print("\nnothing was called — this is --dry-run.")
        return

    # Resolve the prompt once, so the frontier and local paths and the recorded
    # provenance cannot drift apart. The local variant keeps v3's checks but not its
    # grading, which a 7B does not produce reliably (see LOCAL_SYSTEM).
    prompt_version = PROMPT_VERSIONS[args.prompt]
    sys_prompt = SYSTEM_V3 if args.prompt in ("v3", "v4", "v5") else SYSTEM
    local_prompt = PROMPT_TEXTS[args.prompt]
    # v4 differs from v3 only in the escape hatch, which lives in the LOCAL prompt text.
    # The frontier SYSTEM_V3 carries the same eight-type instruction, so v4 on a Claude
    # backend must use the local variant or the arm would silently be a v3 rerun.
    if args.prompt in ("v4", "v5"):
        sys_prompt = PROMPT_TEXTS[args.prompt]

    if args.backend == "claude-sync":
        backend = ClaudeSyncBackend(model, sys_prompt, prompt_version,
                                    thinking=args.thinking)
        results, status = backend.analyze(bundles)
        _report_status(status)
    elif args.backend == "claude":
        backend = ClaudeBatchBackend(model, sys_prompt, prompt_version, thinking=args.thinking)
        if args.submit:
            STATE.mkdir(parents=True, exist_ok=True)
            batch_id = backend.submit(bundles)
            (STATE / f"{batch_id}.json").write_text(json.dumps(
                {"batch_id": batch_id, "run_id": args.run_id, "model": model,
                 "prompt_version": prompt_version,
                 "bundles": [{k: v for k, v in b.items() if k not in ("statute", "rules")}
                             for b in bundles]}, indent=1))
            print(f"submitted batch {batch_id} ({len(bundles)} requests)\n"
                  f"collect with: python3 src/analyze_conflicts.py --collect {batch_id}")
            return
        results = backend.collect(args.collect, bundles)
    else:
        results, status = LocalBackend(model, args.local_url,
                                       system=local_prompt).run(bundles)
        _report_status(status)

    cat = merge_into_catalog(results, bundles, args.run_id, model, prompt_version,
                             supersede=args.supersede)
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    n = sum(len(v) for v in results.values())
    print(f"merged {n} candidate(s) from {len(results)} bundle(s) into "
          f"{CATALOG.relative_to(REPO_ROOT)}\n"
          "next: python3 src/build_conflict_candidates_data.py && "
          "python3 src/build_conflict_candidates.py")


if __name__ == "__main__":
    main()
