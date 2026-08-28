#!/usr/bin/env python3
"""Populate _meta/catalog/oar.yml with every chapter's division/rule inventory
(Gate #1 input for the mass OAR import: run this, review the printed summary,
THEN run ingest_oar.py on approved chapters). Idempotent and resumable — the
catalog is written after every chapter, and already-discovered chapters are
skipped unless --redo is given.

  python3 src/catalog_oar.py --discover            # all registry chapters
  python3 src/catalog_oar.py --discover 137 150    # specific chapters
  python3 src/catalog_oar.py --summary             # counts only, no network

Discovery source: OARD itself (secure.sos.state.or.us/oard), since #270 — never
oregon.public.law, an unofficial mirror measured 2026-08-27 to be missing 5,730
rules in 325 divisions across the 168 chapters this corpus mirrors, and to be
missing chapters 419 and 950 entirely. OARD's chapter-number -> internal
`selectedChapter` id map is published as a static `<select>` on
`ruleSearch.action` (362 `<option>`s, no JavaScript) and is resolved fresh from
it every run rather than hardcoded, because it is OARD's internal bookkeeping
and may move. `displayChapterRules.action?selectedChapter=<id>` then returns
every division and every CURRENT rule number with its leadline, in one static
page. Discovery only: rule CONTENT is always fetched from the official OARD
per-rule URL by ingest_oar.py, same as before. Chapter titles come from the
agency registry's OAR name (`oar_name` in _meta/catalog/agencies.yml — the title
this same upstream index prints for the chapter); division titles from OARD's
own chapter page. The chapter page also prints a leadline beside every rule
number; nothing in this repo reads it (rule titles are recovered per-rule, from
the rule's own cached snapshot, by backfill_oar_titles.py) so it is parsed only
far enough to find the rule number and is not carried into the catalog.

MERGE, NEVER REPLACE: OARD's chapter listing is a CURRENT rules view, so a
rule already in this catalog and absent from it is history (a renumber or a
repeal), not gone — and this corpus keeps history because deleting a document
breaks every citation pointing at it. Existing per-rule statuses
(ingested/renumbered/not_served/...) are preserved on merge, and
`merge_divisions` + `WouldRemoveRules` (below) make that the rule of this
module rather than a habit: a run whose merge would still drop a rule row
already held REFUSES to save, rather than silently narrowing the catalog."""
import re
import sys
import time
import urllib.request
from datetime import date
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml

from repo_lib import REPO_ROOT, Checks, division_status

OARD_BASE = "https://secure.sos.state.or.us/oard"
CHAPTER_LIST_URL = f"{OARD_BASE}/ruleSearch.action"
CATALOG = REPO_ROOT / "_meta/catalog/oar.yml"
REGISTRY = REPO_ROOT / "_meta/catalog/agencies.yml"
UA = "executive-regulatory-frameworks (+https://github.com/OregonAI/executive-regulatory-frameworks)"
TODAY = date.today().isoformat()

# THE CHAPTER -> INTERNAL ID MAP, resolved at run time (#270). `value="<id>"` is OARD's
# own bookkeeping number; `<id> - ` no longer prefixes the two "Select a chapter..."
# placeholder options because their value is "-1", which \d+ does not match.
CHAPTER_OPTION_RE = re.compile(r'<option value="(\d+)">(\d+) - ')
DIVISION_RE = re.compile(
    r"<h3><a href='[^']*?selectedDivision=\d+'>Division (\d+[A-Za-z]?)&nbsp;-&nbsp;(.*?)</a></h3>",
    re.S)
RULE_RE = re.compile(
    r"<p><strong><a href='[^']*?ruleVrsnRsn=\d+'>(\d{3}-\d{3}-\d{4})</a></strong>"
    r"&nbsp;&nbsp;(.*?)</p>", re.S)


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def load_catalog():
    if CATALOG.exists():
        return yaml.safe_load(CATALOG.read_text())
    return {"note": "", "chapters": []}


# What the note says when the catalog is first created and there is nothing to keep. It is
# a FLOOR, not the note: #228 appended the paragraph distinguishing the two fields spelled
# `status`, #229 appended the one describing what a marked row carries, and both are longer
# than anything this module knows about. Restating this literal on every write deleted 1,430
# characters of them, in a diff that also touched thousands of rule rows (#241).
INITIAL_NOTE = (
    "Discovery map of ALL OAR chapters (Gate #1 input for the mass import): every "
    "chapter's divisions and rule numbers, discovered from OARD itself "
    "(secure.sos.state.or.us/oard), not from oregon.public.law -- that mirror was measured "
    "2026-08-27 to omit 5,730 rules in 325 divisions across the 168 chapters this corpus "
    "mirrors, plus chapters 419 and 950 entirely (#270). The chapter-number -> internal "
    "`selectedChapter` id is resolved from the `ruleSearch.action` dropdown at run time, "
    "never hardcoded, because it is OARD's own bookkeeping and may move. A chapter the "
    "dropdown does not carry is a recorded refusal, not a silent skip. OARD's chapter "
    "listing is a CURRENT rules view, so a catalogued rule it does not list is history, "
    "not gone; MERGE, NEVER REPLACE is the rule of this module and a run whose merge would "
    "drop an already-held rule row refuses to save. Rule CONTENT always comes from the "
    "official OARD per-rule URL at ingest time. Per-rule status: 'ingested' means a full "
    "document exists in rules/; renumbered/not_served/not_sliceable are recorded by "
    "ingest_oar.py. Chapter titles from the agency registry.")


def save_catalog(cat, discovered_note=True, stamp_retrieved=True):
    # THE FILE'S NOTE IS THE FILE'S (#241). This module writes it only when there is none;
    # it never restates one that exists, because it does not know what has been added to it.
    if not cat.get("note"):
        cat["note"] = INITIAL_NOTE
    # AND `retrieved` IS A CLAIM THAT SOMETHING WAS RETRIEVED (#259). A run that discovered
    # nothing -- because the source does not carry the chapter -- used to stamp today's date
    # anyway, which is the same substitution one field over.
    if stamp_retrieved:
        cat["retrieved"] = TODAY
    cat["chapters"].sort(key=lambda c: (len(c["chapter"]), c["chapter"]))
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))


