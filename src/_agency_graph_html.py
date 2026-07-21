"""HTML template for src/build_agency_graph.py — kept separate so the generator stays
readable. `/*DATA*/` is replaced with the inlined JSON payload at build time. The page is
fully self-contained (no external requests): a vanilla-JS canvas force-directed layout
that projects the agency<->agency edges in-browser, so the rollup / ubiquity / density
controls work with no server."""

HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Oregon agencies — shared statutory authority</title>
<style>
  :root{
    --bg:#f7f8fa; --panel:#ffffff; --ink:#1a1d23; --muted:#5b6472; --line:#e2e6ec;
    --edge:rgba(90,100,120,.28); --edge-hi:#c8202f; --shadow:0 1px 3px rgba(20,25,40,.12),0 6px 24px rgba(20,25,40,.10);
    --accent:#2f6df6;
  }
  @media (prefers-color-scheme:dark){
    :root{--bg:#0f1216; --panel:#171b21; --ink:#e8ecf2; --muted:#9aa4b2; --line:#262c35;
      --edge:rgba(150,165,190,.22); --edge-hi:#ff5a67; --shadow:0 1px 3px rgba(0,0,0,.5),0 8px 30px rgba(0,0,0,.45);}
  }
  :root[data-theme="light"]{--bg:#f7f8fa;--panel:#fff;--ink:#1a1d23;--muted:#5b6472;--line:#e2e6ec;--edge:rgba(90,100,120,.28);--edge-hi:#c8202f;}
  :root[data-theme="dark"]{--bg:#0f1216;--panel:#171b21;--ink:#e8ecf2;--muted:#9aa4b2;--line:#262c35;--edge:rgba(150,165,190,.22);--edge-hi:#ff5a67;}
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;overflow:hidden;background:var(--bg);color:var(--ink);
    font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  #wrap{position:fixed;inset:0}
  canvas{display:block;width:100%;height:100%;cursor:grab}
  canvas.drag{cursor:grabbing}
  .panel{position:absolute;background:var(--panel);border:1px solid var(--line);
    border-radius:12px;box-shadow:var(--shadow)}
  #controls{top:14px;left:14px;padding:14px 16px;width:284px;max-height:calc(100% - 28px);overflow:auto}
  #controls h1{font-size:15px;margin:0 0 2px;letter-spacing:-.01em}
  #controls .sub{color:var(--muted);font-size:12px;margin:0 0 12px}
  .row{margin:11px 0}
  .row label{display:flex;justify-content:space-between;font-size:12px;color:var(--muted);margin-bottom:5px}
  .row .val{color:var(--ink);font-variant-numeric:tabular-nums}
  input[type=range]{width:100%;accent-color:var(--accent)}
  .toggle{display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer;user-select:none;margin:8px 0}
  .toggle input{accent-color:var(--accent);width:15px;height:15px}
  #search{width:100%;padding:7px 9px;border:1px solid var(--line);border-radius:8px;
    background:var(--bg);color:var(--ink);font-size:13px}
  #stat{font-size:11px;color:var(--muted);margin-top:8px;font-variant-numeric:tabular-nums}
  #legend{bottom:14px;left:14px;padding:11px 13px;max-width:290px;max-height:42%;overflow:auto}
  #legend h2{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 8px}
  .lg{display:flex;align-items:center;gap:7px;font-size:12px;margin:4px 0;cursor:pointer}
  .sw{width:11px;height:11px;border-radius:3px;flex:0 0 auto}
  #tip{position:absolute;pointer-events:none;background:var(--panel);border:1px solid var(--line);
    border-radius:10px;box-shadow:var(--shadow);padding:10px 12px;max-width:290px;font-size:12.5px;
    opacity:0;transition:opacity .09s;z-index:5}
  #tip b{font-size:13px}
  #tip .g{color:var(--muted)}
  #tip .par{margin-top:6px;font-size:11.5px;color:var(--muted)}
  #tip .par span{color:var(--ink)}
  .hint{position:absolute;bottom:14px;right:16px;font-size:11px;color:var(--muted);text-align:right;
    background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:6px 10px;box-shadow:var(--shadow)}
  #theme{position:absolute;top:14px;right:14px;width:34px;height:34px;border-radius:9px;border:1px solid var(--line);
    background:var(--panel);color:var(--ink);cursor:pointer;box-shadow:var(--shadow);font-size:15px}
  .disc{margin-top:10px;font-size:10.5px;color:var(--muted);border-top:1px solid var(--line);padding-top:8px}
