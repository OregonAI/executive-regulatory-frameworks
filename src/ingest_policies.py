#!/usr/bin/env python3
"""Mechanically ingest an agency's published policy PDFs as full-text-first documents.

Generalizes agency-policy intake (agency #2+; DAS was done ad hoc). Driven by a policies
source group under _meta/sources/<slug>-policies.yml. Two phases:

  python3 src/ingest_policies.py <group> --discover   # parse the agency's listing page,
                                                       # write the sources: list (GATE #1:
                                                       # a human reviews the list)
  python3 src/ingest_policies.py <group>               # ingest every source in the group
  python3 src/ingest_policies.py <group> --only doc-10-1-2 [...]   # subset
  python3 src/ingest_policies.py <group> --limit 5     # first N (build/verify)

Per source: fetch the PDF (magic-byte check) -> snapshot _meta/snapshots/<id>.pdf +
pdftotext -layout <id>.txt -> content-hash -> emit a verbatim doc via the policy template,
placed with ingest_lib.output_dir_for. Header fields (title, policy number, effective /
supersedes dates) are transcribed from the PDF's OWN labeled header — never inferred (HC-1).
Idempotent/resumable; a fetch/parse failure is logged and skipped, never fabricated.

Adding agency #3: add a POLICY_PROFILES entry (listing url + link/header regexes + citation
format) and, if its PDFs have running furniture, an AGENCY_FURNITURE entry in ingest_lib.
"""
import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from ingest_lib import clean_pdf_text, fetch, output_dir_for
from repo_lib import REPO_ROOT, SNAPSHOT_DIR, content_hash, normalize_ws

SOURCES_DIR = REPO_ROOT / "_meta" / "sources"
TODAY = date.today().isoformat()
HANDLE = "@morficflux"


def iso_date(s: str) -> str | None:
    """'04/14/21' or '4/14/2021' -> '2021-04-14'. None if unparseable (never guessed)."""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$", s or "")
    if not m:
        return None
    mo, d, y = (int(x) for x in m.groups())
    if y < 100:
        y += 2000 if y < 70 else 1900
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


# ---- per-agency profiles ----
# Each profile knows how to (a) discover its listing and (b) read its PDF header.
POLICY_PROFILES = {
    "department-of-corrections": {
        "agency": "department-of-corrections",
        "listing_url": "https://www.oregon.gov/doc/rules-and-policies/pages/policies.aspx",
        "site_root": "https://www.oregon.gov",
        # PDF links on the listing page
        "link_re": re.compile(r'href="(/doc/rules-and-policies/Documents/[^"]+\.pdf)"', re.I),
        # the doc's own header (page 1)
        "title_re": re.compile(r"Title:\s*(.+?)\s{2,}DOC Policy:", re.I),
        "num_re": re.compile(r"DOC Policy:\s*([\d.]+)", re.I),
        "effective_re": re.compile(r"Effective:\s*([\d/]+)", re.I),
        "supersedes_re": re.compile(r"Supersedes:\s*([\d/]+)", re.I),
        # the sub-banner line after "DEPARTMENT OF CORRECTIONS" is the issuing division
        "division_re": re.compile(r"DEPARTMENT OF CORRECTIONS\s+([A-Z][A-Za-z /&,-]{2,60}?)\s+Title:", re.S),
        "citation": lambda num: f"DOC Policy {num}",
        "id": lambda num: "doc-" + num.replace(".", "-"),
        "issuing_default": "Oregon Department of Corrections",
        "authority_level": "state_policy",
        "tags": ["department-of-corrections", "policy"],
    },
}


def profile_for(group_data: dict) -> dict:
    slug = group_data["group"].replace("-policies", "")
    prof = POLICY_PROFILES.get(slug)
    if not prof:
        sys.exit(f"no POLICY_PROFILES entry for agency {slug!r} — add one (see module docstring)")
    return prof


