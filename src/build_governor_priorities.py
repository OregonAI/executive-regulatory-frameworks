#!/usr/bin/env python3
"""Governor's-priorities visualization — does OAR rulemaking activity show elevated recent
attention in the chapters that plausibly implement each of 4 stated priority areas?

CURATED, not mechanically derived: the chapter-to-priority mapping lives in
_meta/catalog/governor-priorities.yml with its own reasoning per chapter — this generator
only renders the (real, mechanically-computed) rulemaking-recency data against that mapping.
The mapping itself is a judgment call, prominently labeled as such in the page.

Reads the cached dataset from build_governor_priorities_data.py.

  python3 src/build_governor_priorities.py          # -> viz/governor-priorities.html
  python3 src/build_governor_priorities.py --check   # exit 1 if stale (CI)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT

DATA = REPO_ROOT / "_meta/governor_priorities.json"
OUT = REPO_ROOT / "viz/governor-priorities.html"


def build_data() -> dict:
    return json.loads(DATA.read_text())


def build_html(data: dict) -> str:
    return TEMPLATE.replace("/*DATA*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def outputs():
    return {OUT: build_html(build_data())}


def main():
    if not DATA.exists():
        print("governor_priorities.json missing — run: python3 src/build_governor_priorities_data.py")
        sys.exit(1)
    outs = outputs()
    if "--check" in sys.argv:
        stale = [p for p, t in outs.items() if not p.exists() or p.read_text() != t]
        if stale:
            print(f"{OUT.relative_to(REPO_ROOT)} is stale — run: python3 src/build_governor_priorities.py")
            sys.exit(1)
        print("governor-priorities.html is current.")
        return
    for p, t in outs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    d = build_data()
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {len(d['areas'])} areas, "
          f"{d['mapped_rules']} mapped rules")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Oregon governor's priorities — rulemaking activity</title>
<style>
  :root{--bg:#f5f6f8;--panel:#fff;--ink:#151a21;--muted:#5c6672;--line:#e3e7ee;--grid:#eceff3;
    --up:#2f9e44;--down:#c92a2a;--accent:#2f6df6;--dim:#c3ccd8;--warn-bg:#fff4e0;--warn-ink:#7a4a00;
    --shadow:0 2px 10px rgba(20,25,40,.10)}
  @media (prefers-color-scheme:dark){:root{--bg:#0c0f14;--panel:#151b23;--ink:#e7ecf3;--muted:#98a2b0;--line:#232b35;--grid:#1a2028;
    --up:#4caf5f;--down:#ff6b6b;--accent:#5a9bff;--dim:#33404f;--warn-bg:#3a2c0d;--warn-ink:#f0c674;--shadow:0 2px 12px rgba(0,0,0,.55)}}
  :root[data-theme=light]{--bg:#f5f6f8;--panel:#fff;--ink:#151a21;--muted:#5c6672;--line:#e3e7ee;--grid:#eceff3;--up:#2f9e44;--down:#c92a2a;--dim:#c3ccd8;--warn-bg:#fff4e0;--warn-ink:#7a4a00}
  :root[data-theme=dark]{--bg:#0c0f14;--panel:#151b23;--ink:#e7ecf3;--muted:#98a2b0;--line:#232b35;--grid:#1a2028;--up:#4caf5f;--down:#ff6b6b;--dim:#33404f;--warn-bg:#3a2c0d;--warn-ink:#f0c674}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  .wrap{max-width:1180px;margin:0 auto;padding:20px 20px 60px}
  header{display:flex;align-items:flex-start;gap:14px;margin-bottom:6px}
  h1{margin:0;font-size:21px;letter-spacing:-.01em;flex:1}
  #theme{width:34px;height:34px;border-radius:9px;border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer;font-size:15px;flex:none}
  .sub{color:var(--muted);font-size:13px;margin:0 0 14px}
  .disclaimer{background:var(--warn-bg);color:var(--warn-ink);border-radius:10px;padding:12px 16px;font-size:13px;line-height:1.55;margin-bottom:20px}
  .disclaimer b{display:block;margin-bottom:3px;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(460px,1fr));gap:16px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px;box-shadow:var(--shadow)}
  .card h2{margin:0 0 4px;font-size:16px}
  .card .summary{color:var(--muted);font-size:12.5px;margin:0 0 12px;line-height:1.5}
  .rate{display:flex;align-items:baseline;gap:10px;margin-bottom:12px}
  .rate .n{font-size:26px;font-weight:800;font-variant-numeric:tabular-nums}
  .rate .cmp{font-size:12.5px;color:var(--muted)}
  .rate .cmp b{font-variant-numeric:tabular-nums}
  .up{color:var(--up)}.down{color:var(--down)}
  .bars{display:flex;align-items:flex-end;gap:2px;height:70px;margin-bottom:6px;border-bottom:1px solid var(--line);padding-bottom:2px}
  .bars .b{flex:1;background:var(--dim);border-radius:2px 2px 0 0;min-height:1px;position:relative}
  .bars .b.recent{background:var(--accent)}
  .bars .b:hover{opacity:.75}
  .yaxis{display:flex;justify-content:space-between;font-size:10px;color:var(--muted);margin-bottom:14px}
  .caveat{background:var(--grid);border-radius:8px;padding:9px 12px;font-size:12px;color:var(--muted);margin-bottom:12px;line-height:1.5}
  .caveat b{color:var(--ink)}
  table{width:100%;border-collapse:collapse;font-size:12px}
  th{text-align:left;color:var(--muted);font-weight:600;font-size:10.5px;text-transform:uppercase;letter-spacing:.03em;padding:5px 6px;border-bottom:1px solid var(--line)}
  td{padding:6px;border-bottom:1px solid var(--line);vertical-align:top}
  td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
  .why{color:var(--muted);font-size:11.5px;line-height:1.4}
  #tip{position:fixed;pointer-events:none;background:var(--panel);border:1px solid var(--line);border-radius:9px;box-shadow:var(--shadow);padding:7px 10px;font-size:12px;opacity:0;transition:opacity .08s;z-index:9}
  footer{color:var(--muted);font-size:11.5px;margin-top:22px;line-height:1.6}
</style></head>
<body>
<div class="wrap">
  <header><h1>Are the Governor's priorities showing up as rulemaking?</h1>
    <button id="theme" title="Toggle theme">◑</button></header>
  <p class="sub" id="sub"></p>
  <div class="disclaimer"><b>Curated, not mechanically derived</b>
    Which OAR chapters plausibly implement each priority is a judgment call — see
    <code>_meta/catalog/governor-priorities.yml</code> for the reasoning behind every chapter
    below. A recent-activity spike is consistent with active attention, not proof of it; the
    absence of one doesn't mean inaction — funding, staffing, and litigation moves don't show
    up as rulemaking at all.</p>
  <div class="grid" id="grid"></div>
  <footer id="foot"></footer>
</div>
<div id="tip"></div>
<script>
const D=/*DATA*/;
document.getElementById('sub').textContent=
  D.mapped_rules.toLocaleString()+' rules across '+D.areas.reduce((s,a)=>s+a.chapters.length,0)+
  ' mapped OAR chapters, of '+D.total_oar_rules.toLocaleString()+' total · corpus-wide baseline: '+
  Math.round(D.baseline_recent_rate*100)+'% of rules amended in the last 2 years · generated '+D.generated;
document.getElementById('foot').innerHTML=D.viz_note;

function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
const grid=document.getElementById('grid');
const tip=document.getElementById('tip');
const thisYear=D.this_year, startYear=thisYear-14;

for(const a of D.areas){
  const rate=a.n_dated? a.recent_2yr/a.n_dated : 0;
  const base=D.baseline_recent_rate;
  const diff=Math.round((rate-base)*100);
  const card=document.createElement('div');card.className='card';
  const counts=[];for(let y=startYear;y<=thisYear;y++)counts.push(a.years[y]||a.years[String(y)]||0);
  const maxN=Math.max(1,...counts);
  const bars=counts.map((n,i)=>{const y=startYear+i,h=Math.max(2,Math.round(n/maxN*66));
    return '<div class="b'+(y>=thisYear-1?' recent':'')+'" style="height:'+h+'px" data-y="'+y+'" data-n="'+n+'"></div>';}).join('');
  const chRows=a.chapters.map(ch=>{
    const cr=ch.n_dated? ch.recent_2yr/ch.n_dated:0;
    return '<tr><td>'+esc(ch.agency.replace(/-/g,' '))+'<div class="why">'+esc(ch.reasoning)+'</div></td>'+
      '<td class="n">OAR '+ch.oar_chapter+'</td><td class="n">'+ch.n_rules+'</td>'+
      '<td class="n">'+Math.round(cr*100)+'%</td></tr>';}).join('');
  card.innerHTML=
    '<h2>'+esc(a.name)+'</h2><p class="summary">'+esc(a.summary)+'</p>'+
    (a.caveat?'<div class="caveat"><b>Weakest fit of the four:</b> '+esc(a.caveat)+'</div>':'')+
    '<div class="rate"><span class="n '+(diff>=0?'up':'down')+'">'+Math.round(rate*100)+'%</span>'+
    '<span class="cmp">of mapped rules amended in the last 2 years — <b class="'+(diff>=0?'up':'down')+'">'+
    (diff>=0?'+':'')+diff+' pts</b> vs. the '+Math.round(base*100)+'% corpus-wide baseline</span></div>'+
    '<div class="bars" data-start="'+startYear+'">'+bars+'</div>'+
    '<div class="yaxis"><span>'+startYear+'</span><span>'+thisYear+'</span></div>'+
    '<table><thead><tr><th>Agency (mapped chapter, why)</th><th>Chapter</th><th>Rules</th><th>Recent 2y</th></tr></thead>'+
    '<tbody>'+chRows+'</tbody></table>';
  grid.appendChild(card);
  card.querySelectorAll('.bars .b').forEach(el=>{
    el.addEventListener('mousemove',e=>{
      tip.innerHTML='<b>'+el.dataset.y+'</b>: '+el.dataset.n+' rule'+(el.dataset.n==1?'':'s')+' amended';
      tip.style.opacity=1;tip.style.left=Math.min(e.clientX+12,innerWidth-160)+'px';tip.style.top=(e.clientY+14)+'px';
    });
    el.addEventListener('mouseleave',()=>tip.style.opacity=0);
  });
}

document.getElementById('theme').onclick=()=>{const c=document.documentElement.getAttribute('data-theme');
  document.documentElement.setAttribute('data-theme',c==='dark'?'light':c==='light'?'dark':(matchMedia('(prefers-color-scheme:dark)').matches?'light':'dark'));};
</script></body></html>
"""


if __name__ == "__main__":
    main()
