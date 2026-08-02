#!/usr/bin/env python3
"""Re-fetch executive-order PDFs into a local, gitignored cache.

WHY THIS EXISTS. Executive orders are `snapshot_policy: hash-only`: `ingest_eo.py` pulls
each PDF into a temp dir, OCRs it, commits the `.txt` extraction, and throws the PDF away
(~700 MB of scans that would otherwise sit in git forever). That is the right default, and
it has one consequence -- when the OCR stack improves, there is nothing on disk to re-run
it against. The `.txt` files are OCR OUTPUT; text cannot be fed back into an OCR engine.

So a re-OCR necessarily begins with a re-fetch. This script makes that re-fetch cheap to
repeat: the cache lives under `_meta/.cache/` (already gitignored), so the next stack
upgrade does not pay for another 700 MB, and nothing committed changes -- the snapshot
policy governs what enters git, and this never enters git.

DELIBERATELY SLOW. Serial with a delay between requests, because this is ~500 requests at
a state government host that gains nothing from our hurry. The cache makes the cost
one-time; there is no reason to also make it rude.

RESUMABLE, because a 700 MB serial fetch will be interrupted. A file already in the cache
whose bytes hash to the manifest entry is skipped, so re-running costs a hash per file
rather than a download.

THE MANIFEST RECORDS RAW-BYTE SHA256, WHICH IS NOT `source_sha256`. For an OCR'd order
`source_sha256` is the hash of the whitespace-normalized TEXT (see `cmd_ocr` in
ingest_eo.py) -- verified: 494/494 committed orders match that formula, none match the
PDF's bytes. Recording the byte hash here gives the one thing the corpus does not already
have: a way to tell on a later run whether upstream reissued the scan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "_meta" / "catalog" / "eo.yml"
CACHE = ROOT / "_meta" / ".cache" / "eo-pdfs"
MANIFEST = CACHE / "manifest.json"

UA = ("executive-regulatory-frameworks "
      "(+https://github.com/OregonAI/executive-regulatory-frameworks)")

# Same construction as ingest_eo.py: file_ref is a site-relative path and some contain
# spaces ("eo-24-15 (amended).pdf"), so it must be percent-encoded.
BASE = "https://www.oregon.gov"


def url_for(order: dict) -> str:
    return BASE + urllib.request.quote(order["file_ref"])


def load_manifest() -> dict:
    if MANIFEST.is_file():
        return json.loads(MANIFEST.read_text())
    return {}


def save_manifest(m: dict) -> None:
    MANIFEST.write_text(json.dumps(m, indent=2, sort_keys=True))


def fetch_one(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--delay", type=float, default=1.0,
                    help="seconds between requests (default 1.0)")
    ap.add_argument("--limit", type=int, default=None,
                    help="stop after N downloads (for spikes)")
    ap.add_argument("--only", nargs="*", help="fetch only these order ids")
    ap.add_argument("--states", nargs="*",
                    default=["ocr-recovered", "none", "fallback-ocr"],
                    help="catalog text_layer prefixes to fetch")
    args = ap.parse_args()

    cat = yaml.safe_load(CATALOG.read_text())
    orders = [o for o in cat["orders"]
              if any(str(o.get("text_layer", "")).startswith(s) for s in args.states)
              and o.get("file_ref")]
    if args.only:
        orders = [o for o in orders if o["id"] in set(args.only)]

    CACHE.mkdir(parents=True, exist_ok=True)
    man = load_manifest()

    todo = []
    for o in orders:
        p = CACHE / f"{o['id']}.pdf"
        # Trust the cache only when the file is present AND matches the manifest hash; a
        # truncated download from an interrupted run would otherwise be treated as done and
        # silently OCR'd as a broken PDF.
        if p.is_file() and man.get(o["id"], {}).get("sha256") == \
                hashlib.sha256(p.read_bytes()).hexdigest():
            continue
        todo.append(o)

    print(f"{len(orders)} orders in scope, {len(orders) - len(todo)} already cached, "
          f"{len(todo)} to fetch", file=sys.stderr)
    if args.limit:
        todo = todo[:args.limit]

    ok = failed = 0
    total_bytes = 0
    for i, o in enumerate(todo, 1):
        url = url_for(o)
        try:
            raw = fetch_one(url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            print(f"  [{i}/{len(todo)}] {o['id']:24s} FAILED {type(e).__name__}: {e}",
                  file=sys.stderr)
            man.setdefault(o["id"], {})["error"] = f"{type(e).__name__}: {e}"
            failed += 1
            continue
        if not raw.startswith(b"%PDF-"):
            # An HTML error page saved as .pdf would OCR into plausible-looking garbage.
            print(f"  [{i}/{len(todo)}] {o['id']:24s} NOT A PDF ({raw[:20]!r})",
                  file=sys.stderr)
            man.setdefault(o["id"], {})["error"] = "response was not a PDF"
            failed += 1
            continue
        (CACHE / f"{o['id']}.pdf").write_bytes(raw)
        man[o["id"]] = {"sha256": hashlib.sha256(raw).hexdigest(),
                        "bytes": len(raw), "url": url}
        man[o["id"]].pop("error", None)
        ok += 1
        total_bytes += len(raw)
        if i % 25 == 0 or i == len(todo):
            save_manifest(man)
            print(f"  [{i}/{len(todo)}] {ok} ok, {failed} failed, "
                  f"{total_bytes/1e6:.0f} MB", file=sys.stderr)
        time.sleep(args.delay)

    save_manifest(man)
    print(f"done: {ok} fetched, {failed} failed, {total_bytes/1e6:.0f} MB into {CACHE}",
          file=sys.stderr)
    return 1 if failed and not ok else 0


if __name__ == "__main__":
    sys.exit(main())