# ---- discovery ----
def discover(group_path: Path, gd: dict, prof: dict):
    html = fetch(prof["listing_url"]).decode("utf-8", errors="replace")
    seen, sources = set(), []
    for href in prof["link_re"].findall(html):
        url = prof["site_root"] + href
        fname = href.rsplit("/", 1)[-1]
        # provisional id from the filename number prefix (e.g. 10-1-2-telecom.pdf -> doc-10-1-2);
        # the authoritative id/citation come from the PDF header at ingest time.
        mnum = re.match(r"(\d+-\d+-\d+)", fname)
        pid = "doc-" + mnum.group(1) if mnum else "doc-" + re.sub(r"\.pdf$", "", fname)
        if pid in seen:
            continue
        seen.add(pid)
        sources.append({"id": pid, "url": url, "sha256": "TODO",
                        "last_checked": TODAY, "notes": fname})
    gd["sources"] = sources
    gd["kind"] = "content-hash"
    gd["upstream_signal"] = (f"Static HTML listing of numbered policy PDFs at {prof['listing_url']} "
                             "(not a SharePoint list). Freshness: re-fetch the page and diff the "
                             "PDF-link set; re-hash members.")
    gd["last_checked"] = TODAY
    group_path.write_text(yaml.safe_dump(gd, sort_keys=False, allow_unicode=True, width=100))
    print(f"discovered {len(sources)} policy PDFs -> {group_path.relative_to(REPO_ROOT)}")


_HDR_LABEL = re.compile(r"^(Applicability|Supersedes|Directives|Attachments|Security Level)\b", re.I)


def doc_header_title(raw_txt: str):
    """(division, title) from a DOC policy header. Handles both layouts: title on the
    'Title:' line, and title centered on separate lines above/below the label (long/
    two-line titles). The division is the banner's second line (e.g. 'Information Systems')."""
    head = re.split(r"\n\s*Effective:", raw_txt, 1)[0]
    lines = head.splitlines()
    bi = next((i for i, l in enumerate(lines) if "DEPARTMENT OF CORRECTIONS" in l.upper()), -1)
    division, title_parts = "", []
    for l in lines[bi + 1:] if bi >= 0 else lines:
        s = re.sub(r"\s+", " ", l).strip()
        if not s:
            continue
        if not division and "DOC Policy:" not in s and not s.lower().startswith("title:"):
            division = s
            continue
        if "Title:" in s or "DOC Policy:" in s:              # label line — may carry title text
            rest = re.sub(r"DOC Policy:.*", "", s)
            rest = re.sub(r".*Title:\s*", "", rest).strip()
            if rest:
                title_parts.append(rest)
            continue
        if _HDR_LABEL.match(s):
            continue
        title_parts.append(s)
    return division, re.sub(r"\s+", " ", " ".join(title_parts)).strip()


# ---- ingest one ----
def doc_markdown(prof, num, title, division, url, sha, effective, supersedes, raw_txt):
    doc_id = prof["id"](num)
    citation = prof["citation"](num)
    eff_iso = iso_date(effective)
    body, conv = clean_pdf_text(raw_txt, prof["agency"])
    eff_field = f'"{eff_iso}"' if eff_iso else "null"
    src_ver = f"Effective {effective}" if effective else ""
    sup_field = f'"Superseded policy dated {supersedes}"' if supersedes else "null"
    glance = f"{citation} — {title}. {prof['issuing_default']}."
    if eff_iso:
        glance += f" Effective {effective}."
    fm = f"""---
id: {doc_id}
title: "{title.replace(chr(34), chr(39))}"
doc_type: policy
citation: "{citation}"
authority_level: {prof['authority_level']}
issuing_body: "{(division or prof['issuing_default']).replace(chr(34), chr(39))}"
agency: {prof['agency']}
legal_authority: []
source_url: "{url}"
source_format: pdf
retrieved: "{TODAY}"
source_sha256: "{sha}"
effective_date: {eff_field}
last_reviewed: null
source_version: "{src_ver}"
status: current
supersedes: {sup_field}
content_mode: verbatim
conversion_notes: "{conv.replace(chr(34), chr(39))}"
last_verified: "{TODAY}"
verified_by: "{HANDLE}"
maintainer: "{HANDLE}"
relationships:
  implements: []
  implemented_by: []
  references_external: []
  related: []
  supersedes: []
tags: {prof['tags']}
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated copy of the
> official text. Verify against the official source: <{url}> (retrieved {TODAY}).

# {title} ({citation})

## At a glance

{glance}

## Full text

{body}

## Provenance & change history

- Source: <{url}> · retrieved {TODAY} · sha256 `{sha}`
- Snapshot: `_meta/snapshots/{doc_id}.pdf`
- See [CHANGELOG](./CHANGELOG.md).
"""
    return doc_id, fm


