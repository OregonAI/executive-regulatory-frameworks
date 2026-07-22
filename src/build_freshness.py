#!/usr/bin/env python3
"""Regulatory-freshness visualization — the functional age of Oregon's rule and policy body,
and how far each item lags the statute it implements. An agency slicer drives a lag scatter
(rule year vs the statute's last-amendment year; the diagonal is 'in sync'), an agency
ranking, and a named list of the documents most worth reviewing.

Reads the cached dataset from build_freshness_data.py and joins in titles from the graph for
the flagged set only, so the inline payload stays small.

  python3 src/build_freshness.py          # -> viz/regulatory-freshness.html
  python3 src/build_freshness.py --check   # exit 1 if stale (CI)
"""
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT

DATA = REPO_ROOT / "_meta/freshness.json"
GRAPH = REPO_ROOT / "_meta/graph.json"
OUT = REPO_ROOT / "viz/regulatory-freshness.html"
NOW = 2026
FLAG = 10               # a rule/policy >= FLAG yrs older than its statute is "worth reviewing"
XMIN = 1955             # axis floor (older items clamp here)


def build_data() -> dict:
    fr = json.loads(DATA.read_text())
    titles = {n["id"]: n.get("title", "") for n in json.loads(GRAPH.read_text())["nodes"]}

    # agency aggregates over rules (need a stable index shared by every array)
    order, seen = [], {}
    def aidx(name):
        name = name or "(unattributed)"
        if name not in seen:
            seen[name] = len(order); order.append(name)
        return seen[name]

    ag = defaultdict(lambda: {"nr": 0, "nd": 0, "l10": 0, "ages": [], "np": 0, "pages": []})
    r_ai, r_ry, r_ay, r_id, r_sd = [], [], [], [], []
    p_ai, p_py, p_ay, p_id, p_sd = [], [], [], [], []
    tit = {}

    for r in fr["rules"]:
        i = aidx(r["ag"]); a = ag[order[i]]
        a["nr"] += 1
        if r["yr"]:
            a["ages"].append(NOW - r["yr"])
            r_ai.append(i); r_ry.append(r["yr"]); r_ay.append(r["ay"] or 0)
            r_id.append(r["id"]); r_sd.append(r["sid"] or "")
            if r["ay"]:
                a["nd"] += 1
                if r["ay"] - r["yr"] >= FLAG:
                    a["l10"] += 1
                    tit[r["id"]] = titles.get(r["id"], "")
                    if r["sid"]:
                        tit[r["sid"]] = titles.get(r["sid"], "")

    for p in fr["policies"]:
        i = aidx(p["ag"]); a = ag[order[i]]
        a["np"] += 1
        if p["yr"]:
            a["pages"].append(NOW - p["yr"])
            p_ai.append(i); p_py.append(p["yr"]); p_ay.append(p["ay"] or 0)
            p_id.append(p["id"]); p_sd.append(p["sid"] or "")
            if p["ay"] and p["ay"] - p["yr"] >= FLAG:
                tit[p["id"]] = titles.get(p["id"], "")
                if p["sid"]:
                    tit[p["sid"]] = titles.get(p["sid"], "")

    ags = []
    for i, name in enumerate(order):
        a = ag[name]
        ags.append({"n": name, "nr": a["nr"], "nd": a["nd"], "l10": a["l10"],
                    "med": round(statistics.median(a["ages"])) if a["ages"] else None,
                    "np": a["np"],
                    "pmed": round(statistics.median(a["pages"])) if a["pages"] else None})

    return {"now": NOW, "flag": FLAG, "xmin": XMIN, "ags": ags,
            "r_ai": r_ai, "r_ry": r_ry, "r_ay": r_ay, "r_id": r_id, "r_sd": r_sd,
            "p_ai": p_ai, "p_py": p_py, "p_ay": p_ay, "p_id": p_id, "p_sd": p_sd,
            "tit": tit,
            "note": fr["note"]}


