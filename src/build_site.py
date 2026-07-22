#!/usr/bin/env python3
"""Build the static GitHub Pages site into ./site/ (gitignored; produced at deploy time).

A curated, human-facing landing page for the corpus — NOT a render of all 68k documents
(the repo, the MCP server, and llms.txt already serve the full text). It shows live corpus
stats (from _meta/graph.json) and links to: the interactive agency graph, llms.txt, the MCP
server, and the GitHub repo. The self-contained agency-graph viz and llms.txt are copied in
alongside it.

  python3 src/build_site.py        # writes ./site/{index.html, agency-authority-graph.html, llms.txt}

Wired into .github/workflows/pages.yml, which runs this and deploys ./site/ on push to main.
"""
import json
import shutil
from collections import Counter
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
REPO_URL = "https://github.com/morficflux/oregon-policy-repo"
MCP_URL = "https://mcp.morficflux.com/mcp"


def stats() -> dict:
    g = json.loads((REPO / "_meta/graph.json").read_text())
    by = Counter(n["doc_type"] for n in g["nodes"])
    agencies = sorted(p.parent.parent.name
                      for p in (REPO / "agencies").glob("*/policies")
                      if any(p.glob("*.md")))
    # non-doc files (_index/CHANGELOG) inflate a raw glob; count doc_type nodes instead
    return {
        "statutes": by.get("statute", 0),
        "rules": by.get("rule", 0),
        "orders": by.get("executive_order", 0),
        "policies": by.get("policy", 0) + by.get("procedure", 0),
        "standards": by.get("standard", 0) + by.get("manual", 0),
        "documents": len(g["nodes"]),
        "edges": len(g["edges"]),
        "agencies": len(agencies),
    }


def commas(n: int) -> str:
    return f"{n:,}"


def build_html() -> str:
    s = stats()
    today = date.today().isoformat()
    tiles = [
        ("ORS statutes", s["statutes"], "verbatim sections of Oregon Revised Statutes"),
        ("OAR rules", s["rules"], "administrative rules across every agency chapter"),
        ("Executive orders", s["orders"], "gubernatorial orders, 2003–present"),
        ("Agency policies", s["policies"], "internal policies & procedures"),
        ("Standards & manuals", s["standards"], "EIS/CSS standards + Oregon Accounting Manual"),
        ("Authority edges", s["edges"], "mechanically-derived statute→rule→policy links"),
    ]
    tile_html = "\n".join(
        f'''<div class="tile"><div class="num">{commas(v)}</div>
        <div class="lbl">{name}</div><div class="sub">{sub}</div></div>'''
        for name, v, sub in tiles)
    return TEMPLATE.format(
        tiles=tile_html, docs=commas(s["documents"]), agencies=s["agencies"],
        repo=REPO_URL, mcp=MCP_URL, today=today)


def main():
    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(build_html(), encoding="utf-8")
    for src, dst in [("viz/agency-authority-graph.html", "agency-authority-graph.html"),
                     ("llms.txt", "llms.txt")]:
        p = REPO / src
        if p.exists():
            shutil.copyfile(p, SITE / dst)
    print(f"built site/ ({stats()['documents']:,} documents) -> {SITE.relative_to(REPO)}")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Oregon Executive-Branch Law &amp; Policy — an AI-agent-friendly corpus</title>
