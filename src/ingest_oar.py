#!/usr/bin/env python3
"""OAR chapter/division ingestion pipeline (full-text-first, HC-1 safe).

  python3 src/ingest_oar.py --enumerate 125 128   # discover divisions+rules (gate #1 input)
  python3 src/ingest_oar.py --ingest 125 128      # fetch each rule from OARD; emit docs

Enumeration uses oregon.public.law's server-rendered chapter/division pages ONLY to
discover rule numbers; every rule's content is fetched from the authoritative OARD
page (view.action?ruleNumber=). Renumbering guard: if OARD serves a different rule
number than requested (the 125-800 -> 128-030 lesson), the document is filed under the
SERVED number and the mapping recorded in the catalog. Enumeration results are cached
to _meta/catalog/oar.yml so --ingest runs from the approved list."""
import argparse
import fcntl
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

import yaml

from html_to_text import html_to_text
from ingest_lib import fetch
from repo_lib import (REPO_ROOT, SNAPSHOT_DIR, content_hash, normalize_ws,
                      normalize_volatile, snapshot_slice, ws_only)

CATALOG = REPO_ROOT / "_meta/catalog/oar.yml"
GROUP = REPO_ROOT / "_meta/sources/oar.yml"
TODAY = date.today().isoformat()
PL = "https://oregon.public.law"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def enumerate_chapter(ch):
    """[(division, division_title, [rule numbers])] from oregon.public.law."""
    page = get(f"{PL}/rules/oar_chapter_{ch}")
    # hrefs are relative (href="oar_chapter_125_division_55"); titles live in link text
    divs = re.findall(rf'href="(?:/rules/)?(oar_chapter_{ch}_division_(\d+))"[^>]*>\s*([^<]*)', page)
    seen, out = set(), []
    for name, div, title in divs:
        if div in seen:
            continue
        seen.add(div)
        dpage = get(f"{PL}/rules/{name}")
        rules = sorted(set(re.findall(rf'href="(?:/rules/)?oar_({ch}-\d{{3}}-\d{{4}})"', dpage)))
        out.append((div, normalize_ws(title) or f"Division {div}", rules))
        time.sleep(0.2)
    return out


def cmd_enumerate(chapters):
    cat = yaml.safe_load(CATALOG.read_text())
    by_ch = {c["chapter"]: c for c in cat["chapters"]}
    for ch in chapters:
        found = enumerate_chapter(ch)
        c = by_ch.get(ch)
        if c is None:
            c = {"chapter": ch, "title": f"Chapter {ch}", "divisions": []}
            cat["chapters"].append(c)
            by_ch[ch] = c
        by_div = {d["division"]: d for d in c["divisions"]}
        total = 0
        for div, title, rules in found:
            d = by_div.get(div) or {"division": div}
            d["title"] = d.get("title") or title
            existing = {r["number"]: r for r in d.get("rules", []) if isinstance(d.get("rules"), list)} \
                if isinstance(d.get("rules"), list) else {}
            d["rules"] = [existing.get(n, {"number": n, "status": "not_ingested"}) for n in rules]
            d["status"] = d.get("status") if any(r.get("status") == "ingested" for r in d["rules"]) else "not_ingested"
            if div not in by_div:
                c["divisions"].append(d)
                by_div[div] = d
            total += len(rules)
            print(f"{ch}-{div} | {title[:55]} | {len(rules)} rules")
        print(f"chapter {ch}: {len(found)} divisions, {total} rules")
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))


def served_rule_number(text):
    m = re.search(r"\b(\d{3}-\d{3}-\d{4})\b", text)
    return m.group(1) if m else None


