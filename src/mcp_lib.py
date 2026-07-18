#!/usr/bin/env python3
"""Query engine behind the MCP server — pure stdlib + repo_lib, NO `mcp` dependency,
so CI can smoke-test it (`python3 src/mcp_lib.py --selftest`) without installing the SDK.

Layers:
  - FTS5 full-text index over all content files, cached at _meta/.cache/fts.db and
    keyed on the repo state (git HEAD + working-tree changes) — auto-rebuilds when
    the corpus changes, instant startup otherwise.
  - Graph queries over _meta/graph.json (authority chains, neighbors).
  - Citation resolution using the same patterns link_graph.py links with, including
    the OAR renumbering map (125-800-0020 -> 128-030-0020).

Every document payload carries the non-authoritative notice + source_url + retrieved,
straight from frontmatter — this server must never present content as official text."""
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

from link_graph import build_renumber_map
from repo_lib import REPO_ROOT, content_files, extract_fulltext, parse_frontmatter

CACHE_DIR = REPO_ROOT / "_meta/.cache"
DB_PATH = CACHE_DIR / "fts.db"
GRAPH_PATH = REPO_ROOT / "_meta/graph.json"
BIG_DOC_BYTES = 50_000

DISCLAIMER = ("NON-AUTHORITATIVE curated copy for AI-agent reference. Not the official "
              "text of Oregon law or policy — always cite and verify against source_url.")


# ---------- corpus state / index ----------

def repo_state() -> str:
    """Cheap fingerprint of the corpus: HEAD commit + hash of `git status` porcelain
    (captures uncommitted adds/edits well enough for a cache key)."""
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                          capture_output=True, text=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                            capture_output=True, text=True).stdout
    return head + ":" + hashlib.sha256(status.encode()).hexdigest()[:16]


def _extract_section(body: str, heading: str) -> str | None:
    m = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", body, re.M | re.S)
    return m.group(1).strip() if m else None


def ensure_index() -> sqlite3.Connection:
    CACHE_DIR.mkdir(exist_ok=True)
    state = repo_state()
    con = sqlite3.connect(DB_PATH)
    try:
        row = con.execute("SELECT v FROM meta WHERE k='state'").fetchone()
        if row and row[0] == state:
            return con
    except sqlite3.OperationalError:
        pass
    con.close()
    DB_PATH.unlink(missing_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    con.execute("""CREATE TABLE docs (
        id TEXT PRIMARY KEY, path TEXT, doc_type TEXT, agency TEXT, citation TEXT,
        title TEXT, status TEXT, source_url TEXT, retrieved TEXT, effective_date TEXT,
        content_mode TEXT, content_exception TEXT, size INTEGER)""")
    con.execute("""CREATE VIRTUAL TABLE fts USING fts5(
        id, citation, title, tags, glance, body, tokenize='porter unicode61')""")
    for p in content_files():
        fm, body = parse_frontmatter(p)
        glance = _extract_section(body, "At a glance") or ""
        ft = extract_fulltext(body) or _extract_section(body, "Key provisions") or ""
        con.execute("INSERT INTO docs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            fm["id"], str(p.relative_to(REPO_ROOT)), fm["doc_type"],
            fm.get("agency", ""), fm.get("citation", ""), fm["title"],
            fm.get("status", ""), fm.get("source_url", ""), str(fm.get("retrieved", "")),
            str(fm.get("effective_date") or ""), fm.get("content_mode", ""),
            fm.get("content_exception") or "", p.stat().st_size))
        con.execute("INSERT INTO fts VALUES (?,?,?,?,?,?)", (
            fm["id"], fm.get("citation", ""), fm["title"],
            " ".join(fm.get("tags") or []), glance, ft))
    con.execute("INSERT INTO meta VALUES ('state', ?)", (state,))
    con.commit()
    return con


