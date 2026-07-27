#!/usr/bin/env python3
"""Conflict candidates that need no model at all.

WHY THIS EXISTS. A hand-labelled taxonomy of all 137 frontier-model pilot candidates
(_meta/eval/pilot-taxonomy.json) found 40 of them — 29% — are DETERMINISTIC: a citation
to a section that does not exist, a rule marked current beside its own repeal, a rule
filed before the statute it implements was last amended, frontmatter disagreeing with
itself.

CORRECTION: this file previously claimed ~40%. That was an estimate made before the
labelling existed, and it over-counted by folding in numeric-threshold mismatches. Those
are NOT mechanical — deciding that a rule's $180 fee conflicts with a statutory
"$50 base + $25 CE" cap requires reading both texts and working out that they govern the
same trigger. They are the `numeric` semantic type (14 candidates) and belong to the
model.

Asking a language model to eyeball the deterministic ones costs ~636s per bundle on local
hardware, can hallucinate, and finds fewer of them than a regex does — a first pass over
4,000 of 36,953 rules turned up 486 distinct dead citations across 772 documents, where
the pilot's frontier models reported 21 such candidates in total.

So these are code, not prompts. The model's budget belongs on the other 97 (71%), which
genuinely require reading comprehension: what a rule omits, what it adds without
authority, how it redefines a statutory term, where two agencies disagree. Those eight
types are enumerated as explicit checks in analyze_conflicts.py's SYSTEM_V3 prompt, and
that prompt DISQUALIFIES the four types handled here so the two do not overlap.

EVERYTHING HERE IS A CANDIDATE, NOT A FINDING, and one limit matters more than the rest.

An unresolvable citation has several causes, and separating them was impossible until
recently. A first version asked whether the ORS catalog knew the section — invalid at the
time, because the catalog omitted whole real chapters (ORS 25, Support Enforcement, was
absent), so "not in the catalog" would have accused agencies of 887 bad citations that
were merely uncatalogued. The cause was a missing zero-pad in the chapter URL: every
chapter below 100 404'd and was never fetched. With that fixed and 538 chapters
catalogued, the test is now sound, and classify_dead() splits three ways:

  renumbered_or_repealed  chapter is current, but this section left its table of contents
  not_ingested            OUR gap: catalogued, yet no document was produced
  chapter_absent          no such chapter page exists on the site

Only `not_ingested` is a defect in this corpus. The other two are findings ABOUT the
rules — agencies citing statute numbers that no longer exist. A mistyped citation is
still not separable from a genuinely dead one; both land in renumbered_or_repealed, so
it remains a candidate, not a finding.

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
    known, chapters = set(), set()
    if ORS_CAT.is_file():
        cat = yaml.safe_load(ORS_CAT.read_text())
        for ch in cat.get("chapters", []):
            chapters.add(str(ch.get("chapter", "")).lower())
            for s in ch.get("sections", []):
                if s.get("number"):
                    known.add(f"ors-{str(s['number']).lower()}")
    return ids, paths, known, chapters


def classify_dead(section_id, in_catalog, chapters):
    """Why an ORS citation resolves to nothing. This split was impossible while the
    catalog was missing whole real chapters (every chapter below 100 404'd on an unpadded
    URL); with those catalogued it is now decidable, and the three causes want different
    responses -- only the middle one is a defect in our corpus."""
    ch = section_id[4:].split(".")[0]
    if ch not in chapters:
        return "chapter_absent"      # no such chapter page on the site (fully repealed)
    if in_catalog:
        return "not_ingested"        # OUR gap: catalogued, but no document was produced
    return "renumbered_or_repealed"  # chapter is current; this section left its TOC


def check_all(limit=None, today="2026-07-26"):
    ids, paths, catalog, chapters = load_universe()
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
                                     "in_ors_catalog": tid in catalog,
                                     "cause": classify_dead(tid, tid in catalog, chapters)})
        for num in set(OAR_CITE.findall(text)):
            if f"oar-{num}" not in ids:
                out["dead_xref"].append({"rule": rid, "cites": f"OAR {num}",
                                     # the ORS catalog says nothing about OAR rules,
                                     # so these are out of scope for classify_dead()
                                     "cause": "oar_unclassified"})

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
        causes = collections.Counter(r.get("cause", "unknown") for r in res["dead_xref"])
        section("dead_xref", "CITATIONS THAT RESOLVE TO NOTHING",
                "by cause — " + ", ".join(f"{k} {v:,}" for k, v in causes.most_common())
                + "\n   (only not_ingested is a gap in this corpus; the rest are findings "
                  "about rules citing statute numbers that no longer exist)",
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
