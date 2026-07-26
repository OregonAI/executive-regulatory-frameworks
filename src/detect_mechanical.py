#!/usr/bin/env python3
"""Conflict candidates that need no model at all.

WHY THIS EXISTS. A hand-labelled taxonomy of the 137 frontier-model pilot candidates
found that roughly 40% of them are DETERMINISTIC: a citation to a section that does not
exist, a rule marked current beside its own repeal, a rule filed before the statute it
implements was last amended, frontmatter disagreeing with itself. Asking a language model
to eyeball those costs ~636s per bundle on local hardware, can hallucinate, and finds
fewer of them than a regex does — a first pass over 4,000 of 36,953 rules turned up 486
distinct dead citations across 772 documents, where the pilot's frontier models reported
21 such candidates in total.

So these are code, not prompts. The model's budget belongs on the ~60% that genuinely
requires reading comprehension: what a rule omits, what it adds without authority, how it
redefines a statutory term, where two agencies disagree.

EVERYTHING HERE IS A CANDIDATE, NOT A FINDING, and one limit matters more than the rest.

An unresolvable citation has at least three causes and this tool CANNOT tell them apart:
the section was repealed or renumbered, the rule mistyped it, or the corpus simply lacks
it. A first version tried to separate "genuinely dead" from "our gap" by asking whether
the ORS catalog knew the section — that test is invalid: the catalog covers 432 chapters
but omits some real ones entirely (ORS chapter 25, Support Enforcement, is absent), so
"not in the catalog" would have accused agencies of 887 bad citations that are mostly
just uncatalogued. They are reported as ONE bucket with the cause stated as unknown.

Staleness is read from _meta/freshness.json rather than recomputed. ORS documents carry
no effective_date at all — only source_version and status — so a from-scratch computation
here silently returned zero every time. freshness.json already derives rule year vs
statute amendment year, and is CI-gated for freshness.

  python3 src/detect_mechanical.py --check all
  python3 src/detect_mechanical.py --check xref --limit 4000
  python3 src/detect_mechanical.py --check all --out _meta/.cache/mechanical.json
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT, extract_fulltext, parse_frontmatter

GRAPH = REPO_ROOT / "_meta/graph.json"
ORS_CAT = REPO_ROOT / "_meta/catalog/ors.yml"

ORS_CITE = re.compile(r"\bORS\s+(\d{1,3}[A-Za-z]?\.\d{3,4})\b")
OAR_CITE = re.compile(r"\bOAR\s+(\d{3}-\d{3}-\d{4})\b")
# Citation-string defects the pilot logged as `artifacts`: a missing space or period turns
# a real citation into an unresolvable one and silently costs a graph edge.
MALFORMED = [
    (re.compile(r"\bORS(\d)"), "missing space after ORS"),
    (re.compile(r"\bORS\s+\d{3}\d{3}\b"), "missing period in section number"),
    (re.compile(r"\bORS\s+\d{1,3}\.\d{5,}\b"), "too many digits after the period"),
    (re.compile(r"\bORS\s+\d{4}\s+(HB|SB)\b", re.I), "bill number labelled as ORS"),
    (re.compile(r"\bORS\s+\d+\s+(CFR|U\.?S\.?C)\b", re.I), "federal citation labelled as ORS"),
]
SUNSET = re.compile(r"\b(?:sunset|expires?|terminates?)\b[^.\n]{0,60}\b(19|20)(\d{2})\b", re.I)


def load_universe():
    g = json.loads(GRAPH.read_text())
    ids = {n["id"] for n in g["nodes"]}
    paths = {n["id"]: n["path"] for n in g["nodes"]}
    # Sections the ORS catalog knows about, ingested or not. A citation absent from BOTH
    # the corpus and the catalog is the one that suggests a defect in the rule itself.
    known = set()
    if ORS_CAT.is_file():
        cat = yaml.safe_load(ORS_CAT.read_text())
        for ch in cat.get("chapters", []):
            for s in ch.get("sections", []):
                if s.get("number"):
                    known.add(f"ors-{str(s['number']).lower()}")
    return ids, paths, known


def check_all(limit=None, today="2026-07-26"):
    ids, paths, catalog = load_universe()
    rules = sorted(i for i in ids if i.startswith("oar-"))
    if limit:
        rules = rules[:limit]

    out = {"dead_xref": [], "corpus_gap": [], "zombie": [], "stale": [], "malformed": []}
    # Staleness comes from the artifact that already computes it correctly.
    fresh = REPO_ROOT / "_meta/freshness.json"
    if fresh.is_file():
        want = set(rules)
        for r in json.loads(fresh.read_text()).get("rules", []):
            if r.get("id") in want and r.get("ay") and r.get("yr") and r["ay"] - r["yr"] >= 10:
                out["stale"].append({"rule": r["id"], "statute": r.get("sid"),
                                     "rule_year": r["yr"], "statute_year": r["ay"],
                                     "lag_years": r["ay"] - r["yr"]})

    for rid in rules:
        try:
            fm, body = parse_frontmatter(REPO_ROOT / paths[rid])
        except Exception:                      # noqa: BLE001
            continue
        text = extract_fulltext(body) or ""
        raw = text + "\n" + json.dumps(fm.get("legal_authority") or []) + \
            json.dumps(fm.get("statutes_implemented") or [])

        # 1. citations that resolve nowhere
        for num in set(ORS_CITE.findall(text)):
            tid = f"ors-{num.lower()}"
            if tid in ids:
                continue
            out["dead_xref"].append({"rule": rid, "cites": f"ORS {num}",
                                     "in_ors_catalog": tid in catalog})
        for num in set(OAR_CITE.findall(text)):
            if f"oar-{num}" not in ids:
                out["dead_xref"].append({"rule": rid, "cites": f"OAR {num}"})

        # 2. repealed / self-sunset but still current
        if fm.get("status") == "current":
            m = SUNSET.search(text)
            if m and int(m.group(1) + m.group(2)) < int(today[:4]):
                out["zombie"].append({"rule": rid, "why": "self-declared sunset has passed",
                                      "evidence": m.group(0)[:80]})

        # 4. citation strings that cannot resolve because they are malformed
        for rx, why in MALFORMED:
            m = rx.search(raw)
            if m:
                out["malformed"].append({"rule": rid, "why": why,
                                         "evidence": m.group(0)[:40]})
    return out, len(rules)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", default="all",
                    choices=["all", "xref", "zombie", "stale", "malformed"])
    ap.add_argument("--limit", type=int, help="scan only the first N rules (spot check)")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--out")
    args = ap.parse_args()

    res, n = check_all(args.limit)
    print(f"scanned {n:,} rules\n")

    def section(key, title, note, fmt):
        rows = res[key]
        docs = len({r["rule"] for r in rows})
        print(f"{title}: {len(rows):,} occurrence(s) across {docs:,} document(s)")
        print(f"   {note}")
        seen = collections.Counter(fmt(r) for r in rows)
        for k, c in seen.most_common(args.top):
            print(f"     {k}" + (f"   x{c}" if c > 1 else ""))
        print()

    if args.check in ("all", "xref"):
        section("dead_xref", "CITATIONS THAT RESOLVE TO NOTHING",
                "cause UNKNOWN: repealed, renumbered, mistyped, or simply not ingested "
                "here. The ORS catalog cannot settle it — it omits whole real chapters",
                lambda r: r["cites"])
    if args.check in ("all", "zombie"):
        section("zombie", "LAPSED BUT STILL 'current'",
                "rule text declares a sunset that has already passed",
                lambda r: f"{r['rule']}: {r['evidence']}")
    if args.check in ("all", "stale"):
        section("stale", "RULE PREDATES ITS STATUTE'S LAST AMENDMENT BY 10+ YEARS",
                "a candidate for review, not a defect: many old rules remain correct",
                lambda r: f"{r['rule']} vs {r['statute']} ({r['lag_years']}y)")
    if args.check in ("all", "malformed"):
        section("malformed", "MALFORMED CITATION STRINGS",
                "cannot resolve as written, so they silently cost graph edges",
                lambda r: f"{r['why']}: {r['evidence']}")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(res, indent=1))
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
