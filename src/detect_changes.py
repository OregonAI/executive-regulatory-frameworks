#!/usr/bin/env python3
"""All-groups upstream sweep (manual workflow_dispatch path). Re-fetches every
source in every _meta/sources/<group>.yml, diffs content hashes and SharePoint
listings, writes changed-sources.tsv and a changed=true/false GitHub output.
For on-demand, group-scoped checking use check_updates.py (the /check-updates
skill drives it). Exit code is 0 unless a fetch fails outright — a changed
source is a signal, not an error."""
import argparse
import hashlib
import sys
import urllib.request

import yaml

from repo_lib import REPO_ROOT, content_hash, source_groups

USER_AGENT = "oregon-policy-repo-change-detector (+https://github.com/morficflux/oregon-policy-repo)"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


LISTING_SNAPSHOTS = {
    "oam-listing": "oam-listing.json",
    "administrative-services-department-policies-listing": "administrative-services-department-policies-listing.json",
}


def _fetch_view_rows(web, list_path, guid):
    url = (f"https://www.oregon.gov{web}/_api/web/GetList('{list_path}')/"
           f"RenderListDataAsStream?View={guid}")
    body = b'{"parameters":{"__metadata":{"type":"SP.RenderListDataParameters"},"RenderOptions":2}}'
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json;odata=verbose",
        "Content-Type": "application/json;odata=verbose"})
    import json
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["Row"]


def check_sp_listing(snapshot_name):
    """Re-query a SharePoint listing's views (same data the official page renders) and
    diff normalized rows against the committed snapshot. Diff rules per the listing of
    record: key on document id + file path; a change = effective date changed; rows
    keyed only one way so adds/removals are also flagged."""
    import json
    snap = json.loads((REPO_ROOT / "_meta/snapshots" / snapshot_name).read_text())
    cfg = snap["checker"]
    diffs = []
    # stored rows: OAM nests under chapters; policies is a flat rows list
    stored_by_view = {}
    if "chapters" in snap:
        for ch, c in snap["chapters"].items():
            stored_by_view[ch] = {r["id"] + "|" + r["file_ref"]: r["effective_date"]
                                  for r in c["rows"]}
    else:
        flat = {}
        for r in snap["rows"]:
            flat[r["number"] + "|" + r["file_ref"]] = r["effective_date"]
        # live side is per-view; compare against the union once
        stored_by_view["*"] = flat

    if "chapters" in snap:
        for ch in snap["chapters"]:
            rows = _fetch_view_rows(cfg["web"], cfg["list"], snap["views"][ch])
            live = {(r.get(cfg["id_field"]) or "").strip() + "|" + (r.get("FileRef") or ""):
                    (r.get(cfg["date_field"]) or "") for r in rows}
            stored = stored_by_view[ch]
            for k in stored.keys() - live.keys():
                diffs.append(f"{ch} REMOVED: {k}")
            for k in live.keys() - stored.keys():
                diffs.append(f"{ch} ADDED: {k}")
            for k in stored.keys() & live.keys():
                if stored[k] != live[k]:
                    diffs.append(f"{ch} DATE CHANGED: {k}: {stored[k]!r} -> {live[k]!r}")
    else:
        live = {}
        for name, guid in snap["views"].items():
            for r in _fetch_view_rows(cfg["web"], cfg["list"], guid):
                key = (r.get(cfg["id_field"]) or "").strip() + "|" + (r.get("FileRef") or "")
                live[key] = (r.get(cfg["date_field"]) or "")
        stored = stored_by_view["*"]
        for k in stored.keys() - live.keys():
            diffs.append(f"REMOVED: {k}")
        for k in live.keys() - stored.keys():
            diffs.append(f"ADDED: {k}")
        for k in stored.keys() & live.keys():
            if stored[k] != live[k]:
                diffs.append(f"DATE CHANGED: {k}: {stored[k]!r} -> {live[k]!r}")
    return diffs


def main():
    """All-groups sweep for the manual workflow_dispatch path. On-demand, scoped
    checking lives in check_updates.py (driven by the /check-updates skill)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--github-output", help="path to $GITHUB_OUTPUT")
    args = ap.parse_args()

    changed, failed = [], []
    for gpath, g in source_groups():
        if g["kind"] == "sp-listing":
            snap_name = g["listing_snapshot"].rsplit("/", 1)[-1]
            try:
                diffs = check_sp_listing(snap_name)
            except Exception as e:
                failed.append(g["group"] + "-listing")
                print(f"FETCH FAILED {g['group']} listing ({e})")
                diffs = []
            if diffs:
                changed.append((g["group"] + "-listing", g["upstream_signal"], "listing", "listing"))
                print(f"CHANGED  {g['group']} listing: {len(diffs)} difference(s)")
                for d in diffs[:20]:
                    print(f"    {d}")
        for s in g["sources"]:
            sid, url, old = s["id"], s["url"], s["sha256"]
            path = url.lower().split("?")[0]
            ext = path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else "html"
            fmt = ext if ext in ("pdf", "xls", "xlsx", "docx", "xml") else "html"
            try:
                new = content_hash(fetch(url), fmt)
            except Exception as e:
                failed.append(sid)
                print(f"FETCH FAILED {sid}: {url} ({e})")
                continue
            if new != old:
                changed.append((sid, url, old, new))
                print(f"CHANGED  {sid}: {old[:12]}… -> {new[:12]}…")

    out = REPO_ROOT / "changed-sources.tsv"
    out.write_text("".join(f"{a}\t{b}\t{c}\t{d}\n" for a, b, c, d in changed))
    if args.github_output:
        with open(args.github_output, "a") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
    print(f"\n{len(changed)} changed, {len(failed)} fetch failure(s).")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
