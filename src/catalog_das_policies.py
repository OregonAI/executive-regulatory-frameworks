#!/usr/bin/env python3
"""Generator for the DAS statewide-policies listing snapshot and its discovery catalog.

  python3 src/catalog_das_policies.py --refresh   # re-query the 14 live views the
                                                    # committed snapshot names; rebuild the
                                                    # snapshot + catalog. NEVER ingests
                                                    # ADDED rows (intake gate #1) -- exits
                                                    # nonzero and names them instead.
  python3 src/catalog_das_policies.py --check      # CI: the committed catalog must be
                                                    # exactly what rebuilding from the
                                                    # committed snapshot (+ the catalog's
                                                    # own status/path/note/type, the only
                                                    # curated fields) produces.
  python3 src/catalog_das_policies.py --selftest   # every rule --check enforces,
                                                    # demonstrated failing

WHY THIS EXISTS (#387). `_meta/snapshots/department-of-administrative-services-policies-
listing.json` and `_meta/catalog/department-of-administrative-services-policies.yml` were
built ad hoc (f5eb8ff1, 2026-07-18) -- no generator was ever committed, so nothing could
refresh either file without hand-editing them. DAS re-issued its statewide policies in
August 2026; the committed listing and catalog kept reporting July. This is the generator
that should have existed from the start.

ADDED ROWS ARE NEVER INGESTED HERE. A live row whose file_ref this repo's catalog has never
carried is left OUT of the rebuilt catalog and printed for a human (AGENTS.md / the
check-updates skill, intake gate #1). `--refresh` exits nonzero whenever it finds one, so a
caller driving it cheaply cannot miss it in silent output.

A row this repo already tracks (by file_ref -- the SharePoint identity that survives a
title or annotation change; measured against the August 2026 re-issue: all five retitled
policies and the one dropped procedure kept the same file_ref) that drops out of every live
view is NOT deleted from the catalog. A document absent from a listing is not a withdrawn
document (AGENTS.md). Its row is kept, `status`/`path`/`type` untouched, with a `note`
recording that the live listing no longer carries it. Whether the underlying corpus
document is superseded, and by what evidence, is a separate, human/curator decision this
script does not make -- see #387's own resolution of das-107-009-0030_pr for an example.

`fetch_live_rows` is the only function here that touches the network, and only `--refresh`
calls it -- `--check`/`--selftest` read committed data alone, like every other gate in this
repo's `tests/gates.py`.
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repo_lib import REPO_ROOT  # noqa: E402

SNAPSHOT = REPO_ROOT / "_meta/snapshots/department-of-administrative-services-policies-listing.json"
CATALOG = REPO_ROOT / "_meta/catalog/department-of-administrative-services-policies.yml"

ANNOTATION_RE = re.compile(r"\s*\(under revision\)\s*$", re.I)
DROPPED_NOTE_RE = re.compile(r"^no longer in any live DAS policies view as of \d{4}-\d{2}-\d{2}\b")


def base_number(num: str) -> str:
    """A row's identity, stripped of a trailing listing annotation like '(under
    revision)' -- the annotation is state, not identity: DAS added and later removed one
    from 107-009-0030 without the underlying document changing."""
    return ANNOTATION_RE.sub("", num or "").strip()


def view_category_map(snapshot: dict) -> dict:
    """view label -> (category, subcategory), DERIVED from the snapshot's own rows rather
    than hand-typed -- each of the 14 views it names carries rows of exactly one
    (category, subcategory) pair (measured: 14 views, 14 pairs, 1:1). Raises rather than
    guessing if that stops holding, or if a view carries no rows to derive from at all."""
    out = {}
    for r in snapshot["rows"]:
        for v in r["views"]:
            pair = (r["category"], r["subcategory"])
            if v in out and out[v] != pair:
                raise SystemExit(f"view {v!r} carries rows in two categories "
                                 f"({out[v]!r} and {pair!r}) -- the 1:1 mapping this "
                                 f"script relies on no longer holds; map it by hand")
            out[v] = pair
    missing = set(snapshot["views"]) - set(out)
    if missing:
        raise SystemExit(f"view(s) {sorted(missing)} carry no rows in the committed "
                         f"snapshot, so this script cannot derive their category -- add "
                         f"them by hand before refreshing")
    return out


def fetch_live_rows(snapshot: dict) -> list:
    """Every row live in the 14 views the committed snapshot names, normalized into the
    snapshot's own row shape. A per-view fetch failure raises -- never silently drops a
    view's rows, which AGENTS.md's overriding rule treats as measuring the view empty."""
    from sp_listing import _fetch_view_rows
    cfg = snapshot["checker"]
    cat_map = view_category_map(snapshot)
    rows = []
    for label, guid in snapshot["views"].items():
        category, subcategory = cat_map[label]
        live = _fetch_view_rows(cfg["web"], cfg["list"], guid)
        for r in live:
            rows.append({
                "number": (r.get(cfg["id_field"]) or "").strip(),
                "title": r.get("Title_x0020_of_x0020_Policy.desc") or "",
                "effective_date": r.get(cfg["date_field"]) or "",
                "file_ref": r.get("FileRef") or "",
                "show": r.get("Show") or "",
                "category": category,
                "subcategory": subcategory,
                "views": [label],
            })
    return rows


def _sort_key(row):
    return (row["category"], row["subcategory"], base_number(row["number"]), row["file_ref"])


def diff_rows(old_rows: list, new_rows: list):
    """(added, removed, changed) file_refs -- the SharePoint identity that survives a
    title or annotation change. `changed` pairs (old row, new row) whose number, title or
    effective_date moved."""
    old_by_ref = {r["file_ref"]: r for r in old_rows}
    new_by_ref = {r["file_ref"]: r for r in new_rows}
    added = sorted(set(new_by_ref) - set(old_by_ref))
    removed = sorted(set(old_by_ref) - set(new_by_ref))
    changed = []
    for ref in sorted(set(old_by_ref) & set(new_by_ref)):
        o, n = old_by_ref[ref], new_by_ref[ref]
        if (o["number"], o["title"], o["effective_date"]) != (n["number"], n["title"], n["effective_date"]):
            changed.append((ref, o, n))
    return added, removed, changed


def build_snapshot(old_snapshot: dict, new_rows: list, retrieved: str) -> dict:
    """The static endpoint/view/checker metadata is carried over unchanged -- only
    `retrieved` and `rows` are this run's own."""
    out = dict(old_snapshot)
    out["retrieved"] = retrieved
    out["rows"] = sorted(new_rows, key=_sort_key)
    return out


