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

GROUND TRUTH IS PINNED TO THAT RUN, not to the catalog (#65). The catalog is where scored
runs get MERGED, so reading `known` from the whole file meant an arm was credited for
rediscovering its own output and the denominator grew every time anyone analysed
anything: this eval set printed 7 known candidates when the v2/v3 table was built, 13 for
the qwen arm, and 16 once the v4 and v5 arms landed — one eval set, three numbers, no code
change between them. `--ground-truth-run` selects it and every report states which was
used.

Four numbers, and the second is the one that decides usability:

  RECALL       rediscovered / reachable known candidates. Matched on
               candidate_fingerprint (chapter + the set of cited document/subsection
               pairs), which deliberately ignores summary wording, so a rediscovery
               phrased differently still counts — and, since #65, through the same
               containment rule `merge_into_catalog` uses, so the catalog cannot record
               a corroboration that this scorer is calling a miss.

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
  python3 src/eval_conflicts.py --selftest             # CI gate: pinned truth, live labels
  python3 src/eval_conflicts.py --migrate-taxonomy REF # re-key hand labels (#64)
"""
import argparse
import collections
import json
import pathlib
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT
from build_conflict_candidates_data import (candidate_fingerprint, candidate_pairs,
                                            grounding_sources, looks_like_absence_claim,
                                            quote_is_grounded)
import analyze_conflicts as AC

CATALOG = REPO_ROOT / "_meta/catalog/conflict-candidates.yml"
GRAPH = REPO_ROOT / "_meta/graph.json"
OUT_DIR = REPO_ROOT / "_meta/.cache/conflict-eval"      # gitignored: a report, not corpus

# The frontier-model grounding rate over the same corpus, from _meta/conflict_candidates
# .json at the time this was written. The bar, not a target.
BASELINE_GROUNDING = 213 / 268


TAXONOMY = REPO_ROOT / "_meta/eval/pilot-taxonomy.json"

# The run whose candidates are the ground truth. PINNED, because the catalog is not a
# fixed set (#65): every scored run is merged into it, so taking `known` from the whole
# file means an arm is scored partly against its own output and the denominator moves
# under everyone. Measured: the 9-bundle eval set had 7 reachable knowns when the v2/v3
# comparison table was built, printed 13 for the qwen arm, and printed 16 once the v4 and
# v5 arms were merged. Three numbers, one eval set, no code change between them.
GROUND_TRUTH_RUN = "pilot-2026-07"


def load_taxonomy() -> tuple[dict, set]:
    """candidate fingerprint -> hand-labelled type, plus the set of types code (not a
    model) owns. Absent file is not fatal: per-type recall is simply not reported.

    KEYED BY FINGERPRINT, NOT POSITION (#64). The labels were originally an index into a
    flattened walk of the catalog, which was correct exactly once — on the day they were
    written. `merge_into_catalog` re-sorts `cat["chapters"]` by chapter number, and the
    catalog at the time of labelling was in discovery order (291, 215, 270, ...) rather
    than sorted order (105, 106, 107, ...). Measured against the labelling commit
    8723043e57: positional lookup lands on the correct candidate for **4 of 137** labels
    today. Not shifted — scrambled.

    A fingerprint key cannot go silently wrong the same way. If the identity function
    changes, or a labelled candidate is edited or folded away, its label stops resolving
    and `unresolved_labels()` says so; a label is then ABSENT rather than attached to
    someone else's finding, and an absent type reads as "unlabelled" instead of as a human
    judgement that was never made."""
    if not TAXONOMY.is_file():
        return {}, set()
    d = json.loads(TAXONOMY.read_text())
    return d.get("labels", {}), set(d.get("mechanical_types", []))


def unresolved_labels(known: dict) -> list:
    """Taxonomy labels that match no candidate in the ground-truth set.

    This is the guard the fingerprint key buys. Position-keying failed silently by
    construction — every index resolved to something. A fingerprint that resolves to
    nothing is the signal that the labels and the catalog have parted company, and it is
    reported rather than swallowed by `labels.get()`."""
    labels, _ = load_taxonomy()
    return sorted(set(labels) - set(known))


def _migration_refusals(fps: list, positional: dict, live: set) -> list:
    """Reasons a positional->fingerprint mapping cannot be built without guessing.

    Pure, and separate from `migrate_taxonomy`, so the selftest can exercise every refusal
    path. Inline, they were unreachable by any fixture — disabling the "labelled candidate
    has vanished" branch changed no test result, because no candidate has vanished yet.
    A refusal that only runs on data nobody has is a guard that cannot fire, and this
    repo has shipped four of those."""
    out = []
    if len(fps) != len(positional):
        out.append(f"{len(fps)} candidates but {len(positional)} labels — the positional "
                   "mapping this migration inverts does not hold at that commit")
    dupes = sorted({fp for fp in fps if fps.count(fp) > 1})
    if dupes:
        out.append(f"{len(dupes)} fingerprint(s) shared by two or more labelled "
                   f"candidates, e.g. {dupes[:3]} — which label belongs to which finding "
                   "cannot be decided mechanically")
    lost = sorted({fp for fp in fps if fp not in live})
    if lost:
        out.append(f"{len(lost)} labelled candidate(s) no longer resolve in the current "
                   f"catalog, e.g. {lost[:3]} — they were edited or folded away, and "
                   "re-attaching their labels needs a human")
    return out


def migrate_taxonomy(ref: str) -> dict:
    """Re-key the positional taxonomy at `ref` onto current fingerprints (#64).

    Both inputs are read from git at `ref`, never from the working tree: the catalog as it
    was when the labels were written, and the labels themselves. That makes the mapping a
    function of an immutable commit rather than of whatever the file happens to say today,
    so it can be re-derived if `candidate_fingerprint` ever changes again — which it did
    once already, under #63.

    Refuses on ANY ambiguity. Two labelled candidates colliding on one fingerprint, or a
    label whose candidate no longer exists, would each force a guess about which finding a
    human's judgement belongs to, and a wrong type label is worse than a missing one
    because it will be read as that judgement."""
    def at_ref(path):
        return subprocess.run(["git", "show", f"{ref}:{path}"], cwd=REPO_ROOT,
                              capture_output=True, text=True, check=True).stdout

    old_cat = yaml.safe_load(at_ref("_meta/catalog/conflict-candidates.yml"))
    old_tax = json.loads(at_ref("_meta/eval/pilot-taxonomy.json"))
    positional = old_tax["labels"]

    flat = [(str(ch["ors_chapter"]), c)
            for ch in old_cat["chapters"] for c in (ch.get("candidates") or [])]
    fps = [candidate_fingerprint(chn, c) for chn, c in flat]
    cur = yaml.safe_load(CATALOG.read_text())
    live = {candidate_fingerprint(str(ch["ors_chapter"]), c)
            for ch in cur["chapters"] for c in (ch.get("candidates") or [])}

    refusals = _migration_refusals(fps, positional, live)
    if refusals:
        raise SystemExit(f"cannot migrate the taxonomy from {ref}:\n  "
                         + "\n  ".join(refusals))

    return {
        "note": old_tax.get("note", ""),
        "key": "candidate_fingerprint(ors_chapter, candidate) — see "
               "build_conflict_candidates_data.py. NOT a position: the catalog is re-sorted "
               "by chapter on every merge, and positional labels were measured landing on "
               "the correct candidate for 4 of 137 (#64).",
        "recovered_from": ref,
        "regenerate": f"python3 src/eval_conflicts.py --migrate-taxonomy {ref}",
        "mechanical_types": old_tax.get("mechanical_types", []),
        "labels": {fps[i]: positional[str(i)] for i in range(len(flat))},
    }


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


def known_candidates(cat: dict, run_id: str | None = GROUND_TRUTH_RUN) -> dict:
    """fingerprint -> {chapter, summary, doc_ids, pairs, type} for the ground-truth set.

    `run_id` selects it, defaulting to the withheld pilot. Passing None takes every
    candidate in the file, which is what this function used to do unconditionally and is
    almost never what a measurement wants: the catalog is where scored runs are MERGED, so
    an arm evaluated against the whole file is credited for rediscovering itself, and the
    denominator grows every time anyone analyses anything (#65).

    Labels attach by fingerprint, not by position in this walk — see `load_taxonomy`."""
    labels, _ = load_taxonomy()
    out = {}
    for ch in cat["chapters"]:
        for cand in ch.get("candidates") or []:
            if run_id is not None and cand.get("run_id") != run_id:
                continue
            fp = candidate_fingerprint(ch["ors_chapter"], cand)
            out[fp] = {"chapter": str(ch["ors_chapter"]),
                       "summary": cand.get("summary", ""),
                       "type": labels.get(fp),
                       "pairs": candidate_pairs(cand),
                       # Carried so a caller can CHECK the pinning rather than trust it.
                       # The selftest asserts on this field; without it the assertion
                       # would read a key that is never present and pass unconditionally.
                       "run_id": cand.get("run_id"),
                       "doc_ids": sorted({d["id"] for d in cand.get("documents") or []})}
    return out


def rediscovered(known: dict, reach: set, produced: dict) -> tuple[set, int]:
    """(reachable known fingerprints the run found, how many were found by containment).

    Exact fingerprint identity is not the whole of "found it". `merge_into_catalog` treats
    a candidate whose pair-set contains, or is contained by, an existing finding's as the
    SAME finding and records it as corroboration (#58) — so scoring on exact identity
    alone let the catalog say "two models agree" about a candidate the evaluator was
    calling a miss. The same `_contained_match` runs here, which makes scorer and merge
    agree by construction rather than by both being maintained by hand.

    It carries its own conservatism with it: at least two shared pairs, and ambiguity
    declines. Measured over every stored arm, crediting containment changes no arm's
    recall today — it removes a divergence rather than inflating a number."""
    by_chapter = collections.defaultdict(list)
    for fp in reach:
        by_chapter[known[fp]["chapter"]].append((known[fp]["pairs"], fp))
    hit, by_containment = set(), 0
    for chapter, lst in produced.items():
        for fp, cand in lst:
            if fp in reach:
                hit.add(fp)
                continue
            match, _ = AC._contained_match(candidate_pairs(cand), by_chapter.get(chapter, []))
            if match is not None and match not in hit:
                hit.add(match)
                by_containment += 1
    return hit, by_containment


def reachable(known: dict, bundles: list) -> tuple[set, set]:
    """(reachable, unreachable) fingerprints — reachable = some bundle holds every
    document the candidate cites, so the model had the evidence in front of it."""
    contents = [{b["section"]} | {r["id"] for r in b["rules"]} for b in bundles]
    ok, no = set(), set()
    for fp, k in known.items():
        (ok if any(set(k["doc_ids"]) <= c for c in contents) else no).add(fp)
    return ok, no


def grounding(results: dict, paths: dict) -> dict:
    """Quote-grounding over everything the model produced, using the same matcher and the
    same haystacks the catalog gate uses — so the number is directly comparable to the
    79.5% baseline. `grounding_sources` is shared rather than reimplemented here: when
    this file grew its own copy, a v5 quote of a rule's declared authority was grounded
    by one tool and reported as fabricated by the other (#62)."""
    cache: dict = {}

    def sources(doc_id: str) -> tuple[str, str]:
        if doc_id not in cache:
            p = paths.get(doc_id)
            cache[doc_id] = grounding_sources(REPO_ROOT / p) if p else ("", "")
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
                ft, declared = sources(did)
                if not ft and not declared:
                    bad_id += 1          # cited a document that does not exist / has no text
                    continue
                if quote_is_grounded(q, ft, declared):
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
        # Case-fold the id. Every document id in this corpus is lowercase by schema
        # (^[a-z0-9][a-z0-9._-]*[a-z0-9]$), so "ORS-332.114" can only ever mean
        # "ors-332.114" -- there is no id it could collide with. phi4-mini-reasoning
        # emits ids uppercased; scoring those as phantom citations would report a
        # hallucination where the model actually named the right document. This is
        # NOT the coercion the docstring warns about: the string is unchanged apart
        # from case, so nothing is being guessed.
        docs = [{**d, "id": str(d["id"]).lower()}
                for d in (c.get("documents") or [])
                if isinstance(d, dict) and d.get("id")]
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


def selftest() -> int:
    """Prove the MEASUREMENT is sound: pinned ground truth, labels that resolve, and a
    quote classified into the right bucket.

    These are the failures that produce a confident wrong number rather than an error, so
    none of them announces itself. Runs against the committed catalog and taxonomy — no
    model, no network, no writes.
    """
    fails = []
    cat = yaml.safe_load(CATALOG.read_text())

    # 1. #65: ground truth is PINNED to one run, not to whatever the catalog holds. The
    #    default must exclude every candidate that a scored run put there, or an arm is
    #    credited for rediscovering its own output.
    pinned = known_candidates(cat)
    every = known_candidates(cat, None)
    runs = {c.get("run_id") for ch in cat["chapters"] for c in (ch.get("candidates") or [])}
    if len(runs) < 2:
        fails.append("the catalog holds candidates from only one run, so this fixture "
                     "cannot tell a pinned ground truth from an unpinned one")
    elif len(pinned) >= len(every):
        fails.append(f"known_candidates() default is not pinned: {len(pinned)} of "
                     f"{len(every)} catalog candidates, with {len(runs)} runs present. "
                     "An arm merged into the catalog is scored against itself (#65)")
    intruders = sorted({k["run_id"] for k in pinned.values()
                        if k["run_id"] != GROUND_TRUTH_RUN})
    if intruders:
        fails.append(f"the pinned ground truth contains candidates from {intruders}")

    # 2. #64: every hand label resolves to a ground-truth candidate. Position-keying could
    #    not fail this way — every index resolved to SOMETHING — which is exactly why the
    #    labels went 133/137 wrong in silence. Measured against the labelling commit
    #    8723043e57, positional lookup lands correctly for 4 of 137 today.
    labels, _ = load_taxonomy()
    if not labels:
        fails.append("no hand labels loaded; RECALL BY TYPE would report nothing and this "
                     "gate would pass vacuously")
    else:
        stale = unresolved_labels(pinned)
        if stale:
            fails.append(f"{len(stale)} of {len(labels)} hand label(s) match no "
                         f"ground-truth candidate, e.g. {stale[:3]} — the taxonomy and "
                         "the catalog have parted company; re-key with --migrate-taxonomy")
        if len(labels) != len(pinned):
            fails.append(f"{len(labels)} labels for {len(pinned)} ground-truth candidates "
                         "— one of them has changed without the other")

    # 3. #64, and the part a resolve-check CANNOT see: `known_candidates` must actually
    #    attach each label to its own candidate. Restoring the positional lookup passed
    #    properties 1, 2 and 4 untouched — every fingerprint still resolved, the file was
    #    still correct, and every candidate simply came back typed None. The attachment
    #    itself has to be asserted, or the fix for #64 is not under test at all.
    attached = {fp: k["type"] for fp, k in pinned.items() if k["type"] is not None}
    if labels and attached != labels:
        fails.append(f"{len(labels)} hand labels are loaded but {len(attached)} reach a "
                     "candidate through known_candidates(); the labels are not being "
                     "attached by the key they are stored under (#64)")

    # 4. #64: the committed mapping must be the one re-derived from the labelling commit,
    #    so a mapping built the wrong way round is caught rather than trusted.
    try:
        recovered = migrate_taxonomy("8723043e57")["labels"]
    except Exception as e:                      # noqa: BLE001 — reported, not hidden
        recovered = None
        fails.append(f"the taxonomy cannot be re-derived from 8723043e57 ({e}); the "
                     "mapping is no longer reproducible from git")
    if recovered is not None and recovered != labels:
        wrong = sum(1 for fp, t in recovered.items() if labels.get(fp) != t)
        fails.append(f"{wrong} committed label(s) disagree with the mapping re-derived "
                     "from the labelling commit")

    # 5. #64: every refusal path in the migration must be reachable. These only trigger on
    #    data that does not exist yet — no label has been orphaned, no two candidates
    #    collide — so disabling the "labelled candidate has vanished" branch changed no
    #    test result at all. Exercised synthetically instead, which is the only way a
    #    defensive branch gets to be a guard rather than a comment.
    for fps_in, positional_in, live_in, why in (
            (["a", "b"], {"0": "narrows", "1": "stale"}, {"a", "b"}, None),
            (["a", "b"], {"0": "narrows"}, {"a", "b"}, "a label/candidate count mismatch"),
            (["a", "a"], {"0": "narrows", "1": "stale"}, {"a"}, "two candidates sharing "
                                                               "one fingerprint"),
            (["a", "b"], {"0": "narrows", "1": "stale"}, {"a"}, "a labelled candidate "
                                                               "that no longer exists")):
        got = _migration_refusals(fps_in, positional_in, live_in)
        if why is None and got:
            fails.append(f"the migration refuses an unambiguous mapping: {got}")
        elif why is not None and not got:
            fails.append(f"the migration accepts {why}; a hand label would be attached to "
                         "a finding nobody judged")

    # 6. #67: an absence claim about a NESTED frontmatter field belongs in the
    #    absence bucket, not the ungrounded one. Both forms are asserted: the dotted path
    #    is the bug, and the plain form is what makes the fixture honest — a regex that
    #    only handled dots would break the case that already worked.
    for quote, want, why in (
            ("relationships.implements: [..., ors-435.120]; body text cites only "
             "'42 CFR 435.926'", True, "a dotted frontmatter path"),
            ("statutes_implemented: ORS 411.060 — the rule never engages it", True,
             "a plain frontmatter field"),
            ("(full text has no operative subsections)", True, "a parenthesised aside"),
            ("The provisions of this section do not apply to a public charter school.",
             False, "ordinary quoted source text")):
        if looks_like_absence_claim(quote) != want:
            fails.append(f"looks_like_absence_claim() returns {not want} for {why}; a "
                         "quote is in the wrong bucket and the grounding rate is wrong")

    # 7. #65: scorer and merge must agree on what "the same finding" is. A run citing the
    #    conflict plus one extra supporting provision is corroboration to
    #    merge_into_catalog and used to be a MISS here — the same divergence #63 was filed
    #    about, in the other direction.
    kn = {"fp1": {"chapter": "163", "pairs": frozenset(
        {"ors-163.465#2.a", "oar-736-010-0040#1"})}}
    extra = {"summary": "x", "documents": [
        {"id": "ors-163.465", "citation": "ORS 163.465(2)(a)"},
        {"id": "oar-736-010-0040", "citation": "OAR 736-010-0040(1)"},
        {"id": "oar-736-010-0040", "citation": "OAR 736-010-0040(11)(l)"}]}
    hit, n_cont = rediscovered(kn, {"fp1"}, {"163": [("other-fp", extra)]})
    if hit != {"fp1"} or n_cont != 1:
        fails.append("a rediscovery citing one extra supporting provision is scored as a "
                     "miss, while merge_into_catalog records it as corroboration")
    #    ...and the conservatism comes with it: one shared citation is not a rediscovery.
    vague = {"summary": "x", "documents": [
        {"id": "ors-163.465", "citation": "ORS 163.465(2)(a)"}]}
    if rediscovered(kn, {"fp1"}, {"163": [("other-fp", vague)]})[0]:
        fails.append("a candidate sharing ONE citation is credited as a rediscovery; "
                     "recall is inflated by candidates that found something else")

    for f in fails:
        print(f"FAIL {f}")
    print(f"eval selftest: {7 - len(fails)}/7 passed")
    return 1 if fails else 0


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
    # Choices come from AC.PROMPT_TEXTS rather than a literal list. The literal was
    # ["v2","v3","v4"] and had already gone stale — v5 existed and could not be scored
    # here, which is exactly the arm #62 says must be re-measured before any bulk run.
    ap.add_argument("--prompt", choices=sorted(AC.PROMPT_TEXTS), default="v2",
                    help="which local prompt to evaluate; run both to compare")
    ap.add_argument("--from-raw", metavar="PATH",
                    help="score an existing results JSON instead of running inference "
                         "(same bundles, same scoring) — for models not served by ollama")
    ap.add_argument("--out", default=None)
    ap.add_argument("--ground-truth-run", default=GROUND_TRUTH_RUN, metavar="RUN_ID",
                    help=f"which run's candidates are ground truth (default "
                         f"{GROUND_TRUTH_RUN}, the withheld pilot). 'all' takes the whole "
                         "catalog, which credits an arm for rediscovering itself and puts "
                         "the denominator on a moving base — see #65.")
    ap.add_argument("--migrate-taxonomy", metavar="REF",
                    help="re-key _meta/eval/pilot-taxonomy.json from the positional labels "
                         "at git REF onto current fingerprints (#64), and exit")
    ap.add_argument("--selftest", action="store_true",
                    help="prove the ground truth is pinned and the hand labels resolve")
    args = ap.parse_args()

    if args.selftest:
        # sys.exit, NOT return: main() is called bare at the bottom of this module, so a
        # returned code would be discarded and the gate would report failures while
        # exiting 0. Same convention, and same reason, as analyze_conflicts.py.
        sys.exit(selftest())

    if args.migrate_taxonomy:
        out = migrate_taxonomy(args.migrate_taxonomy)
        TAXONOMY.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {TAXONOMY.relative_to(REPO_ROOT)}: {len(out['labels'])} labels "
              f"re-keyed from positions at {args.migrate_taxonomy} onto fingerprints")
        return

    cat = yaml.safe_load(CATALOG.read_text())
    graph = json.loads(GRAPH.read_text())
    paths = {n["id"]: n["path"] for n in graph["nodes"]}

    chapters = [str(c["ors_chapter"]).lower() for c in cat["chapters"]]
    if args.chapters:
        want = {c.strip().lower() for c in args.chapters.split(",")}
        chapters = [c for c in chapters if c in want]
    if args.limit_chapters:
        chapters = chapters[:args.limit_chapters]
    gt_run = None if args.ground_truth_run == "all" else args.ground_truth_run
    known = {fp: k for fp, k in known_candidates(cat, gt_run).items()
             if k["chapter"].lower() in set(chapters)}
    # Say what the number was measured against, in the output that carries the number. A
    # recall figure quoted in a commit message is otherwise uncheckable later: the same
    # command on the same eval set has printed 7, 13 and 16 knowns at three points in
    # time, purely because the ground truth was whatever the catalog held that day (#65).
    stale = unresolved_labels(known_candidates(cat, gt_run))
    if stale:
        print(f"WARNING: {len(stale)} hand label(s) in "
              f"{TAXONOMY.relative_to(REPO_ROOT)} match no candidate in the ground-truth "
              f"set, e.g. {stale[:3]} — those candidates will read as 'unlabelled'. "
              f"Re-key with --migrate-taxonomy <ref>.", file=sys.stderr)

    bundles = AC.build_bundles(chapters, graph, args.tier, args.max_context_tokens)
    if args.limit_bundles:
        bundles = bundles[:args.limit_bundles]
    reach, unreach = reachable(known, bundles)

    print(f"ground truth: run {args.ground_truth_run!r} — "
          f"{sum(1 for _ in known_candidates(cat, gt_run))} candidate(s) in the catalog, "
          f"{len(known)} in this eval set")
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

    if args.from_raw:
        # Score output produced somewhere else (e.g. a Haiku agent) on the SAME bundles,
        # through the SAME grounding and recall code. Without this, a non-ollama model
        # could only be compared by eye, which is exactly how unfounded claims get made.
        raw = json.loads(pathlib.Path(args.from_raw).read_text())
        results = raw["results"]
        status = raw.get("status") or {
            cid: {"state": "ok" if results.get(cid) is not None else "error"}
            for cid in {b["custom_id"] for b in bundles}}
        missing = {b["custom_id"] for b in bundles} - set(results)
        if missing:
            print(f"WARNING: {len(missing)} bundle(s) absent from {args.from_raw} — "
                  "they count as unanswered, not as clean", file=sys.stderr)
            for cid in missing:
                status[cid] = {"state": "error"}
        args.model = raw.get("model", args.model)
    else:
        sys_prompt = AC.PROMPT_TEXTS[args.prompt]
        results, status = AC.LocalBackend(args.model, args.local_url,
                                          max_tokens=args.max_output_tokens,
                                          system=sys_prompt).run(bundles)
    AC._report_status(status)

    # Persist the raw model output IMMEDIATELY, before any analysis touches it. A shape
    # bug in post-processing already destroyed one 60-minute run; inference is the
    # expensive, unrepeatable part and must never depend on the cheap part working.
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = OUT_DIR / (f"raw-{args.prompt}-{date.today().isoformat()}.json"
                          if not args.from_raw else
                          f"rescored-{pathlib.Path(args.from_raw).name}")
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
    hit, n_contained = rediscovered(known, reach, produced)
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
        f"            ground truth: run {args.ground_truth_run!r}; "
        f"{n_contained} of these matched by containment, not exact citation",
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
        # Recorded, not just printed: a recall figure whose ground truth is unstated
        # cannot be checked once the catalog has moved on (#65).
        "ground_truth_run": args.ground_truth_run,
        "rediscovered_by_containment": n_contained,
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
