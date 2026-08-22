#!/usr/bin/env python3
"""Merged agency profiles: registry identity + curated context + derived stats.

  python3 src/agency_profile.py department-of-administrative-services
  python3 src/agency_profile.py --overview      # agencies with in-repo content
  python3 src/agency_profile.py --selftest

Three layers, merged fresh at read time (nothing derived is ever stored):
  registry  (_meta/catalog/agencies.yml)   who the agency is: statutory name, OAR name,
                                           OAR chapter, and the `relations` placing it
                                           under other bodies (ADR 0004)
  curated   (_meta/agency-profiles.yml)    context a human asserted: governance class
                                           (+ required citation basis), where policies
                                           are published (or that they aren't), notes
  derived   (computed here)                what the corpus actually holds: doc counts
                                           by body, verbatim/summary/OCR-recovered
                                           counts, content_exception count, and
                                           last-checked/cadence from the update groups
                                           whose documents belong to this agency

Consumed by build_agency_index.py and by this module's own command line; pure stdlib+yaml
so CI can selftest without the MCP SDK (same pattern as mcp_lib.py).

WHAT SERVES THE MCP TOOL, checked rather than assumed (#187). This corpus is served by
`corpus-mcp-serve` (Dockerfile), which is corpus-toolkit's own server: its
`issuing_body_profile` tool is implemented in `corpus_toolkit/mcp/framework.py` and reads
the same registry file, named here by `plugins.issuing_body_registry` in _meta/corpus.yml.
It does NOT run this module. That matters for the search below: the toolkit's copy still
resolves a query against `name` alone, so once ADR 0003 promotes `name` a reader who asks
that tool for a body by the name the rules index prints stops finding it. Fixing that is a
change to corpus-toolkit and is reported to #168 rather than worked around here."""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import catalog_agencies
from repo_lib import (REPO_ROOT, Checks, content_files, parse_frontmatter, repo_state,
                      yaml_load)

PROFILES = REPO_ROOT / "_meta/agency-profiles.yml"
REGISTRY = REPO_ROOT / "_meta/catalog/agencies.yml"
SOURCES_DIR = REPO_ROOT / "_meta/sources"


def _load():
    reg = yaml_load(REGISTRY.read_text())
    prof = yaml_load(PROFILES.read_text())
    return {o["slug"]: o for o in reg["organizations"]}, prof["profiles"]


_STATS_CACHE = None  # (repo_state, stats, groups) — in-memory only, per docstring ("nothing
                     # derived is ever stored" means never written to disk/repo; this just
                     # memoizes within one long-lived process, e.g. the MCP server)


def _derived_stats():
    """Per-agency corpus stats + update-group freshness. At ~68k documents, scanning every
    file's frontmatter takes real minutes — cached in memory for a long-lived process (the
    MCP server) and invalidated via the same repo_state() fingerprint the FTS index uses, so
    a CLI one-shot run and a server that's been up for days both always see current data."""
    global _STATS_CACHE
    state = repo_state()
    if _STATS_CACHE and _STATS_CACHE[0] == state:
        return _STATS_CACHE[1], _STATS_CACHE[2]

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
        g = yaml_load(gp.read_text())
        groups[g["group"]] = {"last_checked": g.get("last_checked"),
                              "recheck": g.get("recheck"),
                              "upstream_signal": g.get("upstream_signal", "")[:160]}
    _STATS_CACHE = (state, stats, groups)
    return stats, groups


