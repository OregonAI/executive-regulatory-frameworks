#!/usr/bin/env python3
"""Whole-chapter ORS ingestion pipeline (full-text-first, HC-1 safe).

  python3 src/ingest_ors.py 183 [184 ...]

Per chapter: fetch the chapter HTML -> snapshot ors-chapter-<ch>.html/.txt ->
for every section in _meta/catalog/ors.yml: slice its text via
repo_lib.snapshot_slice (the same function verify_provenance uses) and emit a
full-text document. Sections whose slice is missing/tiny or fails a
title-anchoring sanity check are SKIPPED and marked not_sliceable in the
catalog (renumbered/repealed/TOC-noise entries) — nothing is ever fabricated.
Also updates the catalog, the ors source group, statutes/_index.md, and prints
a terse per-chapter summary."""
import re
import sys
from datetime import date
from pathlib import Path

import yaml

from html_to_text import html_to_text
from ingest_lib import fetch, flow_to_lines
from repo_lib import (REPO_ROOT, SNAPSHOT_DIR, content_hash, hash_snapshot,
                      normalize_ws, snapshot_slice)

CATALOG = REPO_ROOT / "_meta/catalog/ors.yml"
GROUP = REPO_ROOT / "_meta/sources/ors.yml"
OUT = REPO_ROOT / "statutes"
TODAY = date.today().isoformat()
EDITION = "2025 Edition"

CHAPTER_TITLES = {}  # filled from catalog


def anchor_ok(slice_text: str, sec: str, title: str) -> bool:
    """Sanity check against mis-anchored slices: must start with the section number
    and share vocabulary with the catalog catchline."""
    if not slice_text.startswith(sec):
        return False
    head = normalize_ws(slice_text[:160]).lower()
    words = [w for w in re.findall(r"[a-z]{4,}", title.lower())][:6]
    if not words:
        return True
    hits = sum(1 for w in words if w in head)
    return hits >= max(1, len(words) // 2)


def doc_body(sec, title, ch, ch_title, snap_id, sha, url, slice_text):
    ft = flow_to_lines(slice_text)
    return f"""---
id: ors-{sec.lower()}
title: "{title.replace(chr(34), chr(39))}"
doc_type: statute
citation: "ORS {sec}"
authority_level: statute
issuing_body: "Oregon Legislative Assembly; published by the Legislative Counsel Committee"
agency: statewide
legal_authority: []
source_url: "{url}"
source_format: html
retrieved: "{TODAY}"
source_sha256: "{sha}"
snapshot_id: {snap_id}
effective_date: null
last_reviewed: null
source_version: "{EDITION}"
status: current
supersedes: null
content_mode: verbatim
conversion_notes: "sliced the section's text out of the shared chapter snapshot; line breaks inserted at subsection markers (whitespace-only)"
last_verified: "{TODAY}"
verified_by: "@morficflux"
maintainer: "@morficflux"
relationships:
  implements: []
  implemented_by: []
  references_external: []
  related: []
  supersedes: []
tags: ["ors", "chapter-{ch.lower()}"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** The official ORS text is the printed
> published copy of the Oregon Revised Statutes. Verify against the official source:
> <{url}> (retrieved {TODAY}, {EDITION}).

# {title} (ORS {sec})

## At a glance

ORS {sec} — {title}. Chapter {ch} ({ch_title}), {EDITION}.

## Full text

{ft}

## Provenance & change history

- Source: <{url}> · retrieved {TODAY} · sha256 `{sha}`
  (chapter snapshot `_meta/snapshots/{snap_id}.html`)
- See [CHANGELOG](./CHANGELOG.md).
"""


def ingest_chapter(ch, cat_chapter):
    ch_l = ch.lower()
    snap_id = f"ors-chapter-{ch_l}"
    url = cat_chapter["url"]
    html_path = SNAPSHOT_DIR / f"{snap_id}.html"
    if not html_path.exists():
        raw = fetch(url)
        html_path.write_bytes(raw)
        (SNAPSHOT_DIR / f"{snap_id}.txt").write_text(html_to_text(raw), encoding="utf-8")
    sha = hash_snapshot(snap_id, "html")
    raw_txt = (SNAPSHOT_DIR / f"{snap_id}.txt").read_text(encoding="utf-8", errors="replace")
    ch_title = cat_chapter["title"]

    made = skipped = kept = 0
    for s in cat_chapter["sections"]:
        sec, title = s["number"], s["title"]
        doc_id = f"ors-{sec.lower()}"
        out = OUT / f"{doc_id}.md"
        if s.get("status") == "ingested" and out.exists():
            kept += 1
            continue
        sl = snapshot_slice(doc_id, snap_id, raw_txt)
        if len(sl) < 120 or not anchor_ok(sl, sec, title):
            s["status"] = "not_sliceable"
            s["note"] = ("no section body found in the chapter text (likely renumbered/"
                         "repealed or a TOC cross-reference artifact); not ingested")
            s.pop("path", None)
            skipped += 1
            continue
        out.write_text(doc_body(sec, title, ch, ch_title, snap_id, sha, url, sl))
        s["status"] = "ingested"
        s["path"] = f"statutes/{doc_id}.md"
        s.pop("note", None)
        made += 1
    return made, skipped, kept, sha, url


def main():
    chapters = sys.argv[1:]
    if not chapters:
        print("usage: ingest_ors.py <chapter> [<chapter> ...]")
        sys.exit(2)
    cat = yaml.safe_load(CATALOG.read_text())
    by_num = {c["chapter"]: c for c in cat["chapters"]}
    group = yaml.safe_load(GROUP.read_text())
    gsrc = {s["id"]: s for s in group["sources"]}

    for ch in chapters:
        if ch not in by_num:
            print(f"{ch}: not in catalog")
            continue
        made, skipped, kept, sha, url = ingest_chapter(ch, by_num[ch])
        print(f"chapter {ch}: made {made}, skipped(not_sliceable) {skipped}, kept {kept}")
        snap_id = f"ors-chapter-{ch.lower()}"
        gsrc[snap_id] = {"id": snap_id, "url": url, "sha256": sha,
                         "last_checked": TODAY,
                         "notes": f"ORS chapter {ch} ({by_num[ch]['title']}), {EDITION}"}

    group["sources"] = sorted(gsrc.values(), key=lambda s: s["id"])
    GROUP.write_text(yaml.safe_dump(group, sort_keys=False, allow_unicode=True, width=110))
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))

    # regenerate statutes/_index.md from the catalog
    lines = ["# Statutes (ORS) — index", "",
             "Oregon Revised Statutes for DAS/executive-branch administration, full text per",
             f"section, sliced from the Legislature's chapter HTML ({EDITION}).",
             "**Non-authoritative copies** — the official text is the printed published ORS.", "",
             "| Chapter | Title | Sections listed | Ingested |", "|---|---|---|---|"]
    tot = [0, 0]
    for c in cat["chapters"]:
        n = len(c["sections"])
        i = sum(1 for s in c["sections"] if s.get("status") == "ingested")
        tot[0] += n; tot[1] += i
        lines.append(f"| {c['chapter']} | {c['title']} | {n} | {i} |")
    lines += [f"| **all** | | **{tot[0]}** | **{tot[1]}** |", "",
              "Per-section numbers/titles/paths: [`_meta/catalog/ors.yml`](../_meta/catalog/ors.yml).",
              "Sections marked `not_sliceable` there have no body text in the chapter HTML",
              "(renumbered/repealed or catalog noise) and are intentionally not ingested.", ""]
    (OUT / "_index.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