class DiscoveredNothing(Exception):
    """The source served no divisions for this chapter, so nothing was discovered."""

    def __init__(self, chapter):
        self.chapter = chapter
        super().__init__(f"the discovery source lists no divisions for chapter {chapter}")


class ChapterNotListed(Exception):
    """OARD's `ruleSearch.action` dropdown does not carry this chapter -- A RECORDED
    REFUSAL, not a silent skip (#270, same shape as #259's DiscoveredNothing one level
    up: nothing is written, nothing is stamped discovered, and the next run tries again).
    Chapter 624 is the live instance: 181 chapters are in the dropdown, 624 is not one of
    them, and this catalog holds 15 rules for it that this refusal leaves untouched."""

    def __init__(self, chapter, n_listed):
        self.chapter = chapter
        super().__init__(
            f"chapter {chapter} is not in OARD's ruleSearch.action dropdown "
            f"({n_listed} chapters listed)")


class WouldRemoveRules(Exception):
    """THE LOAD-BEARING GUARD (#270). OARD's chapter listing is a CURRENT rules view --
    2,566 catalogued rules were measured 2026-08-27 to be absent from it, and they are
    history (a renumber, a repeal), not gone. `merge_divisions` is written to carry every
    already-held rule row forward regardless of whether OARD's current listing still names
    it; this is the backstop that does not TRUST that logic to be bug-free. It compares the
    full set of rule numbers before and after a merge and refuses to save if the merge would
    still narrow it -- a run that would remove a rule row fails, it does not commit."""

    def __init__(self, chapter, missing):
        self.chapter = chapter
        self.missing = sorted(missing)
        preview = ", ".join(self.missing[:10])
        more = f" (+{len(self.missing) - 10} more)" if len(self.missing) > 10 else ""
        super().__init__(
            f"chapter {chapter}: merge would drop {len(self.missing)} rule row(s) already "
            f"in the catalog: {preview}{more}")


def chapter_id_map(raw: str) -> dict:
    """Chapter number -> OARD's internal `selectedChapter` id, read from the
    `ruleSearch.action` dropdown. Resolved fresh every run rather than hardcoded (#270):
    the id is OARD's own bookkeeping, not the chapter number, and may move."""
    return {chapter: chapter_id for chapter_id, chapter in CHAPTER_OPTION_RE.findall(raw)}


def parse_chapter_rules(raw: str) -> list:
    """One `displayChapterRules.action` page -> [(division, title, [rule_number, ...])].

    Pure parsing, no network -- the seam `--selftest` exercises directly. Each division's
    heading is printed TWICE on the page (once as "Division N - TITLE", once as bare
    "TITLE"); matching only the "Division N -" form and slicing the raw HTML between one
    match and the next is what keeps a division's rules from leaking into its neighbour's,
    and needs `re.S` -- a title that wraps a newline (`INTELLECTUAL PROPERTY\\n`) is exactly
    where a `.` without DOTALL silently drops 23 of chapter 813's 82 divisions.

    RULE_RE's second group matches the leadline text printed beside each rule number, which
    the page requires `re.S` to reach across too (a leadline that wraps a newline before its
    closing `</p>` is chapter 813 division 4, live) -- but nothing in this module or its
    callers reads the captured text itself (module docstring), so it is discarded here
    rather than threaded through merge_divisions and the catalog schema for no reader."""
    matches = list(DIVISION_RE.finditer(raw))
    divisions = []
    for i, m in enumerate(matches):
        div_num = m.group(1)
        div_title = re.sub(r"\s+", " ", unescape(m.group(2))).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        chunk = raw[start:end]
        rule_numbers = [num for num, _leadline in RULE_RE.findall(chunk)]
        divisions.append((div_num, div_title, rule_numbers))
    return divisions


def catalog_claimed_numbers(cat: dict) -> set:
    """Every rule number the catalog ANYWHERE already authoritatively tracks -- a row's own
    `number`, or the `served_as` number it points at (#237, the #270 collision this
    exists to prevent). `catalog_agreement.py`'s own words for what happens without this:
    "Adding rows for them breaks the re-ingest join by number: measured, 18 violations."

    #237's own case: chapters 419 and 950 hold 303 documents on disk, and EVERY ONE is
    already a `served_as` target of a row filed under the chapter it was ORIGINALLY
    discovered in -- 333-002-0000 carries `served_as: 950-050-0000`, not a fresh
    950-050-0000 row. Measured 2026-08-27 against OARD's own listing for those two
    chapters: 258 of 419's 295 named rules and 44 of 950's 59 are exactly this shape.
    Giving them a SECOND row keyed by the served number is the addition #237 says was
    "tried, measured, reverted" -- two rows both claiming to BE the same document, which
    is what the re-ingest join (reads the catalog BY NUMBER) cannot resolve."""
    claimed = set()
    for c in cat.get("chapters", []):
        for d in c.get("divisions") or []:
            for r in d.get("rules") or []:
                claimed.add(r["number"])
                if r.get("served_as"):
                    claimed.add(r["served_as"])
    return claimed


# Marks written by merge_divisions, read back by history_count() and (the division-level
# ones) by review_queue.py -- named here, not underscored, because they cross that module
# boundary the same way legal_status.ACTION_KEY/CATALOG_KEY/NOTICE_KEY do: imported rather
# than respelled, so a reader stops finding what the writer writes only if this constant
# itself changes.
HISTORY_MARK = "not on OARD's current chapter listing"
VANISHED_DIVISION_MARK = "no longer listed on OARD"
CLAIMED_ELSEWHERE_DIVISION_MARK = "every rule OARD lists here is already claimed under another row"
CONFIRMED_EMPTY_DIVISION_MARK = "OARD lists no current rules under this division"
_HISTORY_SUFFIX_RE = re.compile(r" \(" + re.escape(HISTORY_MARK) + r".*\)$")


def display_note(note: str) -> str:
    """The note a HUMAN should read, with a carry-forward HISTORY_MARK suffix stripped.

    merge_divisions appends that suffix to whatever note a row already had (#270 follow-up:
    the mark must land even on a row ingest_oar.py already wrote one for, or history_count()
    undercounts -- see merge_divisions's own comment). For the 533 renumbered/not_served
    rows, that existing note ALREADY says why the row is absent from OARD's current listing
    under its own number ("OARD serves 123-021-2100 for this number" implies exactly that),
    so the appended suffix is true but redundant -- and review_queue.py's renumbered section
    truncates at 90 characters, so the redundant half was pushing the useful half (which
    number OARD actually serves) out of what a reviewer sees. Callers that want the raw,
    unstripped note for counting (history_count) read `note` directly; callers building
    something a HUMAN reads should call this first."""
    return _HISTORY_SUFFIX_RE.sub("", note or "")