def _groups_for_agency(slug: str, registry_entry: dict, groups: dict) -> dict:
    """Update groups covering this agency: by slug-prefixed group name, plus the
    corpus-wide groups that cover its jurisdiction-wide docs.

    A sub-unit falls back to the groups named for the body it is placed UNDER — the OAM
    group covering the DAS Chief Financial Office is named for DAS, because that is whose
    manual it is. The placement is read off `relations` (ADR 0004), which is the registry's
    only statement of it now that #174 has retired `parent_slug`.

    EVERY PARENT IS TRIED, not the first. A body may hold more than one relation, because
    the sources may place it under different parents and ADR 0003 keeps that disagreement;
    what this asks of each is "is there an update group named for you", which several
    parents can answer without contradicting each other. That is a different question from
    the rollups in `build_policy_gap.py` and `build_agency_graph.py`, which must pick ONE
    body and therefore refuse to pick at all — here nothing is being chosen between."""
    out = {}
    for name, g in groups.items():
        if name.startswith(slug):
            out[name] = g
    if not out:
        for target in catalog_agencies.parent_targets(registry_entry):
            for name, g in groups.items():
                if name.startswith(target):
                    out[name] = g
    return out


def search(registry: dict, query: str) -> list:
    """Slugs of every body a reader could mean by `query`.

    NAME READER — DISPLAY, and the design decision of #187. Search is filed under
    DISPLAY rather than JOIN because what it hands back is a candidate for a READER to
    accept — `profile()` requires a unique hit and reports candidates otherwise — where a
    join decides an attribution with nobody in the loop. It spans every name a
    body is known by — statutory name, OAR name, curated aliases — through
    `catalog_agencies.name_matches()`, which is the ONE place that question is answered for
    both this search and the command-line one. Searching `name` alone was the same behaviour
    while `name` held the OAR title; once ADR 0003 promotes the statutory name, a reader who
    knows the body by the name the rules index prints (the name all 36,953 rule documents
    carry) would stop finding it, and a search that answers "no such body" to a name the
    body really has is worse than one that asks which of two bodies was meant.

    `registry` is a PARAMETER rather than a load, so the behaviour can be proven against a
    registry whose `name` and `oar_name` differ — which no committed row's do today."""
    return [s for s, o in registry.items() if catalog_agencies.name_matches(o, query)]


