#!/usr/bin/env python3
"""Executive-order ingestion pipeline (immutable corpus, hash-only snapshots).

  python3 src/ingest_eo.py --enumerate   # pull the /gov/eo SharePoint listing of record;
                                         # write _meta/catalog/eo.yml + eo-listing.json
  python3 src/ingest_eo.py --ingest      # fetch each catalog row; emit docs

Orders never change once issued (per project policy), so the update group only watches
the listing for ADDED rows — existing orders are never re-fetched.

Snapshot policy is HASH-ONLY (user decision 2026-07-18): the 527 source PDFs are ~700 MB
of mostly image-only scans, so the .pdf files are NOT committed. Each doc records the
raw-byte sha256 of the fetched PDF; docs whose text layer passes the quality gate also
commit the small _meta/snapshots/<id>.txt extraction (which verify_provenance checks).

Quality gate (mechanical, HC-1 safe): a PDF's text layer becomes '## Full text' only if
it has >= 100 words AND >= 80% of its alphabetic words appear in the system dictionary —
this rejects garbage OCR layers (e.g. "EXECI]TIVE ORDER") that would otherwise pass as
verbatim text. Everything else is a summary stub with content_exception; the At-a-glance
line quotes the listing-of-record description verbatim. No auto-OCR, ever.

Identity: id eo-YY-NN derived from the FILENAME (listing Year/Number metadata is wrong
for 6 rows — filenames + descriptions agree with each other); mismatches recorded in the
catalog as listing_metadata_mismatch. Companion files keep their suffix (-letter, -a,
-rev, -amended). Two listing rows pointing at byte-identical files collapse to one doc."""
import argparse
import hashlib
import html as html_mod
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date
from pathlib import Path

import yaml

from ingest_lib import clean_pdf_text, fetch, output_dir_for
from repo_lib import REPO_ROOT, SNAPSHOT_DIR, normalize_ws

CATALOG = REPO_ROOT / "_meta/catalog/eo.yml"
GROUP = REPO_ROOT / "_meta/sources/executive-orders.yml"
LISTING_SNAP = SNAPSHOT_DIR / "eo-listing.json"
TODAY = date.today().isoformat()

WEB, LIST = "/gov", "/gov/eo"
PUBLIC_VIEW = "c3c5713c-02f9-45ba-9de8-5b29d30ce221"
LIST_PAGE = "https://www.oregon.gov/gov/pages/executive-orders.aspx"
DICT_PATHS = ["/usr/share/dict/words", "/usr/share/dict/american-english"]
MIN_WORDS, MIN_DICT_RATIO = 100, 0.80


