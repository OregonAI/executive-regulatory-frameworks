#!/usr/bin/env python3
"""Second-stage validation: score an already-proposed candidate, don't search for new ones.

THE HYPOTHESIS THIS TESTS. Generation is expensive because the model reads a statute plus
every rule implementing it and hunts for anything wrong — on gemma4-12b that costs ~636s
per bundle, nearly all of it reasoning tokens. Validation is a narrower question ("is THIS
specific claim true?") over far less text (only the cited documents, not the whole
cluster), so it should be much cheaper. Whether it actually is, is measured here rather
than assumed.

WHY A CASCADE STILL WON'T WORK WITH QWEN IN FRONT. Measured on identical bundles, qwen
flagged 0 of the 4 candidates gemma correctly found, and the two models' flag sets overlap
on 1 of 17. A first stage with ~0% recall discards everything downstream no matter how
good the validator is. This tool is therefore useful for RE-SCORING candidates that
already exist — the 137 pilot candidates, or a Gemma run — not for rescuing a cheap
generator.

The validator is given the candidate's claim and the REAL source text of each cited
document, pulled from the corpus rather than from the candidate. That matters: a candidate
citing a document that does not exist is a fabrication, and the validator must be able to
see that rather than take the quote on faith. Those are scored 0 mechanically, without
asking a model, because it is not a judgement call.

  python3 src/validate_candidates.py --in /tmp/s12-gemma.json --model gemma4:12b-it-qat
  python3 src/validate_candidates.py --in /tmp/s12-qwen.json  --model qwen2.5:7b-instruct-q4_K_M
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT, extract_fulltext, parse_frontmatter
from build_conflict_candidates_data import fold, quote_is_grounded

GRAPH = REPO_ROOT / "_meta/graph.json"

# Deliberately tiny. The whole point is that validation needs less thinking than search;
# a long instruction would work against that, and a score is all we want back.
# WHAT "confidence" MEANS HAS TO BE SPELLED OUT. The first version of this prompt asked
# for `{"confidence": 0-100}` without saying confidence in WHAT, and gemma4 returned 100
# for every single candidate — including ones where its own `why` read "No conflict
# between statute and rule exists" and "Both provisions can be satisfied simultaneously".
# It was reporting confidence in its ASSESSMENT, which is a perfectly reasonable reading
# of an ambiguous instruction. The scores were uniform, so the stage looked useless when
# the instrument was simply broken.
SYSTEM = """You judge whether a claimed conflict between an Oregon statute and a rule is REAL.

Output a single number: the probability that this is a genuine conflict a lawyer would
recognise.

  0   = not a conflict at all, or the claim is fabricated
  50  = arguable, needs a human
  100 = certainly a real conflict

Score LOW when: the quoted words are not in the document, the two provisions can both be
obeyed at once, or the rule is merely more detailed than the statute. Being more specific
is what rules are FOR and is not a conflict.

The number must agree with your reason. If your reason says there is no conflict, the
number is near 0, not near 100.

