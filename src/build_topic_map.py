#!/usr/bin/env python3
"""Semantic topic map — a 2-D UMAP projection of every document's embedding, one point per
document. Nearby points are semantically similar text, so clusters surface de-facto topics
that cut across the ORS/OAR/policy boundary. The map is labeled with the distinctive words of
each topic cluster, and points can be colored by document type, owning agency, or topic.

Reads the cached projection from build_topic_projection.py (UMAP + clustering are slow +
stochastic, so they are computed once and committed); this generator joins in each doc's type
and agency and renders the self-contained scatter. Coordinates are the quantised 0..4095 grid.

  python3 src/build_topic_map.py          # -> viz/topic-map.html
  python3 src/build_topic_map.py --check   # exit 1 if stale (CI)
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
PROJ = REPO_ROOT / "_meta/embeddings/projection.2d.json"
OUT = REPO_ROOT / "viz/topic-map.html"
DOC_LAYER = {"policy", "procedure", "standard", "executive_order", "manual"}
TOP_AGENCIES = 15  # distinctly-colored; the rest fold into "other agencies"


def _agency_of(doc_id: str, node: dict, reg: dict, names: dict):
    """Owning agency display name for a document, or None (statutes have none)."""
    if doc_id.startswith("ors-"):
        return None
    if doc_id.startswith("oar-"):
        org = reg.get(doc_id.split("-")[1])
        return names.get(org["slug"], org["slug"]) if org else None
    path = node.get("path", "")
    if path.startswith("agencies/"):
        slug = path.split("/")[1]
        return names.get(slug, slug)
    return None


def build_data() -> dict:
    proj = json.loads(PROJ.read_text())
    g = json.loads(GRAPH.read_text())
    meta = {n["id"]: n for n in g["nodes"]}
    reg = load_registry_by_chapter()
    names = {o["slug"]: o.get("name", o["slug"]) for o in
             yaml.safe_load((REPO_ROOT / "_meta/catalog/agencies.yml").read_text())["organizations"]}
    ids = proj["ids"]

    types = [meta.get(i, {}).get("doc_type", "external_reference") for i in ids]
    tl = list(dict.fromkeys(types))
    tmap = {t: k for k, t in enumerate(tl)}
    ty = [tmap[t] for t in types]

    # owning agency per point, folded to top-N + "other" + a statutes bucket
    agency = [_agency_of(i, meta.get(i, {}), reg, names) for i in ids]
    top = {a for a, _ in Counter(a for a in agency if a).most_common(TOP_AGENCIES)}
    order = [a for a, _ in Counter(a for a in agency if a).most_common(TOP_AGENCIES)]
    agl = [{"name": a, "kind": "agency"} for a in order]
    agl.append({"name": "other agencies", "kind": "other"})
    agl.append({"name": "ORS statutes (no agency)", "kind": "statute"})
    OTHER, STAT = len(order), len(order) + 1
    aidx = {a: k for k, a in enumerate(order)}
    ag = [STAT if a is None and i.startswith("ors-") else
          (aidx[a] if a in top else OTHER) for i, a in zip(ids, agency)]
    for e in agl:  # attach counts
        e["n"] = 0
    agn = Counter(ag)
    for k, e in enumerate(agl):
        e["n"] = agn.get(k, 0)

    titles = {str(k): meta[i].get("title", "") for k, i in enumerate(ids)
              if types[k] in DOC_LAYER and meta.get(i, {}).get("title")}
    return {"ids": ids, "x": proj["x"], "y": proj["y"], "grid": proj["grid"],
            "ty": ty, "tl": tl, "ag": ag, "agl": agl,
            "cl": proj["cl"], "clusters": proj["clusters"],
            "titles": titles, "n": len(ids),
            "note": "2-D UMAP (cosine) of model2vec document embeddings; regions labeled by "
                    "their distinctive words. Proximity ≈ textual similarity, not authority. "
                    "Non-authoritative; a lossy projection."}


def build_html(data: dict) -> str:
    return TEMPLATE.replace("/*DATA*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def outputs():
    return {OUT: build_html(build_data())}


def main():
    if not PROJ.exists():
        print("projection cache missing — run: .venv/bin/python src/build_topic_projection.py")
        sys.exit(1)
    outs = outputs()
    if "--check" in sys.argv:
        stale = [p for p, t in outs.items() if not p.exists() or p.read_text() != t]
        if stale:
            print(f"{OUT.relative_to(REPO_ROOT)} is stale — run: python3 src/build_topic_map.py")
            sys.exit(1)
        print("topic-map.html is current.")
        return
    for p, t in outs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    d = build_data()
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {d['n']:,} points, "
          f"{len(d['clusters'])} topic clusters, {len(d['agl'])} agency buckets")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Oregon policy corpus — semantic topic map</title>
<style>
  :root{--bg:#f5f6f8;--panel:#fff;--ink:#151a21;--muted:#5c6672;--line:#e3e7ee;--shadow:0 2px 10px rgba(20,25,40,.10)}
  @media (prefers-color-scheme:dark){:root{--bg:#0b0e13;--panel:#141a22;--ink:#e7ecf3;--muted:#98a2b0;--line:#232b35;--shadow:0 2px 12px rgba(0,0,0,.55)}}
  :root[data-theme=light]{--bg:#f5f6f8;--panel:#fff;--ink:#151a21;--muted:#5c6672;--line:#e3e7ee}
  :root[data-theme=dark]{--bg:#0b0e13;--panel:#141a22;--ink:#e7ecf3;--muted:#98a2b0;--line:#232b35}
  *{box-sizing:border-box}html,body{height:100%;margin:0}
  body{background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;overflow:hidden}
  header{position:fixed;top:0;left:0;right:0;height:54px;display:flex;align-items:center;gap:14px;padding:0 16px;background:var(--panel);border-bottom:1px solid var(--line);z-index:5}
  header h1{font-size:15px;margin:0;white-space:nowrap}
  .sub{color:var(--muted);font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
  .ctl{display:flex;align-items:center;gap:6px;color:var(--muted);font-size:13px;white-space:nowrap}
  .ctl select{padding:6px 8px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink)}
  canvas{position:fixed;top:54px;left:0;width:100vw;height:calc(100vh - 54px);display:block;cursor:crosshair}
  #tip{position:fixed;pointer-events:none;background:var(--panel);border:1px solid var(--line);border-radius:9px;box-shadow:var(--shadow);padding:8px 11px;font-size:12.5px;opacity:0;transition:opacity .07s;z-index:8;max-width:320px}
  #tip b{font-size:13px}#tip i{color:var(--muted);font-style:normal}
  .legend{position:fixed;left:14px;bottom:14px;background:var(--panel);border:1px solid var(--line);border-radius:10px;box-shadow:var(--shadow);padding:10px 12px;font-size:12.5px;z-index:4;max-height:60vh;overflow:auto;max-width:280px}
  .legend b{display:block;margin-bottom:6px;font-size:11px;letter-spacing:.03em;text-transform:uppercase;color:var(--muted)}
  .legend label{display:flex;align-items:center;gap:7px;margin:3px 0;cursor:pointer;user-select:none}
  .legend i{width:11px;height:11px;border-radius:3px;display:inline-block;flex:none}
  .legend .off{opacity:.32}
  .legend span.ct{color:var(--muted);margin-left:auto;font-variant-numeric:tabular-nums;padding-left:12px}
  .hint{position:fixed;right:14px;bottom:14px;color:var(--muted);font-size:11.5px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:6px 10px;z-index:4;text-align:right;max-width:260px}
  #theme{width:34px;height:34px;border-radius:9px;border:1px solid var(--line);background:var(--bg);color:var(--ink);cursor:pointer;font-size:15px}
</style></head>
<body>
<header>
  <h1>Semantic topic map</h1>
  <div class="sub" id="sub"></div>
  <div class="ctl">color by <select id="mode"><option value="topic" selected>topic</option><option value="type">document type</option><option value="agency">agency</option></select></div>
  <button id="theme" title="Toggle theme">◑</button>
</header>
<canvas id="cv"></canvas>
<div id="tip"></div>
<div class="legend" id="legend"></div>
<div class="hint">scroll = zoom · drag = pan · hover a point for the document</div>
<script>
const DATA=/*DATA*/;
const N=DATA.n, G=DATA.grid;
const TYPECOL={statute:'#2f9e44',rule:'#2f6df6',policy:'#e8590c',executive_order:'#ae3ec9',manual:'#0c8599',procedure:'#f08c00',standard:'#c2255c',external_reference:'#868e96'};
const PAL16=['#2f6df6','#e8590c','#2f9e44','#ae3ec9','#0c8599','#c2255c','#f08c00','#5c7cfa','#37b24d','#f76707','#9c36b5','#1098ad','#e64980','#4263eb','#66a80f','#d6336c'];
const tl=DATA.tl;
document.getElementById('sub').textContent=N.toLocaleString()+' documents · '+DATA.clusters.length+' labeled topic regions · proximity ≈ textual similarity (non-authoritative)';
function docLabel(k){const id=DATA.ids[k];
  if(id.startsWith('ors-'))return 'ORS '+id.slice(4);
  if(id.startsWith('oar-'))return 'OAR '+id.slice(4).replace(/-/g,' ');
  if(id.startsWith('eo-'))return 'EO '+id.slice(3);
  return id.toUpperCase();}
function topicColor(i){return `hsl(${(i*137.508)%360},58%,55%)`;}
function agColor(i){const e=DATA.agl[i];return e.kind==='other'?'#8892a0':e.kind==='statute'?'#b4bcc7':PAL16[i%PAL16.length];}
// color modes: each maps a per-point category array to a list of {name,color}
const MODES={
  topic:{arr:DATA.cl,cats:DATA.clusters.map((c,i)=>({name:c.t,color:topicColor(i),n:c.n})),title:'topic region'},
  type:{arr:DATA.ty,cats:tl.map((t)=>({name:t.replace(/_/g,' '),color:TYPECOL[t]||'#888'})),title:'document type'},
  agency:{arr:DATA.ag,cats:DATA.agl.map((a,i)=>({name:a.name,color:agColor(i),n:a.n})),title:'agency'},
};
let mode='topic',cur=MODES[mode],on=cur.cats.map(()=>true);
// spatial grid index for hover pick
const B=128, cell=(G+1)/B, buckets=Array.from({length:B*B},()=>[]);
for(let k=0;k<N;k++){const bx=Math.min(B-1,DATA.x[k]/cell|0),by=Math.min(B-1,DATA.y[k]/cell|0);buckets[by*B+bx].push(k);}
const cv=document.getElementById('cv'),ctx=cv.getContext('2d');
let DPR=Math.min(devicePixelRatio||1,2);
let view={s:1,tx:0,ty:0},sized=false;
function resize(){cv.width=cv.clientWidth*DPR;cv.height=cv.clientHeight*DPR;if(!sized){fit();sized=true;}else frame();}
function fit(){const w=cv.clientWidth,h=cv.clientHeight,pad=40;
  view.s=Math.min((w-pad*2)/G,(h-pad*2)/G);view.tx=(w-G*view.s)/2;view.ty=(h-G*view.s)/2;frame();}
let raf=0;function frame(){if(raf)return;raf=requestAnimationFrame(draw);}
function draw(){raf=0;
  ctx.setTransform(DPR,0,0,DPR,0,0);ctx.clearRect(0,0,cv.clientWidth,cv.clientHeight);
  const sz=Math.max(1.3,1.1*Math.sqrt(view.s)*3),half=sz/2,arr=cur.arr;
  ctx.globalAlpha=0.72;
  for(let c=0;c<cur.cats.length;c++){
    if(!on[c])continue;ctx.fillStyle=cur.cats[c].color;
    for(let k=0;k<N;k++){if(arr[k]!==c)continue;
      const px=view.tx+DATA.x[k]*view.s,py=view.ty+DATA.y[k]*view.s;
      ctx.fillRect(px-half,py-half,sz,sz);}
  }
  ctx.globalAlpha=1;
  drawTopicLabels();
}
function drawTopicLabels(){
  ctx.textAlign='center';ctx.textBaseline='middle';
  const ink=getComputedStyle(document.body).getPropertyValue('--ink').trim();
  const panel=getComputedStyle(document.body).getPropertyValue('--panel').trim();
  ctx.font='600 12.5px system-ui';
  for(const c of DATA.clusters){
    const px=view.tx+c.x*view.s,py=view.ty+c.y*view.s;
    if(px<-40||px>cv.clientWidth+40||py<-20||py>cv.clientHeight+20)continue;
    const w=ctx.measureText(c.t).width;
    ctx.globalAlpha=0.72;ctx.fillStyle=panel;
    ctx.fillRect(px-w/2-5,py-9,w+10,18);
    ctx.globalAlpha=1;ctx.fillStyle=ink;ctx.fillText(c.t,px,py);
  }
}
let drag=null;
cv.addEventListener('mousedown',e=>{drag={x:e.clientX,y:e.clientY,tx:view.tx,ty:view.ty};});
addEventListener('mousemove',e=>{
  if(drag){view.tx=drag.tx+(e.clientX-drag.x);view.ty=drag.ty+(e.clientY-drag.y);frame();return;}
  hover(e);
});
addEventListener('mouseup',()=>drag=null);
cv.addEventListener('wheel',e=>{e.preventDefault();
  const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  const f=Math.exp(-e.deltaY*0.0015),ns=Math.min(60,Math.max((cv.clientWidth/G)*0.5,view.s*f));
  view.tx=mx-(mx-view.tx)*ns/view.s;view.ty=my-(my-view.ty)*ns/view.s;view.s=ns;frame();
},{passive:false});
const tip=document.getElementById('tip');
function hover(e){const r=cv.getBoundingClientRect();
  const wx=(e.clientX-r.left-view.tx)/view.s,wy=(e.clientY-r.top-view.ty)/view.s;
  const bx=wx/cell|0,by=wy/cell|0;let best=-1,bd=(10/view.s)*(10/view.s);
  for(let gy=Math.max(0,by-1);gy<=Math.min(B-1,by+1);gy++)for(let gx=Math.max(0,bx-1);gx<=Math.min(B-1,bx+1);gx++){
    for(const k of buckets[gy*B+gx]){if(!on[cur.arr[k]])continue;const dx=DATA.x[k]-wx,dy=DATA.y[k]-wy,d=dx*dx+dy*dy;if(d<bd){bd=d;best=k;}}}
  if(best<0){tip.style.opacity=0;return;}
  const t=DATA.titles[best]||'';
  tip.innerHTML='<b>'+docLabel(best)+'</b>'+(t?'<br><i>'+esc(t)+'</i>':'')
    +'<br><i>'+tl[DATA.ty[best]].replace(/_/g,' ')+' · topic: '+esc(DATA.clusters[DATA.cl[best]].t)+'</i>';
  tip.style.opacity=1;tip.style.left=Math.min(e.clientX+13,innerWidth-tip.offsetWidth-8)+'px';tip.style.top=Math.min(e.clientY+13,innerHeight-tip.offsetHeight-8)+'px';
}
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
document.getElementById('theme').onclick=()=>{const c=document.documentElement.getAttribute('data-theme');
  document.documentElement.setAttribute('data-theme',c==='dark'?'light':c==='light'?'dark':(matchMedia('(prefers-color-scheme:dark)').matches?'light':'dark'));frame();};
function buildLegend(){
  const counts=cur.cats.map((c,i)=>c.n!==undefined?c.n:0);
  if(cur.cats[0].n===undefined){cur.arr.forEach(v=>counts[v]++);}
  const idx=cur.cats.map((_,i)=>i).sort((a,b)=>counts[b]-counts[a]);
  document.getElementById('legend').innerHTML='<b>'+cur.title+' · click to filter</b>'+
    idx.map(i=>'<label data-c="'+i+'"><i style="background:'+cur.cats[i].color+'"></i>'+esc(cur.cats[i].name)+
      '<span class="ct">'+counts[i].toLocaleString()+'</span></label>').join('');
  document.querySelectorAll('.legend label').forEach(l=>l.onclick=()=>{const c=+l.dataset.c;on[c]=!on[c];l.classList.toggle('off',!on[c]);frame();});
}
document.getElementById('mode').onchange=e=>{mode=e.target.value;cur=MODES[mode];on=cur.cats.map(()=>true);buildLegend();frame();};
addEventListener('resize',()=>{DPR=Math.min(devicePixelRatio||1,2);resize();});
buildLegend();resize();
</script></body></html>
"""


if __name__ == "__main__":
    main()
