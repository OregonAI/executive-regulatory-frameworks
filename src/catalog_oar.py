#!/usr/bin/env python3
"""Populate _meta/catalog/oar.yml with every chapter's division/rule inventory
(Gate #1 input for the mass OAR import: run this, review the printed summary,
THEN run ingest_oar.py on approved chapters). Idempotent and resumable — the
catalog is written after every chapter, and already-discovered chapters are
skipped unless --redo is given.

  python3 src/catalog_oar.py --discover            # all registry chapters
  python3 src/catalog_oar.py --discover 137 150    # specific chapters
  python3 src/catalog_oar.py --summary             # counts only, no network

Discovery source: oregon.public.law chapter/division pages (static HTML — the
official OARD chapter listings render via JavaScript and return empty shells to
plain fetches). Discovery only: rule CONTENT is always fetched from the official
OARD per-rule URL by ingest_oar.py, never from the mirror. Chapter titles come
from the agency registry (_meta/catalog/agencies.yml, same upstream); division
titles from the chapter page; rule numbers from each division page's links.
Existing per-rule statuses (ingested/renumbered/not_served/...) are preserved on
merge — discovery never un-ingests anything."""
import re
import sys
import time
import urllib.request
from datetime import date
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml

from repo_lib import REPO_ROOT

BASE = "https://oregon.public.law"
CATALOG = REPO_ROOT / "_meta/catalog/oar.yml"
REGISTRY = REPO_ROOT / "_meta/catalog/agencies.yml"
UA = "oregon-policy-repo (+https://github.com/morficflux/oregon-policy-repo)"
TODAY = date.today().isoformat()

DIV_LINK_RE = re.compile(
    r'<a href="oar_chapter_(\d+)_division_(\d+[A-Za-z]?)">'
    r'<div class="number">[^<]*</div><div class="name">\s*(.*?)\s*</div>', re.S)
RULE_LINK_RE = re.compile(r'href="oar_(\d{3}-\d{3}-\d{4})"')


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def load_catalog():
    if CATALOG.exists():
        return yaml.safe_load(CATALOG.read_text())
    return {"note": "", "chapters": []}


def save_catalog(cat, discovered_note=True):
    cat["note"] = (
        "Discovery map of ALL OAR chapters (Gate #1 input for the mass import): every "
        "chapter's divisions and rule numbers, discovered from oregon.public.law "
        "chapter/division pages (static HTML; the official OARD listings are "
        "JS-rendered). Rule CONTENT always comes from the official OARD per-rule URL "
        "at ingest time, never from the mirror. Per-rule status: 'ingested' means a "
        "full document exists in rules/; renumbered/not_served/not_sliceable are "
        "recorded by ingest_oar.py. Chapter titles from the agency registry.")
    cat["retrieved"] = TODAY
    cat["chapters"].sort(key=lambda c: (len(c["chapter"]), c["chapter"]))
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))


def discover_chapter(ch: str, title: str, cat: dict) -> tuple:
    """Fetch one chapter's divisions + rule numbers; merge into cat preserving
    existing rule statuses. Returns (n_divisions, n_rules, n_new)."""
    raw = get(f"{BASE}/rules/oar_chapter_{ch}")
    time.sleep(0.2)
    divs = DIV_LINK_RE.findall(raw)

    existing = next((c for c in cat["chapters"] if c["chapter"] == ch), None)
    if existing is None:
        existing = {"chapter": ch, "title": title,
                    "url": f"{BASE}/rules/oar_chapter_{ch}", "divisions": []}
        cat["chapters"].append(existing)
    existing["title"] = title
    old_rules = {}
    for d in existing.get("divisions", []):
        for r in d.get("rules") or []:
            old_rules[r["number"]] = r

    new_divisions = []
    n_rules = n_new = 0
    for _ch, div, div_title in divs:
        div_raw = get(f"{BASE}/rules/oar_chapter_{ch}_division_{div}")
        time.sleep(0.2)
        numbers = sorted(set(RULE_LINK_RE.findall(div_raw)))
        rules = []
        for num in numbers:
            entry = old_rules.get(num) or {"number": num, "status": "not_ingested"}
            entry["number"] = num
            rules.append(entry)
            n_rules += 1
            if entry.get("status") == "not_ingested" and num not in old_rules:
                n_new += 1
        new_divisions.append({
            "division": div,
            "title": re.sub(r"\s+", " ", unescape(div_title)).strip(),
            "status": ("ingested" if rules and all(
                r.get("status") == "ingested" for r in rules) else "not_ingested"),
            "rules": rules,
        })
    # keep any old divisions that vanished from the mirror (never silently drop)
    seen = {d["division"] for d in new_divisions}
    for d in existing.get("divisions", []):
        if d["division"] not in seen and (d.get("rules") or []):
            d.setdefault("note", "division no longer listed on the mirror — verify upstream")
            new_divisions.append(d)
    existing["divisions"] = new_divisions
    existing["discovered"] = TODAY
    return len(new_divisions), n_rules, n_new


def cmd_discover(only: list):
    reg = yaml.safe_load(REGISTRY.read_text())
    chapters = [(o["oar_chapter"], o["name"]) for o in reg["organizations"]
                if o.get("oar_chapter")]
    chapters.sort(key=lambda t: (len(t[0]), t[0]))
    if only:
        chapters = [c for c in chapters if c[0] in only]
    cat = load_catalog()

    total_d = total_r = total_new = skipped = 0
    for i, (ch, title) in enumerate(chapters, 1):
        existing = next((c for c in cat["chapters"] if c["chapter"] == ch), None)
        if (existing and existing.get("discovered") and not only
                and "--redo" not in sys.argv):
            skipped += 1
            continue
        try:
            nd, nr, nn = discover_chapter(ch, title, cat)
        except Exception as e:
            print(f"FAILED chapter {ch}: {e}")
            continue
        total_d += nd
        total_r += nr
        total_new += nn
        print(f"[{i}/{len(chapters)}] ch {ch:>4} ({title[:50]}): "
              f"{nd} divisions, {nr} rules ({nn} new)")
        save_catalog(cat)  # checkpoint after every chapter — resumable
    save_catalog(cat)
    print(f"\ndiscovered: {total_d} divisions, {total_r} rules ({total_new} new); "
          f"{skipped} chapters already discovered (use --redo to refresh)")


def cmd_summary():
    cat = load_catalog()
    total = ingested = 0
    rows = []
    for c in sorted(cat["chapters"], key=lambda c: (len(c["chapter"]), c["chapter"])):
        n = sum(len(d.get("rules") or []) for d in c["divisions"])
        ing = sum(1 for d in c["divisions"] for r in d.get("rules") or []
                  if r.get("status") == "ingested")
        total += n
        ingested += ing
        rows.append((c["chapter"], c["title"], len(c["divisions"]), n, ing))
    for ch, title, nd, n, ing in rows:
        print(f"{ch:>4}  {nd:3d} div  {n:5d} rules  {ing:5d} ingested  {title[:55]}")
    print(f"\nTOTAL: {len(rows)} chapters, {total} rules, {ingested} ingested, "
          f"{total - ingested} to import")


def main():
    if "--discover" in sys.argv:
        only = [a for a in sys.argv[1:] if not a.startswith("--")]
        cmd_discover(only)
    elif "--summary" in sys.argv:
        cmd_summary()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