Reply with ONLY this JSON: {"confidence": <integer 0-100>, "why": "<10 words or fewer>"}"""

# Phrases that mean "no conflict". A reply pairing one of these with a high score has
# misread the scale, and is recorded rather than trusted — the failure above was silent.
_NEGATION = re.compile(
    r"\bno (real )?conflict|not a conflict|no contradiction|can be satisfied|"
    r"consistent with|no discrepancy|both.{0,12}satisfied|does not conflict", re.I)

_SCORE = re.compile(r'"confidence"\s*:\s*(\d{1,3})')
# Excerpt window around the quote. Sending whole documents would rebuild the cost this
# is trying to avoid; the claim is about a specific passage, so show that passage in
# context and let the model judge it.
WINDOW = 1200


def excerpt(full: str, quote: str) -> str:
    """The region of the document around the quoted passage, or the head of it if the
    quote cannot be located — in which case the model should see that it is absent."""
    if not full:
        return ""
    folded, fq = fold(full), fold(quote or "")
    i = folded.find(fq[:80]) if fq else -1
    if i == -1:
        return full[:WINDOW] + ("\n[...]" if len(full) > WINDOW else "")
    # map back approximately: fold only collapses whitespace, so ratio is close enough
    j = int(i * len(full) / max(len(folded), 1))
    return full[max(0, j - WINDOW // 3): j + WINDOW]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", required=True, help="an eval_conflicts.py output")
    ap.add_argument("--model", required=True)
    ap.add_argument("--backend", choices=["local", "claude"], default="local",
                    help="claude uses the Anthropic SDK and ANTHROPIC_API_KEY; local "
                         "posts to any OpenAI-compatible server")
    ap.add_argument("--local-url", default="http://localhost:11434/v1")
    ap.add_argument("--max-output-tokens", type=int, default=8000)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out")
    args = ap.parse_args()

    graph = json.loads(GRAPH.read_text())
    paths = {n["id"]: n["path"] for n in graph["nodes"]}
    cache: dict = {}

    def full_text(doc_id: str) -> str:
        if doc_id not in cache:
            p = paths.get(doc_id)
            if not p:
                cache[doc_id] = ""
            else:
                _, body = parse_frontmatter(REPO_ROOT / p)
                cache[doc_id] = extract_fulltext(body) or ""
        return cache[doc_id]

    cands = []
    for cid, lst in json.loads(Path(args.inp).read_text())["results"].items():
        for c in lst:
            docs = [d for d in (c.get("documents") or []) if isinstance(d, dict) and d.get("id")]
            if docs:
                cands.append({**c, "documents": docs, "custom_id": cid})
    if args.limit:
        cands = cands[:args.limit]

    client = None
    if args.backend == "claude":
        try:
            import anthropic
        except ImportError:
            sys.exit("--backend claude needs the SDK: pip install anthropic")
        import os
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("--backend claude needs ANTHROPIC_API_KEY in the environment.")
        client = anthropic.Anthropic()

    def ask_claude(user: str) -> str:
        """Validation is a short, bounded judgement, so no extended thinking — the whole
        point of this stage is that it costs a fraction of generation."""
        r = client.messages.create(
            model=args.model, max_tokens=200, system=SYSTEM,
            messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")

    rows, t_model = [], 0.0
    for i, c in enumerate(cands, 1):
        missing = [d["id"] for d in c["documents"] if not full_text(d["id"])]
        if missing:
            # Not a judgement call: the candidate cites a document that does not exist.
            rows.append({"summary": c.get("summary", ""), "score": 0, "sec": 0.0,
                         "reason": f"cites nonexistent document(s): {', '.join(missing)}",
                         "mechanical": True})
            print(f"  [{i}/{len(cands)}] score=0 (mechanical: nonexistent {missing[0]})",
                  file=sys.stderr)
            continue

        parts = [f"CLAIM: {c.get('summary','')}", ""]
        for d in c["documents"]:
            ft = full_text(d["id"])
            grounded = quote_is_grounded(d.get("quote", ""), fold(ft))
            parts += [f"--- {d['id']} ({d.get('citation','')}) ---",
                      f"quoted: {d.get('quote','')}",
                      f"quote present in this document: {'YES' if grounded else 'NO'}",
                      "document text around that passage:",
                      excerpt(ft, d.get("quote", "")), ""]
        user = "\n".join(parts)

        body = json.dumps({"model": args.model, "temperature": 0,
                           "max_tokens": args.max_output_tokens,
                           "messages": [{"role": "system", "content": SYSTEM},
                                        {"role": "user", "content": user}]}).encode()
        req = urllib.request.Request(args.local_url.rstrip("/") + "/chat/completions",
                                     data=body, headers={"Content-Type": "application/json"})
        t0 = time.time()
        try:
            if client is not None:
                txt = ask_claude(user)
            else:
                with urllib.request.urlopen(req, timeout=1800) as r:
                    txt = json.loads(r.read())["choices"][0]["message"]["content"]
            el = time.time() - t0
            m = _SCORE.search(txt or "")
            score = int(m.group(1)) if m else None
            # A high score whose reason says "no conflict" is a scale misread, not a
            # judgement. Flag it instead of averaging it into a rate.
            contradicted = bool(score is not None and score >= 60
                                and _NEGATION.search(txt or ""))
        except Exception as e:                       # noqa: BLE001 — recorded, not hidden
            el, score, txt, contradicted = time.time() - t0, None, f"ERROR {e}", False
        t_model += el
        rows.append({"summary": c.get("summary", ""), "score": score, "sec": round(el, 1),
                     "reason": (txt or "")[:120], "mechanical": False,
                     "contradicted": contradicted, "tokens_in": len(user) // 4})
        print(f"  [{i}/{len(cands)}] score={score} {el:.0f}s ({len(user)//4:,} tok in)",
              file=sys.stderr)

    asked = [r for r in rows if not r["mechanical"]]
    scored = [r for r in asked if r["score"] is not None]
    print(f"\n{'='*64}\nVALIDATION — {args.model}\n{'='*64}")
    print(f"candidates            : {len(rows)}")
    print(f"  rejected mechanically (cite a nonexistent document): "
          f"{sum(1 for r in rows if r['mechanical'])}")
    print(f"  sent to the model   : {len(asked)}   scored ok: {len(scored)}")
    if scored:
        s = sorted(r["score"] for r in scored)
        print(f"score  median {s[len(s)//2]}  min {s[0]}  max {s[-1]}")
        for lo, hi in ((0, 33), (34, 66), (67, 100)):
            print(f"   {lo:3d}-{hi:<3d}: {sum(1 for x in s if lo <= x <= hi)}")
    if asked:
        secs = [r["sec"] for r in asked]
        print(f"seconds per validation: mean {sum(secs)/len(secs):.0f}  "
              f"min {min(secs):.0f}  max {max(secs):.0f}   total {t_model/60:.1f} min")
        toks = [r.get("tokens_in", 0) for r in asked]
        print(f"input tokens          : mean {sum(toks)//max(len(toks),1):,}")
    bad = [r for r in asked if r.get("contradicted")]
    if bad:
        print(f"\nSCALE MISREADS: {len(bad)} reply(ies) scored >=60 while the reason says "
              "there is no conflict. These are not judgements and must not be averaged in:")
        for r in bad[:5]:
            print(f"   score={r['score']}  {r['reason'][:90]}")
    if args.out:
        Path(args.out).write_text(json.dumps(rows, indent=1, ensure_ascii=False))
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
