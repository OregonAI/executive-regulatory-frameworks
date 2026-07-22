#!/usr/bin/env python3
"""Authority-chain ego explorer — pick any document and see its N-hop authority
neighborhood: the statutes it implements (walking *up* toward ORS) and the rules/policies
that implement it (walking *down*). Built from the mechanically-derived authority graph.

A compact index-based adjacency (implements edges only, mirror pairs dropped) is inlined so
the page is self-contained; BFS + a layered column layout run client-side, with per-node
fan-out capped so high-degree statutes don't explode into a hairball.

  python3 src/build_authority_explorer.py          # -> viz/authority-explorer.html
  python3 src/build_authority_explorer.py --check   # exit 1 if stale (CI)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT

GRAPH = REPO_ROOT / "_meta/graph.json"
OUT = REPO_ROOT / "viz/authority-explorer.html"
# document-layer types keep their title inline; statutes/rules use their citation id as label
DOC_LAYER = {"policy", "procedure", "standard", "executive_order", "manual"}
# reasonable default starting doc (an executive order — rich chain, modest degree)
DEFAULTS = ["das-10-000-01", "eo-2020-04", "oam-10-00-00"]


def build_data() -> dict:
    g = json.loads(GRAPH.read_text())
    nodes = g["nodes"]
    idx = {n["id"]: i for i, n in enumerate(nodes)}
    ids = [n["id"] for n in nodes]
    types = [n["doc_type"] for n in nodes]
    tl = list(dict.fromkeys(types))
    tmap = {t: i for i, t in enumerate(tl)}
    ty = [tmap[t] for t in types]
    # sparse titles: only the pickable document layer (keeps the payload small)
    titles = {str(i): n.get("title", "") for i, n in enumerate(nodes)
              if n["doc_type"] in DOC_LAYER and n.get("title")}

    fi, ti = [], []          # child implements authority: fi -> ti  (up = follow to ti)
    other = []               # related / references_external
    for e in g["edges"]:
        if e["type"] == "implements":
            a, b = idx.get(e["from"]), idx.get(e["to"])
            if a is not None and b is not None:
                fi.append(a); ti.append(b)
        elif e["type"] in ("related", "references_external"):
            a, b = idx.get(e["from"]), idx.get(e.get("to"))
            if a is not None and b is not None:
                other.append([a, b])
    start = next((s for s in DEFAULTS if s in idx), ids[0])
    return {"ids": ids, "ty": ty, "tl": tl, "titles": titles,
            "fi": fi, "ti": ti, "other": other, "start": idx[start],
            "note": "Neighborhood computed from the mechanically-derived authority graph "
                    "(implements / implemented-by). Non-authoritative; verify against the source."}


def build_html(data: dict) -> str:
    return TEMPLATE.replace("/*DATA*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def outputs():
    return {OUT: build_html(build_data())}


def main():
    outs = outputs()
    if "--check" in sys.argv:
        stale = [p for p, t in outs.items() if not p.exists() or p.read_text() != t]
        if stale:
            print(f"{OUT.relative_to(REPO_ROOT)} is stale — run: python3 src/build_authority_explorer.py")
            sys.exit(1)
        print("authority-explorer.html is current.")
        return
    for p, t in outs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    d = build_data()
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {len(d['ids']):,} nodes, "
          f"{len(d['fi']):,} implements edges")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Oregon authority-chain explorer</title>
<style>
  :root{--bg:#f5f6f8;--panel:#fff;--ink:#151a21;--muted:#5c6672;--line:#e3e7ee;--edge:#c3ccd8;--shadow:0 2px 10px rgba(20,25,40,.10)}
  @media (prefers-color-scheme:dark){:root{--bg:#0d1016;--panel:#151b23;--ink:#e7ecf3;--muted:#98a2b0;--line:#232b35;--edge:#33404f;--shadow:0 2px 12px rgba(0,0,0,.55)}}
  :root[data-theme=light]{--bg:#f5f6f8;--panel:#fff;--ink:#151a21;--muted:#5c6672;--line:#e3e7ee;--edge:#c3ccd8}
  :root[data-theme=dark]{--bg:#0d1016;--panel:#151b23;--ink:#e7ecf3;--muted:#98a2b0;--line:#232b35;--edge:#33404f}
  *{box-sizing:border-box}
  html,body{height:100%;margin:0}
  body{background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;overflow:hidden}
  header{position:fixed;top:0;left:0;right:0;height:56px;display:flex;align-items:center;gap:12px;padding:0 16px;background:var(--panel);border-bottom:1px solid var(--line);z-index:5}
  header h1{font-size:15px;margin:0;white-space:nowrap}
  .search{position:relative;flex:1;max-width:440px}
  .search input{width:100%;padding:8px 11px;border:1px solid var(--line);border-radius:9px;background:var(--bg);color:var(--ink);font-size:14px}
  .results{position:absolute;top:40px;left:0;right:0;background:var(--panel);border:1px solid var(--line);border-radius:9px;box-shadow:var(--shadow);max-height:320px;overflow:auto;display:none;z-index:9}
  .results div{padding:7px 11px;cursor:pointer;border-bottom:1px solid var(--line);font-size:13px}
  .results div:hover,.results div.sel{background:rgba(120,150,255,.14)}
  .results small{color:var(--muted);display:block;font-size:11.5px}
  .ctl{display:flex;align-items:center;gap:6px;color:var(--muted);font-size:13px;white-space:nowrap}
  .ctl select{padding:6px 8px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink)}
  canvas{position:fixed;top:56px;left:0;width:100vw;height:calc(100vh - 56px);display:block;cursor:grab}
  canvas.drag{cursor:grabbing}
  #tip{position:fixed;pointer-events:none;background:var(--panel);border:1px solid var(--line);border-radius:9px;box-shadow:var(--shadow);padding:8px 11px;font-size:12.5px;opacity:0;transition:opacity .07s;z-index:8;max-width:300px}
  #tip b{font-size:13px}#tip i{color:var(--muted);font-style:normal}
  .legend{position:fixed;left:14px;bottom:14px;background:var(--panel);border:1px solid var(--line);border-radius:10px;box-shadow:var(--shadow);padding:9px 12px;font-size:12px;z-index:4;max-width:230px}
  .legend b{display:block;margin-bottom:5px;font-size:11px;letter-spacing:.03em;text-transform:uppercase;color:var(--muted)}
  .legend span{display:inline-flex;align-items:center;gap:5px;margin:2px 8px 2px 0}
  .legend i{width:10px;height:10px;border-radius:3px;display:inline-block}
  .hint{position:fixed;right:14px;bottom:14px;color:var(--muted);font-size:11.5px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:6px 10px;z-index:4;max-width:260px;text-align:right}
  #theme{width:34px;height:34px;border-radius:9px;border:1px solid var(--line);background:var(--bg);color:var(--ink);cursor:pointer;font-size:15px}
</style></head>
<body>
<header>
  <h1>Authority-chain explorer</h1>
  <div class="search"><input id="q" type="search" placeholder="Search a document (e.g. ORS 496, DAS 10-000-01, executive order)…" autocomplete="off"><div class="results" id="res"></div></div>
  <div class="ctl">hops <select id="hops"><option>1</option><option selected>2</option><option>3</option><option>4</option></select></div>
  <div class="ctl">dir <select id="dir"><option value="both" selected>up + down</option><option value="up">authorities (up)</option><option value="down">implementers (down)</option></select></div>
  <button id="theme" title="Toggle theme">◑</button>
</header>
<canvas id="cv"></canvas>
<div id="tip"></div>
<div class="legend" id="legend"></div>
<div class="hint">scroll = zoom · drag = pan · click a node to recenter</div>
<script>
const DATA=/*DATA*/;
const N=DATA.ids.length;
// build adjacency (up = follow implements to authority; down = reverse)
const up=Array.from({length:N},()=>[]), down=Array.from({length:N},()=>[]);
for(let k=0;k<DATA.fi.length;k++){up[DATA.fi[k]].push(DATA.ti[k]);down[DATA.ti[k]].push(DATA.fi[k]);}
const COLOR={statute:'#2f9e44',rule:'#2f6df6',policy:'#e8590c',executive_order:'#ae3ec9',manual:'#0c8599',procedure:'#f08c00',standard:'#c2255c',external_reference:'#868e96'};
const tl=DATA.tl;
function label(i){const id=DATA.ids[i];
  if(id.startsWith('ors-'))return 'ORS '+id.slice(4);
  if(id.startsWith('oar-'))return 'OAR '+id.slice(4).replace(/-/g,' ');
  if(id.startsWith('eo-'))return 'EO '+id.slice(3);
  return id.toUpperCase();}
function title(i){return DATA.titles[i]||'';}
function tname(i){return tl[DATA.ty[i]];}
const CAP=60;                 // max neighbors expanded per node (tames degree-3312 statutes)

let nodes=[],edges=[],pos=new Map();
function buildEgo(center,hops,dir){
  // depth = unsigned hop distance; side = direction of the branch's FIRST hop from center
  // (+1 authorities / -1 implementers). layer = side*depth keeps the two directions in
  // separate columns and stops an up-then-down path collapsing back onto the center column.
  const depth=new Map([[center,0]]),side=new Map([[center,0]]);
  let frontier=[center];const E=[];
  for(let h=0;h<hops;h++){
    const next=[];
    for(const u of frontier){
      const outs=[];
      if(dir!=='down'){for(const v of up[u])outs.push([v,+1]);}
      if(dir!=='up'){for(const v of down[u])outs.push([v,-1]);}
      let c=0;
      for(const [v,sgn] of outs){
        if(c++>=CAP)break;
        E.push([u,v]);
        if(!depth.has(v)){depth.set(v,h+1);side.set(v,u===center?sgn:side.get(u));next.push(v);}
      }
    }
    frontier=next;
    if(!frontier.length)break;
  }
  const layerOf=n=>side.get(n)*depth.get(n);
  // dedupe edges
  const ek=new Set();edges=[];
  for(const [a,b] of E){const key=a<b?a+'_'+b:b+'_'+a;if(ek.has(key))continue;ek.add(key);edges.push([a,b]);}
  nodes=[...depth.keys()];
  // layered layout: x by layer, y stacked within layer
  const byLayer=new Map();
  for(const n of nodes){const L=layerOf(n);(byLayer.get(L)||byLayer.set(L,[]).get(L)).push(n);}
  const layers=[...byLayer.keys()].sort((a,b)=>a-b);
  pos=new Map();
  const COLW=240;
  for(const L of layers){
    const col=byLayer.get(L);
    col.sort((a,b)=>DATA.ty[a]-DATA.ty[b]||a-b);
    // target a bounded column height (~720px) so a 130-implementer column packs tight
    // instead of forcing a 4000px stack that flattens the horizontal chain on fit()
    const gap=Math.max(5,Math.min(64,720/Math.max(col.length-1,1)));
    const h=(col.length-1)*gap;
    col.forEach((n,i)=>pos.set(n,{x:L*COLW,y:i*gap-h/2,c:L,center:n===center}));
  }
  frame();
}

const cv=document.getElementById('cv'),ctx=cv.getContext('2d');
let DPR=Math.min(devicePixelRatio||1,2);
let view={s:1,tx:0,ty:0};let sized=false;
function resize(){const w=cv.clientWidth,h=cv.clientHeight;cv.width=w*DPR;cv.height=h*DPR;if(!sized){fit();sized=true;}else frame();}
function fit(){ // center the ego graph in view
  let minx=1e9,maxx=-1e9,miny=1e9,maxy=-1e9;
  for(const p of pos.values()){minx=Math.min(minx,p.x);maxx=Math.max(maxx,p.x);miny=Math.min(miny,p.y);maxy=Math.max(maxy,p.y);}
  if(minx>maxx){minx=maxx=miny=maxy=0;}
  const w=cv.clientWidth,h=cv.clientHeight,gw=maxx-minx||1,gh=maxy-miny||1;
  view.s=Math.min(2,Math.max(.25,Math.min((w-160)/gw,(h-140)/gh)));
  view.tx=w/2-(minx+maxx)/2*view.s;view.ty=h/2-(miny+maxy)/2*view.s;
  frame();
}
function frame(){
  ctx.setTransform(DPR,0,0,DPR,0,0);
  ctx.clearRect(0,0,cv.clientWidth,cv.clientHeight);
  ctx.save();ctx.translate(view.tx,view.ty);ctx.scale(view.s,view.s);
  ctx.lineWidth=1/view.s;ctx.strokeStyle=getComputedStyle(document.body).getPropertyValue('--edge');
  ctx.beginPath();
  for(const [a,b] of edges){const p=pos.get(a),qq=pos.get(b);if(!p||!qq)continue;ctx.moveTo(p.x,p.y);ctx.lineTo(qq.x,qq.y);}
  ctx.stroke();
  const showLabels=nodes.length<=90||view.s>0.7;
  for(const n of nodes){
    const p=pos.get(n);const r=p.center?9:6;
    ctx.beginPath();ctx.arc(p.x,p.y,r,0,7);
    ctx.fillStyle=COLOR[tname(n)]||'#888';ctx.fill();
    if(p.center){ctx.lineWidth=2.5/view.s;ctx.strokeStyle=getComputedStyle(document.body).getPropertyValue('--ink');ctx.stroke();}
    if(showLabels){
      ctx.fillStyle=getComputedStyle(document.body).getPropertyValue('--ink');
      ctx.font=(p.center?'600 ':'')+(12)+'px system-ui';ctx.textBaseline='middle';
      ctx.fillText(label(n),p.x+r+4,p.y);
    }
  }
  ctx.restore();
}
// interaction
let drag=null;
cv.addEventListener('mousedown',e=>{drag={x:e.clientX,y:e.clientY,tx:view.tx,ty:view.ty,moved:false};cv.classList.add('drag');});
addEventListener('mousemove',e=>{
  if(drag){view.tx=drag.tx+(e.clientX-drag.x);view.ty=drag.ty+(e.clientY-drag.y);if(Math.abs(e.clientX-drag.x)+Math.abs(e.clientY-drag.y)>3)drag.moved=true;frame();return;}
  hover(e);
});
addEventListener('mouseup',e=>{
  if(drag&&!drag.moved){const n=pick(e);if(n!=null)recenter(n);}
  drag=null;cv.classList.remove('drag');
});
cv.addEventListener('wheel',e=>{e.preventDefault();
  const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  const f=Math.exp(-e.deltaY*0.0015),ns=Math.min(4,Math.max(.12,view.s*f));
  view.tx=mx-(mx-view.tx)*ns/view.s;view.ty=my-(my-view.ty)*ns/view.s;view.s=ns;frame();
},{passive:false});
function toWorld(e){const r=cv.getBoundingClientRect();return{x:(e.clientX-r.left-view.tx)/view.s,y:(e.clientY-r.top-view.ty)/view.s};}
function pick(e){const w=toWorld(e);let best=null,bd=14*14/(view.s*view.s);
  for(const n of nodes){const p=pos.get(n);const dx=p.x-w.x,dy=p.y-w.y,d=dx*dx+dy*dy;if(d<bd){bd=d;best=n;}}return best;}
const tip=document.getElementById('tip');
function hover(e){const n=pick(e);
  if(n==null){tip.style.opacity=0;return;}
  const t=title(n);
  tip.innerHTML='<b>'+label(n)+'</b>'+(t?'<br><i>'+esc(t)+'</i>':'')+'<br><i>'+tname(n).replace('_',' ')+' · up '+up[n].length+' · down '+down[n].length+'</i>';
  tip.style.opacity=1;tip.style.left=Math.min(e.clientX+13,innerWidth-tip.offsetWidth-8)+'px';tip.style.top=Math.min(e.clientY+13,innerHeight-tip.offsetHeight-8)+'px';
}
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function recenter(n){history.replaceState(null,'',location.pathname);current=n;refresh(true);}
// controls
let current=DATA.start;
function refresh(doFit){buildEgo(current,+hopsSel.value,dirSel.value);if(doFit)fit();}
const hopsSel=document.getElementById('hops'),dirSel=document.getElementById('dir');
hopsSel.onchange=()=>refresh(true);dirSel.onchange=()=>refresh(true);
document.getElementById('theme').onclick=()=>{const c=document.documentElement.getAttribute('data-theme');
  document.documentElement.setAttribute('data-theme',c==='dark'?'light':c==='light'?'dark':(matchMedia('(prefers-color-scheme:dark)').matches?'light':'dark'));frame();};
// search (linear over ids/titles; N~68k is fine)
const q=document.getElementById('q'),res=document.getElementById('res');
let qsel=0,matches=[];
function norm(s){return s.toLowerCase().replace(/[^a-z0-9]/g,'');}
q.addEventListener('input',()=>{
  const raw=q.value.trim();if(!raw){res.style.display='none';return;}
  const nq=norm(raw);matches=[];
  for(let i=0;i<N&&matches.length<40;i++){
    if(norm(DATA.ids[i]).includes(nq)||(DATA.titles[i]&&DATA.titles[i].toLowerCase().includes(raw.toLowerCase())))matches.push(i);
  }
  qsel=0;drawRes();
});
function drawRes(){
  if(!matches.length){res.style.display='none';return;}
  res.innerHTML=matches.map((i,k)=>'<div class="'+(k===qsel?'sel':'')+'" data-i="'+i+'"><b>'+label(i)+'</b>'+(title(i)?'<small>'+esc(title(i))+'</small>':'')+'</div>').join('');
  res.style.display='block';
  res.querySelectorAll('div').forEach(d=>d.onclick=()=>choose(+d.dataset.i));
}
function choose(i){q.value='';res.style.display='none';recenter(i);}
q.addEventListener('keydown',e=>{
  if(!matches.length)return;
  if(e.key==='ArrowDown'){qsel=(qsel+1)%matches.length;drawRes();e.preventDefault();}
  else if(e.key==='ArrowUp'){qsel=(qsel-1+matches.length)%matches.length;drawRes();e.preventDefault();}
  else if(e.key==='Enter'){choose(matches[qsel]);e.preventDefault();}
  else if(e.key==='Escape'){res.style.display='none';}
});
document.addEventListener('click',e=>{if(!e.target.closest('.search'))res.style.display='none';});
// legend
document.getElementById('legend').innerHTML='<b>document type</b>'+
  Object.entries(COLOR).filter(([k])=>tl.includes(k)).map(([k,c])=>'<span><i style="background:'+c+'"></i>'+k.replace('_',' ')+'</span>').join('');
addEventListener('resize',()=>{DPR=Math.min(devicePixelRatio||1,2);resize();});
refresh(false);resize();
</script></body></html>
"""


if __name__ == "__main__":
    main()