</style>
</head>
<body>
<div id="wrap">
  <canvas id="cv"></canvas>
  <button id="theme" title="Toggle light/dark">◑</button>
  <div id="controls" class="panel">
    <h1>Oregon agencies: shared legal turf</h1>
    <p class="sub">Two agencies are linked when their administrative rules (OAR) implement the
      same statutes (ORS). Thicker link = more shared, specialized statutory domains.</p>
    <input id="search" placeholder="Find an agency…" autocomplete="off">
    <div class="row">
      <label>Link density <span class="val" id="densv"></span></label>
      <input type="range" id="dens" min="0" max="100" value="62">
    </div>
    <label class="toggle"><input type="checkbox" id="ubiq"> Include ubiquitous statutes (APA, public records…)</label>
    <label class="toggle"><input type="checkbox" id="roll"> Roll sub-units into parent department</label>
    <div id="stat"></div>
    <p class="disc">Non-authoritative; derived mechanically from the corpus authority graph.
      Node size = number of rules. Color = parent department.</p>
  </div>
  <div id="legend" class="panel"><h2>Departments (click to focus)</h2><div id="lgbody"></div></div>
  <div id="tip"></div>
  <div class="hint">drag to pan · scroll to zoom · click a node to isolate it · drag a node to pin</div>
</div>
<script>
const DATA = /*DATA*/;
const cv = document.getElementById('cv'), ctx = cv.getContext('2d');
const tip = document.getElementById('tip');
// ---- palette (categorical, readable on light & dark) ----
const PALETTE = ['#2f6df6','#e8590c','#2f9e44','#ae3ec9','#e03131','#1098ad','#f08c00',
  '#4263eb','#c2255c','#5c940d','#7048e8','#0c8599','#d6336c','#495057'];
const NEUTRAL = getComputedStyle(document.documentElement).getPropertyValue('--muted').trim() || '#888';
const groupColor = {};
DATA.colored_groups.forEach((g,i)=> groupColor[g.slug] = PALETTE[i % PALETTE.length]);
function colorOf(a){ return groupColor[a.group] || '#8a94a6'; }

// ---- state ----
let W=0,H=0,DPR=Math.min(2,window.devicePixelRatio||1);
let view={x:0,y:0,k:1};
let nodes=[], links=[], byId={};
let hover=null, selected=null, dragNode=null, panning=false, last=null;

function resize(){
  const w = cv.clientWidth || window.innerWidth, h = cv.clientHeight || window.innerHeight;
  if(!w || !h) return;
  const first = (W===0);
  W=w; H=h; cv.width=W*DPR; cv.height=H*DPR;
  if(first && nodes.length){                 // canvas got real size after nodes existed
    const cx=W/2, cy=H/2, rad=Math.min(W,H)*0.32;
    nodes.forEach((n,i)=>{ const a=i/nodes.length*6.2832;
      n.x=cx+Math.cos(a)*rad; n.y=cy+Math.sin(a)*rad; n.vx=n.vy=0; });
    T=0.9;
  }
}
window.addEventListener('resize',resize);
if(window.ResizeObserver) new ResizeObserver(resize).observe(cv);

