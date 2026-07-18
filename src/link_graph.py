#!/usr/bin/env python3
"""Mechanically link the corpus relationship graph and emit the MCP-ready
_meta/graph.json.

Edges are derived ONLY from signals present in each document itself (HC-1):
  - procedure <-> policy: the procedure's number minus _PR is its policy;
  - OAR -> ORS: the structured "Statutory/Other Authority:" / "Statutes/Other
    Implemented:" lines OARD prints inside every rule's full text;
  - policy/procedure/manual -> ORS/OAR: the REFERENCE/AUTHORITY header block at
    the top of the document's full text, plus frontmatter legal_authority;
  - renumbered OAR citations resolve through the mapping recorded in
    _meta/catalog/oar.yml (e.g. "OAR 125-800-0020" -> oar-128-030-0020).

Generic in-text ORS<->ORS cross-references are deliberately NOT linked (noise).
Existing hand-authored edges are preserved; reruns are no-ops (idempotent).

  python3 src/link_graph.py           # write edges + regenerate _meta/graph.json
  python3 src/link_graph.py --check   # exit 1 if graph.json is stale (CI)
"""
import json
import re
import sys
from pathlib import Path

import yaml

from repo_lib import REPO_ROOT, content_files, extract_fulltext, parse_frontmatter, ws_only

GRAPH = REPO_ROOT / "_meta/graph.json"
OAR_CATALOG = REPO_ROOT / "_meta/catalog/oar.yml"

ORS_RE = re.compile(r"\b(\d{2,3}[A-Z]?\.\d{3})\b")
OAR_RULE_RE = re.compile(r"\b(\d{3}-\d{3}-\d{4})\b")
OAR_DIV_RE = re.compile(r"OAR\s+(\d{3}-\d{3})(?!-)")
DIV_LINK_CAP = 12  # division-level citations link all its rules only if small

REL_KEYS = ["implements", "implemented_by", "references_external", "related", "supersedes"]


def build_renumber_map():
    """old rule number -> served rule number, and old division -> served division(s)."""
    cat = yaml.safe_load(OAR_CATALOG.read_text())
    rule_map, div_map = {}, {}
    for c in cat["chapters"]:
        for d in c["divisions"]:
            rules = d.get("rules")
            if not isinstance(rules, list):
                continue
            for r in rules:
                served = r.get("served_as") or (
                    r.get("note", "").split("OARD serves ")[-1].split(" ")[0]
                    if r.get("status") == "renumbered" else None)
                if r.get("status") == "renumbered" and served and OAR_RULE_RE.fullmatch(served):
                    rule_map[r["number"]] = served
                    old_div = "-".join(r["number"].split("-")[:2])
                    new_div = "-".join(served.split("-")[:2])
                    div_map.setdefault(old_div, set()).add(new_div)
    return rule_map, div_map


def authority_text(fm, body):
    """The authority-bearing text regions for a doc (never the whole full text)."""
    parts = [" ".join(str(x) for x in (fm.get("legal_authority") or []))]
    ft = extract_fulltext(body)
    if not ft:
        return " ".join(parts)
    t = ws_only(ft)
    if fm["doc_type"] == "rule":
        for marker in ("Statutory/Other Authority:", "Statutes/Other Implemented:"):
            i = t.find(marker)
            if i > -1:
                seg = t[i + len(marker):]
                end = min([x for x in (seg.find("History:"), seg.find("Statutes/Other"),
                                       len(seg)) if x > -1])
                parts.append("ORS " + seg[:end])  # ensure bare numbers count as ORS refs
    elif fm["doc_type"] in ("policy", "procedure", "manual", "standard"):
        # header region: everything before the first substantive heading
        m = re.search(r"\b(PURPOSE|POLICY STATEMENT|POLICY/)\b", t)
        parts.append(t[: m.start()] if m else t[:2500])
    elif fm["doc_type"] == "executive_order":
        # orders are short and cite their authority inline throughout
        parts.append(t)
    return " ".join(parts)


def resolve_citations(text, docs, rule_map, div_map, rules_by_div, self_id):
    """Set of in-repo ids this authority text cites."""
    out = set()
    for sec in ORS_RE.findall(text):
        tid = f"ors-{sec.lower()}"
        if tid in docs:
            out.add(tid)
    for rule in OAR_RULE_RE.findall(text):
        rule = rule_map.get(rule, rule)
        tid = f"oar-{rule}"
        if tid in docs:
            out.add(tid)
    for div in OAR_DIV_RE.findall(text):
        for target_div in div_map.get(div, {div}):
            rules = rules_by_div.get(target_div, [])
            if 0 < len(rules) <= DIV_LINK_CAP:
                out.update(rules)
    out.discard(self_id)
    return out


