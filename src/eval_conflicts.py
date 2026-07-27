#!/usr/bin/env python3
"""Measure a local model against the frontier-model conflict candidates.

The question this answers is "how well does a small local model do at this?", and it
answers it mechanically, because the alternative — reading the output and forming an
impression — cannot see what the model MISSED. A model that finds three plausible
things while silently missing thirty reads exactly like a good one.

Ground truth is the 2026-07 pilot: 137 candidates over 60 ORS chapters, produced by
Sonnet/Opus reading whole chapters. That is not a perfect oracle — the pilot is not
exhaustive and its own notes record a ~3x recall gap between models — so this reports
recall AGAINST IT, never "accuracy".

Four numbers, and the second is the one that decides usability:

  RECALL       rediscovered / reachable known candidates. Matched on
               candidate_fingerprint (chapter + the set of cited document/subsection
               pairs), which deliberately ignores summary wording, so a rediscovery
               phrased differently still counts.

  GROUNDING    fraction of the model's quotes that are actually present in the document
               they are attributed to. The frontier baseline is 213/268 = 79.5%. A model
               that invents quotes is unusable at ANY recall, because every candidate it
               produces then has to be checked by hand, which is the work this was
               supposed to save.

  VOLUME       candidates produced vs the pilot's, per chapter.

  HEALTH       ok / parse_failed / error per bundle. Reported first and loudly: a run
               that errored on half its bundles and "found nothing" is not a clean
               corpus, and a low candidate count must never be read as one.

REACHABILITY. A known candidate is only counted in the recall denominator if some
bundle actually contains every document it cites. Section-scoped bundles cannot see a
candidate spanning two ORS sections, and holding the model to a finding it was never
shown the evidence for would understate it. The unreachable ones are reported
separately rather than dropped silently.

  python3 src/eval_conflicts.py --dry-run              # bundle plan for the eval set
  python3 src/eval_conflicts.py --limit-chapters 10    # calibration run
  python3 src/eval_conflicts.py                        # full evaluation
"""
import argparse
import collections
import json
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT, extract_fulltext, parse_frontmatter
from build_conflict_candidates_data import (candidate_fingerprint, fold,
                                            looks_like_absence_claim, quote_is_grounded)
import analyze_conflicts as AC

CATALOG = REPO_ROOT / "_meta/catalog/conflict-candidates.yml"
GRAPH = REPO_ROOT / "_meta/graph.json"
OUT_DIR = REPO_ROOT / "_meta/.cache/conflict-eval"      # gitignored: a report, not corpus

# The frontier-model grounding rate over the same corpus, from _meta/conflict_candidates
# .json at the time this was written. The bar, not a target.
BASELINE_GROUNDING = 213 / 268


TAXONOMY = REPO_ROOT / "_meta/eval/pilot-taxonomy.json"


def load_taxonomy() -> tuple[dict, set]:
    """index -> hand-labelled type, plus the set of types code (not a model) owns.
    Absent file is not fatal: per-type recall is simply not reported."""
    if not TAXONOMY.is_file():
        return {}, set()
    d = json.loads(TAXONOMY.read_text())
    return d.get("labels", {}), set(d.get("mechanical_types", []))


def _per_type(known: dict, reach: set, hit: set) -> list:
    """Recall broken out by hand-labelled type. This is the whole point of the labels:
    an aggregate recall number cannot tell you WHICH check to rewrite, and a prompt
    change that helps one type while quietly costing another looks like noise without
    it. Mechanical types are shown but flagged — a model missing them is correct now,
    since detect_mechanical.py owns them."""
    _, mech = load_taxonomy()
    if not any(k.get("type") for k in known.values()):
        return []
    agg = {}
    for fp in reach:
        t = known[fp].get("type") or "unlabelled"
        d = agg.setdefault(t, [0, 0])
        d[1] += 1
        if fp in hit:
            d[0] += 1
    rows = ["RECALL BY TYPE   (mechanical types are detect_mechanical.py's job — a miss "
            "there is correct)"]
    for t, (h, n) in sorted(agg.items(), key=lambda kv: (-kv[1][1], kv[0])):
        tag = "code " if t in mech else "MODEL"
        rows.append(f"            {tag} {t:<14} {h}/{n}"
                    + (f"  ({100*h/n:.0f}%)" if n else ""))
    rows.append("")
    return rows


def known_candidates(cat: dict) -> dict:
    """fingerprint -> {chapter, summary, doc_ids, type} for every pilot candidate.

    The taxonomy is keyed by POSITION in this same flattened walk (chapters in file
    order, candidates within each), which is how the labels were produced. Keeping one
    iteration order is what lets a hand-label attach to a fingerprint at all."""
    labels, _ = load_taxonomy()
    out, i = {}, 0
    for ch in cat["chapters"]:
        for cand in ch.get("candidates") or []:
            fp = candidate_fingerprint(ch["ors_chapter"], cand)
            out[fp] = {"chapter": str(ch["ors_chapter"]),
                       "summary": cand.get("summary", ""),
                       "type": labels.get(str(i)),
                       "doc_ids": sorted({d["id"] for d in cand.get("documents") or []})}
            i += 1
    return out