def build_html(data: dict) -> str:
    return TEMPLATE.replace("/*DATA*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def outputs():
    return {OUT: build_html(build_data())}


def main():
    if not DATA.exists():
        print("freshness.json missing — run: python3 src/build_freshness_data.py")
        sys.exit(1)
    outs = outputs()
    if "--check" in sys.argv:
        stale = [p for p, t in outs.items() if not p.exists() or p.read_text() != t]
        if stale:
            print(f"{OUT.relative_to(REPO_ROOT)} is stale — run: python3 src/build_freshness.py")
            sys.exit(1)
        print("regulatory-freshness.html is current.")
        return
    for p, t in outs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    d = build_data()
    flagged = sum(a["l10"] for a in d["ags"])
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {len(d['r_id']):,} datable rules, "
          f"{len(d['ags'])} agencies, {flagged:,} flagged rules")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Oregon regulatory freshness</title>
<style>
  :root{--bg:#f5f6f8;--panel:#fff;--ink:#151a21;--muted:#5c6672;--line:#e3e7ee;--grid:#eceff3;
    --ok:#8b95a3;--warn:#e8933c;--bad:#e8590c;--crit:#c92a2a;--accent:#2f6df6;--shadow:0 2px 10px rgba(20,25,40,.10)}
  @media (prefers-color-scheme:dark){:root{--bg:#0c0f14;--panel:#151b23;--ink:#e7ecf3;--muted:#98a2b0;--line:#232b35;--grid:#1a2028;
    --ok:#5b6675;--warn:#e8933c;--bad:#f2762e;--crit:#ff6b6b;--accent:#5a9bff;--shadow:0 2px 12px rgba(0,0,0,.55)}}
  :root[data-theme=light]{--bg:#f5f6f8;--panel:#fff;--ink:#151a21;--muted:#5c6672;--line:#e3e7ee;--grid:#eceff3;--ok:#8b95a3}
  :root[data-theme=dark]{--bg:#0c0f14;--panel:#151b23;--ink:#e7ecf3;--muted:#98a2b0;--line:#232b35;--grid:#1a2028;--ok:#5b6675}
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
  .pill{display:inline-block;width:9px;height:9px;border-radius:2px;vertical-align:middle;margin-right:4px}
</style></head>
<body>
<header>
  <h1>Regulatory freshness</h1>
  <div class="sub" id="sub"></div>
  <button id="theme" title="Toggle theme">◑</button>
</header>
<div class="app">
  <div class="col left">
    <h2>Agencies · share of rules 10+ yrs behind their statute</h2>
    <div id="ranking"></div>
  </div>
  <div class="col mid">
    <canvas id="cv"></canvas>
  </div>
  <div class="col right">
    <h2 id="offhead">Most worth reviewing</h2>
    <div class="stat" id="stat"></div>
    <div id="offenders"></div>
    <div class="foot" id="foot"></div>
  </div>
</div>
<div id="tip"></div>
<script>
const D=/*DATA*/;
const NOW=D.now, FLAG=D.flag, XMIN=D.xmin;
const gapColor=g=>g>=20?'var(--crit)':g>=FLAG?'var(--bad)':g>=3?'var(--warn)':'var(--ok)';
const cssv=n=>getComputedStyle(document.body).getPropertyValue(n).trim();
const gapCss=g=>g>=20?cssv('--crit'):g>=FLAG?cssv('--bad'):g>=3?cssv('--warn'):cssv('--ok');
// selected agency: -1 = all
let sel=-1;
document.getElementById('sub').textContent=
  D.r_id.length.toLocaleString()+' datable rules · '+D.ags.reduce((s,a)=>s+a.l10,0).toLocaleString()+
  ' sit '+FLAG+'+ yrs behind a statute they implement · flags are “worth reviewing”, non-authoritative';

// ---- agency ranking (sortable by lag rate) ----
const rank=D.ags.map((a,i)=>({i,a,rate:a.nd?a.l10/a.nd:0})).filter(r=>r.a.nd>=40)
  .sort((x,y)=>y.rate-x.rate);
function ageColor(m){ // median-age heat for the bar fill
  if(m==null)return cssv('--ok');
  return m>=18?cssv('--crit'):m>=12?cssv('--bad'):m>=7?cssv('--warn'):cssv('--ok');}
function drawRanking(){
  const el=document.getElementById('ranking');
  el.innerHTML='<div class="arow'+(sel===-1?' sel':'')+'" data-i="-1"><div class="nm">All Oregon agencies</div>'+
    '<div class="pct">'+(pctAll())+'%</div><div class="bar"><i style="width:'+pctAll()+'%;background:'+cssv('--bad')+'"></i></div>'+
    '<div class="meta">'+D.r_id.length.toLocaleString()+' rules · median age '+medAll()+'y</div></div>'+
    rank.map(r=>{const p=Math.round(r.rate*100);
      return '<div class="arow'+(sel===r.i?' sel':'')+'" data-i="'+r.i+'"><div class="nm">'+esc(r.a.n)+'</div>'+
      '<div class="pct">'+p+'%</div><div class="bar"><i style="width:'+p+'%;background:'+ageColor(r.a.med)+'"></i></div>'+
      '<div class="meta">'+r.a.nd.toLocaleString()+' rules · median age '+(r.a.med??'—')+'y'+(r.a.np?' · '+r.a.np+' policies':'')+'</div></div>';}).join('');
  el.querySelectorAll('.arow').forEach(d=>d.onclick=()=>{select(+d.dataset.i);});
}
function pctAll(){let l=0,n=0;for(const a of D.ags){l+=a.l10;n+=a.nd;}return n?Math.round(l/n*100):0;}
function medAll(){const ys=[];for(let k=0;k<D.r_ry.length;k++)ys.push(NOW-D.r_ry[k]);ys.sort((a,b)=>a-b);return ys[ys.length>>1];}

// ---- scatter ----
const cv=document.getElementById('cv'),ctx=cv.getContext('2d');
let DPR=Math.min(devicePixelRatio||1,2),W=0,H=0;
const M={l:52,r:16,t:16,b:40};
function resize(){W=cv.clientWidth;H=cv.clientHeight;cv.width=W*DPR;cv.height=H*DPR;draw();}
function X(yr){return M.l+(yr-XMIN)/(NOW-XMIN)*(W-M.l-M.r);}
function Y(yr){return H-M.b-(yr-XMIN)/(NOW-XMIN)*(H-M.t-M.b);}
function draw(){
  ctx.setTransform(DPR,0,0,DPR,0,0);ctx.clearRect(0,0,W,H);
  const x0=M.l,x1=W-M.r,y0=H-M.b,y1=M.t;
  // danger wedge: rule >= FLAG yrs older than statute (below the y=x-FLAG line)
  ctx.fillStyle=cssv('--bad');ctx.globalAlpha=0.07;
  ctx.beginPath();ctx.moveTo(X(XMIN+FLAG),Y(XMIN));ctx.lineTo(X(NOW),Y(NOW-FLAG));ctx.lineTo(X(NOW),Y(XMIN));ctx.closePath();ctx.fill();
  ctx.globalAlpha=1;
  // grid + axis ticks every decade
  ctx.strokeStyle=cssv('--grid');ctx.fillStyle=cssv('--muted');ctx.font='11px system-ui';ctx.lineWidth=1;
  ctx.textAlign='center';ctx.textBaseline='top';
  for(let y=1960;y<=NOW;y+=10){const px=X(y);ctx.beginPath();ctx.moveTo(px,y1);ctx.lineTo(px,y0);ctx.stroke();ctx.fillText(y,px,y0+6);}
  ctx.textAlign='right';ctx.textBaseline='middle';
  for(let y=1960;y<=NOW;y+=10){const py=Y(y);ctx.beginPath();ctx.moveTo(x0,py);ctx.lineTo(x1,py);ctx.stroke();ctx.fillText(y,x0-6,py);}
  // diagonal (in sync) + FLAG threshold
  ctx.strokeStyle=cssv('--muted');ctx.globalAlpha=.6;ctx.beginPath();ctx.moveTo(X(XMIN),Y(XMIN));ctx.lineTo(X(NOW),Y(NOW));ctx.stroke();
  ctx.globalAlpha=.35;ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(X(XMIN+FLAG),Y(XMIN));ctx.lineTo(X(NOW),Y(NOW-FLAG));ctx.stroke();ctx.setLineDash([]);ctx.globalAlpha=1;
  // axis labels
  ctx.fillStyle=cssv('--muted');ctx.font='600 11px system-ui';
  ctx.textAlign='center';ctx.textBaseline='bottom';ctx.fillText('STATUTE last amended  →',(x0+x1)/2,H-4);
  ctx.save();ctx.translate(12,(y0+y1)/2);ctx.rotate(-Math.PI/2);ctx.textBaseline='top';ctx.fillText('RULE last filed  →',0,0);ctx.restore();
  ctx.textAlign='left';ctx.textBaseline='top';ctx.fillStyle=cssv('--muted');ctx.globalAlpha=.8;
  ctx.fillText('in sync',X(NOW-6)-2,Y(NOW-2));ctx.globalAlpha=1;
  // points
  const only=sel>=0;
  // pass 1: context (all/other agencies) faint, only when a slice is active
  if(only){ctx.globalAlpha=.10;ctx.fillStyle=cssv('--ok');
    for(let k=0;k<D.r_ai.length;k++){if(D.r_ay[k]===0)continue;ctx.fillRect(X(D.r_ay[k])-1,Y(D.r_ry[k])-1,2,2);}}
  ctx.globalAlpha=only?.9:.5;
  for(let k=0;k<D.r_ai.length;k++){
    if(D.r_ay[k]===0)continue; if(only&&D.r_ai[k]!==sel)continue;
    const g=D.r_ay[k]-D.r_ry[k];
    ctx.fillStyle=gapCss(g);
    const s=g>=FLAG?3:2.4;ctx.fillRect(X(D.r_ay[k])-s/2,Y(D.r_ry[k])-s/2,s,s);
  }
  // policies as diamonds for the slice
  ctx.globalAlpha=1;
  for(let k=0;k<D.p_ai.length;k++){
    if(D.p_ay[k]===0)continue; if(only&&D.p_ai[k]!==sel)continue; if(!only)continue;
    const g=D.p_ay[k]-D.p_py[k],px=X(D.p_ay[k]),py=Y(D.p_py[k]);
    ctx.fillStyle=gapCss(g);ctx.strokeStyle=cssv('--panel');ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(px,py-4);ctx.lineTo(px+4,py);ctx.lineTo(px,py+4);ctx.lineTo(px-4,py);ctx.closePath();ctx.fill();ctx.stroke();
  }
}
// hover: nearest point among the visible set
function nearest(mx,my){let best=-1,bd=100,kind='r';
  const only=sel>=0;
  for(let k=0;k<D.r_ai.length;k++){if(D.r_ay[k]===0)continue;if(only&&D.r_ai[k]!==sel)continue;
    const dx=X(D.r_ay[k])-mx,dy=Y(D.r_ry[k])-my,d=dx*dx+dy*dy;if(d<bd){bd=d;best=k;kind='r';}}
  if(only)for(let k=0;k<D.p_ai.length;k++){if(D.p_ay[k]===0)continue;if(D.p_ai[k]!==sel)continue;
    const dx=X(D.p_ay[k])-mx,dy=Y(D.p_py[k])-my,d=dx*dx+dy*dy;if(d<bd){bd=d;best=k;kind='p';}}
  return best<0?null:{k:best,kind};
}
const tip=document.getElementById('tip');
cv.addEventListener('mousemove',e=>{const r=cv.getBoundingClientRect();const h=nearest(e.clientX-r.left,e.clientY-r.top);
  if(!h){tip.style.opacity=0;return;}
  const A=h.kind==='r'?D.r_id:D.p_id, YR=h.kind==='r'?D.r_ry:D.p_py, AY=h.kind==='r'?D.r_ay:D.p_ay, SD=h.kind==='r'?D.r_sd:D.p_sd;
  const g=AY[h.k]-YR[h.k];
  tip.innerHTML='<b>'+cite(A[h.k])+'</b> · '+(h.kind==='r'?'rule':'policy')+' filed '+YR[h.k]+
    '<br><i>implements '+cite(SD[h.k])+' — last amended '+AY[h.k]+'</i>'+
    '<br><i style="color:'+gapCss(g)+'">'+(g>0?('+'+g+' yrs behind'):(g===0?'in sync':(-g)+' yrs ahead'))+'</i>';
  tip.style.opacity=1;tip.style.left=Math.min(e.clientX+13,innerWidth-tip.offsetWidth-8)+'px';tip.style.top=Math.min(e.clientY+13,innerHeight-tip.offsetHeight-8)+'px';
});
cv.addEventListener('mouseleave',()=>tip.style.opacity=0);

// ---- offender list + stats for the selection ----
function select(i){sel=i;drawRanking();draw();buildOffenders();}
function inSel(ai){return sel<0||ai===sel;}
function buildOffenders(){
  const items=[];
  for(let k=0;k<D.r_ai.length;k++){if(!inSel(D.r_ai[k])||D.r_ay[k]===0)continue;const g=D.r_ay[k]-D.r_ry[k];if(g>=FLAG)items.push({id:D.r_id[k],yr:D.r_ry[k],ay:D.r_ay[k],sd:D.r_sd[k],g,p:false});}
  for(let k=0;k<D.p_ai.length;k++){if(!inSel(D.p_ai[k])||D.p_ay[k]===0)continue;const g=D.p_ay[k]-D.p_py[k];if(g>=FLAG)items.push({id:D.p_id[k],yr:D.p_py[k],ay:D.p_ay[k],sd:D.p_sd[k],g,p:true});}
  items.sort((a,b)=>b.g-a.g||b.ay-a.ay);
  const scope=sel<0?'All Oregon':D.ags[sel].n;
  document.getElementById('offhead').textContent='Most worth reviewing — '+scope;
  // stats
  let nd=0,l10=0;for(let k=0;k<D.r_ai.length;k++){if(inSel(D.r_ai[k])&&D.r_ay[k]!==0){nd++;if(D.r_ay[k]-D.r_ry[k]>=FLAG)l10++;}}
  const ages=[];for(let k=0;k<D.r_ai.length;k++)if(inSel(D.r_ai[k]))ages.push(NOW-D.r_ry[k]);ages.sort((a,b)=>a-b);
  document.getElementById('stat').innerHTML=
    '<div><b>'+(ages.length?ages[ages.length>>1]:'—')+'y</b>median rule age</div>'+
    '<div><b>'+(nd?Math.round(l10/nd*100):0)+'%</b>'+FLAG+'+ yrs behind</div>'+
    '<div><b>'+l10.toLocaleString()+'</b>flagged rules</div>';
  const el=document.getElementById('offenders');
  el.innerHTML=items.slice(0,120).map(o=>
    '<div class="off"><span class="gap" style="color:'+gapCss(o.g)+'">+'+o.g+'y</span>'+
    '<a href="'+url(o.id)+'" target="_blank" rel="noopener">'+cite(o.id)+'</a>'+(o.p?' <span style="color:var(--muted)">(policy)</span>':'')+
    (D.tit[o.id]?'<div class="d">'+esc(D.tit[o.id])+'</div>':'')+
    '<div class="d">'+(o.p?'policy':'rule')+' '+o.yr+' → implements '+cite(o.sd)+' <span style="color:var(--muted)">amended '+o.ay+(D.tit[o.sd]?' · '+esc(D.tit[o.sd]):'')+'</span></div></div>').join('')
    ||'<div class="foot">No rules in this slice are '+FLAG+'+ years behind a datable statute.</div>';
  document.getElementById('foot').innerHTML=D.note;
}
function cite(id){if(!id)return '—';
  if(id.startsWith('ors-'))return 'ORS '+id.slice(4);
  if(id.startsWith('oar-'))return 'OAR '+id.slice(4).replace(/-/g,' ');
  return id.toUpperCase();}
function url(id){
  if(id.startsWith('oar-'))return 'https://secure.sos.state.or.us/oard/view.action?ruleNumber='+id.slice(4);
  if(id.startsWith('ors-'))return 'https://www.oregonlegislature.gov/bills_laws/ors/ors'+id.slice(4).split('.')[0]+'.html';
  return '#';}
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
document.getElementById('theme').onclick=()=>{const c=document.documentElement.getAttribute('data-theme');
  document.documentElement.setAttribute('data-theme',c==='dark'?'light':c==='light'?'dark':(matchMedia('(prefers-color-scheme:dark)').matches?'light':'dark'));drawRanking();draw();buildOffenders();};
addEventListener('resize',()=>{DPR=Math.min(devicePixelRatio||1,2);resize();});
drawRanking();resize();buildOffenders();
</script></body></html>
"""


if __name__ == "__main__":
    main()
