#!/usr/bin/env python3
"""Populate _meta/catalog/agencies.yml — the canonical registry of Oregon agencies and
their sub-units, grounded in the OAR chapter assignment scheme as presented by
https://oregon.public.law/rules.

  python3 src/catalog_agencies.py --refresh
  python3 src/catalog_agencies.py --check           # CI: the registry keeps its contract
  python3 src/catalog_agencies.py --selftest        # CI: every rule --check enforces fires
  python3 src/catalog_agencies.py "<search term>"   # look up a slug

WHY --check EXISTS. This registry is the identity three sibling corpora crosswalk into, and
--refresh rebuilds all 189 rows from the scrape every time it runs, so the ways it breaks are
quiet ones: a curated field nothing preserves, a manual row nothing carries over, a slug two
bodies claim. Every one of those leaves a file that still parses and slugs that still resolve,
and surfaces months later as a cross-corpus join that quietly stopped matching (it has already
happened twice — see preserve_manual and preserve_curated). --check reads committed data only,
runs a --refresh in simulation against it, and states what would be lost. It asserts nothing
about upstream: what oregon.public.law currently serves is not something a PR here can break.

Why this source (user decision 2026-07-19, third source after two rejects):
data.oregon.gov's org dataset and the SoS Blue Book directory were both reviewed and
rejected. OAR chapter numbers are the state's own operational agency-assignment scheme
(every chapter belongs to exactly one agency/board/commission), and oregon.public.law's
index additionally models HIERARCHY: sub-units nest under their parent agency (e.g.
chapter 125 Dept. of Administrative Services, with 122 Chief Financial Office, 105
Chief Human Resources Office, 128 Office of the State CIO as sub-units). Caveat,
recorded in the catalog note: oregon.public.law is an unofficial (well-maintained)
mirror; official chapter assignment lives with the SoS Administrative Rules Unit.

Mechanics: the /rules index provides the tree (nested "quasi-sub-chapter" cards) but
abbreviates names ("Dept.", "Comm'n"); each chapter page's <title> carries the proper
full name ("OAR Chapter 125 - Department of Administrative Services"), so --refresh
fetches every chapter page (politeness delay) and uses that. Slugs are mechanical
(lowercase, non-alnum runs -> one hyphen). A slug collision between two chapters is a
hard error needing a human decision, never silent dedup.

validate_frontmatter.py requires every content file's agency: field to be 'statewide',
'external', or a slug from this registry. Sub-unit slugs are valid agency: values like
any other; whether a sub-unit gets its own agencies/<slug>/ tree or files under its
parent is an onboarding-time decision."""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections import Counter, namedtuple
from datetime import date
from html import unescape

import yaml

from check_rule_ledger import RuleLedger
from repo_lib import ORCONST_ARTICLE_TOKEN, ORCONST_SECTION_TOKEN, REPO_ROOT

BASE = "https://oregon.public.law"
INDEX_URL = f"{BASE}/rules"
CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"

# ------------------------------------------------------------------- the registry's fields
#
# THE ONE PLACE A REGISTRY FIELD IS DECLARED. `CURATED_KEYS` is DERIVED from this table
# rather than restated, because the two used to be the same fact written twice: this set was
# hand-maintained beside a comment asking whoever adds a curated field to remember to add it
# here too, and forgetting means --refresh destroys the curation with no error and no diff
# anyone reads. A field that is not scraped is curated by the same statement that says it
# exists, so the two cannot disagree.
#
# ORIGIN is the load-bearing column, and it answers one question: what happens to this field
# when --refresh rebuilds every row from oregon.public.law?
#
# THE DECLARATION ORDER OF THIS TABLE IS ALSO LOAD-BEARING (#182), not just the ORIGIN
# column beside each key. `preserve_curated()` appends a rebuilt row's curated fields in
# `curated_keys_in_order()`'s order, which is a VIEW of this table filtered to CURATED and
# nothing else — so the sequence a curated field lands in inside every committed row, and
# therefore the shape of every --refresh diff, is set by the order the entries are WRITTEN
# below. Regrouping this table for readability regroups the committed registry with it, and
# nothing above the ORIGIN column said so until this paragraph did. `check_registry()`'s own
# read of this table (`curated_keys_in_order(fields)`) is what makes the simulation faithful
# to that ordering, not only to which keys survive.
#
#   SCRAPED     the refresh writes it. `scraped_entry()` below is the only thing that may
#               produce one, and --check verifies this column against that constructor, so
#               calling a field scraped is a claim the code has to back up.
#   CURATED     nothing upstream produces it; it survives only because CURATED_KEYS carries
#               it across a refresh. Hand-reviewed data, and the reason this table exists.
#   MANUAL_FLAG `manual: true`, which is preserved by a different mechanism — it keeps the
#               WHOLE row (a body the chapter scrape can never see). Deliberately NOT
#               curated: copying the flag onto a row the scrape now produces would re-assert
#               a claim that a human is supposed to retire by hand after comparing names.
#   MERGED      the field is a LIST whose entries do not share one origin: some are
#               regenerated by the refresh and some are curation it must carry across, and
#               which is which is written on the entry. The whole-field question the three
#               origins above answer ("does the refresh write this key?") has no true answer
#               for such a field, so it is merged ENTRY BY ENTRY instead — see RELATIONS
#               below for the field that forced it. `note` used to be a simpler version of
#               the same problem and MERGED could not have fixed it either, since a mixed
#               origin written per-list-entry has nowhere to live on a field that is one
#               string: #178 gave the two origins separate FIELDS instead (`note` below).
#   PER_ROW     the field's origin is written ON THE ROW, because it differs between rows
#               rather than between fields. `name` is the field that forced it (#168): once
#               `name` is the STATUTORY name, a row whose statutory name has been
#               established from its enabling authority holds curation the refresh must
#               carry across, while a row still carrying its unverified OAR title holds a
#               value the refresh rebuilds from the chapter page — and the two are the same
#               key on the same file. MERGED could not express it: that origin is written on
#               a LIST'S ENTRIES, and a name is one string. So the row says which, in
#               `name_basis`, and `preserve_name()` reads it — the same shape `relations`
#               has one level down, and the same reason: a field whose origin nothing states
#               is a field --refresh either freezes or destroys, with nothing to report
#               which.
SCRAPED, CURATED, MANUAL_FLAG, MERGED = "scraped", "curated", "manual-flag", "merged"
PER_ROW = "per-row"

# ---------------------------------------------------------------- what a name is grounded in
#
# WHICH OF THE TWO THINGS THIS ROW'S `name` IS, WRITTEN ON THE ROW. ADR 0003 makes `name` the
# STATUTORY name — the name a body's enabling authority gives it — and #168 lands that
# meaning. What it does NOT do is invent one: whether a row carries a reviewed enabling
# authority is a separate fact from whether its `name` has been promoted from one —
# `authority_census()` prints the live split of the first on every `--check` run, and
# promotion still needs a second, hand-driven step (link_enabling_authority.py's
# STATUTORY_NAMES) that most rows have not had yet, so most still hold the OAR chapter
# title they were scraped with.
#
# THAT IS THE WHOLE POINT OF THIS FIELD. A row that quietly keeps its OAR title while the
# field's documented meaning becomes "statutory name" is a false statement about Oregon law
# published under provenance — the same substitution `manual: true` was retired for (ADR
# 0003: an assertion records that someone decided, never what decided it) and the same one
# `UNMAPPED` exists to prevent in link_budget_codes.py: "we looked and this is what we found"
# and "nobody has looked yet" must not be the same state. So the two states are NAMED, and
# `--check` reports both counts on every run rather than leaving a reader to infer one from
# the other.
#
#   enabling-authority     the statutory name, read off the body's enabling authority by a
#                          human. The row must carry an authority in one of AUTHORITY_FORMS
#                          to support the claim (`statutory-name-basis`), and the name is
#                          written by link_enabling_authority.py from its reviewed table —
#                          the same single writer the authority itself has (#175).
#   unverified-oar-title   nobody has established a statutory name for this body, so `name`
#                          still holds the OAR chapter title it was scraped with. The row
#                          must hold exactly that (`statutory-name-basis` states
#                          `name == oar_name`), which is what makes "retains its current
#                          value" a checkable claim rather than a promise.
#
# ALLOWLIST, NOT BLOCKLIST, as everywhere else in this module: a third word here is a
# provenance no reader can weigh and no gate can act on.
ENABLING_AUTHORITY_NAME = "enabling-authority"
UNVERIFIED_OAR_TITLE = "unverified-oar-title"
NAME_BASES = (ENABLING_AUTHORITY_NAME, UNVERIFIED_OAR_TITLE)
NAME_BASIS_KEY = "name_basis"

# THE NAME AND ITS PROVENANCE TRAVEL TOGETHER, and that is why this is a pair rather than two
# keys carried independently. Carrying `name` without `name_basis` leaves a statutory name
# labelled as an OAR title; carrying `name_basis` without `name` leaves an OAR title labelled
# as a statutory name. Both are the row lying about itself, and the second is the one this
# ticket exists to make impossible.
NAME_KEYS = ("name", NAME_BASIS_KEY)

Field = namedtuple("Field", "origin required")

# EVERY RULE THIS MODULE CAN REPORT (#320). Declared rather than counted at run time so a
# rule added with no proof is visible as a list that did not grow, matching
# `legal_status.CHECK_RULES` and `stated_census.CHECK_RULES` -- `--selftest` asserts both
# that this is what the code actually emits (the AST scan) and that every name here was
# watched firing during the run (`_LEDGER.fired`).
CHECK_RULES = (
    # can the registry be read at all, and does it hold anything
    "readable-registry", "registry-populated", "readable-row",
    # a row's own shape: the fields it must carry, and the ones it may not
    "required-field", "declared-field",
    # the one this module reads off two scripts
    "chapter-page-count-current",
    # the retired DAS-number alias, the enabling authority's form, the statutory
    # name's provenance, and the two names a body must stay findable by
    "budget-agency-code-retired", "enabling-authority-form", "statutory-name-basis",
    "name-origin", "findable-by-both-names",
    # the relations: their shape, uniqueness, resolution, what `part_of` may not carry, an
    # `administered_by` authority that belongs to a different body (#212), and the field's
    # own mixed origin
    "relation-shape", "relation-unique", "relation-resolves",
    "part-of-has-nothing-to-enable", "relation-authority-is-not-another-bodys-own",
    "relation-origin",
    # what the OAR index tree itself asserts, and the parent chapter beside it
    "index-relation-is-regenerated", "parent-agrees",
    # the two things a sibling corpus joins on, claimed twice
    "unique-slug", "unique-chapter",
    # the registry's own top-level `note`, checked three ways
    "note-covers-fields", "note-agrees-with-refresh", "note-numbers-current",
    # a ROW's own `note` (a different field of the same name), checked against the shape
    # only cmd_refresh() can write
    "note-scrape-shape",
    # a field's declared origin, checked against what a simulated --refresh actually does
    "scraped-field", "survives-refresh",
)

# THE CHECK-RULE LEDGER (#319, adopted here by #320). Recording a rule name when a Failure
# is built (`_LEDGER.fired`, the ledger's own set rather than a module global), the AST scan
# of this module's own source for the rule names a `Failure(...)` call can EMIT
# (`_LEDGER.emitted_rules`), and the both-directions comparison of the two against
# `CHECK_RULES` (`_LEDGER.gaps()`) are the one shared implementation `legal_status.py` and
# `stated_census.py` already carry -- this module had none of it (#320's own measurement:
# no `CHECK_RULES`, no recording, no gate in either direction), and adopting it is what
# surfaced two rules this module could report and nothing demonstrated
# (`chapter-page-count-current` turned out to already have a proof; `readable-registry` did
# not), a rule spelled a second time as a bare print string outside any `Failure(...)` call,
# and two rules (`unique-slug`, `unique-chapter`) the code emitted through a variable rather
# than a literal -- invisible to the AST scan by the SAME narrowing
# `check_rule_ledger.py`'s own proof deliberately keeps, so the fix is the call sites, not
# the scanner (see the loop `check_registry()` used to share between them, now two literal
# call sites below).
_LEDGER = RuleLedger(CHECK_RULES, __file__)


class Failure(_LEDGER.Failure):
    """One rule, the registry site it is about, and what is wrong with it -- recorded on
    construction by the shared ledger (like `legal_status.Failure` and
    `stated_census.Failure`) so no proof has to remember to say it fired, and a rule name
    not in `CHECK_RULES` refuses construction rather than passing an unmarked write through.
    Only `__str__` is added here, matching `stated_census.Failure`: `cmd_check()` prints a
    failure directly, so both of the rule's call sites -- the per-row loop and the
    registry-missing guard that used to spell it separately -- format it identically."""
    __slots__ = ()

    def __str__(self):
        return f"  FAIL [{self.rule}] {self.site}: {self.detail}"


FIELDS = {
    "slug": Field(SCRAPED, required=True),
    # THE STATUTORY NAME (CONTEXT.md): the name the body's enabling authority gives it, which
    # is what ADR 0003 decided this field holds — "the registry's subject is the body, and a
    # body's name is the one its enabling authority gives it; the OAR index is a publisher,
    # and publishers spell things their own way". ADR 0003 calls the promotion the risky half
    # and took it deliberately; #187 moved the two OAR-derived joins onto `oar_name` first,
    # which is what makes it safe to land.
    #
    # NOT EVERY ROW HOLDS ONE, AND THE ROW SAYS SO. This ticket does not invent statutory
    # names: a row whose statutory name has been established from its enabling authority
    # holds it, and every other row still holds the OAR chapter title it was scraped with.
    # `name_basis` below is which — see NAME_BASES for why the two may never be the same
    # state, and `statutory-name-basis` in check_registry() for what states each of them.
    #
    # PER_ROW, and it is the field that forced that origin. An established statutory name is
    # curation nothing upstream produces, so a refresh that rebuilt it from the chapter page
    # would silently replace a reviewed name with a publisher's spelling; an unverified OAR
    # title is exactly what the chapter page prints, so freezing it would leave the row
    # asserting a title the rules index no longer uses. Neither whole-field origin is true of
    # this key, and `preserve_name()` is what reads the row to decide. `name-origin` in
    # check_registry() states that it may not be declared as either.
    "name": Field(PER_ROW, required=True),
    # WHICH OF THE TWO THINGS THE `name` BESIDE IT IS (NAME_BASES above). Required on every
    # row, because an absent basis and `unverified-oar-title` are not the same claim — the
    # first says nobody recorded where this name came from, the second says somebody looked
    # and it is still the rules index's title. PER_ROW for the reason `name` is: it is half
    # of one statement, and `preserve_name()` carries the pair or neither.
    NAME_BASIS_KEY: Field(PER_ROW, required=True),
    # THE OAR NAME (CONTEXT.md): the name the administrative rules index gives a body, and
    # the string OAR-derived joins must match (ADR 0003). It landed BESIDE `name` rather than
    # replacing it, so consumers could move off `name` while `name` still meant what it always
    # did — and they did, before #168 changed what `name` holds. A crosswalk that keeps
    # matching a string that quietly changed meaning is the failure those crosswalks exist to
    # prevent, and the order of those two steps is the whole of why it did not happen here.
    #
    # SCRAPED, NOT CURATED, and that is the whole point of the field. The chapter page's own
    # title is where this value comes from — `scraped_entry()` already reads it — so
    # declaring it CURATED would mean --refresh preserves the old file's copy and never
    # updates it: an upstream chapter retitle would move `name` and leave `oar_name` frozen
    # at a title the rules index no longer prints. A field that cannot track an upstream
    # retitle cannot be the string OAR-derived joins match on.
    "oar_name": Field(SCRAPED, required=True),
    # Null on 20 rows (#281, re-measured; live count printed by --check as "N chapterless")
    # and that is not a gap: a body is in the registry because it EXISTS, not because it
    # issues rules (ADR 0003). Required means the KEY is present.
    "oar_chapter": Field(SCRAPED, required=True),
    "raw_index_name": Field(SCRAPED, required=True),
    "source_url": Field(SCRAPED, required=True),
    # THE PARENT'S OAR CHAPTER, and the half of the old pointer pair that is left. #174
    # retired `parent_slug`: a body's placement under another lives in `relations` and
    # nowhere else (ADR 0004), because the relation says who places it there, which of ADR
    # 0004's two kinds it is and on what authority — none of which a bare slug could say,
    # and all of which a consumer reading the slug would have to invent. `parent_chapter`
    # is NOT that pointer written again: it is the CHAPTER the rules index files the parent
    # under, scraped from the same tree, and `parent-agrees` states that it may not
    # disagree with the body the row's relations name.
    "parent_chapter": Field(SCRAPED, required=True),
    # THE RELATIONS (CONTEXT.md), and since #174 the ONLY statement this registry makes
    # about which body another sits under: a target, the source whose evidence places it
    # there, a kind and, where one is known, the authority that establishes it (ADR 0004).
    # Required and a list, empty when the registry places this body under nothing — an
    # absent key would say nobody looked, and those are different claims.
    #
    # MERGED, and it is the first field that is. A body may hold MORE THAN ONE relation,
    # because DAS, the OAR index and statute may each place it under a different parent and
    # ADR 0003 decided that disagreement is KEPT rather than reconciled — so one list holds
    # an entry the scrape regenerates beside an entry only curation produces. Declaring the
    # whole field SCRAPED would drop the curated entries on every refresh and hide the drop
    # (a scraped field is skipped by the survival comparison); declaring it CURATED would
    # freeze the OAR index's placement at whatever it said the day it was written. See
    # `preserve_relations()` for the merge and `relation-origin` in check_registry() for
    # what states that this field may not be declared as either.
    "relations": Field(MERGED, required=True),
    # SCRAPE-ONLY (CONTEXT.md, "Relation source"). `cmd_refresh()` writes one of exactly
    # three sentences — NOTE_SCRAPE_TEMPLATES, above `cmd_refresh()` — when a chapter page's
    # title will not parse, its fetch fails, or a chapterless group's children disagree on a
    # name prefix.
    # #178: this field USED TO be where curator prose lived too (the two rows carrying one
    # were both hand-typed), which made it a field with two origins and no way to tell them
    # apart — declaring it CURATED would resurrect a stale "title not parseable" sentence
    # forever, and leaving it SCRAPED let a hand-typed note get silently rebuilt away the
    # first time it landed on a row `manual` did not protect. `note-scrape-shape` in
    # check_registry() is what makes that unreadable state unreachable rather than merely
    # undocumented: a `note` that is not one of the scrape's own sentences is refused,
    # `manual` or not, because curator prose belongs in `curator_note` below instead of
    # here.
    "note": Field(SCRAPED, required=False),
    "manual": Field(MANUAL_FLAG, required=False),
    # CURATOR PROSE ABOUT A ROW (CONTEXT.md, "Relation source") — #178's other half. Nothing
    # upstream ever produces this key, so it needs none of `manual`'s whole-row protection:
    # CURATED_KEYS carries it across a refresh on ANY row, the same way `das_agency_number`
    # survives one today. The two hand-typed sentences that used to sit in `note` (chapters
    # 419, 950 — the mirror gap `manual` was already protecting them for) live here now.
    "curator_note": Field(CURATED, required=False),
    # THE DAS AGENCY NUMBER (CONTEXT.md): the number DAS assigns a body in the Oregon
    # Accounting Manual (OAM 70.10.00). It identifies the body in the state's financial
    # administration and says nothing about whether it spends money — thirteen
    # semi-independent bodies carry one and are explicitly outside the state's accounting
    # system, which is why ADR 0003 renames the field off a name that says "budget".
    # Hand-reviewed, one number per body; the table is src/link_budget_codes.py.
    "das_agency_number": Field(CURATED, required=False),
    # Other names the same body is known by, including former names after a rename. An
    # ASSERTION of identity, reviewed once, rather than a similarity score computed at
    # query time.
    "aliases": Field(CURATED, required=False),
    # THE ENABLING AUTHORITY (CONTEXT.md): what created the body. CURATED and NOT required,
    # and both halves of that are the point — see AUTHORITY_FORMS below for what the value
    # may say and `enabling-authority-form` in check_registry() for what it may not.
    #
    # CURATED because nothing upstream produces it: the OAR index publishes chapter
    # assignments, and no chapter page states what statute created the body it belongs to.
    # The single writer is src/link_enabling_authority.py, driven by the hand-reviewed
    # MAPPED/UNMAPPED tables in that file — the same shape `das_agency_number` has, for the
    # same reason (#175): two writers of one field is drift nothing reports.
    #
    # NOT required because an absent key is the honest default: an absent key says nobody
    # has looked yet, however many rows that is today — `authority_census()` prints the
    # live count on every `--check` run rather than a figure fixed here — which is a
    # different claim from a body that was looked at and has no separate enabling
    # authority, and neither may be written as a blank.
    "enabling_authority": Field(CURATED, required=False),
}

# THE COMMITTED FILE'S OWN TOP-LEVEL `note` (the prose above `organizations`, read by
# three sibling corpora) AND THE STRING cmd_refresh() WRITES BACK ARE THE SAME OBJECT,
# not two hand-synchronized copies — extracted here so check_registry()'s
# `note-agrees-with-refresh` (#185 follow-up) can compare the committed file against it
# directly, rather than only checking that every FIELDS name appears somewhere in the
# committed prose (`note-covers-fields`), which says nothing about whether the two texts
# actually agree.
#
# #278 asked whether that equality check was itself the bug — AC4 of #185 wanted "the note
# not regenerated wholesale on every write," reasoning by analogy to catalog_oar.py's
# `INITIAL_NOTE` (#241: restating that literal on every write once deleted 1,430 characters
# of genuine curator prose). The analogy does not transfer: measured by walking every one of
# the 23 commits that have ever touched `_meta/catalog/agencies.yml` and comparing each
# commit's committed `note` against that same revision's module literal, the committed
# top-level note has NEVER been longer than the literal — byte-identical in most revisions,
# a stale SHORTER earlier version in the rest, at every single commit including the one
# immediately before #185's own fix (committed 5,260 == literal 5,260, exact). No curator
# prose has ever been appended to this field. `catalog_oar.py`'s case is real (4,425
# committed characters against an `INITIAL_NOTE` of 1,875, from #228/#229 appending
# paragraphs directly) because that module never split a curator-prose field out of its
# note the way #178 split this registry's row-level `note`/`curator_note` — a curator here
# who wants to say something about a specific row already has `curator_note` (CURATED,
# survives any refresh via `CURATED_KEYS`, CONTEXT.md), needing none of this field's
# whole-note protection. AC4 is closed by option 2 of #278's own two named shapes: the
# top-level `note` is declared out of scope for curator prose, in AGENTS.md and CONTEXT.md,
# rather than given a preservation mechanism for content that has never once been written to
# it. `note-agrees-with-refresh` stays exactly as #185 left it — a real regression guard,
# not a check that would fail forever the first time someone used a capability nothing here
# actually needs.
# THE TWO SCRIPTS THAT STATE, IN PROSE, HOW MANY CHAPTER PAGES A --refresh FETCHES (#279).
# `expand_oar_name.py` and `record_name_basis.py` each explain why they are a one-shot
# script and not a --refresh by naming the network cost of the alternative — a number that
# went stale in both of them at once (189, the registry's ROW count, when only 170 of those
# rows carry an `oar_chapter` and are ever fetched) because nothing compared the claim
# against the data it describes. Extracted here, not typed into check_registry(), so
# --selftest can inject synthetic text instead of reading these two files off disk (the
# same reason `refresh_note` is a parameter and not a read of REGISTRY_NOTE inline).
CHAPTER_PAGE_DOC_FILES = (
    REPO_ROOT / "src/expand_oar_name.py",
    REPO_ROOT / "src/record_name_basis.py",
)
# THE PHRASE THE CHECK LOOKS FOR. Both files were written to share it on purpose (#279's
# fix), so one pattern catches both; a future rewording that drops this exact shape is
# refused by `chapter-page-count-current` below rather than silently going unchecked.
CHAPTER_PAGE_COUNT_RE = re.compile(r"re-fetches (?:all )?([\d,]+) chapter pages")

# THE REGISTRY'S OWN "null on N of the M chapterless" CLAIM, IN ITS OWN NOTE (code review
# of #281). `REGISTRY_NOTE` states, in prose, how many chapterless rows carry no
# `source_url` — a hand-typed pair of numbers that went stale a second time in the commit
# that added the 20th chapterless row: the sentence survived a whitespace-only re-wrap
# unchanged at "14 of the 19" while `chapter_census()` printed "(20 chapterless)" in the
# same `--check` run. `note-covers-fields` (#185) only proves every FIELDS name appears
# somewhere in the note; `note-agrees-with-refresh` only proves the committed note matches
# `REGISTRY_NOTE`, which can be wrong the same way and was — neither reads a number.
NOTE_CHAPTERLESS_RE = re.compile(r"null on (\d+) of the (\d+) chapterless")


def _default_chapter_page_docs():
    """{path: text} for `CHAPTER_PAGE_DOC_FILES`, `None` in place of the text for a file
    that could not be read (code review of #279: a bare `p.read_text()` here let a missing
    file crash `--check` with an uncaught `FileNotFoundError` instead of a `Failure` line —
    both files it reads are, by their own docstrings, one-shot migration scripts a future
    cleanup may delete). Every other unreadable input in this module is REPORTED, not
    raised: `cmd_check()` guards `CATALOG.exists()` for `readable-registry` and
    `check_registry()` has `readable-row` for the same reason. `check_registry()` turns a
    `None` here into a `chapter-page-count-current` failure naming the file, keeping the
    failure inside the contract instead of outside it."""
    docs = {}
    for p in CHAPTER_PAGE_DOC_FILES:
        try:
            docs[str(p)] = p.read_text()
        except OSError:
            docs[str(p)] = None
    return docs


REGISTRY_NOTE = (
    "Canonical registry of Oregon agencies and their sub-units, keyed on "
    "the OAR chapter assignment scheme as presented by oregon.public.law/"
    "rules (an unofficial but well-maintained mirror; official chapter "
    "assignment lives with the SoS Administrative Rules Unit). The names "
    "the scrape produces come from each chapter page's own title; the index tree "
    "provides the parent/sub-unit hierarchy, recorded in `relations` "
    "(ADR 0004) with parent_chapter beside it. "
    "Third registry source: a data.oregon.gov dataset and the SoS Blue "
    "Book directory were both previously used and dropped after review "
    "(2026-07-18/19). validate_frontmatter.py requires every content "
    "file's agency: field to resolve to 'statewide', 'external', or a "
    "slug here. THREE NAME FIELDS, WHICH ARE THREE DIFFERENT STRINGS. name "
    "is the STATUTORY name (ADR 0003) — the name the body's enabling "
    "authority gives it — and name_basis, on every row, says whether this "
    "row actually holds one: enabling-authority means a human read the "
    "body's enabling authority and recorded what it calls the body, and "
    "unverified-oar-title means nobody has established a statutory name and "
    "name still holds the OAR chapter title it was scraped with, unchanged "
    "(#168). The two are never the same state, and --check reports both "
    "counts on every run: a row quietly keeping its OAR title under a field "
    "that means `statutory name` is a false statement about Oregon law "
    "published under provenance. Which of the two a row is decides what "
    "--refresh does to its name, so name is neither scraped nor curated: an "
    "established name is carried across untouched, and an unverified one is "
    "rebuilt from the chapter page so an upstream retitle reaches it. "
    "oar_name is the OAR name — the chapter page's own title, "
    "which is the string OAR-derived joins must match; it is scraped, so an "
    "upstream chapter retitle moves it. raw_index_name is a different "
    "string: the index's own abbreviated spelling. "
    "das_agency_number, where present, is the three-digit number DAS "
    "assigns the body in the Oregon Accounting Manual (OAM 70.10.00) — it "
    "identifies the body in the state's financial administration and is not "
    "evidence that the body spends money, and it is what the oregon-budget "
    "corpus joins on; it is "
    "hand-reviewed (src/link_budget_codes.py), is NOT scraped from the "
    "source above, and is preserved across --refresh. Its absence on an "
    "entry means no counterpart was found, not that none was sought. "
    "relations, on every row, is where each body's placement under another "
    "is recorded (ADR 0004): a target slug, the source whose evidence places "
    "it there, a kind, and — where one has been established — the authority "
    "that makes it true. It REPLACED parent_slug, which this registry no "
    "longer carries (#174): a bare parent slug could not say whose reading a "
    "placement was, which of ADR 0004's two kinds it is, or on what authority. "
    "A kind other than undetermined also records the BASIS it was derived "
    "from, which is a different fact from the source: the source says who "
    "places this body under that one, the basis says what settled which of ADR "
    "0004's two kinds it is, and a relation the OAR index discovered can have "
    "its kind decided by a statute. The two bases are not the same strength. "
    "proposed-enabling-authority means the kind was derived from a CANDIDATE in "
    "_meta/catalog/enabling-authority-review.yml that nobody has read — a "
    "proposal, not evidence — and the row upgrades to "
    "reviewed-enabling-authority when the review lands (ADR 0004 records this "
    "deviation and why it was taken). Only administered_by is derived: the "
    "absence of a candidate is never read as evidence that a body is part_of "
    "anything, so a relation nothing speaks to stays undetermined, which is the "
    "answer and not a gap. The kind is never guessed, and --check reports every "
    "kind, every source and every basis with its count on each run. Kinds are "
    "written by ONE thing, src/derive_relation_kinds.py, and carried across a "
    "--refresh per key: the scrape rebuilds the placement and the decision "
    "rides along. A body may hold more than "
    "one relation, because the OAR index, DAS and statute may place it under "
    "different parents and the disagreement is kept rather than reconciled "
    "(ADR 0003). MIXED ORIGIN, which is why the field is neither scraped nor "
    "curated: entries whose source is oar-index are REGENERATED by --refresh "
    "from the index tree, so an upstream re-filing reaches this file, and "
    "every other entry is carried across untouched. A manual row's placement "
    "is sourced `registry` and never `oar-index`: the index does not carry "
    "that body, so it has placed it nowhere and no refresh can rebuild the "
    "entry. An empty list means this registry places the body under no other. "
    "enabling_authority, where present, is what created the body "
    "— an ORS citation, a constitutional article, or an executive order (ADR "
    "0003) — or `none: ` and the reason there is none. It is hand-reviewed "
    "(src/link_enabling_authority.py), is NOT scraped, and is preserved "
    "across --refresh. An ABSENT enabling_authority means nobody has reviewed "
    "this body yet; it never means the body has no enabling authority, which "
    "is what the `none: ` form says and says with a reason. "
    "oar_chapter is the OAR chapter this body's rules are filed under, "
    "scraped from the index tree; null on the chapterless rows is not a "
    "gap — a body is in this registry because it EXISTS, not because it "
    "issues rules. source_url is the chapter page each row was scraped "
    "from, where the scrape found one: null on 15 of the 20 chapterless "
    "rows, not all of them — the other five hold a source_url that is "
    "not a chapter page (four hold the mirror's own rules index, "
    "https://oregon.public.law/rules, and the manual saif-corporation "
    "row holds its own site). aliases, where present, are other "
    "names the same body is known by, including former names after a "
    "rename — hand-reviewed once, curated, and preserved across "
    "--refresh. note is scrape-only (#178): cmd_refresh() writes one of "
    "exactly three sentences into it, when a chapter page's title will "
    "not parse, its fetch fails, or a chapterless group's children "
    "disagree on a name prefix, and nothing else may live there, "
    "`manual` or not. curator_note holds hand-typed prose about a row "
    "instead, protected across --refresh the way das_agency_number is: a "
    "finding a hand edit cannot safely fold into a gated field, such as "
    "why a manual row is manual when the mirror's index omits its "
    "chapter, or a body's identity change the current derivation "
    "contract cannot yet state as a relation (#212). This paragraph is "
    "itself checked against FIELDS by name on every --check run "
    "(`note-covers-fields`, #185): a field FIELDS declares that these "
    "sentences do not mention fails the gate, so this note cannot go "
    "stale the way it did before anything watched it."
)


# THE RETIRED KEY, NAMED SO IT CANNOT COME BACK UNNOTICED. ADR 0003 renamed
# `budget_agency_code` to `das_agency_number`; #175 was the EXPAND half (every row carrying
# the number carried it under both keys, with the same value, for one deprecation cycle) and
# this is the CONTRACT half (#177): the old key is gone from FIELDS, and `das_agency_number`
# is the only key the number is ever written under, by `write_das_agency_number()` below.
#
# Removing it from FIELDS already makes `declared-field` refuse any row that still carries
# it — an undeclared key. That generic message ("declare it") is the wrong instruction for a
# key ADR 0003 retired on purpose, so `budget-agency-code-retired` in check_registry() names
# the reappearance specifically, with the instruction that fits it: this key does not get
# declared, it gets deleted again. See #177.
BUDGET_AGENCY_CODE = "budget_agency_code"

