"""SharePoint-listing change checker — used by the /check-updates skill
(check_updates.py) for sp-listing-kind source groups. Deliberately NOT part
of corpus-toolkit's corpus-detect-changes: it re-queries a specific vendor's
list-view API (SharePoint RenderListDataAsStream), which doesn't generalize
to other corpora. Split out of the old src/detect_changes.py (now replaced
by the toolkit) so this Oregon-specific piece survives the migration."""
import json
import urllib.request

USER_AGENT = "executive-regulatory-frameworks-change-detector (+https://github.com/OregonAI/executive-regulatory-frameworks)"


def _fetch_view_rows(web, list_path, guid):
    url = (f"https://www.oregon.gov{web}/_api/web/GetList('{list_path}')/"
           f"RenderListDataAsStream?View={guid}")
    body = b'{"parameters":{"__metadata":{"type":"SP.RenderListDataParameters"},"RenderOptions":2}}'
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json;odata=verbose",
        "Content-Type": "application/json;odata=verbose"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["Row"]


def check_sp_listing(snapshot_name):
    """Re-query a SharePoint listing's views (same data the official page renders) and
    diff normalized rows against the committed snapshot. Diff rules per the listing of
    record: key on document id + file path; a change = effective date changed; rows
    keyed only one way so adds/removals are also flagged."""
    from repo_lib import REPO_ROOT
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
