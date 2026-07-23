#!/usr/bin/env python3
"""Policy-documentation gap — which agencies write the most binding OAR rules while having
the fewest of their own policy/procedure documents ingested into this corpus. Rule counts
are rolled up from agency sub-divisions to their root agency (agencies.yml parent_slug) so
e.g. OHA's public-health division rules are compared against OHA's own policies, not treated
as a separate zero-policy agency.

A zero here means zero policy/procedure documents have been INGESTED for that agency —
policy ingestion is scoped and incomplete (see BACKLOG.md "Agency-policy coverage"). It is
never evidence that an agency has no internal policies; every piece of copy in this viz says
so explicitly.

  python3 src/build_policy_gap.py            # -> viz/policy-documentation-gap.html
  python3 src/build_policy_gap.py --check    # exit 1 if stale (CI)

Self-contained (data inlined, no external assets).
"""
import json
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from enrich_oar import load_registry_by_chapter
from repo_lib import REPO_ROOT

GRAPH = REPO_ROOT / "_meta/graph.json"
PAGES = REPO_ROOT / "_meta/catalog/agency-policy-pages.yml"  # advisory only, never authoritative
OUT = REPO_ROOT / "viz/policy-documentation-gap.html"


def root(slug, orgs):
    """Roll a sub-division slug up to its top-level agency via parent_slug (loop-safe)."""
    seen = set()
    while slug in orgs and orgs[slug].get("parent_slug") and orgs[slug]["parent_slug"] not in seen:
        seen.add(slug)
        slug = orgs[slug]["parent_slug"]
    return slug


def build_data() -> dict:
    g = json.loads(GRAPH.read_text())
    reg = load_registry_by_chapter()
    orgs = {o["slug"]: o for o in
            yaml.safe_load((REPO_ROOT / "_meta/catalog/agencies.yml").read_text())["organizations"]}

    def org_name(slug):
        return orgs.get(slug, {}).get("name", slug)

    rules, policies = Counter(), Counter()
    for n in g["nodes"]:
        dt, nid, path = n["doc_type"], n["id"], n["path"]
        if dt == "rule":
            org = reg.get(nid.split("-")[1])
            if org:
                rules[root(org["slug"], orgs)] += 1
        elif dt in ("policy", "procedure"):
            policies[root(Path(path).parts[1], orgs)] += 1

    candidates = set()
    pages = yaml.safe_load(PAGES.read_text())
    for a in pages.get("agencies", []):
        if a.get("status") == "candidate_found":
            candidates.add(root(a["slug"], orgs))

    rows = [{"slug": slug, "name": org_name(slug), "rules": n,
             "policies": policies.get(slug, 0), "candidate": slug in candidates}
            for slug, n in rules.most_common()]

    n_with_policies = sum(1 for r in rows if r["policies"] > 0)
    return {
        "rows": rows,
        "max_rules": rows[0]["rules"] if rows else 1,
        "n_agencies": len(rows),
        "n_with_policies": n_with_policies,
        "n_zero": len(rows) - n_with_policies,
        "note": "Rule and policy counts from _meta/graph.json, rolled up from agency "
                "sub-divisions to their root agency (_meta/catalog/agencies.yml "
                "parent_slug). ‘Policy documents’ = policy/procedure doc types only "
                "(standards & manuals excluded). A zero here means zero policy/procedure "
                "documents have been ingested for that agency to date — policy "
                "ingestion is scoped and incomplete (see BACKLOG.md ‘Agency-policy "
                "coverage’); it is never evidence that an agency has no internal "
                "policies. Non-authoritative.",
    }


def build_html(data: dict) -> str:
    return TEMPLATE.replace("/*DATA*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def outputs():
    return {OUT: build_html(build_data())}


def main():
    outs = outputs()
    if "--check" in sys.argv:
        stale = [p for p, t in outs.items() if not p.exists() or p.read_text() != t]
        if stale:
            print(f"{OUT.relative_to(REPO_ROOT)} is stale — run: python3 src/build_policy_gap.py")
            sys.exit(1)
        print("policy-documentation-gap.html is current.")
        return
    for p, t in outs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    d = build_data()
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {d['n_agencies']} agencies, "
          f"{d['n_with_policies']} with policies ingested, {d['n_zero']} with none")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Oregon corpus — policy-documentation gap</title>
