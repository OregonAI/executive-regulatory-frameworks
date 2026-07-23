#!/usr/bin/env python3
"""Cache rulemaking recency/volume for the 4 stated gubernatorial priority areas, per
_meta/catalog/governor-priorities.yml's CURATED chapter mapping (see that file's note —
the mapping is an interpretive judgment call, not something the corpus itself asserts).

Answers: "if these are stated priorities, do we see agencies actively amending rules in the
areas that plausibly implement them?" — via each mapped chapter's rules' own effective_date,
compared against the corpus-wide OAR baseline (are these chapters more/less active than OAR
rulemaking generally?).

Light step (only reads rule files in the ~14 mapped chapters, not the full corpus), but
cached separately so the HTML generator's --check runs without re-reading files.

  python3 src/build_governor_priorities_data.py          # scan + write cache
  python3 src/build_governor_priorities_data.py --check   # exit 1 if stale (CI)
"""
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT, parse_frontmatter

CATALOG = REPO_ROOT / "_meta/catalog/governor-priorities.yml"
OUT = REPO_ROOT / "_meta/governor_priorities.json"
GRAPH = REPO_ROOT / "_meta/graph.json"
FRESHNESS = REPO_ROOT / "_meta/freshness.json"  # reused for the exact corpus-wide OAR
                                                 # recent-activity baseline (already computes
                                                 # every rule's effective year; no need to
                                                 # re-scan all 36,953 rule files here too)
THIS_YEAR = date.today().year


def _rule_year(path_str):
    p = REPO_ROOT / path_str
    fm, _ = parse_frontmatter(p)
    eff = fm.get("effective_date")
    if not eff:
        return None
    try:
        return int(eff.split("-")[0])
    except Exception:
        return None


def compute() -> dict:
    cat = yaml.safe_load(CATALOG.read_text())
    g = json.loads(GRAPH.read_text())
    rules_by_chapter = {}
    for n in g["nodes"]:
        if n["doc_type"] != "rule":
            continue
        ch = n["id"].split("-")[1]
        rules_by_chapter.setdefault(ch, []).append(n["path"])

    total_rules = sum(1 for n in g["nodes"] if n["doc_type"] == "rule")
    # exact corpus-wide "share amended in the last 2 years" baseline, from freshness.json's
    # already-computed per-rule effective years (avoids a second full-corpus file scan)
    fr = json.loads(FRESHNESS.read_text())
    base_dated = sum(1 for r in fr["rules"] if r.get("yr"))
    base_recent = sum(1 for r in fr["rules"] if r.get("yr") and r["yr"] >= THIS_YEAR - 1)
    baseline_recent_rate = round(base_recent / base_dated, 4) if base_dated else None

    areas = []
    mapped_chapters = set()
    for area in cat["areas"]:
        chapters = []
        area_years = Counter()
        area_n = 0
        for ch_entry in area["chapters"]:
            ch = ch_entry["oar_chapter"]
            mapped_chapters.add(ch)
            paths = rules_by_chapter.get(ch, [])
            years = Counter()
            for p in paths:
                y = _rule_year(p)
                if y:
                    years[y] += 1
                    area_years[y] += 1
            area_n += len(paths)
            recent2 = sum(n for y, n in years.items() if y >= THIS_YEAR - 1)
            chapters.append({
                "agency": ch_entry["agency"], "oar_chapter": ch,
                "reasoning": ch_entry["reasoning"], "n_rules": len(paths),
                "n_dated": sum(years.values()),
                "recent_2yr": recent2,
                "years": dict(sorted(years.items())),
            })
        recent2_area = sum(n for y, n in area_years.items() if y >= THIS_YEAR - 1)
        areas.append({
            "id": area["id"], "name": area["name"], "summary": area["summary"],
            "caveat": area.get("caveat", ""), "chapters": chapters,
            "n_rules": area_n, "n_dated": sum(area_years.values()),
            "recent_2yr": recent2_area,
            "years": dict(sorted(area_years.items())),
        })

    return {"generated": date.today().isoformat(), "this_year": THIS_YEAR,
            "total_oar_rules": total_rules, "baseline_recent_rate": baseline_recent_rate,
            "mapped_rules": sum(a["n_rules"] for a in areas), "areas": areas,
            "note": cat["note"],
            "viz_note": ("Rulemaking recency in each area's CURATED chapter mapping "
                        "(see _meta/catalog/governor-priorities.yml), vs. the corpus-wide "
                        "OAR baseline. A recent-activity spike is consistent with active "
                        "attention, not proof of it — and the absence of one doesn't mean "
                        "inaction (funding/staffing/litigation moves don't show up as "
                        "rulemaking at all). Non-authoritative.")}


def outputs():
    return {OUT: json.dumps(compute(), ensure_ascii=False, separators=(",", ":"))}


def _stable(text: str) -> dict:
    """Parsed JSON with the 'generated' timestamp dropped, so --check compares actual
    data, not the date it happened to run on. Without this, --check trips on nothing but
    the clock whenever it runs on a different calendar day (in its own timezone) than the
    day the committed file was generated on — e.g. a file built in the evening in a
    UTC-negative timezone looks stale to CI running in UTC a few hours later, same date in
    neither reality but 'today' already rolled over in one of them."""
    d = json.loads(text)
    d.pop("generated", None)
    return d


def main():
    outs = outputs()
    if "--check" in sys.argv:
        stale = [p for p, t in outs.items() if not p.exists() or _stable(p.read_text()) != _stable(t)]
        if stale:
            print(f"{OUT.relative_to(REPO_ROOT)} is stale — run: "
                  "python3 src/build_governor_priorities_data.py")
            sys.exit(1)
        print("governor_priorities.json is current.")
        return
    for p, t in outs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    d = json.loads(outs[OUT])
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {len(d['areas'])} areas, "
          f"{d['mapped_rules']} mapped rules of {d['total_oar_rules']} total OAR rules")


if __name__ == "__main__":
    main()