def reachable(known: dict, bundles: list) -> tuple[set, set]:
    """(reachable, unreachable) fingerprints — reachable = some bundle holds every
    document the candidate cites, so the model had the evidence in front of it."""
    contents = [{b["section"]} | {r["id"] for r in b["rules"]} for b in bundles]
    ok, no = set(), set()
    for fp, k in known.items():
        (ok if any(set(k["doc_ids"]) <= c for c in contents) else no).add(fp)
    return ok, no


def grounding(results: dict, paths: dict) -> dict:
    """Quote-grounding over everything the model produced, using the same matcher the
    catalog gate uses — so the number is directly comparable to the 79.5% baseline."""
    cache: dict = {}

    def full_text(doc_id: str) -> str:
        if doc_id not in cache:
            p = paths.get(doc_id)
            if not p:
                cache[doc_id] = ""
            else:
                _, body = parse_frontmatter(REPO_ROOT / p)
                ft = extract_fulltext(body)
                cache[doc_id] = fold(ft) if ft else ""
        return cache[doc_id]

    n = g = absence = ungrounded = bad_id = 0
    examples = []
    for cands in results.values():
        for c in cands:
            for d in c.get("documents") or []:
                q, did = d.get("quote"), d.get("id")
                if not q:
                    continue
                n += 1
                ft = full_text(did)
                if not ft:
                    bad_id += 1          # cited a document that does not exist / has no text
                    continue
                if quote_is_grounded(q, ft):
                    g += 1
                elif looks_like_absence_claim(q):
                    absence += 1
                else:
                    ungrounded += 1
                    if len(examples) < 8:
                        examples.append((did, q[:110]))
    return {"n_quotes": n, "grounded": g, "absence": absence,
            "ungrounded": ungrounded, "bad_doc_id": bad_id, "examples": examples}


def normalize(cands: list) -> tuple[list, int]:
    """(well-formed candidates, malformed count).

    A small model does not reliably emit the shape it was shown. Observed in practice:
    `documents` entries arriving as bare strings instead of {id, citation, quote}
    objects, which crashed fingerprinting after an hour of GPU time. Malformed
    candidates are DROPPED AND COUNTED, never coerced — guessing which string was
    meant to be the id would invent a citation, which is the one thing this pipeline
    must not do."""
    good, bad = [], 0
    for c in cands or []:
        if not isinstance(c, dict):
            bad += 1
            continue
        docs = [d for d in (c.get("documents") or []) if isinstance(d, dict) and d.get("id")]
        if not docs:
            bad += 1
            continue
        good.append({**c, "documents": docs})
    return good, bad


