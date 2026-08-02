#!/usr/bin/env python3
"""Build the GitHub Pages site into ./site/ (gitignored; produced at deploy time).

    python3 src/build_site.py

MIGRATED onto `corpus_toolkit.site`. This file used to carry its own copy of the theme-aware
CSS, the tile markup, the theme toggle and the corpus-index.json emission — shell shared with
two other corpora and now with seven. What stays here is what is actually specific to this
corpus: its numbers, its prose, and the nine self-contained visualisations it publishes.

THE VISUALISATIONS ARE WHY THE SHELL HAS AN EXTENSION POINT. They are standalone HTML files
built by src/build_*.py, copied into site/ verbatim and linked as cards. `extra_files` reports
a missing one by name rather than skipping it, because an absent viz renders as a dead link on
a page that otherwise looks finished.
"""
import json
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from corpus_toolkit import config as config_mod                       # noqa: E402
from corpus_toolkit.site import Page, Section, Tile, build            # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent

VIZZES = [
    ("Agency authority graph", "agency-authority-graph.html",
     "Which agencies share statutory turf — linked by the ORS chapters their rules jointly implement."),
    ("Authority-chain explorer", "authority-explorer.html",
     "Pick any document and walk its authority neighborhood — up to the statutes it implements, down to the rules that implement it."),
    ("Statute operationalization", "statute-operationalization.html",
     "Which ORS chapters get turned into the most administrative rules — and which lie dormant."),
    ("Policy documentation gap", "policy-documentation-gap.html",
     "93 agencies write binding rules; only 9 have any internal policy document ingested into this corpus — a governance-documentation gap, not a claim about missing policies."),
    ("Semantic topic map", "topic-map.html",
     "A 2-D UMAP of every document's embedding: proximity means similar text, so clusters surface topics across ORS, OAR, and policy."),
    ("Regulatory freshness", "regulatory-freshness.html",
     "The functional age of the rule &amp; policy body — which rules lag the statutes they implement, sliced by agency, with the specific documents worth reviewing."),
    ("Policy age", "policy-age.html",
     "How long since each internal policy/procedure/standard was last touched, against a 2-year review cadence — sliced by agency, with the specific documents overdue for review."),
]
# The governor's-priorities and conflict-candidates views are DELIBERATELY ABSENT:
# interpretive content now publishes only through the oregon-stories manifest gate
# (operator decision 2026-08-02 — unreviewed candidates never present as findings).
# Both entered that manifest as drafts; their data builders stay here (the data is
# what the stories side consumes), their pages do not.


def stats() -> dict:
    g = json.loads((REPO / "_meta/graph.json").read_text())
    by = Counter(n["doc_type"] for n in g["nodes"])
    agencies = sorted(p.parent.parent.name
                      for p in (REPO / "agencies").glob("*/policies")
                      if any(p.glob("*.md")))
    return {"statutes": by.get("statute", 0), "rules": by.get("rule", 0),
            "orders": by.get("executive_order", 0),
            "policies": by.get("policy", 0) + by.get("procedure", 0),
            "documents": len(g["nodes"]), "edges": len(g["edges"]),
            "agencies": len(agencies)}


def main() -> int:
    s = stats()
    cards = "\n".join(
        f'      <a class="card" href="{fn}"><b>{title}</b><span>{desc}</span></a>'
        for title, fn, desc in VIZZES)

    out = build(Page(
        config=config_mod.load(REPO / "_meta/corpus.yml"),
        repo="executive-regulatory-frameworks",
        title="Oregon Executive-Branch Law & Policy",
        description=("A non-authoritative, machine-readable mirror of Oregon statutes, "
                     "administrative rules, executive orders and agency policy, with a "
                     "mechanically-derived authority graph."),
        eyebrow="Oregon · executive branch",
        headline="Statute to rule to policy, as one graph",
        lede_html=(
            f"<b>{s['documents']:,} documents</b> — {s['statutes']:,} ORS sections, "
            f"{s['rules']:,} OAR rules, executive orders and agency policy — joined by "
            f"<b>{s['edges']:,} mechanically-derived edges</b>. The spine every other corpus "
            "on this platform cites into."),
        disclaimer=("NON-AUTHORITATIVE reference — not the official text. Always verify "
                    "against the Oregon Legislature or the Secretary of State."),
        tiles=[
            Tile("ORS sections", f"{s['statutes']:,}", "the statutes themselves"),
            Tile("OAR rules", f"{s['rules']:,}",
                 "administrative rules, linked to the statutes they implement"),
            Tile("Authority edges", f"{s['edges']:,}",
                 "statute → rule → policy, derived from the text, never hand-asserted"),
            Tile("Agencies with policy", f"{s['agencies']}",
                 "internal policy, procedure and standards where published"),
        ],
        sections=[
            Section("Explore", f'    <div class="cards">\n{cards}\n    </div>\n'
                    '    <p class="lede">More visuals from this corpus, and every other, '
                    'live in the <a href="https://oregonai.github.io/oregon-stories/">'
                    'stories gallery</a> — the platform\'s one index of published '
                    'visual work.</p>'),
            Section("What the edges mean", """
    <ul class="plain">
      <li><b>An edge is derived, not asserted.</b> A rule that names the statute it is
        adopted under gets an <code>implements</code> edge; one that merely mentions a
        statute does not. The distinction is the whole value of the graph.</li>
      <li><b>A repealed or renumbered section is a disposition, not a gap.</b> This corpus
        mines both from the statute book, so a citation that resolves to nothing can be
        answered with why rather than with silence.</li>
      <li><b>Interpretive work publishes elsewhere, gated.</b> The conflict-candidate
        and governor's-priorities readings moved behind the
        <a href="https://oregonai.github.io/oregon-stories/">oregon-stories</a>
        publication gate — curated readings appear there only after operator review,
        never as findings on this page.</li>
    </ul>"""),
            Section("For agents", """
    <ul class="plain">
      <li><b>MCP server</b> — tools: <code>search_corpus</code> (semantic + keyword),
        <code>get_document</code>, <code>resolve_citation</code>,
        <code>corpus_overview</code>, <code>graph_neighbors</code>,
        <code>authority_chain</code>, <code>issuing_body_profile</code>.</li>
      <li><b>Every document carries provenance</b> — source URL, retrieval date and a
        content hash — and its full text is verified against the snapshot it came from.</li>
    </ul>"""),
        ],
        footer_note=("Unofficial and non-authoritative; not affiliated with the State of "
                     "Oregon."),
        extra_files=[REPO / "viz" / fn for _, fn, _ in VIZZES],
    ))
    print(f"built site/ — {s['documents']:,} documents, {s['edges']:,} edges")
    print(f"  corpus-index.json: {out['index']}")
    missing = [c for c in out["copied"] if c.startswith("MISSING")]
    print(f"  copied {len(out['copied']) - len(missing)} file(s)"
          + (f"; {len(missing)} MISSING: {', '.join(missing)}" if missing else ""))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