// ---- build node set (respecting rollup) ----
function buildNodes(){
  const roll = document.getElementById('roll').checked;
  const prev = {}; nodes.forEach(n=>prev[n.id]={x:n.x,y:n.y});
  let items;
  if(!roll){
    items = DATA.agencies.map(a=>({id:a.slug,name:a.name,rules:a.rules,group:a.group,
      groupName:a.group_name,gov:a.governance,chapters:a.chapters}));
  } else {
    const g={};
    DATA.agencies.forEach(a=>{
      const key=a.group;
      if(!g[key]) g[key]={id:key,name:a.group_name,rules:0,group:key,groupName:a.group_name,
        gov:a.governance,chapters:new Set(),units:0};
      a.chapters.forEach(c=>g[key].chapters.add(c));
      g[key].rules+=a.rules; g[key].units++;
    });
    items=Object.values(g).map(o=>({...o,chapters:[...o.chapters].sort()}));
  }
  const cx=W/2,cy=H/2;
  nodes=items.map((o,i)=>{
    const p=prev[o.id];
    const ang=i/items.length*Math.PI*2;
    return {...o, x:p?p.x:cx+Math.cos(ang)*220+(Math.random()-.5)*40,
                  y:p?p.y:cy+Math.sin(ang)*220+(Math.random()-.5)*40,
                  vx:0,vy:0, r:4+Math.sqrt(o.rules)*1.15, chSet:new Set(o.chapters)};
  });
  nodes.forEach(n=>n.r=Math.min(n.r,26));
  byId={}; nodes.forEach(n=>byId[n.id]=n);
}

// ---- project weighted edges from shared ORS chapters ----
function projectEdges(){
  const includeUbiq = document.getElementById('ubiq').checked;
  const pop = DATA.chapter_pop, UB = DATA.ubiquity_default;
  const wOf = c => 1/Math.log((pop[c]||1) + Math.E);
  const all=[]; const strongest={};
  for(let i=0;i<nodes.length;i++){
    for(let j=i+1;j<nodes.length;j++){
      const A=nodes[i], B=nodes[j];
      let w=0, shared=0;
      const small = A.chSet.size<B.chSet.size ? A.chSet : B.chSet;
      const big   = A.chSet.size<B.chSet.size ? B.chSet : A.chSet;
      small.forEach(c=>{ if(big.has(c)){ if(!includeUbiq && (pop[c]||0)>=UB) return; w+=wOf(c); shared++; } });
      if(shared>0){
        const e={a:A,b:B,w,shared};
        all.push(e);
        if(!strongest[A.id]||strongest[A.id].w<w) strongest[A.id]=e;
        if(!strongest[B.id]||strongest[B.id].w<w) strongest[B.id]=e;
      }
    }
  }
  all.sort((p,q)=>q.w-p.w);
  const maxW = all.length?all[0].w:1;
  // density slider -> min-weight cutoff; always keep each node's single strongest link
  const dens = +document.getElementById('dens').value;      // 0..100
  const cutoff = maxW * Math.pow(1 - dens/100, 1.6);
  const keep=new Set(); Object.values(strongest).forEach(e=>keep.add(e));
  links = all.filter(e=> e.w>=cutoff || keep.has(e));
  window._maxW=maxW;
  document.getElementById('stat').textContent =
    `${nodes.length} agencies · ${links.length} links shown (of ${all.length})`;
  document.getElementById('densv').textContent = links.length+' links';
}

function relayout(){ buildNodes(); projectEdges(); buildLegend(); T=0.9; }
function reproject(){ projectEdges(); T=Math.max(T,0.4); }

// ---- force simulation ----
let T=0.9;
function step(){
  const rep = 6800, cx=W/2, cy=H/2;
  for(const n of nodes){ n.vx*=0.86; n.vy*=0.86; }
  for(let i=0;i<nodes.length;i++){
    const a=nodes[i];
    for(let j=i+1;j<nodes.length;j++){
      const b=nodes[j];
      let dx=a.x-b.x, dy=a.y-b.y, d2=dx*dx+dy*dy+0.01;
      let d=Math.sqrt(d2); if(d>360) continue;
      const f=rep/d2;
      const fx=dx/d*f, fy=dy/d*f;
      a.vx+=fx; a.vy+=fy; b.vx-=fx; b.vy-=fy;
    }
  }
  for(const e of links){
    const a=e.a,b=e.b; let dx=b.x-a.x, dy=b.y-a.y, d=Math.hypot(dx,dy)+.01;
    const ideal=70;
    const f=(d-ideal)*0.015*(0.5+Math.min(e.w,3));
    const fx=dx/d*f, fy=dy/d*f;
    a.vx+=fx; a.vy+=fy; b.vx-=fx; b.vy-=fy;
  }
  for(const n of nodes){
    n.vx += (cx-n.x)*0.006; n.vy += (cy-n.y)*0.006;   // gravity to center
    if(n===dragNode) continue;
    n.x += n.vx*T; n.y += n.vy*T;
  }
  if(T>0.05) T*=0.992;
}