def fetch_rows():
    """All rows from the listing of record, incl. FileRef (needs a custom ViewXml —
    the Public view's own render omits file paths)."""
    url = (f"https://www.oregon.gov{WEB}/_api/web/GetList('{LIST}')/RenderListDataAsStream")
    viewxml = ('<View Scope="RecursiveAll"><ViewFields>'
               '<FieldRef Name="FileRef"/><FieldRef Name="FileLeafRef"/>'
               '<FieldRef Name="Number"/><FieldRef Name="Year"/>'
               '<FieldRef Name="Document_x0020_Description"/>'
               '</ViewFields><RowLimit>3000</RowLimit></View>')
    body = json.dumps({"parameters": {"__metadata": {"type": "SP.RenderListDataParameters"},
                                      "RenderOptions": 2, "ViewXml": viewxml}}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": "oregon-policy-repo (+https://github.com/morficflux/oregon-policy-repo)",
        "Accept": "application/json;odata=verbose",
        "Content-Type": "application/json;odata=verbose"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["Row"]


def parse_id(leaf: str):
    """Canonical id from the filename. Handles every pattern on the 2003-2026 listing:
    eo-YY-NN, eo_YY-NN, eo_YY_NN, eo--YY-NN, eoYYNN, EOYYNN, eo-YYNN, esYY-NN (typo'd
    prefix), plus suffixes (-letter, -a, -r, -rev, ' (amended)', -special-session)."""
    n = re.sub(r"\.pdf$", "", leaf.strip(), flags=re.I)
    m = re.match(r"^(?:eo|es)-{0,2}_?(\d{2})[-_](\d{2})(.*)$", n, re.I)
    if not m:
        m = re.match(r"^eo-?(\d{2})(\d{2})(.*)$", n, re.I)
    if not m:
        m2 = re.match(r"^eo-(\d{2})-(.+)$", n, re.I)  # eo-12-special-session
        if m2:
            slug = re.sub(r"[^a-z0-9]+", "-", m2.group(2).lower()).strip("-")
            return f"eo-{m2.group(1)}-{slug}"
        return None
    yy, nn, rest = m.groups()
    suffix = re.sub(r"[^a-z0-9]+", "-", rest.lower()).strip("-")
    base = f"eo-{yy}-{nn}"
    return f"{base}-{suffix}" if suffix else base


def cmd_enumerate():
    rows = fetch_rows()
    existing = {}
    if CATALOG.exists():
        cat = yaml.safe_load(CATALOG.read_text())
        existing = {o["id"]: o for o in cat.get("orders", [])}

    orders, listing_rows = {}, []
    for r in rows:
        leaf = r["FileLeafRef"]
        year = r["Year."].split(".")[0]
        num = r["Number."].split(".")[0]
        title = normalize_ws(html_mod.unescape(r["Document_x0020_Description"]))
        oid = parse_id(leaf)
        listing_rows.append({"number": f"{year}-{num}", "file_ref": r["FileRef"],
                             "effective_date": ""})
        if oid is None:
            print(f"UNPARSED filename, needs a parse rule: {leaf}")
            continue
        entry = existing.get(oid) or {"id": oid, "status": "not_ingested"}
        entry.update({"title": title, "file_ref": r["FileRef"],
                      "listing_year": year, "listing_number": num})
        m = re.match(r"^eo-(\d{2})-(\d{2})$", oid)
        if m and (m.group(1) != year[2:] or m.group(2) != num.zfill(2)):
            entry["listing_metadata_mismatch"] = (
                f"listing says {year} No. {num}; filename (trusted) says 20{m.group(1)} "
                f"No. {m.group(2)} — the description matches the filename")
        if oid in orders:  # two listing rows -> same id (e.g. eo-21-05.pdf + eo_21-05.pdf)
            orders[oid].setdefault("duplicate_file_refs", []).append(r["FileRef"])
        else:
            orders[oid] = entry
    cat = {"note": ("Listing of record: SharePoint list /gov/eo behind " + LIST_PAGE +
                    " (Public view). Ids derive from filenames; 6 rows have wrong "
                    "Year/Number listing metadata (recorded per-order). Orders are "
                    "immutable — only NEW orders ever appear."),
           "retrieved": TODAY,
           "orders": sorted(orders.values(), key=lambda o: o["id"])}
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))

    snap = {"note": ("Normalized rows of the /gov/eo listing (Public view), for "
                     "check_sp_listing() ADDED/REMOVED diffing. The listing has no date "
                     "field and orders never change, so only adds/removals matter; the "
                     "checker's date_field intentionally names a field the view does not "
                     "return, making both sides empty. Live rows from the view GUID carry "
                     "no FileRef, so stored file_ref is empty to match."),
            "retrieved": TODAY, "list_url": LIST_PAGE,
            "api": f"https://www.oregon.gov{WEB}/_api/web/GetList('{LIST}')/RenderListDataAsStream",
            "views": {"Public": PUBLIC_VIEW},
            "rows": sorted({r["number"]: {"number": r["number"], "file_ref": "",
                                          "effective_date": ""}
                            for r in listing_rows}.values(), key=lambda r: r["number"]),
            "checker": {"web": WEB, "list": LIST, "id_field": "Order0",
                        "date_field": "NoDateFieldOrdersAreImmutable"}}
    LISTING_SNAP.write_text(json.dumps(snap, indent=1, ensure_ascii=False) + "\n")
    n_mm = sum(1 for o in orders.values() if o.get("listing_metadata_mismatch"))
    n_dup = sum(1 for o in orders.values() if o.get("duplicate_file_refs"))
    print(f"catalog: {len(orders)} orders from {len(rows)} listing rows "
          f"({n_mm} metadata mismatches, {n_dup} duplicate-row collapses); "
          f"listing snapshot: {len(snap['rows'])} keys")


