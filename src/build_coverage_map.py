#!/usr/bin/env python3
"""Corpus coverage map — a treemap of the whole corpus: body → agency → doc_type, sized
by document count, colored by body. Shows what the corpus holds and where the mass is
(and, by their absence, which agencies have no policies yet).

  python3 src/build_coverage_map.py            # -> viz/corpus-coverage.html
  python3 src/build_coverage_map.py --check    # exit 1 if stale (CI)

Self-contained (data inlined, no external assets); a small squarified-treemap renderer.
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
OUT = REPO_ROOT / "viz/corpus-coverage.html"


def build_data() -> dict:
    g = json.loads(GRAPH.read_text())
    reg = load_registry_by_chapter()
    orgs = {o["slug"]: o for o in
            yaml.safe_load((REPO_ROOT / "_meta/catalog/agencies.yml").read_text())["organizations"]}

    def org_name(slug):
        return orgs.get(slug, {}).get("name", slug)

    rules_by_ag, policy_by_ag, std_by_ag = Counter(), Counter(), Counter()
    n_stat = n_eo = 0
    for n in g["nodes"]:
        dt, nid, path = n["doc_type"], n["id"], n["path"]
        if dt == "rule":
            org = reg.get(nid.split("-")[1])
            rules_by_ag[org["slug"] if org else "(unassigned)"] += 1
        elif dt == "statute":
            n_stat += 1
        elif dt == "executive_order":
            n_eo += 1
        elif dt in ("policy", "procedure"):
            policy_by_ag[Path(path).parts[1]] += 1
        elif dt in ("standard", "manual"):
            std_by_ag[Path(path).parts[1]] += 1

    def children(counter):
        return [{"name": org_name(s), "value": v} for s, v in counter.most_common()]

    root = {"name": "Oregon executive-branch corpus", "children": [
        {"name": "OAR rules", "key": "rule", "children": children(rules_by_ag)},
        {"name": "ORS statutes", "key": "statute", "value": n_stat},
        {"name": "Executive orders", "key": "executive_order", "value": n_eo},
        {"name": "Agency policies", "key": "policy", "children": children(policy_by_ag)},
        {"name": "Standards & manuals", "key": "standard", "children": children(std_by_ag)},
    ]}
    total = sum(c.get("value", 0) or sum(x["value"] for x in c.get("children", []))
                for c in root["children"])
    return {"root": root, "total": total,
            "policy_agencies": len(policy_by_ag),
            "note": "Document counts from _meta/graph.json. Non-authoritative."}


def build_html(data: dict) -> str:
    return TEMPLATE.replace("/*DATA*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def outputs():
    return {OUT: build_html(build_data())}


def main():
    outs = outputs()
    if "--check" in sys.argv:
        stale = [p for p, t in outs.items() if not p.exists() or p.read_text() != t]
        if stale:
            print(f"{OUT.relative_to(REPO_ROOT)} is stale — run: python3 src/build_coverage_map.py")
            sys.exit(1)
        print("corpus-coverage.html is current.")
        return
    for p, t in outs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    d = build_data()
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {d['total']:,} documents, "
          f"{d['policy_agencies']} agencies with policies")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Oregon corpus — coverage map</title>
<style>
  :root{--bg:#f6f7f9;--panel:#fff;--ink:#161a20;--muted:#5a6472;--line:#e4e8ee;--shadow:0 1px 3px rgba(20,25,40,.1),0 8px 30px rgba(20,25,40,.08)}
  @media (prefers-color-scheme:dark){:root{--bg:#0e1116;--panel:#161b22;--ink:#e8ecf2;--muted:#9aa4b2;--line:#232a33;--shadow:0 1px 3px rgba(0,0,0,.5)}}
  :root[data-theme=light]{--bg:#f6f7f9;--panel:#fff;--ink:#161a20;--muted:#5a6472;--line:#e4e8ee}
  :root[data-theme=dark]{--bg:#0e1116;--panel:#161b22;--ink:#e8ecf2;--muted:#9aa4b2;--line:#232a33}
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  #wrap{position:fixed;inset:0;display:flex;flex-direction:column}
  header{padding:16px 20px 10px}
  h1{margin:0;font-size:19px;letter-spacing:-.01em}
  .sub{color:var(--muted);font-size:13px;margin-top:3px}
  #cvwrap{flex:1;position:relative;margin:6px 14px 14px}
  canvas{position:absolute;inset:0;width:100%;height:100%;border-radius:12px;cursor:crosshair}
  #legend{display:flex;flex-wrap:wrap;gap:14px;padding:2px 20px 10px;font-size:12px;color:var(--muted)}
  .lg{display:flex;align-items:center;gap:6px}.sw{width:11px;height:11px;border-radius:3px}
  #tip{position:absolute;pointer-events:none;background:var(--panel);border:1px solid var(--line);border-radius:9px;box-shadow:var(--shadow);padding:8px 11px;font-size:12.5px;opacity:0;transition:opacity .08s;z-index:5;max-width:260px}
  #tip b{font-size:13px}#tip .g{color:var(--muted)}
  #theme{position:absolute;top:14px;right:16px;width:34px;height:34px;border-radius:9px;border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer;box-shadow:var(--shadow);font-size:15px;z-index:6}
</style></head>
<body><div id="wrap">
  <button id="theme" title="Toggle theme">◑</button>
  <header><h1>Oregon executive-branch corpus — coverage</h1>
    <div class="sub" id="sub"></div></header>
  <div id="legend"></div>
  <div id="cvwrap"><canvas id="cv"></canvas></div>
  <div id="tip"></div>
</div>
<script>
const DATA=/*DATA*/;
const PAL={rule:'#2f6df6',statute:'#2f9e44',executive_order:'#ae3ec9',policy:'#e8590c',standard:'#0c8599'};
const LABELS={rule:'OAR rules',statute:'ORS statutes',executive_order:'Executive orders',policy:'Agency policies',standard:'Standards & manuals'};
const cv=document.getElementById('cv'),ctx=cv.getContext('2d'),tip=document.getElementById('tip');
let DPR=Math.min(2,devicePixelRatio||1),W,H,rects=[];
document.getElementById('sub').textContent=DATA.total.toLocaleString()+' documents · '+DATA.policy_agencies+' agencies with policies ingested · non-authoritative';
document.getElementById('legend').innerHTML=Object.keys(PAL).map(k=>`<span class="lg"><span class="sw" style="background:${PAL[k]}"></span>${LABELS[k]}</span>`).join('');

function val(n){return n.value||(n.children?n.children.reduce((s,c)=>s+val(c),0):0);}
// --- correct squarified treemap (Bruls, Huizing, van Wijk) ---
function worst(areas,side){let s=areas.reduce((a,b)=>a+b,0),mx=Math.max(...areas),mn=Math.min(...areas);
  return Math.max(side*side*mx/(s*s),s*s/(side*side*mn));}
function squarify(items,x,y,w,h){ // items:[{area,ref}] -> [{x,y,w,h,ref}]
  const res=[];items=items.slice().sort((a,b)=>b.area-a.area);let i=0;
  while(i<items.length){
    const side=Math.min(w,h);let row=[items[i]],j=i+1;
    while(j<items.length){
      const cur=worst(row.map(r=>r.area),side),nxt=worst(row.concat(items[j]).map(r=>r.area),side);
      if(nxt>cur)break;row.push(items[j]);j++;}
    const rowArea=row.reduce((s,r)=>s+r.area,0);
    if(w>=h){const cw=rowArea/h;let oy=y;for(const it of row){const ih=it.area/cw;res.push({x,y:oy,w:cw,h:ih,ref:it.ref});oy+=ih;}x+=cw;w-=cw;}
    else{const rh=rowArea/w;let ox=x;for(const it of row){const iw=it.area/rh;res.push({x:ox,y,w:iw,h:rh,ref:it.ref});ox+=iw;}y+=rh;h-=rh;}
    i=j;}
  return res;
}
function treemap(children,x,y,w,h,depth,out,pkey){
  const tot=children.reduce((s,c)=>s+val(c),0);if(tot<=0||w<=0||h<=0)return;
  const scale=(w*h)/tot;
  const items=children.map(c=>({area:Math.max(val(c)*scale,0),ref:c}));
  for(const r of squarify(items,x,y,w,h)){
    const c=r.ref,key=c.key||pkey;
    if(c.children&&depth<1){
      out.push({x:r.x,y:r.y,w:r.w,h:r.h,name:c.name,key,value:val(c),group:true});
      treemap(c.children,r.x+2,r.y+17,Math.max(0,r.w-4),Math.max(0,r.h-19),depth+1,out,key);
    }else out.push({x:r.x,y:r.y,w:r.w,h:r.h,name:c.name,key,value:val(c),group:false});
  }
}
function resize(){W=cv.clientWidth||innerWidth;H=cv.clientHeight||innerHeight;cv.width=W*DPR;cv.height=H*DPR;layout();draw();}
function layout(){rects=[];treemap(DATA.root.children,0,0,W,H,0,rects,null);}
function draw(){
  ctx.setTransform(DPR,0,0,DPR,0,0);ctx.clearRect(0,0,W,H);
  for(const r of rects){if(r.group)continue;
    ctx.fillStyle=PAL[r.key]||'#888';ctx.globalAlpha=.86;
    rr(r.x,r.y,r.w,r.h,4);ctx.fill();ctx.globalAlpha=1;
    ctx.strokeStyle=getBg();ctx.lineWidth=1.5;rr(r.x,r.y,r.w,r.h,4);ctx.stroke();
    if(r.w>62&&r.h>26){ctx.fillStyle='#fff';ctx.font='600 12px system-ui';ctx.textBaseline='top';
      const nm=r.name.replace(/^(Department|Oregon) /,'');
      clip(r,()=>{ctx.fillText(nm,r.x+7,r.y+6);ctx.globalAlpha=.85;ctx.font='11px system-ui';ctx.fillText(r.value.toLocaleString(),r.x+7,r.y+21);ctx.globalAlpha=1;});
    }
  }
  // group (top body) outlines + header labels
  for(const r of rects){if(!r.group)continue;
    ctx.strokeStyle=PAL[r.key]||'#888';ctx.globalAlpha=.9;ctx.lineWidth=2;rr(r.x,r.y,r.w,r.h,5);ctx.stroke();ctx.globalAlpha=1;
    if(r.w>90){ctx.fillStyle=PAL[r.key]||'#888';ctx.font='700 12px system-ui';ctx.textBaseline='top';
      clip({x:r.x,y:r.y,w:r.w,h:16},()=>ctx.fillText(`${r.name} · ${r.value.toLocaleString()}`,r.x+6,r.y+3));}}
}
function clip(r,fn){ctx.save();ctx.beginPath();ctx.rect(r.x,r.y,r.w,r.h);ctx.clip();fn();ctx.restore();}
function rr(x,y,w,h,r){r=Math.min(r,w/2,h/2);ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath();}
function getBg(){return getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();}
cv.addEventListener('mousemove',e=>{const mx=e.offsetX,my=e.offsetY;
  const hit=[...rects].reverse().find(r=>!r.group&&mx>=r.x&&mx<=r.x+r.w&&my>=r.y&&my<=r.y+r.h);
  if(hit){tip.innerHTML=`<b>${hit.name}</b><br><span class="g">${LABELS[hit.key]} · ${hit.value.toLocaleString()} documents (${(hit.value/DATA.total*100).toFixed(1)}%)</span>`;
    tip.style.opacity=1;tip.style.left=Math.min(e.clientX+13,innerWidth-tip.offsetWidth-8)+'px';tip.style.top=Math.min(e.clientY+13,innerHeight-tip.offsetHeight-8)+'px';}
  else tip.style.opacity=0;});
document.getElementById('theme').onclick=()=>{const c=document.documentElement.getAttribute('data-theme');
  document.documentElement.setAttribute('data-theme',c==='dark'?'light':c==='light'?'dark':(matchMedia('(prefers-color-scheme:dark)').matches?'light':'dark'));draw();};
addEventListener('resize',resize);resize();
</script></body></html>
"""


if __name__ == "__main__":
    main()
