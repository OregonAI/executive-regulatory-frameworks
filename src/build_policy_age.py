#!/usr/bin/env python3
"""Policy-age visualization — where the internal policy/procedure/standard/manual body has
gone stale against a 2-year review cadence, sliced by agency. An agency slicer drives an
agency ranking (share due/overdue), an age beeswarm for the sliced agency, and a named list of
the documents most overdue for review.

Reads the cached dataset from build_policy_age_data.py.

  python3 src/build_policy_age.py          # -> viz/policy-age.html
  python3 src/build_policy_age.py --check   # exit 1 if stale (CI)
"""
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT

DATA = REPO_ROOT / "_meta/policy_age.json"
OUT = REPO_ROOT / "viz/policy-age.html"
DUE_YEARS = 2       # matches the 2-year internal review cadence
OVERDUE_YEARS = 4    # twice the cadence — a firmer "this has been missed" line


def build_data() -> dict:
    d = json.loads(DATA.read_text())
    names = {o["slug"]: o.get("name", o["slug"]) for o in
             yaml.safe_load((REPO_ROOT / "_meta/catalog/agencies.yml").read_text())["organizations"]}

    order, seen = [], {}
    def aidx(slug):
        name = names.get(slug, slug) if slug else "(unattributed)"
        if name not in seen:
            seen[name] = len(order); order.append(name)
        return seen[name]

    agg = defaultdict(lambda: {"n": 0, "dated": 0, "due": 0, "overdue": 0, "ages": []})
    ai, age, kind, cite, title, docid, url = [], [], [], [], [], [], []
    for x in d["docs"]:
        i = aidx(x["agency"])
        a = agg[order[i]]
        a["n"] += 1
        if x["age_years"] is None:
            continue
        a["dated"] += 1
        a["ages"].append(x["age_years"])
        if x["age_years"] >= OVERDUE_YEARS:
            a["overdue"] += 1
        elif x["age_years"] >= DUE_YEARS:
            a["due"] += 1
        ai.append(i); age.append(x["age_years"]); kind.append(x["doc_type"])
        cite.append(x["citation"] or x["id"].upper())
        title.append(x["title"]); docid.append(x["id"]); url.append(x.get("source_url") or "")

    ags = []
    for i, name in enumerate(order):
        a = agg[name]
        ags.append({"n": name, "total": a["n"], "dated": a["dated"],
                    "due": a["due"], "overdue": a["overdue"],
                    "med": round(statistics.median(a["ages"]), 1) if a["ages"] else None})

    return {"due_yrs": DUE_YEARS, "overdue_yrs": OVERDUE_YEARS, "ags": ags,
            "ai": ai, "age": age, "kind": kind, "cite": cite, "title": title, "id": docid,
            "url": url, "generated": d["generated"], "note": d["note"]}


def build_html(data: dict) -> str:
    return TEMPLATE.replace("/*DATA*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def outputs():
    return {OUT: build_html(build_data())}


def main():
    if not DATA.exists():
        print("policy_age.json missing — run: python3 src/build_policy_age_data.py")
        sys.exit(1)
    outs = outputs()
    if "--check" in sys.argv:
        stale = [p for p, t in outs.items() if not p.exists() or p.read_text() != t]
        if stale:
            print(f"{OUT.relative_to(REPO_ROOT)} is stale — run: python3 src/build_policy_age.py")
            sys.exit(1)
        print("policy-age.html is current.")
        return
    for p, t in outs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    d = build_data()
    overdue = sum(a["overdue"] for a in d["ags"])
    due = sum(a["due"] for a in d["ags"])
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {len(d['id'])} dated docs, {len(d['ags'])} "
          f"agencies, {due} due, {overdue} overdue")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Oregon policy age</title>
