#!/usr/bin/env python3
"""Conflict-candidates pilot — an AI-assisted read of 12 ORS chapters (of 245 in the
corpus's shared-authority set — see agency-authority-graph) for candidate inconsistencies
between statutes, implementing OAR rules, and other implementing rules. NOT mechanically
derived, NOT legally reviewed: every candidate here needs human/legal confirmation. See
_meta/catalog/conflict-candidates.yml for the full methodology note.

Reads the cached dataset from build_conflict_candidates_data.py.

  python3 src/build_conflict_candidates.py          # -> viz/conflict-candidates.html
  python3 src/build_conflict_candidates.py --check   # exit 1 if stale (CI)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT

DATA = REPO_ROOT / "_meta/conflict_candidates.json"
OUT = REPO_ROOT / "viz/conflict-candidates.html"


def build_data() -> dict:
    return json.loads(DATA.read_text())


def build_html(data: dict) -> str:
    return TEMPLATE.replace("/*DATA*/", json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def outputs():
    return {OUT: build_html(build_data())}


def main():
    outs = outputs()
    if "--check" in sys.argv:
        stale = [p for p, t in outs.items() if not p.exists() or p.read_text() != t]
        if stale:
            print(f"{OUT.relative_to(REPO_ROOT)} is stale — run: python3 src/build_conflict_candidates.py")
            sys.exit(1)
        print("conflict-candidates.html is current.")
        return
    for p, t in outs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    d = build_data()
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {d['n_chapters']} chapters, {d['n_candidates']} candidates, "
          f"{len(d.get('all_agencies', []))} agencies")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Oregon corpus — conflict-candidates pilot</title>
<style>
  :root{--bg:#f6f7f9;--panel:#fff;--ink:#161a20;--muted:#5a6472;--line:#e4e8ee;--accent:#c2255c;--accent2:#2f6df6;--warn-bg:#fff3f0;--warn-line:#f3c6bb;--shadow:0 1px 3px rgba(20,25,40,.09)}
  @media (prefers-color-scheme:dark){:root{--bg:#0e1116;--panel:#161b22;--ink:#e8ecf2;--muted:#9aa4b2;--line:#232a33;--accent:#e0578a;--accent2:#5a9bff;--warn-bg:#2a1712;--warn-line:#5a3324;--shadow:0 1px 3px rgba(0,0,0,.5)}}
  :root[data-theme=light]{--bg:#f6f7f9;--panel:#fff;--ink:#161a20;--muted:#5a6472;--line:#e4e8ee;--accent:#c2255c;--accent2:#2f6df6;--warn-bg:#fff3f0;--warn-line:#f3c6bb}
  :root[data-theme=dark]{--bg:#0e1116;--panel:#161b22;--ink:#e8ecf2;--muted:#9aa4b2;--line:#232a33;--accent:#e0578a;--accent2:#5a9bff;--warn-bg:#2a1712;--warn-line:#5a3324}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  .wrap{max-width:880px;margin:0 auto;padding:22px 20px 60px}
  h1{margin:0 0 4px;font-size:22px;letter-spacing:-.01em}
  .sub{color:var(--muted);font-size:13.5px;margin-bottom:14px}
  .banner{background:var(--warn-bg);border:1px solid var(--warn-line);border-radius:10px;padding:12px 14px;font-size:13px;line-height:1.5;margin-bottom:18px}
  .banner b{display:block;margin-bottom:3px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin-bottom:10px;box-shadow:var(--shadow);overflow:hidden}
  .head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:13px 16px;cursor:pointer;user-select:none}
  .head:hover{background:color-mix(in srgb, var(--ink) 3%, transparent)}
  .htitle{font-weight:650;font-size:14.5px}
  .htitle small{display:block;font-weight:400;color:var(--muted);font-size:11.5px;margin-top:2px}
  .badge{padding:3px 9px;border-radius:99px;font-size:11.5px;font-weight:650;white-space:nowrap}
  .badge.has{background:color-mix(in srgb, var(--accent) 16%, transparent);color:var(--accent)}
  .badge.clean{background:color-mix(in srgb, #2f9e44 16%, transparent);color:#2f9e44}
  .body{display:none;padding:0 16px 14px;border-top:1px solid var(--line)}
  .card.open .body{display:block}
  .cand{margin-top:14px;padding-top:2px}
  .cand .csum{font-weight:600;font-size:13.5px;margin-bottom:6px}
  blockquote{margin:6px 0;padding:8px 12px;border-left:3px solid var(--accent2);background:color-mix(in srgb, var(--accent2) 6%, transparent);border-radius:0 6px 6px 0;font-size:12.5px;font-style:italic}
  blockquote cite{display:block;font-style:normal;font-weight:650;font-size:11.5px;color:var(--muted);margin-bottom:3px}
  .cnote{font-size:12.5px;color:var(--muted);margin-top:4px}
  .cleannote{font-size:13px;color:var(--muted);padding-top:12px}
  details{margin-top:12px}
  summary{cursor:pointer;font-size:12.5px;color:var(--muted);font-weight:600}
  .artifacts{margin:8px 0 0;padding-left:18px;font-size:12px;color:var(--muted)}
  .artifacts li{margin-bottom:5px}
  #theme{position:fixed;top:14px;right:16px;width:34px;height:34px;border-radius:9px;border:1px solid var(--line);background:var(--panel);color:var(--ink);cursor:pointer;box-shadow:var(--shadow);font-size:15px}
  footer{color:var(--muted);font-size:12px;margin-top:18px;line-height:1.6}
  .filterbar{display:flex;align-items:center;gap:8px;margin:2px 0 16px;flex-wrap:wrap}
  .filterbar label{font-size:12.5px;color:var(--muted);font-weight:600}
  #agencyFilter{font:inherit;font-size:13px;padding:6px 10px;border-radius:8px;border:1px solid var(--line);background:var(--panel);color:var(--ink);max-width:340px}
  #clearFilter{font-size:12px;color:var(--accent2);background:none;border:none;cursor:pointer;padding:0;display:none}
  .card.hidden{display:none}
  .agchip{display:inline-block;font-size:11px;font-weight:600;color:var(--muted);background:color-mix(in srgb, var(--ink) 6%, transparent);border-radius:99px;padding:2px 8px;margin:0 4px 4px 0}
</style></head>
<body>
<button id="theme" title="Toggle theme">◑</button>
<div class="wrap">
  <h1 id="h1"></h1>
  <div class="sub" id="sub"></div>
  <div class="banner">
    <b>Every item below is a CANDIDATE for human/legal review — none is a confirmed conflict.</b>
    Produced by an LLM reading each chapter's full statute + implementing-rule text in one pass. Every
    candidate carries the exact document citations and quoted text it's based on, so you can verify
    it yourself. This is a pilot over a subset of 245 shared-authority chapters, not an exhaustive scan.
  </div>
  <div class="filterbar">
    <label for="agencyFilter">Filter by agency</label>
    <select id="agencyFilter"><option value="">All agencies</option></select>
    <button id="clearFilter">clear</button>
    <span class="sub" id="filterCount" style="margin:0"></span>
  </div>
  <div id="list"></div>
  <footer id="foot"></footer>
</div>
<script>
const DATA=/*DATA*/;
document.getElementById('h1').textContent=`What does ${DATA.n_chapters} ORS chapters' worth of cross-referencing actually hold together?`;
document.getElementById('sub').textContent=`${DATA.n_chapters} chapters piloted · ${DATA.n_candidates} candidates · ${DATA.n_clean_chapters} chapters with none found · ${DATA.n_docs_verified} citations verified against the corpus graph · non-authoritative`;
document.getElementById('foot').innerHTML = esc(DATA.note) + '<br><br><b>Methodology:</b> ' + esc(DATA.methodology);

const sel=document.getElementById('agencyFilter');
for(const a of (DATA.all_agencies||[])){
  const opt=document.createElement('option');
  opt.value=a.slug; opt.textContent=`${a.name} (${a.chapters})`;
  sel.appendChild(opt);
}

const list=document.getElementById('list');
const rows=DATA.chapters.slice().sort((a,b)=>(b.candidates||[]).length-(a.candidates||[]).length);
const cards=[];
for(const ch of rows){
  const n=(ch.candidates||[]).length;
  const el=document.createElement('div');el.className='card';
  const badge = n>0 ? `<span class="badge has">${n} candidate${n===1?'':'s'}</span>` : `<span class="badge clean">none found</span>`;
  const agList = ch.agency_list||[];
  const agChips = agList.map(a=>`<span class="agchip">${esc(a.name)}</span>`).join('');
  el.innerHTML = `<div class="head">
      <div class="htitle">ORS chapter ${esc(ch.ors_chapter)}<small>${ch.agencies} agencies · ${ch.rules_reviewed} rules reviewed</small></div>
      ${badge}
    </div><div class="body"></div>`;
  const bodyEl = el.querySelector('.body');
  if(agChips){
    const agDiv=document.createElement('div');agDiv.style.marginTop='12px';agDiv.innerHTML=agChips;
    bodyEl.appendChild(agDiv);
  }
  if(n>0){
    for(const c of ch.candidates){
      const cand=document.createElement('div');cand.className='cand';
      const quotes=c.documents.map(d=>`<blockquote><cite>${esc(d.citation)}${d.not_found?' — NOT FOUND in corpus':''}</cite>${esc(d.quote)}</blockquote>`).join('');
      cand.innerHTML = `<div class="csum">${esc(c.summary)}</div>${quotes}<div class="cnote">${esc(c.note||'')}</div>`;
      bodyEl.appendChild(cand);
    }
  } else if(ch.note){
    const p=document.createElement('div');p.className='cleannote';p.textContent=ch.note;
    bodyEl.appendChild(p);
  }
  if(ch.artifacts && ch.artifacts.length){
    const det=document.createElement('details');
    det.innerHTML = `<summary>${ch.artifacts.length} citation-metadata artifact${ch.artifacts.length===1?'':'s'} noticed (data-quality, not legal)</summary>
      <ul class="artifacts">${ch.artifacts.map(a=>`<li>${esc(a)}</li>`).join('')}</ul>`;
    bodyEl.appendChild(det);
  }
  el.querySelector('.head').addEventListener('click',()=>el.classList.toggle('open'));
  list.appendChild(el);
  cards.push({el, slugs: new Set(agList.map(a=>a.slug))});
}
if(rows.length) list.firstChild.classList.add('open');

function applyFilter(){
  const slug = sel.value;
  document.getElementById('clearFilter').style.display = slug ? 'inline' : 'none';
  let shown = 0;
  for(const {el, slugs} of cards){
    const match = !slug || slugs.has(slug);
    el.classList.toggle('hidden', !match);
    if(match) shown++;
  }
  document.getElementById('filterCount').textContent = slug ? `showing ${shown} of ${cards.length} chapters` : '';
}
sel.addEventListener('change', applyFilter);
document.getElementById('clearFilter').addEventListener('click', ()=>{sel.value=''; applyFilter();});

function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
document.getElementById('theme').onclick=()=>{const c=document.documentElement.getAttribute('data-theme');
  document.documentElement.setAttribute('data-theme',c==='dark'?'light':c==='light'?'dark':(matchMedia('(prefers-color-scheme:dark)').matches?'light':'dark'));};
</script></body></html>
"""


if __name__ == "__main__":
    main()