<meta name="description" content="A non-authoritative, machine-readable knowledge base of Oregon executive-branch statutes, rules, executive orders, and agency policies — with a mechanically-derived authority graph.">
<style>
  :root{{
    --bg:#f6f7f9; --panel:#ffffff; --ink:#161a20; --muted:#5a6472; --line:#e4e8ee;
    --accent:#1f6feb; --accent-ink:#0b4bc0; --gold:#8a6d1f; --shadow:0 1px 2px rgba(20,25,40,.06),0 8px 30px rgba(20,25,40,.07);
  }}
  @media (prefers-color-scheme:dark){{
    :root{{--bg:#0e1116; --panel:#161b22; --ink:#e8ecf2; --muted:#9aa4b2; --line:#232a33;
      --accent:#5a9bff; --accent-ink:#8fbaff; --gold:#d9b45a; --shadow:0 1px 2px rgba(0,0,0,.4),0 10px 34px rgba(0,0,0,.45);}}
  }}
  :root[data-theme="light"]{{--bg:#f6f7f9;--panel:#fff;--ink:#161a20;--muted:#5a6472;--line:#e4e8ee;--accent:#1f6feb;--accent-ink:#0b4bc0;--gold:#8a6d1f;}}
  :root[data-theme="dark"]{{--bg:#0e1116;--panel:#161b22;--ink:#e8ecf2;--muted:#9aa4b2;--line:#232a33;--accent:#5a9bff;--accent-ink:#8fbaff;--gold:#d9b45a;}}
  *{{box-sizing:border-box}}
  html{{-webkit-text-size-adjust:100%}}
  body{{margin:0;background:var(--bg);color:var(--ink);
    font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    -webkit-font-smoothing:antialiased}}
  a{{color:var(--accent-ink);text-decoration:none}} a:hover{{text-decoration:underline}}
  .wrap{{max-width:960px;margin:0 auto;padding:0 22px}}
  .disc{{background:var(--gold);color:#1a1400;font-size:13px;text-align:center;padding:7px 14px;font-weight:600;letter-spacing:.01em}}
  @media (prefers-color-scheme:dark){{.disc{{color:#1a1400}}}}
  header{{padding:64px 0 26px;border-bottom:1px solid var(--line)}}
  .eyebrow{{text-transform:uppercase;letter-spacing:.14em;font-size:12px;color:var(--muted);font-weight:700;margin-bottom:14px}}
  h1{{font-size:clamp(30px,5vw,46px);line-height:1.08;margin:0 0 16px;letter-spacing:-.02em;text-wrap:balance;font-weight:800}}
  .lede{{font-size:19px;color:var(--muted);max-width:64ch;margin:0}}
  .cta{{display:flex;flex-wrap:wrap;gap:12px;margin-top:26px}}
  .btn{{display:inline-flex;align-items:center;gap:8px;padding:11px 18px;border-radius:10px;font-weight:650;font-size:15px;border:1px solid var(--line);background:var(--panel);color:var(--ink);box-shadow:var(--shadow)}}
  .btn.primary{{background:var(--accent);color:#fff;border-color:transparent}}
  .btn:hover{{text-decoration:none;transform:translateY(-1px)}}
  section{{padding:44px 0}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}}
  .tile{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px 20px 18px;box-shadow:var(--shadow)}}
  .tile .num{{font-size:32px;font-weight:800;letter-spacing:-.02em;font-variant-numeric:tabular-nums}}
  .tile .lbl{{font-weight:650;margin-top:2px}}
  .tile .sub{{color:var(--muted);font-size:13.5px;margin-top:5px;line-height:1.45}}
  h2{{font-size:14px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin:0 0 18px;font-weight:700}}
  .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}}
  .card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px;box-shadow:var(--shadow);display:flex;flex-direction:column}}
  .card h3{{margin:0 0 8px;font-size:18px;letter-spacing:-.01em}}
  .card p{{margin:0 0 16px;color:var(--muted);font-size:14.5px;flex:1}}
  .card .go{{font-weight:650;font-size:14.5px}}
  code{{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:1px 6px;font-size:13px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}
  footer{{border-top:1px solid var(--line);padding:30px 0 60px;color:var(--muted);font-size:13.5px}}
  footer p{{margin:6px 0}}
  #theme{{position:fixed;top:14px;right:14px;width:36px;height:36px;border-radius:10px;border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer;box-shadow:var(--shadow);font-size:16px;z-index:5}}
</style>
</head>
<body>
<button id="theme" title="Toggle light/dark" aria-label="Toggle theme">◑</button>
<div class="disc">NON-AUTHORITATIVE reference — not the official text of Oregon law. Always verify against each document's cited source.</div>
<div class="wrap">
  <header>
    <div class="eyebrow">Oregon executive branch · statutes · rules · policies</div>
    <h1>A machine-readable knowledge base of Oregon law &amp; policy</h1>
    <p class="lede">Every ORS statute, OAR rule, executive order, and agency policy in scope — carried as
      complete verbatim text with a mechanically-derived authority graph linking each rule and policy
      up to the statute that authorizes it. Built for AI agents and humans alike.</p>
    <div class="cta">
      <a class="btn primary" href="agency-authority-graph.html">◑ Explore the agency graph</a>
      <a class="btn" href="{repo}">View on GitHub</a>
      <a class="btn" href="llms.txt">llms.txt (AI index)</a>
    </div>
  </header>

  <section>
    <div class="grid">
      {tiles}
    </div>
  </section>

  <section>
    <h2>Three ways in</h2>
    <div class="cards">
      <div class="card">
        <h3>The agency graph</h3>
        <p>An interactive map of which Oregon agencies share statutory turf — agencies linked by the ORS
          chapters their rules jointly implement. Click a node to trace its neighborhood.</p>
        <a class="go" href="agency-authority-graph.html">Open the visualization →</a>
      </div>
      <div class="card">
        <h3>For AI agents (MCP)</h3>
        <p>A live Model Context Protocol server exposes full-text search, citation resolution, document
          retrieval, and authority-chain traversal over the whole corpus.</p>
        <a class="go" href="{mcp}"><code>{mcp}</code> →</a>
      </div>
      <div class="card">
        <h3>The source</h3>
        <p>Every document is a Markdown file with provenance frontmatter, verified line-by-line against a
          pinned source snapshot. Read it, fork it, or run the pipeline yourself.</p>
        <a class="go" href="{repo}">Browse the repository →</a>
      </div>
    </div>
  </section>

  <footer>
    <p><strong>{docs} documents</strong> across {agencies} content-bearing agencies · generated {today}.</p>
    <p>Non-authoritative curated copies for reference and AI use. The official text is the published
      source cited in each document. See the repository's disclaimer and <code>AGENTS.md</code> for the
      full-text-first, anti-fabrication content policy.</p>
    <p>Not affiliated with the State of Oregon.</p>
  </footer>
</div>
<script>
  document.getElementById('theme').onclick=function(){{
    var c=document.documentElement.getAttribute('data-theme');
    var n=c==='dark'?'light':c==='light'?'dark':(matchMedia('(prefers-color-scheme:dark)').matches?'light':'dark');
    document.documentElement.setAttribute('data-theme',n);
  }};
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