// ---- render ----
function toScreen(x,y){ return [ (x-view.x)*view.k, (y-view.y)*view.k ]; }
function draw(){
  ctx.setTransform(DPR,0,0,DPR,0,0);
  ctx.clearRect(0,0,W,H);
  const egoSet = selected ? new Set([selected.id]) : null;
  if(selected){ for(const e of links){ if(e.a===selected)egoSet.add(e.b.id); if(e.b===selected)egoSet.add(e.a.id);} }
  // edges
  ctx.lineCap='round';
  for(const e of links){
    const [x1,y1]=toScreen(e.a.x,e.a.y), [x2,y2]=toScreen(e.b.x,e.b.y);
    const hi = selected && (e.a===selected||e.b===selected);
    const dim = (selected && !hi) || (hover && e.a!==hover && e.b!==hover && !hi);
    ctx.strokeStyle = hi ? getVar('--edge-hi') : getVar('--edge');
    ctx.globalAlpha = hi?0.85 : dim?0.05:1;
    ctx.lineWidth = Math.max(.5, Math.min(4, e.w*0.9)) * (hi?1.5:1);
    ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke();
  }
  ctx.globalAlpha=1;
  // nodes
  for(const n of nodes){
    const [x,y]=toScreen(n.x,n.y); const r=n.r*Math.sqrt(view.k);
    const faded = (egoSet && !egoSet.has(n.id)) || (hover && hover!==n && !(egoSet&&egoSet.has(n.id)));
    ctx.globalAlpha = faded?0.22:1;
    ctx.beginPath(); ctx.arc(x,y,r,0,7); ctx.fillStyle=colorOf(n); ctx.fill();
    if(n===hover||n===selected){ ctx.lineWidth=2; ctx.strokeStyle=getVar('--ink'); ctx.stroke(); }
    else { ctx.lineWidth=1; ctx.strokeStyle='rgba(255,255,255,.55)'; ctx.stroke(); }
  }
  ctx.globalAlpha=1;
  // labels for big / focused nodes
  ctx.fillStyle=getVar('--ink'); ctx.font='600 11px system-ui'; ctx.textAlign='center';
  for(const n of nodes){
    const show = n===hover||n===selected||(egoSet&&egoSet.has(n.id))|| (n.rules>1200 && view.k>0.7);
    if(!show) continue;
    const [x,y]=toScreen(n.x,n.y);
    const label = n.name.length>34?n.name.slice(0,32)+'…':n.name;
    ctx.globalAlpha=(egoSet&&!egoSet.has(n.id))?0.3:1;
    ctx.fillText(label, x, y - n.r*Math.sqrt(view.k) - 5);
  }
  ctx.globalAlpha=1;
}
function getVar(v){ return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }

function frame(){ step(); draw(); requestAnimationFrame(frame); }

