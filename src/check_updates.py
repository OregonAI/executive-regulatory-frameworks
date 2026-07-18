#!/usr/bin/env python3
"""Group-scoped upstream update checker — the engine behind the /check-updates skill.

Groups are data (_meta/sources/<group>.yml); this tool is generic and never needs
changing when knowledge bodies or agencies are added. Output is deliberately terse
(silent on unchanged sources) so an agent can drive it cheaply.

  --due                 no-network report: which groups are due per their recheck cadence
  --group NAME ...      check specific group(s)
  --all                 check every group
  --refresh             with a check: re-fetch changed docs and regenerate their
                        '## Full text' (ingest_lib.refresh_document); rebuild changed
                        listing snapshots. Never auto-ingests listing ADDED rows
                        (intake gate #1: a human vets the list first).
"""
import argparse
import sys
from datetime import date, datetime

import yaml

from repo_lib import REPO_ROOT, content_files, content_hash, parse_frontmatter, source_groups

CADENCE_DAYS = {"weekly": 7, "monthly": 30, "quarterly": 90, "biennial": 730,
                "on_review_date": 365}


def days_since(iso: str) -> int:
    return (date.today() - datetime.strptime(iso, "%Y-%m-%d").date()).days


def report_due():
    for gpath, g in source_groups():
        age = days_since(g["last_checked"])
        limit = CADENCE_DAYS[g["recheck"]]
        state = "DUE" if age >= limit else "ok"
        print(f"{g['group']}: {state} (last checked {age}d ago; cadence {g['recheck']}; "
              f"{len(g['sources'])} source(s); signal: {g['upstream_signal']})")


def doc_paths_by_id():
    m = {}
    for p in content_files():
        fm, _ = parse_frontmatter(p)
        m.setdefault(fm.get("snapshot_id") or fm["id"], []).append(p)
        m.setdefault(fm["id"], []).append(p)
    return m


def check_group(gpath, g, refresh, today):
    from ingest_lib import fetch
    changed = []
    # 1) listing diff for sp-listing groups
    if g["kind"] == "sp-listing":
        from detect_changes import check_sp_listing
        snap_name = g["listing_snapshot"].rsplit("/", 1)[-1]
        try:
            diffs = check_sp_listing(snap_name)
        except Exception as e:
            print(f"{g['group']}: LISTING CHECK FAILED ({e})")
            diffs = None
        if diffs:
            print(f"{g['group']}: LISTING CHANGED — {len(diffs)} difference(s):")
            for d in diffs[:25]:
                print(f"  {d}")
            changed.append("listing")
            if refresh:
                print(f"  (listing snapshot NOT auto-rebuilt; ADDED rows require intake "
                      f"gate #1 — see the check-updates skill)")
    # 2) content hash per source
    docs = doc_paths_by_id()
    for s in g["sources"]:
        path_url = s["url"].lower().split("?")[0]
        ext = path_url.rsplit(".", 1)[-1] if "." in path_url.rsplit("/", 1)[-1] else "html"
        fmt = ext if ext in ("pdf", "xls", "xlsx", "docx", "xml") else "html"
        try:
            new = content_hash(fetch(s["url"]), fmt)
        except Exception as e:
            print(f"{g['group']}/{s['id']}: FETCH FAILED ({e})")
            continue
        if new != s["sha256"]:
            print(f"{g['group']}/{s['id']}: CHANGED {s['sha256'][:10]}… -> {new[:10]}…")
            changed.append(s["id"])
            if refresh:
                from ingest_lib import refresh_document
                for p in sorted(set(docs.get(s["id"], []))):
                    res = refresh_document(p, today)
                    print(f"  refresh {p.relative_to(REPO_ROOT)}: {res}")
                s["sha256"] = new
    # 3) bump last_checked
    g["last_checked"] = today
    for s in g["sources"]:
        s["last_checked"] = today
    gpath.write_text(yaml.safe_dump(g, sort_keys=False, allow_unicode=True, width=110))
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--due", action="store_true")
    ap.add_argument("--group", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    if args.due:
        report_due()
        return

    groups = dict(source_groups())
    names = {g["group"]: (p, g) for p, g in groups.items()}
    targets = list(names) if args.all else args.group
    if not targets:
        print("nothing to do: pass --due, --group NAME, or --all")
        sys.exit(2)
    today = date.today().isoformat()
    total_changed = 0
    for t in targets:
        if t not in names:
            print(f"unknown group: {t} (available: {', '.join(sorted(names))})")
            sys.exit(2)
        gpath, g = names[t]
        changed = check_group(gpath, g, args.refresh, today)
        total_changed += len(changed)
        if not changed:
            print(f"{t}: no changes ({len(g['sources'])} source(s) checked)")
    print(f"done: {total_changed} change(s) across {len(targets)} group(s)")


if __name__ == "__main__":
    main()
