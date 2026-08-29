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

REGENERATION ORDER MATTERS (#326). `build_freshness_data.py --write` must run BEFORE this
script's own --write, since this reads freshness.json's content rather than recomputing it
-- writing this catalog against a freshness.json that is about to be regenerated commits a
catalog that already disagrees with the file sitting beside it. The --check gates catch it
either way (this one goes stale the moment freshness.json's content moves, same as
`build_conflict_candidates_data.py`'s note about `detect_mechanical.py` itself), but the
correct order is: build_freshness_data --write, then this. `build_governor_priorities_
data.py` reads the same cache the same way and carries the identical note.

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



CATALOG = REPO_ROOT / "_meta/catalog/mechanical-findings.yml"

# `not_ingested` means the ORS section is catalogued upstream but this corpus produced no
# document for it. That is OUR gap, not a defect in the rule, and pooling it with the rest
# would accuse agencies of citation errors we caused. Reported separately, always.
OUR_GAP_CAUSES = {"not_ingested"}


def render_catalog(res: dict, n_scanned: int) -> str:
    """The committed artifact. Deterministic: every list sorted, no timestamp.

    NO `generated` DATE ON PURPOSE. A timestamp would make the file differ on every run,
    so the staleness gate could never distinguish "the corpus changed" from "someone ran
    the script", which is the only question the gate exists to answer.
    """
    import collections

    dead = [r for r in res["dead_xref"] if r.get("cause") not in OUR_GAP_CAUSES]
    ours = [r for r in res["dead_xref"] if r.get("cause") in OUR_GAP_CAUSES]
    by_cause = collections.Counter(r.get("cause", "unknown") for r in dead)

    doc = {
        "note": (
            "Conflict candidates decidable BY CODE — no model involved. A hand-labelled "
            "taxonomy of the 137 frontier-pilot candidates found 29% of them were of these "
            "four deterministic types, and a regex finds far more of them than the models "
            "did: the pilot reported 21 dead citations in total, this scan finds "
            f"{len({r['cites'] for r in dead}):,} DISTINCT dead targets, cited "
            f"{len(dead):,} times across {len({r['rule'] for r in dead}):,} documents. "
            "READ THE DISTINCT COUNT, NOT THE OCCURRENCES: they differ by ~2.7x because a "
            "single repealed section is cited by many rules — ORS 184.616 alone is cited "
            "by 727 of them. Occurrences are the blast radius; distinct targets are the "
            "number of things to actually resolve, and they are heavily concentrated, so "
            "the top handful clear thousands of documents. The magnitude is expected: "
            "Oregon has renumbered wholesale (ORS 181 to 181A in 2015, ORS 279 split into "
            "279A/B/C in 2003, the 2015 higher-education restructuring), and every rule "
            "written before those still cites the old numbers. A decades-spanning corpus "
            "of 36,953 rules showing NO stale citations would be the surprising result. "
            "Verified against the live source: six sampled flagged sections were all "
            "genuinely absent, and a live control section was correctly not flagged. "
            f"Everything here is a CANDIDATE, not a finding, and not legally "
            "reviewed. The model's budget belongs on the other 71% — what a rule omits, "
            "adds without authority, or redefines — which SYSTEM_V3 enumerates and which "
            "explicitly disqualifies these four types so the two passes do not overlap."),
        "scanned_rules": n_scanned,
        # OCCURRENCES vs DISTINCT PROBLEMS. These differ by 2.7x and quoting the wrong
        # one overstates the work: ORS 184.616 alone is cited by 727 rules, so one repealed
        # section produces 727 "dead citations". Distinct targets is the number of things
        # to actually resolve; occurrences is the blast radius.
        "counts": {
            "distinct_dead_targets": len({r["cites"] for r in dead}),
            "dead_citation_occurrences": len(dead),
            "documents_affected": len({r["rule"] for r in dead}),
            "dead_citations": len(dead),
            "corpus_gap_not_ingested": len(ours),
            "lapsed_but_current": len(res["zombie"]),
            "rule_predates_statute_amendment": len(res["stale"]),
            "malformed_citations": len(res["malformed"]),
        },
        "dead_citations_by_cause": dict(sorted(by_cause.items())),
        "cause_meanings": {
            "renumbered_or_repealed": "the chapter is current, but this section has left "
                                      "its table of contents",
            "chapter_absent": "no such ORS chapter page exists upstream",
            "oar_unclassified": "an OAR-to-OAR citation that did not resolve",
        },
        "corpus_gap_note": (
            f"{len(ours):,} citations point at ORS sections that ARE catalogued upstream "
            "but have no document here. That is this corpus's ingestion gap, not a defect "
            "in the rule, and is counted separately so it is never reported as an agency's "
            "citation error."),
        # The work is concentrated: resolving a handful of high-fanout sections clears
        # thousands of documents. This table is the triage order.
        "most_cited_dead_targets": [
            {"cites": c, "cited_by_rules": n}
            for c, n in collections.Counter(r["cites"] for r in dead).most_common(25)],
        "dead_citations": sorted(
            ({"rule": r["rule"], "cites": r["cites"], "cause": r.get("cause")}
             for r in dead), key=lambda r: (r["rule"], r["cites"])),
        "lapsed_but_current": sorted(
            ({"rule": r["rule"], "evidence": r.get("evidence")} for r in res["zombie"]),
            key=lambda r: r["rule"]),
        "malformed_citations": sorted(
            ({"rule": r["rule"], "why": r.get("why"), "evidence": r.get("evidence")}
             for r in res["malformed"]), key=lambda r: (r["rule"], str(r["evidence"]))),
        # `stale` is 4,603 rows of "old rule, amended statute" — a review QUEUE, not a
        # defect list, and most entries are correct rules that simply predate an
        # amendment. Counted above and summarised here rather than enumerated, so the
        # artifact stays reviewable.
        "rule_predates_statute_amendment_top": sorted(
            ({"rule": r["rule"], "statute": r["statute"], "lag_years": r["lag_years"]}
             for r in res["stale"]), key=lambda r: (-r["lag_years"], r["rule"]))[:100],
    }
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # RENAMED from --check. Every other builder in this repo uses --check to mean "is the
    # committed artifact stale?", and this one used it to select WHICH check to run — so
    # wiring it into CI the obvious way would have run a spot check and reported success.
    # The old name was referenced nowhere.
    ap.add_argument("--only", default="all",
                    choices=["all", "xref", "zombie", "stale", "malformed"])
    ap.add_argument("--check", action="store_true",
                    help="regenerate and fail if the committed catalog is out of date")
    ap.add_argument("--limit", type=int, help="scan only the first N rules (spot check)")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--write", action="store_true",
                    help="regenerate the committed catalog")
    ap.add_argument("--out")
    args = ap.parse_args()

    res, n = check_all(args.limit)
    print(f"scanned {n:,} rules\n")

    if args.check or args.write:
        text = render_catalog(res, n)
        if args.check:
            if not CATALOG.is_file():
                sys.exit(f"{CATALOG.relative_to(REPO_ROOT)} is missing — run "
                         f"`python3 src/detect_mechanical.py --write`")
            if CATALOG.read_text() != text:
                sys.exit(f"{CATALOG.relative_to(REPO_ROOT)} is stale — rerun "
                         f"`python3 src/detect_mechanical.py --write`")
            print(f"{CATALOG.relative_to(REPO_ROOT)} is current.")
            return
        CATALOG.parent.mkdir(parents=True, exist_ok=True)
        CATALOG.write_text(text)
        print(f"wrote {CATALOG.relative_to(REPO_ROOT)}")
        return

    def section(key, title, note, fmt):
        rows = res[key]
        docs = len({r["rule"] for r in rows})
        print(f"{title}: {len(rows):,} occurrence(s) across {docs:,} document(s)")
        print(f"   {note}")
        seen = collections.Counter(fmt(r) for r in rows)
        for k, c in seen.most_common(args.top):
            print(f"     {k}" + (f"   x{c}" if c > 1 else ""))
        print()

    if args.only in ("all", "xref"):
        causes = collections.Counter(r.get("cause", "unknown") for r in res["dead_xref"])
        section("dead_xref", "CITATIONS THAT RESOLVE TO NOTHING",
                "by cause — " + ", ".join(f"{k} {v:,}" for k, v in causes.most_common())
                + "\n   (only not_ingested is a gap in this corpus; the rest are findings "
                  "about rules citing statute numbers that no longer exist)",
                lambda r: r["cites"])
    if args.only in ("all", "zombie"):
        section("zombie", "LAPSED BUT STILL 'current'",
                "rule text declares a sunset that has already passed",
                lambda r: f"{r['rule']}: {r['evidence']}")
    if args.only in ("all", "stale"):
        section("stale", "RULE PREDATES ITS STATUTE'S LAST AMENDMENT BY 10+ YEARS",
                "a candidate for review, not a defect: many old rules remain correct",
                lambda r: f"{r['rule']} vs {r['statute']} ({r['lag_years']}y)")
    if args.only in ("all", "malformed"):
        section("malformed", "MALFORMED CITATION STRINGS",
                "cannot resolve as written, so they silently cost graph edges",
                lambda r: f"{r['why']}: {r['evidence']}")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(res, indent=1))
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
