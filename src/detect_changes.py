#!/usr/bin/env python3
"""Re-fetch every source in _meta/source-manifest.yml and compare content hashes.
Writes changed-sources.tsv (id, url, old sha256, new sha256) and, with
--github-output FILE, a changed=true/false output for the workflow. Exit code is
0 unless a fetch fails outright — a changed source is a signal, not an error."""
import argparse
import hashlib
import sys
import urllib.request

import yaml

from repo_lib import MANIFEST_PATH, REPO_ROOT, content_hash

USER_AGENT = "oregon-policy-repo-change-detector (+https://github.com/morficflux/oregon-policy-repo)"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def check_oam_listing():
    """Re-query the 16 OAM chapter views (SharePoint REST, same data the official page
    renders) and diff normalized rows (id | effective_date | file_ref) against the
    committed snapshot. Diff rules per the listing of record: key on document id; a
    change = effective date or file path changed. Returns list of difference strings."""
    import json
    snap = json.loads((REPO_ROOT / "_meta/snapshots/oam-listing.json").read_text())
    diffs = []
    for ch, c in snap["chapters"].items():
        guid = snap["views"][ch]
        url = ("https://www.oregon.gov/das/Financial/Acctng/_api/web/"
               "GetList('/das/Financial/Acctng/Documents')/RenderListDataAsStream"
               f"?View={guid}")
        body = b'{"parameters":{"__metadata":{"type":"SP.RenderListDataParameters"},"RenderOptions":2}}'
        req = urllib.request.Request(url, data=body, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json;odata=verbose",
            "Content-Type": "application/json;odata=verbose"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        live = {}
        for r in data["Row"]:
            key = (r.get("Alpha_x002f_Number") or "").strip() + "|" + (r.get("FileRef") or "")
            live[key] = (r.get("Effective_x0020_Date") or "")
        stored = {}
        for r in c["rows"]:
            stored[r["id"] + "|" + r["file_ref"]] = r["effective_date"]
        for k in stored.keys() - live.keys():
            diffs.append(f"ch{ch} REMOVED: {k}")
        for k in live.keys() - stored.keys():
            diffs.append(f"ch{ch} ADDED: {k}")
        for k in stored.keys() & live.keys():
            if stored[k] != live[k]:
                diffs.append(f"ch{ch} DATE CHANGED: {k}: {stored[k]!r} -> {live[k]!r}")
    return diffs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--github-output", help="path to $GITHUB_OUTPUT")
    args = ap.parse_args()

    manifest = yaml.safe_load(MANIFEST_PATH.read_text())
    changed, failed = [], []
    for src in manifest.get("sources", []):
        sid, url, old = src["id"], src["url"], src["sha256"]
        if sid == "oam-listing":
            try:
                diffs = check_oam_listing()
            except Exception as e:
                failed.append(sid)
                print(f"FETCH FAILED {sid}: listing API ({e})")
                continue
            if diffs:
                changed.append((sid, url, "listing", "listing"))
                print(f"CHANGED  {sid}: {len(diffs)} listing difference(s)")
                for d in diffs[:20]:
                    print(f"    {d}")
            else:
                print(f"unchanged {sid}")
            continue
        try:
            path = url.lower().split("?")[0]
            ext = path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else "html"
            fmt = ext if ext in ("pdf", "xls", "xlsx", "docx", "xml") else "html"
            new = content_hash(fetch(url), fmt)
        except Exception as e:
            failed.append(sid)
            print(f"FETCH FAILED {sid}: {url} ({e})")
            continue
        if new != old:
            changed.append((sid, url, old, new))
            print(f"CHANGED  {sid}: {old[:12]}… -> {new[:12]}…")
        else:
            print(f"unchanged {sid}")

    out = REPO_ROOT / "changed-sources.tsv"
    out.write_text("".join(f"{sid}\t{url}\t{old}\t{new}\n" for sid, url, old, new in changed))
    if args.github_output:
        with open(args.github_output, "a") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")

    print(f"\n{len(changed)} changed, {len(failed)} fetch failure(s).")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