def merge_divisions(old_divisions: list, discovered: list, claimed_elsewhere: set = frozenset()) -> tuple:
    """MERGE, NEVER REPLACE (#270). `discovered` is what OARD's chapter page names today
    (a CURRENT rules view); `old_divisions` is what the catalog already holds for THIS
    chapter. Every rule number the catalog already carries survives the merge, whether or
    not OARD's current listing still names it -- a rule absent from a current-rules view is
    history (a renumber, a repeal), and this corpus keeps history because deleting a
    document breaks every citation pointing at it. Per-rule status
    (ingested/renumbered/not_served/...) is carried across unchanged for every number that
    IS still named.

    `claimed_elsewhere` is `catalog_claimed_numbers()` computed BEFORE this chapter's own
    numbers exist in it (#237): a number OARD names for this chapter that some OTHER row
    already authoritatively claims -- another chapter's, or, live 2026-08-27 in chapter
    199, a row filed under a DIFFERENT DIVISION of this SAME chapter -- is named in the
    returned skip list, never given a second row here. "Other chapter" is the common case,
    not the rule; #237's invariant is about rows, not chapters.

    NEVER MUTATES `old_divisions` OR ANYTHING IN IT. A run whose merge would drop a rule
    row raises before saving (WouldRemoveRules), and `cmd_discover` is written on the
    assumption that a raised merge leaves the caller's catalog exactly as it found it --
    which requires every dict this function hands back to be a fresh one, never the same
    object a mutated `old_divisions` row already was.

    Returns (new_divisions, skipped_claimed_elsewhere)."""
    old_rules_by_number = {}
    old_by_division = {}
    for d in old_divisions:
        old_by_division[d["division"]] = d
        for r in d.get("rules") or []:
            old_rules_by_number[r["number"]] = r

    new_divisions = []
    skipped = []
    for div_num, div_title, rule_numbers in discovered:
        named_numbers = set(rule_numbers)
        row_list = []
        division_skipped = []
        # DEDUPE BY NUMBER. OARD's chapter page prints a number MORE THAN ONCE when a
        # single number is ambiguous and its own per-rule page is a search-results list,
        # not a rule (#251's live case: 165-020-0125, 5 leadlines under one number on the
        # chapter page too). Walking `rule_numbers` unfiltered gave that one number 5
        # identical rows, caught by catalog_agreement.py's #237 gate: "2 document(s) are
        # claimed by more than one non-renumbered row." One row per NUMBER, same as every
        # other rule.
        for num in dict.fromkeys(rule_numbers):
            old_entry = old_rules_by_number.get(num)
            if old_entry is None:
                if num in claimed_elsewhere:
                    skipped.append(num)
                    division_skipped.append(num)
                    continue
                row_list.append({"number": num, "status": "not_ingested"})
            else:
                # A FRESH COPY, never the object living inside `old_divisions` -- see the
                # docstring above. `entry["number"] = num` used to write straight into that
                # shared object, which is harmless when `num` already equals it (the only
                # way it gets here) but was still a mutation the caller never asked for.
                row_list.append(dict(old_entry, number=num))
        old_div = old_by_division.get(div_num)
        for r in (old_div.get("rules") if old_div else []) or []:
            if r["number"] not in named_numbers:
                r = dict(r)  # a fresh copy -- see the docstring above
                # THE HISTORY MARK IS A FACT, THE NOTE TEXT IS PROSE (#270 follow-up). A
                # row can already carry a note from an earlier writer -- ingest_oar.py
                # overwrites `note` directly for its own per-rule cases, and #241 is why
                # this module never does the same. `setdefault` used to mean such a row
                # was carried forward SILENTLY, unmarked, and invisible to history_count():
                # live chapter 813 has 52 rows OARD's current listing does not name, and
                # the old setdefault-only code marked only 51 -- 813-005-0020 already
                # carried the #251 search-results-list note and the mark never landed.
                # Appending keeps that existing note intact (#241's lesson) while still
                # guaranteeing HISTORY_MARK ends up in it either way.
                existing_note = r.get("note")
                if not existing_note:
                    r["note"] = f"{HISTORY_MARK} — history, kept (ADR 0006, #270)"
                elif HISTORY_MARK not in existing_note:
                    r["note"] = f"{existing_note} ({HISTORY_MARK} — history, kept, ADR 0006 #270)"
                row_list.append(r)
        row_list.sort(key=lambda r: r["number"])
        division = {
            "division": div_num,
            "title": div_title,
            # THE SAME ONE DECLARATION ingest_oar uses (#236).
            "status": division_status(row_list),
            "rules": row_list,
        }
        if not row_list:
            # AN EMPTY DIVISION IS A CLAIM, NOT A GAP (#270 follow-up). Both cases below
            # were mechanically confirmed by this run, not left unenumerated -- neither
            # belongs in REVIEW.md's "could not enumerate mechanically" section, and
            # review_queue.py reads these two marks to say so.
            if division_skipped:
                # Every number OARD lists here is a served_as target some other row
                # already claims (live case: chapter 199 division 8 -- OARD lists six
                # numbers, all six already claimed by rows filed under divisions 1 and 5
                # of this SAME chapter). The division is real; there is nothing to
                # enumerate a SECOND time under its own number.
                division["note"] = (
                    f"{CLAIMED_ELSEWHERE_DIVISION_MARK} ({len(division_skipped)} rule(s): "
                    f"{', '.join(sorted(division_skipped))}) — covered, not a gap")
            elif not rule_numbers:
                # OARD's own page said so ("There are no rules to display."), live case
                # chapter 104 division 25 -- a confirmed-empty division, not one this run
                # failed to enumerate.
                division["note"] = f"{CONFIRMED_EMPTY_DIVISION_MARK} — confirmed, not a gap"
        new_divisions.append(division)

    # keep any old divisions OARD no longer lists at all (never silently drop)
    seen = {d["division"] for d in new_divisions}
    for d in old_divisions:
        if d["division"] not in seen and (d.get("rules") or []):
            d = dict(d)  # a fresh copy -- see the docstring above
            d.setdefault("note", "division no longer listed on OARD — verify upstream")
            new_divisions.append(d)
    return new_divisions, skipped


