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
import tempfile
import time
from collections import namedtuple
from datetime import date
from pathlib import Path

import yaml

from check_source_urls import SOFT_404
from ingest_lib import fetch, fetch_page
from legal_status import bulletin_status_by_rule, resolve
from repo_lib import (REPO_ROOT, SNAPSHOT_DIR, Checks, content_hash, division_status,
                      normalize_volatile, oar_rule_path, rule_title_from_html,
                      snapshot_slice, ws_only, snapshot_text)

CATALOG = REPO_ROOT / "_meta/catalog/oar.yml"
GROUP = REPO_ROOT / "_meta/sources/oar.yml"
TODAY = date.today().isoformat()

# THE ONE DECLARATION (#334 code review, same discipline as `catalog_oar.py`'s
# VANISHED_DIVISION_MARK/HISTORY_MARK). `results_page_documents.py` reads a rule's `note`
# for this phrase, by substring, to tell an ALREADY-PUBLISHED search-results-list document
# (#251) apart from an ordinary rule -- it used to carry its own retyped copy of these words
# rather than importing this one, so rewording the note here without also rewording that
# copy would silently stop `results_page_documents.py` from finding what this line writes.
SEARCH_RESULTS_MARK = "search-results list"

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
_RESULTS_LIST = re.compile(r"returned \d+ results?\.\s*New Search")

# The OTHER signal, and the one that does not depend on OARD's wording: where the request
# ENDED UP. OARD answers an ambiguous or unknown ruleNumber with a 302 to
# ruleSearchResults.action, and check_source_urls.py's SOFT_404 table already declares that
# fact -- imported here, not retyped, so the ingester and the weekly source-url check cannot
# disagree about what a results page is (#439).
SEARCH_RESULTS_URL_MARK = SOFT_404["secure.sos.state.or.us"]

# A rule is fetched by its OWN version id when its bare number is shared (#439): OARD's
# search lists every record that matches a number -- older and newer rules that were given the
# same number, and rules whose history merely cites it -- and each links here.
VERSION_URL = "https://secure.sos.state.or.us/oard/viewSingleRule.action?ruleVrsnRsn={rsn}"


def is_search_results_page(ws_text: str, final_url: str = "") -> bool:
    """True when this OARD page is a search-results list rather than a single rule: it ended
    on ruleSearchResults.action (the soft-404 signal), or it says it is one."""
    return SEARCH_RESULTS_URL_MARK in (final_url or "") or bool(_RESULTS_LIST.search(ws_text))


def may_replace(existing_text: str) -> bool:
    """The version-id path replaces a document ONLY if that document is itself a results
    page (#439). A real rule is never overwritten by it."""
    return is_search_results_page(ws_only(existing_text))


VersionPlan = namedtuple("VersionPlan", "refusal url title full_text sha text raw")


def plan_version_document(number: str, rsn: str, raw: bytes, final_url: str) -> VersionPlan:
    """What mirroring ONE OARD rule record (by ruleVrsnRsn) would publish, or why not.
    Pure: no disk, no network. Refuses a results page and a page that prints a different
    rule number than the one asked for -- an anti-fabrication guard, since the rule text
    published is whatever this page says."""
    from ingest_lib import flow_to_lines
    url = VERSION_URL.format(rsn=rsn)
    raw = normalize_volatile(raw)
    text = snapshot_text(raw)
    wt = ws_only(text)

    def refuse(why):
        return VersionPlan(why, url, None, None, None, None, raw)

    if is_search_results_page(wt, final_url):
        return refuse("OARD served a search-results list, not a rule")
    served = served_rule_number(wt)
    if served != number:
        return refuse(f"the page prints rule number {served}, not {number}")
    sl = snapshot_slice(f"oar-{number}", f"oar-{number}", text)
    if len(sl) < 100:
        return refuse("no rule body found on the OARD page")
    title = rule_title_from_html(raw.decode("utf-8", errors="replace"), number) or f"OAR {number}"
    return VersionPlan(None, url, title, flow_to_lines(sl), content_hash(raw, "html"), text, raw)


