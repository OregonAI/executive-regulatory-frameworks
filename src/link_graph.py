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

from repo_lib import (REPO_ROOT, content_files, extract_fulltext, parse_frontmatter, ws_only,
                      yaml_load)

GRAPH = REPO_ROOT / "_meta/graph.json"
OAR_CATALOG = REPO_ROOT / "_meta/catalog/oar.yml"

# #293: the same chapter/section digit-count question `citation_schemes.ORS_C` answers,
# widened the same way and for the same reason — measured on this corpus, not assumed
# (see the comment above `citation_schemes.ORS_CHAPTER_TOKEN`). Duplicated rather than
# imported: `citation_schemes` imports FROM this module (`build_renumber_map`), so the
# reverse import would be circular; `repo_lib` is the natural shared home if a third site
# ever needs this token. Currently a no-op on the committed corpus (no rule's own
# authority-header text cites a single-digit chapter or a 4-digit UCC section) — fixed
# anyway because leaving the same floor here would be #293 again, just unnoticed until an
# authority header happened to use one.
ORS_RE = re.compile(r"\b(\d{1,3}[A-Z]?\.\d{3,4})\b")
OAR_RULE_RE = re.compile(r"\b(\d{3}-\d{3}-\d{4})\b")
OAR_DIV_RE = re.compile(r"OAR\s+(\d{3}-\d{3})(?!-)")
DIV_LINK_CAP = 12  # division-level citations link all its rules only if small

# Policy-to-policy cross-references (a policy's own "Directives/References" block naming
# other agencies' policies). These are `related` edges, not authority `implements`.
#   DAS Policy: 107-001-015   -> das-107-001-015   (hyphen triple; also matches the dotted
#                                form "DAS Policy 50.010.03" and 2-digit families like 10-011-01)
#   (DOC) Policy: 30.2.3      -> doc-30-2-3        (dotted triple, DOC numbering)
#   OYA policy: 0-2.3 / I-A-10.1  -> oya-0-2-3 / oya-i-a-10-1  (OYA's own numbering scheme)
DAS_POL_RE = re.compile(r"DAS Policy:?\s*(\d{2,3})[-.](\d{3})[-.](\d{2,3})", re.I)
DOC_POL_RE = re.compile(r"\bPolicy:?\s*(\d{1,3}\.\d{1,2}\.\d{1,3})\b")
OSH_POL_RE = re.compile(r"\bPolicy:?\s*(\d{1,2}\.\d{3})\b")   # OSH two-part number, e.g. 1.010
OYA_POL_RE = re.compile(r"\b(0-\d{1,2}\.\d{1,2}|[IVX]{1,3}-[A-Z]-\d{1,2}(?:\.\d{1,2})?)\b")

REL_KEYS = ["implements", "implemented_by", "references_external", "related", "supersedes"]


def contributes_implements_edges(doc_type, status, doc_id, suspended):
    """THE ONE DECLARATION of which documents contribute implements edges.

    NOT-CURRENT IS TWO THINGS, and until #229 they were the same set. A REPEALED rule
    is gone and implements nothing. A SUSPENDED one is paused to a date it prints
    itself, so it keeps its edge (#242): the statute would otherwise understate what
    implements it, and a reader could not tell a five-month pause from a permanent
    repeal -- the collapse #229's own criteria forbid, one layer below where its
    proofs look.

    compute() and --selftest both call THIS, so the proof gates the real predicate
    rather than a second copy of it that can drift out of agreement.
    """
    if doc_type not in LINK_DOC_TYPES:
        return False
    if doc_type != "rule":
        return True
    if status == "current":
        return True
    return doc_id in suspended