def doc_body(rule, title_line, url, sha, ch, div):
    return f"""---
id: oar-{rule}
title: "{title_line.replace(chr(34), chr(39))}"
doc_type: rule
citation: "OAR {rule}"
authority_level: administrative_rule
issuing_body: "Adopting agency per the rule text; compiled by the Secretary of State Administrative Rules Unit"
agency: statewide
legal_authority: []
source_url: "{url}"
source_format: html
retrieved: "{TODAY}"
source_sha256: "{sha}"
effective_date: null
last_reviewed: null
source_version: "As served by OARD {TODAY}; AON history inside the full text"
status: current
supersedes: null
content_mode: verbatim
conversion_notes: "rule text sliced from the OARD page (site chrome excluded); whitespace-collapsed with breaks at subsection markers"
last_verified: "{TODAY}"
verified_by: "@morficflux"
maintainer: "@morficflux"
relationships:
  implements: []
  implemented_by: []
  references_external: []
  related: []
  supersedes: []
tags: ["oar", "chapter-{ch}", "division-{div}"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated copy, not the
> official text. Verify against OARD:
> <{url}> (retrieved {TODAY}).

# {title_line} (OAR {rule})

## At a glance

OAR {rule} — {title_line}. Chapter {ch}, Division {div}. Statutory authority and AON
history are in the full text below.

## Full text

{{FT}}

## Provenance & change history

- Source: <{url}> · retrieved {TODAY} · sha256 `{sha}`
- See [CHANGELOG](../../CHANGELOG.md).
"""