def _rule_numbers(divisions: list) -> set:
    return {r["number"] for d in divisions for r in (d.get("rules") or [])}


def history_count(cat: dict) -> int:
    """Rules PRESENT in this catalog and ABSENT from OARD's current-rules listing --
    exactly what merge_divisions's carry-forward and the vanished-division fallback both
    mark (#270). This is the other half of the acceptance criterion's delta: not just what
    OARD added, but what this catalog holds that OARD's CURRENT view no longer speaks
    for -- a renumber, a repeal, kept per ADR 0006."""
    n = 0
    for c in cat.get("chapters", []):
        for d in c.get("divisions") or []:
            if VANISHED_DIVISION_MARK in (d.get("note") or ""):
                n += len(d.get("rules") or [])
                continue
            n += sum(1 for r in (d.get("rules") or [])
                     if HISTORY_MARK in (r.get("note") or ""))
    return n


def discover_chapter(ch: str, title: str, chapter_id: str, cat: dict) -> tuple:
    """Fetch one chapter's divisions + rule numbers from OARD; merge into cat preserving
    existing rule statuses. Returns
    (n_divisions, n_divisions_added, n_rules, n_new, n_claimed_elsewhere)."""
    raw = get(f"{OARD_BASE}/displayChapterRules.action?selectedChapter={chapter_id}")
    time.sleep(0.2)
    discovered = parse_chapter_rules(raw)

    existing = next((c for c in cat["chapters"] if c["chapter"] == ch), None)
    if not discovered and not (existing or {}).get("divisions"):
        # A FETCH THAT FOUND NOTHING IS NOT A DISCOVERY (#259, carried over to OARD). The
        # id came straight from OARD's own dropdown, so a real chapter with genuinely zero
        # current divisions is not ruled out -- but neither is a transient or malformed
        # response, and `get()` cannot tell the two apart. Could not check, written as is
        # not there.
        raise DiscoveredNothing(ch)

    old_divisions = (existing or {}).get("divisions", [])
    old_division_numbers = {d["division"] for d in old_divisions}
    before = _rule_numbers(old_divisions)
    # Computed from `cat` BEFORE this chapter's merge touches it (#237) -- a number OARD
    # names here that some OTHER row already claims (own number OR served_as) never gets a
    # second row; see catalog_claimed_numbers().
    claimed_elsewhere = catalog_claimed_numbers(cat) - before
    new_divisions, skipped = merge_divisions(old_divisions, discovered, claimed_elsewhere)
    after = _rule_numbers(new_divisions)
    missing = before - after
    if missing:
        raise WouldRemoveRules(ch, missing)

    if existing is None:
        existing = {"chapter": ch, "title": title,
                    "url": f"{OARD_BASE}/displayChapterRules.action?selectedChapter={chapter_id}",
                    "divisions": []}
        cat["chapters"].append(existing)
    existing["title"] = title
    existing["url"] = f"{OARD_BASE}/displayChapterRules.action?selectedChapter={chapter_id}"
    n_new = sum(1 for d in new_divisions for r in (d.get("rules") or [])
                if r["number"] not in before and r.get("status") == "not_ingested")
    n_rules = len(after)
    n_divisions_added = sum(1 for d in new_divisions if d["division"] not in old_division_numbers)
    existing["divisions"] = new_divisions
    existing["discovered"] = TODAY
    # SELF-CLEARING (#270 follow-up): this chapter WAS just found in OARD's dropdown and
    # walked, so whatever an earlier run's NOT LISTED refusal recorded on this row is no
    # longer true. See the marker's own write site below in cmd_discover.
    existing.pop("not_in_oard_dropdown", None)
    # RECORDED, NOT SILENT (#237, #270): named on the row itself so a reader of the catalog
    # -- not just this run's stdout -- sees why OARD names more rules for this chapter than
    # this row lists. Cleared when a later run finds nothing to record, rather than left
    # stating a fact about a run that is no longer this run's.
    existing.pop("claimed_by_other_chapters", None)  # migrate off the #270 field name (below)
    if skipped:
        existing["claimed_by_another_row"] = sorted(set(skipped))
    else:
        existing.pop("claimed_by_another_row", None)
    return len(new_divisions), n_divisions_added, n_rules, n_new, len(set(skipped))


def registry_chapters(reg: dict) -> list:
    """Every (chapter, title) discovery walks, shortest chapter number first.

    NAME READER — JOIN (OAR-derived). Pairing a chapter number with a name is an OAR-keyed
    join by construction: the chapter is the OAR index's key and the title written beside it
    in _meta/catalog/oar.yml is the name that index prints for the body — `oar_name`
    (CONTEXT.md, *OAR name*). It read `name` until ADR 0003 moved the ground under that
    field, and the two still hold identical bytes on 186 of the 189 committed rows — four
    rows have an established statutory name (#168) and only three of those differ from the
    OAR title — so the change is all but invisible in the data and visible in the
    fault-injected fixture below.

    A chapter whose row carries no `oar_name` is REFUSED rather than walked under whatever
    other name the row happens to hold. Every row is required to carry one
    (`catalog_agencies.py --check`), so this is a registry that has already broken its
    contract, and discovering it under a substitute name would write that substitute into
    the catalog as though the rules index printed it."""
    chapters = []
    for o in reg["organizations"]:
        if not o.get("oar_chapter"):
            continue
        if not o.get("oar_name"):
            raise SystemExit(f"chapter {o['oar_chapter']} ({o.get('slug')!r}): registry row "
                             "carries no oar_name — run catalog_agencies.py --check")
        chapters.append((o["oar_chapter"], o["oar_name"]))
    chapters.sort(key=lambda t: (len(t[0]), t[0]))
    return chapters