def ingest_one(prof, src, out_dir) -> dict:
    """Returns {status, id, sha, msg}. status: 'ok' | 'skip' | 'fail'."""
    url = src["url"]
    prov_id = src["id"]
    try:
        raw = fetch(url)
    except Exception as e:
        return {"status": "fail", "id": prov_id, "msg": f"FETCH_FAIL {prov_id}: {e}"}
    if raw[:5] != b"%PDF-":
        return {"status": "skip", "id": prov_id, "msg": f"NOT_PDF {prov_id}"}
    pdf_path = SNAPSHOT_DIR / f"{prov_id}.pdf"
    pdf_path.write_bytes(raw)
    proc = subprocess.run(["pdftotext", "-layout", str(pdf_path), "-"], capture_output=True)
    raw_txt = proc.stdout.decode("utf-8", errors="replace")
    if len(normalize_ws(raw_txt)) < 200:
        pdf_path.unlink(missing_ok=True)
        return {"status": "skip", "id": prov_id,
                "msg": f"NO_TEXT {prov_id} (image-only/empty; needs OCR/human review)"}
    mnum = prof["num_re"].search(raw_txt)
    if not mnum:
        pdf_path.unlink(missing_ok=True)
        return {"status": "skip", "id": prov_id,
                "msg": f"NON_POLICY {prov_id} ({src.get('notes','')}) — no policy number "
                       "(attachment/form); dropped from manifest"}
    num = mnum.group(1)
    doc_id = prof["id"](num)
    division, title = doc_header_title(raw_txt)
    if not title:
        title = src.get("notes", doc_id)
    me = prof["effective_re"].search(raw_txt)
    effective = me.group(1) if me else ""
    ms = prof["supersedes_re"].search(raw_txt)
    supersedes = ms.group(1) if ms else ""

    if doc_id != prov_id:
        pdf_path.rename(SNAPSHOT_DIR / f"{doc_id}.pdf")
    (SNAPSHOT_DIR / f"{doc_id}.txt").write_text(raw_txt, encoding="utf-8")
    sha = content_hash(raw, "pdf")
    _id, text = doc_markdown(prof, num, title, division, url, sha, effective, supersedes, raw_txt)
    (out_dir / f"{doc_id}.md").write_text(text, encoding="utf-8")
    return {"status": "ok", "id": doc_id, "sha": sha, "url": url,
            "notes": f"{title} (DOC {num})", "msg": f"OK {doc_id} (DOC {num})"}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("group", help="source group name, e.g. department-of-corrections-policies")
    ap.add_argument("--discover", action="store_true", help="(re)build the sources: list from the listing page")
    ap.add_argument("--only", nargs="*", help="ingest only these source ids")
    ap.add_argument("--limit", type=int, help="ingest only the first N sources")
    args = ap.parse_args()

    group_path = SOURCES_DIR / f"{args.group}.yml"
    if not group_path.is_file():
        sys.exit(f"no such source group: {group_path}")
    gd = yaml.safe_load(group_path.read_text())
    prof = profile_for(gd)

    if args.discover:
        discover(group_path, gd, prof)
        return

    out_dir = output_dir_for("policy", prof["agency"])
    out_dir.mkdir(parents=True, exist_ok=True)
    sources = gd.get("sources") or []
    if args.only:
        sources = [s for s in sources if s["id"] in set(args.only)]
    if args.limit:
        sources = sources[:args.limit]
    if not sources:
        sys.exit("no sources to ingest (run --discover first?)")

    results = {}
    made = skipped = resumed = 0
    for s in sources:
        # resume: a source with a real hash was already ingested — skip (idempotent reruns)
        if not args.only and s.get("sha256") and s["sha256"] != "TODO":
            resumed += 1
            continue
        res = ingest_one(prof, s, out_dir)
        print(res["msg"])
        results[s["id"]] = res
        if res["status"] == "ok":
            made += 1
        else:
            skipped += 1

    # Write real sha256/id back into the manifest; drop processed non-policy attachments.
    # Sources not processed this run (subset --only/--limit) are left untouched.
    new_sources = []
    for s in gd.get("sources") or []:
        r = results.get(s["id"])
        if r is None:
            new_sources.append(s)                       # not processed this run
        elif r["status"] == "ok":
            new_sources.append({"id": r["id"], "url": r["url"], "sha256": r["sha"],
                                "last_checked": TODAY, "notes": r["notes"]})
        # status skip/fail with no PDF/number -> dropped
    gd["sources"] = new_sources
    gd["last_checked"] = TODAY
    group_path.write_text(yaml.safe_dump(gd, sort_keys=False, allow_unicode=True, width=100))
    print(f"\ndone: {made} ingested, {skipped} dropped/skipped, {resumed} already-done "
          f"(of {len(sources)}); manifest now has {len(new_sources)} sources")


if __name__ == "__main__":
    main()