def profile(slug_or_query: str) -> dict:
    registry, curated = _load()
    slug = slug_or_query
    if slug not in registry:
        hits = search(registry, slug_or_query)
        if len(hits) != 1:
            # BOTH NAMES ON A CANDIDATE. A reader who searched by the OAR name and is handed
            # eight statutory names has been asked to disambiguate between bodies they
            # cannot recognise; the name they typed has to be among the ones they are shown.
            return {"error": f"no unique agency match for {slug_or_query!r}",
                    "candidates": [{"slug": s, "name": registry[s]["name"],
                                    "oar_name": registry[s].get("oar_name")}
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
        # NAME READER — DISPLAY. Both names are published, because after ADR 0003 they are
        # two different facts about the body: `name` is what its enabling authority calls it
        # and `oar_name` is what the rules index prints — the string this body's rule
        # documents carry in `issuing_body`. Showing one and hiding the other would leave a
        # reader unable to tell which of the two they are looking at.
        # OUTPUT SCHEMA CHANGE (#174): `parent_slug` is GONE from this tuple and
        # `relations` stands where it stood. The tuple is what consumers of this module
        # read, so dropping a key is a visible contract change and not an internal one —
        # and dropping it without putting the placement back would leave the profile unable
        # to say what body this one sits under, which is a fact it published until today.
        # `relations` says more than the pointer did: the target, whose evidence places it
        # there, which of ADR 0004's two kinds it is, and the authority that makes it true.
        "registry": {k: reg.get(k) for k in
                     ("name", "oar_name", "oar_chapter", "relations", "parent_chapter",
                      "source_url")},
        # THE BODIES PLACED UNDER THIS ONE, read off their `relations` (ADR 0004). A body
        # whose sources disagree about its parent is listed under EVERY parent they name,
        # which is the opposite of what the two rollups do and is right for the same
        # reason: a listing states each source's reading side by side, where a rollup would
        # have to publish one of them as the answer.
        # NAME READER — DISPLAY: the statutory name, shown to a reader beside the slug.
        "sub_units": [{"slug": o["slug"], "name": o["name"],
                       "oar_chapter": o["oar_chapter"]}
                      for o in registry.values()
                      if slug in catalog_agencies.parent_targets(o)],
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
        # NAME READER — DISPLAY: one row per body for the generated agency overview.
        rows.append({"slug": slug, "name": registry[slug]["name"],
                     "governance": c.get("governance", "unclassified"),
                     "policies_published": c.get("policies_published", "unknown"),
                     "documents": s["documents"], "verbatim": s["verbatim"],
                     "ocr_recovered": s["ocr_recovered"],
                     "content_exceptions": s["content_exceptions"],
                     "last_checked": last or None})
    return rows


# THE REGISTRY AS ADR 0003 LEAVES IT, and the only place this module's two names differ:
# `name` and `oar_name` hold identical bytes on 186 of the 189 committed rows, differing only
# on the three whose established statutory name is not the rules index's title (#168), so a
# search proof that reads the committed registry passes whichever field the matcher reads on
# all but three of them. Both names
# below are real — ORS 471.705 names the commission one thing and the rules index prints
# chapter 845 under the other.
_SEARCH_FIXTURE = {
    "oregon-liquor-control-commission": {
        "slug": "oregon-liquor-control-commission",
        "name": "Oregon Liquor and Cannabis Commission",
        "oar_name": "Oregon Liquor Control Commission",
        "aliases": ["OLCC"], "oar_chapter": "845"},
    "board-of-nursing": {
        "slug": "board-of-nursing", "name": "Oregon State Board of Nursing",
        "oar_name": "Board of Nursing", "oar_chapter": "851"},
}


def selftest():
    check = Checks()

    # THE SEARCH THE MCP SERVER SERVES, against a registry whose two names disagree. A
    # reader arrives holding whichever name their source printed; the tool has to reach the
    # same body from either one, because promoting `name` (#168) must not make a body
    # unfindable by the name 36,953 rule documents call it.
    fx = _SEARCH_FIXTURE
    check("search resolves a body by its statutory name",
          search(fx, "liquor and cannabis") == ["oregon-liquor-control-commission"])
    check("search resolves the same body by its OAR name",
          search(fx, "liquor control") == ["oregon-liquor-control-commission"])
    check("search resolves a body by a curated alias",
          search(fx, "OLCC") == ["oregon-liquor-control-commission"])
    check("search refuses a name no source prints", search(fx, "zzz") == [])
    check("search is not a listing of every body", search(fx, "") == [])
    p = profile("department-of-administrative-services")
    check("DAS profile has cited governance",
          p["curated"]["governance"] == "executive_branch"
          and "ORS 184.305" in p["curated"]["governance_basis"])
    check("DAS derived stats present", isinstance(p["in_repo"], dict)
          and p["in_repo"]["documents"] > 100)
    check("DAS has 3 sub-units", len(p["sub_units"]) == 3)
    # THE OUTPUT SCHEMA #174 CHANGES, asserted rather than described. The tuple this module
    # emits is a contract, so the key that left and the key that took its place are both
    # stated here — a consumer that still reads `parent_slug` off a profile gets None and
    # no error, which is the failure that has to be visible from this side.
    check("the profile publishes no parent_slug", "parent_slug" not in p["registry"])
    check("the profile publishes the relations that replaced it",
          isinstance(p["registry"]["relations"], list))
    # THE PLACEMENT READ THE WAY EVERY OTHER CONSUMER READS IT. DAS's sub-units and the
    # CFO's update group both come off `relations` now, and both are facts about the
    # committed registry rather than about a fixture.
    check("a sub-unit's own relations name DAS",
          all("department-of-administrative-services"
              in catalog_agencies.parent_targets(_load()[0][u["slug"]])
              for u in p["sub_units"]))
    check("DAS update group freshness present",
          any(g.get("last_checked") for g in p["update_groups"].values()))
    p2 = profile("financial office")
    check("search resolves CFO sub-unit", p2.get("slug", "").endswith("chief-financial-office"))
    check("unknown agency errors gracefully", "error" in profile("zzz-not-real"))
    rows = overview()
    check("overview has rows incl. DAS",
          any(r["slug"] == "department-of-administrative-services" for r in rows))
    sys.exit(check.report())


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