// ---- interaction ----
function nodeAt(mx,my){
  let best=null,bd=1e9;
  for(const n of nodes){ const [x,y]=toScreen(n.x,n.y); const r=n.r*Math.sqrt(view.k)+4;
    const d=Math.hypot(mx-x,my-y); if(d<r && d<bd){bd=d;best=n;} }
  return best;
}
cv.addEventListener('mousemove',ev=>{
  const mx=ev.offsetX,my=ev.offsetY;
  if(dragNode){ dragNode.x=mx/view.k+view.x; dragNode.y=my/view.k+view.y; dragNode.vx=dragNode.vy=0; T=Math.max(T,0.3); return; }
  if(panning){ view.x-=(mx-last[0])/view.k; view.y-=(my-last[1])/view.k; last=[mx,my]; return; }
  hover=nodeAt(mx,my);
  cv.style.cursor = hover?'pointer':'grab';
  if(hover){ showTip(hover,ev.clientX,ev.clientY); } else tip.style.opacity=0;
});
function showTip(n,cx,cy){
  const part = n.units?`<div class="par">rolled-up department · <span>${n.units}</span> units</div>`:'';
  const partners = topPartners(n);
  tip.innerHTML = `<b>${esc(n.name)}</b><br><span class="g">${n.rules.toLocaleString()} rules ·
    ${n.chapters.length} ORS chapters · ${esc(n.gov.replace(/_/g,' '))}</span>${part}
    ${partners?`<div class="par">shares most with: <span>${partners}</span></div>`:''}`;
  tip.style.opacity=1;
  const w=tip.offsetWidth,h=tip.offsetHeight;
  tip.style.left=Math.min(cx+14,innerWidth-w-8)+'px';
  tip.style.top=Math.min(cy+14,innerHeight-h-8)+'px';
}
function topPartners(n){
  const es=links.filter(e=>e.a===n||e.b===n).sort((p,q)=>q.w-p.w).slice(0,3);
  return es.map(e=>esc((e.a===n?e.b:e.a).name.replace(/^(Department of the |Department of |Oregon )/,''))).join(', ');
}
cv.addEventListener('mousedown',ev=>{
  const n=nodeAt(ev.offsetX,ev.offsetY);
  if(n){ dragNode=n; cv.classList.add('drag'); } else { panning=true; last=[ev.offsetX,ev.offsetY]; }
});
window.addEventListener('mouseup',ev=>{
  if(dragNode && Math.abs(ev.offsetX)>=0){ /* keep pinned briefly */ }
  dragNode=null; panning=false; cv.classList.remove('drag');
});
cv.addEventListener('click',ev=>{
  const n=nodeAt(ev.offsetX,ev.offsetY);
  selected = (n && n!==selected) ? n : null;
});
cv.addEventListener('wheel',ev=>{
  ev.preventDefault();
  const mx=ev.offsetX,my=ev.offsetY;
  const wx=mx/view.k+view.x, wy=my/view.k+view.y;
  const f=Math.exp(-ev.deltaY*0.0012); view.k=Math.max(0.25,Math.min(4,view.k*f));
  view.x=wx-mx/view.k; view.y=wy-my/view.k;
},{passive:false});

// ---- controls ----
document.getElementById('dens').addEventListener('input',reproject);
document.getElementById('ubiq').addEventListener('change',reproject);
document.getElementById('roll').addEventListener('change',relayout);
document.getElementById('search').addEventListener('input',e=>{
  const q=e.target.value.toLowerCase().trim(); if(!q){selected=null;return;}
  const hit=nodes.find(n=>n.name.toLowerCase().includes(q));
  if(hit){ selected=hit; view.k=1.1; view.x=hit.x-W/2/view.k; view.y=hit.y-H/2/view.k; }
});
function buildLegend(){
  const b=document.getElementById('lgbody'); b.innerHTML='';
  DATA.colored_groups.forEach((g,i)=>{
    const el=document.createElement('div'); el.className='lg';
    el.innerHTML=`<span class="sw" style="background:${PALETTE[i%PALETTE.length]}"></span>${esc(g.name)} <span style="color:var(--muted)">(${g.members})</span>`;
    el.onclick=()=>{ const hit=nodes.find(n=>n.group===g.slug||n.id===g.slug); if(hit)selected=hit; };
    b.appendChild(el);
  });
  const el=document.createElement('div'); el.className='lg';
  el.innerHTML=`<span class="sw" style="background:#8a94a6"></span><span style="color:var(--muted)">standalone agency</span>`;
  b.appendChild(el);
}
document.getElementById('theme').onclick=()=>{
  const cur=document.documentElement.getAttribute('data-theme');
  const next = cur==='dark'?'light':cur==='light'?'dark':(matchMedia('(prefers-color-scheme:dark)').matches?'light':'dark');
  document.documentElement.setAttribute('data-theme',next);
};
function esc(s){ return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

// ---- go ----
resize(); relayout(); frame();
// settle initial layout faster (only if we already have real dimensions)
if(W>0){ for(let i=0;i<220;i++) step(); }
</script>
</body>
</html>
"""