def suspended_rule_ids():
    """Rule ids the Bulletin SUSPENDED, which is not the same as repealed (#242).

    A suspension is temporary and dated: 30 of 40 sampled documents print their own end
    date, and August's run through 2026-12-27. The rule is on the books and returns to force
    on a known day, so it still implements its statute -- dropping its edge makes the statute
    understate what implements it, and makes a five-month pause indistinguishable from a
    permanent repeal.

    THE ACTION IS ONLY IN THE CATALOG. A suspended rule's document reads `status: superseded`
    and says nothing about why, because corpus-toolkit's shared enum has no word for a
    suspension (corpus-toolkit#159). `legal_status_action` carries it, so this reads the
    catalog rather than the document -- and a rule marked superseded by anything OTHER than a
    filed suspension keeps the old behaviour.
    """
    cat = yaml_load(OAR_CATALOG.read_text())
    out = set()
    for c in cat["chapters"]:
        for d in c["divisions"]:
            for r in (d.get("rules") or []):
                if isinstance(r, dict) and r.get("legal_status_action") == "suspend":
                    out.add(f"oar-{r['number']}")
    return out


def build_renumber_map():
    """old rule number -> served rule number, and old division -> served division(s)."""
    cat = yaml_load(OAR_CATALOG.read_text())
    rule_map, div_map = {}, {}
    for c in cat["chapters"]:
        for d in c["divisions"]:
            rules = d.get("rules")
            if not isinstance(rules, list):
                continue
            for r in rules:
                # `served_as` ALONE, not a fallback that re-derives the same fact by
                # splitting `note` on the words "OARD serves " (#334). That parse was a
                # FACT A READER PULLS OUT OF PROSE BY SUBSTRING -- exactly the pattern #334
                # found live in catalog_oar.py's VANISHED_DIVISION_MARK -- and it read a
                # field `served_as` already carries structurally, defensively, for a case
                # that could not happen: ingest_oar.py's one renumbered write site sets
                # `status`, `note` and `served_as` together, in the same statement, so a
                # `renumbered` row with a note and no `served_as` is not a shape this
                # pipeline produces. catalog_oar.py's own `served-as-tracks-renumbered`
                # check (part of `catalog_oar.py --check`, in CI) now GATES that as a
                # contract violation rather than leaving it to be inferred here, so this
                # reads the structured field and nothing else.
                served = r.get("served_as")
                if r.get("status") == "renumbered" and served and OAR_RULE_RE.fullmatch(served):
                    rule_map[r["number"]] = served
                    old_div = "-".join(r["number"].split("-")[:2])
                    new_div = "-".join(served.split("-")[:2])
                    div_map.setdefault(old_div, set()).add(new_div)
    return rule_map, div_map


def build_ors_renumber_map(docs):
    """old ORS section (lowercase, no 'ORS ' prefix) -> current ors-* doc id, mined from
    statute docs' own relationships.supersedes ("ORS <old>", populated by
    ingest_ors_renumbering.py from the official Legislative Counsel renumbering table).
    Mirrors build_renumber_map()'s OAR-to-OAR role for the ORS side."""
    out = {}
    for did, d in docs.items():
        if not did.startswith("ors-"):
            continue
        for s in (d["fm"].get("relationships") or {}).get("supersedes") or []:
            m = re.match(r"ORS\s+(\S+)", str(s), re.I)
            if m:
                out[m.group(1).lower()] = did
    return out


