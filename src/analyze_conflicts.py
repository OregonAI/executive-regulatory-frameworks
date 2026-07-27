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
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT, extract_fulltext, parse_frontmatter
from enrich_oar import load_registry_by_chapter
from build_conflict_candidates_data import candidate_fingerprint

CATALOG = REPO_ROOT / "_meta/catalog/conflict-candidates.yml"
GRAPH = REPO_ROOT / "_meta/graph.json"
STATE = REPO_ROOT / "_meta/.cache/conflict-runs"      # gitignored; batch bookkeeping

PROMPT_VERSION = "conflict-v2-2026-07"
DEFAULT_MODEL = "claude-opus-5"
# Well inside every current context window, leaving room for the instructions and a long
# reply. Bundles above this are split.
MAX_BUNDLE_TOKENS = 150_000
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
                rules.append({"id": rid, "title": _title(rid, paths), "text": t})
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
        parts += [f"\n## {r['id']} — {r['title']}", "", r["text"]]
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

class ClaudeBatchBackend:
    """Anthropic Batch API. 50% off list, <=100k requests per batch."""
    name = "claude"

    def __init__(self, model: str):
        self.model = model
        try:
            import anthropic
        except ImportError:
            sys.exit("--backend claude needs the Anthropic SDK: pip install anthropic")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("--backend claude needs ANTHROPIC_API_KEY in the environment.")
        self.anthropic = anthropic
        self.client = anthropic.Anthropic()

    def submit(self, bundles: list) -> str:
        reqs = [{
            "custom_id": b["custom_id"],
            "params": {
                "model": self.model,
                "max_tokens": 8000,
                # Cache the shared instruction prefix across every request in the batch.
                "system": [{"type": "text", "text": SYSTEM,
                            "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": render_user(b)}],
            },
        } for b in bundles]
        batch = self.client.messages.batches.create(requests=reqs)
        return batch.id

    def collect(self, batch_id: str) -> dict:
        out, failed = {}, []
        # Keyed by custom_id, never by position — the API makes no ordering promise.
        for result in self.client.messages.batches.results(batch_id):
            cid = result.custom_id
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

def merge_into_catalog(results: dict, bundles: list, run_id: str, model: str) -> dict:
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
                "documents": c.get("documents") or [],
                "run_id": run_id,
                "model": model,
                "prompt_version": PROMPT_VERSION,
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
        else:
            # Re-analysis of an already-covered chapter REPLACES its candidates (triage
            # already carried across above). Appending would duplicate every finding.
            ch["run_id"] = run_id
            ch["candidates"] = cands
    cat["chapters"].sort(key=lambda c: str(c["ors_chapter"]))
    return cat


# --------------------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=["claude", "local"], default="claude")
    ap.add_argument("--model", default=None, help=f"default: {DEFAULT_MODEL} (claude)")
    ap.add_argument("--local-url", default="http://localhost:11434/v1",
                    help="OpenAI-compatible base url for --backend local")
    ap.add_argument("--max-context-tokens", type=int, default=MAX_BUNDLE_TOKENS,
                    help="per-bundle input budget. Default suits a frontier model; a "
                         "local 7B at 32k context wants roughly 24000, leaving room "
                         "for the instructions and the reply.")
    ap.add_argument("--tier", choices=["section", "cluster", "pairwise", "all"],
                    default="cluster",
                    help="cluster: multi-agency sections only (default, highest value per "
                         "token); pairwise: one rule vs its statute section; all: both")
    ap.add_argument("--chapters", help="comma-separated ORS chapters (default: all unanalyzed)")
    ap.add_argument("--limit", type=int, help="cap the number of bundles (dev)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would run — bundles, tokens, cost — and call nothing")
    ap.add_argument("--submit", action="store_true", help="create a Claude batch and exit")
    ap.add_argument("--collect", metavar="BATCH_ID", help="merge a finished Claude batch")
    ap.add_argument("--run-id", default=f"run-{date.today().isoformat()}")
    args = ap.parse_args()

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

    model = args.model or (DEFAULT_MODEL if args.backend == "claude" else "llama3.1:8b")

    if args.dry_run or not (args.submit or args.collect or args.backend == "local"):
        tok = sum(b["est_tokens"] for b in bundles)
        split = [b for b in bundles if b["partial"]]
        print(f"shared-authority chapters: {len(shared)}  already analyzed: "
              f"{len(set(shared) & done)}  to analyze: {len(chapters)}")
        modes = collections.Counter(b["mode"] for b in bundles)
        print(f"tier: {args.tier}  ->  requests: {len(bundles):,} "
              f"({', '.join(f'{v:,} {k}' for k, v in sorted(modes.items()))})")
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

    if args.backend == "claude":
        backend = ClaudeBatchBackend(model)
        if args.submit:
            STATE.mkdir(parents=True, exist_ok=True)
            batch_id = backend.submit(bundles)
            (STATE / f"{batch_id}.json").write_text(json.dumps(
                {"batch_id": batch_id, "run_id": args.run_id, "model": model,
                 "prompt_version": PROMPT_VERSION,
                 "bundles": [{k: v for k, v in b.items() if k not in ("statute", "rules")}
                             for b in bundles]}, indent=1))
            print(f"submitted batch {batch_id} ({len(bundles)} requests)\n"
                  f"collect with: python3 src/analyze_conflicts.py --collect {batch_id}")
            return
        results = backend.collect(args.collect)
    else:
        results, status = LocalBackend(model, args.local_url).run(bundles)
        _report_status(status)

    cat = merge_into_catalog(results, bundles, args.run_id, model)
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    n = sum(len(v) for v in results.values())
    print(f"merged {n} candidate(s) from {len(results)} bundle(s) into "
          f"{CATALOG.relative_to(REPO_ROOT)}\n"
          "next: python3 src/build_conflict_candidates_data.py && "
          "python3 src/build_conflict_candidates.py")


if __name__ == "__main__":
    main()