def _write_catalog_merged(cat, my_chapters):
    """Concurrent-safe catalog save for parallel --ingest workers: under an exclusive
    lock, re-read the catalog from disk and replace ONLY this worker's chapters with
    our in-memory state, then write atomically. Workers own disjoint chapter sets, so
    merge-by-chapter is conflict-free — this exists because whole-file checkpoint
    writes from parallel workers would silently revert each other's progress (the
    lesson from the EO OCR concurrency incident)."""
    lock_path = REPO_ROOT / "_meta/.cache/oar-catalog.lock"
    lock_path.parent.mkdir(exist_ok=True)
    mine = {c["chapter"]: c for c in cat["chapters"] if c["chapter"] in my_chapters}
    with open(lock_path, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        disk = yaml.safe_load(CATALOG.read_text())
        disk["chapters"] = [mine.get(c["chapter"], c) for c in disk["chapters"]]
        tmp = CATALOG.parent / ".oar.yml.tmp"
        tmp.write_text(yaml.safe_dump(disk, sort_keys=False, allow_unicode=True, width=100))
        os.replace(tmp, CATALOG)


def cmd_ingest(chapters, skip_group=False):
    # skip_group: mass-import mode — do NOT append per-rule entries to the oar
    # update group. At thousands of rules, per-rule content-hash rechecking is
    # impractical; freshness for mass-imported chapters comes from re-running
    # catalog_oar.py --discover --redo and diffing the catalog (new/removed rule
    # numbers), then re-ingesting just the changes.
    from ingest_lib import flow_to_lines
    # New documents are born enriched: agency/authority/effective-date/lineage parsed
    # from the rule's own structured lines right after writing (see enrich_oar.py,
    # which is also the CI drift check for these fields).
    from enrich_oar import apply as enrich_apply
    from enrich_oar import derive as enrich_derive
    from enrich_oar import load_registry_by_chapter
    registry_by_ch = load_registry_by_chapter()
    cat = yaml.safe_load(CATALOG.read_text())
    by_ch = {c["chapter"]: c for c in cat["chapters"]}
    group = yaml.safe_load(GROUP.read_text())
    gsrc = {s["id"]: s for s in group["sources"]}
    made = skipped = renumbered = failed = 0
    for ch in chapters:
        for d in by_ch[ch]["divisions"]:
            if not isinstance(d.get("rules"), list):
                continue
            for r in d["rules"]:
                num = r["number"]
                if r.get("status") == "ingested":
                    continue
                url = f"https://secure.sos.state.or.us/oard/view.action?ruleNumber={num}"
                try:
                    raw = normalize_volatile(fetch(url))
                except Exception as e:
                    print(f"FETCH FAILED {num}: {e}")
                    failed += 1
                    continue
                time.sleep(0.3)
                text = html_to_text(raw)
                wt = ws_only(text)
                served = served_rule_number(wt)
                # OARD's not-found shell echoes the requested number in its search box
                if served and re.search(re.escape(served) + r"\s+not found", wt):
                    served = None
                if not served:
                    r["status"] = "not_served"
                    r["note"] = "OARD page contains no rule number (rule likely repealed)"
                    skipped += 1
                    continue
                target = served
                if served != num:
                    r["status"] = "renumbered"
                    r["note"] = f"OARD serves {served} for this number"
                    r["served_as"] = served
                    renumbered += 1
                doc_id = f"oar-{target}"
                s_ch, s_div, _ = target.split("-")
                out_dir = REPO_ROOT / "rules" / s_ch / s_div
                out = out_dir / f"{doc_id}.md"
                if out.exists():
                    if served == num:
                        r["status"] = "ingested"
                        r["path"] = str(out.relative_to(REPO_ROOT))
                    continue
                out_dir.mkdir(parents=True, exist_ok=True)
                (SNAPSHOT_DIR / f"{doc_id}.html").write_bytes(raw)
                (SNAPSHOT_DIR / f"{doc_id}.txt").write_text(text, encoding="utf-8")
                sha = content_hash(raw, "html")
                sl = snapshot_slice(doc_id, doc_id, text)
                if len(sl) < 100:
                    r["status"] = "not_sliceable"
                    r["note"] = "no rule body found on the OARD page"
                    skipped += 1
                    continue
                # title = text between the rule number and the first sentence marker
                m = re.match(re.escape(target) + r"\s+(.{3,120}?)(?:\s\(1\)|\s[A-Z][a-z]|\.)", sl)
                title_line = normalize_ws(m.group(1)) if m else f"OAR {target}"
                body = doc_body(target, title_line, url, sha, s_ch, s_div)
                body = body.replace("{FT}", flow_to_lines(sl))
                out.write_text(body)
                try:
                    enrich_apply(out, enrich_derive(flow_to_lines(sl), doc_id, registry_by_ch))
                except SystemExit as e:
                    # e.g. OARD renumbered the rule into a chapter the registry doesn't
                    # know (mirror index gap). Quarantine: withdraw the doc, record why,
                    # keep the worker alive — resolved by a later registry fix + re-run.
                    out.unlink(missing_ok=True)
                    print(f"NEEDS REGISTRY {num} -> {target}: {e}")
                    r["status"] = "needs_registry"
                    r["note"] = str(e)[:160]
                    failed += 1
                    continue
                if served == num:
                    r["status"] = "ingested"
                r["path"] = str(out.relative_to(REPO_ROOT))
                if not skip_group:
                    gsrc[doc_id] = {"id": doc_id, "url": url, "sha256": sha,
                                    "last_checked": TODAY, "notes": title_line[:90]}
                made += 1
                if made % 100 == 0:
                    print(f"...{made} ingested")
                    _write_catalog_merged(cat, set(chapters))
    if not skip_group:
        group["sources"] = sorted(gsrc.values(), key=lambda s: s["id"])
        GROUP.write_text(yaml.safe_dump(group, sort_keys=False, allow_unicode=True, width=110))
    _write_catalog_merged(cat, set(chapters))
    print(f"made {made}, renumbered {renumbered}, skipped {skipped}, failed {failed}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enumerate", nargs="+", metavar="CH")
    ap.add_argument("--ingest", nargs="+", metavar="CH")
    ap.add_argument("--skip-group", action="store_true",
                    help="mass-import mode: no per-rule update-group entries (see cmd_ingest)")
    a = ap.parse_args()
    if a.enumerate:
        cmd_enumerate(a.enumerate)
    elif a.ingest:
        cmd_ingest(a.ingest, a.skip_group)
    else:
        ap.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
