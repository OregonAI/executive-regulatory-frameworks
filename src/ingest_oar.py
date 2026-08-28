#!/usr/bin/env python3
"""OAR chapter/division ingestion pipeline (full-text-first, HC-1 safe).

  python3 src/ingest_oar.py --ingest 125 128      # fetch each rule from OARD; emit docs
  python3 src/ingest_oar.py --selftest            # every rule, watched failing

Discovery of division/rule membership is `catalog_oar.py --discover` (OARD, since #270).
This module's `--ingest` fetches each rule's CONTENT from the authoritative OARD page
(view.action?ruleNumber=) for numbers the catalog already lists, and never discovers a
number on its own. Renumbering guard: if OARD serves a different rule number than
requested (the 125-800 -> 128-030 lesson), the document is filed under the SERVED number
and the mapping recorded in the catalog.

`--enumerate` is RETIRED (#276): it used to re-scrape oregon.public.law -- an unofficial
mirror #270 measured 2026-08-27 to omit 5,730 rules across the 168 chapters this corpus
then mirrored, missing chapters 419 and 950 entirely -- and rebuild each division's rule list
from ONLY that scrape's current output, with no guard against dropping a row the catalog
already held (`d["rules"] = [existing.get(n, ...) for n in rules]`, gone since #276: any
number `existing` held and this run's `rules` did not re-name -- history OARD's own
current-listing view does not repeat, same as its successor never repeats -- was silently
dropped). `catalog_oar.py --discover` reads OARD instead and merges non-destructively
(`merge_divisions` + `WouldRemoveRules`, watched failing before that guard existed). Two
scrapers wrote `_meta/catalog/oar.yml`'s division/rule membership; #276 makes it one."""
import argparse
import ast
import fcntl
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import yaml

from ingest_lib import fetch
from legal_status import bulletin_status_by_rule, resolve
from repo_lib import (REPO_ROOT, SNAPSHOT_DIR, Checks, content_hash, normalize_volatile,
                      rule_title_from_html, snapshot_slice, ws_only, snapshot_text)

CATALOG = REPO_ROOT / "_meta/catalog/oar.yml"
GROUP = REPO_ROOT / "_meta/sources/oar.yml"
TODAY = date.today().isoformat()

_DISCOVER_REPLACEMENT = "python3 src/catalog_oar.py --discover"


def cmd_enumerate(chapters):
    """RETIRED (#276): does not read or write anything -- not the catalog, not the
    network. A pure refusal, so anyone with `--enumerate` in a script or in muscle
    memory is told where the job moved rather than getting a silent no-op or, worse,
    the old destructive merge back."""
    sys.exit(
        "ingest_oar.py --enumerate is retired (#276). It used to re-scrape an unofficial "
        "mirror (see this module's docstring) and rebuild each division's rule list from "
        "that scrape alone, which could silently drop a rule row the catalog already "
        "held -- the same shape #270 fixed in catalog_oar.py's discovery, here left "
        "unguarded.\n"
        "Division/rule discovery is now catalog_oar.py --discover only, which reads OARD "
        "(the authoritative source) and merges non-destructively:\n"
        f"  {_DISCOVER_REPLACEMENT} " + " ".join(chapters))


def served_rule_number(text):
    m = re.search(r"\b(\d{3}-\d{3}-\d{4})\b", text)
    return m.group(1) if m else None


# OARD serves a RESULTS LIST, not a rule, when a number is ambiguous -- two rules sharing
# 836-054-0020 in the same chapter, for instance. The page still carries the number, still
# slices to something over the length floor, and still hashes; every existing guard passes
# it. What gets published is the titles of the rules that matched plus the site footer,
# under a document claiming to mirror one rule (#251).
#
# Declared once and read by both ingest paths: a predicate the two disagreed on would let
# the refresh republish exactly what the first ingest refused.
_RESULTS_LIST = re.compile(r"returned \d+ results\.\s*New Search")


