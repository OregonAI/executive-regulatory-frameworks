#!/usr/bin/env python3
"""Semantic topic map — a 2-D UMAP projection of every document's embedding, one point per
document, colored by document type. Nearby points are semantically similar text, so clusters
surface de-facto topics that cut across the ORS/OAR/policy boundary.

Reads the cached projection from build_topic_projection.py (UMAP is slow + stochastic, so it
is computed once and committed); this generator only joins in each doc's type and renders the
self-contained scatter. Point coordinates are the quantised 0..4095 grid from the cache.

  python3 src/build_topic_map.py          # -> viz/topic-map.html
  python3 src/build_topic_map.py --check   # exit 1 if stale (CI)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT

GRAPH = REPO_ROOT / "_meta/graph.json"
PROJ = REPO_ROOT / "_meta/embeddings/projection.2d.json"
OUT = REPO_ROOT / "viz/topic-map.html"
DOC_LAYER = {"policy", "procedure", "standard", "executive_order", "manual"}


def build_data() -> dict:
    proj = json.loads(PROJ.read_text())
    g = json.loads(GRAPH.read_text())
    meta = {n["id"]: n for n in g["nodes"]}
    ids = proj["ids"]
    types = [meta.get(i, {}).get("doc_type", "external_reference") for i in ids]
    tl = list(dict.fromkeys(types))
    tmap = {t: k for k, t in enumerate(tl)}
    ty = [tmap[t] for t in types]
    # sparse titles for the readable document layer (hover); statutes/rules use their id
    titles = {str(k): meta[i].get("title", "") for k, i in enumerate(ids)
              if types[k] in DOC_LAYER and meta.get(i, {}).get("title")}
    return {"ids": ids, "x": proj["x"], "y": proj["y"], "grid": proj["grid"],
            "ty": ty, "tl": tl, "titles": titles, "n": len(ids),
            "note": "2-D UMAP (cosine) of model2vec document embeddings. Proximity ≈ textual "
                    "similarity, not authority. Non-authoritative; a lossy projection."}


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
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {d['n']:,} points, {len(d['tl'])} types")


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
  .sub{color:var(--muted);font-size:12.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  canvas{position:fixed;top:54px;left:0;width:100vw;height:calc(100vh - 54px);display:block;cursor:crosshair}
  #tip{position:fixed;pointer-events:none;background:var(--panel);border:1px solid var(--line);border-radius:9px;box-shadow:var(--shadow);padding:8px 11px;font-size:12.5px;opacity:0;transition:opacity .07s;z-index:8;max-width:300px}
  #tip b{font-size:13px}#tip i{color:var(--muted);font-style:normal}
  .legend{position:fixed;left:14px;bottom:14px;background:var(--panel);border:1px solid var(--line);border-radius:10px;box-shadow:var(--shadow);padding:10px 12px;font-size:12.5px;z-index:4}
  .legend b{display:block;margin-bottom:6px;font-size:11px;letter-spacing:.03em;text-transform:uppercase;color:var(--muted)}
  .legend label{display:flex;align-items:center;gap:7px;margin:3px 0;cursor:pointer;user-select:none}
  .legend i{width:11px;height:11px;border-radius:3px;display:inline-block}
  .legend .off{opacity:.32}
  .legend span.ct{color:var(--muted);margin-left:auto;font-variant-numeric:tabular-nums;padding-left:12px}
  .hint{position:fixed;right:14px;bottom:14px;color:var(--muted);font-size:11.5px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:6px 10px;z-index:4;text-align:right;max-width:260px}
  #theme{width:34px;height:34px;border-radius:9px;border:1px solid var(--line);background:var(--bg);color:var(--ink);cursor:pointer;font-size:15px;margin-left:auto}
</style></head>
<body>
<header>
  <h1>Semantic topic map</h1>
  <div class="sub" id="sub"></div>
  <button id="theme" title="Toggle theme">◑</button>
</header>
<canvas id="cv"></canvas>
<div id="tip"></div>
<div class="legend" id="legend"></div>
<div class="hint">scroll = zoom · drag = pan · hover a point for the document</div>
<script>
const DATA=/*DATA*/;
const N=DATA.n, G=DATA.grid;
const COLOR={statute:'#2f9e44',rule:'#2f6df6',policy:'#e8590c',executive_order:'#ae3ec9',manual:'#0c8599',procedure:'#f08c00',standard:'#c2255c',external_reference:'#868e96'};
const tl=DATA.tl;
const on=tl.map(()=>true);
document.getElementById('sub').textContent=N.toLocaleString()+' documents · UMAP of embeddings · proximity ≈ textual similarity (non-authoritative)';
function label(k){const id=DATA.ids[k];
  if(id.startsWith('ors-'))return 'ORS '+id.slice(4);
  if(id.startsWith('oar-'))return 'OAR '+id.slice(4).replace(/-/g,' ');
  if(id.startsWith('eo-'))return 'EO '+id.slice(3);
  return id.toUpperCase();}
// spatial grid index for hover pick (buckets over the 0..G coordinate space)
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
  const sz=Math.max(1.3,1.1*Math.sqrt(view.s)*3);
  const half=sz/2;
  // draw by type so color batches (fewer fillStyle changes than per-point)
  for(let t=0;t<tl.length;t++){
    if(!on[t])continue;ctx.fillStyle=COLOR[tl[t]]||'#888';ctx.globalAlpha=0.72;
    for(let k=0;k<N;k++){if(DATA.ty[k]!==t)continue;
      const px=view.tx+DATA.x[k]*view.s,py=view.ty+DATA.y[k]*view.s;
      ctx.fillRect(px-half,py-half,sz,sz);}
  }
  ctx.globalAlpha=1;
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
    for(const k of buckets[gy*B+gx]){if(!on[DATA.ty[k]])continue;const dx=DATA.x[k]-wx,dy=DATA.y[k]-wy,d=dx*dx+dy*dy;if(d<bd){bd=d;best=k;}}}
  if(best<0){tip.style.opacity=0;return;}
  const t=DATA.titles[best]||'';
  tip.innerHTML='<b>'+label(best)+'</b>'+(t?'<br><i>'+esc(t)+'</i>':'')+'<br><i>'+tl[DATA.ty[best]].replace('_',' ')+'</i>';
  tip.style.opacity=1;tip.style.left=Math.min(e.clientX+13,innerWidth-tip.offsetWidth-8)+'px';tip.style.top=Math.min(e.clientY+13,innerHeight-tip.offsetHeight-8)+'px';
}
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
document.getElementById('theme').onclick=()=>{const c=document.documentElement.getAttribute('data-theme');
  document.documentElement.setAttribute('data-theme',c==='dark'?'light':c==='light'?'dark':(matchMedia('(prefers-color-scheme:dark)').matches?'light':'dark'));};
// legend with per-type toggle + counts
const counts=tl.map(()=>0);for(let k=0;k<N;k++)counts[DATA.ty[k]]++;
const order=tl.map((_,i)=>i).sort((a,b)=>counts[b]-counts[a]);
document.getElementById('legend').innerHTML='<b>document type · click to filter</b>'+
  order.map(t=>'<label data-t="'+t+'"><i style="background:'+(COLOR[tl[t]]||'#888')+'"></i>'+tl[t].replace('_',' ')+'<span class="ct">'+counts[t].toLocaleString()+'</span></label>').join('');
document.querySelectorAll('.legend label').forEach(l=>l.onclick=()=>{const t=+l.dataset.t;on[t]=!on[t];l.classList.toggle('off',!on[t]);frame();});
addEventListener('resize',()=>{DPR=Math.min(devicePixelRatio||1,2);resize();});
resize();
</script></body></html>
"""


if __name__ == "__main__":
    main()