def load_dictionary():
    for p in DICT_PATHS:
        if Path(p).is_file():
            return {w.strip().lower() for w in Path(p).read_text().splitlines()
                    if w.strip().isalpha()}
    return None


def text_quality(text: str, dictionary):
    """(word_count, dict_ratio) of a PDF text layer."""
    words = [w for w in re.findall(r"[A-Za-z]+", text) if len(w) > 1]
    if not words or dictionary is None:
        return len(words), 0.0
    hits = sum(1 for w in words if w.lower() in dictionary)
    return len(words), hits / len(words)


def eo_citation(oid: str):
    m = re.match(r"^eo-(\d{2})-(\d{2})", oid)
    return f"Executive Order {m.group(1)}-{m.group(2)}" if m else f"Executive Order {oid[3:]}"


def parse_signed_date(text: str):
    """The order's own 'Dated this Nth day of Month, Year' line, if cleanly printed."""
    m = re.search(r"Dated\s+this\s+(\d{1,2})\w{0,2}\s+day\s+of\s+([A-Z][a-z]+),?\s+(\d{4})",
                  text)
    if not m:
        return None
    months = {mo: i for i, mo in enumerate(
        ["January", "February", "March", "April", "May", "June", "July", "August",
         "September", "October", "November", "December"], 1)}
    mo = months.get(m.group(2))
    return f"{m.group(3)}-{mo:02d}-{int(m.group(1)):02d}" if mo else None


BANNER = """> **NON-AUTHORITATIVE — AI-friendly reference only.**{extra} Verify against the official
> source: <{url}> (retrieved {today})."""


def doc_text(oid, title, url, sha, fulltext, conv, eff_date, exception, related):
    cit = eo_citation(oid)
    yy = oid[3:5]
    fm_title = (title or cit).replace('"', "'")
    rel_lines = "".join(f"\n    - {r}" for r in related)
    common = f"""---
id: {oid}
title: "{fm_title}"
doc_type: executive_order
citation: "{cit}"
authority_level: executive_order
issuing_body: "Office of the Governor, State of Oregon"
agency: statewide
legal_authority: []
source_url: "{url}"
source_format: pdf
retrieved: "{TODAY}"
source_sha256: "{sha}"
snapshot_policy: hash-only
effective_date: {eff_date or 'null'}
last_reviewed: null
source_version: null
status: current
supersedes: null
"""
    if fulltext is not None:
        common += f"""content_mode: verbatim
conversion_notes: "{conv.replace('"', "'")}"
"""
    else:
        common += f"""content_mode: summary
content_exception: "{exception}"
"""
    common += f"""last_verified: "{TODAY}"
verified_by: "@morficflux"
maintainer: "@morficflux"
relationships:
  implements: []
  implemented_by: []
  references_external: []
  related: []
  supersedes: []
tags: ["executive-order", "year-20{yy}"]
---

"""
    if related:
        common = common.replace("  related: []", "  related:" + rel_lines)
    extra = ("" if fulltext is not None else
             " The source PDF is an image-only scan (or has an\n"
             "> unusable OCR text layer), so this file carries **no verbatim text** — only\n"
             "> the listing-of-record metadata below.")
    body = BANNER.format(extra=extra, url=url, today=TODAY) + "\n\n"
    body += f"# {fm_title} ({cit})\n\n"
    body += "## At a glance\n\n"
    body += (f"{cit}: {title}. (Title as printed in the Governor's office listing of "
             f"record; see Provenance.)\n\n" if title else
             f"{cit}. The listing of record carries no description for this order.\n\n")
    if fulltext is not None:
        body += f"## Full text\n\n{fulltext}\n\n"
    body += "## Provenance & change history\n\n"
    body += (f"- Source: <{url}> · retrieved {TODAY} · raw-byte sha256 `{sha}`\n"
             if fulltext is None else
             f"- Source: <{url}> · retrieved {TODAY} · text-content sha256 `{sha}`\n")
    body += ("- Snapshot policy: **hash-only** — executive-order PDFs (mostly large "
             "image scans) are not committed to the repo; "
             + ("the text extraction is committed as `_meta/snapshots/" + oid + ".txt`.\n"
                if fulltext is not None else
                "there is no text layer to commit, so nothing diffs this document "
                "against its source mechanically.\n"))
    body += "- See this knowledge body's [CHANGELOG](./CHANGELOG.md).\n"
    return common + body