def is_search_results_page(ws_text: str) -> bool:
    """True when this OARD page is a search-results list rather than a single rule."""
    return bool(_RESULTS_LIST.search(ws_text))


# THE INGESTER NO LONGER NAMES THE LEGAL STATUS. `status: current` used to be a hardcoded
# literal in the template below, written onto every one of the 36,953 rule documents this
# pipeline created. That is fine on a FIRST ingest -- nothing better is known about a rule
# OARD is serving normally -- and it is the whole hazard on a re-ingest: once #230 refreshes
# an amended rule automatically, the literal would restamp `current` over a repeal the
# Bulletin filed, resurrecting the rule silently and publishing a false statement about
# Oregon law under provenance. The value now arrives from `legal_status.resolve()`, which is
# the only thing that decides it (ADR 0006).
def doc_body(rule, title_line, url, sha, ch, div, status):
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
status: {status}
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


# Exactly the fields `cmd_ingest`'s loop ever assigns onto a rule row (`r["status"] = ...`,
# `r["note"] = ...`, `r["served_as"] = ...`, `r["path"] = ...`). `_write_catalog_merged`
# below copies only these, by number, onto the matching row already on disk -- never a
# whole row, and never anything about which rows or divisions exist.
_CHECKPOINT_FIELDS = ("status", "note", "served_as", "path")