def authority_text(fm, body):
    """The authority-bearing text regions for a doc (never the whole full text).

    For rules, this is used to derive `implements` edges, so it must reflect ONLY what
    the rule implements — never its broader rulemaking authority. legal_authority and
    the body's "Statutory/Other Authority:" line frequently cite statutes the rule does
    NOT implement (general enabling statutes, adjacent context, etc.); mixing them in
    here previously contaminated `implements` with authority-only citations (see
    the retired BACKLOG.md's "relationships.implements built from legal_authority" entry,
    recoverable from git history). Rules
    therefore use ONLY the already-parsed statutes_implemented frontmatter (populated by
    enrich_oar.py from the body's "Statutes/Other Implemented:" line) — never
    legal_authority, never the raw "Statutory/Other Authority:" text."""
    if fm["doc_type"] == "rule":
        return " ".join(str(x) for x in (fm.get("statutes_implemented") or []))
    parts = [" ".join(str(x) for x in (fm.get("legal_authority") or []))]
    ft = extract_fulltext(body)
    if not ft:
        return " ".join(parts)
    t = ws_only(ft)
    if fm["doc_type"] in ("policy", "procedure", "manual", "standard"):
        if str(fm.get("agency", "")).startswith(
                ("oregon-health-authority", "department-of-human-services",
                 "oregon-watershed-enhancement-board", "public-utility-commission",
                 "department-of-environmental-quality")):
            parts.append(t)  # small agencies whose policies cite ORS/OAR/other policies
                             # throughout the body, not in a header authority block
        else:
            # header region: everything before the first substantive heading
            m = re.search(r"\b(PURPOSE|POLICY STATEMENT|POLICY/)\b", t)
            parts.append(t[: m.start()] if m else t[:2500])
    elif fm["doc_type"] == "executive_order":
        # orders are short and cite their authority inline throughout
        parts.append(t)
    return " ".join(parts)


def resolve_citations(text, docs, rule_map, div_map, rules_by_div, self_id, ors_renumber_map):
    """Set of in-repo ids this authority text cites."""
    out = set()
    for sec in ORS_RE.findall(text):
        tid = f"ors-{sec.lower()}"
        if tid in docs:
            out.add(tid)
        elif sec.lower() in ors_renumber_map:
            out.add(ors_renumber_map[sec.lower()])
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


def policy_xrefs(text, docs, self_id):
    """In-repo policy ids cross-referenced by a policy's directives/references block —
    `related` edges (not authority). Resolves DAS (hyphen or dotted), DOC (dotted-triple), and
    OYA (its own numbering scheme) policy numbers; links only to policies actually in the
    corpus."""
    out = set()
    for g1, g2, g3 in DAS_POL_RE.findall(text):
        tid = f"das-{g1}-{g2}-{g3}"
        if tid in docs:
            out.add(tid)
    for num in DOC_POL_RE.findall(text):
        tid = "doc-" + num.replace(".", "-")
        if tid in docs:
            out.add(tid)
    for num in OYA_POL_RE.findall(text):
        tid = "oya-" + num.lower().replace(".", "-")
        if tid in docs:
            out.add(tid)
    if self_id.startswith("oha-osh"):        # OSH policies cross-reference sibling OSH policies
        for num in OSH_POL_RE.findall(text):
            tid = "oha-osh-" + num.replace(".", "-")
            if tid in docs:
                out.add(tid)
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


LINK_DOC_TYPES = ("rule", "policy", "procedure", "manual", "standard", "executive_order")