def category_label(category: str, subcategory: str) -> str:
    return f"{category} / {subcategory}" if subcategory else category


def build_catalog(new_snapshot: dict, old_catalog: dict, retrieved: str) -> tuple:
    """(catalog, added_file_refs). `new_snapshot`'s rows are the live state; `old_catalog`
    supplies every curated field (`status`, `path`, `type`, `note`) this script never
    invents. `added_file_refs` -- live rows the catalog has never carried -- are named in
    the return value and left OUT of the rebuilt catalog: intake gate #1."""
    old_by_ref = {}
    old_label_by_ref = {}
    for cat in old_catalog.get("categories") or []:
        for d in cat.get("documents") or []:
            old_by_ref[d["file_ref"]] = d
            old_label_by_ref[d["file_ref"]] = cat["category"]

    by_label: dict = {}
    added = []
    for row in new_snapshot["rows"]:
        label = category_label(row["category"], row["subcategory"])
        old = old_by_ref.get(row["file_ref"])
        if old is None:
            added.append(row["file_ref"])
            continue
        doc = {
            "number": row["number"] or "(none)",
            "title": row["title"] or "(untitled)",
            "effective_date_listed": row["effective_date"] or None,
            "file_ref": row["file_ref"],
            "status": old["status"],
        }
        if "path" in old:
            doc["path"] = old["path"]
        if old.get("type"):
            doc["type"] = old["type"]
        if old.get("note"):
            doc["note"] = old["note"]
        by_label.setdefault(label, []).append(doc)

    # ROWS THIS REPO STILL TRACKS THAT DROPPED OUT OF EVERY LIVE VIEW. Not deleted --
    # AGENTS.md: a document absent from a listing is not a withdrawn document. Kept under
    # the category label the catalog last placed them in (nothing live names one now), and
    # the "dropped" note is written ONCE -- DROPPED_NOTE_RE makes this idempotent across
    # repeated rebuilds, so --check does not see a note that grows a new sentence every run.
    live_refs = {r["file_ref"] for r in new_snapshot["rows"]}
    for ref, old in old_by_ref.items():
        if ref in live_refs:
            continue
        doc = dict(old)
        if not DROPPED_NOTE_RE.match(old.get("note") or ""):
            note = f"no longer in any live DAS policies view as of {retrieved}"
            if old.get("note"):
                note += f" — {old['note']}"
            doc["note"] = note
        by_label.setdefault(old_label_by_ref[ref], []).append(doc)

    categories = [
        {"category": label,
         "documents": sorted(docs, key=lambda d: base_number(d["number"]))}
        for label, docs in sorted(by_label.items())
    ]
    catalog = {
        "note": old_catalog["note"],
        "listing_snapshot": old_catalog["listing_snapshot"],
        "retrieved": retrieved,
        "categories": categories,
    }
    # PASSED THROUGH, NEVER DERIVED: documents linked outside all 14 views (e.g.
    # das-107-011-050_pr, linked only from the Surplus section of policies.aspx) carry no
    # file_ref this script's live fetch will ever see, so there is nothing to diff them
    # against -- they are curated data, not a view of the listing.
    if "listed_via_static_links_not_views" in old_catalog:
        catalog["listed_via_static_links_not_views"] = old_catalog["listed_via_static_links_not_views"]
    return catalog, sorted(added)