def cmd_ingest(limit=None):
    cat = yaml.safe_load(CATALOG.read_text())
    dictionary = load_dictionary()
    if dictionary is None:
        sys.exit("no system dictionary found (needed for the OCR quality gate); "
                 "install `wamerican` or similar")
    out_dir = output_dir_for("executive_order")
    made = full = stub = failed = skipped = 0
    for o in cat["orders"]:
        if o.get("status") == "ingested":
            skipped += 1
            continue
        if limit and made >= limit:
            break
        # percent-encode the path — some FileRefs contain spaces ("eo-24-15 (amended).pdf")
        url = "https://www.oregon.gov" + urllib.request.quote(o["file_ref"])
        try:
            raw = fetch(url)
        except Exception as e:
            print(f"FETCH FAILED {o['id']}: {e}")
            o["status"] = "fetch_failed"
            o["note"] = str(e)[:120]
            failed += 1
            continue
        time.sleep(0.2)
        if not raw.startswith(b"%PDF"):
            print(f"NOT A PDF {o['id']}: server returned {raw[:40]!r}")
            o["status"] = "not_pdf"
            o["note"] = "server returned a non-PDF (HTTP-200 not-found shell?)"
            failed += 1
            continue
        # duplicate listing rows: confirm the other file is byte-identical
        for dup in o.get("duplicate_file_refs", []):
            try:
                dup_raw = fetch("https://www.oregon.gov" + dup)
                o["duplicate_note"] = ("byte-identical duplicate listing row"
                                       if dup_raw == raw else
                                       "DUPLICATE ROW WITH DIFFERENT BYTES — human review")
            except Exception as e:
                o["duplicate_note"] = f"duplicate row fetch failed: {e}"

        with tempfile.NamedTemporaryFile(suffix=".pdf") as tf:
            tf.write(raw)
            tf.flush()
            proc = subprocess.run(["pdftotext", "-layout", tf.name, "-"],
                                  capture_output=True)
        text = proc.stdout.decode("utf-8", errors="replace") if proc.returncode == 0 else ""
        words, ratio = text_quality(text, dictionary)
        # companion/amended files: relate to the base order only if the listing also
        # carries the base as its own row (often the suffixed file IS the only copy)
        related = []
        base = re.match(r"^(eo-\d{2}-\d{2})-", o["id"])
        if base and any(x["id"] == base.group(1) for x in cat["orders"]):
            related.append(base.group(1))
        if words >= MIN_WORDS and ratio >= MIN_DICT_RATIO:
            ft, conv = clean_pdf_text(text)
            (SNAPSHOT_DIR / f"{o['id']}.txt").write_text(text, encoding="utf-8")
            sha = hashlib.sha256(normalize_ws(text).encode("utf-8")).hexdigest()
            eff = parse_signed_date(normalize_ws(text))
            eff_date = f'"{eff}"' if eff else None
            doc = doc_text(o["id"], o["title"], url, sha, ft, conv, eff_date, None, related)
            o["text_layer"] = f"clean ({words} words, {ratio:.0%} dictionary)"
            full += 1
        else:
            sha = hashlib.sha256(raw).hexdigest()
            reason = ("image-only scan with no text layer" if words < MIN_WORDS else
                      f"unusable OCR text layer ({ratio:.0%} dictionary words)")
            exc = (f"Source PDF is an {reason}; no machine-verifiable text. Hash-only "
                   "snapshot policy for executive orders (raw-byte sha256 recorded; "
                   "PDF not committed). Resolvable only by OCR + human verification.")
            doc = doc_text(o["id"], o["title"], url, sha, None, None, None, exc, related)
            o["text_layer"] = ("none" if words < MIN_WORDS else
                               f"garbage OCR ({words} words, {ratio:.0%} dictionary)")
            stub += 1
        out = out_dir / f"{o['id']}.md"
        out.write_text(doc)
        o["status"] = "ingested"
        o["path"] = str(out.relative_to(REPO_ROOT))
        o["sha256"] = sha
        made += 1
        if made % 50 == 0:
            print(f"...{made} ingested ({full} full-text, {stub} stubs)")
            CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True,
                                              width=100))
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    print(f"made {made} ({full} full-text, {stub} scan stubs), "
          f"failed {failed}, already-ingested {skipped}")


