#!/usr/bin/env python3
"""Generate the agency shared-statutory-authority graph — data + a self-contained
interactive HTML visualization.

Two agencies are linked when their administrative rules (OAR) implement the same ORS
statute chapters; the edge weight discounts ubiquitous statutes (e.g. ORS 183, the APA,
which nearly every agency implements) so shared *specialized* domains stand out. This is
the data-supported "which agencies share legal turf" view: a *directed* "agency A cites
agency B" graph is near-empty because 98% of implements-edges point to ORS statutes, which
are statewide (not owned by any agency).

Outputs (both committed, both covered by --check):
  _meta/agency-graph.json        aggregated data (agency -> ORS chapters it implements,
                                 chapter popularity, node metadata) for programmatic reuse
  viz/agency-authority-graph.html  self-contained page (data inlined, no external CDN); a
                                 vanilla-JS canvas force layout projects the edges in-browser
                                 so the rollup / ubiquity / threshold controls need no server

  python3 src/build_agency_graph.py            # write both files
  python3 src/build_agency_graph.py --check    # exit 1 if either is stale (CI)

Attribution uses only node ids/paths + the agency registry (no per-file reads):
  rule oar-CCC-... -> chapter CCC -> registry agency (enrich_oar.load_registry_by_chapter)
  rule implements ors-NN.NNN     -> agency implements ORS chapter NN
"""
import json
import math
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from enrich_oar import load_registry_by_chapter
from repo_lib import REPO_ROOT

GRAPH = REPO_ROOT / "_meta/graph.json"
AGENCIES = REPO_ROOT / "_meta/catalog/agencies.yml"
PROFILES = REPO_ROOT / "_meta/agency-profiles.yml"
JSON_OUT = REPO_ROOT / "_meta/agency-graph.json"
HTML_OUT = REPO_ROOT / "viz/agency-authority-graph.html"

# ORS chapters implemented by this many agencies or more are "ubiquitous" (general-
# government statutes like the APA / public records) — the UI can toggle them out so the
# specialized shared domains stand out. This is a display default, not baked into the data.
UBIQUITY_DEFAULT = 40


def build_data() -> dict:
    graph = json.loads(GRAPH.read_text())
    reg_by_chapter = load_registry_by_chapter()          # {oar_chapter: org}
    orgs = yaml.safe_load(AGENCIES.read_text())["organizations"]
    by_slug = {o["slug"]: o for o in orgs}
    profiles = (yaml.safe_load(PROFILES.read_text()) or {}).get("profiles", {})

    node_type = {n["id"]: n["doc_type"] for n in graph["nodes"]}

    # agency slug -> set of ORS chapters it implements; and its distinct rule count
    ag_chapters: dict[str, set] = {}
    ag_rules: dict[str, set] = {}
    for e in graph["edges"]:
        if e["type"] != "implements":
            continue
        frm, to = e["from"], e["to"]
        if not frm.startswith("oar-") or not to.startswith("ors-"):
            continue
        chapter = frm.split("-")[1]                       # OAR chapter
        org = reg_by_chapter.get(chapter)
        if not org:
            continue
        slug = org["slug"]
        ors_ch = to.split("-")[1].split(".")[0].lower()   # ORS chapter, e.g. "183", "468a"
        ag_chapters.setdefault(slug, set()).add(ors_ch)
        ag_rules.setdefault(slug, set()).add(frm)

    # chapter popularity (how many agencies implement each ORS chapter) -> ubiquity discount
    chapter_pop: dict[str, int] = {}
    for chs in ag_chapters.values():
        for c in chs:
            chapter_pop[c] = chapter_pop.get(c, 0) + 1

    # parent-department grouping (for node color): sub-units share their parent's group.
    def group_of(slug: str) -> str:
        return by_slug.get(slug, {}).get("parent_slug") or slug

    # which groups actually contain more than one in-graph agency (get a distinct color)
    group_members: dict[str, list] = {}
    for slug in ag_chapters:
        group_members.setdefault(group_of(slug), []).append(slug)
    multi = sorted((g for g, m in group_members.items() if len(m) > 1),
                   key=lambda g: (-len(group_members[g]), g))

    agencies = []
    for slug in sorted(ag_chapters):
        grp = group_of(slug)
        prof = profiles.get(slug) or {}
        agencies.append({
            "slug": slug,
            "name": by_slug.get(slug, {}).get("name", slug),
            "rules": len(ag_rules.get(slug, ())),
            "parent": by_slug.get(slug, {}).get("parent_slug"),
            "group": grp,
            "group_name": by_slug.get(grp, {}).get("name", grp),
            "governance": prof.get("governance", "unclassified"),
            "chapters": sorted(ag_chapters[slug]),
        })

    return {
        "note": ("Agency shared-statutory-authority graph. Two agencies are linked when "
                 "their OAR rules implement the same ORS chapters; edge weight = "
                 "sum(1/ln(pop+e)) over shared chapters, so ubiquitous statutes count "
                 "less. Non-authoritative — derived from _meta/graph.json. Regenerate "
                 "with src/build_agency_graph.py after any ingest."),
        "weighting": "sum over shared ORS chapters of 1/ln(chapter_pop + e)",
        "ubiquity_default": UBIQUITY_DEFAULT,
        "counts": {"agencies": len(agencies),
                   "colored_groups": len(multi),
                   "ors_chapters": len(chapter_pop)},
        "colored_groups": [{"slug": g, "name": by_slug.get(g, {}).get("name", g),
                            "members": len(group_members[g])} for g in multi],
        "chapter_pop": dict(sorted(chapter_pop.items())),
        "agencies": agencies,
    }


def _json(data: dict) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False, sort_keys=False) + "\n"


def build_html(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return HTML_TEMPLATE.replace("/*DATA*/", payload)


def outputs() -> dict:
    data = build_data()
    return {JSON_OUT: _json(data), HTML_OUT: build_html(data)}


def main():
    outs = outputs()
    if "--check" in sys.argv:
        stale = [p for p, text in outs.items()
                 if not p.exists() or p.read_text() != text]
        if stale:
            names = ", ".join(str(p.relative_to(REPO_ROOT)) for p in stale)
            print(f"{names} is stale — run: python3 src/build_agency_graph.py")
            sys.exit(1)
        print("agency-graph outputs are current.")
        return
    for p, text in outs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    d = json.loads(_json(build_data()))
    print(f"wrote {JSON_OUT.relative_to(REPO_ROOT)} and {HTML_OUT.relative_to(REPO_ROOT)}: "
          f"{d['counts']['agencies']} agencies, {d['counts']['colored_groups']} colored "
          f"departments, {d['counts']['ors_chapters']} ORS chapters")


# The HTML template lives in a sibling module string to keep this file readable.
from _agency_graph_html import HTML_TEMPLATE  # noqa: E402


if __name__ == "__main__":
    main()
