#!/usr/bin/env python3
"""Merged agency profiles: registry identity + curated context + derived stats.

  python3 src/agency_profile.py department-of-administrative-services
  python3 src/agency_profile.py --overview      # agencies with in-repo content
  python3 src/agency_profile.py --selftest

Three layers, merged fresh at read time (nothing derived is ever stored):
  registry  (_meta/catalog/agencies.yml)   who the agency is: name, OAR chapter,
                                           parent/sub-unit hierarchy
  curated   (_meta/agency-profiles.yml)    context a human asserted: governance class
                                           (+ required citation basis), where policies
                                           are published (or that they aren't), notes
  derived   (computed here)                what the corpus actually holds: doc counts
                                           by body, verbatim/summary/OCR-recovered
                                           counts, content_exception count, and
                                           last-checked/cadence from the update groups
                                           whose documents belong to this agency

Consumed by the MCP server (agency_profile tool) and build_agency_index.py; pure
stdlib+yaml so CI can selftest without the MCP SDK (same pattern as mcp_lib.py)."""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml

from repo_lib import REPO_ROOT, content_files, parse_frontmatter

PROFILES = REPO_ROOT / "_meta/agency-profiles.yml"
REGISTRY = REPO_ROOT / "_meta/catalog/agencies.yml"
SOURCES_DIR = REPO_ROOT / "_meta/sources"


def _load():
    reg = yaml.safe_load(REGISTRY.read_text())
    prof = yaml.safe_load(PROFILES.read_text())
    return {o["slug"]: o for o in reg["organizations"]}, prof["profiles"]


def _derived_stats():
    """Per-agency corpus stats + update-group freshness, computed fresh."""
    stats = defaultdict(lambda: {"documents": 0, "by_body": defaultdict(int),
                                 "verbatim": 0, "summary": 0, "ocr_recovered": 0,
                                 "content_exceptions": 0})
    for p in content_files():
        fm, _ = parse_frontmatter(p)
        a = fm.get("agency")
        s = stats[a]
        s["documents"] += 1
        rel = p.relative_to(REPO_ROOT).parts
        body = rel[2] if rel[0] == "agencies" and len(rel) > 2 else rel[0]
        s["by_body"][body] += 1
        if fm.get("content_mode") == "verbatim":
            s["verbatim"] += 1
        else:
            s["summary"] += 1
        if "OCR" in (fm.get("conversion_notes") or ""):
            s["ocr_recovered"] += 1
        if fm.get("content_exception"):
            s["content_exceptions"] += 1

    # update-group freshness: attribute a group to the agencies its sources' docs
    # belong to (id prefix match is enough: group files name their agency or body)
    groups = {}
    for gp in sorted(SOURCES_DIR.glob("*.yml")):
        g = yaml.safe_load(gp.read_text())
        groups[g["group"]] = {"last_checked": g.get("last_checked"),
                              "recheck": g.get("recheck"),
                              "upstream_signal": g.get("upstream_signal", "")[:160]}
    return stats, groups


def _groups_for_agency(slug: str, registry_entry: dict, groups: dict) -> dict:
    """Update groups covering this agency: by slug-prefixed group name, plus the
    corpus-wide groups that cover its jurisdiction-wide docs."""
    out = {}
    for name, g in groups.items():
        if name.startswith(slug):
            out[name] = g
    # sub-units of DAS: the OAM group (CFO) has a non-slug name; match via note text
    if not out and registry_entry.get("parent_slug"):
        for name, g in groups.items():
            if name.startswith(registry_entry["parent_slug"]):
                out[name] = g
    return out


def profile(slug_or_query: str) -> dict:
    registry, curated = _load()
    slug = slug_or_query
    if slug not in registry:
        q = slug_or_query.lower()
        hits = [s for s, o in registry.items() if q in o["name"].lower()]
        if len(hits) != 1:
            return {"error": f"no unique agency match for {slug_or_query!r}",
                    "candidates": [{"slug": s, "name": registry[s]["name"]}
                                   for s in hits[:8]]}
        slug = hits[0]
    stats, groups = _derived_stats()
    reg = registry[slug]
    s = stats.get(slug)
    derived = None
    if s:
        derived = {"documents": s["documents"], "by_body": dict(s["by_body"]),
                   "verbatim": s["verbatim"], "summary_only": s["summary"],
                   "ocr_recovered": s["ocr_recovered"],
                   "content_exceptions": s["content_exceptions"]}
    return {
        "slug": slug,
        "registry": {k: reg.get(k) for k in
                     ("name", "oar_chapter", "parent_slug", "parent_chapter",
                      "source_url")},
        "sub_units": [{"slug": o["slug"], "name": o["name"],
                       "oar_chapter": o["oar_chapter"]}
                      for o in registry.values() if o.get("parent_slug") == slug],
        "curated": curated.get(slug, {"governance": "unclassified",
                                      "policies_published": "unknown"}),
        "in_repo": derived or "no documents ingested for this agency yet",
        "update_groups": _groups_for_agency(slug, reg, groups),
    }


def overview() -> list:
    """One row per agency that has in-repo content (agency-scoped docs)."""
    registry, curated = _load()
    stats, groups = _derived_stats()
    rows = []
    for slug, s in sorted(stats.items()):
        if slug not in registry:
            continue  # statewide/external pseudo-agencies
        c = curated.get(slug, {})
        gs = _groups_for_agency(slug, registry[slug], groups)
        last = max((g["last_checked"] or "" for g in gs.values()), default="")
        rows.append({"slug": slug, "name": registry[slug]["name"],
                     "governance": c.get("governance", "unclassified"),
                     "policies_published": c.get("policies_published", "unknown"),
                     "documents": s["documents"], "verbatim": s["verbatim"],
                     "ocr_recovered": s["ocr_recovered"],
                     "content_exceptions": s["content_exceptions"],
                     "last_checked": last or None})
    return rows


def selftest():
    ok = True
    def check(name, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok = ok and cond
    p = profile("department-of-administrative-services")
    check("DAS profile has cited governance",
          p["curated"]["governance"] == "executive_branch"
          and "ORS 184.305" in p["curated"]["governance_basis"])
    check("DAS derived stats present", isinstance(p["in_repo"], dict)
          and p["in_repo"]["documents"] > 100)
    check("DAS has 3 sub-units", len(p["sub_units"]) == 3)
    check("DAS update group freshness present",
          any(g.get("last_checked") for g in p["update_groups"].values()))
    p2 = profile("financial office")
    check("search resolves CFO sub-unit", p2.get("slug", "").endswith("chief-financial-office"))
    check("unknown agency errors gracefully", "error" in profile("zzz-not-real"))
    rows = overview()
    check("overview has rows incl. DAS",
          any(r["slug"] == "department-of-administrative-services" for r in rows))
    print("selftest", "OK" if ok else "FAILED")
    sys.exit(0 if ok else 1)


def main():
    if "--selftest" in sys.argv:
        selftest()
    elif "--overview" in sys.argv:
        for r in overview():
            print(r)
    elif len(sys.argv) > 1:
        import json
        print(json.dumps(profile(sys.argv[1]), indent=1, default=str))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
