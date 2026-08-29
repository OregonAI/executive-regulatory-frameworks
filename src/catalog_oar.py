#!/usr/bin/env python3
"""Populate _meta/catalog/oar.yml with every chapter's division/rule inventory
(Gate #1 input for the mass OAR import: run this, review the printed summary,
THEN run ingest_oar.py on approved chapters). Idempotent and resumable — the
catalog is written after every chapter, and already-discovered chapters are
skipped unless --redo is given.

  python3 src/catalog_oar.py --discover            # all registry chapters
  python3 src/catalog_oar.py --discover 137 150    # specific chapters
  python3 src/catalog_oar.py --summary             # counts only, no network
  python3 src/catalog_oar.py --check               # CI: every row matches the declared shape
  python3 src/catalog_oar.py --selftest            # CI: every rule --check enforces fires

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

EVERY CHAPTER ROW'S `url` IS RE-RESOLVED AGAINST THE ID MAP ON EVERY --discover
RUN (#280), never carried forward untouched — `refresh_chapter_urls()` applies the
id_map fetched at the top of this run to every catalogued chapter, whether or not that
chapter is otherwise skipped this run for already being discovered. OARD gives this
corpus no chapter-NUMBER-keyed alternative to fall back on instead: measured 2026-08-28,
`displayChapterRules.action?selectedChapter=<n>` reads `<n>` as an id and only an id — a
request built from a chapter NUMBER lands on whatever chapter OARD's dropdown happens to
assign that number to as an id, silently, and `?chapterNumber=`, `?selectedChapterNumber=`
and `?chapter=` are all ignored outright. So a stored id is refreshed rather than trusted:
the id map itself is resolved fresh every run regardless (as above), and this is what
makes that freshness reach the FIELD a reader would actually follow, not just this run's
in-memory dict. A chapter absent from the id map (624 is the only one today — outside
OARD's dropdown entirely) never held a `selectedChapter` url to refresh and keeps
pointing at `ruleSearch.action`'s own chapter picker instead, where a human resolves the
chapter for themselves. THE FIELD'S SHELF LIFE IS THIS CATALOG'S OWN `retrieved` DATE, not
the moment a reader clicks it — nothing runs `--discover` continuously, so an id OARD
renumbers between one run and the next is wrong for exactly that window, undetected until
the next run resolves it fresh. That window is real and stated rather than hidden; it is
the same tradeoff the id map itself already accepts by resolving fresh per run instead of
per click, extended to the field a reader actually follows.

WEIGHED AGAINST THE TICKET'S OTHER HONEST OPTION -- store the chapter NUMBER only and
resolve `url` at read time -- and rejected for now, not on principle: that option closes
the window this one leaves open, at the cost of a live network fetch (a full re-walk of
`ruleSearch.action`'s dropdown, the same request this module already makes once per
`--discover` run) at every point of use instead of once per run. No in-repo consumer reads
this field today (module docstring, above) — `--discover`'s own summary print is the only
reader that exists — so there is no call site yet to carry that cost, and building one to
close a window nothing has walked into would be solving a problem this repo does not have
one of. Should a consumer appear that clicks this field between `--discover` runs, this is
the tradeoff to revisit, not re-litigate: the two options were never a question of which
is more correct, only of where the volatility is cheapest to carry today.

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
from collections import Counter, namedtuple
from datetime import date
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml

from check_rule_ledger import RuleLedger
from ingest_status import INGEST_STATUS_VALUES
from repo_lib import REPO_ROOT, Checks, division_status, oar_rule_path

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
    "ingest_oar.py. Chapter titles from the agency registry. EVERY CHAPTER'S `url` IS "
    "RE-RESOLVED AGAINST THE ID MAP ON EVERY --discover RUN (#280), not carried forward "
    "untouched, and not derived from the chapter number -- OARD accepts no chapter-number "
    "route: `?selectedChapter=<n>` reads `<n>` as an id and lands on whatever chapter "
    "OARD's dropdown currently assigns that id to, and `?chapterNumber=`/`?chapter=` are "
    "silently ignored (measured 2026-08-28). A chapter absent from the id map (624, not in "
    "OARD's dropdown) points at `ruleSearch.action`'s own chapter picker instead. The "
    "field's shelf life is this catalog's own `retrieved` date, not the moment a reader "
    "clicks it: an id OARD renumbers between one --discover run and the next is wrong for "
    "exactly that window, undetected until the next run resolves it fresh.")


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


def refresh_chapter_urls(cat: dict, id_map: dict) -> int:
    """Re-resolve every already-catalogued chapter's `url` against THIS run's own
    `id_map` (#280). `chapter_id_map()` was already re-fetched fresh every run before this
    function existed; what was missing was anything that APPLIED that freshness to a
    chapter's stored `url` once the chapter itself was no longer being walked --
    `cmd_discover`'s already-discovered skip exists to avoid re-fetching and re-parsing a
    chapter's own rules page every run, and had nothing to do with the id map, but it was
    ALSO the only place `url` got written, so a skipped chapter kept whatever id an earlier
    run had resolved, however long ago -- exactly the volatility `chapter_id_map()`'s own
    docstring warns about, just not carried through to the field a reader clicks.

    Measured 2026-08-28 that OARD has no chapter-NUMBER-keyed alternative to fall back on:
    treating chapter 125's own NUMBER as if it belonged in the id slot --
    `displayChapterRules.action?selectedChapter=125` -- served chapter 661, because 125 is
    what OARD's dropdown assigns as the ID of a wholly different chapter, not what it
    accepts as a chapter number. `?chapterNumber=125` and `?selectedChapterNumber=125` are
    silently ignored, byte-identical (5,505 bytes, sha256 9f5b802449bd...) to the error
    page a request with no parameter at all gets, which itself carries an explicit
    `<div class="errors">...Error retrieving chapter and current rules.</div>`.
    `?chapter=125` is ALSO ignored but not identically -- a shorter, different page (5,320
    bytes, sha256 9fe7ee537c27...) that silently drops that error block rather than
    reproducing it, so this one fails more quietly than the other two, not the same way.
    None of the three route to a chapter by number regardless, so the distinction changes
    nothing about the fix: the
    id is the only key `displayChapterRules.action` accepts, so re-resolving it every run
    -- rather than deriving a URL from the chapter number, which OARD gives this corpus no
    way to do -- is the fix: a stale id is refreshed, not carried.

    Every row whose chapter is in `id_map` gets its url set to what that map says today,
    UNCONDITIONALLY -- cheap, since `id_map` is one dict already held in memory and this
    touches no network. A chapter absent from `id_map` (624 is the live instance: not in
    OARD's dropdown, so it never held a `selectedChapter` url and there is nothing here to
    re-resolve it against) is left exactly as it is, same as `ChapterNotListed` already
    treats it elsewhere in this module. Returns how many rows' `url` actually changed, so a
    caller can report it rather than silently rewrite all 169 mapped rows to say the same
    thing (170 catalogued chapters, minus 624, the one `id_map` never carries)."""
    changed = 0
    for c in cat.get("chapters", []):
        chapter_id = id_map.get(c["chapter"])
        if chapter_id is None:
            continue
        new_url = f"{OARD_BASE}/displayChapterRules.action?selectedChapter={chapter_id}"
        if c.get("url") != new_url:
            changed += 1
        c["url"] = new_url
    return changed


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
            # BUILT FROM THE CONSTANT, NOT RETYPED (#334). This line used to spell the mark
            # out as its own literal ("division no longer listed on OARD — verify
            # upstream"), which is exactly the discipline the comment above HISTORY_MARK
            # states and this line broke: a reader (history_count(), below) that imports
            # VANISHED_DIVISION_MARK stops finding what this line writes the moment either
            # copy is reworded without the other. Verified live before this fix: rewording
            # only this literal (`sed -i 's/division no longer listed on OARD/division is
            # no longer listed by OARD/'`) left `--selftest` printing OK, because nothing in
            # it ever called this line -- see the selftest fixture below, which now does.
            #
            # APPEND, NEVER `setdefault` (#334 code review, closing the SAME BUG the
            # rule-level carry-forward above was fixed for, live, at #270's own follow-up:
            # `setdefault` only ever WRITES when `note` is absent, so a division that
            # vanishes while already carrying a note -- from an earlier CLAIMED_ELSEWHERE_
            # DIVISION_MARK/CONFIRMED_EMPTY_DIVISION_MARK pass, or any other writer -- would
            # keep that note UNCHANGED and never gain VANISHED_DIVISION_MARK, invisible to
            # history_count() exactly the way 813-005-0020's rule-level row was before #270's
            # follow-up. No division in the catalog committed at this ticket's own HEAD hits
            # this today (measured 2026-08-29: every division holding both rules and a note
            # already carries the mark), so the old code never failed a real run -- but the
            # selftest fixture below exercised only the note-less branch, which is exactly
            # the shape this review was asked to hunt: a proof silent on the case where its
            # own docstring's claim would be false.
            existing_note = d.get("note")
            if not existing_note:
                d["note"] = f"division {VANISHED_DIVISION_MARK} — verify upstream"
            elif VANISHED_DIVISION_MARK not in existing_note:
                d["note"] = f"{existing_note} (division {VANISHED_DIVISION_MARK} — verify upstream)"
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


# --------------------------------------------------------------------- the row's own shape
#
# THE OAR CATALOG ROW HAS TWELVE KEYS, FOUR WRITERS, AND UNTIL NOW NO DECLARED SHAPE (#334).
# `agencies.yml` has `FIELDS` (`catalog_agencies.py`) -- a `declared-field` rule refusing an
# undeclared key on any row -- and this catalog, bigger and joined through by more modules
# (`ingest_oar.py`, `reingest_oar.py`, `legal_status.py`, `link_graph.py`,
# `stated_census.py`, `review_queue.py`...), had none of it.
#
# TWELVE, NOT TEN. #334's own measurement (an AI-drafted review) counted only the keys with
# a NONZERO row count in the committed catalog and named nothing else -- exactly the
# substitution AGENTS.md's overriding rule exists to catch ("a count that omits a category
# because it happened to be zero cannot be told apart from a count that was never asked").
# `reingest_oar.py` writes a SECOND both-or-neither pair, the same shape as
# `reingest_action`/`reingest_notice`: `reingest_refused`/`reingest_refused_notice`
# (`REFUSED_KEYS`, written together at reingest_oar.py's one write site, `candidate.row[...]
# = ...` beside it). Measured on the catalog committed at this ticket's own HEAD,
# 2026-08-29: 0 of 42,615 rows carry either key -- a real writer with a real write site and
# zero rows to show for it yet, not a field that does not exist. A `declared-field` rule
# built from the ten measured keys would refuse `reingest_oar.py`'s own legitimate write the
# day a text action is first refused, on a field that module has written since #245.
FieldSpec = namedtuple("FieldSpec", "writers required")

# THE FOUR WRITERS, named once so FIELDS below reads as a table rather than four repeated
# strings. `catalog_oar.py` (this module) is DISCOVERY: it is the only writer that can
# create a row at all (merge_divisions/discover_chapter), and the only writer of `number`.
DISCOVERY = "catalog_oar.py (discovery)"
INGEST = "ingest_oar.py"
REINGEST = "reingest_oar.py"
LEGAL = "legal_status.py"

FIELDS = {
    # THE ONLY TWO KEYS EVERY ROW CARRIES. `number` is set once, at discovery, and never
    # rewritten by anything downstream (merge_divisions carries it forward verbatim).
    "number": FieldSpec((DISCOVERY,), required=True),
    # `status` (CONTEXT.md, *Ingest status*) starts `not_ingested` at discovery and is then
    # the one field `ingest_oar.py` rewrites for every row it touches -- the six words are
    # `ingest_status.INGEST_STATUS_VALUES` (#333), imported above, not restated here.
    "status": FieldSpec((DISCOVERY, INGEST), required=True),
    # Where the document lives on disk. Required exactly when `status` says a document was
    # written -- see `path-matches-ingest-status` below, not a blanket `required` here,
    # because "required" on this table means "on every row", which `path` is not.
    "path": FieldSpec((INGEST,), required=False),
    # Free text. BOTH writers append to it (`merge_divisions`'s HISTORY_MARK/
    # VANISHED_DIVISION_MARK/etc., above -- `ingest_oar.py`'s per-outcome sentences) and
    # neither ever owns the whole field the way `curator_note` is CURATED in agencies.yml --
    # there is no curator-authored counterpart here to split it from.
    #
    # A FACT A READER PARSES OUT OF THIS PROSE BY SUBSTRING IS A FIELD WEARING A SENTENCE
    # (#334's own question, asked of this exact field). Two of the four marks above
    # (HISTORY_MARK, VANISHED_DIVISION_MARK) are read that way by THIS module and stay that
    # way deliberately -- they mark a division/rule-level FACT ABOUT THE MERGE
    # (`merge_divisions` docstring: "the mark is a fact, the note text is prose") that has no
    # structured key of its own to move into, and the write site now builds its text FROM
    # the constant a reader imports (the fix above), so the two cannot drift apart silently.
    # A THIRD case was live and is now fixed: `link_graph.py`'s `build_renumber_map()` used
    # to fall back to `note.split("OARD serves ")[-1]` for a renumbered rule's served
    # number -- parsing, by substring, a fact `served_as` (below) ALREADY carries
    # structurally. That fallback is gone; `served-as-tracks-renumbered` below is what makes
    # it provably unreachable rather than merely unlikely.
    "note": FieldSpec((DISCOVERY, INGEST), required=False),
    # THE NUMBER OARD NOW SERVES THIS ONE UNDER. Present exactly when `status` is
    # `renumbered` -- `served-as-tracks-renumbered` below, not `required` here for the same
    # reason `path` is not: "required" means every row, and most rows are never renumbered.
    "served_as": FieldSpec((INGEST,), required=False),
    "reingest_action": FieldSpec((REINGEST,), required=False),
    "reingest_notice": FieldSpec((REINGEST,), required=False),
    "reingest_refused": FieldSpec((REINGEST,), required=False),
    "reingest_refused_notice": FieldSpec((REINGEST,), required=False),
    "legal_status": FieldSpec((LEGAL,), required=False),
    "legal_status_action": FieldSpec((LEGAL,), required=False),
    "legal_status_notice": FieldSpec((LEGAL,), required=False),
}

# THREE BOTH-OR-NEITHER GROUPS, DECLARED RATHER THAN INFERRED (#334). A row may hold every
# key in a group or none of them; holding some is one writer's record left half-written.
#
# The `legal_status` trio is ALSO gated, more strictly, by `legal_status.py`'s own
# `legal-status-cites-its-notice` (it additionally checks the action is a real FORCE_ACTIONS
# member and that the status agrees with what that action derives) -- declaring it here too
# is this module stating its OWN row's shape rather than trusting a fact about it that lives
# in a different module's file, the same reason `agencies.yml`'s FIELDS states requiredness
# for keys other modules also write.
PAIRS = (
    ("legal_status", "legal_status_action", "legal_status_notice"),
    ("reingest_action", "reingest_notice"),
    ("reingest_refused", "reingest_refused_notice"),
)

# EVERY RULE THIS SECTION CAN REPORT (#319/#334). Declared rather than counted at run time,
# gated in both directions against this module's own syntax tree by `check_rule_ledger.py` --
# the shared implementation `legal_status.py`, `stated_census.py` and `catalog_agencies.py`
# already carry, adopted here rather than a sixth hand-rolled copy of it (this module carried
# NONE of the pattern before #334).
CHECK_RULES = (
    "readable-catalog", "catalog-populated", "readable-row",
    "declared-field", "required-field", "field-group-complete",
    "served-as-tracks-renumbered", "path-matches-ingest-status",
)

_LEDGER = RuleLedger(CHECK_RULES, __file__)


class Failure(_LEDGER.Failure):
    """One rule, the row it is about, and what is wrong with it -- recorded on construction
    by the shared ledger, matching `legal_status.Failure`, `stated_census.Failure` and
    `catalog_agencies.Failure`."""
    __slots__ = ()

    def __str__(self):
        return f"  FAIL [{self.rule}] {self.site}: {self.detail}"


def _all_rows(cat: dict):
    """Every rule row, flat -- the one traversal every check below shares, matching
    `legal_status.catalog_rules()`'s role for this module."""
    for c in cat.get("chapters") or []:
        for d in c.get("divisions") or []:
            yield from (d.get("rules") or [])


# STATUSES THAT MEAN "NOTHING WAS FETCHED UNDER THIS NUMBER" -- a `path` on one of these is
# not a typo, it is this row asserting a document exists that its own `status` says does
# not. `ingested` is the opposite claim (a document WAS written) and is the only status
# `path-matches-ingest-status` requires the key for; `renumbered` is neither -- see the
# module-level `renumbered_without_path()` below for why it is not gated as a third case.
#
# DERIVED FROM `INGEST_STATUS_VALUES`, NOT HAND-TYPED (#334 code review). The six-word
# vocabulary has exactly two statuses that assert a document WAS fetched -- handled above --
# and every other declared status means nothing was, `not_ingested` included: it is the
# status every row is born with at discovery, before `ingest_oar.py` has touched it, and a
# `path` present alongside it is exactly as impossible a claim as a `path` alongside
# `not_served`. Hand-listing the "nothing fetched" three rather than deriving them as
# everything-but-`ingested`-and-`renumbered` is the identical drift shape #333 fixed one
# section up (`RULE_STATUSES` vs. `INGEST_STATUS_VALUES`) -- and it had already reopened:
# `not_ingested` was left off this tuple, so a `not_ingested` row carrying a `path` passed
# `path-matches-ingest-status` silently. Verified live before this fix: a `not_ingested` row
# with a `path` attached, run through `check_row_shape`, produced zero failures.
_FETCHED_STATUSES = ("ingested", "renumbered")
_NOTHING_FETCHED_STATUSES = tuple(s for s in INGEST_STATUS_VALUES if s not in _FETCHED_STATUSES)


def check_row_shape(cat: dict, fields=FIELDS, pairs=PAIRS) -> list:
    """Every contract violation in the catalog's OWN row shape: undeclared keys, missing
    required keys, a both-or-neither group holding some but not all of its keys, and the two
    status-derived pairings (`served_as` <-> `status: renumbered`, `path` <-> whether
    anything was fetched). Pure function of `cat` -- no network, no disk beyond `cat`
    itself -- so `--selftest` can fire every rule against a synthetic fixture."""
    failures = []
    for i, r in enumerate(_all_rows(cat)):
        if not isinstance(r, dict):
            # `readable-row` (#334 code review, matching `catalog_agencies.py`'s rule of
            # the same name): a rule row that is not a mapping -- a bare string in the YAML
            # where a `{number: ..., status: ...}` block belongs -- crashed every check
            # below with an unhandled AttributeError instead of a named failure. CI still
            # goes red on the traceback, so this was never a SILENT pass; it is a coverage
            # gap in what the gate can name, closed the same way the sibling module already
            # closed it for its own rows.
            failures.append(Failure(
                "readable-row", f"<row {i}>",
                "not a mapping, so no rule below could be evaluated against it"))
            continue
        num = str(r.get("number", "<no number>"))
        for key in r:
            if key not in fields:
                failures.append(Failure(
                    "declared-field", num,
                    f"field {key!r} is not declared in FIELDS -- if a writer produces it, "
                    "declare it"))
        for key, field in fields.items():
            if field.required and key not in r:
                failures.append(Failure(
                    "required-field", num,
                    f"required field {key!r} is absent (null is a value; absent is not)"))
        for group in pairs:
            present = [k for k in group if r.get(k) is not None]
            if present and len(present) != len(group):
                failures.append(Failure(
                    "field-group-complete", num,
                    f"holds {', '.join(present)} and not "
                    f"{', '.join(k for k in group if k not in present)} -- these keys are "
                    "one writer's record and arrive together or not at all"))
        status, served = r.get("status"), r.get("served_as")
        if served is not None and status != "renumbered":
            failures.append(Failure(
                "served-as-tracks-renumbered", num,
                f"carries served_as={served!r} with status={status!r} -- served_as means "
                "OARD now serves this number under a different one, which is what "
                "status: renumbered says; a row cannot say both that it moved and that it "
                "did not"))
        elif status == "renumbered" and served is None:
            failures.append(Failure(
                "served-as-tracks-renumbered", num,
                "status is renumbered and served_as is absent -- ingest_oar.py's one "
                "renumbered write site sets both together, so a renumbered row with no "
                "served_as is one nothing here can resolve the renumber through"))
        path = r.get("path")
        if status == "ingested" and path is None:
            failures.append(Failure(
                "path-matches-ingest-status", num,
                "status is ingested and path is absent -- ingested means a document was "
                "written to disk, and path is where"))
        elif status in _NOTHING_FETCHED_STATUSES and path is not None:
            failures.append(Failure(
                "path-matches-ingest-status", num,
                f"status is {status!r} and path={path!r} is present -- {status!r} means "
                "nothing was fetched under this number, so a path here names a document "
                "this row's own status says does not exist"))
    return failures


def renumbered_without_path(cat: dict, root: Path = REPO_ROOT) -> list:
    """Renumbered rows whose `path` is absent even though the document their `served_as`
    names is real and on disk -- REPORTED, not gated (#334, filed as #338).

    NOT a `path-matches-ingest-status` failure: that rule catches a row LYING about a
    document (claiming one that does not exist, or omitting one that does not exist to
    claim); this is a row SILENT about a document that DOES exist, which is a different
    failure and this repository's overriding rule treats the two directions alike --
    could-not-check is never is-not-there, and is-not-there is never could-not-check either.

    THE DISK CLAIM IS MEASURED, NOT ASSUMED (#334 code review). This used to be a pure
    status filter -- `status == "renumbered" and not path` -- with no reference to `served_as`
    or to disk at all, so the sentence this prints ("despite naming a served_as target OARD
    serves") was true only by luck of what `ingest_oar.py`'s control flow happens to do
    today, and the selftest fixture proving it only ever built a row whose served_as target
    was ABSENT from disk -- the one case this function's own contract says should NOT be
    reported. `oar_rule_path()` (`repo_lib.py`, the same definition `ingest_oar.py`'s
    renumbered-write site now uses) is what turns "renumbered and pathless" into "renumbered,
    pathless, AND the target is really there" -- a row that is pathless because nothing was
    ever fetched (a `not_served`/`not_sliceable` sibling, or a renumber whose target was never
    ingested either) is correctly excluded rather than folded into this bucket by name alone.

    THE PROVEN CAUSE (#334, reproduced against the catalog committed at this ticket's own
    HEAD, 2026-08-29): `ingest_oar.py`'s `out.exists()` branch sets `r["path"]` only when
    `served == num` (the rule was not renumbered); when `served != num` and the SERVED
    target's file already exists, the loop `continue`s with `path` never stamped on THIS
    row, even though the document it points at via `served_as` is real. Measured: exactly 3
    rows, all chapter 125 division 800 (125-800-0005/0010/0020, served_as 128-030-000{5,10,
    20}) -- and `rules/128/030/oar-128-030-000{5,10,20}.md` all exist on disk. Fixing the
    write site is `ingest_oar.py`'s to do, not this module's (out of scope for #334's own
    acceptance criteria, which are about the row's declared SHAPE); reported here, by name,
    every `--check` run, rather than silently narrowing FIELDS' contract to paper over it."""
    return [r for r in _all_rows(cat)
            if r.get("status") == "renumbered" and not r.get("path")
            and r.get("served_as") and oar_rule_path(r["served_as"], root).exists()]


def cmd_check(catalog_path=None) -> int:
    """Report every contract violation in the committed catalog's row shape. Exit 1 if any.

    `catalog_path` is a PARAMETER, defaulting to `CATALOG`, so --selftest can point this at
    a path that does not exist, does not parse, or parses to no chapters and watch
    `readable-catalog`/`catalog-populated` fire through the real command line, matching
    `catalog_agencies.cmd_check()`'s own reason for the same parameter."""
    catalog_path = CATALOG if catalog_path is None else catalog_path
    if not catalog_path.exists():
        print(Failure("readable-catalog", str(catalog_path), "no catalog to check"),
              file=sys.stderr)
        return 1
    try:
        cat = yaml.safe_load(catalog_path.read_text())
    except yaml.YAMLError as e:
        # A CATALOG THAT DOES NOT PARSE IS UNREADABLE, THE SAME AS ONE THAT DOES NOT EXIST
        # (#334 code review) -- both are `readable-catalog`, not two different rules, because
        # both leave this function with no `cat` to check anything else against. Before this,
        # a parse error escaped as a raw YAMLError traceback rather than a named failure; CI
        # still went red either way, so this was a naming gap, not a silent pass.
        print(Failure("readable-catalog", str(catalog_path), f"does not parse: {e}"),
              file=sys.stderr)
        return 1
    if not cat or not cat.get("chapters"):
        print(Failure("catalog-populated", str(catalog_path), "catalog holds no chapters"),
              file=sys.stderr)
        return 1
    failures = check_row_shape(cat)
    for f in failures:
        print(f, file=sys.stderr)
    total = sum(1 for _ in _all_rows(cat))
    if failures:
        print(f"\n{len(failures)} contract violation(s) across {total} row(s)",
              file=sys.stderr)
        return 1
    print(f"{total:,} row(s) against {len(FIELDS)} declared fields, {len(PAIRS)} "
          "both-or-neither group(s) -- every one intact")
    # NAME THE ZEROES (catalog_agencies.tally's own rule, restated here): a bucket printed
    # only when it holds something looks identical to a bucket nobody thought to report.
    gap = renumbered_without_path(cat)
    named = ", ".join(r["number"] for r in gap) if gap else "none"
    print(f"{len(gap)} renumbered row(s) lack a path despite naming a served_as target "
          f"OARD serves (#338, reported not gated -- see renumbered_without_path()): "
          f"{named}")
    return 0


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
        # `url` is set here ONLY because this row does not exist yet for
        # `refresh_chapter_urls` (#280) to have already reached in cmd_discover's pass
        # over `cat["chapters"]`, which runs before this loop. An EXISTING row's `url` is
        # not touched here at all -- that pass already set it from this same id_map, and
        # writing it twice from the same formula in the same run is not a second writer
        # so much as an invitation for the two to be read as independent someday. One
        # writer for a row that already exists; this is only the one-time exception for a
        # row that, until this line, did not.
        existing = {"chapter": ch, "title": title,
                    "url": f"{OARD_BASE}/displayChapterRules.action?selectedChapter={chapter_id}",
                    "divisions": []}
        cat["chapters"].append(existing)
    existing["title"] = title
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
    field, and the two still hold identical bytes on 187 of the 190 committed rows (#279,
    re-measured for #281) — five rows have an established statutory name (#168) and only
    three of those differ from the OAR title — so the change is all but invisible in the
    data and visible in the fault-injected fixture below.

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


def run_discovery(chapters: list, cat: dict, id_map: dict, only: list,
                   discover_fn=discover_chapter) -> dict:
    """The assembled body of a --discover run, once `chapters` and `id_map` are already
    resolved: the #280 url-refresh call plus the per-chapter loop, EXTRACTED from
    `cmd_discover` (#280 follow-up) so the wiring between them is something a selftest can
    reach without network, not only the four `refresh_chapter_urls()` calls a selftest
    already made in isolation.

    That distinction is not decorative. Sabotage-tested against this repo's own working
    tree: deleting `n_urls_changed = refresh_chapter_urls(cat, id_map)` from what was then
    inline in `cmd_discover` left `--selftest` printing OK, because every #280 check
    called `refresh_chapter_urls()` directly -- proving the helper works, never that
    `cmd_discover` actually calls it. `cmd_discover` now HAS no code path of its own that
    could drop this call silently: it delegates the whole assembly here, so a selftest
    against `run_discovery` is a selftest against what a real run executes, not a
    parallel reimplementation of it that could drift from the real one the way the four
    isolated checks did.

    `discover_fn` is injectable so a caller can drive the loop without touching the
    network at all, by supplying `chapters`/`cat` that route every chapter through the
    already-discovered skip below (real `--discover` runs always pass the default,
    `discover_chapter`). Returns a dict of the totals `cmd_discover` prints."""
    # RE-RESOLVED EVERY RUN, EVEN FOR A CHAPTER THIS RUN OTHERWISE SKIPS OR DOES NOT
    # TARGET (#280): `id_map` is a fetch of OARD's WHOLE dropdown regardless of `only`, so
    # applying it to every catalogued row costs no extra network call and closes the gap
    # the already-discovered skip below left open -- a chapter's `url` used to go stale
    # the moment nobody happened to re-walk its rules page.
    n_urls_changed = refresh_chapter_urls(cat, id_map)

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
            nd, nda, nr, nn, nc = discover_fn(ch, title, id_map[ch], cat)
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
    return {
        "n_urls_changed": n_urls_changed, "total_d": total_d, "total_da": total_da,
        "total_r": total_r, "total_new": total_new, "total_claimed": total_claimed,
        "skipped": skipped, "found_nothing": found_nothing, "not_listed": not_listed,
        "failed": failed,
    }


def cmd_discover(only: list):
    reg = yaml.safe_load(REGISTRY.read_text())
    chapters = registry_chapters(reg)
    if only:
        chapters = [c for c in chapters if c[0] in only]
    cat = load_catalog()

    id_map = chapter_id_map(get(CHAPTER_LIST_URL))
    time.sleep(0.2)

    stats = run_discovery(chapters, cat, id_map, only)
    n_urls_changed = stats["n_urls_changed"]
    total_d, total_da, total_r, total_new, total_claimed, skipped = (
        stats["total_d"], stats["total_da"], stats["total_r"], stats["total_new"],
        stats["total_claimed"], stats["skipped"])
    found_nothing, not_listed, failed = (
        stats["found_nothing"], stats["not_listed"], stats["failed"])

    save_catalog(cat, stamp_retrieved=total_d > 0)
    print(f"\ndiscovered: {total_d} divisions ({total_da} new to the catalog), {total_r} "
          f"rules ({total_new} new added to the catalog); {skipped} chapters already "
          f"discovered (use --redo to refresh)")
    # #280: every catalogued chapter's `url` is re-resolved against this run's own id_map
    # above, whether or not the chapter itself was walked this run -- this is that check's
    # own report, so a moved id is visible in stdout and not just in the diff.
    print(f"{n_urls_changed} chapter url(s) re-resolved to a different OARD id than the "
          f"catalog held (0 means every id_map entry still matches; #280)")
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


# The per-rule `status` vocabulary this catalog declares (CONTEXT.md's "Ingest status") is
# NOT DECLARED HERE (#333, closing #297): `ingest_status.INGEST_STATUS_VALUES` is the one
# declaration, gated against what `ingest_oar.py` and this module actually write
# (`ingest_status.py --check`), and this used to be a second, narrower copy of it --
# `ingested`, `not_ingested`, `renumbered`, `not_served` only, four of the six words the
# pipeline writes, missing `not_sliceable` and `needs_registry` (ingest_oar.py writes both).
# A rule is awaiting import when its status SAYS so, never when it merely fails to say
# `ingested` -- #282 found `--summary`'s "to import" computed as `total - ingested`, which
# counted `renumbered` and `not_served` rows (recorded WITH A REASON precisely because they
# will never be imported) as outstanding work, overcounting by 533 on the catalog measured
# 2026-08-28. Counting below is done directly against the full six-word allowlist rather
# than by subtraction, and anything the allowlist does not name is surfaced by its own name
# instead of being folded into either bucket.


def status_counts(cat):
    """Tally every catalogued rule number by its own `status`, counting the thing each
    bucket names rather than deriving one bucket from a total. Returns a dict keyed by
    every value in `INGEST_STATUS_VALUES`, plus `total` (every rule row seen) and `other`
    (a Counter of any status outside that vocabulary -- empty on a catalog that matches
    CONTEXT.md's declared vocabulary, which today's committed catalog does)."""
    counts = {s: 0 for s in INGEST_STATUS_VALUES}
    other = Counter()
    total = 0
    for c in cat["chapters"]:
        for d in c["divisions"]:
            for r in d.get("rules") or []:
                total += 1
                st = r.get("status")
                if st in counts:
                    counts[st] += 1
                else:
                    other[st] += 1
    counts["total"] = total
    counts["other"] = other
    return counts


def summary_total_line(n_chapters, counts):
    """THE ACTUAL PRINTED STRING for `--summary`'s TOTAL line, factored out of
    `cmd_summary` so `--selftest` can assert on the printer itself rather than only on
    `status_counts()` feeding it. #282's own review found the gap this closes: every new
    selftest check exercised `status_counts`, and nothing exercised this line -- reverting
    ONLY this f-string to the pre-#282 arithmetic (`total - ingested`) left `--selftest`
    green while `--summary` printed the exact #282 bug again, verbatim. This function is
    now the thing under test, not a copy of it.

    NAMES ALL SIX WORDS, not the four `RULE_STATUSES` used to name before #333. A
    `not_sliceable` or `needs_registry` row is counted into `status_counts()`'s dict by
    that ticket, which is exactly what makes it stop being an `other` row -- and a row this
    line does not also print BY NAME has been counted somewhere with no visible trace of
    it, a strictly worse version of the #282/#297 failure this ticket exists to end (found
    by code review of #333, over a fixture carrying one row of each: both counted, neither
    printed here nor in `summary_other_line`, which only reports `other`)."""
    return (f"TOTAL: {n_chapters} chapters, {counts['total']} rules, "
            f"{counts['ingested']} ingested, {counts['not_ingested']} to import "
            f"-- {counts['renumbered']} renumbered, {counts['not_served']} not served, "
            f"{counts['not_sliceable']} not sliceable and {counts['needs_registry']} "
            f"needing registry work, every one recorded with a reason and never counted "
            f"as pending (#282, #333)")


def summary_other_line(counts):
    """THE ACTUAL PRINTED STRING for `--summary`'s `other` line. Always printed, never
    only `if counts["other"]` -- catalog_agencies.py's `tally()` names this rule
    ("NAME THE ZEROES") for exactly this reason: a bucket silently skipped when it holds
    zero looks identical to a bucket nobody thought to report. Names the declared
    vocabulary as a plain list rather than interpolating `INGEST_STATUS_VALUES` (a raw
    tuple repr, `('ingested', 'not_ingested', ...)`, is not something a human reader asked
    for)."""
    vocab = ", ".join(INGEST_STATUS_VALUES)
    other_total = sum(counts["other"].values())
    if not other_total:
        return f"0 rule(s) carry a status outside the declared vocabulary ({vocab})"
    named = ", ".join(f"{n} {s!r}" for s, n in sorted(counts["other"].items(), key=str))
    return (f"{other_total} rule(s) carry a status outside the declared vocabulary "
            f"({vocab}) ({named}) -- reported rather than guessed, and not counted as "
            f"pending")


def cmd_summary():
    cat = load_catalog()
    rows = []
    for c in sorted(cat["chapters"], key=lambda c: (len(c["chapter"]), c["chapter"])):
        n = sum(len(d.get("rules") or []) for d in c["divisions"])
        ing = sum(1 for d in c["divisions"] for r in d.get("rules") or []
                  if r.get("status") == "ingested")
        rows.append((c["chapter"], c["title"], len(c["divisions"]), n, ing))
    for ch, title, nd, n, ing in rows:
        print(f"{ch:>4}  {nd:3d} div  {n:5d} rules  {ing:5d} ingested  {title[:55]}")
    counts = status_counts(cat)
    print(f"\n{summary_total_line(len(rows), counts)}")
    print(summary_other_line(counts))


# ------------------------------------------------------------------------------ selftest
#
# THE PROOF THAT DISCOVERY IS KEYED ON THE OAR NAME. The fixture's two names differ, which
# 187 of the 190 committed registry rows do not (#279, re-measured for #281): `name` and
# `oar_name` hold the same bytes on every row whose statutory name is unestablished AND on
# the established rows whose statute agrees with the rules index (#168), so a fixture built
# from committed data would pass whichever field this code reads on all but three rows.
# Synthetic: no network, no read of the committed registry or catalog.


def _fixture_registry():
    """A registry in the state ADR 0003 leaves it in — `name` promoted to the statutory
    name, `oar_name` still the rules index's chapter title — plus one body holding no
    chapter, because 20 rows hold none and discovery must not walk them (#279,
    re-measured for #281)."""
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

    # THE URL FIELD IS RE-RESOLVED AGAINST id_map EVERY RUN, DECOUPLED FROM THE
    # ALREADY-DISCOVERED SKIP (#280). cmd_discover's "skip a chapter already discovered"
    # check exists so a routine run does not re-fetch and re-parse every chapter's own
    # rules page -- it was never about the id map, which chapter_id_map() already
    # re-resolves fresh on every invocation regardless. Before this fix that fresh map sat
    # in memory two lines above the skip and was simply never applied to a skipped row's
    # `url`, which is why 169 chapters could carry a `selectedChapter` id from whatever run
    # last walked them, however long ago, while the module's own docstring says the id "is
    # OARD's own bookkeeping and may move". Measured live 2026-08-28 that OARD has no
    # chapter-NUMBER-keyed route to fall back on instead: treating chapter 125's own
    # NUMBER as if it belonged in the id slot -- `displayChapterRules.action
    # ?selectedChapter=125` -- actually serves chapter 661, because 125 is what OARD's
    # dropdown assigns as the ID of a wholly different chapter, not what it accepts as a
    # chapter number. `?chapterNumber=125` and `?selectedChapterNumber=125` are silently
    # ignored, producing the identical error page a request with no parameter at all does;
    # `?chapter=125` is ALSO ignored but produces a different, shorter page that drops that
    # page's explicit error message rather than reproducing it (measured 2026-08-28: 5,505
    # vs 5,320 bytes) -- quieter, not identical, and beside the point either way, since none
    # of the three route by chapter number. So the id is the only key OARD accepts, and this
    # catalog's answer is to keep
    # RE-RESOLVING it every run rather than pretend a stored one can be trusted between runs.
    stale_cat = {"chapters": [
        {"chapter": "125", "title": "Department of Administrative Services",
         "url": f"{OARD_BASE}/displayChapterRules.action?selectedChapter=31",
         "divisions": []},
        {"chapter": "624", "title": "Oregon Alfalfa Seed Commission",
         "url": f"{OARD_BASE}/ruleSearch.action", "divisions": []},
    ]}
    moved_id_map = {"125": "999"}  # OARD renumbered chapter 125's own bookkeeping id
    n_changed = refresh_chapter_urls(stale_cat, moved_id_map)
    ch125 = next(c for c in stale_cat["chapters"] if c["chapter"] == "125")
    ch624 = next(c for c in stale_cat["chapters"] if c["chapter"] == "624")
    check("a skipped chapter's stale url is re-resolved against a moved id",
          ch125["url"] == f"{OARD_BASE}/displayChapterRules.action?selectedChapter=999")
    check("refresh_chapter_urls reports exactly the row(s) that changed", n_changed == 1)
    check("a chapter absent from the id map (624 -- not in OARD's dropdown) is left alone",
          ch624["url"] == f"{OARD_BASE}/ruleSearch.action")
    check("re-running against an id map that has not moved changes and reports nothing",
          refresh_chapter_urls(stale_cat, moved_id_map) == 0)

    # THE WIRING, NOT JUST THE HELPER (#280 follow-up). Every check above calls
    # `refresh_chapter_urls()` directly, which proves the helper is correct and proves
    # nothing about whether `cmd_discover` still calls it -- sabotaged and confirmed
    # against this working tree: deleting that one line from what was then inline in
    # `cmd_discover` left every check above green and `--selftest` printing OK. This
    # drives `run_discovery` -- the function `cmd_discover` now delegates its whole
    # assembly to, verbatim -- through the already-discovered skip path (no `discover_fn`
    # call, so no network) and checks the SAME fact the isolated checks above check, but
    # reached through the real call path instead of a second one built to match it.
    wiring_cat = {"chapters": [
        {"chapter": "125", "title": "Department of Administrative Services",
         "url": f"{OARD_BASE}/displayChapterRules.action?selectedChapter=31",
         "divisions": [], "discovered": "2026-01-01"},
    ]}
    wiring_id_map = {"125": "999"}  # OARD renumbered chapter 125's id since 2026-01-01

    def _discover_fn_must_not_be_called(*a, **kw):
        raise AssertionError(
            "discover_fn was called for an already-discovered chapter -- the skip path "
            "this fixture depends on to prove no network is needed did not fire")

    wiring_stats = run_discovery(
        [("125", "Department of Administrative Services")], wiring_cat, wiring_id_map,
        only=[], discover_fn=_discover_fn_must_not_be_called)
    check("run_discovery skipped the already-discovered chapter (no network touched)",
          wiring_stats["skipped"] == 1)
    check("run_discovery's own call to refresh_chapter_urls reached an already-discovered "
          "chapter's url -- the exact wiring a deleted call site would leave undetected",
          wiring_cat["chapters"][0]["url"] ==
          f"{OARD_BASE}/displayChapterRules.action?selectedChapter=999")
    check("...and run_discovery reports it in the same total cmd_discover prints",
          wiring_stats["n_urls_changed"] == 1)

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
    #
    # THE VANISHED-DIVISION HALF IS PRODUCED BY THE REAL WRITER, NOT HAND-TYPED (#334). This
    # used to read `"note": VANISHED_DIVISION_MARK + " — verify upstream"` -- a note built
    # FROM THE CONSTANT, same as the reader below, and so proven only against itself: the
    # write site at the bottom of merge_divisions() (the `d.setdefault("note", ...)` line)
    # was never called by this fixture at all, so a reword THERE could not be caught here.
    # Verified live before this fix: `sed`-rewording only that write site's literal left
    # this exact fixture, and every check against it, printing OK -- calling merge_divisions
    # itself is what closes the gap between what the reader is proven against and what the
    # writer actually emits.
    vanish_old = [{"division": "9", "title": "T", "status": "ingested",
                   "rules": [{"number": "813-009-0000", "status": "ingested"},
                             {"number": "813-009-0010", "status": "ingested"}]}]
    # OARD's current listing no longer names division 9 AT ALL -- the whole-division
    # carry-forward path at the bottom of merge_divisions, not the per-rule one above.
    vanish_merged, _ = merge_divisions(vanish_old, [])
    vanished_division = next(d for d in vanish_merged if d["division"] == "9")
    check("a division OARD's current listing no longer names carries the vanished-division "
          "mark WRITTEN BY merge_divisions ITSELF, not hand-typed by this fixture",
          VANISHED_DIVISION_MARK in (vanished_division.get("note") or ""))

    # THE `setdefault`-VS-APPEND CASE (#334 code review), same shape as the rule-level
    # 813-005-0020 case the comment above HISTORY_MARK's write site documents: a division
    # that ALREADY carries a note gets the mark APPENDED, never silently skipped because
    # `note` was non-empty. Not reachable against the catalog committed at this ticket's
    # own HEAD (measured 2026-08-29), which is exactly why this fixture has to build the
    # case rather than pull it from the corpus.
    vanish_old_noted = [{"division": "10", "title": "T", "status": "ingested",
                         "note": "an earlier writer's note, not about vanishing at all",
                         "rules": [{"number": "813-010-0000", "status": "ingested"}]}]
    vanish_merged_noted, _ = merge_divisions(vanish_old_noted, [])
    vanished_division_noted = next(d for d in vanish_merged_noted if d["division"] == "10")
    noted = vanished_division_noted.get("note") or ""
    check("a division that already carried a note before vanishing keeps that note AND "
          "gains the vanished-division mark -- proven by breaking it back to `setdefault`, "
          "which drops this to only the pre-existing note and no mark",
          "an earlier writer's note" in noted and VANISHED_DIVISION_MARK in noted)

    history_cat = {"chapters": [
        {"chapter": "813", "divisions": [
            {"division": "1", "rules": [
                {"number": "813-001-0003", "note": HISTORY_MARK + " -- history, kept"},
                {"number": "813-001-0002"}]},
            vanished_division]}]}
    check("history_count finds a per-rule carried-forward row AND a vanished division whose "
          "mark came from the real writer above, not a fixture literal",
          history_count(history_cat) == 3)  # 1 per-rule + 2 in the vanished division

    # #282: "to import" MUST count rows whose status SAYS they await import, never rows
    # left over after subtracting `ingested` from a total drawn from a wider vocabulary.
    # One row of every declared status -- the SIX `ingest_status.INGEST_STATUS_VALUES`
    # words, not the four `RULE_STATUSES` used to name (#333, closing #297: `not_sliceable`
    # and `needs_registry` are now declared, so both must be counted BY NAME below and land
    # in neither `not_ingested` nor `other`) -- plus one genuinely undeclared word
    # (`quarantined`), which must still be the only thing `other` reports.
    #
    # `quarantined` is assigned through a variable, not a `"status": "quarantined"` literal
    # -- `ingest_status.ingest_vocabulary()` scans this module's OWN source file for the
    # words the real pipeline writes (`DISCOVERER = catalog_oar.py`, since #276), file-wide,
    # not scoped to any one function. A literal fixture word here would read to that scan
    # exactly like a real write site, which is the same narrowing `legal_status.py`'s own
    # scan documents ("a status held in a variable and assigned from somewhere else passes
    # it") -- watched firing once while writing this fixture: `ingest_status.py --check`
    # failed against the real ingest_oar.py/catalog_oar.py the moment this word was a bare
    # string literal here, over a corpus this test never touches.
    _undeclared_test_word = "quarantined"
    # THE SAME NARROWING, APPLIED TO EVERY DECLARED WORD TOO -- not only the undeclared
    # one. Found by code review of #333: with `needs_registry` written as a bare
    # `"status": "needs_registry"` literal below, `ingest_status.ingest_vocabulary()`'s
    # file-wide scan of `catalog_oar.py` (`DISCOVERER`) reads this SELFTEST FIXTURE as a
    # live write site indistinguishable from a real one -- retiring `ingest_oar.py`'s
    # only actual `needs_registry` write site left `ingest_status.py --check` green,
    # because this fixture alone kept the word looking written. Demonstrated: with the
    # literal in place, changing `ingest_oar.py`'s one real `needs_registry` write to
    # write an already-declared word instead still reported "6 ingest-status word(s)
    # declared, matching what ... write" (rc=0) -- a retired write site invisible to the
    # gate meant to catch exactly that. Every declared word below is therefore assigned
    # through its own variable first, same as `_undeclared_test_word` above, so none of
    # them is a literal for the scan to find.
    _fixture_ingested = "ingested"
    _fixture_not_ingested = "not_ingested"
    _fixture_renumbered = "renumbered"
    _fixture_not_served = "not_served"
    _fixture_not_sliceable = "not_sliceable"
    _fixture_needs_registry = "needs_registry"
    status_cat = {"chapters": [{"chapter": "1", "title": "T", "divisions": [
        {"division": "1", "rules": [
            {"number": "1-001-0001", "status": _fixture_ingested},
            {"number": "1-001-0002", "status": _fixture_not_ingested},
            {"number": "1-001-0003", "status": _fixture_renumbered,
             "served_as": "1-001-0009"},
            {"number": "1-001-0004", "status": _fixture_not_served},
            {"number": "1-001-0005", "status": _fixture_not_sliceable},
            {"number": "1-001-0006", "status": _fixture_needs_registry},
            {"number": "1-001-0007", "status": _undeclared_test_word},
        ]}]}]}
    counts = status_counts(status_cat)
    check("every rule in the fixture is counted exactly once",
          counts["total"] == 7)
    # RED, WATCHED AGAINST THE ACTUAL PRE-#282 ARITHMETIC: `total - ingested` is literally
    # what `cmd_summary` printed as "to import" before that fix (git blame this file).
    # Reproduced inline, over this fixture, to prove the failure mode is real and not
    # asserted -- it counts renumbered, not_served, not_sliceable, needs_registry AND the
    # undeclared `quarantined` row as awaiting import, none of which will ever be.
    naive_to_import = counts["total"] - counts["ingested"]
    check("RED: the pre-#282 formula (total - ingested) overcounts by every row that is "
          "not literally 'ingested' -- 6 rows counted as pending, only 1 actually is",
          naive_to_import == 6)
    check("...while only the row whose status actually SAYS not_ingested is 1",
          counts["not_ingested"] == 1)
    check("GREEN: status_counts reports the correct 'to import' figure directly",
          counts["not_ingested"] == 1 and counts["not_ingested"] != naive_to_import)
    check("a renumbered row is never counted as awaiting import",
          counts["renumbered"] == 1)
    check("a not_served row is never counted as awaiting import",
          counts["not_served"] == 1)
    # #333's OWN FINDING, CAPTURED AS A PROOF: before this ticket these two rows fell into
    # `other` (the four-word `RULE_STATUSES` did not declare them) -- measured against the
    # real committed catalog to be zero rows either way (2026-08-29), but the BUCKET a row
    # with either word lands in changes here, which is exactly the drift #282 already hit
    # once for a different word.
    check("a not_sliceable row is now counted BY NAME, not folded into 'other'",
          counts["not_sliceable"] == 1)
    check("...and so is a needs_registry row",
          counts["needs_registry"] == 1)
    check("a status neither this module nor ingest_status.py declares (quarantined) is "
          "still reported by name in 'other', not folded into not_ingested or dropped",
          counts["other"] == {"quarantined": 1})

    # THE PRINTER ITSELF, not just status_counts() feeding it -- a code review of #282
    # found that every prior check above stopped at status_counts, so a regression back
    # to `total - ingested` inside summary_total_line would leave --selftest green while
    # --summary printed the bug again (reproduced: reverting only the f-string to
    # `{counts['total'] - counts['ingested']} to import` prints "6 to import" on this
    # fixture and every check above still PASSes, because none of them call this
    # function). Asserted against the exact naive figure so a reversion is caught here.
    total_line = summary_total_line(1, counts)
    naive_to_import = counts["total"] - counts["ingested"]
    check("summary_total_line prints the counted 'to import' figure (1), not the naive "
          "total-minus-ingested figure the naive formula over this fixture would print "
          f"({naive_to_import})",
          "1 to import" in total_line and f"{naive_to_import} to import" not in total_line)
    # FOUND BY CODE REVIEW OF #333: `not_sliceable` and `needs_registry` are counted into
    # `status_counts()`'s dict by this ticket, which is exactly what stops either row from
    # landing in `other` -- but nothing printed them BY NAME either, so both rows vanished
    # from `--summary` entirely, reachable nowhere in its output. The check this replaced
    # asserted the words appeared in `summary_other_line`'s output, which is true on ANY
    # fixture regardless of these rows' counts (that line always interpolates the full
    # vocabulary list) -- a proof that cannot fail is not a proof. Asserted here against
    # the actual per-word COUNT in the line that reports it now.
    check("summary_total_line names the not_sliceable row BY COUNT, not silently absorbed",
          "1 not sliceable" in total_line)
    check("...and the needs_registry row, the same way",
          "1 needing registry work" in total_line)

    other_line = summary_other_line(counts)
    check("summary_other_line names the quarantined row by value, not as a raw tuple "
          "repr of the declared vocabulary",
          "quarantined" in other_line and "('ingested'" not in other_line)
    check("...and the declared vocabulary it interpolates into that line is the full six "
          "words, not the four RULE_STATUSES used to declare before #333 (this is the "
          "vocabulary LIST always printed there, not a claim these two rows are counted "
          "in 'other' -- they are not; see summary_total_line above)",
          "not_sliceable" in other_line and "needs_registry" in other_line)

    # A catalog matching CONTEXT.md's declared vocabulary exactly (no undeclared rows, the
    # shape of the real committed catalog measured 2026-08-29) reports no `other`.
    clean_cat = {"chapters": [{"chapter": "1", "title": "T", "divisions": [
        {"division": "1", "rules": [{"number": "1-001-0001", "status": "ingested"}]}]}]}
    clean_counts = status_counts(clean_cat)
    check("a catalog holding only declared statuses reports an empty 'other'",
          not clean_counts["other"])
    # NAME THE ZEROES (catalog_agencies.tally's own rule): a zero 'other' bucket must
    # still be printed, not silently skipped -- a skipped zero looks identical to a
    # zero nobody thought to report.
    check("summary_other_line names the zero rather than printing nothing for it",
          summary_other_line(clean_counts) == "0 rule(s) carry a status outside the "
          "declared vocabulary (ingested, renumbered, not_ingested, not_served, "
          "not_sliceable, needs_registry)")

    # ------------------------------------------------------------ the row's own shape (#334)
    #
    # ONE ROW OF EVERY SHAPE, so every FIELDS key and every PAIRS group appears at least
    # once and the fixture is not vacuously clean.
    def _fixture_row_shape():
        return {"chapters": [{"chapter": "1", "title": "T", "divisions": [{
            "division": "1", "status": "ingested", "rules": [
                {"number": "1-001-0001", "status": "ingested",
                 "path": "rules/1/001/oar-1-001-0001.md"},
                {"number": "1-001-0002", "status": "renumbered", "served_as": "1-001-0009",
                 "path": "rules/1/001/oar-1-001-0009.md",
                 "note": "OARD serves 1-001-0009 for this number"},
                {"number": "1-001-0003", "status": "not_served",
                 "note": "OARD page contains no rule number (rule likely repealed)"},
                {"number": "1-001-0004", "status": "ingested",
                 "path": "rules/1/001/oar-1-001-0004.md",
                 "legal_status": "repealed", "legal_status_action": "repeal",
                 "legal_status_notice": "August 2026 Bulletin",
                 "reingest_action": "amend", "reingest_notice": "August 2026 Bulletin",
                 "reingest_refused": "renumbered",
                 "reingest_refused_notice": "July 2026 Bulletin"},
            ]}]}]}

    def _row(cat, number):
        return next(r for r in _all_rows(cat) if r["number"] == number)

    def _shape_mutation(mutate):
        cat = _fixture_row_shape()
        mutate(cat)
        return check_row_shape(cat)

    check("a clean catalog (one row of every shape) passes check_row_shape with no "
          "violations", check_row_shape(_fixture_row_shape()) == [])

    # readable-row (#334 code review, matching catalog_agencies.py's rule of the same name):
    # a rule row that is not a mapping -- a bare string where a `{number: ..., status: ...}`
    # block belongs -- used to crash check_row_shape() with an unhandled AttributeError
    # instead of reporting a named rule.
    unreadable_cat = {"chapters": [{"chapter": "1", "title": "T", "divisions": [
        {"division": "1", "rules": ["1-001-0001"]}]}]}
    failures = check_row_shape(unreadable_cat)
    check("a rule row that is not a mapping is refused by readable-row, proven by feeding "
          "check_row_shape a bare string where a row belongs, rather than raising",
          any(f.rule == "readable-row" for f in failures))

    failures = _shape_mutation(
        lambda cat: _row(cat, "1-001-0001").__setitem__("bogus_key", "x"))
    check("an undeclared key on a row is refused, proven by adding one and watching the "
          "named rule fire",
          any(f.rule == "declared-field" for f in failures))

    failures = _shape_mutation(lambda cat: _row(cat, "1-001-0001").pop("number"))
    check("a row missing the required `number` field is refused",
          any(f.rule == "required-field" for f in failures))

    failures = _shape_mutation(lambda cat: _row(cat, "1-001-0004").pop("legal_status_notice"))
    check("the legal_status trio is refused when only two of the three are present, "
          "proven by breaking it",
          any(f.rule == "field-group-complete" for f in failures))

    failures = _shape_mutation(lambda cat: _row(cat, "1-001-0004").pop("reingest_notice"))
    check("reingest_action without reingest_notice is refused, proven by breaking it",
          any(f.rule == "field-group-complete" for f in failures))

    failures = _shape_mutation(
        lambda cat: _row(cat, "1-001-0004").pop("reingest_refused_notice"))
    check("reingest_refused without reingest_refused_notice is refused (#334's own finding: "
          "a real writer's SECOND both-or-neither pair, uncounted by #334's ten-key "
          "measurement because every committed row holds neither key today)",
          any(f.rule == "field-group-complete" for f in failures))

    failures = _shape_mutation(
        lambda cat: _row(cat, "1-001-0001").__setitem__("served_as", "1-001-0099"))
    check("served_as on a row that is not status: renumbered is refused, proven by "
          "breaking it",
          any(f.rule == "served-as-tracks-renumbered" for f in failures))

    failures = _shape_mutation(lambda cat: _row(cat, "1-001-0002").pop("served_as"))
    check("status: renumbered with no served_as is refused, proven by breaking it",
          any(f.rule == "served-as-tracks-renumbered" for f in failures))

    failures = _shape_mutation(lambda cat: _row(cat, "1-001-0001").pop("path"))
    check("status: ingested with no path is refused, proven by breaking it",
          any(f.rule == "path-matches-ingest-status" for f in failures))

    failures = _shape_mutation(
        lambda cat: _row(cat, "1-001-0003").__setitem__(
            "path", "rules/1/001/oar-1-001-0003.md"))
    check("status: not_served with a path present is refused, proven by breaking it",
          any(f.rule == "path-matches-ingest-status" for f in failures))

    # THE OTHER "NOTHING FETCHED" STATUSES, the same direction as not_served above -- every
    # word `INGEST_STATUS_VALUES` declares other than `ingested`/`renumbered`
    # (`_NOTHING_FETCHED_STATUSES`, derived, not hand-listed). `not_ingested` is in this
    # loop, not treated as a special case (#334 code review: it used to be left off the
    # hand-typed tuple entirely, so this exact mutation passed silently).
    for extra_status in ("not_sliceable", "needs_registry", "not_ingested"):
        failures = _shape_mutation(
            lambda cat, s=extra_status: (
                _row(cat, "1-001-0003").__setitem__("status", s),
                _row(cat, "1-001-0003").__setitem__(
                    "path", "rules/1/001/oar-1-001-0003.md")))
        check(f"status: {extra_status} with a path present is refused, proven by breaking it",
              any(f.rule == "path-matches-ingest-status" for f in failures))

    # THE COMMAND LINE ITSELF, not only check_row_shape() feeding it -- readable-catalog and
    # catalog-populated only fire through cmd_check(), which is what a CI run actually
    # invokes (matching catalog_agencies.cmd_check()'s own reason for a `catalog_path` param).
    check("readable-catalog fires when the catalog file does not exist, through the real "
          "command line",
          cmd_check(catalog_path=REPO_ROOT / "_meta/catalog/does-not-exist-334.yml") == 1)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        empty_path = Path(tmp) / "empty.yml"
        empty_path.write_text(yaml.safe_dump({"chapters": []}))
        check("catalog-populated fires when the catalog parses but holds no chapters",
              cmd_check(catalog_path=empty_path) == 1)
        # readable-catalog ALSO COVERS A CATALOG THAT DOES NOT PARSE, NOT ONLY ONE THAT
        # DOES NOT EXIST (#334 code review). Before this fix a YAML parse error escaped
        # cmd_check() as a raw traceback instead of a named failure.
        unparseable_path = Path(tmp) / "unparseable.yml"
        unparseable_path.write_text("chapters:\n  - [unclosed")
        check("readable-catalog fires when the catalog file exists but does not parse, "
              "instead of a raw YAMLError traceback escaping cmd_check()",
              cmd_check(catalog_path=unparseable_path) == 1)
        clean_path = Path(tmp) / "clean.yml"
        clean_path.write_text(yaml.safe_dump(_fixture_row_shape()))
        check("cmd_check() exits 0 on a catalog that passes every declared rule",
              cmd_check(catalog_path=clean_path) == 0)

    # THE KNOWN, REPORTED GAP (#334/#338) -- not gated, but named, and its own function
    # proven to find exactly the rows the rule above declines to fail on. Proven in BOTH
    # directions (#334 code review): the old version was a pure status filter that read no
    # disk at all, so its docstring's disk claim was never exercised by the case where it
    # would be FALSE. `root` points this at a temporary directory so neither direction
    # touches or depends on the real `rules/` tree.
    gap_cat = _fixture_row_shape()
    _row(gap_cat, "1-001-0002").pop("path")  # renumbered, served_as="1-001-0009", path absent
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        check("RED: renumbered_without_path finds NOTHING when the served_as target is "
              "NOT on disk -- the direction the old pure-status-filter implementation "
              "could never fail, because it never looked",
              renumbered_without_path(gap_cat, root=tmp_root) == [])
        served_target = oar_rule_path("1-001-0009", root=tmp_root)
        served_target.parent.mkdir(parents=True, exist_ok=True)
        served_target.write_text("stub rule body")
        check("GREEN: ...and finds exactly that renumbered row once its served_as target "
              "is really on disk, and check_row_shape does NOT fail it (reported, not "
              "gated -- #338)",
              [r["number"] for r in renumbered_without_path(gap_cat, root=tmp_root)]
              == ["1-001-0002"]
              and not any(f.site == "1-001-0002" for f in check_row_shape(gap_cat)))

    # THE DECLARATION, GATED FROM BOTH SIDES (#319, matching legal_status.py,
    # stated_census.py, catalog_agencies.py and ingest_status.py). A rule can go undetected
    # by being DECLARED WITH NO PROOF (did it fire during this run) or by being EMITTED WITH
    # NO DECLARATION (does the AST agree with CHECK_RULES).
    gaps = _LEDGER.gaps()
    declared_gap = (f" (emitted-not-declared={sorted(gaps.emitted_but_undeclared)}, "
                    f"declared-not-emitted={sorted(gaps.unemitted_but_declared)})"
                    if gaps.emitted_but_undeclared or gaps.unemitted_but_declared else "")
    check("every rule this module's row-shape section can report is declared" + declared_gap,
          not declared_gap)
    unfired_gap = f" (unfired={sorted(gaps.unfired)})" if gaps.unfired else ""
    check("...and every declared rule was watched firing, not merely listed" + unfired_gap,
          not unfired_gap)

    return check.report()


def main():
    if "--selftest" in sys.argv:
        return selftest()
    if "--check" in sys.argv:
        return cmd_check()
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