def write_index():
    """Regenerate executive-orders/_index.md from the catalog (grouped by year)."""
    cat = yaml.safe_load(CATALOG.read_text())
    ingested = [o for o in cat["orders"] if o.get("status") == "ingested"]
    full = sum(1 for o in ingested if str(o.get("text_layer", "")).startswith("clean"))
    by_year = {}
    for o in ingested:
        yy = o["id"][3:5]
        by_year.setdefault(f"20{yy}", []).append(o)
    L = ["# Executive Orders — index",
         "",
         "Governor's executive orders 2003–present, from the listing of record (SharePoint",
         "list `/gov/eo` behind oregon.gov/gov/pages/executive-orders.aspx). Filenames:",
         "`eo-YY-NN.md` (suffixes `-letter`/`-a`/`-rev`/`-amended` are companion or amended",
         "files, `related`-linked to their base order). **Non-authoritative copies.**",
         "",
         f"{len(ingested)} orders ingested; {full} carry verbatim full text (the rest are",
         "image-only scans — metadata + link only, see the aggregated REVIEW.md entry).",
         "Orders are immutable; only NEW orders appear upstream (checked via the",
         "`executive-orders` update group). GENERATED by `src/ingest_eo.py` from",
         "`_meta/catalog/eo.yml` — do not edit by hand.",
         ""]
    for year in sorted(by_year, reverse=True):
        L.append(f"## {year}")
        L.append("")
        L.append("| Order | Title | Full text |")
        L.append("|---|---|---|")
        for o in sorted(by_year[year], key=lambda o: o["id"]):
            ft = "yes" if str(o.get("text_layer", "")).startswith("clean") else "—"
            title = (o["title"] or "(no description on the listing)").replace("|", "\\|")
            L.append(f"| [{o['id']}]({o['id']}.md) | {title} | {ft} |")
        L.append("")
    (REPO_ROOT / "executive-orders/_index.md").write_text("\n".join(L))
    print(f"executive-orders/_index.md: {len(ingested)} orders across {len(by_year)} years")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enumerate", action="store_true")
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--index", action="store_true", help="regenerate _index.md only")
    ap.add_argument("--limit", type=int, default=None, help="ingest at most N (testing)")
    args = ap.parse_args()
    if args.enumerate:
        cmd_enumerate()
    elif args.ingest:
        cmd_ingest(args.limit)
        write_index()
    elif args.index:
        write_index()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