def cmd_refresh() -> int:
    old_snapshot = json.loads(SNAPSHOT.read_text())
    old_catalog = yaml.safe_load(CATALOG.read_text())
    today = date.today().isoformat()

    new_rows = fetch_live_rows(old_snapshot)
    _, removed, changed = diff_rows(old_snapshot["rows"], new_rows)

    new_snapshot = build_snapshot(old_snapshot, new_rows, today)
    new_catalog, added = build_catalog(new_snapshot, old_catalog, today)

    # indent=1: matches the committed snapshot's own formatting (f5eb8ff1) so a refresh
    # with no real change diffs as nothing, not a whole-file re-indent.
    SNAPSHOT.write_text(json.dumps(new_snapshot, indent=1, ensure_ascii=False, sort_keys=False) + "\n")
    CATALOG.write_text(yaml.safe_dump(new_catalog, sort_keys=False, allow_unicode=True, width=110))

    print(f"refreshed {SNAPSHOT.relative_to(REPO_ROOT)}: {len(new_rows)} row(s) "
         f"(was {len(old_snapshot['rows'])}), retrieved {today}")
    print(f"rebuilt {CATALOG.relative_to(REPO_ROOT)} from the refreshed snapshot")

    if removed:
        print(f"\nREMOVED from every live view ({len(removed)}) -- kept in the catalog, "
             f"noted, NOT deleted:")
        for ref in removed:
            print(f"  {ref}")
    if changed:
        print(f"\nCHANGED ({len(changed)}):")
        for ref, o, n in changed:
            print(f"  {ref}")
            print(f"    number:  {o['number']!r} -> {n['number']!r}")
            print(f"    title:   {o['title']!r} -> {n['title']!r}")
            print(f"    date:    {o['effective_date']!r} -> {n['effective_date']!r}")
    if added:
        print(f"\nADDED -- new to this listing, NOT ingested (intake gate #1). For human "
             f"review ({len(added)}):")
        for ref in added:
            print(f"  {ref}")
        return 1
    return 0


def cmd_check() -> int:
    snapshot = json.loads(SNAPSHOT.read_text())
    catalog = yaml.safe_load(CATALOG.read_text())
    rebuilt, added = build_catalog(snapshot, catalog, catalog.get("retrieved", ""))
    bad = []
    if added:
        bad.append(f"the committed catalog is missing {len(added)} row(s) the committed "
                  f"snapshot carries and no category explains: {added[:10]}")
    if rebuilt != catalog:
        bad.append("the committed catalog is not what rebuilding from the committed "
                  "snapshot (preserving the catalog's own status/path/type/note) "
                  "produces -- it was hand-edited, or the snapshot moved without a "
                  "rebuild. Run `python3 src/catalog_das_policies.py --refresh`.")
    if bad:
        for b in bad:
            print(f"FAIL: {b}")
        return 1
    n_docs = sum(len(c["documents"]) for c in catalog["categories"])
    print(f"DAS policies catalog: {n_docs} row(s) across {len(catalog['categories'])} "
         f"categories, matches the committed snapshot exactly (retrieved "
         f"{catalog.get('retrieved')}).")
    return 0