# ------------------------------------------------------------------- what a relation is
#
# A RELATION NAMES THE BODY THIS ONE IS UNDER, AND SAYS ON WHOSE EVIDENCE. ADR 0004 splits
# `parent_slug` into *part of* and *administered by* (CONTEXT.md defines both), and ADR 0003
# decides that where the evidence disagrees the disagreement is kept: "a body that DAS files
# under one parent and statute under another is a finding, and silently picking one hides
# it". So a relation is (target, source, kind) with an optional authority, and a body may
# hold several — one per source that has spoken about it.
RELATION_KEY = "relations"

# THE SOURCES, AND WHAT --refresh DOES WITH EACH. The value is the ORIGIN of an entry from
# that source, reusing the same two words FIELDS uses, because it is the same question asked
# one level down: does the refresh write this, or must it carry it across?
#
#   oar-index   the placement the rules index publishes, which is what `parent_slug` already
#               holds. REGENERATED every refresh from the index tree, for the reason
#               `oar_name` is scraped: a field that cannot follow an upstream move is a
#               field that quietly starts lying about where the publisher files this body.
#   statute     the placement an ORS section establishes. ADR 0004: enabling authority wins
#               where the sources disagree, and it is the reading nothing upstream produces.
#   das         where DAS files the body in the Oregon Accounting Manual — corroborating
#               evidence (CONTEXT.md), recorded as its own reading rather than merged into
#               the others.
#   registry    a placement THIS REGISTRY recorded by hand, on evidence stated in the row's
#               `note`. It exists because one row needs it and `oar-index` would be false on
#               that row: a `manual` body is one the chapter index does not carry, so the
#               index has placed it nowhere, and the entry can never be regenerated because
#               the scrape cannot see the row (`preserve_manual`). Recording it as the
#               index's reading would attribute a placement to a publisher that never made
#               it AND label an unregenerable entry as one the refresh rebuilds — two false
#               claims to save one source name.
#
# ALLOWLIST, NOT BLOCKLIST. A source this registry has no meaning for is refused in front of
# whoever wrote it, rather than published as provenance nobody can act on — the same reason
# AUTHORITY_FORMS is an allowlist, and the reason a new source is added HERE, deliberately,
# rather than by a consumer inventing a string.
OAR_INDEX = "oar-index"
REGISTRY = "registry"
RELATION_SOURCES = {OAR_INDEX: SCRAPED, REGISTRY: CURATED, "statute": CURATED,
                    "das": CURATED}

# THE KINDS, AND WHY THE DEFAULT IS A WORD RATHER THAN A GUESS. ADR 0004's two kinds turn on
# whether the body carries its own admitting evidence, and that evidence is not in the
# registry yet (#173 derives the kinds from it). Recording every relation as `part_of` today
# would be 25 false statements about Oregon law; leaving the key off would let a consumer
# read the absence as either kind. `undetermined` says the one true thing: this relation is
# real and nobody has established which of the two it is. It is REPORTED as a count by
# --check rather than defaulted away (`relation_census`).
UNDETERMINED = "undetermined"
PART_OF, ADMINISTERED_BY = "part_of", "administered_by"
RELATION_KINDS = (UNDETERMINED, PART_OF, ADMINISTERED_BY)

# WHAT DECIDED THE KIND, WHICH IS NOT WHERE THE RELATION CAME FROM. `source` answers "who
# places this body under that one" and `basis` answers "what settled which of ADR 0004's two
# kinds it is" — two different facts about one entry, and #173 is where they come apart: a
# relation the OAR INDEX discovered can have its kind decided by a STATUTE. Collapsing them
# would mean either attributing a placement to a publisher that never made it, or attributing
# a kind to one that cannot state it (ADR 0004 rejects inferring the relation from a chapter
# assignment).
#
# THE THREE BASES ARE NOT THE SAME STRENGTH, and keeping them apart is the whole of #173 and
# #222. ADR 0004 derives the kind from ADMITTING EVIDENCE, and how much of it the registry
# holds moves as reviews land — a live split `catalog_agencies.py --check` prints every run
# rather than a count fixed here. What is not yet reviewed sits in
# _meta/catalog/enabling-authority-review.yml — as a PROPOSED candidate where the matcher
# found one, or in that sheet's `no_candidate` list where it did not, which is a statement
# about the matcher and not about the body (link_enabling_authority.py's own note;
# CONTEXT.md's Undetermined entry) and never a proposal for anything.
# link_enabling_authority.py is explicit that "a row that was pattern-matched and not read
# belongs in the review sheet, not here". So a kind derived from a proposal is a weaker
# claim than one derived from a reviewed
# authority, and a reader must be able to tell them apart in the file — otherwise the
# registry asserts a relationship on evidence it does not hold, which is what `manual: true`
# was retired for (ADR 0003: an assertion records that someone decided, never what decided
# it). ADR 0004 records this deviation and why it was taken.
#
#   proposed-enabling-authority   a candidate an automated matcher produced and NOBODY HAS
#                                 READ. Evidence that a body is separately constituted, at
#                                 the strength of a proposal — and the row upgrades visibly
#                                 when the candidate is reviewed.
#   reviewed-enabling-authority   the authority the registry row itself carries, written by
#                                 link_enabling_authority.py from its hand-reviewed table.
#                                 This is the basis ADR 0004 describes.
#   reviewed-absence              `enabling_authority` records `none: <reason>` — A HUMAN
#                                 LOOKED and found nothing separately constitutes this body.
#                                 That is ADR 0004's own description of *part of*, and unlike
#                                 the other two bases it decides the OTHER kind: nothing to
#                                 cite, so the relation carries no `authority` (#222 — the
#                                 second derivation #173 deliberately left untaken, because
#                                 the ABSENCE of a candidate is a statement about the matcher
#                                 and not about the body, and must never be confused with a
#                                 human having looked and found none).
#
# ALLOWLIST, NOT BLOCKLIST, as everywhere else in this module. A basis this registry has no
# meaning for is a provenance nobody can act on, and it is indistinguishable from a typo in
# one that matters.
PROPOSED_AUTHORITY = "proposed-enabling-authority"
REVIEWED_AUTHORITY = "reviewed-enabling-authority"
REVIEWED_ABSENCE = "reviewed-absence"
RELATION_BASES = (PROPOSED_AUTHORITY, REVIEWED_AUTHORITY, REVIEWED_ABSENCE)

# The keys one relation entry may carry. `authority` and `basis` are the OPTIONAL two, and
# they are optional in exactly one state: an `undetermined` relation, which records no
# decision and so has nothing to cite and nothing to have decided it. Every OTHER kind
# carries both — see `relation_fault()` for the rules and #173 for why a kind without a
# basis is worse than no kind at all.
RELATION_KEYS = ("target", "source", "kind", "basis", "authority")

# THE KEYS THE SCRAPE DOES NOT OWN, ON THE ENTRY THE SCRAPE REGENERATES. This is where a
# derived kind LIVES (#173), and the answer had to be worked out rather than assumed: the
# relation whose kind is being decided is the one the OAR INDEX states, and --refresh
# rewrites that entry from the index tree on every run, so a kind simply set on it is
# destroyed unread — #178's shape, in a field that can tell its two origins apart.
#
# It is not solved by putting the kind on a second entry, because a second entry is a second
# PLACEMENT: `source` says who places this body under that one, and no statute, DAS register
# or hand-written note places the Appraiser Certification and Licensure Board under DCBS —
# the rules index does. Recording one would attribute a placement to a source that never
# made it, to carry a fact about the kind.
#
# So `relations` merges per KEY as well as per ENTRY. The scrape owns the PLACEMENT
# (`target`, `source`); the derivation owns the DECISION, which is these three; and
# preserve_relations() carries the decision onto the rebuilt entry that names the same
# parent. `kind` is in the list even though the scrape writes it, because what the scrape
# writes is `undetermined` — the absence of a decision, which is exactly what a carried
# decision replaces.
DECISION_KEYS = ("kind", "basis", "authority")


def index_relation(target: str) -> dict:
    """The relation the OAR index states, as --refresh writes it.

    THE ONE PLACE A SCRAPE-DERIVED RELATION IS CONSTRUCTED, so the refresh and the survival
    simulation cannot write it two ways — a difference of one key between them would report
    itself as curation the refresh destroys, on every row, forever.

    The kind is `undetermined` and NOT a guess. The index files a body under a parent; that
    is a publisher's filing decision (ADR 0004 rejects inferring the relation from it), so
    the only honest kind for an entry from this source is the one that says nobody has
    established it yet."""
    return {"target": target, "source": OAR_INDEX, "kind": UNDETERMINED}


def relation_fault(entry):
    """What is wrong with one relation entry, or None when nothing is.

    THE ONE PLACE A RELATION'S GRAMMAR IS STATED, so the registry's contract
    (`relation-shape` in check_registry) and anything that writes the field are reading the
    same rules — a value cannot be legal where it is written and illegal in the file.

    ONE ANSWER, NOT A CLASSIFICATION. `classify_authority()` above returns the FORM it
    matched because two callers act on which one it was; nothing acts on a relation's source
    or kind beyond the rules below, which read them off the entry itself, and a second
    return value nobody reads is a claim about this function that its callers do not
    keep."""
    if not isinstance(entry, dict):
        return f"{entry!r} is not a mapping, so nothing about it could be read"
    # ALLOWLIST, as everywhere else in this module: a key nobody declared is one nothing can
    # say whether --refresh preserves, and it is indistinguishable from a typo in a key that
    # matters — `kimd` is a kind no reader will ever see.
    undeclared = sorted(set(entry) - set(RELATION_KEYS))
    if undeclared:
        return (f"relation {entry!r} carries key(s) {undeclared} that this registry "
                f"does not declare — a relation is {list(RELATION_KEYS)}, with `basis` and "
                "`authority` the optional two, and both required as soon as the kind is not "
                f"{UNDETERMINED!r}")
    target = entry.get("target")
    if not isinstance(target, str) or not target.strip():
        return (f"relation {entry!r} names no body — `target` is the registry slug "
                "of the body this one is under, and a relation without one records a "
                "hierarchy with one end")
    source = entry.get("source")
    if source not in RELATION_SOURCES:
        return (f"source {source!r} is not one this registry records — expected one "
                f"of {sorted(RELATION_SOURCES)}. The source is what says whether --refresh "
                "regenerates this entry or carries it across, so an entry without one "
                "recognisable is an entry the refresh cannot keep safe")
    kind = entry.get("kind")
    if kind not in RELATION_KINDS:
        return (f"kind {kind!r} is not one this registry records — expected one of "
                f"{sorted(RELATION_KINDS)}. {UNDETERMINED!r} is a value and not a missing "
                "one: it says the relation is real and which of ADR 0004's two kinds it is "
                "has not been established, where an absent kind says nothing and lets a "
                "consumer read it as either")
    # A KIND RECORDS WHAT DECIDED IT (#173). The registry holds kinds derived from two
    # different strengths of evidence — a PROPOSED enabling-authority candidate nobody has
    # read, and a REVIEWED authority — and one that does not say which it came from is
    # indistinguishable from the other, so a reader cannot tell a claim the registry stands
    # behind from a claim it is only entertaining, and a review that lands upgrades nothing
    # visible. `undetermined` is the one kind exempt, because it records no decision: there
    # is nothing for a basis to be the basis OF.
    if kind != UNDETERMINED and "basis" not in entry:
        return (f"relation {entry!r} records kind {kind!r} and does not say what decided it "
                f"— every kind but {UNDETERMINED!r} carries a `basis`, one of "
                f"{sorted(RELATION_BASES)}, because a kind derived from an unreviewed "
                "proposal and a kind derived from a reviewed authority are different claims "
                "and must not read alike")
    basis = entry.get("basis")
    if "basis" in entry and basis not in RELATION_BASES:
        return (f"basis {basis!r} is not one this registry records — expected one of "
                f"{sorted(RELATION_BASES)}. The basis is the STRENGTH of the claim: a kind "
                "derived from a candidate nobody has read is not the kind ADR 0004 derives "
                "from admitting evidence, and a reader who cannot tell them apart is reading "
                "a proposal as a finding")
    if "basis" in entry and kind == UNDETERMINED:
        return (f"relation {entry!r} records a basis and no kind — {UNDETERMINED!r} says "
                "nobody has established which of ADR 0004's two kinds this is, so there is "
                "no decision for a basis to be the basis of, and an entry carrying both says "
                "one was taken while declining to say which")
    # AN ADMINISTERED BODY IS ONE OREGON LAW SEPARATELY CONSTITUTES, so the relation says
    # what law. ADR 0004: "Recording that the commodity commissions are administered by the
    # Department of Agriculture is less useful than recording that ORS 576.066 is what makes
    # that true... A bare parent pointer states a hierarchy; a cited one states a claim about
    # Oregon law that a reader can check." Uncited, `administered_by` is that bare pointer
    # with a stronger word on it. `part_of` is deliberately NOT held to this — it records
    # that nothing separate constitutes the unit, so there is nothing separate to cite.
    # WHICH SECTION THE CITATION IS, AND WHICH IT IS NOT. ADR 0004's worked example holds
    # TWO sections, and they are different facts: ORS 576.062 establishes the commodity
    # commissions as state commissions — which is what makes the relation *administered by*
    # rather than *part of* — and ORS 576.066 is what the department's administration of them
    # actually runs on. A DERIVED relation cites the FIRST, because the first is the evidence
    # the kind rests on and the second is a section nobody in this repository has read; a
    # derivation that wrote it would be citing a claim about Oregon law on nobody's authority.
    # The `basis` is what tells the two apart, and it is why both derived bases are named for
    # an ENABLING authority: `proposed-enabling-authority` and `reviewed-enabling-authority`
    # each say the citation beside them is what CONSTITUTES the body. Recording the
    # administering section is a decision on a basis nothing here produces, which is a
    # deliberate widening of RELATION_BASES and `decision-not-ours` in
    # derive_relation_kinds.py.
    if kind == ADMINISTERED_BY and "authority" not in entry:
        return (f"relation {entry!r} records {ADMINISTERED_BY!r} and cites no authority — "
                "the kind says Oregon law constitutes this body separately from the one "
                "that administers it, and a reader has nowhere to go and check that")
    # AND THE OTHER HALF OF THE SAME CLAIM. CONTEXT.md: a *part of* unit "has no enabling
    # authority because there is nothing separate to enable", so there is no section that
    # makes the relation true either. A citation on one is either the PARENT's authority
    # written onto the child, or evidence that the unit IS separately constituted and the
    # kind beside it is wrong — and both are a claim a reader cannot reconcile with the word
    # next to it. Stated because CONTEXT.md and the ADR now say it, and a stated rule with
    # nothing enforcing it is a rule nobody has watched fail.
    if kind == PART_OF and "authority" in entry:
        return (f"relation {entry!r} records {PART_OF!r} and cites {entry['authority']!r} — "
                "*part of* says nothing separately constitutes this unit (ADR 0004), so "
                "nothing separate makes the relation true; a citation here is the parent's "
                "authority written onto the child, or a body the kind has got wrong")
    if "authority" in entry:
        # THE SAME FORMS THE BODY'S OWN AUTHORITY TAKES, minus the reviewed absence. An
        # `enabling_authority` needs `none: <reason>` because the key is absent on a body
        # nobody has reviewed and the two states must not read alike (CONTEXT.md); a
        # relation carries the key only when there is a citation to put in it, so a second
        # spelling of "there is none" would be one state written two ways.
        form, detail = classify_authority(entry["authority"])
        if form is None or form == "reviewed-none":
            return (f"relation {entry!r} cites no authority this registry can record "
                    "— expected an ORS citation (`ORS 576.066`), a constitutional article, "
                    "an executive order, or a session law; leave the key off where no "
                    "authority has been established for the relation"
                    + ("" if form else f" ({detail})"))
    return None


def relation_entries(org) -> list:
    """The relation entries on one row, as a list, for a reader that must not crash on a
    row whose `relations` is a string or a null. What is WRONG with such a value is
    `relation-shape`'s to report; every other reader needs to keep going and say its own
    piece about the row."""
    value = org.get(RELATION_KEY) if isinstance(org, dict) else None
    return value if isinstance(value, list) else []


# ------------------------------------------------------------------ walking the hierarchy
#
# WHERE HIERARCHY IS READ, AND THE ONE PLACE IT IS READ FROM. ADR 0004 replaces the parent
# pointer with a relation, and #174 removes the pointer — so `relations` is now the only
# statement this registry makes about which body another sits under. Two consumers walk it
# (`build_policy_gap.py` rolls sub-divisions up to their root agency, `build_agency_graph.py`
# groups a sub-unit with its department), and they walk it from HERE rather than each
# writing their own loop: a rollup that carries spending-relevant totals and a rollup that
# colours a node must not be able to disagree about where a body sits.
#
# A RELATION IS NOT A POINTER, AND THE DIFFERENCE IS THE WHOLE OF THIS SECTION. A pointer had
# one value; a body may hold SEVERAL relations, because the OAR index, DAS and statute may
# each place it under a different parent and ADR 0003 keeps that disagreement rather than
# reconciling it — "a body that DAS files under one parent and statute under another is a
# finding, and silently picking one hides it". So a walk that used to follow one value has to
# decide what to do with two, and the decision taken here is TO STOP AND SAY SO: a body its
# sources disagree about rolls up to itself, and the disagreement is REPORTED by the caller
# rather than resolved by whichever entry happened to be written first.
#
# Taking the first entry would have been the smaller diff and it is the one thing this may
# not do. In `build_policy_gap.py` the rollup carries rule counts that are read as a claim
# about an agency's regulatory footprint; attributing them to the department the OAR index
# files a body under, when statute places it elsewhere, is a wrong number rather than a
# crash — and nothing downstream would ever say which reading produced it.
#
# No committed row is in that state today: 81 children carry exactly one relation each and
# 108 carry none, so every walk below returns exactly what the retired pointer returned.
# That is the point — the decision is made now, in the open, rather than the first time two
# sources disagree.

# Why a walk stopped, so a caller can tell "this body is a root" from "this registry cannot
# say what this body's root is". A rollup that reported the two alike would publish a
# disagreement as a top-level agency (CONTEXT.md: "could not check" is never reported as
# "is not there").
AT_THE_TOP = "top"                  # nothing places this body under anything
SOURCES_DISAGREE = "sources-disagree"   # more than one body, and no basis here to choose
PLACED_IN_A_LOOP = "loop"           # the relations lead back to a body already walked
OFF_THE_REGISTRY = "off-registry"   # the walk left the rows this registry carries

Rollup = namedtuple("Rollup", "slug stopped")

# The one body a row is placed under, or the reason this registry cannot name one.
# `cannot_say` is None when the answer is definite — a parent, or genuinely nothing — and
# `SOURCES_DISAGREE` when the sources name more than one. The two are kept apart because a
# consumer that showed them alike would publish a disagreement as a body under nothing,
# which is "could not check" reported as "is not there" (CONTEXT.md).
Placement = namedtuple("Placement", "parent cannot_say")


def parent_targets(org) -> list:
    """Every DISTINCT body this row's relations place it under, in the order named.

    DISTINCT, because two entries naming ONE parent are two sources agreeing about the
    placement and disagreeing at most about its kind — which is a question about the kind
    and not about where the body sits. Two entries naming two parents are the disagreement
    ADR 0003 keeps, and the callers below act on that.

    Reads through `relation_entries()`, so a row whose `relations` is a string or a null
    yields nothing here instead of crashing; what is WRONG with such a row is
    `relation-shape`'s to report."""
    out = []
    for entry in relation_entries(org):
        if not isinstance(entry, dict):
            continue
        target = entry.get("target")
        if isinstance(target, str) and target and target not in out:
            out.append(target)
    return out


def sole_parent(org) -> Placement:
    """The ONE body this registry places `org` under, for a consumer that can hold only one.

    THE REFUSE-TO-PICK DECISION, WRITTEN ONCE. Both rollups need it — `build_agency_graph.py`
    groups a sub-unit with its department one hop up, `root_body()` below walks the same step
    repeatedly — and a second spelling of "what do I do with two parents" is a second answer
    that can differ from this one. It is the same reason the walk itself is here rather than
    in either consumer."""
    targets = parent_targets(org)
    if len(targets) == 1:
        return Placement(targets[0], None)
    return Placement(None, SOURCES_DISAGREE if targets else None)


def root_body(slug, by_slug) -> Rollup:
    """The body `slug` rolls up to, and WHY the walk stopped there.

    LOOP-SAFE, over data that is not guaranteed acyclic: `relation-resolves` states that a
    target names a body this registry carries, and nothing states that the targets form a
    tree. A walk that met a cycle would hang, and hanging is how a CI job reports nothing at
    all.

    A slug this registry does not carry rolls up to ITSELF, stopped `OFF_THE_REGISTRY`.
    `build_policy_gap.py` calls this with a directory name, which is not always a registry
    slug, and the honest answer for one is that this registry places it nowhere — not that
    it is a top-level agency."""
    seen = {slug}
    while True:
        org = by_slug.get(slug)
        if org is None:
            return Rollup(slug, OFF_THE_REGISTRY)
        step = sole_parent(org)
        if step.cannot_say:
            return Rollup(slug, step.cannot_say)
        if step.parent is None:
            return Rollup(slug, AT_THE_TOP)
        if step.parent in seen:
            return Rollup(slug, PLACED_IN_A_LOOP)
        seen.add(step.parent)
        slug = step.parent


# ------------------------------------------------------------- what an enabling authority is
#
# AN AUTHORITY, NOT A STATUTE (ADR 0003), "so constitutional offices have somewhere true to
# sit" and a body created by executive order is expressible. Three forms are accepted here
# and everything else is refused.
#
# ALLOWLIST, NOT BLOCKLIST — the same rule --check keeps for field names, for a sharper
# reason: the two get their errors backwards. An allowlist that is too narrow refuses a real
# authority in front of the person adding it, who then widens it deliberately. A blocklist
# that is too narrow accepts a wrong one and publishes it under provenance, and this
# repository has already paid for that shape once: `\bdept\.?\b` looked like it excluded
# nothing and silently matched no abbreviation it was written for, costing 9 of 76 matches
# before anyone found it. A citation is admitting evidence (ADR 0003), so a wrong one is a
# false statement about Oregon law, not a formatting slip.
AUTHORITY_FORMS = (
    # `ORS 674.305`. All 37,465 mirrored sections cite themselves in exactly this shape,
    # chapter letter included (`ORS 743A.052`). Whether the section EXISTS is a different
    # question, answered against the mirror by link_enabling_authority.py --check; this rule
    # says only that the value is spelled like a citation.
    #
    # ONE SECTION, DELIBERATELY. A subsection (`ORS 279A.140(1)`) and a range (`ORS 182.456
    # to 182.472`) are both refused today, because neither has ever been needed and both
    # change what the value MEANS: a range names a scheme a body operates under rather than
    # the section that created it, which is a different claim and a wider door. ADR 0004
    # already has eight boards "declared to operate as semi-independent state agencies under
    # ORS 182.456 to 182.472" and does not decide whether that is an enabling authority —
    # so widening this form is that decision, taken here, rather than a formatting tweak.
    ("ors", re.compile(r"ORS \d+[A-Z]?\.\d+")),
    # `Or. Const. Art. VI, sec. 1` — the Secretary of State's, and the spelling CONTEXT.md
    # and ADR 0005 both use. THIS FORM SAYS ONLY THAT THE VALUE IS SPELLED LIKE A CITATION,
    # which is all a registry-contract check can say: RESOLVING one against the mirrored
    # Constitution is `link_enabling_authority.py --check`'s, and it does it since #196 —
    # the same division of labour the `ors` form above has with the mirrored statutes, and
    # the reason `Or. Const. Art. XVII, sec. 99` passes here and fails there.
    #
    # THE ARTICLE HALF IS NOT WRITTEN HERE. It is `repo_lib.ORCONST_ARTICLE_TOKEN`, the same
    # declaration `citation_schemes.OR_CONST_C` interpolates, so this allowlist and the
    # citation scheme cannot answer "what is a constitutional article" differently. They did:
    # this form accepted `Art. VII (Amended)` where the scheme refused it, and refused
    # `Art. XI-A` where the scheme accepted it, and neither took `Art. XI-F(1)`, which is a
    # real article. `citation_schemes.article_form_disagreements()` is the gate, run by that
    # module's --selftest in CI (#195).
    #
    # STILL AN ALLOWLIST, and a wider one now by decision rather than by wildcard: the
    # parenthetical is not decoration (Oregon carries BOTH Article VII (Original) and Article
    # VII (Amended), and the judicial power sits in the amended one), and the lettered
    # articles XI-A through XI-Q are where the state's bonding authority lives.
    ("constitution", re.compile(rf"Or\. Const\. Art\. {ORCONST_ARTICLE_TOKEN}, "
                                rf"sec\. {ORCONST_SECTION_TOKEN}")),
    # `Executive Order 20-03`, the citation 525 of the 526 mirrored orders carry. One of them is
    # cited `Executive Order 12-special-session` and is deliberately OUTSIDE this form:
    # widening it to admit a free-text suffix would admit every typo too, and if a body ever
    # turns out to be created by that order, it is a decision to record here rather than a
    # surprise at the gate.
    ("executive-order", re.compile(r"Executive Order \d\d-\d\d")),
    # `Oregon Laws 1975, chapter 789` — an uncodified SESSION LAW (#211). A body created by
    # one has admitting evidence exactly as a body created by an ORS section does; before
    # this form existed the registry could only leave the row empty (reading as "nobody
    # looked") or cite a codified section that merely carries the body's OPERATION forward
    # without restating its creation. #211's OWN WORKED CASE is the Legislative Fiscal
    # Office (Oregon Laws 1959, chapter 70; codified ORS 173.410-173.465, none of which
    # creates the office — 173.410 defines "appointing authority", 173.465 creates the
    # FUND). This module's example is the Legislative Revenue Office instead, a second,
    # independently-supplied instance of the same shape: ORS 173.800-173.855 mirror
    # everything the 1975 act did to that office except the sentence that created it, and
    # citing 173.800 anyway would be the same wrong-section failure ADR 0004 already refuses
    # for `administered_by` (576.066 in place of 576.062).
    #
    # DERIVED FROM THE CORPUS, MEASURED, NOT FROM A STYLE GUIDE. Two independent measurements
    # anchor this shape, both against MIRRORED (verbatim) text, never curated prose:
    #   (1) `\d{4} c\.\d+` — the Legislative Counsel's own bracket citation of a session law
    #       inside a codified section's history note — occurs 294,366 times across 34,163
    #       mirrored ORS sections (23,213 distinct year/chapter pairs), establishing that a
    #       session law's identity IS its year and chapter number. `statutes/ors-173.800.md`
    #       itself carries `[1975 c.789 §1]` — the exact enactment behind this ticket's
    #       verified instance.
    #   (2) `Oregon Laws \d{4}, chapter \d+` — the SAME identity spelled out in prose — is not
    #       curator commentary; it is mirrored text. `rules/603/008/oar-603-008-0000.md`
    #       reads "...as authorized by Oregon Laws 2020, chapter 6" — a genuine, unspliced
    #       instance. RE-MEASURED 2026-08-30, because this comment's first cited example
    #       (`statutes/ors-174.535.md`) turned out to be a misread: that section's history
    #       note is an enumerated list actually written `chapter <n>, Oregon Laws <year>` —
    #       chapter FIRST — and every one of the 36 matches this form's own pattern finds
    #       there is a SPLICE across two adjacent list items, not a genuine instance of this
    #       spelling; the section demonstrates the reversed order, not this one. Corpus-wide
    #       (statutes, rules, constitution, executive-orders) the adopted spelling occurs 566
    #       times across 257 documents, 486 of them not immediately preceded by ", " (i.e.
    #       not a splice); the reversed order `chapter \d+, Oregon Laws \d{4}` occurs 4,115
    #       times across 1,844 documents — MORE common, not less. So this is NOT the
    #       majority spelling and the form does not claim to be: it is chosen the same way
    #       the `ors` form's own spelling is chosen — as the single spelling a reviewer must
    #       write, deliberately, out of several the corpus itself uses inconsistently, not
    #       because a frequency count backs it.
    #
    # NOT MIRRORED, so NOT RESOLVED. Unlike the three forms above, this corpus holds no
    # `session-laws/` — there is nothing on disk for a citation to name. This form says only
    # that the VALUE IS SPELLED LIKE a session-law citation; `link_enabling_authority.py`'s
    # `check()` reports every row in this form as "form-checked, not resolved" and counts it
    # SEPARATELY from the forms that resolve against a mirror, never folded into the same
    # "verified" a resolved ORS or constitutional citation earns (CONTEXT.md: "could not
    # check" is never reported as "is not there", and its mirror image — reporting a weaker
    # check as the stronger one — is just as false).
    #
    # MEASURE WHAT ELSE THE WIDER FORM ADMITS (this week's own lesson, applied to itself): the
    # pattern is deliberately narrow — full "Oregon Laws" (not "Or Laws"/"Or. Laws"), a comma,
    # lowercase "chapter" (not "Chapter"/"ch."/"ch"), one or more digits, nothing else. Every
    # one of the other 345 measured shapes — "Or Laws 1975, ch. 789", "Oregon Laws 1975
    # Chapter 789" (no comma), a bare "1975 c.789" bracket citation, "chapter 789" alone, a
    # year with no chapter, a chapter with no year — is REFUSED by this exact pattern
    # (`_proof_session_law_form_boundary` in this module's own selftest proves ten
    # of them failing, not merely asserted). ONE SECTION, DELIBERATELY, as the `ors` form's own
    # comment states it: no section suffix is admitted (`Or Laws 1961, ch 454 §19`, the real
    # citation quoted in #211 for a different body, oregon-military-department, does not
    # fullmatch this pattern), because a session law's identity for this field is the ACT,
    # and admitting a lettered or numbered subdivision of one is a decision to take later,
    # not a formatting tweak now.
    ("session-law", re.compile(r"Oregon Laws \d{4}, chapter \d+")),
)

# THE OTHER THING THE FIELD MAY SAY, and what makes the third state honest. A body that was
# reviewed and has no separate enabling authority records the REASON here — ADR 0004 names
# the common one: a `part_of` unit has nothing separate to enable. Written as a value rather
# than as a null, because a null and an absent key are read alike by every consumer, and the
# claims are opposite:
#
#   key absent                       nobody has looked yet
#   `ORS 576.062` / `Or. Const. …`   an authority is recorded
#   `none: <reason>`                 someone looked, and this is what they found
#
# So a falsy value means exactly one thing here — nobody has looked — and every other state
# is a non-empty string that says which it is. A bare null is refused by
# `enabling-authority-form`, because it is an assertion of absence with nobody behind it.
NO_AUTHORITY = "none: "

# A reason has to be a reason. The floor is not a judgment about quality — it is set to
# refuse the four non-reasons that would otherwise pass as review (`n/a`, `-`, `none`,
# `unknown`, the last of which is "nobody has looked" wearing the wrong label) while
# accepting a true short one: `none: Part of DAS` is eleven characters and states ADR 0004's
# case exactly.
MIN_NO_AUTHORITY_REASON = 8


def no_authority_value(reason) -> str:
    """`none: <reason>` as a registry row carries it, with the reason's whitespace collapsed.

    THE CONSTRUCTOR FOR THE FORM `classify_authority` PARSES, and it sits beside it so the
    two cannot drift. The reasons it is given are Python strings wrapped across source lines
    in link_enabling_authority.py, so their newlines and indentation are an artifact of how
    the table is READ rather than part of the finding — collapsing them here means the value
    written and the value compared are the same however the table is re-wrapped."""
    return NO_AUTHORITY + " ".join(str(reason or "").split())


def classify_authority(value):
    """(form, detail) for one `enabling_authority` value, or (None, what is wrong with it).

    `form` is one of AUTHORITY_FORMS' names, or `reviewed-none` when the value records a
    reviewed absence — in which case `detail` is the reason. THE ONE PLACE THE FIELD'S
    GRAMMAR IS STATED: the registry's contract (`enabling-authority-form` below) and the
    reviewed table that writes the field (link_enabling_authority.py) both read it here, so
    a value cannot be legal in the table and illegal in the file it is written to."""
    if not isinstance(value, str) or not value.strip():
        return None, ("is blank — an absent key is how this registry says nobody has looked "
                      "yet, so a blank value asserts a body has no enabling authority with "
                      f"nobody behind the claim. Record {NO_AUTHORITY!r} and the reason, or "
                      "leave the key off")
    if value.lower().startswith("none"):
        if not value.startswith(NO_AUTHORITY):
            return None, (f"{value!r} looks like a reviewed absence but is not written as "
                          f"{NO_AUTHORITY!r} followed by the reason")
        reason = value[len(NO_AUTHORITY):].strip()
        if len(reason) < MIN_NO_AUTHORITY_REASON:
            return None, (f"{value!r} records no authority and gives no reason — 'we looked "
                          "and there is none' is a decision, and a decision states its basis")
        return "reviewed-none", reason
    # AFTER the reviewed-absence branch, so `none: ` with an empty reason is reported as the
    # missing reason it is rather than as a stray trailing space.
    if value != value.strip():
        return None, f"{value!r} has leading or trailing whitespace"
    for form, pattern in AUTHORITY_FORMS:
        if pattern.fullmatch(value):
            return form, value
    return None, (f"{value!r} is not an authority this registry can record — expected an ORS "
                  "citation (`ORS 576.062`), a constitutional article (`Or. Const. Art. VI, "
                  "sec. 1`), an executive order (`Executive Order 20-03`), a session law "
                  "(`Oregon Laws 1975, chapter 789`), or "
                  f"{NO_AUTHORITY!r} and the reason there is none")