def rewrite_relationships(path, new_rel):
    """Textually splice the relationships block (between 'relationships:' and 'tags:')."""
    raw = path.read_text()
    m = re.search(r"^relationships:\n(?:^[ \t].*\n)*", raw, re.M)
    if not m:
        return False
    block = "relationships:\n"
    for k in REL_KEYS:
        vals = new_rel.get(k) or []
        if not vals:
            block += f"  {k}: []\n"
        else:
            block += f"  {k}:\n"
            for v in vals:
                block += f'    - "{v}"\n' if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", v) \
                    else f"    - {v}\n"
    new_raw = raw[:m.start()] + block + raw[m.end():]
    if new_raw != raw:
        path.write_text(new_raw)
        return True
    return False


def compute(write=False):
    docs = {}      # id -> {path, fm, body}
    for p in content_files():
        fm, body = parse_frontmatter(p)
        docs[fm["id"]] = {"path": p, "fm": fm, "body": body}

    rules_by_div = {}
    for did in docs:
        if did.startswith("oar-"):
            rules_by_div.setdefault("-".join(did[4:].split("-")[:2]), []).append(did)
    rule_map, div_map = build_renumber_map()

    # start from existing edges
    rel = {did: {k: list((d["fm"].get("relationships") or {}).get(k) or [])
                 for k in REL_KEYS} for did, d in docs.items()}

    # 1) citation-derived implements edges (rules/policies/procedures/manuals/standards)
    for did, d in docs.items():
        if d["fm"]["doc_type"] in ("rule", "policy", "procedure", "manual", "standard",
                                   "executive_order"):
            targets = resolve_citations(
                authority_text(d["fm"], d["body"]), docs, rule_map, div_map,
                rules_by_div, did)
            rel[did]["implements"].extend(sorted(targets))

    # 2) procedure <-> policy naming pairs
    for did, d in docs.items():
        if d["fm"]["doc_type"] == "procedure" and did.endswith("_pr"):
            pol = did[:-3]
            if pol in docs:
                rel[did]["implements"].append(pol)

    # 3) symmetry: mirror implements -> implemented_by (resolved ids only)
    for did in docs:
        for t in rel[did]["implements"]:
            if t in docs:
                rel[t]["implemented_by"].append(did)

    # dedupe + deterministic order: resolved ids sorted first, citation strings after
    for did in docs:
        for k in REL_KEYS:
            vals = rel[did][k]
            ids = sorted({v for v in vals if v in docs})
            strs = sorted({v for v in vals if v not in docs})
            rel[did][k] = ids + strs

    changed = 0
    if write:
        for did, d in docs.items():
            if rewrite_relationships(d["path"], rel[did]):
                changed += 1

    nodes = [{"id": did, "title": d["fm"]["title"], "doc_type": d["fm"]["doc_type"],
              "path": str(d["path"].relative_to(REPO_ROOT))}
             for did, d in sorted(docs.items())]
    edges = []
    for did in sorted(docs):
        for k in REL_KEYS:
            for t in rel[did][k]:
                if t in docs:
                    edges.append({"from": did, "to": t, "type": k})
    graph = {"note": ("Generated by src/link_graph.py from frontmatter relationships "
                      "(themselves mechanically derived from authority citations in each "
                      "document). Regenerate after any ingest; CI checks freshness."),
             "nodes": nodes, "edges": edges}
    return graph, changed


def main():
    if "--check" in sys.argv:
        graph, _ = compute(write=False)
        current = json.dumps(graph, indent=1, ensure_ascii=False) + "\n"
        if not GRAPH.exists() or GRAPH.read_text() != current:
            print("_meta/graph.json is stale — run: python3 src/link_graph.py")
            sys.exit(1)
        print("_meta/graph.json is current.")
        return
    graph, changed = compute(write=True)
    # recompute from the now-updated files so graph.json matches committed frontmatter
    graph, _ = compute(write=False)
    GRAPH.write_text(json.dumps(graph, indent=1, ensure_ascii=False) + "\n")
    from collections import Counter
    c = Counter(e["type"] for e in graph["edges"])
    print(f"updated {changed} file(s); graph: {len(graph['nodes'])} nodes, "
          f"{len(graph['edges'])} edges ({dict(c)})")


if __name__ == "__main__":
    main()