def _load_graph():
    g = json.loads(GRAPH_PATH.read_text())
    nodes = {n["id"]: n for n in g["nodes"]}
    out = {}
    for e in g["edges"]:
        out.setdefault(e["from"], {}).setdefault(e["type"], []).append(e["to"])
    return nodes, out


_GRAPH = None


def graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = _load_graph()
    return _GRAPH


# ---------- tools ----------

def search_corpus(query: str, doc_type: str | None = None, agency: str | None = None,
                  limit: int = 10) -> list[dict]:
    con = ensure_index()
    # sanitize into quoted terms (implicit AND) so FTS5 syntax chars can't error
    terms = re.findall(r"[\w.\-]+", query)
    if not terms:
        return []
    match = " ".join(f'"{t}"' for t in terms)
    sql = ("SELECT f.id, snippet(fts, 5, '[', ']', ' … ', 24), d.title, d.citation, "
           "d.doc_type, d.agency, d.path, bm25(fts) FROM fts f "
           "JOIN docs d ON d.id = f.id WHERE fts MATCH ?")
    args = [match]
    if doc_type:
        sql += " AND d.doc_type = ?"
        args.append(doc_type)
    if agency:
        sql += " AND d.agency = ?"
        args.append(agency)
    sql += " ORDER BY bm25(fts) LIMIT ?"
    args.append(max(1, min(int(limit), 40)))
    rows = con.execute(sql, args).fetchall()
    return [{"id": r[0], "title": r[2], "citation": r[3], "doc_type": r[4],
             "agency": r[5], "path": r[6], "snippet": r[1][:400]} for r in rows]


def _doc_row(doc_id: str):
    con = ensure_index()
    r = con.execute("SELECT id, path, doc_type, citation, title, status, source_url, "
                    "retrieved, effective_date, content_mode, content_exception, size "
                    "FROM docs WHERE id = ?", (doc_id,)).fetchone()
    return r


def get_document(doc_id: str, part: str = "auto") -> dict:
    r = _doc_row(doc_id)
    if not r:
        sug = search_corpus(doc_id.replace("-", " "), limit=3)
        return {"error": f"no document with id {doc_id!r}",
                "did_you_mean": [{"id": s["id"], "title": s["title"]} for s in sug]}
    path = REPO_ROOT / r[1]
    fm, body = parse_frontmatter(path)
    meta = {"id": r[0], "title": r[4], "citation": r[3], "doc_type": r[2],
            "status": r[5], "source_url": r[6], "retrieved": r[7],
            "effective_date": r[8] or None, "content_mode": r[9], "path": r[1],
            "relationships": {k: v for k, v in (fm.get("relationships") or {}).items() if v},
            "disclaimer": DISCLAIMER}
    if r[10]:
        meta["content_exception"] = r[10]
    headings = re.findall(r"^## (.+)$", body, re.M)
    if part == "auto" and r[11] > BIG_DOC_BYTES:
        glance = _extract_section(body, "At a glance")
        return {**meta, "note": (f"document body is {r[11] // 1024} KB — pass "
                                 "part='full text' (or another heading below) to page in "
                                 "the content you need"),
                "at_a_glance": glance, "sections": headings}
    if part in ("auto", "full"):
        return {**meta, "body": body}
    sec = _extract_section(body, part) or next(
        (_extract_section(body, h) for h in headings if h.lower() == part.lower()), None)
    if sec is None:
        return {**meta, "error": f"no section {part!r}", "sections": headings}
    return {**meta, "section": part, "body": sec}


ORS_C = re.compile(r"(?:ORS\s*)?(\d{2,3}[A-Za-z]?\.\d{3})\s*$", re.I)
OAR_RULE_C = re.compile(r"(?:OAR\s*)?(\d{3}-\d{3}-\d{4})\s*$", re.I)
OAR_DIV_C = re.compile(r"(?:OAR\s*)?(\d{3}-\d{3})\s*$", re.I)
EO_C = re.compile(r"(?:EO|Executive\s+Order)\s*(?:No\.?\s*)?(?:20)?(\d{2})-(\d{1,2})\s*$", re.I)
NUMS_C = re.compile(r"(?:DAS|policy|statewide policy|OAM)?\s*([\d]{2,3}[.\-][\d]{3}[.\-][\d]{2,4})\s*$", re.I)