<style>
  :root{--bg:#f6f7f9;--panel:#fff;--ink:#161a20;--muted:#5a6472;--line:#e4e8ee;--bar:#2f6df6;--bar2:#8bb4ff;--pol:#e8590c;--zero:#c2255c;--shadow:0 1px 3px rgba(20,25,40,.09)}
  @media (prefers-color-scheme:dark){:root{--bg:#0e1116;--panel:#161b22;--ink:#e8ecf2;--muted:#9aa4b2;--line:#232a33;--bar:#5a9bff;--bar2:#2b4c86;--pol:#f08a4b;--zero:#e0578a;--shadow:0 1px 3px rgba(0,0,0,.5)}}
  :root[data-theme=light]{--bg:#f6f7f9;--panel:#fff;--ink:#161a20;--muted:#5a6472;--line:#e4e8ee;--bar:#2f6df6;--bar2:#8bb4ff;--pol:#e8590c;--zero:#c2255c}
  :root[data-theme=dark]{--bg:#0e1116;--panel:#161b22;--ink:#e8ecf2;--muted:#9aa4b2;--line:#232a33;--bar:#5a9bff;--bar2:#2b4c86;--pol:#f08a4b;--zero:#e0578a}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  .wrap{max-width:920px;margin:0 auto;padding:22px 20px 60px}
  h1{margin:0 0 4px;font-size:22px;letter-spacing:-.01em}
  .sub{color:var(--muted);font-size:13.5px;margin-bottom:16px}
  .controls{display:flex;gap:10px;align-items:center;margin-bottom:14px;flex-wrap:wrap}
  input[type=search]{padding:8px 11px;border:1px solid var(--line);border-radius:9px;background:var(--panel);color:var(--ink);font-size:14px;min-width:220px}
  .row{display:grid;grid-template-columns:190px 1fr 92px;gap:12px;align-items:center;padding:5px 0;border-bottom:1px solid var(--line)}
  .ag{font-weight:650}.ag small{display:block;font-weight:400;color:var(--muted);font-size:11.5px;margin-top:1px}
  .barwrap{position:relative;height:22px;background:var(--line);border-radius:5px;overflow:hidden}
  .bar{position:absolute;inset:0 auto 0 0;height:100%;background:var(--bar);border-radius:5px}
  .pol{position:absolute;inset:0 auto 0 0;height:100%;background:var(--pol);border-radius:5px 0 0 5px}
  .cnt{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
  .cnt small{display:block;font-weight:400;color:var(--muted);font-size:11px}
  .badge{display:inline-block;padding:2px 7px;border-radius:99px;background:color-mix(in srgb, var(--zero) 16%, transparent);color:var(--zero);font-size:11px;font-weight:650;white-space:nowrap}
  #tip{position:fixed;pointer-events:none;background:var(--panel);border:1px solid var(--line);border-radius:9px;box-shadow:0 8px 30px rgba(0,0,0,.2);padding:9px 12px;font-size:12.5px;opacity:0;transition:opacity .08s;z-index:9;max-width:300px}
  #tip b{font-size:13px}#tip div{color:var(--muted);margin-top:3px}
  #theme{position:fixed;top:14px;right:16px;width:34px;height:34px;border-radius:9px;border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer;box-shadow:var(--shadow);font-size:15px}
  footer{color:var(--muted);font-size:12px;margin-top:18px}
</style></head>
<body>
<button id="theme" title="Toggle theme">◑</button>
<div class="wrap">
  <h1>What the corpus documents about agency policy — and what it doesn't yet</h1>
  <div class="sub" id="sub"></div>
  <div class="controls">
    <input type="search" id="q" placeholder="Filter by agency…">
  </div>
  <div id="list"></div>
  <footer id="foot"></footer>
</div>
<div id="tip"></div>
<script>
const DATA=/*DATA*/;
const tip=document.getElementById('tip');
document.getElementById('sub').textContent=`${DATA.n_agencies} rule-writing agencies · ${DATA.n_with_policies} with policy documents ingested · ${DATA.n_zero} with none ingested yet — non-authoritative, see footer`;
document.getElementById('foot').textContent=DATA.note;
const list=document.getElementById('list');
function render(){
  const q=document.getElementById('q').value.toLowerCase().trim();
  list.innerHTML='';
  let shown=0;
  for(const r of DATA.rows){
    if(q && !r.name.toLowerCase().includes(q)) continue;
    shown++;
    const el=document.createElement('div');el.className='row';
    const barPct=Math.max(r.rules/DATA.max_rules*100,0.6);
    const polPct=r.rules?r.policies/r.rules*100:0;
    const rightCol=r.policies>0
      ? `${r.policies.toLocaleString()}<small>policy docs</small>`
      : `<span class="badge">0 ingested</span>`;
    el.innerHTML=`<div class="ag">${esc(r.name)}<small>${r.rules.toLocaleString()} OAR rules</small></div>
      <div class="barwrap"><div class="bar" style="width:${barPct}%"><div class="pol" style="width:${polPct}%"></div></div></div>
      <div class="cnt">${rightCol}</div>`;
    el.addEventListener('mousemove',e=>{
      const pct=r.rules?(r.policies/r.rules*100).toFixed(1):'0';
      const body=r.policies>0
        ? `<div>${r.rules.toLocaleString()} OAR rules · ${r.policies.toLocaleString()} policy/procedure documents ingested (≈${pct}% of rule volume)</div>`
        : `<div><b>0 policy/procedure documents ingested into this corpus.</b> This reflects ingestion scope, not confirmed absence of internal policy.</div>`;
      const cand=r.candidate?`<div>Flagged in the unverified review queue as a candidate for future ingestion.</div>`:'';
      tip.innerHTML=`<b>${esc(r.name)}</b>${body}${cand}`;
      tip.style.opacity=1;tip.style.left=Math.min(e.clientX+13,innerWidth-tip.offsetWidth-8)+'px';tip.style.top=Math.min(e.clientY+13,innerHeight-tip.offsetHeight-8)+'px';});
    el.addEventListener('mouseleave',()=>tip.style.opacity=0);
    list.appendChild(el);
  }
  if(!shown)list.innerHTML='<p style="color:var(--muted)">No agencies match.</p>';
}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
document.getElementById('q').addEventListener('input',render);
document.getElementById('theme').onclick=()=>{const c=document.documentElement.getAttribute('data-theme');
  document.documentElement.setAttribute('data-theme',c==='dark'?'light':c==='light'?'dark':(matchMedia('(prefers-color-scheme:dark)').matches?'light':'dark'));};
render();
</script></body></html>
"""


if __name__ == "__main__":
    main()