# THE INGESTER NO LONGER NAMES THE LEGAL STATUS. `status: current` used to be a hardcoded
# literal in the template below, written onto every one of the rule documents this
# pipeline created. That is fine on a FIRST ingest -- nothing better is known about a rule
# OARD is serving normally -- and it is the whole hazard on a re-ingest: once #230 refreshes
# an amended rule automatically, the literal would restamp `current` over a repeal the
# Bulletin filed, resurrecting the rule silently and publishing a false statement about
# Oregon law under provenance. The value now arrives from `legal_status.resolve()`, which is
# the only thing that decides it (ADR 0006).
def doc_body(rule, title_line, url, sha, ch, div, status):
    return f"""---
schema_version: 1
corpus: "executive-regulatory-frameworks"
jurisdiction: "oregon"
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
last_verified: ""
verified_by: ""
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


def _write_catalog_merged(cat, my_chapters, clear=None):
    """Concurrent-safe catalog save for parallel --ingest workers: under an exclusive
    lock, re-read the catalog from disk and write this worker's OWN field updates
    (`_CHECKPOINT_FIELDS`) onto the matching rule rows, by number, plus each touched
    division's own recomputed `status` (#422), then write atomically.

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
    # #422: a division's OWN status has to cross too. `cmd_ingest` recomputes it
    # (`d["status"] = division_status(d["rules"])`) on the in-memory catalog because "a
    # command that writes a rule's status owns the aggregate that reads it" -- but this
    # function merged by RULE row only, so that recompute was computed and then dropped
    # before it reached disk, and `catalog_agreement.py --check` kept reporting the very
    # disagreement `cmd_ingest` had just fixed. Keyed by (chapter, division) because a
    # division number is only unique within its chapter.
    mine_divs = {(c["chapter"], d.get("division")): d
                 for c in cat["chapters"] if c["chapter"] in my_chapters
                 for d in (c.get("divisions") or [])}
    with open(lock_path, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        disk = yaml.safe_load(CATALOG.read_text())
        for c in disk["chapters"]:
            if c["chapter"] not in my_chapters:
                continue
            for d in (c.get("divisions") or []):
                # Sets ONE named key on a division dict already on disk -- the same
                # idiom as the rule loop below, and for the same reason: it cannot
                # reassign `divisions` or `rules`, so #276's membership guarantee is
                # untouched. Disk keeps every division and rule it gained since this
                # worker loaded; only this division's own `status` is updated.
                src_div = mine_divs.get((c["chapter"], d.get("division")))
                if src_div is not None and "status" in src_div:
                    d["status"] = src_div["status"]
                for r in (d.get("rules") or []):
                    src = mine_rules.get(r["number"])
                    if src is None:
                        continue
                    for key in _CHECKPOINT_FIELDS:
                        if key in src:
                            r[key] = src[key]
                    # keys a caller deliberately removed (`clear`: number -> keys); a pop
                    # on the in-memory row cannot cross by itself, only a set can
                    for key in (clear or {}).get(r["number"], ()):
                        r.pop(key, None)
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
                    fetched = fetch_page(url)
                    raw = normalize_volatile(fetched.body)
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
                if is_search_results_page(wt, fetched.url):
                    # NOT `not_served`: OARD served something, and it is not this rule.
                    r["status"] = "not_sliceable"
                    r["note"] = (f"OARD serves a {SEARCH_RESULTS_MARK} for this number, not "
                                 "a rule -- more than one rule shares it (#251)")
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
                # THE ONE DEFINITION (#334 code review): `repo_lib.oar_rule_path` is the
                # single place this layout is computed, so `catalog_oar.py`'s
                # `renumbered_without_path()` reads this same path rather than a second,
                # independently-typed copy of it.
                out = oar_rule_path(target)
                out_dir = out.parent
                if out.exists():
                    # #338: the document at `out` is the same document either way -- what
                    # differs is only whether THIS row's own number is also the served
                    # one. A renumbered row (served != num) still names it via
                    # `served_as`, and that target is real, so `path` is stamped the same
                    # way a same-numbered row's already was.
                    r["path"] = str(out.relative_to(REPO_ROOT))
                    if served == num:
                        r["status"] = "ingested"
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
    # A DIVISION'S STATUS IS WHAT ITS RULES SAY, and only --enumerate used to restate it.
    # `cmd_ingest` moved rules to `ingested` and left every touched division declaring the
    # status it held before the run, so `catalog_agreement.py --check` failed on the very
    # catalog this command had just written -- measured on one rule: "1 division(s) disagree
    # with the rules beneath them: 101-65 says 'not_ingested' not 'ingested'".
    #
    # Recomputed HERE rather than left to `--enumerate` (which #276 retires) or to
    # `catalog_oar.py --discover` (a 170-chapter re-scrape). A command that writes a rule's
    # status owns the aggregate that reads it.
    for ch in chapters:
        for d in by_ch[ch]["divisions"]:
            if isinstance(d.get("rules"), list):
                d["status"] = division_status(d["rules"])
    if not skip_group:
        group["sources"] = sorted(gsrc.values(), key=lambda s: s["id"])
        GROUP.write_text(yaml.safe_dump(group, sort_keys=False, allow_unicode=True, width=110))
    _write_catalog_merged(cat, set(chapters))
    print(f"made {made}, renumbered {renumbered}, skipped {skipped}, failed {failed}")


_VERSION_PAIR = re.compile(r"^\d{3}-\d{3}-\d{4}=\d+$")


def parse_version_pairs(args):
    """`NUMBER=RSN` arguments to (number, rsn) tuples; ValueError names the bad one."""
    for a in args:
        if not _VERSION_PAIR.match(a):
            raise ValueError(f"{a!r} is not NUMBER=RSN (e.g. 586-030-0025=153282)")
    return [tuple(a.split("=", 1)) for a in args]


def cmd_ingest_version(pairs):
    """`--ingest-version NUMBER RSN ...` (#439): replace the document at `oar-NUMBER` -- which
    MUST be an OARD search-results page, see `may_replace` -- with the rule record OARD
    itself serves at viewSingleRule.action?ruleVrsnRsn=RSN. The id stays `oar-NUMBER`
    (ADR 0006: ids are cited), so every inbound reference keeps resolving. Which RSN is the
    rule is a judgement made from OARD's own records and passed in; this function checks what
    it can (the page must print NUMBER and must not be a results page) and never writes
    text that did not come from that page."""
    from enrich_oar import apply as enrich_apply
    from enrich_oar import derive as enrich_derive
    from enrich_oar import load_registry_by_chapter
    registry_by_ch = load_registry_by_chapter()
    cat = yaml.safe_load(CATALOG.read_text())
    bulletin = bulletin_status_by_rule(cat)
    group = yaml.safe_load(GROUP.read_text())
    gsrc = {s["id"]: s for s in group["sources"]}
    rows = {r["number"]: (c["chapter"], r) for c in cat["chapters"]
            for d in (c.get("divisions") or []) for r in (d.get("rules") or [])}
    made, failed, chapters = 0, 0, set()
    cleared = {}
    for number, rsn in pairs:
        doc_id = f"oar-{number}"
        out = oar_rule_path(number)
        if number not in rows or not out.exists():
            print(f"REFUSED {number}: no catalogued row and document to replace")
            failed += 1
            continue
        if not may_replace(out.read_text(encoding="utf-8", errors="replace")):
            print(f"REFUSED {number}: the document is not a search-results page; "
                  "this path never overwrites a real rule")
            failed += 1
            continue
        try:
            fetched = fetch_page(VERSION_URL.format(rsn=rsn))
        except Exception as e:
            print(f"FETCH FAILED {number} ({rsn}): {e}")
            failed += 1
            continue
        plan = plan_version_document(number, rsn, fetched.body, fetched.url)
        if plan.refusal:
            print(f"REFUSED {number} ({rsn}): {plan.refusal}")
            failed += 1
            continue
        ch, div, _ = number.split("-")
        status = resolve(bulletin=bulletin.get(number))
        body = doc_body(number, plan.title, plan.url, plan.sha, ch, div, status)
        saved = out.read_text(encoding="utf-8")
        out.write_text(body.replace("{FT}", plan.full_text))
        try:
            enrich_apply(out, enrich_derive(plan.full_text, doc_id, registry_by_ch,
                                            bulletin.get(number), status))
        except SystemExit as e:
            out.write_text(saved)
            print(f"NEEDS REGISTRY {number}: {e}")
            failed += 1
            continue
        (SNAPSHOT_DIR / f"{doc_id}.html").write_bytes(plan.raw)
        (SNAPSHOT_DIR / f"{doc_id}.txt").write_text(plan.text, encoding="utf-8")
        chapter, row = rows[number]
        chapters.add(chapter)
        row["status"] = "ingested"
        # a refusal recorded against the results page says the refresh failed; this document
        # now carries the record's own text, so the refusal is stale (as `reingest_oar --run`
        # also clears it on success)
        from reingest_oar import REFUSED_KEYS
        cleared[number] = [k for k in REFUSED_KEYS if row.pop(k, None) is not None]
        row["path"] = str(out.relative_to(REPO_ROOT))
        row["note"] = (f"OARD's results for this number list more than one record; this document "
                       f"mirrors ruleVrsnRsn={rsn}, the record that prints {number} (#439)")
        if doc_id in gsrc:
            # only the keys the entry already carries: its `notes` (where the baseline
            # came from) stays true, and a key the entry never had is not invented.
            gsrc[doc_id]["url"] = plan.url
            gsrc[doc_id]["sha256"] = plan.sha
            if "last_checked" in gsrc[doc_id]:
                gsrc[doc_id]["last_checked"] = TODAY
        made += 1
        time.sleep(0.5)
    if made:
        group["sources"] = sorted(gsrc.values(), key=lambda s: s["id"])
        GROUP.write_text(yaml.safe_dump(group, sort_keys=False, allow_unicode=True, width=110))
        _write_catalog_merged(cat, chapters, clear=cleared)
    print(f"replaced {made}, refused {failed}")
    return 1 if failed else 0


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


def _folded_str_concat(node: ast.AST):
    """The string a chain of `ast.BinOp(ast.Add)` string constants would produce at
    RUNTIME, or `None` if any operand is not itself a string constant or a foldable
    chain -- Python's `ast` module does not fold `"a" + "b"` into one `Constant` at
    parse time (unlike adjacent-literal concatenation, or an f-string with no
    interpolation, which the parser DOES merge into one `Constant`), so a needle split
    across two or more `+`-joined literals leaves each half its own node and neither
    half contains the whole needle alone (#296). This walks the same chain by hand and
    hands back what it would evaluate to. NOT COVERED, same as before this function
    existed: an f-string WITH interpolation (`f"public{v}.law"`, parsed as `JoinedStr`,
    never merged), `.join`/`.format`/`%`-formatting, `chr()`, or either operand being a
    `Name` rather than a literal -- #296 scoped the fix to the one obfuscation this
    module's own `_RETIRED_HOST` constant demonstrates is realistic, not every
    conceivable one ('unbounded', in the ticket's own words)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _folded_str_concat(node.left)
        right = _folded_str_concat(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _self_reference_ids(tree: ast.Module) -> set:
    """id() of this module's OWN `_RETIRED_HOST = "public" + ".law"` value expression
    and everything nested inside it. Folding `BinOp(Add)` chains (#296) would otherwise
    flag that declaration as a violation of itself -- it is deliberately built as a
    split literal precisely so a single-`Constant` scan can't self-match, and a
    folding-aware scan needs the same immunity, granted BY NAME to this one assignment
    rather than by re-permitting every two-part string concatenation in the module.

    THE EXEMPTION IS NARROW ON PURPOSE, in both scope and value, because #296's own
    complaint was a by-name exemption wide enough to hide a real reintroduction:
    MODULE-LEVEL ONLY (`tree.body` directly, never `ast.walk` into every function and
    class) so a function-local `_RETIRED_HOST = "<a live URL>"` -- a plain single
    string, needing no folding immunity at all -- gets none, and VALUE-CHECKED (the
    assignment's folded value must equal `_RETIRED_HOST` itself) so a module-level
    `_RETIRED_HOST` rebound to the actual retired URL is not laundered through the same
    name. A rebind that fails either test is not this declaration and is not exempted."""
    ids = set()
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "_RETIRED_HOST"
                and _folded_str_concat(node.value) == _RETIRED_HOST):
            for sub in ast.walk(node.value):
                ids.add(id(sub))
    return ids


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
    still BUILD A URL against the retired host.

    #296: also catches the needle FOLDED out of a `"a" + "b" + ...` chain -- a single
    `ast.Constant` scan is blind to the host spelled as a run-time string
    concatenation, because neither half of a split literal contains the whole needle on
    its own. The module's own `_RETIRED_HOST = "public" + ".law"` is excluded BY NAME,
    at MODULE LEVEL ONLY, and only when its value folds to the real `_RETIRED_HOST`
    (`_self_reference_ids`) -- not by re-permitting two-part concatenation generally,
    and not by trusting the name alone. Whatever dodges this scan for the gate's own
    constant would dodge it for a real reintroduction too, which is exactly the gap
    #296 closes."""
    doc_ids = _docstring_string_ids(tree)
    self_ids = _self_reference_ids(tree)
    hits = []
    for n in ast.walk(tree):
        if id(n) in doc_ids or id(n) in self_ids:
            continue
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if _RETIRED_HOST in n.value:
                hits.append(n.lineno)
        elif isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            folded = _folded_str_concat(n)
            if folded is not None and _RETIRED_HOST in folded:
                hits.append(n.lineno)
    return hits


def _renumbered_out_exists_stamps_path() -> bool:
    """#338 fixture: a row whose OARD-served number differs from its own (a renumber)
    must still get `path` set when the served target's file already exists on disk --
    the `out.exists()` branch used to gate that write on `served == num`, so a row like
    125-800-0005 (serves 128-030-0005, whose file another row already wrote) named its
    `served_as` target but never recorded where it lives. Runs `cmd_ingest` itself
    against a temporary catalog/group/rules tree and a stubbed `fetch`, rather than
    re-deriving the expected path the way the code does, so this fails if the real
    write site regresses.
    """
    import tempfile
    num, served = "125-800-0005", "128-030-0005"
    with tempfile.TemporaryDirectory() as td:
        tmp_root = Path(td)
        served_path = oar_rule_path(served, root=tmp_root)
        served_path.parent.mkdir(parents=True, exist_ok=True)
        served_path.write_text("the document OARD already serves 128-030-0005 under")
        (tmp_root / "_meta" / ".cache").mkdir(parents=True, exist_ok=True)

        catalog_path = tmp_root / "oar.yml"
        catalog_path.write_text(yaml.safe_dump({
            "chapters": [{"chapter": "125",
                          "divisions": [{"rules": [{"number": num}]}]}]
        }))
        group_path = tmp_root / "sources.yml"
        group_path.write_text(yaml.safe_dump({"sources": []}))

        raw = (f"<html><body><p>{served}</p><p>" +
               "lorem ipsum rule body text. " * 20 + "</p></body></html>").encode()

        real_oar_rule_path = oar_rule_path
        g = globals()
        _unset = object()
        keys = ("CATALOG", "GROUP", "REPO_ROOT", "fetch", "oar_rule_path")
        saved = {k: g.get(k, _unset) for k in keys}
        try:
            g["CATALOG"] = catalog_path
            g["GROUP"] = group_path
            g["REPO_ROOT"] = tmp_root
            g["fetch"] = lambda url: raw
            # Same derivation `repo_lib.oar_rule_path` uses, just pointed at `tmp_root`
            # via its own documented `root=` parameter (#334's ONE DEFINITION) rather
            # than re-deriving the path by hand.
            g["oar_rule_path"] = lambda number, root=tmp_root: real_oar_rule_path(number, root=root)
            cmd_ingest(["125"], skip_group=True)
        finally:
            for k, v in saved.items():
                if v is _unset:
                    g.pop(k, None)
                else:
                    g[k] = v

        result = yaml.safe_load(catalog_path.read_text())
        row = result["chapters"][0]["divisions"][0]["rules"][0]
        return (row.get("served_as") == served and
                row.get("path") == str(served_path.relative_to(tmp_root)))


def _division_status_round_trips_to_disk() -> bool:
    """#422. `cmd_ingest` recomputes `d["status"] = division_status(d["rules"])` on the
    IN-MEMORY catalog, then hands that object to `_write_catalog_merged`, which merges
    by RULE row only -- it builds `mine_rules` keyed by rule number and copies
    `_CHECKPOINT_FIELDS` onto each matching disk row, and never reads a division's own
    fields. So the recompute the comment above it calls load-bearing ("a command that
    writes a rule's status owns the aggregate that reads it") was computed, then dropped
    before it reached disk, and `catalog_agreement.py --check` kept reporting the
    disagreement `cmd_ingest` had just tried to fix.

    Proves the round trip end to end rather than reading the merge loop: put a catalog on
    disk whose division says `not_ingested`, recompute that division in memory the way
    `cmd_ingest` does, call the writer, and re-read from DISK. RED before #422's fix."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        catalog_path = tmp_root / "oar.yml"
        on_disk = {"chapters": [{"chapter": "125", "divisions": [
            {"division": "1", "title": "D", "status": "not_ingested",
             "rules": [{"number": "125-1-0010", "status": "ingested"}]}]}]}
        catalog_path.write_text(yaml.safe_dump(on_disk, sort_keys=False))

        cat = yaml.safe_load(catalog_path.read_text())
        div = cat["chapters"][0]["divisions"][0]
        div["status"] = division_status(div["rules"])          # what cmd_ingest does
        recomputed = div["status"]

        g, _unset = globals(), object()
        saved = g.get("CATALOG", _unset)
        try:
            g["CATALOG"] = catalog_path
            _write_catalog_merged(cat, {"125"})
        finally:
            if saved is _unset:
                g.pop("CATALOG", None)
            else:
                g["CATALOG"] = saved

        back = yaml.safe_load(catalog_path.read_text())
        return back["chapters"][0]["divisions"][0]["status"] == recomputed


def selftest() -> int:
    check = Checks()
    tree = ast.parse(Path(__file__).read_text())

    # #422: the division-status recompute must survive the write, not just happen.
    check("a division status recomputed by cmd_ingest reaches DISK through "
          "_write_catalog_merged, not just the in-memory catalog (#422)",
          _division_status_round_trips_to_disk())

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

    # #296 RED: reproduce the exact reintroduction a single-`Constant` scan is blind to
    # -- the retired host spelled as a run-time string concatenation split across three
    # literals, the same shape this module's OWN `_RETIRED_HOST` is built as. Proof the
    # folding detector actually fires on it, not just that today's file is silent.
    split_fixture = ast.parse('BASE = "https://oregon." + "public" + ".law"')
    check("RED: a split-literal string concat naming the retired host still fires the "
          "detector",
          _non_docstring_public_law_refs(split_fixture) != [])
    # ...a two-part split is caught the same way, and so is the needle broken across the
    # join point itself rather than kept whole in either half.
    check("RED: a two-part split ('public' + '.law', spelled with a different variable "
          "name) still fires",
          _non_docstring_public_law_refs(
              ast.parse('HOST = "public" + ".law"')) != [])
    check("RED: the needle split ACROSS the join point ('public.' + 'law', neither half "
          "a whole word) still fires",
          _non_docstring_public_law_refs(
              ast.parse('HOST = "oregon.public." + "law"')) != [])
    # GREEN: an unrelated two-part concatenation, naming nothing retired, must not fire
    # -- the fold only matters when the RESULT contains the needle.
    check("GREEN: an unrelated string concatenation does not fire",
          _non_docstring_public_law_refs(
              ast.parse('GREETING = "hello" + "world"')) == [])
    # GREEN: this module's own `_RETIRED_HOST = "public" + ".law"` -- the self-reference
    # the detector must not mistake for a violation of itself -- is excluded BY NAME, and
    # that exclusion does not spill over to protect a DIFFERENTLY-named split literal
    # naming the same host (already proved RED above via `HOST = ...`).
    check("GREEN: the module's own _RETIRED_HOST declaration is excluded by name, not "
          "by permitting all two-part concatenation",
          _non_docstring_public_law_refs(
              ast.parse('_RETIRED_HOST = "public" + ".law"')) == [])

    # #296 code review: the by-name exemption above must not be wider than the ONE
    # declaration it names. A FUNCTION-LOCAL `_RETIRED_HOST` needs no folding immunity
    # at all -- it is a plain single Constant, not a split literal -- and granting it
    # one anyway would blind the gate to a live URL-building site with that name.
    # (Spelled as a split literal here too, same as the fixtures above -- this whole
    # file gets re-parsed and self-scanned a few lines up, and a CONTIGUOUS needle
    # sitting in one of ITS OWN string literals would trip that self-scan the same way
    # a real reintroduction would.)
    check("RED: a function-local _RETIRED_HOST holding the real retired URL still "
          "fires -- the by-name exemption is module-level only",
          _non_docstring_public_law_refs(ast.parse(
              'def f():\n'
              '    _RETIRED_HOST = "https://oregon." + "public" + ".law" + "/oar/"\n'
              '    return _RETIRED_HOST + "125"')) != [])
    # A MODULE-LEVEL `_RETIRED_HOST` rebound to the actual retired URL -- not the
    # split-literal decoy the real declaration is -- must also still fire: the
    # exemption is granted to the declaration's VALUE, not to every future value the
    # same name could hold.
    check("RED: a module-level _RETIRED_HOST rebound to the real retired URL still "
          "fires -- the exemption is value-checked, not name-only",
          _non_docstring_public_law_refs(ast.parse(
              '_RETIRED_HOST = "https://oregon." + "public" + ".law" + "/oar/"'
          )) != [])

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

    # #338: the out.exists() branch must stamp `path` for a RENUMBERED row the same way
    # it already does for a same-numbered one -- watched RED before the fix, since the
    # branch used to `continue` without ever setting `path` when `served != num`.
    check("a renumbered row whose served target's file already exists ends with `path` "
          "set to that file (#338)", _renumbered_out_exists_stamps_path())

    # #439: A RESULTS PAGE IS RECOGNISED BY WHERE OARD SENT US, not only by what it says.
    # OARD answers an ambiguous or unknown `ruleNumber` with a 302 to ruleSearchResults.action
    # -- the same signal check_source_urls.py's SOFT_404 table uses. A singular "returned 1
    # result." did not match the text pattern at all, and neither did any wording OARD changes.
    sr_url = "https://secure.sos.state.or.us/oard/ruleSearchResults.action;JSESSIONID_OARD=x?ruleNumber=1-001-0001"
    one_url = "https://secure.sos.state.or.us/oard/viewSingleRule.action?ruleVrsnRsn=7"
    check("a page whose FINAL url is ruleSearchResults.action is a results page whatever it says (#439)",
          is_search_results_page("1-001-0001 Some wording OARD changed", sr_url))
    check("a singular 'returned 1 result.' listing is a results page (#439)",
          is_search_results_page("Your search returned 1 result. New Search | Modify Search"))
    check("a real rule served from viewSingleRule.action is not a results page (#439)",
          not is_search_results_page("586-030-0025 Preliminary Matters (1) text", one_url))
    check("the url signal is the SOFT_404 table's own entry, not a second copy (#439)",
          SEARCH_RESULTS_URL_MARK == SOFT_404["secure.sos.state.or.us"])

    # #439: THE REAL RULE BEHIND A SHARED NUMBER is mirrored from its OWN page, by version id.
    page = (b"<html><body><strong>586-030-0025</strong><br><strong>Preliminary Matters</strong>"
            b"<p>(1) Preliminary motions challenging the Board's jurisdiction or requesting "
            b"dismissal of the complaint must be filed in writing with the Board.</p>"
            b"<p>History: FDAB 2-2001, f. &amp; cert. ef. 12-31-01</p>"
            b"Please use this link to bookmark or link to this rule.</body></html>")
    plan = plan_version_document("586-030-0025", "153282", page, one_url)
    check("a real rule page is accepted for its own number (#439)", plan.refusal is None)
    check("its source_url is the rule's OWN viewSingleRule page, by ruleVrsnRsn (#439)",
          plan.url == VERSION_URL.format(rsn="153282"))
    check("its title is read from the rule page, not 'returned N results' (#439)",
          plan.title == "Preliminary Matters")
    check("what it would publish contains the rule text and none of the search chrome (#439)",
          "Preliminary motions" in plan.full_text and "New Search" not in plan.full_text)
    bad = plan_version_document("586-030-0025", "153281", b"<html>586-030-0025 returned 2 results. "
                                b"New Search | Modify Search</html>", sr_url)
    check("a results page is refused, not mirrored, even when asked for by version id (#439)",
          bad.refusal is not None and "search-results" in bad.refusal)
    other = plan_version_document("586-030-0025", "999", page.replace(b"586-030-0025", b"586-030-0030"),
                                  one_url)
    check("a rule page that prints a DIFFERENT number is refused: that is a neighbour, not "
          "this rule (#439)", other.refusal is not None and "586-030-0030" in other.refusal)
    check("only a document that IS a results page may be replaced; a real rule is never "
          "overwritten by this path (#439)",
          may_replace("returned 2 results. New Search | Modify Search Rows per page")
          and not may_replace("586-030-0025 Preliminary Matters (1) text"))
    ok = parse_version_pairs(["586-030-0025=153282"]) == [("586-030-0025", "153282")]
    try:
        parse_version_pairs(["586-030-0025"])
        bad_refused = False
    except ValueError:
        bad_refused = True
    check("--ingest-version arguments are validated: NUMBER=RSN passes, a bare number is "
          "refused with a message rather than an unpacking crash", ok and bad_refused)

    return check.report()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enumerate", nargs="+", metavar="CH",
                    help="retired (#276) -- refuses and names catalog_oar.py --discover")
    ap.add_argument("--ingest", nargs="+", metavar="CH")
    ap.add_argument("--ingest-version", nargs="+", metavar="NUMBER=RSN",
                    help="replace a search-results-page document with the OARD rule record "
                         "at ruleVrsnRsn=RSN (#439)")
    ap.add_argument("--skip-group", action="store_true",
                    help="mass-import mode: no per-rule update-group entries (see cmd_ingest)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    elif a.enumerate:
        cmd_enumerate(a.enumerate)
    elif a.ingest_version:
        try:
            pairs = parse_version_pairs(a.ingest_version)
        except ValueError as e:
            ap.error(str(e))
        sys.exit(cmd_ingest_version(pairs))
    elif a.ingest:
        cmd_ingest(a.ingest, a.skip_group)
    else:
        ap.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
