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
                     stdlib HTTP only, no extra dependency. For prompt iteration, not for
                     a coverage run: an 8B at 4-bit is not the quality path here.

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


def build_bundles(chapters: list, graph: dict, tier: str = "cluster") -> list:
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
        want_cluster = multi and tier in ("cluster", "all")
        want_pairs = tier in ("pairwise", "all") and not (multi and tier == "all")

        common = {"ors_chapter": chapter, "section": section,
                  "section_title": _title(section, paths), "statute": statute,
                  "n_agencies": len(agencies)}

        if want_cluster:
            budget = MAX_BUNDLE_TOKENS * CHARS_PER_TOKEN - len(statute)
            parts, cur, size = [], [], 0
            for r in rules:
                if cur and size + len(r["text"]) > budget:
                    parts.append(cur)
                    cur, size = [], 0
                cur.append(r)
                size += len(r["text"])
            if cur:
                parts.append(cur)
            for i, part in enumerate(parts):
                bundles.append({**common, "custom_id": f"{section}#{i}", "mode": "cluster",
                                "rules": part, "partial": len(parts) > 1,
                                "part": i, "n_parts": len(parts),
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

    def __init__(self, model: str, base_url: str):
        self.model = model
        self.url = base_url.rstrip("/") + "/chat/completions"

    def submit(self, bundles):
        raise SystemExit("--backend local runs inline; use it without --submit/--collect.")

    def run(self, bundles: list) -> dict:
        out = {}
        for i, b in enumerate(bundles, 1):
            body = json.dumps({
                "model": self.model, "temperature": 0,
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": render_user(b)}],
            }).encode()
            req = urllib.request.Request(self.url, data=body,
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=600) as r:
                    payload = json.loads(r.read())
                text = payload["choices"][0]["message"]["content"]
                out[b["custom_id"]] = parse_reply(text)
            except Exception as e:                       # noqa: BLE001 - report and continue
                print(f"  {b['custom_id']}: FAILED ({e})", file=sys.stderr)
            print(f"  [{i}/{len(bundles)}] {b['custom_id']} "
                  f"({b['est_tokens']:,} tok)", file=sys.stderr)
        return out


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
    ap.add_argument("--tier", choices=["cluster", "pairwise", "all"], default="cluster",
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
    bundles = build_bundles(chapters, graph, args.tier)
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
        results = LocalBackend(model, args.local_url).run(bundles)

    cat = merge_into_catalog(results, bundles, args.run_id, model)
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    n = sum(len(v) for v in results.values())
    print(f"merged {n} candidate(s) from {len(results)} bundle(s) into "
          f"{CATALOG.relative_to(REPO_ROOT)}\n"
          "next: python3 src/build_conflict_candidates_data.py && "
          "python3 src/build_conflict_candidates.py")


if __name__ == "__main__":
    main()