_RENUM = None


def _renumber(rule):
    global _RENUM
    if _RENUM is None:
        _RENUM = build_renumber_map()[0]
    return _RENUM.get(rule, rule)


def resolve_citation(citation: str) -> dict:
    """Map a legal citation string to in-repo document id(s)."""
    nodes, _ = graph()
    c = citation.strip()
    cands, note = [], None
    if m := ORS_C.search(c):
        cands = [f"ors-{m.group(1).lower()}"]
    elif m := OAR_RULE_C.search(c):
        served = _renumber(m.group(1))
        cands = [f"oar-{served}"]
        if served != m.group(1):
            note = f"OAR {m.group(1)} was renumbered; current rule is {served}"
    elif m := EO_C.search(c):
        cands = [f"eo-{m.group(1)}-{int(m.group(2)):02d}"]
    elif m := OAR_DIV_C.search(c):
        div = m.group(1)
        cands = sorted(i for i in nodes if i.startswith(f"oar-{div}-"))
    if not cands and (m := NUMS_C.search(c)):
        num = m.group(1).replace(".", "-")
        cands = sorted(i for i in nodes
                       if i in (f"das-{num}", f"oam-{num}", f"das-{num}_pr"))
    hits = [{"id": i, "title": nodes[i]["title"], "doc_type": nodes[i]["doc_type"]}
            for i in cands if i in nodes]
    out = {"citation": citation, "matches": hits}
    if note:
        out["note"] = note
    if not hits:
        out["note"] = ("no direct match — the document may not be ingested (see "
                       "corpus_overview) or the citation format wasn't recognized; "
                       "try search_corpus")
        out["search_fallback"] = [{"id": s["id"], "title": s["title"]}
                                  for s in search_corpus(c, limit=3)]
    return out


def authority_chain(doc_id: str, direction: str = "both", depth: int = 3) -> dict:
    """Walk implements (up, toward statute) / implemented_by (down) from a document."""
    nodes, edges = graph()
    if doc_id not in nodes:
        return {"error": f"no document with id {doc_id!r}"}
    depth = max(1, min(int(depth), 6))

    def walk(start, key):
        seen, levels, frontier = {start}, [], [start]
        for _ in range(depth):
            nxt = []
            for i in frontier:
                for t in edges.get(i, {}).get(key, []):
                    if t not in seen:
                        seen.add(t)
                        nxt.append({"id": t, "title": nodes[t]["title"],
                                    "doc_type": nodes[t]["doc_type"], "via": i})
            if not nxt:
                break
            levels.append(nxt)
            frontier = [n["id"] for n in nxt]
        return levels

    out = {"id": doc_id, "title": nodes[doc_id]["title"],
           "doc_type": nodes[doc_id]["doc_type"]}
    if direction in ("up", "both"):
        out["up_implements"] = walk(doc_id, "implements")
    if direction in ("down", "both"):
        out["down_implemented_by"] = walk(doc_id, "implemented_by")
    return out


def graph_neighbors(doc_id: str) -> dict:
    nodes, edges = graph()
    if doc_id not in nodes:
        return {"error": f"no document with id {doc_id!r}"}
    out = {"id": doc_id, "title": nodes[doc_id]["title"]}
    for k, targets in edges.get(doc_id, {}).items():
        out[k] = [{"id": t, "title": nodes[t]["title"], "doc_type": nodes[t]["doc_type"]}
                  for t in targets]
    return out