def authority_counts(orgs) -> dict:
    """The measurement `authority_census` formats -- the three states of `enabling_authority`,
    counted over registry ROWS (#306). ONE MEASUREMENT, TWO READERS: this dict is what
    `authority_census`'s sentence below reads, and it is what `stated_census.py` resolves a
    `census:agencies.authority_*` tag against, so the printed prose and the gated figure can
    never read two different counts of the same file.

    Counted from the file rather than from the reviewed table, for the reason the original
    docstring gave: the table says what SHOULD be recorded, and on any failure path the two
    disagree -- a census taken from the writer would report the intended state as the actual
    one."""
    values = [o["enabling_authority"] for o in orgs
              if isinstance(o, dict) and "enabling_authority" in o]
    none_recorded = sum(1 for v in values if classify_authority(v)[0] == "reviewed-none")
    return {"recorded": len(values) - none_recorded, "reviewed_none": none_recorded,
            "not_looked_at": len(orgs) - len(values), "total": len(orgs)}


def authority_census(orgs) -> str:
    """The three states of `enabling_authority`, counted over registry ROWS.

    ONE SENTENCE, TWO GATES, and counted from the file rather than from the reviewed table:
    the table says what SHOULD be recorded, and on any failure path the two disagree — a
    census that mixed them would report the intended state as the actual one. A summary that
    counted only the bodies carrying an authority would leave a reader to infer that the rest
    have none, which is the one reading this registry never permits.

    FORMATS `authority_counts()` (#306) rather than measuring anything itself, so this
    sentence and a `census:agencies.authority_*` tag elsewhere can never disagree about what
    the file holds -- see that function for the measurement.
    """
    c = authority_counts(orgs)
    return (f"{c['recorded']} recorded, {c['reviewed_none']} reviewed with none to "
            f"record, {c['not_looked_at']} of {c['total']} bodies not looked at yet")


def tally(counts, allowed) -> str:
    """`counts` rendered as "<n> <value>" for every value in `allowed`, THE ZEROES INCLUDED,
    followed by any value the allowlist does not name.

    ONE IMPLEMENTATION OF "NAME THE ZEROES", because it is a rule this repository keeps and
    not a formatting choice: a count that appears only when it is non-zero cannot be told
    apart from a count nobody asked for, and a census printing only the values it happened to
    find leaves a reader to infer that the rest are absent (CONTEXT.md). Two censuses spelling
    that rule separately is two places for one of them to stop keeping it.

    SORTED BY `str`, BECAUSE None IS ONE OF THE VALUES THAT REACHES HERE. A relation missing
    its `kind` counts as None, and so does a row missing its `name_basis` — both are contract
    violations these censuses promise to NAME rather than absorb, and sorting them against the
    strings beside them raises TypeError, which would take down the one report that was
    supposed to surface them.
    """
    named = list(allowed) + sorted((k for k in counts if k not in allowed), key=str)
    return ", ".join(f"{counts.get(k, 0)} {k}" for k in named)


def chaptered_rows(orgs) -> int:
    """How many of the registry's rows carry `oar_chapter` — the chapter pages a full
    --refresh fetches over the network. THE ONE PLACE THIS IS COUNTED (code review of
    #279): `chapter_census()` (the figure --check PRINTS) and `check_registry()`'s
    `chapter-page-count-current` rule (the figure it ENFORCES) each wrote this same
    `sum(1 for o in orgs if o.get("oar_chapter"))` out separately, in the one change whose
    entire subject was two copies of one fact drifting apart (189 vs 170, #279) — the fix
    itself shipped a second copy of the expression that counts it. Extracted so the two
    call sites can never again disagree about what counts as a fetched chapter."""
    return sum(1 for o in orgs if isinstance(o, dict) and o.get("oar_chapter"))


def chapter_counts(orgs) -> dict:
    """The measurement `chapter_census` formats (#306) -- see `authority_counts` for why a
    census is split into a dict a `census:` tag can resolve and a sentence that formats it
    rather than measuring twice."""
    chaptered = chaptered_rows(orgs)
    return {"chaptered": chaptered, "total": len(orgs), "chapterless": len(orgs) - chaptered}


def chapter_census(orgs) -> str:
    """How many of the registry's rows carry `oar_chapter` — the chapter pages a full
    --refresh fetches over the network — counted over rows and printed by --check on every
    run, the same reason `authority_census` is (#279).

    THE FIGURE #279 FOUND STATED IN FOUR PLACES, TWO OF THEM WRONG THE SAME WAY. 189 is
    `len(orgs)`, the registry's total row count; a body is in this registry because it
    EXISTS, not because it issues rules (CONTEXT.md: Agency registry), so a row can hold no
    `oar_chapter` and never be fetched. Two scripts explaining --refresh's network cost had
    both drifted to quoting 189 for a quantity that is actually smaller. This is that
    quantity, computed from the file on every run rather than pinned into either script's
    prose to go stale the next time a row is added or a chapter goes chapterless.

    FORMATS `chapter_counts()` (#306) rather than measuring anything itself."""
    c = chapter_counts(orgs)
    return (f"{c['chaptered']} of {c['total']} row(s) carry oar_chapter "
            f"({c['chapterless']} chapterless)")


def chapterless_source_url_census(orgs) -> tuple[int, int]:
    """(chapterless rows with no `source_url`, chapterless rows total) — the pair
    `REGISTRY_NOTE` states in prose as "null on N of the M chapterless rows" (code review
    of #281). THE ONE PLACE THIS IS COUNTED, the same reason `chaptered_rows()` is (#279):
    `check_registry()`'s `note-numbers-current` rule is the only reader, so there is
    nowhere else for this and the note's own claim to disagree about what counts."""
    chapterless = [o for o in orgs if isinstance(o, dict) and not o.get("oar_chapter")]
    null_source = sum(1 for o in chapterless if not o.get("source_url"))
    return null_source, len(chapterless)


def name_counts(orgs) -> dict:
    """The measurement `name_census` formats (#306) -- every row's `name_basis`, tallied,
    with the row total alongside it under `"total"`. `"total"` is NOT itself a `name_basis`
    value -- a caller re-deriving `name_census`'s tally must exclude it, the way that
    function does below, or it prints as a bogus fourth basis nobody's row actually holds."""
    counts = Counter(o.get(NAME_BASIS_KEY) for o in orgs if isinstance(o, dict))
    counts["total"] = len(orgs)
    return dict(counts)


def name_census(orgs) -> str:
    """What each row's `name` IS, counted over rows — printed by --check on every run.

    THE ONE NUMBER THIS TICKET IS ABOUT (#168), AND IT IS NOT THE BIG ONE. ADR 0003 makes
    `name` the statutory name, and most rows do not have one established: they hold the OAR
    chapter title they were scraped with, and say so. A census reporting only the rows whose
    statutory name HAS been established would leave a reader to infer that the rest are the
    same kind of value — which is the substitution this field exists to prevent, made by the
    report about the field.

    EVERY BASIS IS NAMED, THE ZEROES INCLUDED, for the reason `relation_census` names its
    kinds: a count that appears only when it is non-zero cannot be told apart from a count
    nobody asked for. Counted from the FILE rather than from the table that writes it, for
    the reason `authority_census` is — on any failure path the two disagree, and a census
    taken from the writer reports the intended state as the actual one.

    FORMATS `name_counts()` (#306) rather than measuring anything itself.
    """
    counts = name_counts(orgs)
    total = counts["total"]
    tallyable = {k: v for k, v in counts.items() if k != "total"}
    return f"{tally(tallyable, NAME_BASES)}; {total} row(s)"


def placement_witnesses(orgs) -> str:
    """How many placements this file states TWICE, and how many it states once — printed by
    --check on every run.

    WHAT #174 GAVE UP, SAID OUT LOUD. `parent_slug` held a second copy of every placement,
    so a relation deleted by hand was caught by a rule comparing the two. There is one copy
    now, which is the point of the ticket — and what is left of a second witness is
    `parent_chapter`, the parent's own OAR chapter, which `parent-agrees` states against the
    body the relations name. That witness is silent for a child whose parent holds NO
    chapter: `parent_chapter` is null there for a body under nothing and for a body whose
    entry was deleted alike, and no rule in this file can tell them apart.

    So the number is REPORTED rather than left to be discovered. It is not zero and it is not
    a bug: an `oar-index` entry is SCRAPED, so a hand-deletion is rebuilt by the next
    --refresh from the index tree. What a reader needs to know is how much of the file's
    hierarchy rests on a single unwitnessed statement, and that is this line (CONTEXT.md:
    "could not check" is never reported as "is not there")."""
    placed = [o for o in orgs if parent_targets(o)]
    witnessed = [o for o in placed if o.get("parent_chapter") is not None]
    return (f"{len(placed)} body placement(s), {len(witnessed)} of them witnessed a second "
            f"time by parent_chapter; {len(placed) - len(witnessed)} rest on the relation "
            "alone, because the parent holds no OAR chapter to witness them with — a "
            "deleted entry there is rebuilt by the next --refresh and reported by nothing "
            "in this file")


def relation_counts(orgs) -> dict:
    """The measurement `relation_census` formats (#306) -- everything that sentence reads,
    flattened into one dict a `census:agencies.relation_*` tag can resolve a single key out
    of. `kinds`, `sources` and `basis` are each Counters over what the registry's relation
    entries actually hold (unrecognised values included, exactly as `relation_census` names
    them rather than absorbing them) -- flattened here with a `kind__` / `source__` /
    `basis__` prefix so the three vocabularies, which are not disjoint (`registry` is both a
    `source` value and could in principle collide with a `kind` or `basis` spelling), can
    never be read as one namespace by a caller pulling a single key out of this dict."""
    entries = [e for o in orgs for e in relation_entries(o) if isinstance(e, dict)]
    held_by = sum(1 for o in orgs if relation_entries(o))
    kinds = Counter(e.get("kind") for e in entries)
    sources = Counter(e.get("source") for e in entries)
    bases = Counter(e.get("basis") for e in entries
                    if e.get("kind") not in (None, UNDETERMINED))
    d = {"total_relations": len(entries), "held_by": held_by, "total_orgs": len(orgs),
         "decided_total": sum(bases.values())}
    d.update({f"kind__{k}": v for k, v in kinds.items()})
    d.update({f"source__{k}": v for k, v in sources.items()})
    d.update({f"basis__{k}": v for k, v in bases.items()})
    return d


def relation_census(orgs) -> str:
    """What the registry's relations say, counted over ENTRIES and over the bodies holding
    them, with every kind and every source named — the zeroes included.

    THE KIND IS REPORTED, NEVER DEFAULTED (#171). Every relation the registry carries today
    records `undetermined`, because deciding between ADR 0004's two kinds needs evidence
    that arrives with #173, and a census printing only the kinds it happened to find would
    leave a reader to infer that the rest are absent. Naming a kind with a count of zero
    says the registry was asked and holds none, which is a different statement and the only
    one this repository permits (CONTEXT.md).

    Counted from the FILE rather than from anything that writes it, for the reason
    `authority_census` is: on any failure path the two disagree, and a census taken from the
    writer would report the intended state as the actual one.

    FORMATS `relation_counts()` (#306) rather than measuring anything itself -- unpacking its
    three prefixed vocabularies back into the Counters `tally()` expects.
    """
    d = relation_counts(orgs)
    # Unrecognised values are named too, after the allowlists — `relation-shape` refuses
    # them, and a census that silently left them out of its own total would be the one
    # reader that agreed with the file about how many relations it holds while disagreeing
    # about what they say.
    # SORTED BY `str`, BECAUSE None IS ONE OF THE VALUES THAT REACHES HERE. A relation
    # missing its `kind` counts as None, and so does a decided kind with no `basis` — both
    # are `relation-shape` failures, and both are values this census promises to NAME rather
    # than absorb. Sorting them against the strings beside them raises TypeError, which would
    # take down the one report that was supposed to surface them: --apply prints the census
    # before it reports anything, so the crash would land in front of the diagnosis.
    kinds = {k[len("kind__"):]: v for k, v in d.items() if k.startswith("kind__")}
    sources = {k[len("source__"):]: v for k, v in d.items() if k.startswith("source__")}
    # WHAT THE DECIDED KINDS REST ON, COUNTED APART FROM HOW MANY THERE ARE (#173). The
    # registry holds kinds derived from a PROPOSED enabling-authority candidate nobody has
    # read beside kinds derived from a REVIEWED authority, and those are not the same claim:
    # ADR 0004 derives the kind from admitting evidence, and a proposal is not evidence. A
    # census reporting only the kind tally would present the weaker population as the
    # stronger one on every run.
    bases = {k[len("basis__"):]: v for k, v in d.items() if k.startswith("basis__")}
    return (f"{d['total_relations']} relation(s) on {d['held_by']} of {d['total_orgs']} "
            f"bodies; kinds: {tally(kinds, RELATION_KINDS)}; sources: "
            f"{tally(sources, RELATION_SOURCES)}; the {d['decided_total']} decided kind(s) "
            f"rest on: {tally(bases, RELATION_BASES)}")


def keys_in_order(origin, fields=None):
    """The fields of one ORIGIN, in the order `fields` (default FIELDS) declares them.

    THE ONE PLACE AN ORDERED VIEW OF FIELDS IS FILTERED (#182 review). CURATED_KEYS,
    SCRAPED_KEYS, MERGED_KEYS and PER_ROW_KEYS below, and `check_registry()`'s own read of
    `fields`, all used to write `frozenset(k for k, f in fields.items() if f.origin == X)`
    by hand, once per origin — the same shape as a hand-kept second copy of FIELDS, and the
    kind of duplication this table exists to avoid everywhere else. Only CURATED_KEYS's order
    matters TODAY (`preserve_curated()` is the only one of the four that APPENDS a key a
    rebuilt row is missing, so it is the only one whose order changes a diff) — but the other
    three are ordered the same cheap way rather than left as the one-off comprehension a
    future append-style preserve function would have had to invent again from nothing."""
    fields = FIELDS if fields is None else fields
    return tuple(k for k, f in fields.items() if f.origin == origin)


def curated_keys_in_order(fields=None):
    """The curated fields, in the order `fields` (default FIELDS) declares them.

    WHY ORDER IS A SEPARATE QUESTION FROM CURATED_KEYS BELOW (#182). `CURATED_KEYS` answers
    "is this key curated" and a `frozenset` is the right shape for that — membership, not
    sequence. `preserve_curated()` also has to answer "in what order do I APPEND the curated
    keys a rebuilt row is missing", because `yaml.safe_dump(sort_keys=False)` writes a row in
    exactly the Python dict order its keys were inserted in, and a `frozenset`'s iteration
    order is PYTHONHASHSEED-dependent — stable within one process, different across the next
    `--refresh` run, so a curated field's line moves in the diff for no reason every time.
    No run of `--refresh` has actually produced THREE different files to diff against each
    other for hashseed-driven reordering — #275 is why, until #275's own fix landed in the
    same commit that corrected this sentence: every `--refresh` aborted before writing
    anything, for a reason unrelated to key order, so no such run ever existed to compare. A
    single live `--refresh` now completes (timing and count recorded once, at
    `assert_scrape_declared()`'s own docstring, rather than restated here), but one run says
    nothing about hashseed variance ACROSS runs — that is still only demonstrated the way it
    always was, below.
    The evidence is `simulate_refresh()`, the same `preserve_curated()` a real --refresh
    calls: five subprocesses, one fresh PYTHONHASHSEED apiece, simulating a refresh of
    department-of-administrative-services against unchanged committed data, landed
    `enabling_authority`, `aliases`, `budget_agency_code` and `das_agency_number` in five
    different relative orders (recorded in the #182 commit message) before this fix, and
    FIELDS's own order every time after it —
    `_proof_curated_keys_survive_in_declaration_order()` below asserts that across real
    subprocesses rather than in one interpreter.
    Restating an order by hand (alphabetical, e.g.) would be a second opinion about the
    file's shape that nothing enforces; FIELDS is already an ordered mapping and the one
    place a field is declared, so this is a VIEW of it filtered to CURATED, not a new rule.

    `fields` is a parameter for the same reason it is on `check_registry()`: so a
    differently-declared table orders its own curated keys rather than the module's.

    WHERE ELSE THIS WAS CHECKED (#182's own acceptance criterion, so this is where a reader
    looks rather than a commit message nobody greps): CURATED_KEYS is not the only frozenset
    a rebuilt row is iterated over. SCRAPED_KEYS, MERGED_KEYS and PER_ROW_KEYS are all three
    read inside `assert_scrape_declared()` (#275: PER_ROW_KEYS did not join the other two
    until then, and a real --refresh could not get past that function as a result), and
    MERGED_KEYS and PER_ROW_KEYS are also iterated inside `preserve_relations()` and
    `preserve_name()` respectively — but neither of those two
    loops APPENDS a key the rebuilt row does not already carry, because `scraped_entry()`
    always writes `relations` and the `name`/`name_basis` pair. Only a loop that can add a
    missing key can move a line, which is what `preserve_curated()` alone was doing before
    this fix. That safety is a property of `scraped_entry()`, not of those two loops: a
    future `scraped_entry()` that stops writing one of those keys reintroduces this bug
    silently, with nothing here to catch it."""
    return keys_in_order(CURATED, fields)


CURATED_KEYS = frozenset(curated_keys_in_order())
SCRAPED_KEYS = frozenset(keys_in_order(SCRAPED))
# The fields --refresh writes even though it does not own all of what they hold. Derived
# from the same table for the same reason CURATED_KEYS is: a hand-kept second list of
# "the fields that merge" is the list somebody forgets to add to.
MERGED_KEYS = frozenset(keys_in_order(MERGED))
# The fields whose origin is written on the ROW rather than on the field. Derived from the
# same table for the same reason the three sets above are, and read by `preserve_name()`.
PER_ROW_KEYS = frozenset(keys_in_order(PER_ROW))
# The one field the scrape may never write under any name (#275 review): `manual: true` is
# asserted only by a human, via `preserve_manual()`, which runs AFTER the scrape. Derived
# for the same reason the four sets above are, and read only by `assert_scrape_declared()`.
MANUAL_FLAG_KEYS = frozenset(keys_in_order(MANUAL_FLAG))
UA = "executive-regulatory-frameworks (+https://github.com/OregonAI/executive-regulatory-frameworks)"

ENTRY_RE = re.compile(
    r'<dt class="col-sm-2">[^<]*</dt>\s*'
    r'<dd class="col-sm-10">(?:<a href="/rules/oar_chapter_(\d+[a-z]?)">(.*?)</a>'
    r'|([^<]+?)(?=<div class="card))', re.S)
CARD_RE = re.compile(r'<div class="card[^"]*quasi-sub-chapter"')
TITLE_RE = re.compile(r"<title>OAR Chapter \d+[a-zA-Z]? \W (.*?)</title>", re.S)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def scraped_entry(*, oar_name, oar_chapter, raw_index_name, source_url, note=None):
    """One registry row as --refresh builds it from oregon.public.law.

    THE ONLY PLACE THE SCRAPE'S OWN FIELDS ARE WRITTEN, which is what lets --check
    simulate a refresh honestly: the simulation calls this constructor instead of copying
    the committed row's keys, so it cannot credit the scrape with producing a field the
    scrape never writes. Crediting it wrongly is the exact failure the simulation exists to
    catch — a curated field mislabelled `SCRAPED` would then look preserved while a real
    --refresh silently dropped it.

    THE ARGUMENT IS THE OAR NAME, AND SAYING SO IS #168's HALF OF ADR 0003. The chapter page
    title is the only name the scrape can see, and it is the OAR NAME (CONTEXT.md) — what the
    rules index calls this body, and nothing else. It used to arrive here as `name`, back when
    `name` held the OAR title too; `name` is the STATUTORY name now, and a parameter still
    called that would have the scrape appear to produce one.

    IT STILL WRITES `name`, and the row says on what basis. A body the scrape has just
    discovered has no established statutory name — nobody has read its enabling authority,
    and it may not have one recorded at all — so `name` starts as the OAR title under
    `name_basis: unverified-oar-title`, which is the true statement about it. Writing the
    title alone and leaving `name` off would produce a row --check refuses (`required-field`)
    for a body that is perfectly real; writing it and claiming it as the statutory name would
    be the false statement about Oregon law this whole field exists to prevent. An
    established name never reaches here: `preserve_name()` carries it across, and the row
    the scrape rebuilt is discarded for that key.

    `parent_chapter` is written null here and filled by the caller once the index tree is
    known; it is a key of a scraped row either way. `relations` is written EMPTY for the
    same reason and filled by `set_index_relations()` from the same tree: the entries the
    scrape derives are regenerated on every refresh, so the constructor that stands for
    "what the scrape produces" has to write the key — `scraped-field` in check_registry()
    checks this column against this function, and a MERGED field that the constructor did
    not write would be a field the refresh silently drops in full."""
    entry = {"slug": slugify(oar_name), "name": oar_name,
             NAME_BASIS_KEY: UNVERIFIED_OAR_TITLE, "oar_name": oar_name,
             "oar_chapter": oar_chapter,
             "raw_index_name": raw_index_name, "source_url": source_url}
    if note:
        entry["note"] = note
    entry["parent_chapter"] = None
    entry[RELATION_KEY] = []
    return entry


def set_index_relations(orgs, index_parents) -> None:
    """Write each row's `oar-index` relation from the parent the index tree gave it.

    `index_parents` is {slug: the slug the rules index files this body under}, read from the
    tree by --refresh and replayed from the committed entries by the survival simulation. It
    is a PARAMETER rather than something read off the row, and that is the whole of what
    #174 changed here: the placement used to be read back off `parent_slug`, and there is no
    longer a second copy of it anywhere on the row to read.

    IN PLACE and over the SCRAPE'S OWN OUTPUT ONLY. It runs before anything is preserved, so
    it cannot overwrite a curated entry — the rows it touches are the ones the scrape has
    just rebuilt, and the merge appends to what it leaves behind. A manual row is not among
    them, which is why every entry this writes is the index's. A row the index files under
    nothing gets an EMPTY list rather than no key: `[]` says this registry places the body
    under no other, and an absent key would say nobody asked (CONTEXT.md)."""
    for org in orgs:
        parent = index_parents.get(org["slug"])
        org[RELATION_KEY] = [index_relation(parent)] if parent else []


def write_das_agency_number(row: dict, number) -> None:
    """Write `number` onto `row` under `das_agency_number`, the field of record.

    THE ONE PLACE THE NUMBER IS WRITTEN, so nothing can put it under a second, hand-typed
    key. Before #177 this wrote a second copy under the deprecated `budget_agency_code`
    (ADR 0003's expand half, #175); the field of record is the only key now, and
    `budget-agency-code-retired` in check_registry() is what refuses the old one if
    anything ever writes it again.

    IN PLACE, because the row object is shared. link_budget_codes.py holds the same dict in
    its slug index and in the organizations list, and returning a new row would update one
    of those and leave the other holding the old one.

    A plain assignment: Python dicts keep an existing key's position on reassignment and
    only append on first insertion, so a row that already carried a number keeps its
    position and a row that carried none gets it appended at the end, same as any other
    first write of a curated field. Before #177, when this also wrote a second copy under
    the deprecated `budget_agency_code` key, the rebuild-and-reinsert here kept the two
    keys adjacent; with `das_agency_number` the only key left to write, that reason is
    gone and the rebuild is exactly equivalent to this assignment.
    """
    row["das_agency_number"] = number


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_index(raw: str):
    """[(chapter|None, index_name, parent_top_index|None)] from the /rules tree, plus
    the list of top entries. Sub-unit entries live inside a parent's <dd> in a
    quasi-sub-chapter card, whose single <dl> ends at the first </dl> after the card
    opens. Four parents (e.g. Dept. of Consumer & Business Services, Secretary of
    State) have NO chapter of their own — they appear as a bare-text <dd> (empty
    <dt>, no link) that exists only to carry a card; those become chapterless
    name-only groups."""
    card_spans = []
    for m in CARD_RE.finditer(raw):
        end = raw.index("</dl>", m.start())
        card_spans.append((m.start(), end))

    entries = []   # [chapter|None, index_name, parent_top_index|None]
    tops = []      # (pos, entry_index) of top-level entries
    for m in ENTRY_RE.finditer(raw):
        pos = m.start()
        ch = m.group(1)  # None for a chapterless bare-text group
        name = re.sub(r"\s+", " ", unescape(m.group(2) or m.group(3) or "")).strip()
        if not name:
            continue
        span = next(((s, e) for s, e in card_spans if s <= pos <= e), None)
        if span is None:
            tops.append((pos, len(entries)))
            entries.append([ch, name, None])
        else:
            parent_idx = next((ei for p, ei in reversed(tops) if p < span[0]), None)
            entries.append([ch, name, parent_idx])
    return entries


def assert_scrape_declared(orgs):
    """Stop a refresh that produced a field FIELDS does not declare SCRAPED, MERGED or
    PER_ROW.

    THE DECLARATION IS BINDING ON THE SCRAPE, and this is the half --check cannot reach: it
    reads committed data and never runs a scrape, so it can only ask whether the rows it can
    see would survive. A field added to the scrape without being declared would make that
    simulation wrong in the direction that hides losses — the field would be compared as if
    curated and fail, or worse, be assumed rewritten — so the refresh that would introduce it
    stops here instead, before anything is written.

    #275: PER_ROW_KEYS belongs in the exclusion beside SCRAPED_KEYS and MERGED_KEYS, and
    was not. `scraped_entry()` writes `name`/`name_basis` on EVERY row it builds — PER_ROW
    is what lets a name a human established survive `preserve_name()` untouched while a
    still-unverified OAR title gets rebuilt, but the row's KEYS are as much the scrape's own
    output as anything SCRAPED or MERGED names. This function only asks "did the scrape
    produce a field FIELDS does not know about at all" — whether a PER_ROW field's rebuilt
    VALUE then survives is a separate question, `preserve_name()`'s alone to answer, later.
    Without this, `{'name', 'name_basis'}` came back "undeclared" on every row a real scrape
    ever built, so a real `--refresh` died here before writing anything, every invocation —
    reproduced directly below against the exact row `scraped_entry()` builds, and matching
    #275's own quoted `--refresh` transcript verbatim ("the scrape produced undeclared
    field(s) ['name', 'name_basis']"; the ticket states no timing for that crash, and none is
    claimed here — a number nobody measured is worse than no number). Fixed and verified
    LIVE, not only against the fixture below: `--refresh` against oregon.public.law completed
    end to end, 189 rows in `organizations`, 106.48s wall-clock (2026-08-28, this branch); the
    committed registry was restored unchanged afterward, since a network-dependent refresh's
    output is not this ticket's data to commit.

    THE EXCLUSION IS DERIVED, NOT A LIST (#275 review). It used to name SCRAPED_KEYS,
    MERGED_KEYS and PER_ROW_KEYS by hand — three views of FIELDS restated at the one call
    site that needed their union, the same shape #182 fixed for `preserve_curated()`'s key
    order and this function itself went stale under, once already, the day PER_ROW joined
    the other two origins and this list did not. `admitted` is now `set(FIELDS) -
    CURATED_KEYS - MANUAL_FLAG_KEYS` — every field FIELDS declares, except the two origins
    `scraped_entry()` may never produce. A field the scrape starts writing under any OTHER
    origin is caught by being declared, not by this list remembering to grow: there is no
    longer a per-origin name here for a future origin to be missing from.

    CURATED_KEYS and MANUAL_FLAG_KEYS are the two that stay excluded, and that is a real,
    checkable claim rather than an assumption: `scraped_entry()` never writes a curated field
    or `manual: true` — both reach a row only later, via
    `preserve_curated()`/`preserve_manual()`, which both run AFTER this guard. So a curated
    or manual key on a freshly-scraped `orgs` here is a real bug — the scrape asserting data
    only a human may assert — and admitting those two origins as well would make this guard
    permanently silent on exactly the mistake it exists to catch."""
    admitted = set(FIELDS) - CURATED_KEYS - MANUAL_FLAG_KEYS
    undeclared = {k for o in orgs for k in o} - admitted
    if undeclared:
        unknown = sorted(undeclared - set(FIELDS))
        stray = sorted(undeclared & (CURATED_KEYS | MANUAL_FLAG_KEYS))
        parts = []
        if unknown:
            parts.append(f"{unknown} not declared in FIELDS at all — add them (origin "
                         "SCRAPED, MERGED, or PER_ROW, whichever the scrape actually "
                         "writes)")
        if stray:
            parts.append(f"{stray} ARE declared in FIELDS, as CURATED or MANUAL_FLAG — "
                         "scraped_entry() is not supposed to write those; the bug is "
                         "likely in the scrape, not a missing FIELDS declaration")
        sys.exit("the scrape produced undeclared field(s): " + "; ".join(parts) +
                 " — nothing was written")


def preserve_manual(prev_orgs, orgs, by_slug):
    """Carry over manually-added entries (chapters OARD serves but the mirror's index
    omits, e.g. 419, 950 — discovered via renumbering redirects during the mass import).
    A refresh must never drop them; a collision with a newly-indexed chapter means the
    mirror caught up — then the manual flag should be removed by hand after comparing
    names. Mutates `orgs` and `by_slug`, which is what --refresh needs and what --check
    replays."""
    # THE SCRAPED CHAPTERS, COMPUTED ONCE. This set used to be rebuilt inside the loop
    # against `orgs`, which the loop is simultaneously appending to -- so the first
    # preserved entry with `oar_chapter: null` put None INTO the set that the next one
    # was tested against, and every null-chapter manual entry after it looked like a
    # collision with a chapter the mirror had caught up on.
    #
    # 13 of the 15 manual entries THEN IN THE REGISTRY carried a null chapter -- 17 carry
    # the flag today -- because that is what a body with no OAR chapter looks like: the
    # Governor's office, the Legislative Assembly, district attorneys. Simulated against
    # the registry as it stood, a --refresh kept 2
    # and dropped 13, among them office-of-the-governor, legislative-fiscal-officer and
    # district-attorneys-and-deputies. Six of those are slugs oregon-kpm's agency
    # crosswalk resolves into today.
    #
    # It would have failed the way preserve_curated() below warns about: silently. The
    # registry still parses, every remaining slug still resolves, and the loss only
    # surfaces as a cross-corpus join that quietly stopped matching. `--check` now replays
    # this function against the committed registry on every PR, so the next regression of
    # this class is a red build rather than a silent one.
    # A NULL CHAPTER CANNOT COLLIDE, and that is the second half of the bug. The guard
    # asks "has the mirror caught up on this chapter?", which is meaningless for an entry
    # that never had one -- and four SCRAPED bodies legitimately carry
    # `oar_chapter: null` (Secretary of State, DCBS, the Military Department, the Mental
    # Health Regulatory Agency, all parents whose rules live in their sub-units). So None
    # was always in this set, and every null-chapter manual entry was discarded no matter
    # what order they came in. Such an entry can only be superseded by SLUG, which the
    # first clause already handles.
    scraped_chapters = {x["oar_chapter"] for x in orgs if x.get("oar_chapter")}
    for o in prev_orgs:
        if o.get("manual") and o["slug"] not in by_slug \
                and (not o.get("oar_chapter")
                     or o["oar_chapter"] not in scraped_chapters):
            orgs.append(o)
            by_slug[o["slug"]] = o


def preserve_curated(prev_orgs, by_slug, curated_keys=None):
    """Copy CURATED_KEYS from the previous registry onto the rows the scrape rebuilt.

    Every field --refresh writes is derived fresh from oregon.public.law, so a key that
    is not scraped — and `das_agency_number` is not; it is a hand-reviewed mapping to the
    DAS agency numbers oregon-budget reports spending against — would be silently dropped on
    the next --refresh. Silently is the problem: the file would still parse, every slug would
    still resolve, and the loss would only surface as a cross-corpus join that quietly
    stopped matching anything.

    `curated_keys` defaults to `curated_keys_in_order()`, NOT `CURATED_KEYS` — the default
    has to be the ORDERED view, because this loop appends a key the whole time it iterates,
    and the order it iterates in is the order a newly-carried key lands in the rebuilt row
    (#182). A caller may still pass an unordered set; the guarantee is only that the default
    this function (and `simulate_refresh`) uses is deterministic."""
    curated_keys = curated_keys_in_order() if curated_keys is None else curated_keys
    for o in prev_orgs:
        current = by_slug.get(o["slug"])
        if not current:
            continue
        for key in curated_keys:
            if key in o and key not in current:
                current[key] = o[key]