def _write_catalog_merged(cat, my_chapters):
    """Concurrent-safe catalog save for parallel --ingest workers: under an exclusive
    lock, re-read the catalog from disk and write this worker's OWN field updates
    (`_CHECKPOINT_FIELDS`) onto the matching rule rows, by number, then write atomically.

    NEVER reassigns a chapter's `divisions` or a division's `rules` -- #276 measured that
    the retired shape one level up (`disk["chapters"] = [mine.get(c["chapter"], c) for c
    in disk["chapters"]]`) replaced a whole chapter with this worker's LOAD-TIME snapshot,
    so a row the same chapter gained on disk after this worker loaded -- a concurrent
    `catalog_oar.py --discover`, or simply an earlier checkpoint in this same run adding
    rows this worker's stale in-memory copy never saw -- was silently gone from the next
    checkpoint. Reproduced directly: a chapter holding 3 rules across 2 divisions on disk
    dropped to 1 rule across 1 division after one checkpoint from a worker whose in-memory
    copy predated the concurrent write. Merging by ROW instead of by chapter makes that
    shape structurally impossible: this function only ever sets a few named keys on a row
    dict already on disk -- the same idiom `cmd_ingest`'s own loop uses -- so disk's
    membership, however it grew since this worker loaded, survives every checkpoint
    untouched, and `--ingest` never removes a division or a rule row. Workers still own
    disjoint chapter sets (`my_chapters`), so two workers never race to update the same
    row; only the row-vs-chapter granularity of the write changed."""
    lock_path = REPO_ROOT / "_meta/.cache/oar-catalog.lock"
    lock_path.parent.mkdir(exist_ok=True)
    mine_rules = {r["number"]: r
                  for c in cat["chapters"] if c["chapter"] in my_chapters
                  for d in (c.get("divisions") or [])
                  for r in (d.get("rules") or [])}
    with open(lock_path, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        disk = yaml.safe_load(CATALOG.read_text())
        for c in disk["chapters"]:
            if c["chapter"] not in my_chapters:
                continue
            for d in (c.get("divisions") or []):
                for r in (d.get("rules") or []):
                    src = mine_rules.get(r["number"])
                    if src is None:
                        continue
                    for key in _CHECKPOINT_FIELDS:
                        if key in src:
                            r[key] = src[key]
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
    # What the Bulletin has said about each rule's legal force, read once for the run.
    bulletin = bulletin_status_by_rule(cat)
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
                text = snapshot_text(raw)
                wt = ws_only(text)
                served = served_rule_number(wt)
                # OARD's not-found shell echoes the requested number in its search box
                if served and re.search(re.escape(served) + r"\s+not found", wt):
                    served = None
                if is_search_results_page(wt):
                    # NOT `not_served`: OARD served something, and it is not this rule.
                    r["status"] = "not_sliceable"
                    r["note"] = ("OARD serves a search-results list for this number, not a "
                                 "rule -- more than one rule shares it (#251)")
                    skipped += 1
                    continue
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
                title_line = rule_title_from_html(raw.decode("utf-8", errors="replace"),
                                                  target) or f"OAR {target}"
                # Keyed on the SERVED number, not the requested one: a renumbered rule is
                # filed under the number OARD serves it as, and a Bulletin entry against
                # that number is the one that describes the document being written here.
                # `existing` is not passed because this branch is only reached when the file
                # does not exist -- the `out.exists()` guard above returns first -- so a
                # fresh ingest asserting `current` here is asserting it where nothing better
                # is known, which is the only case ADR 0006 leaves it.
                status = resolve(bulletin=bulletin.get(target))
                body = doc_body(target, title_line, url, sha, s_ch, s_div, status)
                body = body.replace("{FT}", flow_to_lines(sl))
                out.write_text(body)
                try:
                    # The Bulletin status is handed to the enricher too. It runs `apply()`
                    # immediately after this document is written and that call restamps
                    # `status:`, so an ingest that resolved the status correctly above and
                    # then enriched without it would have the History line overwrite the
                    # Bulletin one line later -- the two-writers failure inside a single
                    # function.
                    enrich_apply(out, enrich_derive(flow_to_lines(sl), doc_id,
                                                    registry_by_ch, bulletin.get(target),
                                                    status))
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


# ---------------------------------------------------------------------------------
# #276's negative proof. `--enumerate` is retired outright, so there is no rebuild left
# to watch fail on a bad input -- the acceptance criterion this module has to meet
# instead is "no REMAINING path can remove a catalogued row", which is a claim about
# every function in the file, not one call with a crafted fixture. Proved by walking
# this module's own AST (not by re-reading a docstring's promise) for the exact shape
# that dropped rows before: a wholesale reassignment of a division's `rules`, a chapter's
# `divisions`, or the catalog's own `chapters`, or a `.pop()`/`.remove()`/`.clear()`/`del`
# against any of the three. Every read-modify-write in this file -- `cmd_ingest`'s own
# loop (`r["status"]`, `r["note"]`, ...) AND `_write_catalog_merged`'s checkpoint
# (`_CHECKPOINT_FIELDS`, #276 follow-up: the checkpoint used to reassign a whole chapter
# from a worker's load-time snapshot, which is the shape this set of keys exists to also
# catch) -- instead sets named keys on an existing row it walks to, via `for r in
# d["rules"]:` or a chapter/division/rule walk with the same shape, neither of which can
# shrink a list it only reads. This detector proves that structural fact holds for the
# WHOLE file, this run and every future one, rather than asserting it once in prose.
_DESTRUCTIVE_KEYS = {"rules", "divisions", "chapters"}

# Built at runtime, not as one literal, because the detector below scans THIS FILE'S own
# AST: a single Constant spelling the retired host name at module level would itself be
# a "functional reference outside a docstring" by the detector's own rule -- the search
# needle cannot be indistinguishable from what it searches for.
_RETIRED_HOST = "public" + ".law"


def _subscript_key(node):
    return node.slice.value if (isinstance(node, ast.Subscript)
                                 and isinstance(node.slice, ast.Constant)) else None


def _destructive_call(node: ast.Call) -> bool:
    """True for a call shape that can remove a whole `_DESTRUCTIVE_KEYS` entry, beyond
    the `x["rules"].pop()`/`.remove()`/`.clear()` shape the caller already checks: a
    dict's OWN `.pop("rules")` (the key vanishes from its containing dict, not an
    element from the list) and `.update({"rules": ...})` (a same-key overwrite is
    exactly the wholesale-reassignment shape #276 fixed, just spelled as a call)."""
    if not (isinstance(node.func, ast.Attribute)):
        return False
    attr = node.func.attr
    if (attr == "pop" and node.args and isinstance(node.args[0], ast.Constant)
            and node.args[0].value in _DESTRUCTIVE_KEYS):
        return True
    if attr == "update" and node.args and isinstance(node.args[0], ast.Dict):
        return any(isinstance(k, ast.Constant) and k.value in _DESTRUCTIVE_KEYS
                   for k in node.args[0].keys)
    return False


def membership_dropping_sites(tree: ast.AST) -> list:
    """Line numbers of every AST shape in `tree` that could remove a catalogued rule
    row or division wholesale. Empty means the negative is proved for that tree."""
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if _subscript_key(t) in _DESTRUCTIVE_KEYS:
                    hits.append(t.lineno)
                # a SLICE assign (`d["rules"][:] = [...]`) reassigns the same key one
                # subscript down and is caught the same way `del d["rules"][0]` already is.
                elif isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Slice) \
                        and _subscript_key(t.value) in _DESTRUCTIVE_KEYS:
                    hits.append(t.lineno)
        elif isinstance(node, ast.Delete):
            for t in node.targets:
                if _subscript_key(t) in _DESTRUCTIVE_KEYS:
                    hits.append(node.lineno)
                elif isinstance(t, ast.Subscript) and _subscript_key(t.value) in _DESTRUCTIVE_KEYS:
                    hits.append(node.lineno)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr in ("pop", "remove", "clear")
              and _subscript_key(node.func.value) in _DESTRUCTIVE_KEYS):
            hits.append(node.lineno)
        elif isinstance(node, ast.Call) and _destructive_call(node):
            hits.append(node.lineno)
    return hits