# ---------------------------------------------------------------- selftest

def _fixture():
    """A tiny, self-contained snapshot/catalog pair -- one view, three rows -- shaped like
    the real files but small enough to mutate cheaply. Never touches the committed files or
    the network."""
    snapshot = {
        "note": "fixture", "list_url": "/x/Policies",
        "api": "POST https://example.invalid/x", "views": {"General": "guid-1"},
        "retrieved": "2026-07-18",
        "checker": {"web": "/x", "list": "/x/Policies", "id_field": "Number",
                   "date_field": "Effective_x0020_date"},
        "rows": [
            {"number": "1-000-01", "title": "Kept As-Is", "effective_date": "1/1/2020",
             "file_ref": "/x/Policies/1-000-01.pdf", "show": "Yes",
             "category": "General", "subcategory": "", "views": ["General"]},
            {"number": "1-000-02 (under revision)", "title": "Old Title",
             "effective_date": "1/1/2020", "file_ref": "/x/Policies/1-000-02.pdf",
             "show": "Yes", "category": "General", "subcategory": "", "views": ["General"]},
            {"number": "1-000-03", "title": "Will Be Dropped", "effective_date": "1/1/2020",
             "file_ref": "/x/Policies/1-000-03.pdf", "show": "Yes",
             "category": "General", "subcategory": "", "views": ["General"]},
        ],
    }
    catalog = {
        "note": "fixture catalog", "listing_snapshot": "_meta/snapshots/fixture.json",
        "retrieved": "2026-07-18",
        "categories": [{"category": "General", "documents": [
            {"number": "1-000-01", "title": "Kept As-Is", "effective_date_listed": "1/1/2020",
             "file_ref": "/x/Policies/1-000-01.pdf", "status": "ingested", "path": "a.md"},
            {"number": "1-000-02 (under revision)", "title": "Old Title",
             "effective_date_listed": "1/1/2020", "file_ref": "/x/Policies/1-000-02.pdf",
             "status": "ingested", "path": "b.md"},
            {"number": "1-000-03", "title": "Will Be Dropped",
             "effective_date_listed": "1/1/2020", "file_ref": "/x/Policies/1-000-03.pdf",
             "status": "ingested", "path": "c.md"},
        ]}],
    }
    return snapshot, catalog