def compute(write=False):
    # Store only the small pre-extracted authority region, never the full body — at
    # ~68k files (incl. 30k full-text statutes) retaining every body OOM-kills the
    # process on a memory-constrained host. authority_text() reads the body once here
    # and we drop it; nothing downstream needs the full text.
    docs = {}      # id -> {path, fm, auth}
    for p in content_files():
        fm, body = parse_frontmatter(p)
        auth = authority_text(fm, body) if fm["doc_type"] in LINK_DOC_TYPES else ""
        docs[fm["id"]] = {"path": p, "fm": fm, "auth": auth}

    rules_by_div = {}
    for did in docs:
        if did.startswith("oar-"):
            rules_by_div.setdefault("-".join(did[4:].split("-")[:2]), []).append(did)
    rule_map, div_map = build_renumber_map()
    ors_renumber_map = build_ors_renumber_map(docs)

    # start from existing edges — but only for fields that are ever hand-authored
    # (related, references_external, supersedes: the latter written by
    # ingest_ors_renumbering.py/enrich_oar.py's renumbering detection). `implements` and
    # `implemented_by` are NEVER hand-authored anywhere in the pipeline (every ingest_*.py
    # writes only the placeholder `implements: []`; this script is the sole writer of a
    # non-empty value) — seeding them from existing frontmatter only let bad edges from a
    # prior buggy run survive forever, since nothing downstream ever prunes, only unions.
    # Always recomputing them fresh each run makes fixes to the derivation logic below
    # self-migrating: no separate reset/migration pass is needed after a bugfix.
    PRESERVED_KEYS = ["references_external", "related", "supersedes"]
    rel = {did: {k: (list((d["fm"].get("relationships") or {}).get(k) or [])
                      if k in PRESERVED_KEYS else [])
                 for k in REL_KEYS} for did, d in docs.items()}

    # 1) citation-derived implements edges (rules/policies/procedures/manuals/standards).
    # A repealed rule implements nothing currently in force, so it must not contribute
    # implements edges — otherwise a stale "implemented_by" survives on the target
    # statute even after the rule itself is correctly marked status: repealed.
    suspended = suspended_rule_ids()
    for did, d in docs.items():
        if d["fm"]["doc_type"] in LINK_DOC_TYPES:
            if not contributes_implements_edges(
                    d["fm"]["doc_type"], d["fm"].get("status", "current"), did, suspended):
                continue
            targets = resolve_citations(
                d["auth"], docs, rule_map, div_map, rules_by_div, did, ors_renumber_map)
            rel[did]["implements"].extend(sorted(targets))
            if d["fm"]["doc_type"] in ("policy", "procedure"):
                rel[did]["related"].extend(sorted(policy_xrefs(d["auth"], docs, did)))

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
              "status": d["fm"].get("status", ""),
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
    if "--selftest" in sys.argv:
        # THE PROOF #242 ASKED FOR. Before this change nothing failed if a suspension and a
        # repeal produced identical graphs. Each case runs BOTH rules over the same fixtures
        # and requires the old one to collapse them and the new one not to.
        # LEGAL STATUS - NOT-A-RULE: chapter 9-999 does not exist in the OAR. These are
        # synthetic fixtures for the proof below and assert nothing about Oregon law;
        # the real suspended set comes from the catalog, checked as case 4.
        docs = {"oar-9-999-0001": "superseded",   # stands in for a suspended rule
                "oar-9-999-0002": "repealed"}     # and for a repealed one
        susp = {"oar-9-999-0001"}

        keep = lambda d, st, susp: contributes_implements_edges("rule", st, d, susp)

        fails = []

        # 1. THE OLD RULE, watched collapsing them. If this ever stops being true the
        #    fixture has drifted and every claim below is about nothing.
        old_kept = [d for d, st in docs.items() if not (st != "current")]
        if old_kept:
            fails.append(f"FAIL the-old-rule-collapsed-suspension-into-repeal: it kept "
                         f"{old_kept}, so the defect this proves is not reproduced and the "
                         f"case below proves nothing")

        # 2. THE NEW RULE, keeping exactly the suspended one.
        new_kept = sorted(d for d, st in docs.items() if keep(d, st, susp))
        if new_kept != ["oar-9-999-0001"]:
            fails.append(f"FAIL a-suspended-rule-keeps-its-edge: kept {new_kept}, wanted "
                         f"only the suspended one — a suspension is dated and returns to "
                         f"force, a repeal does not")

        # 3. AND A REPEAL STILL LOSES IT. Keeping both would 'fix' #242 by deleting the
        #    original reason the test existed.
        if keep("oar-9-999-0002", "repealed", susp):
            fails.append("FAIL a-repealed-rule-still-loses-its-edge: a repealed rule "
                         "implements nothing in force, which is why the drop exists at all")

        # 4. AND THE CATALOG MUST REALLY SUPPLY THE SET, or all of the above is synthetic.
        live = suspended_rule_ids()
        if not live:
            fails.append("FAIL the-catalog-supplies-the-suspended-set: none found, so the "
                         "rule cannot fire on real data")

        for f in fails:
            print(f)
        if fails:
            print(f"{len(fails)} rule(s) did not hold")
            sys.exit(1)
        print(f"3 rule(s) held, each watched against the collapse it forbids; "
              f"{len(live)} suspended rule(s) keep their authority edges on real data")
        return

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