def cmd_discover(only: list):
    reg = yaml.safe_load(REGISTRY.read_text())
    chapters = registry_chapters(reg)
    if only:
        chapters = [c for c in chapters if c[0] in only]
    cat = load_catalog()

    id_map = chapter_id_map(get(CHAPTER_LIST_URL))
    time.sleep(0.2)

    total_d = total_da = total_r = total_new = total_claimed = skipped = 0
    found_nothing = []
    not_listed = []
    failed = []
    for i, (ch, title) in enumerate(chapters, 1):
        existing = next((c for c in cat["chapters"] if c["chapter"] == ch), None)
        pre_rule_count = sum(len(d.get("rules") or []) for d in (existing or {}).get("divisions", []))
        if ch not in id_map:
            # A RECORDED REFUSAL, not a silent skip (#270, same shape as #259's
            # DiscoveredNothing): checked -- and reported -- on EVERY run, ahead of the
            # already-discovered skip below, because a chapter's absence from OARD's
            # dropdown is a fact about this run and not something one run can clear for
            # every run after it. The catalog entry is left exactly as it was, except for
            # the marker below, which makes the refusal survive on the row itself and not
            # just in this run's stdout -- and self-clears in discover_chapter the day the
            # chapter reappears in the dropdown, rather than asserting it forever.
            e = ChapterNotListed(ch, len(id_map))
            if existing is not None:
                existing["not_in_oard_dropdown"] = True
            not_listed.append((ch, title, pre_rule_count))
            print(f"NOT LISTED chapter {ch} ({title[:50]}): {e} — catalog entry untouched "
                  f"({pre_rule_count} rules held), and the next run will try again")
            continue
        if (existing and existing.get("discovered") and not only
                and "--redo" not in sys.argv):
            skipped += 1
            continue
        try:
            nd, nda, nr, nn, nc = discover_chapter(ch, title, id_map[ch], cat)
        except DiscoveredNothing as e:
            found_nothing.append(ch)
            print(f"NOT DISCOVERED chapter {ch}: {e} — no entry written, not marked "
                  f"discovered, and the next run will try again (#259)")
            continue
        except WouldRemoveRules as e:
            # THE LOAD-BEARING GUARD FIRES: stop the whole run rather than silently
            # skipping this chapter. Whatever earlier chapters already checkpointed to
            # disk this run stays saved; this chapter's merge is never written.
            save_catalog(cat, stamp_retrieved=total_d > 0)
            print(f"REFUSED chapter {ch}: {e}", file=sys.stderr)
            raise
        except Exception as e:
            # COULD NOT CHECK IS NEVER IS NOT THERE (CONTEXT.md): a transient fetch error
            # or a malformed page is not the same fact as ChapterNotListed or
            # DiscoveredNothing, and unlike them it used to get named once mid-scroll and
            # then vanish -- a run short by N chapters ended with a summary that did not
            # say so. `failed` is read below, same shape as `found_nothing`/`not_listed`.
            failed.append((ch, str(e)))
            print(f"FAILED chapter {ch}: {e}")
            continue
        total_d += nd
        total_da += nda
        total_r += nr
        total_new += nn
        total_claimed += nc
        claimed_note = f", {nc} already claimed under another row (#237)" if nc else ""
        print(f"[{i}/{len(chapters)}] ch {ch:>4} ({title[:50]}): "
              f"{nd} divisions ({nda} new), {nr} rules ({nn} new, {nr - pre_rule_count:+d} vs "
              f"catalog{claimed_note})")
        save_catalog(cat)  # checkpoint after every chapter — resumable
    save_catalog(cat, stamp_retrieved=total_d > 0)
    print(f"\ndiscovered: {total_d} divisions ({total_da} new to the catalog), {total_r} "
          f"rules ({total_new} new added to the catalog); {skipped} chapters already "
          f"discovered (use --redo to refresh)")
    # THE OTHER HALF OF THE DELTA (#270 acceptance criteria): not just what OARD adds, but
    # what this catalog holds that OARD's CURRENT listing does not -- history, kept.
    print(f"{history_count(cat)} rule(s) in this catalog are absent from OARD's current "
          f"listing (history: a renumber, a repeal) and were kept, not dropped")
    if total_claimed:
        print(f"{total_claimed} rule number(s) OARD names were NOT given a second row: "
              f"already authoritatively claimed (by number or served_as) under another row "
              f"-- #237's invariant, not a #270 regression, and not always a different "
              f"chapter's row: recorded per chapter in claimed_by_another_row.")
    if found_nothing:
        print(f"{len(found_nothing)} chapter(s) the discovery source does not carry, left "
              f"UNDISCOVERED rather than recorded as empty: {', '.join(found_nothing)}")
    if not_listed:
        held = sum(n for _, _, n in not_listed)
        names = ", ".join(f"{c} ({n} held)" for c, _, n in not_listed)
        print(f"{len(not_listed)} chapter(s) not in OARD's dropdown, REFUSED rather than "
              f"skipped ({held} rules held here and unwatched by this run): {names}")
    if failed:
        print(f"{len(failed)} chapter(s) FAILED with an unexpected error and were NOT "
              f"discovered this run -- a transient fetch or a malformed page, not a "
              f"recorded refusal like NOT LISTED, so the next run should be watched: "
              f"{', '.join(ch for ch, _ in failed)}")


def cmd_summary():
    cat = load_catalog()
    total = ingested = 0
    rows = []
    for c in sorted(cat["chapters"], key=lambda c: (len(c["chapter"]), c["chapter"])):
        n = sum(len(d.get("rules") or []) for d in c["divisions"])
        ing = sum(1 for d in c["divisions"] for r in d.get("rules") or []
                  if r.get("status") == "ingested")
        total += n
        ingested += ing
        rows.append((c["chapter"], c["title"], len(c["divisions"]), n, ing))
    for ch, title, nd, n, ing in rows:
        print(f"{ch:>4}  {nd:3d} div  {n:5d} rules  {ing:5d} ingested  {title[:55]}")
    print(f"\nTOTAL: {len(rows)} chapters, {total} rules, {ingested} ingested, "
          f"{total - ingested} to import")


# ------------------------------------------------------------------------------ selftest
#
# THE PROOF THAT DISCOVERY IS KEYED ON THE OAR NAME. The fixture's two names differ, which
# 186 of the 189 committed registry rows do not: `name` and `oar_name` hold the same bytes
# on every row whose statutory name is unestablished AND on the one established row whose
# statute agrees with the rules index (#168), so a fixture built from committed data would
# pass whichever field this code reads on all but three rows.
# Synthetic: no network, no read of the committed registry or catalog.


