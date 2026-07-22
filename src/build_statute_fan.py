#!/usr/bin/env python3
"""Statute-operationalization view — which ORS chapters are most heavily turned into
administrative rules. For every ORS chapter, counts the OAR rules that implement it
(across all agencies) and breaks that down by implementing agency. Ranked bars reveal the
most-operationalized statutes at the top and the long dormant tail below.

  python3 src/build_statute_fan.py            # -> viz/statute-operationalization.html
  python3 src/build_statute_fan.py --check    # exit 1 if stale (CI)
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from enrich_oar import load_registry_by_chapter
from repo_lib import REPO_ROOT

GRAPH = REPO_ROOT / "_meta/graph.json"
OUT = REPO_ROOT / "viz/statute-operationalization.html"


def build_data() -> dict:
    g = json.loads(GRAPH.read_text())
    reg = load_registry_by_chapter()
    orgs = {o["slug"]: o.get("name", o["slug"]) for o in
            yaml.safe_load((REPO_ROOT / "_meta/catalog/agencies.yml").read_text())["organizations"]}
    ors_cat = yaml.safe_load((REPO_ROOT / "_meta/catalog/ors.yml").read_text())
    ch_title = {c["chapter"].lower(): c.get("title", "") for c in ors_cat["chapters"]}

    total = Counter()                              # ORS chapter -> # implementing rules
    by_agency = defaultdict(Counter)               # ORS chapter -> {agency name -> count}
    for e in g["edges"]:
        if e["type"] != "implemented_by" or not e["from"].startswith("ors-") \
                or not e["to"].startswith("oar-"):
            continue
        ch = e["from"].split("-")[1].split(".")[0]
        org = reg.get(e["to"].split("-")[1])
        ag = orgs.get(org["slug"], org["slug"]) if org else "(unassigned)"
        total[ch] += 1
        by_agency[ch][ag] += 1

    rows = []
    for ch, n in total.most_common():
        top = [{"a": a.replace("Department of ", "Dept. of "), "n": c}
               for a, c in by_agency[ch].most_common(4)]
        rows.append({"ch": ch.upper(), "title": ch_title.get(ch, ""), "n": n,
                     "agencies": len(by_agency[ch]), "top": top})
    return {"rows": rows, "max": rows[0]["n"] if rows else 1,
            "chapters": len(rows), "total_links": sum(total.values()),
            "note": "Counts of OAR rules implementing each ORS chapter, from the "
                    "mechanically-derived authority graph. Non-authoritative."}


def build_html(data: dict) -> str:
    return TEMPLATE.replace("/*DATA*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def outputs():
    return {OUT: build_html(build_data())}


def main():
    outs = outputs()
    if "--check" in sys.argv:
        stale = [p for p, t in outs.items() if not p.exists() or p.read_text() != t]
        if stale:
            print(f"{OUT.relative_to(REPO_ROOT)} is stale — run: python3 src/build_statute_fan.py")
            sys.exit(1)
        print("statute-operationalization.html is current.")
        return
    for p, t in outs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    d = build_data()
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {d['chapters']} ORS chapters, "
          f"{d['total_links']:,} statute→rule links")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Oregon statutes — operationalization</title>
<style>
  :root{--bg:#f6f7f9;--panel:#fff;--ink:#161a20;--muted:#5a6472;--line:#e4e8ee;--bar:#2f6df6;--bar2:#8bb4ff;--shadow:0 1px 3px rgba(20,25,40,.09)}
  @media (prefers-color-scheme:dark){:root{--bg:#0e1116;--panel:#161b22;--ink:#e8ecf2;--muted:#9aa4b2;--line:#232a33;--bar:#5a9bff;--bar2:#2b4c86;--shadow:0 1px 3px rgba(0,0,0,.5)}}
  :root[data-theme=light]{--bg:#f6f7f9;--panel:#fff;--ink:#161a20;--muted:#5a6472;--line:#e4e8ee;--bar:#2f6df6;--bar2:#8bb4ff}
  :root[data-theme=dark]{--bg:#0e1116;--panel:#161b22;--ink:#e8ecf2;--muted:#9aa4b2;--line:#232a33;--bar:#5a9bff;--bar2:#2b4c86}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  .wrap{max-width:920px;margin:0 auto;padding:22px 20px 60px}
  h1{margin:0 0 4px;font-size:22px;letter-spacing:-.01em}
  .sub{color:var(--muted);font-size:13.5px;margin-bottom:16px}
  .controls{display:flex;gap:10px;align-items:center;margin-bottom:14px;flex-wrap:wrap}
  input[type=search]{padding:8px 11px;border:1px solid var(--line);border-radius:9px;background:var(--panel);color:var(--ink);font-size:14px;min-width:220px}
  .toggle{font-size:13px;color:var(--muted);cursor:pointer;user-select:none;display:flex;align-items:center;gap:6px}
  .row{display:grid;grid-template-columns:118px 1fr 66px;gap:12px;align-items:center;padding:5px 0;border-bottom:1px solid var(--line)}
  .ch{font-weight:650;font-variant-numeric:tabular-nums}.ch small{display:block;font-weight:400;color:var(--muted);font-size:11.5px;line-height:1.25;margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .barwrap{position:relative;height:22px;background:var(--line);border-radius:5px;overflow:hidden}
  .bar{position:absolute;inset:0 auto 0 0;display:flex}
  .seg{height:100%}
  .cnt{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
  .cnt small{display:block;font-weight:400;color:var(--muted);font-size:11px}
  #tip{position:fixed;pointer-events:none;background:var(--panel);border:1px solid var(--line);border-radius:9px;box-shadow:0 8px 30px rgba(0,0,0,.2);padding:9px 12px;font-size:12.5px;opacity:0;transition:opacity .08s;z-index:9;max-width:280px}
  #tip b{font-size:13px}#tip div{color:var(--muted);margin-top:3px}
  #theme{position:fixed;top:14px;right:16px;width:34px;height:34px;border-radius:9px;border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer;box-shadow:var(--shadow);font-size:15px}
  footer{color:var(--muted);font-size:12px;margin-top:18px}
</style></head>
<body>
<button id="theme" title="Toggle theme">◑</button>
<div class="wrap">
  <h1>Which Oregon statutes get operationalized</h1>
  <div class="sub" id="sub"></div>
  <div class="controls">
    <input type="search" id="q" placeholder="Filter by ORS chapter or title…">
    <label class="toggle"><input type="checkbox" id="tail"> show the dormant tail (1–2 rules)</label>
  </div>
  <div id="list"></div>
  <footer id="foot"></footer>
</div>
<div id="tip"></div>
<script>
const DATA=/*DATA*/;
const PAL=['#2f6df6','#e8590c','#2f9e44','#ae3ec9','#0c8599','#c2255c'];
const tip=document.getElementById('tip');
document.getElementById('sub').textContent=`${DATA.chapters} ORS chapters implemented by ${DATA.total_links.toLocaleString()} OAR rules · bar length = rules implementing the chapter, segmented by agency · non-authoritative`;
document.getElementById('foot').textContent=DATA.note;
const list=document.getElementById('list');
function render(){
  const q=document.getElementById('q').value.toLowerCase().trim();
  const tail=document.getElementById('tail').checked;
  list.innerHTML='';
  let shown=0;
  for(const r of DATA.rows){
    if(!tail && r.n<3) continue;
    if(q && !((`ors ${r.ch}`).toLowerCase().includes(q) || r.title.toLowerCase().includes(q))) continue;
    shown++;
    const el=document.createElement('div');el.className='row';
    const segs=r.top.map((t,i)=>`<div class="seg" style="width:${t.n/r.n*100}%;background:${PAL[i%PAL.length]}" data-a="${esc(t.a)}" data-n="${t.n}"></div>`).join('');
    el.innerHTML=`<div class="ch">ORS ${r.ch}<small>${esc(r.title)}</small></div>
      <div class="barwrap"><div class="bar" style="width:${Math.max(r.n/DATA.max*100,0.6)}%">${segs}</div></div>
      <div class="cnt">${r.n.toLocaleString()}<small>${r.agencies} ${r.agencies===1?'agency':'agencies'}</small></div>`;
    el.querySelector('.bar').addEventListener('mousemove',e=>{
      const parts=r.top.map((t,i)=>`<div><span style="color:${PAL[i%PAL.length]}">■</span> ${esc(t.a)} — ${t.n}</div>`).join('');
      const more=r.agencies>r.top.length?`<div>+${r.agencies-r.top.length} more agencies</div>`:'';
      tip.innerHTML=`<b>ORS ${r.ch}${r.title?' · '+esc(r.title):''}</b><div>${r.n.toLocaleString()} implementing rules</div>${parts}${more}`;
      tip.style.opacity=1;tip.style.left=Math.min(e.clientX+13,innerWidth-tip.offsetWidth-8)+'px';tip.style.top=Math.min(e.clientY+13,innerHeight-tip.offsetHeight-8)+'px';});
    el.querySelector('.bar').addEventListener('mouseleave',()=>tip.style.opacity=0);
    list.appendChild(el);
  }
  if(!shown)list.innerHTML='<p style="color:var(--muted)">No chapters match.</p>';
}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
document.getElementById('q').addEventListener('input',render);
document.getElementById('tail').addEventListener('change',render);
document.getElementById('theme').onclick=()=>{const c=document.documentElement.getAttribute('data-theme');
  document.documentElement.setAttribute('data-theme',c==='dark'?'light':c==='light'?'dark':(matchMedia('(prefers-color-scheme:dark)').matches?'light':'dark'));};
render();
</script></body></html>
"""


if __name__ == "__main__":
    main()