def _docstring_string_ids(tree: ast.AST) -> set:
    """id() of every string constant that IS a docstring -- the first statement's value
    in the module or any function/class -- so prose explaining history (module, function
    or class level) is distinguishable from a string that is part of running code."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                ids.add(id(first.value))
    return ids


def _non_docstring_public_law_refs(tree: ast.Module) -> list:
    """String constants naming the retired mirror outside any docstring -- module,
    function or class -- which is where #276 leaves the historical explanation, per the
    ticket's own allowance ('historical comments explaining the switch are fine and
    welcome'). A `#`-comment never reaches the AST at all, so combined with the
    docstring exclusion this only ever catches a functional reference: code that could
    still BUILD A URL against the retired host."""
    doc_ids = _docstring_string_ids(tree)
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and _RETIRED_HOST in n.value and id(n) not in doc_ids]


def selftest() -> int:
    check = Checks()
    tree = ast.parse(Path(__file__).read_text())

    # THE NEGATIVE, for the file as it stands: no remaining path can drop a row.
    live_hits = membership_dropping_sites(tree)
    check("no path in this module reassigns, pops, removes or clears "
          "a division's rules or a chapter's divisions", live_hits == [])

    # THE DETECTOR ITSELF IS PROVED, not just trusted: reproduce the exact retired line
    # (`d["rules"] = [existing.get(n, ...) for n in rules]`, #276's own bug) as a fixture
    # and confirm membership_dropping_sites still catches that shape today. Without this,
    # a detector that catches nothing and a detector that never ran would look identical.
    bug_fixture = ast.parse(
        'd["rules"] = [existing.get(n, {"number": n, "status": "not_ingested"}) '
        'for n in rules]')
    check("RED: the detector catches the retired cmd_enumerate line reproduced as a "
          "fixture -- proof the check itself fires, not just that it is silent today",
          membership_dropping_sites(bug_fixture) != [])
    # ...and the sibling shapes it must also catch: a pop/remove/clear/del against
    # either key, none of which #276's bug used but all of which have the same effect.
    for snippet, label in [
        ('d["rules"].pop()', "pop"),
        ('d["rules"].remove(x)', "remove"),
        ('c["divisions"].clear()', "clear"),
        ('del d["rules"][0]', "del-index"),
        ('del d["rules"]', "del-whole-key"),
        # #276 follow-up (code review): three shapes a probe found this detector missed
        # entirely -- caught now by `_destructive_call` and the slice-assign branch above.
        ('d["rules"][:] = []', "slice-assign"),
        ('d.pop("rules")', "dict-pop-key"),
        ('d.pop("rules", None)', "dict-pop-key-default"),
        ('d.update({"rules": []})', "dict-update-key"),
        # ...and the same three already-known shapes, now against the newly-watched
        # `chapters` key -- what actually caught the live bug at `_write_catalog_merged`.
        ('cat["chapters"] = []', "chapters-reassign"),
        ('cat["chapters"].pop(0)', "chapters-pop-element"),
        ('del cat["chapters"][0]', "chapters-del-index"),
    ]:
        check(f"RED: the detector also catches a .{label} shape",
              membership_dropping_sites(ast.parse(snippet)) != [])
    # ...and guards that must NOT fire: mutating a row's OWN field is what cmd_ingest's
    # loop and _write_catalog_merged's checkpoint actually do, and neither may ever trip
    # this detector.
    check("GREEN: mutating an existing row's own field is not a membership-dropping site",
          membership_dropping_sites(ast.parse('r["status"] = "ingested"')) == [])
    check("GREEN: updating an existing row's own fields by dict, with no destructive "
          "key among them, is not one either",
          membership_dropping_sites(
              ast.parse('r.update({"status": "ingested", "note": "n"})')) == [])
    check("GREEN: popping a key that is not a destructive one is not one either",
          membership_dropping_sites(ast.parse('r.pop("note", None)')) == [])

    # NO FUNCTIONAL REFERENCE TO THE RETIRED MIRROR remains outside a docstring's own
    # historical account of why it was retired.
    check("the retired mirror is named only in a docstring, never in code that could "
          "still build a URL from it",
          _non_docstring_public_law_refs(tree) == [])
    check("...and the module docstring's historical account is still there to be "
          "excluded from", _RETIRED_HOST in ast.get_docstring(tree))

    # THE RETIRED SYMBOLS ARE GONE, not just unreachable -- `enumerate_chapter` and `PL`
    # were the actual scraper and its target host; if either still exists, the refusal
    # below is decoration over a live path.
    check("enumerate_chapter no longer exists", "enumerate_chapter" not in globals())
    check("PL no longer exists", "PL" not in globals())

    # THE REFUSAL ITSELF: touches neither the network nor the catalog file, and names
    # the replacement. Checked against the REAL catalog on disk, byte for byte, so a
    # future edit that sneaks a read/write back in is caught by content, not by
    # assuming the function body says what it does.
    before = CATALOG.read_bytes() if CATALOG.exists() else None
    try:
        cmd_enumerate(["999"])
        check("cmd_enumerate exits rather than returning", False)
    except SystemExit as e:
        msg = str(e)
        check("the refusal names the replacement command",
              "catalog_oar.py --discover" in msg)
        check("the refusal names this ticket", "#276" in msg)
    after = CATALOG.read_bytes() if CATALOG.exists() else None
    check("the refusal did not touch the catalog file on disk", before == after)

    return check.report()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enumerate", nargs="+", metavar="CH",
                    help="retired (#276) -- refuses and names catalog_oar.py --discover")
    ap.add_argument("--ingest", nargs="+", metavar="CH")
    ap.add_argument("--skip-group", action="store_true",
                    help="mass-import mode: no per-rule update-group entries (see cmd_ingest)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    elif a.enumerate:
        cmd_enumerate(a.enumerate)
    elif a.ingest:
        cmd_ingest(a.ingest, a.skip_group)
    else:
        ap.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