def corpus_overview() -> dict:
    con = ensure_index()
    by_type = dict(con.execute(
        "SELECT doc_type, COUNT(*) FROM docs GROUP BY doc_type ORDER BY 2 DESC"))
    exceptions = con.execute(
        "SELECT COUNT(*) FROM docs WHERE content_exception != ''").fetchone()[0]
    head = subprocess.run(["git", "log", "-1", "--format=%h %cs"], cwd=REPO_ROOT,
                          capture_output=True, text=True).stdout.strip()
    review = (REPO_ROOT / "REVIEW.md").read_text()
    review_sections = re.findall(r"^## (.+?) \((\d+)\)$", review, re.M)
    return {
        "disclaimer": DISCLAIMER,
        "repo": "github.com/morficflux/oregon-policy-repo",
        "commit": head,
        "documents_by_type": by_type,
        "graph_edges": sum(len(v) for d in graph()[1].values() for v in d.values()),
        "coverage_notes": [
            "Full verbatim text for nearly all state-authored docs (ORS chapters 183/184/"
            "192/240/276/276A/278/279A-C/282/283/291/292/293; OAR chapters 105/122/125/128; "
            "DAS policies+procedures; OAM; EIS standards).",
            f"{exceptions} documents are summary/metadata-only (content_exception — mostly "
            "executive orders whose sources are image-only scans; their titles, numbers, "
            "and source links are in-repo, the text is not).",
            "Third-party references (NIST etc.) are summary+link only, never full text.",
        ],
        "human_review_queue": {name: int(n) for name, n in review_sections},
    }


# ---------- selftest ----------

def selftest():
    fails = []

    def check(name, cond, detail=""):
        print(("PASS " if cond else "FAIL ") + name + (f" — {detail}" if detail and not cond else ""))
        if not cond:
            fails.append(name)

    r = search_corpus("removable storage devices", limit=5)
    check("search finds 107-004-051", any(x["id"] == "das-107-004-051" for x in r), str(r[:2]))

    r = resolve_citation("OAR 125-800-0020")
    check("renumbered citation resolves to 128-030-0020",
          any(m["id"] == "oar-128-030-0020" for m in r["matches"]), str(r))

    r = resolve_citation("ORS 276A.300")
    check("ORS citation resolves", any(m["id"] == "ors-276a.300" for m in r["matches"]), str(r))

    r = resolve_citation("EO 20-03")
    check("EO citation resolves", any(m["id"] == "eo-20-03" for m in r["matches"]), str(r))

    r = authority_chain("das-107-004-052", direction="up", depth=3)
    ups = [n["id"] for lvl in r.get("up_implements", []) for n in lvl]
    check("policy chains up to a statute or rule",
          any(i.startswith(("ors-", "oar-")) for i in ups), str(r)[:300])

    r = authority_chain("ors-276a.300", direction="down", depth=2)
    downs = [n["id"] for lvl in r.get("down_implemented_by", []) for n in lvl]
    check("ORS 276A.300 chains down", len(downs) > 0, str(r)[:300])

    r = get_document("eis-css-secplan")  # 195 KB — must NOT return the whole body
    check("big doc returns section list, not body",
          "sections" in r and "body" not in r, str(r)[:200])

    r = get_document("oar-128-030-0020")
    check("normal doc returns body with disclaimer",
          "body" in r and r["disclaimer"] == DISCLAIMER and "## Full text" in r["body"])

    r = get_document("eo-03-01")
    check("EO scan stub carries content_exception", bool(r.get("content_exception")))

    r = get_document("nonexistent-id-xyz")
    check("unknown id errors gracefully", "error" in r)

    r = corpus_overview()
    check("overview counts docs", sum(r["documents_by_type"].values()) > 2000, str(r)[:200])

    if fails:
        sys.exit(f"selftest FAILED: {fails}")
    print(f"selftest OK ({11} checks)")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--rebuild" in sys.argv:
        DB_PATH.unlink(missing_ok=True)
        ensure_index()
        print("index rebuilt")
    else:
        print(__doc__)