def carry_decision(previous: dict, rebuilt: list) -> None:
    """Copy the DECISION (DECISION_KEYS) off a relation entry the refresh has just
    regenerated onto its rebuilt counterpart. Mutates the rebuilt entry.

    THE HALF OF A REGENERATED ENTRY THE SCRAPE DOES NOT OWN. An `oar-index` entry is
    rewritten from the index tree on every refresh, which is what lets an upstream re-filing
    reach the registry — and the kind on it was decided by evidence the index never states
    (#173, ADR 0004). Carrying the whole entry would freeze the placement; carrying none of
    it destroys the kind; so the placement is rebuilt and the decision is carried.

    THE PARENT MUST STILL MATCH. A decision records that THIS body, placed under THAT one, is
    administered rather than composed. If the index has re-filed the body, the rebuilt entry
    names a different parent, no counterpart matches, and the decision is dropped — which
    `derive_relation_kinds.py --check` then reports as a registry that disagrees with the
    derivation, a human's cue to re-run it. The alternative is a kind silently transferred to
    a relation nobody derived it for.

    An entry recording no decision carries nothing, so `undetermined` never overwrites
    anything and this cannot un-decide a kind."""
    if previous.get("kind") in (None, UNDETERMINED):
        return
    for entry in rebuilt:
        if (isinstance(entry, dict) and entry.get("source") == previous.get("source")
                and entry.get("target") == previous.get("target")):
            for key in DECISION_KEYS:
                if key in previous:
                    entry[key] = previous[key]
            return


def preserve_relations(prev_orgs, by_slug, merged_keys=None):
    """Carry across the relations --refresh does not regenerate. Mutates the rebuilt rows.

    PER ENTRY, NOT PER FIELD, and that is the whole reason this function exists beside
    preserve_curated(). `relations` holds the OAR index's placement — which the refresh has
    just rewritten from the index tree, and MUST rewrite, or an upstream re-filing would
    never reach the registry — beside a placement statute or DAS states, which nothing
    upstream produces and only this carries. Copying the field wholesale in either direction
    loses one of the two: preserve_curated()'s "copy it if the new row has not got it" never
    fires here, because the new row always has the key.

    WHAT IS REGENERATED IS DECIDED BY THE ENTRY'S SOURCE, which is why `source` is required
    on every entry rather than a nicety: an entry that does not say where it came from is
    one this function cannot classify, and #178 is what that costs — `note` carries both the
    scrape's writing and a human's, tells them apart nowhere, and a hand-written note is
    destroyed by --refresh with nothing to report it.

    NOT AN ALLOWLIST OF SOURCES, DELIBERATELY, and it is the one place in this module that
    is not. This asks "did the scrape just produce this entry?" and carries everything else,
    including an entry whose source this module has no meaning for — because the alternative
    is a refresh that silently deletes hand-written curation over a typo in a source name.
    Whether the source is one the registry recognises is `relation-shape`'s question, and it
    is answered before the row can be committed, not while a rebuild is in flight."""
    merged_keys = MERGED_KEYS if merged_keys is None else merged_keys
    for o in prev_orgs:
        current = by_slug.get(o["slug"])
        if not current:
            continue
        for key in merged_keys:
            # A manual row is preserved WHOLE, so `current` is the very row being read from
            # here; the membership test is what keeps this from appending its own entries
            # onto itself.
            kept = list(current.get(key) or [])
            for entry in (o.get(key) or []):
                regenerated = isinstance(entry, dict) and entry.get("source") == OAR_INDEX
                if regenerated:
                    carry_decision(entry, kept)
                elif entry not in kept:
                    kept.append(entry)
            current[key] = kept


def preserve_name(prev_orgs, by_slug, per_row_keys=None):
    """Carry across the `name` the refresh does not own, and its basis with it. Mutates the
    rebuilt rows.

    PER ROW, NOT PER FIELD, which is what PER_ROW means and why this sits beside
    preserve_curated() and preserve_relations() rather than inside either. The scrape has
    just rebuilt every row's `name` from the chapter page — which is right for the 185 rows
    whose `name` IS the chapter title and nothing more, and is a silent overwrite of a
    reviewed statutory name on the rows where a human read the body's enabling authority and
    recorded what it calls the body (ADR 0003). Neither whole-field origin is true, so the
    ROW is asked: `name_basis` says which of the two this row's name is.

    THE PAIR OR NEITHER. `name` and `name_basis` are one statement in two keys, and carrying
    half of it is worse than carrying none: a `name` carried without its basis is a statutory
    name a refresh has just relabelled as the rules index's title, and a basis carried without
    its name is an OAR title now claiming to be what the statute calls the body — which is the
    false statement about Oregon law #168 exists to make unwriteable. So the keys move
    together, as `per_row_keys` — which is PER_ROW_KEYS, and `name-origin` in check_registry()
    states that PER_ROW_KEYS is exactly NAME_KEYS. That is not tidiness: the DECISION below is
    `name_basis`, and a third PER_ROW field would be carried, or dropped, on the provenance of
    a name it says nothing about. The parameter exists so
    `_proof_the_carry_is_what_keeps_an_established_statutory_name` can switch the carry off
    and watch the loss.

    THE PREVIOUS ROW DECIDES, not the rebuilt one. The rebuilt row always says
    `unverified-oar-title`, because that is all the scrape can know about a body; the
    committed row is where a review is recorded. Reading the rebuilt row would ask the scrape
    whether the scrape owns the value, and it would always answer yes.

    An unverified row carries NOTHING, deliberately: its `name` is the chapter title, the
    refresh has just rewritten it from the chapter page, and that is how an upstream retitle
    reaches the registry. Freezing it would leave the row asserting a title the rules index no
    longer prints, under a basis that says it is the title the rules index prints.
    """
    per_row_keys = PER_ROW_KEYS if per_row_keys is None else per_row_keys
    for o in prev_orgs:
        current = by_slug.get(o.get("slug"))
        # A manual row is preserved WHOLE, so `current` is the very row being read from; the
        # copy is a no-op there rather than a special case.
        if not current or o.get(NAME_BASIS_KEY) != ENABLING_AUTHORITY_NAME:
            continue
        for key in per_row_keys:
            if key in o:
                current[key] = o[key]


# THE SCRAPE'S OWN THREE SENTENCES for `note` (#178), stated ONCE so `cmd_refresh()`, which
# writes them, and `is_scrape_note()` below, which check_registry() reads them against, stay
# the same claim rather than two hand-typed copies of it drifting apart the way the field's
# own rationale already did (three places, before this fix). Two carry a `{...}` placeholder
# for the one piece the scrape could not have predicted (the fetch error, the disagreeing
# prefixes); `is_scrape_note()` turns each into the pattern that matches whatever the scrape
# actually filled it with.
NOTE_TITLE_NOT_PARSEABLE = "chapter page title not parseable; name from index (abbreviated)"
NOTE_FETCH_FAILED = "chapter page fetch failed ({error}); name from index (abbreviated)"
NOTE_PREFIXES_DISAGREE = ("chapterless group; children's name prefixes don't agree "
                           "({prefixes}), name from index (abbreviated)")
NOTE_SCRAPE_TEMPLATES = (NOTE_TITLE_NOT_PARSEABLE, NOTE_FETCH_FAILED, NOTE_PREFIXES_DISAGREE)


def _note_shape_pattern(template: str):
    """A regex matching exactly what `template.format(...)` can produce for any value of
    its one placeholder — built from the literal template text via `re.escape()` rather
    than hand-copied, so the shape `is_scrape_note()` checks against can never drift from
    the sentence `cmd_refresh()` actually writes."""
    before, _, rest = template.partition("{")
    if not rest:
        return re.compile("^" + re.escape(template) + "$")
    _, _, after = rest.partition("}")
    return re.compile("^" + re.escape(before) + ".+" + re.escape(after) + "$")


NOTE_SCRAPE_SHAPES = tuple(_note_shape_pattern(t) for t in NOTE_SCRAPE_TEMPLATES)


def is_scrape_note(note) -> bool:
    """Whether `note` is one of the sentences `cmd_refresh()` itself writes — the only
    thing `note` may hold now that curator prose has `curator_note` of its own (#178)."""
    return isinstance(note, str) and any(p.match(note) for p in NOTE_SCRAPE_SHAPES)


def cmd_refresh():
    raw = get(INDEX_URL)
    entries = parse_index(raw)
    chapters = [e[0] for e in entries if e[0]]
    if len(set(chapters)) != len(chapters):
        dupes = {c for c in chapters if chapters.count(c) > 1}
        sys.exit(f"duplicate chapters in index parse: {dupes}")
    n_groups = sum(1 for e in entries if e[0] is None)
    print(f"index: {len(chapters)} chapters + {n_groups} chapterless parent groups "
          f"({sum(1 for e in entries if e[2] is not None)} sub-units); "
          f"fetching proper names from chapter pages...")

    # Fetch proper names for every chaptered entry
    orgs = [None] * len(entries)
    fallbacks = 0
    done = 0
    for i, (ch, index_name, parent_idx) in enumerate(entries):
        if ch is None:
            continue  # chapterless group — named after its children below
        url = f"{BASE}/rules/oar_chapter_{ch}"
        name, note = index_name, None
        try:
            m = TITLE_RE.search(get(url))
            if m:
                name = re.sub(r"\s+", " ", unescape(m.group(1))).strip()
            else:
                note = NOTE_TITLE_NOT_PARSEABLE
                fallbacks += 1
        except Exception as e:
            note = NOTE_FETCH_FAILED.format(error=e)
            fallbacks += 1
        orgs[i] = scraped_entry(oar_name=name, oar_chapter=ch, raw_index_name=index_name,
                                source_url=url, note=note)
        time.sleep(0.2)
        done += 1
        if done % 40 == 0:
            print(f"...{done}/{len(chapters)}")

    # Chapterless parent groups: derive the proper name mechanically from the common
    # "Parent Name, " prefix their children's chapter pages all print; fall back to
    # the (abbreviated) index name if the children don't agree on one.
    for i, (ch, index_name, _) in enumerate(entries):
        if ch is not None:
            continue
        # --refresh deriving a chapterless parent's name from the common prefix of its
        # children's chapter-page titles. It reads `oar_name` and not `name`, which is the
        # same string on every row the scrape has just built and no longer the same field
        # (#168): what is being taken a prefix of is what the rules index PRINTS, and a
        # chapterless group named from its children's statutory names would be a name no
        # publisher ever wrote.
        child_names = [orgs[j]["oar_name"] for j, e in enumerate(entries)
                       if e[2] == i and orgs[j]]
        # COMPOUND NAME — NAME: the compound is read to produce this group's NAME and never
        # a placement. The hierarchy here is already known — the index tree gave it, and it
        # is written to `relations` below — so this takes the common prefix off the
        # children's chapter-page titles to find out what the rules index CALLS the parent
        # it filed them under. Deriving the placement the other way round, out of the
        # string, is what #174 forbids.
        prefixes = {n.split(", ")[0] for n in child_names if ", " in n}
        if len(prefixes) == 1:
            name = prefixes.pop()
            note = None
        else:
            name = index_name
            note = NOTE_PREFIXES_DISAGREE.format(prefixes=sorted(prefixes))
        orgs[i] = scraped_entry(oar_name=name, oar_chapter=None, raw_index_name=index_name,
                                source_url=INDEX_URL, note=note)

    by_slug = {}
    for o in orgs:
        if o["slug"] in by_slug:
            sys.exit(f"SLUG COLLISION: chapters {by_slug[o['slug']]['oar_chapter']} and "
                     f"{o['oar_chapter']} both slugify to {o['slug']!r} — needs a human "
                     "decision, not silent dedup")
        by_slug[o["slug"]] = o
    index_parents = {}
    for i, (ch, _, parent_idx) in enumerate(entries):
        if parent_idx is not None:
            index_parents[orgs[i]["slug"]] = orgs[parent_idx]["slug"]
            orgs[i]["parent_chapter"] = orgs[parent_idx]["oar_chapter"]
    # BEFORE anything is preserved: these are the entries the scrape owns, written from the
    # tree it has just read, onto rows nothing has been carried onto yet.
    set_index_relations(orgs, index_parents)

    assert_scrape_declared(orgs)

    if CATALOG.exists():
        prev_orgs = yaml.safe_load(CATALOG.read_text()).get("organizations", [])
        preserve_manual(prev_orgs, orgs, by_slug)
        preserve_curated(prev_orgs, by_slug)
        preserve_relations(prev_orgs, by_slug)
        preserve_name(prev_orgs, by_slug)

    cat = {
        "note": REGISTRY_NOTE,
        "source_url": INDEX_URL,
        "retrieved": date.today().isoformat(),
        "organizations": sorted(orgs, key=lambda o: o["slug"]),
    }
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    n_sub = sum(1 for o in orgs if relation_entries(o))
    print(f"catalog: {len(orgs)} organizations ({len(orgs) - n_sub} top-level, "
          f"{n_sub} sub-units, {fallbacks} name fallbacks)")


def load():
    return yaml.safe_load(CATALOG.read_text())


# ------------------------------------------------------------------------------ agency search
#
# WHICH NAMES A READER MAY FIND A BODY BY, and the one place that question is answered. Two
# searches ask it — this module's `find()`, which a human runs from the command line, and
# `agency_profile.profile()`, which build_agency_index and the profile CLI run — and before
# ADR 0003 both answered it with `name` because there was only one name on a row. A THIRD
# lives outside this repository: corpus-toolkit's `issuing_body_profile` reads the same
# registry file over MCP and still matches `name` alone (see agency_profile's docstring),
# which is a gap #168 has to close there and cannot be closed from here.
#
# THERE ARE THREE NOW, AND SEARCH SPANS ALL THREE. `name` becomes the statutory name; the
# rules index's title stays in `oar_name`; `aliases` is the registry's curated, reviewed
# "this body is also called that". A reader knows a body by whichever name the source in
# front of them printed — a rule document says "Oregon Liquor Control Commission" because
# that is what the rules index prints, while the statute says "Oregon Liquor and Cannabis
# Commission" — and search that matched only one of them would answer "no such body" to a
# reader holding the other. Promoting `name` (#168) must not be able to make a body
# unfindable by a name it is genuinely known by.
#
# WHY SPANNING IS SAFE HERE AND WOULD NOT BE IN A JOIN. Search's job is to hand a human or a
# model a SLUG, and the slug is what identity hangs on (CONTEXT.md, *Registry slug*).
# Matching more names cannot attribute a document to the wrong body: `profile()` requires a
# UNIQUE hit and reports the candidates otherwise, so the failure mode of a wider net is a
# disambiguation question, not a silent misattribution. A join has no such reader — which is
# why `enrich_oar.py` and `catalog_oar.py` match `oar_name` alone and do not span anything.
# Whether every body stays reachable by BOTH of its names, on this registry and on one with
# `name` already promoted, is not left to that argument: `findable-by-both-names` in
# check_registry() states it over all 189 rows on every PR.
#
# ALIASES ARE INCLUDED BECAUSE THEY ARE ASSERTED, not inferred. FIELDS declares the field
# "an ASSERTION of identity, reviewed once, rather than a similarity score computed at query
# time" — ten rows carry seventeen of them today, several being exactly the pre-rename name
# a reader arrives with ("Early Learning Division", "Office of State Fire Marshal"). Nothing
# fuzzy is added here: every name matched is a name some Oregon source prints for the body
# and a human put in the row.


def body_names(org) -> list:
    """The two names this registry states for a body: its statutory name and its OAR name.

    Missing keys are skipped rather than defaulted — a row with no `oar_name` is a registry
    that has broken its contract (`required-field`), and inventing an empty string for it
    here would quietly make the body findable by every query. Aliases are NOT here: they are
    names for the same body from elsewhere, and `resolve()` reports matching one as a
    different basis from matching a name this registry states."""
    if not isinstance(org, dict):
        return []
    # NAME READER — JOIN: the two names the registry itself states for a body, which is what
    # `resolve()` matches a publisher-written string against, and what search spans below.
    names = [org.get("name"), org.get("oar_name")]
    return [n for n in names if isinstance(n, str) and n.strip()]


def searchable_names(org) -> list:
    """Every name a reader can FIND this body by: both names the registry states, plus any
    curated alias. Search spans aliases because a reader arrives holding whatever name their
    source printed; `resolve()` keeps them in their own tier, because which name matched is
    part of what it reports."""
    aliases = org.get("aliases") if isinstance(org, dict) else None
    return body_names(org) + [a for a in (aliases or []) if isinstance(a, str) and a.strip()]


def name_matches(org, query) -> bool:
    """Whether `query` is a substring of any name this body is known by.

    An empty query matches NOTHING. It matched every row before, because `"" in anything` is
    true, so a reader who searched for nothing was told all 189 bodies are candidates — a
    list that names no body is not an answer, and `profile()` turns it into a
    "no unique match" error naming eight arbitrary slugs. The same hole was closed on the
    platform's own MCP surface for the sharper version of this failure: on a registry
    holding ONE entry, an empty query was exactly one hit, so the uniqueness test passed and
    a full profile was served for a body nobody named (corpus-toolkit#122). An empty query
    is a missing argument, not a wildcard."""
    q = str(query or "").strip().lower()
    return bool(q) and any(q in n.lower() for n in searchable_names(org))


def cli_line(org: dict, by_chapter: dict) -> str:
    """One search hit as the command line prints it: slug, name, chapter, and the parent a
    sub-unit sits under.

    A FUNCTION RATHER THAN FOUR LINES INSIDE `main()`, because `main()` is the one part of
    this module no gate reaches, and it is where the search a human actually runs is
    rendered — `python3 src/catalog_agencies.py "<search term>"` is the documented first
    step of onboarding an agency (AGENTS.md). It broke once already, in the change that
    added this: a comment landed at the wrong indentation, dedented the sub-unit line out of
    its `if`, and every hit that was a sub-unit died on an unbound name while `--check`,
    `--selftest` and every other gate stayed green."""
    # NAME READER — DISPLAY: what the command-line search prints for a human picking a slug.
    # The MATCHING is done by find(), over every name a body is known by; this only shows
    # the result, under the name the registry states for the body.
    tag = f"[ch. {org['oar_chapter']}"
    if org.get("parent_chapter"):
        parent = by_chapter.get(org["parent_chapter"])
        tag += f", sub-unit of {org['parent_chapter']} {parent['name'] if parent else '?'}"
    return f"{org['slug']:50} {org['name']}  {tag}]"


def promoted_name_registry(orgs) -> list:
    """The registry as ADR 0003 leaves it: every row's `name` replaced by a placeholder
    statutory name, `oar_name` untouched.

    THE FAULT INJECTION, AS CODE RATHER THAN AS A ONE-OFF SCRIPT. `name` and `oar_name` hold
    identical bytes on 186 of the 189 committed rows — four statutory names are established
    and only three of them differ from the OAR title (#168) — so any measurement of "which
    field does this consumer really read" run against committed data still passes on all but
    three rows by construction. Promoting
    `name` in memory is what makes such a measurement an observation — and keeping it here,
    where `--check` runs it on every PR, is what stops it from being a number someone once
    printed. The placeholder deliberately shares no word with the row's OAR name: a
    plausible statutory name ("Oregon " + the OAR name) would keep matching as a substring
    and prove nothing.

    A COPY. The rows are not mutated — this runs against the committed registry inside a
    gate, and a check that edits what it is checking is a check nobody can trust twice."""
    return [dict(o, name=f"Statutory Body {i:03d}") if isinstance(o, dict) else o
            for i, o in enumerate(orgs)]


def find(query: str, limit: int = 8, organizations=None):
    """Substring search for a human picking a slug, over every name a body is known by.

    `organizations` is a PARAMETER so the search can be proven against a registry whose
    `name` and `oar_name` differ. No committed row's do — which is exactly why a proof that
    reads the committed registry cannot tell the two fields apart."""
    orgs = organizations if organizations is not None else load()["organizations"]
    return [o for o in orgs if name_matches(o, query)][:limit]


# ---------------------------------------------------------------- name -> slug resolution
#
# `find()` above is a substring match "for a human picking a slug" and cannot reach a name
# written in another house style. The Secretary of State Archives Division inverts them —
# "Agriculture, Dept. of", "ODOT - Highway Division", "Treasury, Oregon State" — and folding
# in its 76 retention schedules needed every one attributed to a registry slug.
#
# GENERATES CANDIDATE FORMS RATHER THAN REWRITING TO ONE. An earlier version de-inverted a
# trailing kind unconditionally, turned "Criminal Justice Commission" into "commission of
# criminal justice", and LOST two names that had already matched. A name may or may not be
# inverted; guessing costs matches either way, trying both costs nothing.
#
# Measured on those 76: 66 automatic (24 exact, 31 normalized, 10 token, 1 alias), 10 left
# for a human. Recorded in _meta/catalog/retention-schedule-agencies.yml with a basis and,
# for anything non-exact, a note.
#
# MATCHES ON EVERY NAME A BODY HAS, WHICH IS WHAT ADR 0003 MOVED THE GROUND UNDER. This
# matched `name` alone until #187, and was almost unaffected in the data because `oar_name`
# holds the same bytes as `name` on 186 of the 189 rows — so the change is nearly invisible
# against the
# committed registry and stark against one with `name` already promoted: matching `name`
# alone loses 32 of the 72 recorded resolutions this file's tiers produced, and matching
# both loses none of them. The 76 were RE-MEASURED rather than assumed (issue #187), and 5
# of them do not reproduce for a reason older than this change: their recorded basis is
# `alias` and no registry row carries the aliases that produced them.

# The trailing `\.?` deliberately carries no closing `\b`. `\bdept\.?\b` CANNOT match
# "dept." — after the optional period `\b` would sit between "." and " ", neither a word
# character, so it is not a boundary. That form silently matched "dept" alone, left
# "department. of", and cost 9 of 76 matches before it was found.
_ABBREV = [
    (r"\bdept\.?", "department"), (r"\bcomm'?n\.?", "commission"),
    (r"\bdiv\.?(?=\s|$)", "division"), (r"\bexam'?rs\.?", "examiners"),
    (r"\bbd\.?(?=\s|$)", "board"), (r"\bofc\.?", "office"), (r"&", "and"),
]
_KIND = r"(department|board|commission|office|bureau|division|authority|agency)"
_STOP = {"oregon", "state", "of", "the", "and"}