def to_candidates(results: dict, bundles: list) -> dict:
    """custom_id -> [(fingerprint, candidate)] for what the model produced."""
    by_id = {b["custom_id"]: b for b in bundles}
    out = collections.defaultdict(list)
    for cid, cands in results.items():
        b = by_id.get(cid)
        if b is None:
            continue
        for c in cands:
            out[b["ors_chapter"]].append((candidate_fingerprint(b["ors_chapter"], c), c))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="qwen2.5:7b-instruct-q4_K_M")
    ap.add_argument("--local-url", default="http://localhost:11434/v1")
    ap.add_argument("--max-context-tokens", type=int, default=24000)
    ap.add_argument("--tier", choices=["section", "cluster", "pairwise", "all"],
                    default="section")
    ap.add_argument("--chapters",
                    help="comma-separated ORS chapters, for a candidate-dense subset "
                         "that two models can both be run over in reasonable time")
    ap.add_argument("--max-output-tokens", type=int, default=8000,
                    help="reply budget. Gemma 4 emits a separate `reasoning` channel that "
                         "consumed 3,880 tokens BEFORE its answer on a 2.6k-token bundle; "
                         "with too small a budget `content` comes back EMPTY and looks "
                         "exactly like a model that refused. 12000+ for reasoning models.")
    ap.add_argument("--limit-chapters", type=int,
                    help="calibrate on the first N eval chapters before the full run")
    ap.add_argument("--limit-bundles", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prompt", choices=["v2", "v3"], default="v2",
                    help="which local prompt to evaluate; run both to compare")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cat = yaml.safe_load(CATALOG.read_text())
    graph = json.loads(GRAPH.read_text())
    paths = {n["id"]: n["path"] for n in graph["nodes"]}

    chapters = [str(c["ors_chapter"]).lower() for c in cat["chapters"]]
    if args.chapters:
        want = {c.strip().lower() for c in args.chapters.split(",")}
        chapters = [c for c in chapters if c in want]
    if args.limit_chapters:
        chapters = chapters[:args.limit_chapters]
    known = {fp: k for fp, k in known_candidates(cat).items()
             if k["chapter"].lower() in set(chapters)}

    bundles = AC.build_bundles(chapters, graph, args.tier, args.max_context_tokens)
    if args.limit_bundles:
        bundles = bundles[:args.limit_bundles]
    reach, unreach = reachable(known, bundles)

    print(f"eval set: {len(chapters)} chapter(s), {len(known)} known candidate(s)")
    print(f"bundles: {len(bundles)}  (tier={args.tier}, budget={args.max_context_tokens:,} tok)")
    if bundles:
        toks = sorted(b["est_tokens"] for b in bundles)
        over = sum(1 for t in toks if t > args.max_context_tokens)
        print(f"  tokens p50={toks[len(toks)//2]:,} p90={toks[int(len(toks)*.9)]:,} "
              f"max={toks[-1]:,}  over budget: {over}")
        print(f"  split sections: {len({b['section'] for b in bundles if b['partial']})}")
    print(f"reachable known candidates: {len(reach)}  unreachable: {len(unreach)} "
          "(cited documents never co-occur in one bundle)")
    if args.dry_run:
        print("\nnothing was called — this is --dry-run.")
        return

    sys_prompt = AC.LOCAL_SYSTEM_V3 if args.prompt == "v3" else AC.LOCAL_SYSTEM
    results, status = AC.LocalBackend(args.model, args.local_url,
                                      max_tokens=args.max_output_tokens,
                                      system=sys_prompt).run(bundles)
    AC._report_status(status)

    # Persist the raw model output IMMEDIATELY, before any analysis touches it. A shape
    # bug in post-processing already destroyed one 60-minute run; inference is the
    # expensive, unrepeatable part and must never depend on the cheap part working.
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = OUT_DIR / f"raw-{args.prompt}-{date.today().isoformat()}.json"
    raw_path.write_text(json.dumps({"model": args.model, "prompt": args.prompt, "status": status,
                                    "results": results}, indent=1, ensure_ascii=False),
                        encoding="utf-8")
    print(f"raw model output saved: {raw_path}", file=sys.stderr)

    malformed = 0
    for cid in list(results):
        results[cid], bad = normalize(results[cid])
        malformed += bad

    produced = to_candidates(results, bundles)
    found = {fp for lst in produced.values() for fp, _ in lst}
    hit = reach & found
    ok_bundles = sum(1 for v in status.values() if v["state"] == "ok")
    gr = grounding(results, paths)

    lines = [
        "",
        "=" * 72,
        f"LOCAL-MODEL EVALUATION — {args.model}",
        "=" * 72,
        "",
        f"HEALTH      {ok_bundles}/{len(bundles)} bundles answered "
        f"({100*ok_bundles/max(len(bundles),1):.0f}%). Rates below cover only these.",
        "",
        f"RECALL      {len(hit)}/{len(reach)} reachable known candidates rediscovered "
        f"({100*len(hit)/max(len(reach),1):.1f}%)",
        f"            {len(unreach)} known candidate(s) unreachable by this bundling",
        "",
        *_per_type(known, reach, hit),
        f"GROUNDING   {gr['grounded']}/{gr['n_quotes']} quotes found in their cited source "
        f"({100*gr['grounded']/max(gr['n_quotes'],1):.1f}%)",
        f"            frontier baseline {BASELINE_GROUNDING*100:.1f}%  "
        f"| absence-claims {gr['absence']} | ungrounded {gr['ungrounded']} "
        f"| cited-nonexistent {gr['bad_doc_id']}",
        "",
        f"VOLUME      {sum(len(v) for v in produced.values())} candidate(s) produced "
        f"vs {len(known)} known, across {len(produced)} chapter(s)",
        f"NEW         {len(found - reach - unreach)} candidate(s) with no known "
        "counterpart (not necessarily wrong — the pilot is not exhaustive)",
        f"MALFORMED   {malformed} candidate(s) dropped for bad shape (documents not "
        "objects, or no usable id)",
    ]
    if gr["examples"]:
        lines += ["", "ungrounded quote examples (model asserted, source does not say):"]
        lines += [f"   {d}: {q!r}" for d, q in gr["examples"]]
    print("\n".join(lines))

    out = Path(args.out) if args.out else OUT_DIR / f"eval-{date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "model": args.model, "tier": args.tier,
        "max_context_tokens": args.max_context_tokens,
        "n_chapters": len(chapters), "n_bundles": len(bundles),
        "bundles_ok": ok_bundles,
        "known": len(known), "reachable": len(reach), "unreachable": len(unreach),
        "rediscovered": len(hit), "grounding": {k: v for k, v in gr.items() if k != "examples"},
        "produced": sum(len(v) for v in produced.values()), "malformed": malformed,
        "status": status,
        "results": {cid: c for cid, c in results.items()},
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nfull output: {out}")


if __name__ == "__main__":
    main()