def cmd_selftest() -> int:
    fails = []

    # base_number strips the annotation and only the annotation.
    if base_number("107-009-0030 (under revision)") != "107-009-0030":
        fails.append("FAIL base_number-strips-the-under-revision-annotation")
    if base_number("40-080-01") != "40-080-01":
        fails.append("FAIL base_number-leaves-an-unannotated-number-alone")

    # view_category_map derives the 1:1 mapping and refuses when it does not hold.
    snap, _ = _fixture()
    if view_category_map(snap) != {"General": ("General", "")}:
        fails.append("FAIL view-category-map-derives-the-1-1-mapping")
    conflicting = json.loads(json.dumps(snap))
    conflicting["rows"][0]["category"] = "Other"
    try:
        view_category_map(conflicting)
        fails.append("FAIL a-view-mapped-to-two-categories-is-refused: no SystemExit raised")
    except SystemExit:
        pass
    no_rows = json.loads(json.dumps(snap))
    no_rows["views"]["Extra"] = "guid-2"
    try:
        view_category_map(no_rows)
        fails.append("FAIL a-view-with-no-rows-to-derive-from-is-refused: no SystemExit raised")
    except SystemExit:
        pass

    # build_catalog round-trips an UNCHANGED live state back to the same catalog.
    snap, cat = _fixture()
    rebuilt, added = build_catalog(snap, cat, cat["retrieved"])
    if added:
        fails.append(f"FAIL an-unchanged-refresh-adds-nothing: {added}")
    if rebuilt != cat:
        fails.append("FAIL an-unchanged-refresh-round-trips-the-catalog-exactly")

    # A row new to the listing is reported and left OUT of the rebuilt catalog.
    snap, cat = _fixture()
    snap["rows"].append({
        "number": "1-000-09", "title": "Brand New", "effective_date": "1/1/2026",
        "file_ref": "/x/Policies/1-000-09.pdf", "show": "Yes",
        "category": "General", "subcategory": "", "views": ["General"]})
    rebuilt, added = build_catalog(snap, cat, "2026-09-14")
    if added != ["/x/Policies/1-000-09.pdf"]:
        fails.append(f"FAIL an-added-row-is-reported: got {added}")
    if any(d["file_ref"] == "/x/Policies/1-000-09.pdf"
          for c in rebuilt["categories"] for d in c["documents"]):
        fails.append("FAIL an-added-row-is-never-placed-in-the-rebuilt-catalog "
                    "(intake gate #1)")

    # A row DROPPED from every live view is kept, not deleted, and noted once.
    snap, cat = _fixture()
    snap["rows"] = [r for r in snap["rows"] if r["file_ref"] != "/x/Policies/1-000-03.pdf"]
    rebuilt, added = build_catalog(snap, cat, "2026-09-14")
    kept = next((d for c in rebuilt["categories"] for d in c["documents"]
                if d["file_ref"] == "/x/Policies/1-000-03.pdf"), None)
    if kept is None:
        fails.append("FAIL a-dropped-row-is-kept-not-deleted: absent from the rebuilt catalog")
    elif kept["status"] != "ingested" or kept["path"] != "c.md":
        fails.append(f"FAIL a-dropped-rows-status-and-path-are-preserved: {kept}")
    elif "2026-09-14" not in (kept.get("note") or ""):
        fails.append(f"FAIL a-dropped-row-is-noted-with-the-date-it-dropped: {kept}")
    else:
        # Rebuilding a SECOND time (the row still absent) must not grow the note.
        rebuilt2, _ = build_catalog(snap, rebuilt, "2026-09-21")
        kept2 = next(d for c in rebuilt2["categories"] for d in c["documents"]
                    if d["file_ref"] == "/x/Policies/1-000-03.pdf")
        if kept2["note"] != kept["note"]:
            fails.append(f"FAIL a-dropped-rows-note-is-written-once-not-every-rebuild: "
                        f"{kept['note']!r} -> {kept2['note']!r}")

    # diff_rows sees an annotation dropping as a CHANGE (same file_ref), not an add+remove.
    snap, _ = _fixture()
    old_rows = snap["rows"]
    new_rows = json.loads(json.dumps(old_rows))
    new_rows[1]["number"] = "1-000-02"  # the "(under revision)" row, annotation dropped
    added, removed, changed = diff_rows(old_rows, new_rows)
    if added or removed:
        fails.append(f"FAIL diff-rows-keys-on-file-ref-not-number: added={added} removed={removed}")
    if not any(ref == "/x/Policies/1-000-02.pdf" for ref, _, _ in changed):
        fails.append("FAIL diff-rows-reports-an-annotation-drop-as-a-change")

    # cmd_check's rules, exercised without touching the real committed files: a hand-edit
    # (a title changed with nothing re-derived) must be caught.
    snap, cat = _fixture()
    hand_edited = json.loads(json.dumps(cat))
    hand_edited["categories"][0]["documents"][0]["title"] = "Hand-Typed, Never Rebuilt"
    rebuilt, added = build_catalog(snap, hand_edited, hand_edited["retrieved"])
    if rebuilt == hand_edited:
        fails.append("FAIL a-hand-edited-catalog-disagrees-with-a-rebuild: "
                    "the mutation was not detected")

    for f in fails:
        print(f)
    if fails:
        print(f"{len(fails)} rule(s) did not hold")
        return 1
    print("catalog_das_policies: every rule --check and --refresh enforce held against a "
         "fixture, including the two guards that must not fire (an unchanged refresh "
         "round-trips; a dropped row's note is written once).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return cmd_selftest()
    if a.refresh:
        return cmd_refresh()
    return cmd_check()


if __name__ == "__main__":
    sys.exit(main())