def _fixture_registry():
    """A registry in the state ADR 0003 leaves it in — `name` promoted to the statutory
    name, `oar_name` still the rules index's chapter title — plus one body holding no
    chapter, because 19 rows hold none and discovery must not walk them."""
    return {"organizations": [
        {"slug": "department-of-administrative-services",
         "name": "Oregon Department of Administrative Services",
         "oar_name": "Department of Administrative Services", "oar_chapter": "125"},
        {"slug": "board-of-nursing", "name": "Oregon State Board of Nursing",
         "oar_name": "Board of Nursing", "oar_chapter": "851"},
        {"slug": "office-of-the-governor", "name": "Office of the Governor",
         "oar_name": "Office of the Governor", "oar_chapter": None},
    ]}


def selftest() -> int:
    check = Checks()
    reg = _fixture_registry()
    chapters = registry_chapters(reg)
    check("every chapter-holding body is discovered", [c for c, _ in chapters] == ["125", "851"])
    check("a body with no chapter is not discovered",
          "office-of-the-governor" not in str(chapters))
    titles = dict(chapters)
    check("the chapter title is the OAR name",
          titles["125"] == "Department of Administrative Services")
    check("the chapter title is not the statutory name",
          titles["125"] != "Oregon Department of Administrative Services")
    # A ROW THAT CANNOT NAME ITS CHAPTER. Every row is required to carry an `oar_name`
    # (catalog_agencies.py --check), so this is unreachable — and if it is reached, the
    # chapter is REPORTED as undiscoverable rather than walked under a title taken from
    # some other field: "could not check" is never reported as "is not there" (CONTEXT.md).
    broken = {"organizations": [{"slug": "a-body", "name": "A Body", "oar_chapter": "999"}]}
    try:
        registry_chapters(broken)
        check("a chapter whose row carries no oar_name is refused", False)
    except SystemExit as e:
        check("a chapter whose row carries no oar_name is refused", "oar_name" in str(e))

    # THE CHAPTER -> ID MAP (#270). Real structure measured 2026-08-27 against
    # ruleSearch.action: two placeholder options with value="-1" (\d+ does not match the
    # minus sign, so they are excluded without a special case), and every real chapter
    # printed once per <select> -- this repo's page carries two identical <select>s, so a
    # fixture with the option repeated proves the dict comprehension dedupes rather than
    # erroring on the second, differently-cased occurrence.
    dropdown_fixture = (
        '<select name="selectedChapter" id="selectedChapter">'
        '<option value="-1">Select a chapter...</option>'
        '<option value="144">813 - Oregon Housing and Community Services Department</option>'
        '<option value="361">419 - Department of Human Services, OTIS</option>'
        '</select>'
        '<select name="selectedChapter">'
        '<option value="-1">Select a Chapter...</option>'
        '<option value="144">813 - Oregon Housing and Community Services Department</option>'
        '<option value="361">419 - Department of Human Services, OTIS</option>'
        '</select>')
    id_map = chapter_id_map(dropdown_fixture)
    check("the chapter id map resolves a real chapter to its internal id",
          id_map.get("813") == "144")
    check("the chapter id map excludes the -1 placeholder", "-1" not in id_map.values())
    check("chapter 624 -- absent from the live dropdown 2026-08-27 -- is absent here too",
          "624" not in id_map)

    # PARSING ONE CHAPTER PAGE (#270). Fixture shaped like the real
    # displayChapterRules.action structure measured against chapter 813: each division
    # heading printed TWICE (once as "Division N - TITLE", once bare), a title that wraps a
    # newline (division 3 loses 23 of chapter 813's 82 divisions without re.S), and a
    # leadline that wraps onto the next line before its closing </p> (division 4, chapter
    # 813 live).
    chapter_page_fixture = """
    <h3><a href='x?selectedDivision=8362'>Division 2&nbsp;-&nbsp;AFFORDABLE RENTAL HOUSING</a></h3>
    <h3><a href='x?selectedDivision=8362'>AFFORDABLE RENTAL HOUSING</a></h3>
    <p><strong><a href='x?ruleVrsnRsn=1'>813-002-0005</a></strong>&nbsp;&nbsp;Purpose and Objectives</p>
    <p><strong><a href='x?ruleVrsnRsn=2'>813-002-0010</a></strong>&nbsp;&nbsp;Definitions</p>
    <h3><a href='x?selectedDivision=3605'>Division 3&nbsp;-&nbsp;INTELLECTUAL
    PROPERTY</a></h3>
    <h3><a href='x?selectedDivision=3605'>INTELLECTUAL
    PROPERTY</a></h3>
    <p><strong><a href='x?ruleVrsnRsn=3'>813-003-0001</a></strong>&nbsp;&nbsp;Confidentiality and Inadmissibility of Mediation Communications
    </p>
    """
    parsed = parse_chapter_rules(chapter_page_fixture)
    check("every division in the fixture is parsed", len(parsed) == 2)
    div2 = next(d for d in parsed if d[0] == "2")
    check("division 2's rules are its own, not division 3's",
          div2[2] == ["813-002-0005", "813-002-0010"])
    div3 = next(d for d in parsed if d[0] == "3")
    check("a division title that wraps a newline is still read (needs re.S)",
          div3[1] == "INTELLECTUAL PROPERTY")
    check("a rule whose leadline wraps onto the next line before its </p> is still "
          "discovered by number (needs re.S on RULE_RE too)",
          div3[2] == ["813-003-0001"])

    # AN AMBIGUOUS NUMBER IS PRINTED MORE THAN ONCE (#251's shape, found live in chapter
    # 165 running this discovery for real 2026-08-27): OARD's per-rule page for
    # 165-020-0125 is a search-results list because more than one rule shares the number,
    # and its CHAPTER page reflects that the same way -- one <p> per underlying rule, all
    # under the identical number. `merge_divisions` must produce ONE row for it, not one
    # per leadline.
    div_dup = next(d for d in parse_chapter_rules(
        "<h3><a href='x?selectedDivision=1'>Division 20&nbsp;-&nbsp;DUP</a></h3>"
        "<h3><a href='x?selectedDivision=1'>DUP</a></h3>"
        "<p><strong><a href='x?ruleVrsnRsn=1'>165-020-0125</a></strong>&nbsp;&nbsp;First rule</p>"
        "<p><strong><a href='x?ruleVrsnRsn=2'>165-020-0125</a></strong>&nbsp;&nbsp;Second rule</p>"
    ) if d[0] == "20")
    check("parse_chapter_rules reports the ambiguous number once per <p> entry on the page",
          div_dup[2] == ["165-020-0125", "165-020-0125"])

    # THE LOAD-BEARING GUARD: MERGE, NEVER REPLACE (#270). Chapter 813 division 1's live
    # 2026-08-27 case: 813-001-0002 and 813-001-0003 are both already in this catalog;
    # OARD's CURRENT rules view (what `discovered` simulates) names only -0002, because
    # -0003 was renumbered and is history. `merge_divisions` must carry -0003 forward
    # anyway, and `WouldRemoveRules` is the backstop that refuses to save if some future
    # bug in that logic ever drops it regardless.
    old_divisions = [{"division": "1", "title": "GENERAL PROVISIONS", "status": "ingested",
                       "rules": [{"number": "813-001-0002", "status": "ingested"},
                                 {"number": "813-001-0003", "status": "ingested",
                                  "served_as": "813-001-0002"}]}]
    discovered = [("1", "GENERAL PROVISIONS", ["813-001-0002"])]

    # RED, WATCHED BEFORE THE GUARD EXISTED: a merge that does what the pre-#270 code did
    # -- rebuild each division's rules from ONLY what the source names today -- silently
    # drops -0003. This is not hypothetical: it is literally the old discover_chapter's
    # division-rebuild loop, reproduced here to prove the failure mode is real rather than
    # asserted.
    naive_merge = [{"division": d, "title": t,
                     "rules": [{"number": n, "status": "not_ingested"} for n in rs]}
                    for d, t, rs in discovered]
    naive_missing = _rule_numbers(old_divisions) - _rule_numbers(naive_merge)
    check("RED: a rebuild-from-source-only merge is caught DROPPING a history row",
          naive_missing == {"813-001-0003"})
    try:
        raise WouldRemoveRules("813", naive_missing)
    except WouldRemoveRules as e:
        check("...and the guard names the dropped rule in its own message",
              "813-001-0003" in str(e))

    # GREEN: the real merge does not drop it, so the guard never fires on it.
    merged, skipped = merge_divisions(old_divisions, discovered)
    merged_numbers = _rule_numbers(merged)
    check("merge_divisions keeps a rule OARD's current listing no longer names",
          "813-001-0003" in merged_numbers)
    check("...alongside the rule OARD still names",
          "813-001-0002" in merged_numbers)
    check("no rule the catalog already held is dropped by the real merge",
          _rule_numbers(old_divisions) - merged_numbers == set())
    check("nothing was skipped as claimed elsewhere in this fixture (none was)",
          skipped == [])
    kept_row = next(r for r in merged[0]["rules"] if r["number"] == "813-001-0003")
    check("a carried-forward history row is marked, not silently kept unlabeled",
          "history" in kept_row.get("note", ""))
    check("a carried-forward history row keeps its prior status untouched",
          kept_row["status"] == "ingested")

    # ...and the ambiguous number gets exactly one row, not one per leadline (#251 shape,
    # caught live 2026-08-27 by catalog_agreement.py's #237 gate against 165-020-0125:
    # "2 document(s) are claimed by more than one non-renumbered row").
    dup_merged, _ = merge_divisions([], [div_dup])
    dup_rows = [r for r in dup_merged[0]["rules"] if r["number"] == "165-020-0125"]
    check("RED-then-fixed: an ambiguous number printed twice gets ONE catalog row",
          len(dup_rows) == 1)

    # #237, THE REGRESSION #270 MUST NOT REINTRODUCE. Chapter 419's live case, reproduced
    # as a fixture: chapter 333's row already claims 419-050-0000 via `served_as` (that IS
    # #237's shape -- 303 documents on disk under rules/419 and rules/950, every one
    # already a served_as target of a row filed under its ORIGINAL chapter). OARD's
    # chapter-419 page also names 419-050-0000 -- of course it does, that is the number it
    # currently serves the rule under -- and a naive merge would give it a SECOND row here,
    # which is exactly what catalog_agreement.py's #237 comment says was "tried, measured,
    # reverted": two rows both claiming to BE the same document.
    other_chapter_cat = {"chapters": [
        {"chapter": "333", "divisions": [{"division": "2", "rules": [
            {"number": "333-002-0000", "status": "ingested", "served_as": "419-050-0000",
             "path": "rules/419/050/oar-419-050-0000.md"}]}]}]}
    claimed = catalog_claimed_numbers(other_chapter_cat)
    check("catalog_claimed_numbers reads a served_as target as claimed",
          "419-050-0000" in claimed)
    ch419_discovered = [("050", "SOME DIVISION", ["419-050-0000", "419-050-9999"])]
    ch419_merged, ch419_skipped = merge_divisions([], ch419_discovered, claimed)
    check("a number another row already claims is skipped here, not duplicated",
          "419-050-0000" in ch419_skipped and
          "419-050-0000" not in _rule_numbers(ch419_merged))
    check("...while a genuinely new number under the same chapter is still added",
          "419-050-9999" in _rule_numbers(ch419_merged))

    # A DIVISION MAY BE ENTIRELY CLAIMED ELSEWHERE (#270 follow-up, live case chapter 199
    # division 8: OARD lists six numbers, all six already claimed by rows filed under
    # DIVISIONS 1 AND 5 OF THIS SAME CHAPTER -- "another row", not always "another
    # chapter"). merge_divisions must not write that as an unexplained zero-rule
    # not_ingested division -- review_queue.py would read it as an enumeration gap needing
    # "another route", when it is already fully covered.
    claimed_div_discovered = [("8", "COMPLIANCE AND SANCTIONS", ["199-008-0005", "199-008-0008"])]
    claimed_div_merged, claimed_div_skipped = merge_divisions(
        [], claimed_div_discovered, {"199-008-0005", "199-008-0008"})
    div8 = claimed_div_merged[0]
    check("a division whose every rule is claimed under another row gets zero rows here",
          div8["rules"] == [] and set(claimed_div_skipped) == {"199-008-0005", "199-008-0008"})
    check("...and is marked covered, not left an unexplained gap",
          CLAIMED_ELSEWHERE_DIVISION_MARK in (div8.get("note") or ""))

    # A DIVISION MAY GENUINELY HOLD ZERO CURRENT RULES (live case chapter 104 division 25:
    # OARD's own page prints "There are no rules to display."). This was mechanically
    # confirmed, not left unenumerated, and needs a DIFFERENT explanation than the
    # claimed-elsewhere case above -- nothing was skipped, nothing was found.
    empty_div_discovered = [("25", "OREGON DISASTER RESPONSE ASSISTANCE MATCHING FUND", [])]
    empty_div_merged, empty_div_skipped = merge_divisions([], empty_div_discovered)
    div25 = empty_div_merged[0]
    check("a division OARD confirms holds no current rules gets zero rows and no skips",
          div25["rules"] == [] and empty_div_skipped == [])
    check("...and is marked confirmed-empty, not left an unexplained gap",
          CONFIRMED_EMPTY_DIVISION_MARK in (div25.get("note") or ""))

    # DIVISIONS ADDED IS PART OF THE PRINTED DELTA (#270 acceptance criteria: "the run
    # prints the delta -- rules added, divisions added..."). discover_chapter computes it
    # as (division numbers in the merge result) - (division numbers the catalog already
    # held); reproduced here as a unit rather than through discover_chapter, which needs
    # network.
    added_old = [{"division": "1", "rules": [{"number": "813-001-0002", "status": "ingested"}]}]
    added_discovered = [("1", "T", ["813-001-0002"]), ("2", "NEW DIVISION", ["813-002-0001"])]
    added_merged, _ = merge_divisions(added_old, added_discovered)
    added_old_numbers = {d["division"] for d in added_old}
    n_divisions_added = sum(1 for d in added_merged if d["division"] not in added_old_numbers)
    check("a division OARD lists that the catalog did not have before counts as newly added",
          n_divisions_added == 1)

    # MERGE_DIVISIONS NEVER MUTATES THE CALLER'S `old_divisions` (#270 follow-up). The
    # WouldRemoveRules guard's own comment says a refused chapter's "merge is never
    # written" -- true only if nothing this function hands back shares an object with what
    # the caller passed in. Every row below is carried forward (none is dropped), so this
    # exercises the ordinary carry-forward path, not just the refusal path.
    mutation_old = [{"division": "1", "title": "T", "status": "ingested",
                      "rules": [{"number": "813-001-0002", "status": "ingested"},
                                {"number": "813-001-0003", "status": "ingested"}]}]
    mutation_snapshot = yaml.safe_load(yaml.safe_dump(mutation_old))  # a true deep copy
    merge_divisions(mutation_old, [("1", "T", ["813-001-0002"])])
    check("merge_divisions does not mutate the row dicts inside old_divisions",
          mutation_old == mutation_snapshot)

    # THE HISTORY MARK SURVIVES A ROW THAT ALREADY HAD A NOTE (#270 follow-up). Live case
    # chapter 813: 813-005-0020 already carries the #251 search-results-list note by the
    # time it goes absent from OARD's current listing, and `setdefault` used to mean the
    # history mark never landed on it -- measured live, 52 rows absent from chapter 813's
    # current listing, only 51 marked. history_count() must find rows in both states.
    prior_note = ("OARD serves a search-results list for this number rather than a rule "
                  "(#251). Kept rather than deleted: ADR 0006.")
    noted_old = [{"division": "5", "rules": [
        {"number": "813-005-0020", "status": "ingested", "note": prior_note}]}]
    noted_merged, _ = merge_divisions(noted_old, [("5", "T", [])])
    noted_row = noted_merged[0]["rules"][0]
    check("a carried-forward row that already had a note keeps that note",
          "search-results list" in noted_row["note"])
    check("...and still gets the history mark appended, not silently skipped",
          HISTORY_MARK in noted_row["note"])
    check("...so history_count finds it (the #241-lesson case setdefault used to miss)",
          history_count({"chapters": [{"chapter": "813", "divisions": noted_merged}]}) == 1)
    # ...AND A HUMAN READING review_queue.py's renumbered/not_served section still sees the
    # useful half. Every one of the catalog's 533 renumbered/not_served rows already carries
    # a note from ingest_oar.py ("OARD serves X for this number") BEFORE this ever runs, so
    # the appended suffix above is the common case there, not the exception -- and that
    # section truncates at 90 characters, so the appended half was pushing the useful half
    # out. display_note() is what review_queue.py calls before truncating.
    check("display_note() strips the appended history suffix, keeping the original note",
          display_note(noted_row["note"]) == prior_note)
    plain_old = [{"division": "1", "rules": [{"number": "813-001-0099", "status": "ingested"}]}]
    plain_merged, _ = merge_divisions(plain_old, [("1", "T", [])])
    check("...and leaves a row with no prior note as the plain history sentence",
          display_note(plain_merged[0]["rules"][0]["note"]) ==
          f"{HISTORY_MARK} — history, kept (ADR 0006, #270)")

    # THE OTHER HALF OF THE DELTA the run summary prints: rules held here and absent from
    # OARD's current listing. Built from the two ways merge_divisions marks that fact --
    # a per-rule carry-forward note, and a whole vanished division.
    history_cat = {"chapters": [
        {"chapter": "813", "divisions": [
            {"division": "1", "rules": [
                {"number": "813-001-0003", "note": HISTORY_MARK + " -- history, kept"},
                {"number": "813-001-0002"}]},
            {"division": "9", "note": VANISHED_DIVISION_MARK + " — verify upstream",
             "rules": [{"number": "813-009-0000"}, {"number": "813-009-0010"}]}]}]}
    check("history_count finds a per-rule carried-forward row",
          history_count(history_cat) == 3)  # 1 per-rule + 2 in the vanished division

    return check.report()


def main():
    if "--selftest" in sys.argv:
        return selftest()
    if "--discover" in sys.argv:
        only = [a for a in sys.argv[1:] if not a.startswith("--")]
        cmd_discover(only)
    elif "--summary" in sys.argv:
        cmd_summary()
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