<style>
  :root{--bg:#f5f6f8;--panel:#fff;--ink:#151a21;--muted:#5c6672;--line:#e3e7ee;--grid:#eceff3;
    --ok:#2f9e44;--warn:#e8933c;--crit:#c92a2a;--accent:#2f6df6;--shadow:0 2px 10px rgba(20,25,40,.10)}
  @media (prefers-color-scheme:dark){:root{--bg:#0c0f14;--panel:#151b23;--ink:#e7ecf3;--muted:#98a2b0;--line:#232b35;--grid:#1a2028;
    --ok:#4caf5f;--warn:#e8933c;--crit:#ff6b6b;--accent:#5a9bff;--shadow:0 2px 12px rgba(0,0,0,.55)}}
  :root[data-theme=light]{--bg:#f5f6f8;--panel:#fff;--ink:#151a21;--muted:#5c6672;--line:#e3e7ee;--grid:#eceff3;--ok:#2f9e44}
  :root[data-theme=dark]{--bg:#0c0f14;--panel:#151b23;--ink:#e7ecf3;--muted:#98a2b0;--line:#232b35;--grid:#1a2028;--ok:#4caf5f}
  *{box-sizing:border-box}html,body{height:100%;margin:0}
  body{background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;overflow:hidden}
  header{position:fixed;top:0;left:0;right:0;height:58px;display:flex;align-items:center;gap:14px;padding:0 16px;background:var(--panel);border-bottom:1px solid var(--line);z-index:6}
  header h1{font-size:15px;margin:0;white-space:nowrap}
  .sub{color:var(--muted);font-size:12.5px;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #theme{width:34px;height:34px;border-radius:9px;border:1px solid var(--line);background:var(--bg);color:var(--ink);cursor:pointer;font-size:15px}
  .app{position:fixed;top:58px;left:0;right:0;bottom:0;display:grid;grid-template-columns:270px 1fr 340px;min-height:0}
  .col{min-height:0;overflow:auto;padding:12px 12px 24px}
  .col.mid{overflow:hidden;padding:0;position:relative}
  .col.left{border-right:1px solid var(--line)}.col.right{border-left:1px solid var(--line)}
  h2{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:2px 0 10px}
  .arow{display:grid;grid-template-columns:1fr auto;gap:4px 8px;align-items:center;padding:5px 7px;border-radius:8px;cursor:pointer}
  .arow:hover{background:var(--grid)}.arow.sel{background:color-mix(in srgb,var(--accent) 16%,transparent)}
  .arow .nm{font-size:12.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .arow .pct{font-size:12.5px;font-weight:700;font-variant-numeric:tabular-nums;text-align:right}
  .arow .bar{grid-column:1/3;height:5px;border-radius:3px;background:var(--grid);overflow:hidden}
  .arow .bar>i{display:block;height:100%}
  .arow .meta{grid-column:1/3;font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums}
  canvas{display:block;width:100%;height:100%}
  #tip{position:fixed;pointer-events:none;background:var(--panel);border:1px solid var(--line);border-radius:9px;box-shadow:var(--shadow);padding:8px 11px;font-size:12.5px;opacity:0;transition:opacity .07s;z-index:9;max-width:320px}
  #tip b{font-size:13px}#tip i{color:var(--muted);font-style:normal}
  .off{padding:8px 9px;border-bottom:1px solid var(--line);font-size:12.5px}
  .off a{color:var(--ink);text-decoration:none;font-weight:650}.off a:hover{text-decoration:underline}
  .off .gap{float:right;font-weight:700;font-variant-numeric:tabular-nums}
  .off .d{color:var(--muted);font-size:11.5px;margin-top:2px}
  .stat{display:flex;gap:14px;padding:2px 7px 12px}
  .stat div{font-size:12px;color:var(--muted)}.stat b{display:block;font-size:20px;color:var(--ink);font-variant-numeric:tabular-nums}
  .foot{font-size:11px;color:var(--muted);padding:10px 8px}
  .legend2{display:flex;gap:12px;padding:0 8px 8px;font-size:11.5px;color:var(--muted)}
  .legend2 span{display:inline-flex;align-items:center;gap:5px}
  .legend2 i{width:9px;height:9px;border-radius:2px}
</style></head>
<body>
<header>
  <h1>Policy age</h1>
  <div class="sub" id="sub"></div>
  <button id="theme" title="Toggle theme">◑</button>
</header>
<div class="app">
  <div class="col left">
    <h2>Agencies · share due or overdue for review</h2>
    <div id="ranking"></div>
  </div>
  <div class="col mid">
    <canvas id="cv"></canvas>
  </div>
  <div class="col right">
    <h2 id="offhead">Most overdue for review</h2>
    <div class="stat" id="stat"></div>
    <div class="legend2">
      <span><i style="background:var(--ok)"></i>current (&lt;2y)</span>
      <span><i style="background:var(--warn)"></i>due (2-4y)</span>
      <span><i style="background:var(--crit)"></i>overdue (4y+)</span>
    </div>
    <div id="offenders"></div>
    <div class="foot" id="foot"></div>
  </div>
</div>
<div id="tip"></div>
<script>
const D=/*DATA*/;
const DUE=D.due_yrs, OVERDUE=D.overdue_yrs;
const cssv=n=>getComputedStyle(document.body).getPropertyValue(n).trim();
const ageCss=y=>y>=OVERDUE?cssv('--crit'):y>=DUE?cssv('--warn'):cssv('--ok');
let sel=-1;
const totalDated=D.age.length;
document.getElementById('sub').textContent=
  totalDated.toLocaleString()+' dated policies/procedures/standards/manuals · '+
  D.ags.reduce((s,a)=>s+a.due+a.overdue,0).toLocaleString()+' due or overdue for a '+DUE+'-year review · generated '+D.generated;

// ---- ranking ----
const rank=D.ags.map((a,i)=>({i,a,rate:a.dated?(a.due+a.overdue)/a.dated:0})).filter(r=>r.a.dated>=3)
  .sort((x,y)=>y.rate-x.rate);
function pctAll(){let n=0,t=0;for(const a of D.ags){n+=a.due+a.overdue;t+=a.dated;}return t?Math.round(n/t*100):0;}
function medAll(){const a=D.age.slice().sort((x,y)=>x-y);return a.length?a[a.length>>1]:null;}
function drawRanking(){
  const el=document.getElementById('ranking');
  el.innerHTML='<div class="arow'+(sel===-1?' sel':'')+'" data-i="-1"><div class="nm">All Oregon agencies</div>'+
    '<div class="pct">'+pctAll()+'%</div><div class="bar"><i style="width:'+pctAll()+'%;background:'+cssv('--crit')+'"></i></div>'+
    '<div class="meta">'+totalDated.toLocaleString()+' dated · median age '+(medAll()??'—')+'y</div></div>'+
    rank.map(r=>{const p=Math.round(r.rate*100);
      return '<div class="arow'+(sel===r.i?' sel':'')+'" data-i="'+r.i+'"><div class="nm">'+esc(r.a.n)+'</div>'+
      '<div class="pct">'+p+'%</div><div class="bar"><i style="width:'+p+'%;background:'+ageCss(r.a.med??0)+'"></i></div>'+
      '<div class="meta">'+r.a.dated.toLocaleString()+' dated · median age '+(r.a.med??'—')+'y'+(r.a.total>r.a.dated?' · '+(r.a.total-r.a.dated)+' undated':'')+'</div></div>';}).join('');
  el.querySelectorAll('.arow').forEach(d=>d.onclick=()=>select(+d.dataset.i));
}

// ---- beeswarm-style age scatter (x = age in years, y = light jitter per doc_type row) ----
const cv=document.getElementById('cv'),ctx=cv.getContext('2d');
let DPR=Math.min(devicePixelRatio||1,2),W=0,H=0;
const M={l:56,r:20,t:20,b:44};
const KINDS=['policy','procedure','standard','manual'];
function resize(){W=cv.clientWidth;H=cv.clientHeight;cv.width=W*DPR;cv.height=H*DPR;draw();}
const maxAge=Math.max(10,...D.age)+1;
function X(y){return M.l+(y/maxAge)*(W-M.l-M.r);}
function rowY(k){const idx=KINDS.indexOf(k);const rows=KINDS.length;const h=(H-M.t-M.b)/rows;return M.t+h*(idx+0.5);}
function draw(){
  ctx.setTransform(DPR,0,0,DPR,0,0);ctx.clearRect(0,0,W,H);
  const x0=M.l,x1=W-M.r,y0=H-M.b,y1=M.t;
  // due/overdue threshold bands
  ctx.fillStyle=cssv('--warn');ctx.globalAlpha=.07;ctx.fillRect(X(DUE),y1,X(OVERDUE)-X(DUE),y0-y1);
  ctx.fillStyle=cssv('--crit');ctx.globalAlpha=.07;ctx.fillRect(X(OVERDUE),y1,x1-X(OVERDUE),y0-y1);
  ctx.globalAlpha=1;
  // grid + x axis (years)
  ctx.strokeStyle=cssv('--grid');ctx.fillStyle=cssv('--muted');ctx.font='11px system-ui';ctx.lineWidth=1;
  ctx.textAlign='center';ctx.textBaseline='top';
  for(let yr=0;yr<=maxAge;yr+=2){const px=X(yr);ctx.beginPath();ctx.moveTo(px,y1);ctx.lineTo(px,y0);ctx.stroke();ctx.fillText(yr+'y',px,y0+6);}
  // row labels
  ctx.textAlign='right';ctx.textBaseline='middle';
  for(const k of KINDS){ctx.fillText(k,x0-8,rowY(k));}
  ctx.textAlign='center';ctx.textBaseline='bottom';ctx.font='600 11px system-ui';
  ctx.fillText('YEARS SINCE LAST TOUCHED  →',(x0+x1)/2,H-4);
  // dashed threshold lines
  ctx.setLineDash([4,4]);ctx.globalAlpha=.5;
  ctx.strokeStyle=cssv('--warn');ctx.beginPath();ctx.moveTo(X(DUE),y1);ctx.lineTo(X(DUE),y0);ctx.stroke();
  ctx.strokeStyle=cssv('--crit');ctx.beginPath();ctx.moveTo(X(OVERDUE),y1);ctx.lineTo(X(OVERDUE),y0);ctx.stroke();
  ctx.setLineDash([]);ctx.globalAlpha=1;
  // points, jittered vertically within their row band, seeded by index for stability
  const only=sel>=0;
  if(only){ctx.globalAlpha=.08;ctx.fillStyle=cssv('--muted');
    for(let k=0;k<D.age.length;k++){const jy=rowY(D.kind[k])+jitter(k);ctx.fillRect(X(D.age[k])-1,jy-1,2,2);}}
  ctx.globalAlpha=only?.9:.55;
  for(let k=0;k<D.age.length;k++){
    if(only&&D.ai[k]!==sel)continue;
    const jy=rowY(D.kind[k])+jitter(k),s=3;
    ctx.fillStyle=ageCss(D.age[k]);
    ctx.fillRect(X(D.age[k])-s/2,jy-s/2,s,s);
  }
  ctx.globalAlpha=1;
}
function jitter(k){const rowH=(H-M.t-M.b)/KINDS.length;const span=rowH*0.7;
  const x=Math.sin(k*12.9898)*43758.5453; return ((x-Math.floor(x))-0.5)*span;}
function nearest(mx,my){let best=-1,bd=100;
  for(let k=0;k<D.age.length;k++){if(sel>=0&&D.ai[k]!==sel)continue;
    const jy=rowY(D.kind[k])+jitter(k),dx=X(D.age[k])-mx,dy=jy-my,d=dx*dx+dy*dy;if(d<bd){bd=d;best=k;}}
  return best;}
const tip=document.getElementById('tip');
cv.addEventListener('mousemove',e=>{const r=cv.getBoundingClientRect();const k=nearest(e.clientX-r.left,e.clientY-r.top);
  if(k<0){tip.style.opacity=0;return;}
  tip.innerHTML='<b>'+esc(D.cite[k])+'</b> · '+D.kind[k]+
    '<br><i>'+esc(D.title[k])+'</i>'+
    '<br><i style="color:'+ageCss(D.age[k])+'">'+D.age[k]+' years since last touched</i>';
  tip.style.opacity=1;tip.style.left=Math.min(e.clientX+13,innerWidth-tip.offsetWidth-8)+'px';tip.style.top=Math.min(e.clientY+13,innerHeight-tip.offsetHeight-8)+'px';
});
cv.addEventListener('mouseleave',()=>tip.style.opacity=0);

// ---- offender list + stats ----
function select(i){sel=i;drawRanking();draw();buildOffenders();}
function inSel(i){return sel<0||D.ai[i]===sel;}
function buildOffenders(){
  const items=[];
  for(let k=0;k<D.age.length;k++){if(!inSel(k)||D.age[k]<OVERDUE)continue;items.push(k);}
  items.sort((a,b)=>D.age[b]-D.age[a]);
  const scope=sel<0?'All Oregon':D.ags[sel].n;
  document.getElementById('offhead').textContent='Most overdue — '+scope;
  const ages=[];for(let k=0;k<D.age.length;k++)if(inSel(k))ages.push(D.age[k]);
  ages.sort((a,b)=>a-b);
  let due=0,overdue=0;
  for(let k=0;k<D.age.length;k++){if(!inSel(k))continue;if(D.age[k]>=OVERDUE)overdue++;else if(D.age[k]>=DUE)due++;}
  document.getElementById('stat').innerHTML=
    '<div><b>'+(ages.length?ages[ages.length>>1].toFixed(1):'—')+'y</b>median age</div>'+
    '<div><b>'+(ages.length?Math.round((due+overdue)/ages.length*100):0)+'%</b>due or overdue</div>'+
    '<div><b>'+overdue.toLocaleString()+'</b>overdue (4y+)</div>';
  const el=document.getElementById('offenders');
  el.innerHTML=items.slice(0,150).map(k=>
    '<div class="off"><span class="gap" style="color:'+ageCss(D.age[k])+'">'+D.age[k]+'y</span>'+
    '<a href="'+esc(D.url[k]||'#')+'" target="_blank" rel="noopener">'+esc(D.cite[k])+'</a>'+
    '<div class="d">'+esc(D.title[k])+' <span style="color:var(--muted)">('+D.kind[k]+')</span></div></div>').join('')
    ||'<div class="foot">No '+scope+' documents are '+OVERDUE+'+ years since last touched.</div>';
  document.getElementById('foot').innerHTML=D.note;
}
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
document.getElementById('theme').onclick=()=>{const c=document.documentElement.getAttribute('data-theme');
  document.documentElement.setAttribute('data-theme',c==='dark'?'light':c==='light'?'dark':(matchMedia('(prefers-color-scheme:dark)').matches?'light':'dark'));drawRanking();draw();buildOffenders();};
addEventListener('resize',()=>{DPR=Math.min(devicePixelRatio||1,2);resize();});
drawRanking();resize();buildOffenders();
</script></body></html>
"""


if __name__ == "__main__":
    main()