def normalize_name(s: str) -> str:
    """Lowercase, de-punctuate and expand a free-text agency name."""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).lower()
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = re.sub(r"\(.*?\)", " ", s)                       # "(ODOT)", "(formerly DHS)"
    s = re.sub(r"^\s*odot\s*[-\u2013]\s*", "department of transportation ", s)
    for pat, rep in _ABBREV:
        s = re.sub(pat, rep, s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _variants(name: str):
    base = normalize_name(name)
    if not base:
        return []
    out = [base]
    stripped = re.sub(r"^(oregon state|state of oregon|oregon|the)\s+", "", base).strip()
    if stripped != base:
        out.append(stripped)
    for v in list(out):
        for pat, fmt in ((rf"^(.*?),?\s*{_KIND}\s+of$", "{1} of {0}"),
                         (rf"^(.*?)\s+{_KIND}$", "{1} of {0}"),
                         (rf"^{_KIND}\s+of\s+(.*)$", "{1} {0}")):
            m = re.match(pat, v)
            if m:
                out.append(fmt.format(m.group(1), m.group(2)).strip())
        for k in ("department", "agency", "commission", "board", "office"):
            out += [f"{v} {k}", f"{k} of {v}"]
    seen, uniq = set(), []
    for v in out:
        v = re.sub(r"\s+", " ", v).strip()
        if v and v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def _tokens(s):
    return {t for t in normalize_name(s).split() if t not in _STOP}


def resolve(name, organizations=None):
    """Free-text agency name -> (slug, basis) or (None, "unmatched").

    basis is exact | normalized | alias | tokens, in descending confidence."""
    orgs = organizations if organizations is not None else load()["organizations"]
    raw = str(name or "").strip().lower()
    if not raw:
        return None, "unmatched"
    # NAME READER — JOIN. Every tier below matches BOTH names a body has, because the string
    # being resolved was written by a publisher and publishers spell a body the way their
    # own source does: the Archives Division writes "Agriculture, Dept. of", the rules index
    # writes the OAR name, the enabling statute writes the statutory one. `searchable_names`
    # is the same answer the two searches use — one statement of which names identify a
    # body, so a name that finds it cannot fail to resolve it.
    #
    # THE TIERS STILL RANK, AND THE ALIAS TIER STAYS ITS OWN. `body_names` is the two names
    # the registry STATES for a body; an alias is a name from somewhere else, and folding it
    # into the tier above would report a match on a curated alias as `exact` — the basis is
    # recorded per resolution in _meta/catalog/retention-schedule-agencies.yml, where it is
    # what tells a human how far to trust the row. A body matched by both of its names is
    # still one body, which is why the token tier below collects slugs in a SET: a row
    # matching twice must not look like the tie that tier refuses to guess at.
    for o in orgs:
        if any(raw == n.strip().lower() for n in body_names(o)):
            return o["slug"], "exact"
    vs = set(_variants(name))
    for o in orgs:
        forms = {normalize_name(o.get("name")), normalize_name(o.get("oar_name")),
                 normalize_name(o.get("raw_index_name") or "")}
        if forms & vs:
            return o["slug"], "normalized"
    for o in orgs:
        if any(normalize_name(a) in vs for a in (o.get("aliases") or [])):
            return o["slug"], "alias"
    # Token containment, and ONLY when unambiguous. A tie is reported unmatched rather than
    # guessed: a wrong agency attribution is worse than a name on a review list.
    t = _tokens(name)
    if t:
        hits = {o["slug"] for o in orgs
                if any(t <= _tokens(n) for n in body_names(o))}
        if len(hits) == 1:
            return hits.pop(), "tokens"
    return None, "unmatched"


# --------------------------------------------------------------------------------- check
#
# WHAT --check IS FOR. The registry is the identity three sibling corpora crosswalk into, and
# every rule below states something the committed rows already satisfy — so a failure here
# means a change broke the registry's contract, not that the contract was aspirational. It
# reads the committed registry and nothing else: no scrape, no network, so CI can run it on
# every PR.
#
# ALLOWLIST, NOT BLOCKLIST. A row is checked against the fields FIELDS declares; anything
# else is a failure rather than something skipped. A key nobody declared cannot be evaluated
# for whether --refresh preserves it, and CONTEXT.md's overriding rule is that "could not
# check" is never reported as "is not there".


def simulate_refresh(prev_orgs, curated_keys=None, merged_keys=None, per_row_keys=None):
    """{slug: row} for what --refresh would leave behind, run against committed data.

    NO NETWORK AND NO SCRAPE. The scrape is replayed rather than performed: every row the
    scrape would rebuild is reconstructed by `scraped_entry()` from the values already
    committed for it, and then the two real preservation steps run over the result. What
    that measures is SURVIVAL — which rows and which fields a refresh keeps — not whether
    the upstream index still says the same thing, which is a question only a fetch can
    answer and not one a PR can break.

    A `manual` row is not reconstructed, because the scrape cannot see it: that is what the
    flag means. It comes back through preserve_manual() or not at all, and "or not at all"
    is a bug that already happened once (see that function).

    WHAT IT CAN NO LONGER SIMULATE, stated rather than left to be discovered. The index's
    placement is replayed from the row's own `oar-index` entry, because #174 removed the
    second copy that `parent_slug` held — so the rebuilt entry always names the parent the
    committed one names, and an upstream RE-FILING cannot be expressed in here. That was
    never something this function measured (it measures survival, not drift), and the rule
    about a decision not following a placement that moved lives in `carry_decision()` and is
    proven against it directly.

    THE SCRAPE'S NAME IS READ FROM `oar_name`, which is the step #168 owed this function.
    It used to read `name`, because that was where the committed rows held the chapter title
    — `oar_name` held the same bytes on all 189 of them, so the two calls were the same call
    and nothing distinguished them. ADR 0003 splits them: `name` is the statutory name now,
    and replaying the scrape from it would credit oregon.public.law with producing a name it
    has never printed, on exactly the rows where the difference matters.
    """
    orgs, by_slug, index_parents = [], {}, {}
    for o in prev_orgs:
        if o.get("manual"):
            continue
        # NAME READER — MACHINERY: the survival simulation replaying the scrape from
        # committed values. The OAR name is what the scrape produces, so that is what is
        # replayed; see this function's docstring for why it is no longer `name`.
        row = scraped_entry(oar_name=o.get("oar_name"), oar_chapter=o.get("oar_chapter"),
                            raw_index_name=o.get("raw_index_name"),
                            source_url=o.get("source_url"), note=o.get("note"))
        row["parent_chapter"] = o.get("parent_chapter")
        # WHERE THE INDEX'S PLACEMENT IS REPLAYED FROM, now that `parent_slug` is gone
        # (#174): the committed `oar-index` entry itself. `setdefault`, not assignment — a
        # row carrying two of them is `index-relation-is-regenerated`'s to report, and
        # letting the second win here would rebuild the row against a placement that rule
        # is in the middle of refusing.
        for entry in relation_entries(o):
            if isinstance(entry, dict) and entry.get("source") == OAR_INDEX:
                target = entry.get("target")
                if isinstance(target, str) and target:
                    index_parents.setdefault(row["slug"], target)
        orgs.append(row)
        # setdefault, not assignment: a slug claimed twice is unique-slug's failure to
        # report, and masking one of the two here would turn it into a survival failure
        # against the wrong row.
        by_slug.setdefault(row["slug"], row)
    # The same three steps --refresh runs, in the same order. The index relations are
    # rebuilt from the committed `oar-index` entries because that is what the index tree
    # told the last refresh — the simulation measures SURVIVAL, not whether the mirror still
    # says it, which is a question only a fetch can answer.
    set_index_relations(orgs, index_parents)
    preserve_manual(prev_orgs, orgs, by_slug)
    preserve_curated(prev_orgs, by_slug, curated_keys)
    preserve_relations(prev_orgs, by_slug, merged_keys)
    preserve_name(prev_orgs, by_slug, per_row_keys)
    return {o["slug"]: o for o in orgs}


def _row_id(o, i):
    """What to name a row in a failure. Falls back to its position, because a row missing
    the slug is exactly the row that most needs pointing at."""
    slug = o.get("slug") if isinstance(o, dict) else None
    return slug if isinstance(slug, str) and slug else f"organizations[{i}]"


def _claimed_twice(key, rows):
    """(row_id, first_row_id, value) for every row whose `key` a PRECEDING row in `rows`
    already claims. Shared by both uniqueness checks below so the walk itself is written
    once -- but the RULE NAME stays a literal at each call site rather than a parameter
    passed through this function, because a `Failure(rule, ...)` call whose first argument
    is a variable is invisible to `_LEDGER.emitted_rules()`'s AST scan (#320: this is what
    left `unique-slug` and `unique-chapter` undeclarable from the scan's own evidence, the
    one gap adopting the ledger could not close by declaring a name -- only rewriting the
    call site to a literal closes it)."""
    seen = {}
    for i, o in rows:
        value = o.get(key)
        if value is None:   # 19 bodies hold no chapter, which is not a collision
            continue
        if value in seen:
            yield _row_id(o, i), seen[value], value
        else:
            seen[value] = _row_id(o, i)


def check_registry(cat, fields=None, refresh_note=None, chapter_page_docs=None) -> list:
    """Every way the registry violates its contract, as Failures.

    `fields` is the declaration to check against, defaulting to the one this module ships.
    It is a PARAMETER so that --selftest can check a registry against a differently-declared
    table — the two ways a curated field goes missing from CURATED_KEYS are statements about
    the declaration, and no registry row can express either one.

    `refresh_note` is likewise a PARAMETER, defaulting to `REGISTRY_NOTE` — the string
    `cmd_refresh()` writes — for the same reason: --selftest's fixture carries its own
    synthetic note (built to name every FIELDS key without being the real prose), and a
    real registry's `note` is checked against the real `REGISTRY_NOTE`, not the fixture's
    stand-in. #278 asked whether this check should be relaxed, on the theory that the
    top-level `note` might carry hand-appended curator prose the way catalog_oar.py's does
    — measured against all 23 commits that have ever touched agencies.yml and found false
    (see the comment above `REGISTRY_NOTE`'s own extraction site): the committed note has
    never once exceeded the literal, so this stays a real equality check rather than one
    designed to fail the first time a capability nothing here uses gets used.

    `chapter_page_docs` is the same shape of parameter a third time, for the same reason
    (#279): defaulting to the real text of `CHAPTER_PAGE_DOC_FILES`, so --selftest can
    hand this a synthetic `{name: text}` mapping sized to the fixture instead of reading
    two real files off disk against a fixture that was never meant to match them."""
    fields = FIELDS if fields is None else fields
    refresh_note = REGISTRY_NOTE if refresh_note is None else refresh_note
    chapter_page_docs = (_default_chapter_page_docs() if chapter_page_docs is None
                         else chapter_page_docs)
    # ORDERED, not a frozenset: passed straight through to simulate_refresh() -> the same
    # preserve_curated() a real --refresh calls, so the simulation stays faithful to it —
    # including the order it now writes curated keys in (#182), not just which keys survive.
    curated = curated_keys_in_order(fields)
    scraped = frozenset(keys_in_order(SCRAPED, fields))
    merged = frozenset(keys_in_order(MERGED, fields))
    per_row = frozenset(keys_in_order(PER_ROW, fields))

    failures = []
    orgs = (cat or {}).get("organizations")
    if not isinstance(orgs, list):
        return [Failure("readable-registry", "agencies.yml",
                        "no `organizations` list to check")]
    # Every rule below is vacuously true of an empty list, so a registry that lost all its
    # rows would pass every one of them — the "check that passes without checking anything"
    # this repo treats as a defect in its own right. `validate_frontmatter` resolves every
    # content file's agency: against these rows, so zero of them is never a valid state.
    if not orgs:
        return [Failure("registry-populated", "agencies.yml",
                        "no bodies at all — every other rule is vacuously true of an "
                        "empty registry, so nothing was checked")]

    # THE REGISTRY'S OWN `note`, AGAINST THE FIELDS IT ACTUALLY DECLARES (#185). `note` is
    # this file's top-level self-description — read by three sibling corpora — and nothing
    # compared it against FIELDS: it went stale describing eleven fields while rows carried
    # fifteen, then again after #174 removed one and added four more, discovered only by
    # someone reading it. The set checked against is DERIVED from `fields`, the same reason
    # CURATED_KEYS is derived from FIELDS rather than restated (#165) — a second,
    # hand-maintained list of "fields the note should cover" would drift exactly the way the
    # note itself did. The bar is the field's name appearing anywhere in the prose, which is
    # the same measurement this ticket's own triage used to find the fields the note had
    # stopped naming — not a claim that a name-check proves the DESCRIPTION is current, only
    # that a field added and never mentioned at all cannot pass silently again.
    #
    # A WORD-BOUNDARY MATCH, NOT `in`. Bare substring containment cannot fire for `note`
    # (a substring of `curator_note`) or `name` (a substring of `name_basis`, `oar_name`,
    # `raw_index_name` and `curator_note`): with every other field named, dropping either
    # of those two from the note's prose left it undetected, measured directly by calling
    # this function on `_fixture()` with each field's name struck from the fixture note in
    # turn — the field-name characters are still present as part of a longer identifier,
    # so `in` reports the field as named when the note never mentions it on its own. `note`
    # is one of the five fields #185 found the pre-fix note actually missing, so the bare
    # bar could not have caught a recurrence of the exact drift it exists to catch.
    file_note = cat.get("note") if isinstance(cat, dict) else None
    for key in sorted(fields):
        if not isinstance(file_note, str) or not re.search(
            r"(?<![A-Za-z0-9_])" + re.escape(key) + r"(?![A-Za-z0-9_])", file_note
        ):
            failures.append(Failure(
                "note-covers-fields", "agencies.yml",
                f"field {key!r} is declared in FIELDS but is not named anywhere in the "
                "registry's own top-level `note` — the note is this file's "
                "self-description and a field it never mentions is one a reader of the "
                "note alone would not know exists"))

    # THE TWO COPIES, DIRECTLY, NOT ONLY BY WHICH NAMES THEY EACH CONTAIN. Both copies
    # can drift by thousands of characters — a sentence reworded, a clause dropped — while
    # each still names every FIELDS key and passes `note-covers-fields` above cleanly;
    # #185's own root cause was exactly this shape, five tickets in a row updating
    # `cmd_refresh()`'s literal and leaving the committed file's prose behind with nothing
    # comparing the two. `REGISTRY_NOTE` is the one place that literal now lives, read by
    # both `cmd_refresh()` and here, so this is a real equality check rather than a second
    # hand-maintained expectation. #278 proposed retiring this rule on the theory that the
    # top-level `note` might carry hand-appended curator prose a wholesale rewrite would
    # destroy — measured false across the field's entire committed history (see the comment
    # above `REGISTRY_NOTE`'s own extraction site): nothing has ever been appended here, so
    # the rule stays.
    if not isinstance(file_note, str) or file_note != refresh_note:
        failures.append(Failure(
            "note-agrees-with-refresh", "agencies.yml",
            "the registry's own top-level `note` does not match `REGISTRY_NOTE`, the "
            "string `cmd_refresh()` writes back — the two are meant to be kept "
            "byte-identical (#185) and nothing but this rule notices when they stop "
            "being so"))

    # THE NOTE'S OWN "null on N of the M chapterless" CLAIM, AGAINST A LIVE COUNT (code
    # review of #281). Reads the COMMITTED file's note, not `refresh_note`: the defect this
    # rule exists to catch is `REGISTRY_NOTE` itself going stale, which `note-agrees-with-
    # refresh` above cannot see because it only proves the two copies match each other, not
    # that either still describes the file. OPTIONAL, not required — the phrase is matched
    # if present and left alone if not: forcing every note (including the synthetic
    # `--selftest` fixture's, built only to name every FIELDS key) to carry this exact
    # sentence would couple every other rule's fixture to a sentence about this one. The
    # real committed note always has it; when it does, its two numbers must agree with the
    # file's own chapterless census or the sentence is reporting a state the same run's own
    # numbers contradict.
    if isinstance(file_note, str):
        m = NOTE_CHAPTERLESS_RE.search(file_note)
        if m:
            stated = (int(m.group(1)), int(m.group(2)))
            live = chapterless_source_url_census(orgs)
            if stated != live:
                failures.append(Failure(
                    "note-numbers-current", "agencies.yml",
                    f"the registry's own top-level `note` states \"null on {stated[0]} of "
                    f"the {stated[1]} chapterless rows\"; the committed registry has "
                    f"{live[0]} of {live[1]} chapterless rows carrying no `source_url` — "
                    "update the literal in REGISTRY_NOTE (src/catalog_agencies.py) and "
                    "re-run --refresh so the committed note picks it up"))

    # HOW MANY CHAPTER PAGES A --refresh FETCHES, AGAINST WHAT TWO OTHER SCRIPTS SAY IT
    # DOES (#279). `expand_oar_name.py` and `record_name_basis.py` both explain, in prose,
    # why they are a one-shot script rather than a --refresh by naming that refresh's
    # network cost — and the number drifted to 189 (this registry's ROW count) in both of
    # them at once while only rows carrying `oar_chapter` are ever fetched. Measured here
    # from the FILE rather than trusted from either script, the same reason
    # `authority_census` reads the rows and not the table that writes them: on any failure
    # path the two disagree, and a check that read the docstring's own idea of the number
    # would report the claim as evidence for itself. `chaptered_rows()` is the ONLY place
    # that sum is written (code review of #279: this rule and `chapter_census()` — the
    # figure printed beside it on every --check run — each wrote it out separately at
    # first, two copies of one fact in a change about two copies of one fact disagreeing).
    chaptered = chaptered_rows(orgs)
    for doc_name, doc_text in chapter_page_docs.items():
        if doc_text is None:
            failures.append(Failure(
                "chapter-page-count-current", doc_name,
                "could not be read (missing or unreadable), so no chapter-page count "
                "could be checked against it — restore the file, or update "
                "CHAPTER_PAGE_DOC_FILES in the same change if it was deliberately removed"))
            continue
        m = CHAPTER_PAGE_COUNT_RE.search(doc_text)
        if not m:
            failures.append(Failure(
                "chapter-page-count-current", doc_name,
                "does not state, in the phrase this check looks for ('re-fetches ... N "
                "chapter pages'), how many chapter pages a --refresh fetches — reword "
                "within that shape, keeping the count and the words 'chapter pages' on "
                "one line (CHAPTER_PAGE_COUNT_RE cannot match across a wrap), or update "
                "CHAPTER_PAGE_COUNT_RE in the same change"))
            continue
        stated = int(m.group(1).replace(",", ""))
        if stated != chaptered:
            failures.append(Failure(
                "chapter-page-count-current", doc_name,
                f"states a --refresh re-fetches {stated} chapter pages; the committed "
                f"registry has {chaptered} row(s) carrying `oar_chapter` (of {len(orgs)} "
                "total rows) — that is what a --refresh actually fetches"))

    for i, o in enumerate(orgs):
        if not isinstance(o, dict):
            failures.append(Failure("readable-row", _row_id(o, i),
                                    "not a mapping, so no rule below could be evaluated "
                                    "against it"))
            continue
        for key in o:
            if key == BUDGET_AGENCY_CODE:
                failures.append(Failure(
                    "budget-agency-code-retired", _row_id(o, i),
                    "budget_agency_code has reappeared — ADR 0003 renamed it to "
                    "das_agency_number and #177 retired the deprecated alias for good. "
                    "The field of record is das_agency_number; this key does not get "
                    "declared back into FIELDS, it gets deleted"))
            elif key not in fields:
                failures.append(Failure(
                    "declared-field", _row_id(o, i),
                    f"field {key!r} is not declared in FIELDS — if it is curated, "
                    "--refresh will destroy it; declare it"))
        # An absent key and an empty value are different claims: `relations: []` says this
        # registry places a body under no other, an absent `relations` says nobody asked.
        # Consumers read both as "no parent", which is how the second silently becomes the
        # first.
        for key, field in fields.items():
            if field.required and key not in o:
                failures.append(Failure("required-field", _row_id(o, i),
                                        f"required field {key!r} is absent (null is a "
                                        "value; absent is not)"))

    # Position is carried alongside, so a failure points at the row's place in the
    # committed file rather than its place among the rows that happened to be readable.
    rows = [(i, o) for i, o in enumerate(orgs) if isinstance(o, dict)]

    # THE ENABLING AUTHORITY'S THREE STATES, KEPT APART. A row carrying no key at all is
    # saying nobody has looked yet — however many rows that is today, which is the one state
    # this rule passes over in silence. Every row that DOES carry the key has been reviewed
    # by a human, so the value has to be something a reader can act on: an authority in one
    # of the accepted forms, or a stated reason there is none. What this rule refuses is the
    # middle — a blank, a null, or prose — because each of them reads as "this body has no
    # enabling authority" while recording that nobody established anything of the sort.
    for i, o in rows:
        if "enabling_authority" not in o:
            continue
        form, detail = classify_authority(o["enabling_authority"])
        if form is None:
            failures.append(Failure("enabling-authority-form", _row_id(o, i),
                                    f"enabling_authority {detail}"))

    # WHAT THIS ROW'S `name` IS, AND WHETHER THE ROW CAN SUPPORT THE CLAIM (#168). ADR 0003
    # makes `name` the STATUTORY name; most rows still hold the OAR chapter title they were
    # scraped with, and the two must not be the same state. This rule is what stops a row
    # from silently becoming the first while holding the second.
    #
    # AN ESTABLISHED STATUTORY NAME NEEDS AN AUTHORITY TO HAVE BEEN ESTABLISHED FROM, and
    # `enabling_authority` is where this registry records one. A row claiming
    # `enabling-authority` with no authority on it is a claim resting on evidence the file
    # does not hold — `manual: true` again, in the one field ADR 0003 calls the risky half.
    # `none: <reason>` does not support it either: a reviewed absence records that the body
    # has NO enabling authority, so there is nothing for a statutory name to be read off.
    #
    # AN UNVERIFIED ROW MUST STILL HOLD THE OAR TITLE, which is the other half and the one
    # that makes "no row's name is blanked" checkable rather than promised. `name` and
    # `oar_name` hold the same bytes on every row nobody has reviewed, so a row that says it
    # carries the unverified OAR title and carries something else — a blank, a truncation, a
    # hand-written guess — is a name nothing produced and nobody read.
    #
    # THE FORM OF THE NAME ITSELF is `findable-by-both-names`': a name that matches nothing
    # is refused there, on both fields, and reported as the body it makes unfindable.
    # NAME READER — MACHINERY: the registry's contract check, reading `name` to state what
    # KIND of value it is holding and whether the row can support that claim. It never
    # matches the name against anything and never shows it to a reader except inside its own
    # failure message; what it operates on is the field and the provenance beside it.
    for i, o in rows:
        if NAME_BASIS_KEY not in o:
            continue          # `required-field` above already reported it
        basis = o.get(NAME_BASIS_KEY)
        if basis not in NAME_BASES:
            failures.append(Failure(
                "statutory-name-basis", _row_id(o, i),
                f"{NAME_BASIS_KEY} {basis!r} is not a basis this registry can record — "
                f"expected {ENABLING_AUTHORITY_NAME!r} (the statutory name, read off the "
                f"body's enabling authority) or {UNVERIFIED_OAR_TITLE!r} (nobody has "
                f"established one, so `name` still holds the OAR chapter title)"))
            continue
        if basis == ENABLING_AUTHORITY_NAME:
            form = classify_authority(o.get("enabling_authority"))[0]
            if form is None or form == "reviewed-none":
                held = ("no enabling_authority at all, which is how this registry says "
                        "nobody has looked at this body yet"
                        if "enabling_authority" not in o
                        else f"enabling_authority {o['enabling_authority']!r}")
                failures.append(Failure(
                    "statutory-name-basis", _row_id(o, i),
                    f"name {o.get('name')!r} is recorded as the statutory name, and the row "
                    f"carries {held} — so nothing here establishes what the body's enabling "
                    f"authority calls it. Record the authority, or record the name as "
                    f"{UNVERIFIED_OAR_TITLE!r}"))
        # NAME READER — MACHINERY: the other half of the same rule, comparing the two name
        # FIELDS to each other. It asks whether this row holds the string the scrape put
        # there, which is a question about where a value came from and not about which body
        # any name identifies.
        elif not all(isinstance(o.get(k), str) for k in ("name", "oar_name")):
            # A row missing either name, or holding a null in one, is `required-field`'s to
            # report. A rule that fires on the same row as another stops saying which of the
            # two the row is about — the division `findable-by-both-names` already keeps.
            continue
        elif o["name"] != o["oar_name"]:
            failures.append(Failure(
                "statutory-name-basis", _row_id(o, i),
                f"name {o.get('name')!r} is recorded as the unverified OAR title and the "
                f"row's oar_name is {o.get('oar_name')!r} — an unreviewed row holds the "
                f"chapter title and nothing else, so this name was neither scraped nor "
                f"read off an authority"))

    # `note` IS SCRAPE-ONLY NOW (CONTEXT.md, "Relation source"; #178). A SCRAPED field is
    # skipped by `survives-refresh` on the assumption the refresh rewrites it faithfully —
    # true of one of `cmd_refresh()`'s own three sentences (`is_scrape_note()`, above
    # `cmd_refresh()`) and false of anything else, so a `note` that is not one of them is
    # not the scrape's and nothing preserves it, `manual` included: `manual` protects a row
    # WHOLE, but declaring `note` refuses it regardless is what stops a hand-typed sentence
    # from ever being mistaken for one of the three the scrape can produce on its own. The
    # previous version of this rule required `manual` instead of a recognised shape, which
    # refused the scrape's own fetch-failure and title-not-parseable notes on every ordinary
    # row where they fire — the opposite of what #178 asked kept. Curator prose belongs in
    # `curator_note` (CURATED, protected on any row) instead of here.
    for i, o in rows:
        note = o.get("note")
        if note and not is_scrape_note(note):
            failures.append(Failure(
                "note-scrape-shape", _row_id(o, i),
                f"note {note!r} matches none of the sentences cmd_refresh() writes "
                f"({NOTE_SCRAPE_TEMPLATES!r}) — `note` is scrape-only; curator prose "
                "about a row belongs in `curator_note`"))

    # IDENTITY. The slug is the only thing a sibling corpus joins on, and the chapter is
    # what put most rows here; either one claimed twice attributes one body's documents to
    # another. --refresh already calls a slug collision a human decision rather than silent
    # dedup, and this is the same rule applied to what is already committed.
    for row_id, first_id, value in _claimed_twice("slug", rows):
        failures.append(Failure("unique-slug", row_id,
                                f"slug {value!r} is already claimed by {first_id!r}"))
    for row_id, first_id, value in _claimed_twice("oar_chapter", rows):
        failures.append(Failure("unique-chapter", row_id,
                                f"oar_chapter {value!r} is already claimed by {first_id!r}"))

    # THE PARENT'S CHAPTER, AGAINST THE BODY THE RELATIONS NAME. #174 retired `parent_slug`,
    # so `relations` is the registry's only statement of where a body sits and this is the
    # one remaining field that repeats a fact about that placement: `parent_chapter` is the
    # OAR chapter of the body this one is under. When the two disagree, each consumer
    # resolves the parent differently depending on which half it read — the failure that
    # does not look like one from either side.
    #
    # A FIELD THAT HOLDS ONE CHAPTER CANNOT STATE A DISAGREEMENT. A body may hold more than
    # one relation, because the sources may place it under different parents and ADR 0003
    # keeps that (ADR 0004). There is then no single parent whose chapter this field could
    # hold, and writing either one publishes one source's reading as the registry's. No
    # committed row is in that state; the rule says what happens on the day one is, rather
    # than picking for it.
    by_slug = {o["slug"]: o for _, o in rows if isinstance(o.get("slug"), str)}
    for i, o in rows:
        targets = parent_targets(o)
        chapter = o.get("parent_chapter")
        if len(targets) > 1:
            if chapter is not None:
                failures.append(Failure(
                    "parent-agrees", _row_id(o, i),
                    f"parent_chapter is {chapter!r} while this body's relations place it "
                    f"under {targets!r} — one chapter cannot say which of those it is, and "
                    "whichever it names publishes one source's reading as this registry's"))
            continue
        if not targets:
            if chapter is not None:
                failures.append(Failure(
                    "parent-agrees", _row_id(o, i),
                    f"parent_chapter is {chapter!r} and no relation places this body under "
                    "anything — the field names the chapter of the body this one is under, "
                    "and there is none"))
            continue
        # A target naming no body is `relation-resolves`'s to report; saying it again here
        # would tell a reader the chapter is wrong when the placement is.
        parent = by_slug.get(targets[0])
        if parent is not None and chapter != parent.get("oar_chapter"):
            failures.append(Failure(
                "parent-agrees", _row_id(o, i),
                f"parent_chapter {chapter!r} but {targets[0]!r} holds chapter "
                f"{parent.get('oar_chapter')!r}"))

    # THE RELATIONS. Every entry says which body this one is under and on whose evidence
    # (ADR 0004), and a body may hold several because the sources may disagree and ADR 0003
    # keeps the disagreement. What the rules below refuse is an entry a reader cannot act
    # on: one that does not say where it came from, or what it claims, or about whom.
    for i, o in rows:
        # `relations: null` IS CHECKED HERE, not passed over. A row that carries the key
        # has had the field written, so a null is not the "nobody has looked" an absent key
        # would be — it is a list that went missing, and `relation_entries()` reads it as
        # empty, which is a body under nothing to every consumer. The absent key is
        # `required-field`'s to report, which is why this only speaks when the key is there.
        if RELATION_KEY in o and not isinstance(o[RELATION_KEY], list):
            failures.append(Failure("relation-shape", _row_id(o, i),
                                    f"{RELATION_KEY} is {o[RELATION_KEY]!r}, not a list of "
                                    "relations — every reader of the field takes it for a "
                                    "body placed under nothing, and no entry in it could be "
                                    "evaluated"))
            continue
        seen, targets, index_targets = {}, [], []
        for entry in relation_entries(o):
            fault = relation_fault(entry)
            if fault:
                failures.append(Failure("relation-shape", _row_id(o, i), fault))
                continue
            # ONE READING PER SOURCE. Several relations on one body are a disagreement
            # between sources and a finding (ADR 0003); two from ONE source about one parent
            # are the same reading recorded twice, free to differ, with nothing saying which
            # is current — and the shape a merge that carried an entry the scrape had
            # already regenerated would leave behind.
            key = (entry["target"], entry["source"])
            if entry["target"] not in by_slug:
                failures.append(Failure(
                    "relation-resolves", _row_id(o, i),
                    f"relation target {entry['target']!r} is not a slug in this registry — "
                    "the relation names a body this registry carries (ADR 0004), and a "
                    "walk that follows a dangling one cannot tell it lost a hop from a "
                    "body that had none"))
            if key in seen:
                failures.append(Failure(
                    "relation-unique", _row_id(o, i),
                    f"{entry['source']!r} places this body under {entry['target']!r} twice "
                    f"({seen[key]!r} and {entry!r}) — a source states one reading, and two "
                    "entries from it are not the disagreement several relations record"))
            else:
                seen[key] = entry
            targets.append(entry["target"])
            if entry["source"] == OAR_INDEX:
                index_targets.append(entry["target"])
        # AN `oar-index` ENTRY IS A CLAIM THAT --refresh REGENERATES IT, so the rows it may
        # sit on are the rows the refresh rebuilds, and there may be at most ONE. It may not
        # sit on a `manual` row at all: a manual body is one the chapter index does not
        # carry (`preserve_manual`), so the index has placed it nowhere, and an entry
        # claiming otherwise attributes a placement to a publisher that never made it AND
        # labels an entry nothing can regenerate as one the refresh rebuilds. Nothing else
        # would notice — the survival simulation preserves a manual row WHOLE and never
        # compares it with a scrape. `registry` is the source that is true of such a
        # placement.
        #
        # ONE, because the index tree files a body under exactly one parent and the refresh
        # writes exactly what the tree says: a second entry from that source is a placement
        # the scrape will never reproduce, so it is destroyed unread on the next run.
        # `relation-unique` does not reach it — that rule refuses one source naming one
        # parent twice, and these name two. Until #174 this rule compared the entries with
        # `parent_slug`, which held the same placement; there is no second copy to compare
        # with now, so it states what the tree can produce instead.
        if o.get("manual") and index_targets:
            failures.append(Failure(
                "index-relation-is-regenerated", _row_id(o, i),
                f"is a {'manual'!r} row carrying {OAR_INDEX!r} relation(s) naming "
                f"{index_targets!r} — the chapter index does not carry this body, so it has "
                f"placed it nowhere and no refresh can rebuild the entry; record it as "
                f"{REGISTRY!r} (or the source that states it)"))
        elif len(index_targets) > 1:
            failures.append(Failure(
                "index-relation-is-regenerated", _row_id(o, i),
                f"carries {len(index_targets)} {OAR_INDEX!r} relations, naming "
                f"{index_targets!r} — the index tree files a body under one parent and "
                "--refresh writes exactly that, so every entry past the first is destroyed "
                f"unread; record the others as {REGISTRY!r} (or the source that states "
                "them)"))


    # *PART OF* AND AN ENABLING AUTHORITY ARE OPPOSITE CLAIMS ABOUT ONE BODY. ADR 0004
    # defines *part of* as the case where nothing separately constitutes the unit — "there is
    # no statute constituting either, because there is no separate body to constitute" — and
    # CONTEXT.md says it "has no enabling authority because there is nothing separate to
    # enable". A row asserting both is a row whose kind was decided on evidence the row
    # itself contradicts, and it is silent from either side: a consumer reading the relation
    # sees internal structure, a consumer reading the field sees a body Oregon law created,
    # and neither sees the other. Which of the two is wrong is a human's question; that the
    # registry may not publish both is this rule's.
    #
    # A REVIEWED ABSENCE IS NOT THIS FAILURE. `none: <reason>` is precisely what a *part of*
    # unit is expected to carry (ADR 0004 gives it as UNMAPPED's commonest legitimate
    # reason), so the rule asks whether the value is an AUTHORITY rather than whether the key
    # is present. An unreadable value is `enabling-authority-form`'s to report; a rule that
    # fired on the same row would stop saying which of the two the row is about.
    for i, o in rows:
        if "enabling_authority" not in o:
            continue
        form, _detail = classify_authority(o["enabling_authority"])
        if form is None or form == "reviewed-none":
            continue
        for entry in relation_entries(o):
            if isinstance(entry, dict) and entry.get("kind") == PART_OF:
                failures.append(Failure(
                    "part-of-has-nothing-to-enable", _row_id(o, i),
                    f"is recorded {PART_OF!r} under {entry.get('target')!r} and carries "
                    f"enabling_authority {o['enabling_authority']!r} — *part of* says "
                    "nothing separately constitutes this unit (ADR 0004), and an authority "
                    "says Oregon law did; one of the two is wrong and the registry states "
                    "both"))

    # AN AUTHORITY ADMITS ONE BODY (#212), AND A RELATION CITING IT FOR A DIFFERENT ONE IS
    # THE SHAPE OF THE BUG THIS TICKET FOUND. `oregon-military-department-office-of-
    # emergency-management` sat under the Military Department for four years after HB 2927
    # (2021) made the Office of Emergency Management a standalone department (ORS 401.052) —
    # and nothing could have caught it, because the row never carried `enabling_authority`
    # at all: no evidence, nothing for a gate to compare against. The check this omission
    # leaves behind is narrow and MECHANICAL, not a claim about what a citation's TEXT says
    # (this repository does not parse statute prose for meaning at check time; that is
    # exactly the "confidently wrong matcher" trap `link_enabling_authority.py`'s own
    # docstring is about): an `enabling_authority` citation is EXCLUSIVE to the one row it
    # admits unless MORE THAN ONE row already carries it (ORS 576.062's nineteen commodity
    # commissions, admitted by one enumerated list, are the reason this is "exclusive to the
    # rows that share it" and not "exclusive to one row" — sharing is EVIDENCE, recorded on
    # both sides, not a coincidence to refuse). A relation's `administered_by` `authority`
    # citing a DIFFERENT row's exclusive citation asserts that ONE statute simultaneously
    # constitutes body A on its own and places body A under body B — ADR 0004's own
    # distinction between the section that CONSTITUTES a body and the section that
    # ADMINISTERS it, collapsed into one citation that cannot honestly be both.
    #
    # A citation carried by exactly one row is not "no evidence of sharing" and does not
    # become the general rule from a single instance; it is the state every enabling
    # authority is in on the day it is FIRST recorded, and the check does not fire again once
    # a genuine second row cites the same section for the same reason ORS 576.062 does not
    # fire it 19 times over.
    exclusive_authority = {}
    for i, o in rows:
        ea = o.get("enabling_authority")
        if not ea:
            continue
        exclusive_authority.setdefault(ea, []).append(o.get("slug"))
    exclusive_authority = {a: slugs[0] for a, slugs in exclusive_authority.items()
                           if len(slugs) == 1}
    for i, o in rows:
        for entry in relation_entries(o):
            if not isinstance(entry, dict) or entry.get("kind") != ADMINISTERED_BY:
                continue
            auth = entry.get("authority")
            owner = exclusive_authority.get(auth)
            if owner is not None and owner != o.get("slug"):
                failures.append(Failure(
                    "relation-authority-is-not-another-bodys-own", _row_id(o, i),
                    f"is recorded {ADMINISTERED_BY!r} under {entry.get('target')!r} on the "
                    f"authority of {auth!r} — but {auth!r} is {owner!r}'s own "
                    "`enabling_authority`, cited by no other row, so it is what constitutes "
                    f"{owner!r} as a body, not evidence of what {o.get('slug')!r} is placed "
                    "under. One citation cannot honestly be recorded as both — either this "
                    "row has its own authority and cites that instead, or the citation is "
                    "wrong"))

    # EVERY BODY FINDABLE BY BOTH OF THE NAMES IT HAS, BEFORE AND AFTER `name` IS PROMOTED.
    # This is the search half of #187 stated over the whole registry rather than over a
    # fixture: for all 189 rows, the body must be among the hits when a reader searches the
    # statutory name AND when they search the OAR name — the name every one of that body's
    # rule documents carries. Run TWICE, the second time against `promoted_name_registry()`,
    # because on committed data the two fields hold the same bytes and matching either one
    # passes; the promoted run is the only one in which reading `name` alone fails.
    #
    # It judges rows that CARRY both names as strings and leaves the rest to
    # `required-field` — a rule that fires on the same row as another stops saying which of
    # the two the row is about. What it catches that `required-field` cannot is a name that
    # is present, is a string, and matches nothing: `oar_name: "   "` reads as a name to
    # every consumer and makes the body unfindable by the only name the rules index prints
    # for it.
    named = [o for _, o in rows
             if all(isinstance(o.get(k), str) for k in ("name", "oar_name", "slug"))]
    for registry, when in ((named, "as committed"),
                           (promoted_name_registry(named),
                            "once `name` holds the statutory name (ADR 0003)")):
        for o in registry:
            for field in ("name", "oar_name"):
                if not any(x["slug"] == o["slug"] for x in registry
                           if name_matches(x, o[field])):
                    failures.append(Failure(
                        "findable-by-both-names", o["slug"],
                        f"searching its {field} ({o[field]!r}) does not reach this body "
                        f"{when} — a reader who knows it by that name cannot find it"))

    # A FIELD THAT HOLDS TWO ORIGINS MAY NOT BE DECLARED AS ONE. Every other rule here is a
    # statement about a registry row; this one is a statement about the DECLARATION, because
    # no row can express it — the row looks the same whichever origin `relations` is
    # declared with, and what changes is what --refresh does to it.
    #
    # It is stated because the wrong declaration is SILENT in the direction that loses data.
    # Declared SCRAPED, the field is skipped by the survival comparison below on the grounds
    # that the refresh rewrites it, so the curated entries a refresh drops are dropped
    # behind a rule that passed — which is #178 in a new field: `note` has two origins, no
    # way to tell them apart, and a hand-written note is destroyed by --refresh with nothing
    # to report it. A field nobody declared at all is `declared-field`'s to report, on the
    # rows that carry it.
    # THE SAME STATEMENT ABOUT `name`, WHICH HOLDS TWO ORIGINS ACROSS ROWS RATHER THAN
    # ACROSS ENTRIES (#168). An established statutory name is curation nothing upstream
    # produces; an unverified OAR title is exactly what the chapter page prints. Declared
    # SCRAPED, the survival comparison SKIPS the key on the grounds that the refresh rewrites
    # it — and a reviewed statutory name is then replaced by a publisher's spelling with
    # nothing reporting it, which is the false pass a gate must never produce. Declared
    # CURATED, preserve_curated()'s "copy it if the rebuilt row has not got it" never fires,
    # because the rebuilt row always has this key: the statutory name is lost, and the
    # survival comparison does report that. Only PER_ROW makes preserve_name() the thing that
    # decides, per row, from the basis the row states.
    # AND PER_ROW IS EXACTLY THE NAME PAIR, WHICH IS THE OTHER HALF OF THE SAME STATEMENT.
    # `preserve_name()` carries every PER_ROW key, and what it consults to decide is
    # `name_basis` — a provenance that speaks for `name` and for nothing else. So a THIRD
    # field declared PER_ROW would be carried, or dropped, on a claim about a different
    # field's origin, silently: the survival comparison would pass either way, because the
    # carry is consistent, just wrong about what it is carrying. This is the same reason
    # `relation-origin` exists one field over — a field whose origin nothing states is a
    # field --refresh either freezes or destroys with nothing to report which.
    for key in sorted(per_row - set(NAME_KEYS)):
        failures.append(Failure(
            "name-origin", "FIELDS",
            f"{key!r} is declared PER_ROW, and the only thing that decides a PER_ROW field's "
            f"origin is {NAME_BASIS_KEY!r} — which says where this row's NAME came from and "
            f"nothing about {key!r}. preserve_name() would carry it, or drop it, on another "
            "field's provenance"))

    for key in NAME_KEYS:
        field = fields.get(key)
        if field is not None and field.origin != PER_ROW:
            failures.append(Failure(
                "name-origin", "FIELDS",
                f"{key!r} is declared {field.origin.upper()} — a row whose statutory name "
                f"has been established from its enabling authority holds curation --refresh "
                f"must carry across, and a row still carrying its unverified OAR title holds "
                f"a value --refresh rebuilds from the chapter page, so no whole-field origin "
                f"is true of it and it must be declared PER_ROW, which is what makes "
                f"preserve_name() read {NAME_BASIS_KEY!r} to decide"))

    relations_field = fields.get(RELATION_KEY)
    if relations_field is not None and relations_field.origin != MERGED:
        failures.append(Failure(
            "relation-origin", "FIELDS",
            f"{RELATION_KEY!r} is declared {relations_field.origin.upper()} — it holds "
            f"entries --refresh regenerates ({OAR_INDEX}) beside entries only curation "
            "produces (statute, DAS), so no whole-field origin is true of it and it must "
            "be declared MERGED, which is what makes preserve_relations() merge it entry "
            "by entry"))

    # CALLING A FIELD SCRAPED IS A CLAIM ABOUT THE CODE, so it is checked against the code.
    # The survival comparison below skips scraped fields on the grounds that the refresh
    # rewrites them; a curated field wrongly declared SCRAPED would therefore be skipped
    # while a real --refresh dropped it — a false pass, which is the one outcome a gate must
    # not produce. `scraped_entry()` is the only thing that writes a scraped field, so its
    # own key set settles the question. The probe passes a TRUTHY note on purpose: the
    # constructor omits that key when a chapter page parsed fine, which is most of the time.
    written = set(scraped_entry(oar_name="probe", oar_chapter=None, raw_index_name=None,
                                source_url=None, note="probe"))
    # A MERGED FIELD IS WRITTEN BY THE REFRESH TOO, and is held to the same claim. The
    # refresh does not own everything `relations` holds, but it does rebuild the entries it
    # owns — so the constructor must produce the key, and a MERGED field the constructor
    # never writes is one the refresh drops IN FULL, curated entries and all. Keeping both
    # origins in this rule is what stops declaring a field MERGED from becoming a way to be
    # exempt from it.
    # A PER_ROW FIELD IS WRITTEN BY THE REFRESH TOO, on the rows the refresh owns it for, so
    # it is held to the same claim for the same reason: the constructor must produce the key,
    # or every row that has NOT been reviewed loses its name entirely on the next refresh.
    produced = scraped | merged | per_row
    for key in sorted(produced - written):
        failures.append(Failure("scraped-field", "FIELDS",
                                f"{key!r} is declared {fields[key].origin.upper()} but "
                                "scraped_entry() does not write it — --refresh would drop "
                                "it"))
    for key in sorted(written - produced):
        failures.append(Failure("scraped-field", "FIELDS",
                                f"scraped_entry() writes {key!r}, which FIELDS does not "
                                "declare SCRAPED, MERGED or PER_ROW"))

    # WHAT A --refresh WOULD LEAVE BEHIND. Everything above reads the registry as it stands;
    # this reads it as it would stand after the command that rebuilds it, which is the only
    # place curation has ever been lost. Compared for every field that is NOT scraped,
    # allowlist-style: whatever the refresh does not write, it has to preserve.
    #
    # A row with no OAR name or no slug is one the simulation cannot run on at all: the
    # refresh derives the slug from the chapter page's title, so there is nothing to rebuild
    # and nothing to compare. Such a row is REPORTED as unevaluated rather than crashed on or
    # quietly left out of the comparison — "could not check" is never reported as "is not
    # there" (CONTEXT.md).
    #
    # IT IS THE OAR NAME THAT DECIDES THIS, NOT `name`, SINCE #168. The two held the same
    # bytes on all 189 rows, so which one was read made no difference to the answer and every
    # difference to what the answer meant: `name` is the statutory name now, and a body whose
    # statutory name has been established still has a slug the refresh derives — from the
    # chapter title, which is the only name the scrape can see.
    simulatable, unevaluable = [], []
    for i, o in rows:
        (simulatable
         if isinstance(o.get("oar_name"), str) and isinstance(o.get("slug"), str)
         else unevaluable).append((i, o))
    for i, o in unevaluable:
        failures.append(Failure("survives-refresh", _row_id(o, i),
                                "no oar_name or no slug, so a refresh cannot be simulated "
                                "against this row — it is unchecked, not clean"))
    survivors = simulate_refresh([o for _, o in simulatable], curated_keys=curated,
                                 merged_keys=merged, per_row_keys=per_row)
    for i, o in simulatable:
        got = survivors.get(o.get("slug"))
        if got is None:
            failures.append(Failure("survives-refresh", _row_id(o, i),
                                    "--refresh would not produce this row and nothing "
                                    "preserves it — the row, and every curated field on "
                                    "it, would be gone"))
            continue
        for key in o:
            if key in scraped:
                continue
            if key not in got:
                failures.append(Failure("survives-refresh", _row_id(o, i),
                                        f"--refresh would drop {key!r} — it is not "
                                        "scraped, so only CURATED_KEYS can carry it "
                                        "across"))
            elif key in merged and isinstance(o[key], list):
                # ENTRY BY ENTRY, because the field as a whole is not one claim. A
                # comparison of the two lists would report a curated relation the merge
                # dropped and a scrape-derived one the refresh rewrote as the same failure,
                # and name neither — while the row's OTHER relations, which survived
                # perfectly well, would be printed alongside as though they were at risk.
                #
                # ADDING an entry is not reported here, and since #174 the simulation
                # cannot add one at all: it replays the index's placement from the row's own
                # `oar-index` entry, so it rebuilds exactly the entries that are already
                # there. Reporting an addition under a rule about SURVIVAL would in any case
                # tell a reader the refresh is about to lose something when it is about to
                # fill something in.
                for entry in o[key]:
                    if entry not in (got[key] if isinstance(got[key], list) else []):
                        failures.append(Failure(
                            "survives-refresh", _row_id(o, i),
                            f"--refresh would not leave the relation {entry!r} behind — an "
                            "entry the scrape regenerates comes back only as the scrape "
                            "writes it, and every other entry survives only because "
                            "preserve_relations() carries it across"))
            elif got[key] != o[key]:
                failures.append(Failure("survives-refresh", _row_id(o, i),
                                        f"--refresh would change {key!r} from {o[key]!r} "
                                        f"to {got[key]!r}"))
    return failures


def cmd_check(catalog_path=None) -> int:
    """Report every contract violation in the committed registry. Exit 1 if any.

    `catalog_path` is a PARAMETER, defaulting to `CATALOG`, for the same reason
    `check_registry()`'s own three parameters are (its docstring): so --selftest can point
    this at a path that does not exist and watch `readable-registry` fire through the real
    command line, not only through `check_registry()`'s own in-memory early return. Before
    #320 this guard was a bare `print(f"FAIL [readable-registry] ...")` -- the rule's name
    spelled as text with no `Failure` behind it, invisible to `_LEDGER.fired` and to the AST
    scan alike, and free to drift from the declared spelling with nothing to notice. It now
    constructs the same `Failure` the loop below prints, so there is exactly one call site
    that emits `readable-registry` for a missing file, and one `__str__` that formats it."""
    catalog_path = CATALOG if catalog_path is None else catalog_path
    if not catalog_path.exists():
        print(Failure("readable-registry", str(catalog_path), "no registry to check"),
              file=sys.stderr)
        return 1
    cat = load()
    failures = check_registry(cat)
    for f in failures:
        print(f, file=sys.stderr)
    orgs = cat.get("organizations") or []
    if failures:
        print(f"\n{len(failures)} contract violation(s) across {len(orgs)} row(s)",
              file=sys.stderr)
        return 1
    curated = sum(1 for o in orgs if isinstance(o, dict) for k in o if k in CURATED_KEYS)
    print(f"{len(orgs)} rows against {len(FIELDS)} declared fields; "
          f"{curated} curated value(s) and "
          f"{sum(1 for o in orgs if isinstance(o, dict) and o.get('manual'))} manual row(s) "
          "survive a simulated --refresh")
    # HOW MANY CHAPTER PAGES A --refresh FETCHES (#279), printed rather than left for two
    # other scripts' docstrings to state from memory.
    print(f"chapter pages: {chapter_census(orgs)}")
    # THE ENABLING AUTHORITY'S CENSUS, PRINTED RATHER THAN LEFT TO BE COUNTED.
    print(f"enabling authority: {authority_census(orgs)}")
    # WHAT EACH ROW'S `name` IS (#168), on the same terms: `name` is the statutory name now,
    # and how many rows actually hold one is a fact a reader of this registry needs on every
    # run rather than a number to go and count.
    print(f"name: {name_census(orgs)}")
    # THE RELATIONS' CENSUS, for the same reason and one more: the kind is `undetermined` on
    # every relation the registry holds, and that is a state to REPORT on every run rather
    # than a default to stop noticing (#173 is what decides them).
    rows = [o for o in orgs if isinstance(o, dict)]
    print(f"relations: {relation_census(rows)}")
    # WHAT THE RETIRED POINTER USED TO WITNESS (#174), counted rather than assumed.
    print(f"placements: {placement_witnesses(rows)}")
    return 0


# ------------------------------------------------------------------------------ selftest
#
# THE PROOF THAT THE GATE ABOVE CAN FAIL. Every rule --check enforces is exercised here
# against a synthetic registry built to violate exactly one of them, because a check nobody
# has watched fail is not known to work — it is only known to be quiet. Synthetic fixtures:
# no network, no read of the committed registry.


def _fixture():
    """A registry that passes every rule. Each case below breaks exactly one thing."""
    das = scraped_entry(oar_name="Department of Administrative Services", oar_chapter="125",
                        raw_index_name="Dept. of Administrative Services",
                        source_url=f"{BASE}/rules/oar_chapter_125")
    write_das_agency_number(das, "107")   # written the way every writer writes it
    # AN IMPOSSIBLE CITATION ON PURPOSE. This gate checks the FORM of an authority and
    # resolves nothing (link_enabling_authority.py --check does that, against the mirror),
    # and ORS has no chapter 999 — so the fixture exercises the field without asserting
    # what created the Department of Administrative Services, which is a question nobody
    # has reviewed. A real citation here would read as a verdict.
    das["enabling_authority"] = "ORS 999.999"
    # A ROW WHOSE STATUTORY NAME HAS BEEN ESTABLISHED, beside two that carry their OAR title
    # (#168). Both states have to be in the fixture: every rule below is vacuously true of a
    # registry where no row has ever been reviewed, and `preserve_name()` — the only thing
    # standing between a reviewed name and the next --refresh — would never run at all.
    #
    # THE NAME IS MADE UP, like the citation above and for the same reason. This gate checks
    # that a row can SUPPORT the claim it makes about its own name; what ORS 999.999 actually
    # calls the Department of Administrative Services is a question nobody has reviewed, and
    # a real statutory name here would read as a verdict on it.
    das["name"] = "The Oregon Department of Administrative Services"
    das[NAME_BASIS_KEY] = ENABLING_AUTHORITY_NAME
    cfo = scraped_entry(oar_name="Chief Financial Office", oar_chapter="122",
                        raw_index_name="Chief Financial Office",
                        source_url=f"{BASE}/rules/oar_chapter_122")
    cfo["parent_chapter"] = das["oar_chapter"]
    # THE TWO ORIGINS IN ONE LIST, which is the whole of what this field is: the OAR
    # index's placement, which --refresh regenerates, and a statute's, which nothing
    # upstream produces and only the per-entry merge carries across. A fixture holding
    # only the first would let every rule below pass while a refresh destroyed curation.
    # The citation is impossible on purpose, for the reason `enabling_authority` above
    # gives: this gate checks the FORM of an authority and resolves nothing, and a real
    # ORS section here would read as a verdict on a relation nobody has reviewed.
    # THE BASIS IS THE OTHER HALF OF THE CURATED ENTRY (#173): `source` says a statute places
    # this body under that one, `basis` says a reviewed authority is what settled the kind.
    # The fixture carries the REVIEWED basis rather than the proposed one because the proposed
    # basis is the deviation ADR 0004 records, and a fixture is not the place to normalise it.
    cfo["relations"] = [index_relation(das["slug"]),
                        {"target": das["slug"], "source": "statute",
                         "kind": ADMINISTERED_BY, "basis": REVIEWED_AUTHORITY,
                         "authority": "ORS 999.998"}]
    # CURATOR PROSE ON A ROW `manual` DOES NOT PROTECT (#178): `cfo` is scraped, not manual,
    # which is exactly the row `curator_note` has to survive a refresh on for AC1 ("the
    # note is protected... not left to the regenerator's behaviour") to be a proof and not
    # an assumption — CURATED_KEYS carries it across the same way it carries
    # `das_agency_number` on `das` above. The text is made up, for the reason the citation
    # above is: it is not a claim about the real Chief Financial Office.
    cfo["curator_note"] = "fixture-only curator prose, not a claim about the real CFO"
    gov = scraped_entry(oar_name="Office of the Governor", oar_chapter=None,
                        raw_index_name=None, source_url=None)
    gov["manual"] = True
    gov["aliases"] = ["Governor's Office"]
    # THE TOP-LEVEL `note`, WHICH `note-covers-fields` (#185) READS. Built from FIELDS
    # itself rather than typed out, so adding a field to FIELDS without also touching this
    # fixture does not itself start failing every case in _CASES — the same reason
    # CURATED_KEYS is derived rather than restated. `_case_note_missing_a_declared_field`
    # below is what actually exercises that rule; this is only the clean baseline every
    # other case's fixture must already pass. It is also the baseline `note-agrees-
    # with-refresh` compares against in the selftest loop — `check_registry()` is called
    # there with `refresh_note` set to THIS string, not the real `REGISTRY_NOTE`, since
    # this fixture is a synthetic stand-in and was never meant to be the real prose.
    return {"note": "fixture note naming every field: " + ", ".join(sorted(FIELDS)),
            "organizations": [das, cfo, gov]}


# THE FIXTURE'S OWN CHAPTER-PAGE COUNT, for `chapter-page-count-current` (#279): the fixture
# holds 2 chaptered rows (`das`, `cfo`) and 1 chapterless one (`gov`), never 170 — a --selftest
# run that checked this fixture against the REAL two scripts' real prose would fail
# regardless of whether either script says the truth, which is not a demonstration of
# anything. No `_CASES` mutation changes which rows carry `oar_chapter`, so this stays "2"
# for all of them.
_FIXTURE_CHAPTER_PAGE_DOCS = {
    "fixture.py": "a refresh re-fetches all 2 chapter pages from the mirror.",
}


def _case_undeclared_field(cat):
    """A field nobody declared. It may be curation --refresh is about to destroy, and a
    field we could not evaluate must never be reported as one that passed. The name is
    deliberately made up: `das_agency_number` is a field ADR 0003 says the registry is
    GOING to carry, and using it as the example of an illegitimate field would read as a
    verdict on a decision that has already been taken. `oar_name` was the other such
    example until the registry started carrying one, which is the second reason to make
    the name up — a declared field stops demonstrating anything here."""
    cat["organizations"][0]["headcount"] = 412


def _case_missing_required_field(cat):
    """A row that dropped a field every row carries. `relations: []` and no `relations` at
    all read the same to a consumer — a body under nothing — and are not the same claim:
    the first says this registry places it under no other, the second says nobody asked
    (CONTEXT.md). It is the statement `parent_slug: null` used to make, over the field that
    replaced the pointer (#174)."""
    del cat["organizations"][1][RELATION_KEY]


def _case_missing_oar_name(cat):
    """A row that carries a `name` but no `oar_name`. The whole point of landing the OAR
    name in its own field is that consumers can join on it INSTEAD of `name`, so a row
    missing one is a row those joins silently lose — and it is invisible from the outside,
    because `name` still holds the same string today. It stops holding it (ADR 0003), and
    then the gap is a body no OAR-derived join resolves."""
    del cat["organizations"][1]["oar_name"]


def _case_missing_name(cat):
    """A row that dropped `name` — the body's statutory name since ADR 0003, and one of the
    two names a consumer can resolve it by. Every row is required to carry both, and a row
    carrying only the rules index's title is one that no longer states what the body is
    called, which is the registry's whole subject."""
    del cat["organizations"][1]["name"]


def _case_budget_agency_code_reappears(cat):
    """The retired key, written back onto a row exactly the way a stale writer or a bad
    merge would put it there — #177's own mutation proof (its acceptance criterion 2 is
    literally "--check fails if it reappears"). Every consumer that migrated to
    `das_agency_number` (oregon-budget#49, oregon-kpm, oregon-stories) already ignores this
    key; the risk this rule guards against is a FUTURE writer resurrecting it, silently,
    with nothing to notice until a sibling corpus reads two disagreeing sources again."""
    cat["organizations"][0]["budget_agency_code"] = cat["organizations"][0][
        "das_agency_number"]


def _case_enabling_authority_left_blank(cat):
    """`enabling_authority: null`. The key is present, so a human has been here; the value
    says nothing, so what they concluded is lost. Every consumer reads a null and an absent
    key alike, which turns "nobody has looked yet" into "this body has no enabling
    authority" — the substitution CONTEXT.md's overriding rule forbids."""
    cat["organizations"][1]["enabling_authority"] = None


def _case_enabling_authority_absent_without_a_reason(cat):
    """A reviewed absence with nothing behind it. `none:` alone records that someone
    declined to record an authority, not that they found there is none — and ADR 0004 is
    explicit that a `part_of` unit's missing authority is "a decision with a reason and not
    a gap". Without the reason the two are the same string."""
    cat["organizations"][1]["enabling_authority"] = "none:"


def _case_enabling_authority_with_stray_whitespace(cat):
    """A citation that is right and a string that is not. Three sibling corpora join on this
    file as YAML, and a leading space makes the value they read differ from the value the
    reviewed table holds — a difference no reader sees and every comparison does."""
    cat["organizations"][1]["enabling_authority"] = " ORS 999.999"


def _case_enabling_authority_that_almost_records_an_absence(cat):
    """A reviewed absence spelled some other way. `None recorded` says what a reviewer
    concluded and says it in a form nothing can parse, so it is read as an authority by
    anything looking for one and as prose by anything looking for a reason."""
    cat["organizations"][1]["enabling_authority"] = "None recorded"


def _case_enabling_authority_that_is_not_an_authority(cat):
    """A value that talks about an authority without citing one. The field is an AUTHORITY
    (ADR 0003) — an ORS section, a constitutional article, or an executive order — and
    prose in its place is a claim no reader can check and no gate can resolve."""
    cat["organizations"][1]["enabling_authority"] = "created by statute"


def _case_enabling_authority_session_law_near_miss(cat):
    """A session-law citation one punctuation mark from the accepted spelling (#211) —
    `_proof_session_law_form_boundary` proves the ten near misses refused at the
    `classify_authority` level directly; this proves the SAME boundary is what the registry's
    own row-level contract enforces, not a rule that exists only in the function that backs
    it."""
    cat["organizations"][1]["enabling_authority"] = "Oregon Laws 1975, Chapter 789"


def _case_oar_name_that_matches_nothing(cat):
    """An `oar_name` that is present, is a string, and names nothing — so `required-field`
    passes it and every consumer reads it as a name. The body is then unfindable by the OAR
    name, which is the name all of its rule documents carry, and the search that was
    supposed to survive ADR 0003 has lost it silently."""
    cat["organizations"][1]["oar_name"] = "   "


def _case_statutory_name_that_matches_nothing(cat):
    """The same hole under the other name. A body findable only by the name the rules index
    prints is one that stops being findable by the name its enabling authority gives it —
    the half of the pair ADR 0003 promotes."""
    cat["organizations"][1]["name"] = "   "


def _case_name_basis_this_registry_has_no_meaning_for(cat):
    """A basis nobody declared. The field's two words are the two states #168 exists to keep
    apart — a statutory name read off an authority, and an OAR title nobody has reviewed —
    and a third word published there is a provenance no reader can weigh and no gate can act
    on. Widening the allowlist is a decision taken beside NAME_BASES, which is what makes it
    deliberate."""
    cat["organizations"][0][NAME_BASIS_KEY] = "sounds-official"


def _case_statutory_name_with_no_authority_to_support_it(cat):
    """A row claiming its `name` is the statutory name with no enabling authority on it. The
    statutory name is the name a body's ENABLING AUTHORITY gives it (ADR 0003), so a row
    making that claim while recording no authority has nothing behind it — it is `manual:
    true` again, in the field ADR 0003 calls the risky half: an assertion that records
    someone decided and never what decided it.

    THE ROW STILL LOOKS PERFECT WITHOUT THIS RULE, which is why it needs one. The name is a
    non-empty string, `findable-by-both-names` reaches the body by it, and every consumer
    reads it as what Oregon law calls this body."""
    del cat["organizations"][0]["enabling_authority"]


def _case_statutory_name_resting_on_a_reviewed_absence(cat):
    """A statutory name on a body reviewed as having NO enabling authority. `none: <reason>`
    is a finding — someone looked and there is nothing that created this body separately —
    so there is no authority for a name to have been read off, and a row asserting both says
    the two opposite things about one body at once. It is the same contradiction
    `part-of-body-that-carries-an-enabling-authority` refuses one field over."""
    cat["organizations"][0]["enabling_authority"] = no_authority_value(
        "Part of DAS, so nothing separate is enabled")


def _case_unverified_name_that_is_not_the_oar_title(cat):
    """A row that says its `name` is the unverified OAR title and holds something else. ADR
    0003 promotes `name` and #168 requires that no row's name be BLANKED by the promotion:
    a body with no established statutory name keeps the value it had, which is its OAR
    chapter title. The row's own basis is what makes that checkable — an unreviewed row holds
    the chapter title and nothing else, so a truncation, a hand-written guess or an empty
    string here is a name that nothing scraped and nobody read.

    A BLANKED NAME IS THE CASE THIS IS REALLY ABOUT. `""` reads as a name to every consumer
    that checks for the key, and the body it names becomes unfindable by the only name it
    has — which is what makes deleting information a way to pass a criterion, and this is
    what stops it."""
    cat["organizations"][1]["name"] = ""


def _case_relation_with_no_source(cat):
    """A relation that does not say who places this body under that one. The source is what
    lets one list hold the OAR index's placement beside a statute's (ADR 0003 keeps the
    disagreement rather than reconciling it), and it is what `preserve_relations()` reads to
    decide whether --refresh regenerates the entry or carries it across — so a sourceless
    entry is one the refresh cannot classify. #178 is what that costs in a field that has
    it: `note` is written both by the scrape and by hand, says nowhere which it is, and a
    hand-written note is destroyed by --refresh with nothing to report it."""
    del cat["organizations"][1]["relations"][1]["source"]


def _case_relation_with_no_kind(cat):
    """A relation that says which body and not in what way. `undetermined` is a WORD this
    registry writes (#171) rather than a key it leaves off, because the two are not the same
    claim: the word says the relation is real and nobody has established which of ADR 0004's
    two kinds it is, and an absent key says nothing at all — which every consumer is free to
    read as either kind. "Could not check" is never reported as "is not there"
    (CONTEXT.md). It is the CURATED entry that is broken here, so the case breaks exactly
    one rule: the same edit to the scrape-derived entry beside it is a hand edit the refresh
    would rewrite, which is `relation-hand-edited-on-a-scraped-entry` below."""
    del cat["organizations"][1]["relations"][1]["kind"]


def _case_relation_of_an_unrecorded_kind(cat):
    """A kind this registry has no meaning for. ADR 0004 defines two — *part of* and
    *administered by* (CONTEXT.md) — and #171 adds `undetermined` for the relation nobody
    has decided between them yet; 37 of the 81 are still in that state and 44 are
    `administered_by` (#173). A fourth word published in the field is a claim about Oregon
    law that no reader can resolve and no ADR has taken; widening the allowlist is that
    decision, taken deliberately, and this is what makes it deliberate."""
    cat["organizations"][1]["relations"][1]["kind"] = "supervised_by"


def _case_relation_kind_with_no_basis(cat):
    """A kind with nothing behind it. #173 derives kinds from evidence of two different
    strengths — a PROPOSED enabling-authority candidate nobody has read, and a REVIEWED
    authority — and a kind that does not say which it came from is indistinguishable from
    the other, which is the failure `manual: true` was retired for (ADR 0003): an assertion
    records that someone decided, never what decided it. `undetermined` is the one kind that
    needs no basis, because it records no decision."""
    del cat["organizations"][1]["relations"][1]["basis"]


def _case_relation_basis_this_registry_has_no_meaning_for(cat):
    """A basis nobody declared. The three RELATION_BASES differ in STRENGTH and in which
    kind they decide — an unreviewed proposal and a reviewed authority both decide
    `administered_by` (#173), a reviewed absence decides `part_of` (#222) — so the value is
    what a reader weighs the kind by, and a fourth word published there is a weight nothing
    can read. Widening the allowlist is a decision taken beside RELATION_BASES, which is
    what makes it deliberate."""
    cat["organizations"][1]["relations"][1]["basis"] = "seemed-right"


def _case_relation_basis_on_a_relation_that_decided_nothing(cat):
    """A basis on an `undetermined` relation. `undetermined` says nobody has established
    which of ADR 0004's two kinds this is, so there is no decision for a basis to be the
    basis OF — and a row carrying both says a decision was made and declines to say what it
    was. It is also what a half-finished derivation leaves behind, which is the state this
    rule exists to refuse rather than to publish."""
    cat["organizations"][1]["relations"][0]["basis"] = REVIEWED_AUTHORITY


def _case_administered_by_citing_no_authority(cat):
    """An `administered_by` relation with no citation. ADR 0004 is explicit about what the
    citation buys and why the relation is worth encoding at all: "Recording that the commodity
    commissions are administered by the Department of Agriculture is less useful than
    recording that ORS 576.066 is what makes that true." Uncited, the kind is the bare parent
    pointer again, with a stronger word on it — it asserts that Oregon law separately
    constitutes this body and names nothing a reader can check. `part_of` is not held to this:
    it records that there is nothing separate to cite."""
    del cat["organizations"][1]["relations"][1]["authority"]


def _case_relation_authority_is_a_different_bodys_own(cat):
    """An `administered_by` relation citing another row's OWN, exclusive `enabling_authority`
    (#212). `das` above carries `enabling_authority: "ORS 999.999"` and is the only row that
    does, so that citation is what constitutes `das` as a body — not evidence of what a
    DIFFERENT row is placed under. `cfo`'s administered_by relation citing it instead is
    exactly the shape `oregon-military-department-office-of-emergency-management` was never
    caught by: it never carried an `enabling_authority` at all, so no gate had anything to
    compare its relation against. This is the gate that omission left missing, proven on a
    row that does carry one."""
    cat["organizations"][1]["relations"][1]["authority"] = cat["organizations"][0][
        "enabling_authority"]


def _case_part_of_body_that_carries_an_enabling_authority(cat):
    """A unit recorded as *part of* its parent while carrying an authority of its own. The
    two say opposite things: ADR 0004 defines *part of* as the case where "there is no
    statute constituting either, because there is no separate body to constitute", and
    CONTEXT.md says such a unit "has no enabling authority because there is nothing separate
    to enable". A row holding both is one where the kind was decided on evidence the row
    itself contradicts, and each consumer believes whichever field it read. A reviewed
    `none: <reason>` is NOT this failure — that value is what a *part of* unit is expected to
    carry."""
    cat["organizations"][1]["relations"][1] = {
        "target": cat["organizations"][0]["slug"], "source": "statute",
        "kind": PART_OF, "basis": REVIEWED_AUTHORITY}
    cat["organizations"][1]["enabling_authority"] = "ORS 999.999"


def _case_part_of_relation_that_cites_an_authority(cat):
    """A *part of* relation with a citation on it. The sibling rule refuses an
    `administered_by` that cites nothing; this refuses the other half of the same claim.
    *Part of* records that nothing separately constitutes the unit, so there is no section
    that makes the relation true — a citation there is either the PARENT's authority written
    on the child, or evidence the unit is separately constituted and the kind is wrong.
    Either way the relation states something no reader can check against the kind beside it.

    Distinct from `part-of-has-nothing-to-enable`, which is about the BODY's
    `enabling_authority`: a row can carry a clean field and a relation that cites, and the
    field rule would pass it."""
    cat["organizations"][1]["relations"][1] = {
        "target": cat["organizations"][0]["slug"], "source": "statute",
        "kind": PART_OF, "basis": REVIEWED_AUTHORITY, "authority": "ORS 999.998"}


def _case_relation_naming_no_body(cat):
    """A relation with no target. It records that somebody placed this body under something
    and loses the something — a hierarchy with one end, which reads as a relation to every
    consumer that counts them and resolves to nothing for every consumer that follows
    them."""
    del cat["organizations"][1]["relations"][1]["target"]


def _case_relation_carrying_an_undeclared_key(cat):
    """A key on a relation entry that this registry does not declare. Same rule as the row
    above it (`declared-field`) and the same reason: a key nobody declared is one nothing
    can say whether --refresh preserves, and a reader has no way to tell curation from a
    typo. `kimd: part_of` is a kind nobody records under a name nothing reads."""
    cat["organizations"][1]["relations"][1]["kimd"] = "part_of"


def _case_relation_authority_that_is_not_an_authority(cat):
    """A relation whose authority cites nothing. ADR 0004 is explicit about what the
    citation buys — "a bare parent pointer states a hierarchy; a cited one states a claim
    about Oregon law that a reader can check" — so prose in that key is the bare pointer
    wearing the citation's clothes, and the reader who goes to check it has nowhere to
    go."""
    cat["organizations"][1]["relations"][1]["authority"] = "administered under statute"


def _case_relation_authority_recording_an_absence(cat):
    """`none: ` and a reason, which is a true thing to say about a BODY and not about a
    relation. `enabling_authority` needs that form because an absent key there means nobody
    has looked (CONTEXT.md's three states); a relation with no authority recorded simply has
    none recorded, and there is no key to leave off — so admitting the form here would put
    two spellings of one state in the file and make the count of cited relations depend on
    which one a writer picked."""
    cat["organizations"][1]["relations"][1]["authority"] = no_authority_value(
        "Part of the department")


def _case_one_source_placing_a_body_under_a_parent_twice(cat):
    """The same source naming the same parent twice. A body holding SEVERAL relations is
    the point of the field — ADR 0003 keeps the disagreement between DAS, the OAR index and
    statute rather than reconciling it — but that is one reading per source, and two entries
    from one source are not a disagreement between sources: they are one reading recorded
    twice, free to say different things, with nothing in the row to say which is current.
    It is also what a broken merge looks like from the outside, since carrying an entry the
    scrape had already regenerated produces exactly this.

    The two differ in their CITATION rather than in their kind, so the case breaks exactly
    one rule: a second entry saying `part_of` would also cite an authority a *part of*
    relation may not carry (`relation-shape`), and be dropped before the uniqueness check
    ever read it — which is how a case starts passing for the wrong reason."""
    entries = cat["organizations"][1]["relations"]
    entries.append(dict(entries[1], authority="ORS 999.997"))


def _case_relation_target_resolves_to_nothing(cat):
    """A relation aimed at no body. Since #174 this is the ONLY statement the registry makes
    about where a body sits, so a dangling target states a hierarchy nobody can check while
    reading as a fact, with no second copy of the placement to catch it. It matters most
    because a relation is FOLLOWED rather than displayed — three-level nesting is two
    relations between three bodies (ADR 0004), and a walk that loses the middle one has no
    way to tell that from a body that had no parent."""
    cat["organizations"][1]["relations"][1]["target"] = \
        "department-of-administrative-service"


def _adopt_manual_row(cat):
    """Give the fixture's manual row a parent, the way the registry's one manual child
    carries one: `oregon-health-authority-equity-and-inclusion-division` sits under the
    Oregon Health Authority on the strength of its own rule-page header, which is recorded
    in the row's `note`. The placement is a `registry` relation with `parent_chapter` set to
    match, so `parent-agrees` stays quiet and the cases below break exactly what they are
    about."""
    das, _cfo, gov = cat["organizations"]
    gov[RELATION_KEY] = [{"target": das["slug"], "source": REGISTRY, "kind": UNDETERMINED}]
    gov["parent_chapter"] = das["oar_chapter"]
    return gov, das


def _case_the_index_places_a_body_under_two_parents(cat):
    """Two `oar-index` entries on one row, naming two parents. The index tree files a body
    under exactly ONE, and --refresh rewrites the entries it owns from that tree — so the
    second is a placement the scrape will never reproduce and destroys unread on the next
    run, in the one field whose whole point is that what the scrape does not own survives.

    `relation-unique` does not reach it: that rule refuses one source naming one parent
    twice, and these name two — which is the shape a real disagreement takes on every OTHER
    source. Until #174 this rule compared the entries against `parent_slug`; there is no
    second copy of the placement to compare with now, so it states what the tree can produce
    instead."""
    cat["organizations"][1][RELATION_KEY].append(index_relation("office-of-the-governor"))


def _case_index_relation_the_index_could_not_have_stated(cat):
    """An `oar-index` relation on a MANUAL row that has a parent. A manual row is one the
    chapter scrape cannot see — that is what the flag means (`preserve_manual`) — so the OAR
    index has stated nothing about where this body sits, and an entry claiming otherwise
    attributes a placement to a publisher that never made it and calls an entry nothing can
    regenerate one the refresh rebuilds. It is also the one row where nothing else would
    notice: the survival simulation preserves a manual row whole, so a hand-written entry on
    it is never compared with what the scrape would have produced. THE ROW IS GIVEN A REAL
    PARENT FIRST, which is the point: `_adopt_manual_row()` records the placement as the
    `registry` relation that is true of it, and the index entry is then added BESIDE that —
    so what fires is this rule, and not `parent-agrees` reporting a chapter with no
    placement behind it. The real row in the registry (one manual child, under the Oregon
    Health Authority) has exactly that shape."""
    gov, das = _adopt_manual_row(cat)
    gov[RELATION_KEY].append(index_relation(das["slug"]))


def _case_authority_hand_edited_onto_a_scraped_entry(cat):
    """A citation written by hand onto the entry the scrape regenerates, with no kind behind
    it. --refresh rebuilds an `oar-index` entry from the index tree every time it runs, and
    #173 carries exactly one thing across that rebuild: a DECISION (`DECISION_KEYS`, led by a
    kind that is not `undetermined`). An authority attached to no decision is not one, so it
    is destroyed on the next refresh — and it is destroyed silently, which is #178 exactly:
    `note` holds the scrape's writing and a human's with no way to tell them apart, and the
    human's goes with nothing to report it. Here the loss is a red build.

    THIS CASE REPLACES `relation-hand-edited-on-a-scraped-entry`, which asserted that a KIND
    on this entry could not survive a refresh. #173 decided the opposite and had to: the
    relation whose kind is being decided is the one the index states, and the only other
    place to put the kind is a second entry claiming a second placement no source made. The
    guard that replaces it is stricter than the one it retires — a kind here needs a `basis`
    (`relation-shape`), and derive_relation_kinds.py --check compares every decided kind
    against the derivation in BOTH directions, so a hand-written one no derivation stands
    behind is reported rather than merely overwritten."""
    cat["organizations"][1]["relations"][0]["authority"] = "ORS 999.997"


def _case_relations_that_are_not_a_list(cat):
    """`relations: null` on a row that carries the key. Every reader of the field takes it
    for a body placed under nothing — `relation_entries()` included, which is what lets the
    rest of the rules keep speaking about the row — and `required-field` passes it, because
    the key is there. The registry's standing distinction is between an absent key and a
    value; this is the case where the value itself has gone missing."""
    cat["organizations"][1]["relations"] = None


def _case_row_is_not_a_mapping(cat):
    """A row no rule can be evaluated against. It must FAIL, not be skipped — a row we
    could not check is never a row that passed."""
    cat["organizations"][2] = "office-of-the-governor"


def _case_duplicate_slug(cat):
    """Two rows, one identity. The slug is the only thing another corpus joins on, so a
    collision silently attributes one body's documents to another — the case --refresh
    already treats as a human decision rather than silent dedup."""
    cat["organizations"][1]["slug"] = cat["organizations"][0]["slug"]


def _case_duplicate_chapter(cat):
    """One OAR chapter claimed by two bodies. Chapter assignment is one-chapter-one-body
    (ADR 0003); two claims means one of them is wrong and nothing says which."""
    cat["organizations"][1]["oar_chapter"] = cat["organizations"][0]["oar_chapter"]


def _case_the_retired_pointer_comes_back(cat):
    """`parent_slug` written onto a row again. #174 removed it because a body's placement
    lives in `relations` and a bare slug cannot say whose reading that placement is, which
    of ADR 0004's two kinds it is, or on what authority — so a pointer that came back would
    be a SECOND statement of where the body sits, free to disagree with the relations beside
    it and invisible to whichever population of consumers read the other one.

    It fires under `declared-field` rather than a rule of its own, and that is the point:
    rows are checked against an ALLOWLIST, so a retired field needs nothing added to refuse
    it and no blocklist to be forgotten from. This case is what proves the allowlist closed
    behind the field #174 took out. The value is a REAL slug on purpose — a dangling one
    would be refused for pointing nowhere, which is a different rule and would let this case
    pass while the allowlist quietly did not hold."""
    cat["organizations"][1]["parent_slug"] = "department-of-administrative-services"


def _case_parent_chapter_disagrees(cat):
    """`parent_chapter` naming a chapter its parent does not hold. The field is the OAR
    chapter of the body the row's relations place it under, written a second time — and
    consumers use whichever of the two they happened to read, so the disagreement resolves
    differently per consumer."""
    cat["organizations"][1]["parent_chapter"] = "999"


def _case_parent_chapter_on_a_body_under_nothing(cat):
    """A `parent_chapter` with no relation behind it. The chapter names the parent's
    chapter, so a row under nothing has none to name — and the field left standing is a
    parent a consumer can resolve by chapter and cannot find in `relations`, which is the
    two-copies failure in the direction that has no second copy."""
    cat["organizations"][1][RELATION_KEY] = []


def _case_parent_chapter_where_the_sources_disagree(cat):
    """A body two sources place under two different parents, still carrying one
    `parent_chapter`. ADR 0003 keeps that disagreement rather than reconciling it, and one
    chapter cannot hold two readings: whichever it names publishes one source's placement as
    the registry's, silently, to every consumer that resolves the parent by chapter."""
    cat["organizations"][1][RELATION_KEY].append(
        {"target": "office-of-the-governor", "source": "das", "kind": UNDETERMINED})


def _case_slug_the_scrape_would_not_produce(cat):
    """A slug hand-edited away from the one slugify() derives from the name. --refresh
    rebuilds the row under the DERIVED slug, so the hand-edited row — and the curated
    fields riding on it — is not preserved onto anything; it just stops existing.

    The number is written by write_das_agency_number() rather than hand-assigned, same as
    every other writer since #177 — that function is THE ONE PLACE das_agency_number is
    written, not a special case for this fixture."""
    write_das_agency_number(cat["organizations"][1], "107")
    cat["organizations"][1]["slug"] = "cfo"


def _case_field_the_refresh_drops(cat):
    """A non-scraped field that nothing preserves. `manual: false` is not the flag that
    keeps a row whole, so the row is rebuilt from the scrape and the key disappears —
    the silent-loss failure mode CURATED_KEYS exists to prevent, in a field that is not
    in it."""
    cat["organizations"][1]["manual"] = False


def _case_row_the_simulation_cannot_run_on(cat):
    """A row with no OAR name. The refresh derives a slug from the chapter page's own title,
    so there is nothing to simulate — and a row that could not be evaluated must be REPORTED
    as unevaluated, never left out of the report as though it had passed.

    It is the OAR name and no longer `name` that decides this (#168): the two held identical
    bytes on every row until ADR 0003 split them, and the scrape can only ever see the
    chapter title. The same deletion as `missing-oar-name` above, which is deliberate — one
    edit breaks two rules, and a case asserts one, so each gets its own."""
    del cat["organizations"][0]["oar_name"]


def _case_note_that_is_not_a_scrape_shape(cat):
    """A hand-typed sentence in `note`, which is scrape-only now (#178, CONTEXT.md,
    "Relation source"): `cmd_refresh()` writes one of exactly three sentences
    (`NOTE_SCRAPE_TEMPLATES`, above `cmd_refresh()`) and nothing else may live in the
    field, `manual` or not — curator prose belongs in `curator_note` (CURATED) instead.
    The previous version of this rule required `manual` rather than a recognised shape,
    which refused the scrape's own fetch-failure and title-not-parseable sentences on
    every ordinary row where they legitimately fire; this fixture value is deliberately
    NOT one of the three, on `cfo`, which carries no `manual` flag either — so the case
    also proves the fix does not silently start requiring `manual` again."""
    cat["organizations"][1]["note"] = "confirmed by phone with the agency, 2026-08-20"


def _case_note_missing_a_declared_field(cat):
    """The registry's own top-level `note` stops naming one field FIELDS declares — the
    defect #185 measured against the real committed file's own history: 669 characters
    naming 4 of the then-14 row fields from 2026-07-20 to 2026-08-21, then two more
    revisions that each still fell short (4,299 naming 9 of 13, then 5,260 naming 11 of
    15), then #178 grew the field set to 16 with `curator_note` while the note stayed at
    5,260, unchanged — before anything compared the two. `curator_note` is the field
    actually missing on this branch before the fix in this commit, so the case is
    grounded in the real drift rather than a field invented for the fixture."""
    cat["note"] = cat["note"].replace("curator_note, ", "").replace(", curator_note", "")
    assert "curator_note" not in cat["note"]   # the mutation removed the word, not a copy


def _case_note_omits_a_field_whose_name_is_a_substring_of_another(cat):
    """`note-covers-fields` matched with bare `in` before this fix, which cannot fire for
    `note` (a substring of `curator_note`) or `name` (a substring of `name_basis`,
    `oar_name`, `raw_index_name` and `curator_note`) as long as every other declared
    field is still named — `note` is one of the five fields #185 found the pre-fix
    registry note actually missing, so the bare bar could not have caught a recurrence
    of that exact drift. This case drops `note` and `name` from the fixture note while
    leaving every longer identifier that contains their letters in place, the shape a
    prose sentence takes when it stops mentioning a field on its own."""
    remaining = [k for k in sorted(FIELDS) if k not in ("note", "name")]
    cat["note"] = "fixture note naming every field: " + ", ".join(remaining)
    assert "curator_note" in cat["note"] and "name_basis" in cat["note"]  # the longer
    # identifiers stay, so a substring match would wrongly call `note` and `name` covered


def _case_note_diverges_from_what_refresh_would_write(cat):
    """`note-covers-fields` only checks that every FIELDS name appears somewhere in the
    note's prose, which says nothing about whether the prose still AGREES with what
    `cmd_refresh()` would write next — #185's own root cause was exactly a note whose
    WORDING fell behind while nothing compared the two copies. This appends a sentence
    without touching a single field name, so `note-covers-fields` stays silent and only
    `note-agrees-with-refresh` — which compares against the fixture's own baseline note
    here, `REGISTRY_NOTE` on a real registry — catches the divergence."""
    cat["note"] += " A sentence cmd_refresh() would never write."


def _case_note_chapterless_count_stale(cat):
    """The note's own "null on N of the M chapterless" claim, wrong against the fixture's
    own data (code review of #281: the real committed note carried this exact sentence
    unchanged, at "14 of the 19", through the commit that made the true count "15 of the
    20" — surviving both `note-covers-fields`, which only proves every FIELDS name is
    named, and `note-agrees-with-refresh`, which only proves the committed note matches
    `REGISTRY_NOTE` and says nothing about whether `REGISTRY_NOTE` itself is still true).
    The fixture holds exactly one chapterless row (`gov`), which carries no `source_url`
    either, so the true sentence would read "null on 1 of the 1 chapterless rows"; this
    appends "0 of 1", which the fixture's own two rows above (`das`, `cfo`, both chaptered)
    contradict."""
    cat["note"] += " null on 0 of the 1 chapterless rows, not all of them."


def _case_registry_emptied(cat):
    """Every row gone. A gate that reports a registry with no bodies in it as clean is a
    gate that passes without checking anything — and every rule below is vacuously true of
    an empty list, so this one has to be stated separately."""
    cat["organizations"] = []


def _case_organizations_is_not_a_list(cat):
    """`organizations:` holding something that parsed but is not a list — a scalar, a
    mapping, a YAML typo one indent off — which is a different failure from an empty list
    (`registry-populated`, above) and from a row that is not a mapping (`readable-row`,
    below): this one is caught before either of those ever gets to run, by the same early
    return `cmd_check()`'s own missing-file guard now shares a spelling with (#320: this
    rule had 24 siblings each demonstrated in `_CASES` or `_PROOFS` and none of its own)."""
    cat["organizations"] = None


_CASES = [
    ("undeclared-field", _case_undeclared_field, "declared-field"),
    ("relations-that-are-not-a-list", _case_relations_that_are_not_a_list,
     "relation-shape"),
    ("name-basis-this-registry-has-no-meaning-for",
     _case_name_basis_this_registry_has_no_meaning_for, "statutory-name-basis"),
    ("statutory-name-with-no-authority-to-support-it",
     _case_statutory_name_with_no_authority_to_support_it, "statutory-name-basis"),
    ("statutory-name-resting-on-a-reviewed-absence",
     _case_statutory_name_resting_on_a_reviewed_absence, "statutory-name-basis"),
    ("unverified-name-that-is-not-the-oar-title",
     _case_unverified_name_that_is_not_the_oar_title, "statutory-name-basis"),
    ("relation-with-no-source", _case_relation_with_no_source, "relation-shape"),
    ("relation-with-no-kind", _case_relation_with_no_kind, "relation-shape"),
    ("relation-of-an-unrecorded-kind", _case_relation_of_an_unrecorded_kind,
     "relation-shape"),
    ("relation-kind-with-no-basis", _case_relation_kind_with_no_basis, "relation-shape"),
    ("relation-basis-this-registry-has-no-meaning-for",
     _case_relation_basis_this_registry_has_no_meaning_for, "relation-shape"),
    ("relation-basis-on-a-relation-that-decided-nothing",
     _case_relation_basis_on_a_relation_that_decided_nothing, "relation-shape"),
    ("administered-by-citing-no-authority", _case_administered_by_citing_no_authority,
     "relation-shape"),
    ("relation-authority-is-a-different-bodys-own",
     _case_relation_authority_is_a_different_bodys_own,
     "relation-authority-is-not-another-bodys-own"),
    ("part-of-body-that-carries-an-enabling-authority",
     _case_part_of_body_that_carries_an_enabling_authority,
     "part-of-has-nothing-to-enable"),
    ("part-of-relation-that-cites-an-authority",
     _case_part_of_relation_that_cites_an_authority, "relation-shape"),
    ("relation-naming-no-body", _case_relation_naming_no_body, "relation-shape"),
    ("relation-carrying-an-undeclared-key", _case_relation_carrying_an_undeclared_key,
     "relation-shape"),
    ("relation-authority-that-is-not-an-authority",
     _case_relation_authority_that_is_not_an_authority, "relation-shape"),
    ("relation-authority-recording-an-absence",
     _case_relation_authority_recording_an_absence, "relation-shape"),
    ("one-source-placing-a-body-under-a-parent-twice",
     _case_one_source_placing_a_body_under_a_parent_twice, "relation-unique"),
    ("relation-target-resolves-to-nothing", _case_relation_target_resolves_to_nothing,
     "relation-resolves"),
    ("the-index-places-a-body-under-two-parents",
     _case_the_index_places_a_body_under_two_parents,
     "index-relation-is-regenerated"),
    ("index-relation-the-index-could-not-have-stated",
     _case_index_relation_the_index_could_not_have_stated,
     "index-relation-is-regenerated"),
    ("authority-hand-edited-onto-a-scraped-entry",
     _case_authority_hand_edited_onto_a_scraped_entry, "survives-refresh"),
    ("note-that-is-not-a-scrape-shape", _case_note_that_is_not_a_scrape_shape,
     "note-scrape-shape"),
    ("registry-emptied", _case_registry_emptied, "registry-populated"),
    ("note-missing-a-declared-field", _case_note_missing_a_declared_field,
     "note-covers-fields"),
    ("note-omits-a-field-whose-name-is-a-substring-of-another",
     _case_note_omits_a_field_whose_name_is_a_substring_of_another,
     "note-covers-fields"),
    ("note-diverges-from-what-refresh-would-write",
     _case_note_diverges_from_what_refresh_would_write,
     "note-agrees-with-refresh"),
    ("note-chapterless-count-stale", _case_note_chapterless_count_stale,
     "note-numbers-current"),
    ("row-the-simulation-cannot-run-on", _case_row_the_simulation_cannot_run_on,
     "survives-refresh"),
    ("slug-the-scrape-would-not-produce", _case_slug_the_scrape_would_not_produce,
     "survives-refresh"),
    ("field-the-refresh-drops", _case_field_the_refresh_drops, "survives-refresh"),
    # THE RETIRED POINTER, REFUSED BY THE ALLOWLIST (#174 acceptance criterion 7).
    ("the-retired-pointer-comes-back", _case_the_retired_pointer_comes_back,
     "declared-field"),
    # THE THREE WAYS `parent_chapter` STOPS AGREEING WITH THE BODY THE RELATIONS NAME: a
    # different chapter, a chapter with no placement behind it at all, and one chapter where
    # the sources name two parents and it can only speak for one of them.
    ("parent-chapter-disagrees", _case_parent_chapter_disagrees, "parent-agrees"),
    ("parent-chapter-on-a-body-under-nothing", _case_parent_chapter_on_a_body_under_nothing,
     "parent-agrees"),
    ("parent-chapter-where-the-sources-disagree",
     _case_parent_chapter_where_the_sources_disagree, "parent-agrees"),
    ("duplicate-slug", _case_duplicate_slug, "unique-slug"),
    ("duplicate-chapter", _case_duplicate_chapter, "unique-chapter"),
    ("missing-required-field", _case_missing_required_field, "required-field"),
    ("missing-oar-name", _case_missing_oar_name, "required-field"),
    ("missing-name", _case_missing_name, "required-field"),
    # THE RETIRED KEY, WRITTEN BACK — #177's own mutation proof.
    ("budget-agency-code-reappears", _case_budget_agency_code_reappears,
     "budget-agency-code-retired"),
    # THE THREE WAYS THE ENABLING AUTHORITY STOPS SAYING WHICH STATE A BODY IS IN: a value
    # that cites nothing, a blank, and a reviewed absence with no reason behind it.
    ("enabling-authority-that-is-not-an-authority",
     _case_enabling_authority_that_is_not_an_authority, "enabling-authority-form"),
    ("enabling-authority-left-blank", _case_enabling_authority_left_blank,
     "enabling-authority-form"),
    ("enabling-authority-absent-without-a-reason",
     _case_enabling_authority_absent_without_a_reason, "enabling-authority-form"),
    ("enabling-authority-with-stray-whitespace",
     _case_enabling_authority_with_stray_whitespace, "enabling-authority-form"),
    ("enabling-authority-that-almost-records-an-absence",
     _case_enabling_authority_that_almost_records_an_absence, "enabling-authority-form"),
    ("enabling-authority-session-law-near-miss",
     _case_enabling_authority_session_law_near_miss, "enabling-authority-form"),
    ("row-is-not-a-mapping", _case_row_is_not_a_mapping, "readable-row"),
    # THE TWO WAYS A BODY STOPS BEING FINDABLE BY A NAME IT HAS, which is what promoting
    # `name` (#168) must not be able to do to a reader.
    ("oar-name-that-matches-nothing", _case_oar_name_that_matches_nothing,
     "findable-by-both-names"),
    ("statutory-name-that-matches-nothing", _case_statutory_name_that_matches_nothing,
     "findable-by-both-names"),
    ("organizations-is-not-a-list", _case_organizations_is_not_a_list, "readable-registry"),
]


# THE TWO WAYS A CURATED FIELD GOES MISSING FROM CURATED_KEYS. Neither is expressible as a
# registry row, because both are a statement about the FIELDS table — so each is a whole
# alternative declaration, checked against a registry that is otherwise clean. This is
# acceptance criterion 5 of issue #165 kept permanently: deriving CURATED_KEYS from FIELDS
# is only worth doing if the derivation going wrong is caught.
#
#   not curated     the field is declared, but as something other than CURATED, so
#                   preserve_curated() never carries it forward and --refresh drops it.
#   called scraped  worse, because it looks preserved: the field is left out of the
#                   survival comparison as if the scrape rewrote it, while scraped_entry()
#                   — the only thing that writes a scraped field — never produces it.
#
# Both name `das_agency_number` — the field of record for the number, and since #177 the
# only key it is ever declared under.
_PROOFS = [
    ("curated-field-declared-manual-flag",
     dict(FIELDS, das_agency_number=Field(MANUAL_FLAG, required=False)),
     "survives-refresh"),
    ("curated-field-declared-scraped",
     dict(FIELDS, das_agency_number=Field(SCRAPED, required=False)),
     "scraped-field"),
    # THE SAME TWO STATEMENTS ABOUT `enabling_authority`, because a field is only curated in
    # the sense that matters if the declaration going wrong is caught. The fixture row
    # carries one, so declaring it anything but CURATED loses it: MANUAL_FLAG drops it on a
    # refresh, and SCRAPED hides the drop behind a field the scrape never writes.
    ("enabling-authority-declared-manual-flag",
     dict(FIELDS, enabling_authority=Field(MANUAL_FLAG, required=False)),
     "survives-refresh"),
    ("enabling-authority-declared-scraped",
     dict(FIELDS, enabling_authority=Field(SCRAPED, required=False)),
     "scraped-field"),
    # THE SAME TWO STATEMENTS ABOUT `curator_note` (#178). This is the field AC1's "protected
    # the way manual protects curation" is a proof about rather than an assumption: the
    # fixture's `cfo` carries one and is NOT `manual`, so declaring the field anything but
    # CURATED loses it exactly the way it would lose `enabling_authority` above — MANUAL_FLAG
    # drops it on a refresh (nothing preserves a flag-declared field that isn't `manual`
    # itself), and SCRAPED hides the drop behind a field `scraped_entry()` never writes.
    ("curator-note-declared-manual-flag",
     dict(FIELDS, curator_note=Field(MANUAL_FLAG, required=False)),
     "survives-refresh"),
    ("curator-note-declared-scraped",
     dict(FIELDS, curator_note=Field(SCRAPED, required=False)),
     "scraped-field"),
    # THE THREE WAYS A MIXED-ORIGIN FIELD IS DECLARED AS A SINGLE-ORIGIN ONE. `relations`
    # holds entries the refresh regenerates beside entries only curation produces, so every
    # whole-field origin is wrong about half of what it holds — and the three are wrong in
    # different directions, which is why each is stated separately:
    #
    #   CURATED      preserve_curated() copies a key the rebuilt row has not got, and the
    #                rebuilt row always has this one — so nothing is carried and the curated
    #                entries are lost. Reported, because the field is compared whole.
    #   MANUAL_FLAG  nothing preserves it at all; the same loss by a shorter route.
    #   SCRAPED      the loss with nothing to report it, and the reason `relation-origin`
    #                exists: a scraped field is SKIPPED by the survival comparison on the
    #                grounds that the refresh rewrites it, so the curated entries would
    #                disappear behind a rule that passed. That is the shape of #178, and a
    #                gate that cannot see it is the one outcome a gate must not produce.
    ("relations-declared-curated",
     dict(FIELDS, relations=Field(CURATED, required=True)), "survives-refresh"),
    ("relations-declared-manual-flag",
     dict(FIELDS, relations=Field(MANUAL_FLAG, required=True)), "survives-refresh"),
    ("relations-declared-scraped",
     dict(FIELDS, relations=Field(SCRAPED, required=True)), "relation-origin"),
    # A MERGED FIELD THE CONSTRUCTOR DOES NOT WRITE, which is the other half of what
    # `scraped-field` now states. The refresh does not own everything such a field holds,
    # but it does rebuild the entries it owns — so a MERGED field `scraped_entry()` never
    # produces is one --refresh drops IN FULL, curated entries and all, and the survival
    # comparison would report that as a curated field nothing preserves rather than as the
    # declaration it is. The name is MADE UP for the reason the undeclared-field case gives:
    # any real field is one FIELDS may legitimately declare tomorrow, and the proof would
    # stop proving anything the day it did.
    ("merged-field-the-scrape-does-not-write",
     dict(FIELDS, coalition=Field(MERGED, required=False)), "scraped-field"),
    # THE TWO WAYS A PER_ROW FIELD IS DECLARED AS A SINGLE-ORIGIN ONE (#168), stated over
    # both halves of the pair because both halves are carried by the same function and
    # either one lost alone is a row lying about itself.
    #
    #   SCRAPED   the loss with NOTHING TO REPORT IT, and the reason `name-origin` exists.
    #             The survival comparison skips a scraped field on the grounds that the
    #             refresh rewrites it — so a reviewed statutory name is replaced by the
    #             rules index's spelling and every rule here still passes. That is the false
    #             pass a gate must never produce, and it is exactly the shape of #178.
    #   CURATED   preserve_curated() copies a key the rebuilt row has not got, and the
    #             rebuilt row always has this one, so nothing is carried. The loss is real
    #             and the survival comparison DOES report it, which is why this proof names
    #             a different rule from the one above.
    ("name-declared-scraped",
     dict(FIELDS, name=Field(SCRAPED, required=True)), "name-origin"),
    ("name-declared-curated",
     dict(FIELDS, name=Field(CURATED, required=True)), "survives-refresh"),
    ("name-basis-declared-scraped",
     dict(FIELDS, name_basis=Field(SCRAPED, required=True)), "name-origin"),
    ("name-basis-declared-curated",
     dict(FIELDS, name_basis=Field(CURATED, required=True)), "survives-refresh"),
    # AND A THIRD FIELD CLAIMING THE ORIGIN THE NAME PAIR'S PROVENANCE DECIDES. PER_ROW is
    # not a general "the row decides" origin — it is `name_basis` deciding, and `name_basis`
    # says nothing about any other field. Such a field would be carried across a refresh, or
    # dropped, on a claim about where the row's NAME came from, and the survival comparison
    # would pass either way because the carry is CONSISTENT and merely wrong about what it is
    # carrying. `raw_index_name` is the field used, and it has to be a field `scraped_entry()`
    # WRITES: a made-up one is caught by `scraped-field` before this rule is reached, which
    # would prove that a typo is refused rather than that a wrong origin is. This is the
    # silent version — every other rule passes.
    ("third-field-declared-per-row",
     dict(FIELDS, raw_index_name=Field(PER_ROW, required=True)), "name-origin"),
]


def _proof_the_merge_is_what_carries_a_curated_relation() -> int:
    """A curated relation survives a refresh, and survives it BECAUSE preserve_relations()
    carries it — the merge watched working and watched failing, on the same fixture.

    The declaration proofs above state that `relations` may not be declared as a
    single-origin field; this states what the merge itself does, which is the other half.
    Without it the curated entry is gone and the rebuilt row still looks entirely healthy:
    it carries the key, the key holds a list, and the list holds the OAR index's placement.
    That is what the loss looks like from the outside, and it is why the survival comparison
    runs per ENTRY — a whole-field comparison sees a field that is present either way."""
    rows = _fixture()["organizations"]
    curated = {"target": "department-of-administrative-services", "source": "statute",
               "kind": ADMINISTERED_BY, "basis": REVIEWED_AUTHORITY,
               "authority": "ORS 999.998"}
    survived = simulate_refresh(rows)["chief-financial-office"][RELATION_KEY]
    dropped = simulate_refresh(rows, merged_keys=frozenset())["chief-financial-office"]
    bad = 0
    if curated not in survived:
        print(f"FAIL merge-carries-a-curated-relation: {survived!r}", file=sys.stderr)
        bad += 1
    if curated in dropped[RELATION_KEY]:
        print("FAIL merge-is-what-carries-it: the entry survived with the merge switched "
              f"off, so this proves nothing about it ({dropped[RELATION_KEY]!r})",
              file=sys.stderr)
        bad += 1
    if index_relation("department-of-administrative-services") not in dropped[RELATION_KEY]:
        print("FAIL a-dropped-curated-relation-leaves-a-healthy-looking-row: the row lost "
              f"more than the curated entry ({dropped[RELATION_KEY]!r})", file=sys.stderr)
        bad += 1
    return bad


def _proof_the_carry_is_what_keeps_an_established_statutory_name() -> int:
    """An established statutory name survives a refresh, and survives it BECAUSE
    preserve_name() carries it — the carry watched working and watched failing, on one
    fixture.

    The declaration proofs above state that `name` may not be declared as a single-origin
    field; this states what the carry itself does, which is the other half. Without it the
    reviewed name is gone and the row still looks entirely healthy: it carries `name`, the
    key holds a non-empty string, the string is the body's name in some real sense, and every
    consumer reads it as what Oregon law calls the body. That is what the loss looks like
    from the outside — a publisher's spelling wearing a statute's provenance — and it is why
    the pair moves together: the third assertion below is that the basis went with it, so the
    row cannot come back saying a rules-index title was read off an authority.

    AND THE UNVERIFIED ROW MUST STILL TRACK THE INDEX, which is the fourth. A carry that kept
    every row's name would freeze 185 rows at whatever the rules index said the day they were
    scraped, under a basis stating that they hold what the rules index prints — the opposite
    failure, and the one a whole-field CURATED declaration would produce.
    """
    rows = _fixture()["organizations"]
    kept = simulate_refresh(rows)["department-of-administrative-services"]
    lost = simulate_refresh(rows, per_row_keys=frozenset())[
        "department-of-administrative-services"]
    bad = 0
    if kept["name"] != "The Oregon Department of Administrative Services":
        print(f"FAIL carry-keeps-an-established-statutory-name: {kept['name']!r}",
              file=sys.stderr)
        bad += 1
    if lost["name"] == "The Oregon Department of Administrative Services":
        print("FAIL the-carry-is-what-keeps-it: the name survived with the carry switched "
              f"off, so this proves nothing about it ({lost['name']!r})", file=sys.stderr)
        bad += 1
    if lost[NAME_BASIS_KEY] != UNVERIFIED_OAR_TITLE:
        print("FAIL a-dropped-statutory-name-takes-its-basis-with-it: the row kept "
              f"{lost[NAME_BASIS_KEY]!r} over a name the scrape rebuilt", file=sys.stderr)
        bad += 1
    cfo = simulate_refresh(rows)["chief-financial-office"]
    if cfo["name"] != cfo["oar_name"] or cfo[NAME_BASIS_KEY] != UNVERIFIED_OAR_TITLE:
        print("FAIL an-unverified-name-still-follows-the-index: the carry took a row it was "
              f"not asked to take ({cfo['name']!r}, {cfo[NAME_BASIS_KEY]!r})",
              file=sys.stderr)
        bad += 1
    return bad


# THE TEN NEAR MISSES `_proof_session_law_form_boundary` proves REFUSED, most one letter or
# one punctuation mark from the accepted spelling. A pair (the string, a short label for the
# diagnostic) rather than bare strings, so a failing proof names WHICH near miss got through
# rather than making a reader diff two long lists.
#
# EIGHT OF THE TEN ARE MEASURED SHAPES (see AUTHORITY_FORMS' own comment for the corpus
# counts each is drawn from). TWO ARE NOT, and say so where they sit below: the corpus
# happens to contain no two-digit-year session-law citation and no session-law citation with
# a trailing section marker in otherwise-canonical spelling, so those two are constructed
# boundary probes rather than measured ones — a deliberate exception to "measured, not
# invented", not an unnoticed one.
_SESSION_LAW_NEAR_MISSES = (
    ("Oregon Laws 1975, Chapter 789", "capital Chapter"),
    ("Or Laws 1975, chapter 789", "abbreviated prefix, no period"),
    ("Or. Laws 1975, chapter 789", "abbreviated prefix, with period"),
    ("Oregon Laws 1975 chapter 789", "no comma"),
    ("Oregon Laws 1975, ch. 789", "abbreviated chapter"),
    # NOT MEASURED — constructed, because the corpus carries no two-digit-year session-law
    # citation to draw one from (re-measured 2026-08-30: `Oregon Laws \d{2}, chapter \d+`
    # occurs zero times across statutes/rules/constitution/executive-orders). Kept anyway
    # because the form's own comment states the year is `\d{4}`, deliberately, and this is
    # what proves that digit count is enforced rather than merely assumed.
    ("Oregon Laws 75, chapter 789", "two-digit year"),
    ("Oregon Laws 1975, chapter", "no chapter number"),
    ("chapter 789, Oregon Laws 1975", "reversed order"),
    # ALSO NOT MEASURED, for the same reason (re-measured 2026-08-30: `Oregon Laws \d{4},
    # chapter \d+ §\d+` occurs zero times too). Constructed to ISOLATE the trailing-section
    # defect from every other one — every other character of it fullmatches the accepted
    # shape — which the real #211 citation below cannot do, because that one is malformed
    # three ways at once and would not tell a failing proof which of the three broke.
    ("Oregon Laws 1975, chapter 789 §19", "trailing section marker, isolated"),
    # THE REAL CITATION FROM #211 ITSELF: `Or Laws 1961, ch 454 §19` (oregon-military-
    # department, per the issue). Refused, but NOT "for exactly one reason" the way the
    # isolated case above is — measured against this form's own pattern, it fails THREE
    # independent ways at once: an abbreviated prefix ("Or" not "Oregon"), an abbreviated
    # chapter word ("ch" not "chapter"), and the trailing section marker the case above
    # isolates. Kept as its own case so neither this one nor the isolated one is asked to do
    # the other's job.
    ("Or Laws 1961, ch 454 §19", "the real #211 citation, refused three ways at once"),
)


def _proof_session_law_form_boundary() -> int:
    """The session-law form (#211) admits the shape it was built for and refuses everything
    adjacent to it — TESTED BOTH DIRECTIONS, which is this week's own lesson applied to the
    form that lesson is about: a field loose enough to admit `Oregon Laws 1975, chapter 789`
    could easily have been loose enough to admit strings that are not authorities at all, and
    the only way to know it is not is to throw the near misses at it and watch them bounce.

    THE TRUE POSITIVE FIRST, because a form that refuses everything is not a working form —
    the ten refusals below would pass vacuously if this one line were deleted."""
    bad = 0
    true_form, true_detail = classify_authority("Oregon Laws 1975, chapter 789")
    if true_form != "session-law":
        print(f"FAIL session-law-form-accepts-the-real-shape: classify_authority returned "
              f"{(true_form, true_detail)!r}", file=sys.stderr)
        bad += 1
    for value, label in _SESSION_LAW_NEAR_MISSES:
        form, detail = classify_authority(value)
        if form is not None:
            print(f"FAIL session-law-form-refuses-near-misses ({label}): {value!r} was "
                  f"accepted as form {form!r} ({detail!r})", file=sys.stderr)
            bad += 1
    return bad


def _proof_the_merge_carries_a_derived_kind_onto_the_regenerated_entry() -> int:
    """A kind decided for the OAR index's own placement survives a refresh, and survives it
    BECAUSE preserve_relations() carries it — watched working and watched failing on one
    fixture, the pair `_proof_the_merge_is_what_carries_a_curated_relation` above makes for a
    whole entry.

    THIS IS WHERE A DERIVED KIND LIVES (#173). The relation whose kind is being decided is
    the one the OAR index states, and --refresh rewrites that entry from the index tree every
    time it runs — so the merge is per KEY as well as per entry: the scrape owns the
    PLACEMENT (`target`, `source`) and the derivation owns the DECISION (`kind`, `basis`,
    `authority`). Without this the derived kind is destroyed on the next refresh and the row
    still looks healthy, which is #178's shape exactly.

    AND IT IS NOT CARRIED ONTO A PLACEMENT THAT MOVED. A decision that this body is
    separately constituted was recorded ABOUT a placement under one parent; if the index
    re-files the body, the rebuilt entry names a different parent and the decision is dropped
    rather than re-attached. That is a red build in derive_relation_kinds.py --check, which
    is a human re-running the derivation, and the alternative is a kind silently transferred
    to a relation nobody derived it for."""
    rows = _fixture()["organizations"]
    decided = dict(index_relation("department-of-administrative-services"),
                   kind=ADMINISTERED_BY, basis=PROPOSED_AUTHORITY, authority="ORS 999.997")
    rows[1][RELATION_KEY][0] = dict(decided)
    bad = 0
    survived = simulate_refresh(rows)["chief-financial-office"][RELATION_KEY]
    if decided not in survived:
        print(f"FAIL merge-carries-a-derived-kind: {survived!r}", file=sys.stderr)
        bad += 1
    dropped = simulate_refresh(rows, merged_keys=frozenset())["chief-financial-office"]
    if decided in dropped[RELATION_KEY]:
        print("FAIL merge-is-what-carries-the-kind: the decision survived with the merge "
              f"switched off, so this proves nothing about it ({dropped[RELATION_KEY]!r})",
              file=sys.stderr)
        bad += 1
    # THE PLACEMENT MOVED, so the decision recorded about the old one is not re-attached to
    # the new one. PROVEN AGAINST `carry_decision()` ITSELF, which is where the rule lives,
    # and not through the survival simulation: #174 removed `parent_slug`, so the simulation
    # replays the index's placement from the row's own `oar-index` entry and the rebuilt
    # entry always names the parent the committed one names. An upstream re-filing is no
    # longer expressible in there — it never was something the simulation measured, which
    # measures survival rather than drift — and a proof run through it would from now on
    # pass by construction.
    rebuilt = [index_relation("office-of-the-governor")]
    carry_decision(dict(decided), rebuilt)
    if rebuilt != [index_relation("office-of-the-governor")]:
        print(f"FAIL a-derived-kind-does-not-follow-a-placement-that-moved: {rebuilt!r}",
              file=sys.stderr)
        bad += 1
    # AND THE SAME CALL CARRIES IT WHEN THE PARENT DID NOT MOVE, so the check above is not
    # passing because `carry_decision()` carries nothing at all.
    same = [index_relation("department-of-administrative-services")]
    carry_decision(dict(decided), same)
    if same != [dict(decided)]:
        print(f"FAIL a-derived-kind-follows-a-placement-that-stayed: {same!r}",
              file=sys.stderr)
        bad += 1
    return bad


def _proof_the_walk_says_what_it_cannot_answer() -> int:
    """The hierarchy walk in every state it can stop in, INCLUDING the three no committed row
    is in — which is the whole reason it is proven here rather than left to the registry.

    81 children carry exactly one relation each today, so every walk over the committed file
    takes the same branch, and the branches that decide what happens when the sources
    DISAGREE have never run. The counts `build_policy_gap.py` and `build_agency_graph.py`
    publish beside their totals come out of those branches. A number produced by code nobody
    has watched run is not a measurement.

    A DISAGREEMENT IS NOT A BODY UNDER NOTHING, and that is the assertion that matters: both
    rollups must be able to tell "this registry places it nowhere" from "this registry cannot
    say which of two", because showing them alike publishes the second as the first —
    CONTEXT.md's overriding rule, on a page carrying rule counts."""
    bad = 0
    top, child, other = "board-of-imaginary-affairs", "imaginary-affairs-unit", "office-of-x"
    reg = {top: {"slug": top, RELATION_KEY: []},
           other: {"slug": other, RELATION_KEY: []},
           child: {"slug": child, RELATION_KEY: [index_relation(top)]}}
    # TWO SOURCES, ONE PARENT: they agree about the placement and at most disagree about the
    # kind, which is not this walk's question — so the parent is named, not refused.
    agreeing = {"slug": "agreeing", RELATION_KEY: [
        index_relation(top), {"target": top, "source": "statute", "kind": UNDETERMINED}]}
    # TWO SOURCES, TWO PARENTS: the disagreement ADR 0003 keeps, and nothing here picks.
    disputed = {"slug": "disputed", RELATION_KEY: [
        index_relation(top), {"target": other, "source": "das", "kind": UNDETERMINED}]}
    loop = {"slug": "loop", RELATION_KEY: [index_relation("loop-back")]}
    reg.update({"agreeing": agreeing, "disputed": disputed, "loop": loop,
                "loop-back": {"slug": "loop-back", RELATION_KEY: [index_relation("loop")]}})

    expected = [
        ("a body under nothing is at the top", root_body(top, reg), top, AT_THE_TOP),
        ("a child rolls up to its parent", root_body(child, reg), top, AT_THE_TOP),
        ("two sources naming ONE parent still roll up",
         root_body("agreeing", reg), top, AT_THE_TOP),
        ("two sources naming TWO parents are not rolled up",
         root_body("disputed", reg), "disputed", SOURCES_DISAGREE),
        ("a cycle stops rather than hanging", root_body("loop", reg), "loop-back",
         PLACED_IN_A_LOOP),
        ("a slug this registry does not carry rolls up to itself",
         root_body("agencies/not-a-body", reg), "agencies/not-a-body", OFF_THE_REGISTRY),
    ]
    for name, got, slug, stopped in expected:
        if got != Rollup(slug, stopped):
            print(f"FAIL {name}: {got!r}, expected {Rollup(slug, stopped)!r}",
                  file=sys.stderr)
            bad += 1
    # AND THE ONE-HOP ANSWER THE GRAPH USES, from the same place, on the same rows.
    for name, org, want in (("one parent is named", reg[child], Placement(top, None)),
                            ("two sources, one parent", agreeing, Placement(top, None)),
                            ("two parents are refused", disputed,
                             Placement(None, SOURCES_DISAGREE)),
                            ("no parent is not a disagreement", reg[top],
                             Placement(None, None))):
        if sole_parent(org) != want:
            print(f"FAIL sole-parent {name}: {sole_parent(org)!r}, expected {want!r}",
                  file=sys.stderr)
            bad += 1
    return bad


def _proof_the_relation_census_counts_every_kind() -> int:
    """37 of the registry's 81 relations record UNDETERMINED and 44 record a derived kind
    (#173), and #171 requires both to be REPORTED rather than defaulted away. A census that
    printed only the kinds it found would print "1 administered_by" against the fixture and
    leave a reader to infer the rest — the reading this registry never permits (CONTEXT.md:
    an absence is never a claim that there is none). So every kind, every source and every
    basis is named with its count, including the zeroes, and this is what says so.

    The expected numbers come from the fixture ABOVE, which is two relations written out by
    hand — not from re-counting the way the census counts, which would pass whatever it
    said."""
    census = relation_census(_fixture()["organizations"])
    expected = ["2 relation(s) on 1 of 3 bodies",
                f"1 {UNDETERMINED}", "0 part_of", "1 administered_by",
                f"1 {OAR_INDEX}", "1 statute", "0 das",
                # AND WHAT THE DECIDED KINDS REST ON (#173). A kind derived from a candidate
                # nobody has read is a weaker claim than one derived from a reviewed
                # authority, and a census that reported only how many kinds are decided
                # would report the two as one number — which is the substitution the basis
                # exists to prevent, made by the gate that is supposed to surface it.
                f"0 {PROPOSED_AUTHORITY}", f"1 {REVIEWED_AUTHORITY}"]
    missing = [x for x in expected if x not in census]
    if missing:
        print(f"FAIL relation-census-counts-every-kind: {census!r} does not report "
              f"{missing}", file=sys.stderr)
        return 1
    return 0


def _proof_chapter_page_count_check_fires_on_a_stale_docstring() -> int:
    """#279's own bug: `expand_oar_name.py` and `record_name_basis.py` each state how many
    chapter pages a --refresh fetches, and both had drifted to 189 (the registry's ROW
    count) while the true figure — rows carrying `oar_chapter` — was 170. Demonstrated
    against the FIXTURE (2 of its 3 rows carry oar_chapter, `das` and `cfo`; `gov` does
    not) with synthetic doc text, not the real files, so this proves the RULE fires rather
    than that today's committed text happens to pass it.

    Four demonstrations: the rule stays quiet on text stating the true count, fires on
    text stating a stale one, fires on text that dropped the phrase it looks for
    entirely — a rewording that stopped saying anything checkable is exactly as wrong as a
    rewording that started saying something false — and fires when the doc could not be
    read at all (code review of #279)."""
    bad = 0
    cat = _fixture()
    rule = "chapter-page-count-current"

    fresh = {"a.py": "a refresh re-fetches all 2 chapter pages from the mirror."}
    failures = check_registry(cat, refresh_note=cat["note"], chapter_page_docs=fresh)
    if any(f.rule == rule for f in failures):
        print(f"FAIL {rule}-quiet-on-true-count: fired against text stating 2, the "
              "fixture's actual count", file=sys.stderr)
        bad += 1

    stale = {"a.py": "a refresh re-fetches all 3 chapter pages from the mirror."}
    failures = check_registry(cat, refresh_note=cat["note"], chapter_page_docs=stale)
    if not any(f.rule == rule for f in failures):
        print(f"FAIL {rule}-fires-on-stale-count: did not fire against 3, when the "
              "fixture's actual count is 2", file=sys.stderr)
        bad += 1

    missing = {"a.py": "this docstring never says how many pages get fetched."}
    failures = check_registry(cat, refresh_note=cat["note"], chapter_page_docs=missing)
    if not any(f.rule == rule for f in failures):
        print(f"FAIL {rule}-fires-on-missing-phrase: did not fire when the checked "
              "phrase was absent entirely", file=sys.stderr)
        bad += 1

    # Code review of #279: `_default_chapter_page_docs()` used to hand `check_registry()`
    # a bare `p.read_text()` result, so a missing or unreadable file crashed `--check` with
    # an uncaught FileNotFoundError instead of a Failure line — the two migration scripts
    # it reads are exactly the kind of file a future cleanup deletes. `None` in place of a
    # file's text is how a caller now reports "could not read this", the same shape
    # `readable-row` reports an unreadable registry row.
    unreadable = {"a.py": None}
    failures = check_registry(cat, refresh_note=cat["note"], chapter_page_docs=unreadable)
    if not any(f.rule == rule for f in failures):
        print(f"FAIL {rule}-fires-on-unreadable-file: did not fire when the doc text "
              "was None (an unreadable file)", file=sys.stderr)
        bad += 1
    return bad


def _proof_missing_registry_is_refused() -> int:
    """`cmd_check()`'s OWN guard for a registry file that does not exist at all -- the
    SECOND spelling of `readable-registry` #320 found, a bare f-string with no `Failure`
    behind it that the `organizations-is-not-a-list` case above cannot reach (that case
    mutates an in-memory registry `check_registry()` already loaded; this one is about the
    file never being loadable in the first place). Demonstrated against the real command
    line via `catalog_path` (`cmd_check()`'s own docstring), not a synthetic call into
    `check_registry()`, because the whole point is proving the SITE that used to spell the
    rule differently now emits the one declared spelling."""
    import contextlib
    import io
    import tempfile
    from pathlib import Path

    bad = 0
    with tempfile.TemporaryDirectory() as d:
        missing = Path(d) / "does-not-exist.yml"
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            rc = cmd_check(catalog_path=missing)
        out = captured.getvalue()
        if rc != 1:
            print(f"FAIL missing-registry-file-exits-nonzero: cmd_check() returned {rc}",
                  file=sys.stderr)
            bad += 1
        if f"[readable-registry] {missing}: no registry to check" not in out:
            print(f"FAIL missing-registry-file-is-refused: expected one "
                  f"[readable-registry] line naming {missing!r}, got {out!r}",
                  file=sys.stderr)
            bad += 1
    return bad


def _proof_refresh_rejects_an_undeclared_scraped_field() -> int:
    """--refresh's own half of the declaration, which --check cannot reach: it reads
    committed data and never runs a scrape, so a field the SCRAPE started writing without
    declaring it can only be caught where the scrape runs. Demonstrated failing here
    because a guard nobody has watched fire is not known to fire.

    The probe field is MADE UP, and it has to be. This proof used to name `oar_name` — a
    field ADR 0003 said the registry was going to carry — and the day it started carrying
    one the proof stopped proving anything: the guard correctly said nothing, and the only
    reason that surfaced as a red build rather than a quiet pass is that the assertion is on
    the guard firing. Any real field is a field FIELDS may legitimately declare tomorrow.

    #275's other half, and the one a made-up field cannot demonstrate: the guard must also
    stay QUIET on a row the scrape genuinely produces. `scraped_entry()` is the only thing
    that builds one, so THAT is the fixture here rather than a hand-typed dict — a hand-typed
    row is a claim about what the scrape writes, and this proof exists because that claim was
    wrong once already (`note` used to be typed by hand here too, before it grew `name` and
    `name_basis`). Demonstrated failing on unmodified main: `assert_scrape_declared()` read
    only `SCRAPED_KEYS` and `MERGED_KEYS`, so the `name`/`name_basis` pair `scraped_entry()`
    writes on every row (PER_ROW, ADR 0003 — a body the scrape just found has no established
    statutory name, so it starts under `name_basis: unverified-oar-title`) came back as
    undeclared on every row a real scrape ever built — `['name', 'name_basis']`, exactly the
    pair the ticket's own `--refresh` transcript quotes it dying on, before writing anything
    (the ticket states no timing; a live post-fix `--refresh` completed in 106.48s, see
    `assert_scrape_declared()`'s own docstring)."""
    bad = 0
    try:
        assert_scrape_declared([{"slug": "a-body", "headcount": 412}])
    except SystemExit as e:
        if "headcount" not in str(e):
            bad += 1
    else:
        print("FAIL refresh-rejects-undeclared-scraped-field: the scrape guard did not fire",
              file=sys.stderr)
        bad += 1

    row = scraped_entry(oar_name="Department of Administrative Services", oar_chapter="125",
                        raw_index_name="Dept. of Administrative Services",
                        source_url=f"{BASE}/rules/oar_chapter_125")
    try:
        assert_scrape_declared([row])
    except SystemExit as e:
        print("FAIL refresh-accepts-what-the-scrape-produces: assert_scrape_declared "
              f"rejected a row scraped_entry() itself built ({e})", file=sys.stderr)
        bad += 1
    return bad


# The row this proof carries curated keys onto, deliberately holding all four of them (#182):
# `preserve_curated()` only reorders keys it is APPENDING, so a row that starts with none of
# them is the shape that shows the bug — a row that already carried one under a fixed
# position would hide the defect behind that one stable key.
_CURATED_ORDER_PROOF_SCRIPT = """
import sys
sys.path.insert(0, {src!r})
import json
import catalog_agencies as c
das = c.scraped_entry(oar_name="Department of Administrative Services", oar_chapter="125",
                       raw_index_name="Dept. of Administrative Services",
                       source_url="{base}/rules/oar_chapter_125")
c.write_das_agency_number(das, "107")
das["aliases"] = ["DAS"]
das["enabling_authority"] = "ORS 999.999"
das["curator_note"] = "fixture-only, not a claim about the real DAS"
row = c.simulate_refresh([das])[das["slug"]]
print(json.dumps(list(row)))
"""

# FIELDS's curated columns, TRANSCRIBED BY HAND rather than read from `curated_keys_in_order()`
# (#182 review). `curated_keys_in_order()` is the function under test, so computing "expected"
# by calling it pins only cross-process AGREEMENT — two subprocesses independently landing the
# WRONG order (`sorted()`, say: aliases, das_agency_number, curator_note, enabling_authority)
# would agree with each other and with a same-order call to the buggy function, and an
# equality-only check against that call would pass. This tuple is what FIELDS actually
# declares, copied by eye from the table above (curator_note, das_agency_number, aliases,
# enabling_authority) rather than derived from it, so a wrong-but-self-consistent order is
# still caught. Reorder FIELDS's curated columns on purpose and this needs updating by hand
# to match — that is the point, not a maintenance cost: it is where the review AC2 asks for
# ("stated where the keys are declared") would have to be re-confirmed by a human.
_DECLARED_CURATED_ORDER = ("curator_note", "das_agency_number", "aliases",
                           "enabling_authority")


def _proof_curated_keys_survive_in_declaration_order() -> int:
    """A single process cannot see this bug (#182): a `frozenset`'s iteration order is fixed
    for the life of one interpreter, so an in-process test of `preserve_curated()` would pass
    whether the fix landed or not. What varies is PYTHONHASHSEED, which is fixed once per
    process and different across processes — exactly the granularity `--refresh` runs at, one
    process per invocation. So this proof is the one in the file that spawns real subprocesses,
    pinning two DIFFERENT, NONZERO seeds — 0 disables hash randomization rather than pinning
    a seed, and already lands the FIELDS order before this fix (measured), so a proof that
    used it would be resting on the other, single, seed — and asks whether independent
    processes still agree.

    Demonstrated failing by reverting the fix locally and re-running: two runs of the
    reproduction in #182's own report (three, even) landed `aliases` in three different
    positions relative to `das_agency_number` and `budget_agency_code` — the same two keys
    #175 deliberately wrote adjacent, before #177 retired `budget_agency_code` for good.
    Reverting `preserve_curated()`'s default back to `CURATED_KEYS` here still reproduces a
    PYTHONHASHSEED-driven reordering, now among today's curated keys — `curator_note`,
    `das_agency_number`, `aliases`, `enabling_authority` — though not the exact #182
    symptom, which needed a key this branch retired.

    Checks the FULL row from each seed, not only its curated keys, so a --refresh that
    reordered something else in the row would also fail this — the closest this module gets
    to AC1's byte-identical --refresh assertion without THREE real `--refresh` runs to diff
    against each other (#275's fix, landed alongside this correction, lets a real `--refresh`
    run at all now — verified live, timing and count at `assert_scrape_declared()`'s own
    docstring rather than restated here — but a single run says nothing about PYTHONHASHSEED
    variance across runs, which is what this proof still stands in for). Both full rows must
    also agree with each other, and the curated keys within them must
    match `_DECLARED_CURATED_ORDER` — a literal independent of `curated_keys_in_order()`, so
    two seeds agreeing on the WRONG order does not pass this the way it would an equality-only
    check against that function's own output."""
    src = str(REPO_ROOT / "src")
    seen = {}
    for seed in ("3", "1000003"):
        proc = subprocess.run(
            [sys.executable, "-c", _CURATED_ORDER_PROOF_SCRIPT.format(src=src, base=BASE)],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
            env={**os.environ, "PYTHONHASHSEED": seed})
        if proc.returncode != 0:
            print(f"FAIL curated-key-order-survives-hashseed: seed {seed} crashed:\n"
                  f"{proc.stderr}", file=sys.stderr)
            return 1
        seen[seed] = json.loads(proc.stdout)
    rows = list(seen.values())
    if len(set(tuple(r) for r in rows)) != 1:
        print(f"FAIL curated-key-order-survives-hashseed: seeds disagree on the full row: "
              f"{seen}", file=sys.stderr)
        return 1
    curated_subsequence = tuple(k for k in rows[0] if k in _DECLARED_CURATED_ORDER)
    if curated_subsequence != _DECLARED_CURATED_ORDER:
        print("FAIL curated-key-order-survives-hashseed: both seeds agree, but not with "
              f"FIELDS's declared order — expected {_DECLARED_CURATED_ORDER}, got "
              f"{curated_subsequence} (full row {rows[0]})", file=sys.stderr)
        return 1
    return 0


# ------------------------------------------------------------------------- the search proof
#
# A BODY MUST STAY FINDABLE BY THE NAME ITS READER KNOWS, and after ADR 0003 there are two
# such names on every row. The fixture below is where they DIFFER by construction: `name` and
# `oar_name` hold identical bytes on 186 of the 189 committed rows (#168 establishes four
# statutory names, three of which differ from the OAR title), so a proof taken from committed
# data passes whichever field the matcher reads on all but three and proves nothing about
# which it is.


def _search_fixture():
    """One body under three names: the statutory one ADR 0003 promotes into `name`, the
    rules index's title in `oar_name`, and a curated former name in `aliases`. Every one of
    the three is a name some Oregon source prints for the same body."""
    org = scraped_entry(oar_name="Oregon Liquor and Cannabis Commission", oar_chapter="845",
                        raw_index_name="Liquor & Cannabis Comm'n",
                        source_url=f"{BASE}/rules/oar_chapter_845")
    org["name"] = "Oregon Liquor and Cannabis Commission"      # statutory (ORS 471.705)
    org["oar_name"] = "Oregon Liquor Control Commission"       # what the rules index prints
    org["aliases"] = ["OLCC"]
    return org


_SEARCH_CASES = [
    # (what a reader typed, whether it must find the body, why)
    ("liquor and cannabis", True, "its statutory name"),
    ("liquor control", True, "its OAR name — the name every rule document carries"),
    ("olcc", True, "a curated alias, the registry's reviewed 'also known as'"),
    ("Oregon Liquor Control Commission", True, "the OAR name as printed, case and all"),
    ("board of nursing", False, "a name this body is not known by"),
    ("", False, "an empty query names no body, and matching all 189 is not a search"),
]


# WHAT A PUBLISHER-WRITTEN NAME MUST STILL RESOLVE TO. `resolve()` takes a name some other
# source wrote — the Secretary of State's retention schedules spell them "Agriculture, Dept.
# of" — and returns the slug it means. Those spellings are written against the names Oregon
# publishes, which is what the OAR index prints for a body as much as what its statute says,
# so the resolver considers BOTH. Measured over the 76 recorded resolutions in
# _meta/catalog/retention-schedule-agencies.yml when this landed: identical against the
# committed registry (67 agree, 5 already unreproducible for a reason outside this change —
# their recorded `alias` basis names aliases no registry row carries), and against a
# registry with `name` promoted to a synthetic statutory name, matching `name` alone loses
# 32 of 72 while matching both loses none beyond those 5.


def _resolution_fixture():
    """A body whose two names disagree, plus one whose names are the same string — because
    the real registry after ADR 0003 is a mixture and a resolver has to handle both."""
    olcc = _search_fixture()
    nursing = scraped_entry(oar_name="Board of Nursing", oar_chapter="851",
                            raw_index_name="Bd. of Nursing",
                            source_url=f"{BASE}/rules/oar_chapter_851")
    return [olcc, nursing]


_RESOLUTION_CASES = [
    # (the name some other source wrote, the slug it means, why it is that body's name)
    ("Oregon Liquor and Cannabis Commission", "oregon-liquor-and-cannabis-commission",
     "its statutory name, exactly as ORS 471.705 prints it"),
    ("Oregon Liquor Control Commission", "oregon-liquor-and-cannabis-commission",
     "its OAR name, which is how the rules index prints it"),
    ("Liquor and Cannabis Commission, Oregon", "oregon-liquor-and-cannabis-commission",
     "the statutory name inverted, the house style of the Archives Division"),
    ("Liquor Control Commission, Oregon", "oregon-liquor-and-cannabis-commission",
     "the OAR name inverted — the same house style over the other name"),
    ("Nursing, Bd. of", "board-of-nursing",
     "a body whose two names agree, resolved as it always was"),
]


def _proof_a_promoted_name_loses_no_resolution():
    """(failures, resolutions proven). Both are counted rather than stated, because a
    hand-written total is a number that goes stale the first time a case is added."""
    bad = ran = 0
    orgs = _resolution_fixture()
    for name, slug, why in _RESOLUTION_CASES:
        got, basis = resolve(name, organizations=orgs)
        ran += 1
        if got != slug:
            print(f"FAIL resolution-by-{why!r}: {name!r} -> {got!r} ({basis}), expected "
                  f"{slug!r}", file=sys.stderr)
            bad += 1
    # AN ALIAS IS STILL REPORTED AS AN ALIAS. `basis` is recorded per resolution in
    # _meta/catalog/retention-schedule-agencies.yml and is what tells a human how far to
    # trust the row, so a match on a curated alias may not arrive labelled `exact`.
    got = resolve("OLCC", organizations=orgs)
    ran += 1
    if got != (orgs[0]["slug"], "alias"):
        print(f"FAIL resolution-by-an-alias-is-reported-as-one: -> {got!r}", file=sys.stderr)
        bad += 1
    # THE LINE THE COMMAND LINE PRINTS, for a hit that is a sub-unit — the shape that broke.
    das, cfo, _gov = _fixture()["organizations"]
    by_ch = {o["oar_chapter"]: o for o in (das, cfo)}
    ran += 1
    line = cli_line(cfo, by_ch)
    if not (cfo["slug"] in line and "sub-unit of 125" in line and das["name"] in line):
        print(f"FAIL search-hit-prints-its-parent: {line!r}", file=sys.stderr)
        bad += 1
    ran += 1
    if "sub-unit" in cli_line(das, by_ch):
        print("FAIL top-level-hit-claims-no-parent", file=sys.stderr)
        bad += 1
    # A name no body has still resolves to nothing. Spanning a second name widens what
    # matches, and a resolver that started matching anything would be worse than one that
    # lost a match: a wrong agency attribution is worse than a name on a review list.
    got, basis = resolve("Department of Fisheries", organizations=orgs)
    ran += 1
    if got is not None or basis != "unmatched":
        print(f"FAIL resolution-refuses-a-name-no-body-has: -> {got!r} ({basis})",
              file=sys.stderr)
        bad += 1
    return bad, ran


def _proof_search_spans_every_name_a_body_is_known_by():
    """(failures, searches proven)."""
    bad = ran = 0
    org = _search_fixture()
    for query, expected, why in _SEARCH_CASES:
        got = name_matches(org, query)
        ran += 1
        if got != expected:
            print(f"FAIL search-{'finds' if expected else 'refuses'}-{why!r}: "
                  f"{query!r} -> {got}", file=sys.stderr)
            bad += 1
    # The same statement made through the command a human actually runs.
    for query in ("liquor control", "liquor and cannabis", "OLCC"):
        ran += 1
        if [o["slug"] for o in find(query, organizations=[org])] != [org["slug"]]:
            print(f"FAIL search-through-find: {query!r} does not resolve the body",
                  file=sys.stderr)
            bad += 1
    return bad, ran


def selftest() -> int:
    bad = 0
    for name, declaration, rule in _PROOFS:
        # `chapter_page_docs` fixed to the synthetic `_FIXTURE_CHAPTER_PAGE_DOCS` (code
        # review of #279), the same reason the `_CASES` loop below passes it: left at the
        # default, every one of these 15 proofs reads the two REAL scripts off disk and
        # compares their real count against the fixture's — spurious noise in the `got
        # {failures}` diagnostic this loop prints on an actual failure, and the opposite
        # of the reason this parameter was extracted in the first place.
        failures = check_registry(_fixture(), fields=declaration,
                                  chapter_page_docs=_FIXTURE_CHAPTER_PAGE_DOCS)
        if not any(f.rule == rule for f in failures):
            print(f"FAIL {name}: expected a [{rule}] failure, got {failures}",
                  file=sys.stderr)
            bad += 1
    bad += _proof_refresh_rejects_an_undeclared_scraped_field()
    bad += _proof_curated_keys_survive_in_declaration_order()
    bad += _proof_the_walk_says_what_it_cannot_answer()
    bad += _proof_the_relation_census_counts_every_kind()
    bad += _proof_chapter_page_count_check_fires_on_a_stale_docstring()
    bad += _proof_missing_registry_is_refused()
    bad += _proof_the_merge_is_what_carries_a_curated_relation()
    bad += _proof_the_merge_carries_a_derived_kind_onto_the_regenerated_entry()
    bad += _proof_the_carry_is_what_keeps_an_established_statutory_name()
    bad += _proof_session_law_form_boundary()
    resolutions = 0
    for proof in (_proof_search_spans_every_name_a_body_is_known_by,
                  _proof_a_promoted_name_loses_no_resolution):
        failed, ran = proof()
        bad += failed
        resolutions += ran
    for name, mutate, rule in _CASES:
        cat = _fixture()
        # THE FIXTURE'S OWN NOTE IS THE EXPECTED ONE HERE, not `REGISTRY_NOTE` — the
        # fixture's `note` is a synthetic stand-in built to name every FIELDS key
        # (see `_fixture()`), never the real prose, so `note-agrees-with-refresh` is
        # told to expect exactly what this fixture actually carries. A case that mutates
        # `cat["note"]` still trips it, same as production; a case that leaves `note`
        # alone does not.
        baseline_note = cat["note"]
        assert not check_registry(cat, refresh_note=baseline_note,
                                  chapter_page_docs=_FIXTURE_CHAPTER_PAGE_DOCS), \
            f"fixture does not pass cleanly ({name})"
        mutate(cat)
        failures = check_registry(cat, refresh_note=baseline_note,
                                  chapter_page_docs=_FIXTURE_CHAPTER_PAGE_DOCS)
        if not any(f.rule == rule for f in failures):
            print(f"FAIL {name}: expected a [{rule}] failure, got {failures}",
                  file=sys.stderr)
            bad += 1
    # THE DECLARATION, GATED FROM BOTH SIDES (#320, matching legal_status.py and
    # stated_census.py; both directions are `_LEDGER.gaps()`'s one call since #319). A rule
    # can go undetected by being DECLARED WITH NO PROOF (did it fire during this run) or by
    # being EMITTED WITH NO DECLARATION (does the AST agree with CHECK_RULES) — the second
    # failure mode is exactly the hole a hand-typed table left open, and #320's own
    # measurement (this module carried neither direction) is what this replaces.
    gaps = _LEDGER.gaps()
    if gaps.emitted_but_undeclared or gaps.unemitted_but_declared:
        print("FAIL every-rule-this-module-can-report-is-declared: "
              f"emitted-not-declared={sorted(gaps.emitted_but_undeclared)} "
              f"declared-not-emitted={sorted(gaps.unemitted_but_declared)}", file=sys.stderr)
        bad += 1
    if gaps.unfired:
        print(f"FAIL every-declared-rule-was-watched-firing: unfired={sorted(gaps.unfired)}",
              file=sys.stderr)
        bad += 1
    # THE COUNT NOW COMES FROM THE LEDGER, NOT FROM A LITERAL (#320, closes #301). The old
    # "+ 9" here was a hand count of eight proof calls above it — one violation demonstrated
    # per call, except `_proof_refresh_rejects_an_undeclared_scraped_field()`, which #275
    # grew a second, independent demonstration inside without this literal following it: the
    # total silently undercounted by one until #275's review corrected it alongside the
    # function, and #278 briefly grew and then retired a ninth call the same literal had to
    # be hand-updated for again. `_LEDGER.demonstrated_count` — how many DECLARED rules this
    # process watched fire, from `_LEDGER.fired` rather than a count anyone maintains by
    # hand — cannot go stale the way that literal did three times: it is not a count of how
    # many proof calls happen to exist above it, it is what actually happened when they ran,
    # and the two gates just above are what make it EQUAL to `len(CHECK_RULES)` on any clean
    # run rather than merely close to it.
    print(f"{len(_CASES)} case(s) and {len(_PROOFS)} declaration(s) demonstrated failing, "
          f"{resolutions} name resolution(s) proven, "
          f"{_LEDGER.demonstrated_count} rule(s) declared, every one both emitted by this "
          "module and watched firing here"
          if not bad else f"{bad} rule(s) did not fire")
    return 1 if bad else 0


def main():
    if "--refresh" in sys.argv:
        cmd_refresh()
    elif "--check" in sys.argv:
        return cmd_check()
    elif "--selftest" in sys.argv:
        return selftest()
    elif len(sys.argv) > 1:
        cat = load()
        by_ch = {o["oar_chapter"]: o for o in cat["organizations"]}
        for o in find(" ".join(a for a in sys.argv[1:] if not a.startswith("--"))):
            print(cli_line(o, by_ch))
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
