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
import re
import sys
import time
import urllib.request
from collections import namedtuple
from datetime import date
from html import unescape

import yaml

from repo_lib import REPO_ROOT

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
#   SCRAPED     the refresh writes it. `scraped_entry()` below is the only thing that may
#               produce one, and --check verifies this column against that constructor, so
#               calling a field scraped is a claim the code has to back up.
#   CURATED     nothing upstream produces it; it survives only because CURATED_KEYS carries
#               it across a refresh. Hand-reviewed data, and the reason this table exists.
#   MANUAL_FLAG `manual: true`, which is preserved by a different mechanism — it keeps the
#               WHOLE row (a body the chapter scrape can never see). Deliberately NOT
#               curated: copying the flag onto a row the scrape now produces would re-assert
#               a claim that a human is supposed to retire by hand after comparing names.
SCRAPED, CURATED, MANUAL_FLAG = "scraped", "curated", "manual-flag"

Field = namedtuple("Field", "origin required")

# One contract violation: which rule, which row, and what is wrong with it. A type rather
# than a formatted string so --selftest asserts on the RULE that fired instead of pattern-
# matching prose, which is how a test starts passing for the wrong reason.
Failure = namedtuple("Failure", "rule row detail")

FIELDS = {
    "slug": Field(SCRAPED, required=True),
    "name": Field(SCRAPED, required=True),
    # THE OAR NAME (CONTEXT.md): the name the administrative rules index gives a body, and
    # the string OAR-derived joins must match (ADR 0003). It lands BESIDE `name` rather than
    # replacing it, so consumers can move off `name` while `name` still means what it always
    # did — ADR 0003 changes what `name` holds, and a crosswalk that keeps matching a string
    # that quietly changed meaning is the failure those crosswalks exist to prevent.
    #
    # SCRAPED, NOT CURATED, and that is the whole point of the field. The chapter page's own
    # title is where this value comes from — `scraped_entry()` already reads it — so
    # declaring it CURATED would mean --refresh preserves the old file's copy and never
    # updates it: an upstream chapter retitle would move `name` and leave `oar_name` frozen
    # at a title the rules index no longer prints. A field that cannot track an upstream
    # retitle cannot be the string OAR-derived joins match on.
    "oar_name": Field(SCRAPED, required=True),
    # Null on 19 rows and that is not a gap: a body is in the registry because it EXISTS,
    # not because it issues rules (ADR 0003). Required means the KEY is present.
    "oar_chapter": Field(SCRAPED, required=True),
    "raw_index_name": Field(SCRAPED, required=True),
    "source_url": Field(SCRAPED, required=True),
    "parent_slug": Field(SCRAPED, required=True),
    "parent_chapter": Field(SCRAPED, required=True),
    # Written by the refresh when a chapter page's title would not parse or its fetch
    # failed. NOT curated even though the two rows carrying one today were hand-written:
    # both are `manual` rows, preserved whole, so they need nothing from CURATED_KEYS —
    # while making `note` curated would resurrect a stale "title not parseable" note onto a
    # row whose title parsed fine on the next refresh, which is a false claim about the
    # scrape rather than preserved curation.
    "note": Field(SCRAPED, required=False),
    "manual": Field(MANUAL_FLAG, required=False),
    # THE DAS AGENCY NUMBER (CONTEXT.md): the number DAS assigns a body in the Oregon
    # Accounting Manual (OAM 70.10.00). It identifies the body in the state's financial
    # administration and says nothing about whether it spends money — thirteen
    # semi-independent bodies carry one and are explicitly outside the state's accounting
    # system, which is why ADR 0003 renames the field off a name that says "budget".
    # Hand-reviewed, one number per body; the table is src/link_budget_codes.py.
    "das_agency_number": Field(CURATED, required=False),
    # THE SAME NUMBER UNDER THE NAME IT USED TO HAVE, readable for one deprecation cycle so
    # no consumer breaks mid-flight: #163 has 474 published documents to regenerate before
    # #177 can delete this key. Both keys are CURATED because both are committed data
    # nothing upstream produces — declaring the deprecated one anything else would have
    # --refresh drop the copy consumers are still reading. DAS_NUMBER_KEYS below is what
    # keeps the two from drifting apart.
    "budget_agency_code": Field(CURATED, required=False),
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
    # NOT required because an absent key is the honest default. All 189 rows are absent
    # today, and that says nobody has looked yet — which is a different claim from a body
    # that was looked at and has no separate enabling authority, and neither may be written
    # as a blank.
    "enabling_authority": Field(CURATED, required=False),
}

# THE ONE NUMBER'S TWO KEYS, FIELD OF RECORD FIRST. ADR 0003 renames `budget_agency_code`
# to `das_agency_number`, and this is the EXPAND half: every row that carries the number
# carries it under BOTH keys, with the same value, until #177 deletes the old one. Both keys
# hold the value rather than one key holding it and an accessor resolving the other, because
# the consumers this cycle protects do not run this code — three sibling corpora read
# agencies.yml as YAML, and one of them (#163) has 474 published documents keyed on the old
# name. A Python accessor is unreadable from there; a key in the file is not.
#
# Two copies of one fact can disagree, so `deprecated-key-agrees` in check_registry() states
# that they may not: a row carrying one key and not the other, or the two holding different
# numbers, is a contract violation rather than something a reader has to notice.
DAS_NUMBER_KEYS = ("das_agency_number", "budget_agency_code")

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
    # and ADR 0005 both use. NOTHING RESOLVES IT, and that is a hole ADR 0005 states rather
    # than one this form hides: the Oregon Constitution is not mirrored, so
    # `Or. Const. Art. XVII, sec. 99` is well-formed and unverifiable. Both gates report the
    # constitutional rows separately for that reason — "could not check" is never reported
    # as "is not there" (CONTEXT.md).
    # `(Amended)` is not decoration: Oregon carries BOTH Article VII (Original) and Article
    # VII (Amended), and the judicial power sits in the amended one — so a form without it
    # refuses a real authority for the Judicial Department, which is exactly the population
    # this field exists for. An allowlist that is too narrow is still an allowlist; it is
    # widened by a decision like this one rather than by a wildcard.
    ("constitution", re.compile(r"Or\. Const\. Art\. [IVXL]+[A-Z]?"
                                r"(?: \((?:Amended|Original)\))?, sec\. \d+[a-z]?")),
    # `Executive Order 20-03`, the citation 525 of the 526 mirrored orders carry. One of them is
    # cited `Executive Order 12-special-session` and is deliberately OUTSIDE this form:
    # widening it to admit a free-text suffix would admit every typo too, and if a body ever
    # turns out to be created by that order, it is a decision to record here rather than a
    # surprise at the gate.
    ("executive-order", re.compile(r"Executive Order \d\d-\d\d")),
)

# THE OTHER THING THE FIELD MAY SAY, and what makes the third state honest. A body that was
# reviewed and has no separate enabling authority records the REASON here — ADR 0004 names
# the common one: a `part_of` unit has nothing separate to enable. Written as a value rather
# than as a null, because a null and an absent key are read alike by every consumer, and the
# claims are opposite:
#
#   key absent                       nobody has looked yet         (all 189 rows today)
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
                  "sec. 1`), an executive order (`Executive Order 20-03`), or "
                  f"{NO_AUTHORITY!r} and the reason there is none")


def authority_census(orgs) -> str:
    """The three states of `enabling_authority`, counted over registry ROWS.

    ONE SENTENCE, TWO GATES, and counted from the file rather than from the reviewed table:
    the table says what SHOULD be recorded, and on any failure path the two disagree — a
    census that mixed them would report the intended state as the actual one. A summary that
    counted only the bodies carrying an authority would leave a reader to infer that the rest
    have none, which is the one reading this registry never permits.
    """
    values = [o["enabling_authority"] for o in orgs
              if isinstance(o, dict) and "enabling_authority" in o]
    none_recorded = sum(1 for v in values if classify_authority(v)[0] == "reviewed-none")
    return (f"{len(values) - none_recorded} recorded, {none_recorded} reviewed with none to "
            f"record, {len(orgs) - len(values)} of {len(orgs)} bodies not looked at yet")


CURATED_KEYS = frozenset(k for k, f in FIELDS.items() if f.origin == CURATED)
SCRAPED_KEYS = frozenset(k for k, f in FIELDS.items() if f.origin == SCRAPED)
UA = "executive-regulatory-frameworks (+https://github.com/OregonAI/executive-regulatory-frameworks)"

ENTRY_RE = re.compile(
    r'<dt class="col-sm-2">[^<]*</dt>\s*'
    r'<dd class="col-sm-10">(?:<a href="/rules/oar_chapter_(\d+[a-z]?)">(.*?)</a>'
    r'|([^<]+?)(?=<div class="card))', re.S)
CARD_RE = re.compile(r'<div class="card[^"]*quasi-sub-chapter"')
TITLE_RE = re.compile(r"<title>OAR Chapter \d+[a-zA-Z]? \W (.*?)</title>", re.S)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def scraped_entry(*, name, oar_chapter, raw_index_name, source_url, note=None):
    """One registry row as --refresh builds it from oregon.public.law.

    THE ONLY PLACE THE SCRAPE'S OWN FIELDS ARE WRITTEN, which is what lets --check
    simulate a refresh honestly: the simulation calls this constructor instead of copying
    the committed row's keys, so it cannot credit the scrape with producing a field the
    scrape never writes. Crediting it wrongly is the exact failure the simulation exists to
    catch — a curated field mislabelled `SCRAPED` would then look preserved while a real
    --refresh silently dropped it.

    ONE STRING, TWO FIELDS, ON PURPOSE. The chapter page title is the only name the scrape
    can see, and it is the OAR NAME (CONTEXT.md) — what the rules index calls this body. It
    is written to `oar_name`, where OAR-derived joins can rely on it, and to `name`, which
    still holds exactly what it held before. Writing it twice is what makes this the EXPAND
    half of ADR 0003's rename: consumers move onto `oar_name` while `name` is unchanged,
    rather than being re-verified after `name` has already changed meaning underneath them.

    parent_slug/parent_chapter are written null here and filled by the caller once the
    index tree is known; they are keys of a scraped row either way."""
    entry = {"slug": slugify(name), "name": name, "oar_name": name,
             "oar_chapter": oar_chapter,
             "raw_index_name": raw_index_name, "source_url": source_url}
    if note:
        entry["note"] = note
    entry["parent_slug"] = None
    entry["parent_chapter"] = None
    return entry


def write_das_agency_number(row: dict, number) -> None:
    """Write `number` onto `row` under BOTH keys of DAS_NUMBER_KEYS, field of record first.

    THE ONE PLACE THE NUMBER IS WRITTEN, so nothing can put it under a single key. Two
    copies of one fact are only safe while every writer maintains both, and a second
    hand-written spelling of "set the code" is how one of them starts being forgotten —
    which is the same drift `deprecated-key-agrees` reports when it has already happened.

    IN PLACE, because the row object is shared. link_budget_codes.py holds the same dict in
    its slug index and in the organizations list, and returning a new row would update one
    of those and leave the other holding the old one.

    The keys are re-inserted rather than assigned, so that what THIS function writes prints
    the two copies of the number on adjacent lines — a plain assignment appends a new key at
    the end of the row, which puts the second copy under `aliases`, three lines below the
    first. That is a courtesy to the human reading the diff, not an invariant of the file:
    `preserve_curated()` re-appends every curated key in frozenset order, so a --refresh can
    reorder them or split the pair with `aliases`, and does it differently per run (#182).
    Nothing depends on the order — `deprecated-key-agrees` compares the VALUES.
    """
    ordered, landed = {}, False
    for key, value in row.items():
        if key in DAS_NUMBER_KEYS:
            if not landed:
                ordered.update(dict.fromkeys(DAS_NUMBER_KEYS, number))
                landed = True
        else:
            ordered[key] = value
    if not landed:      # a row that carried no number: the pair goes at the end
        ordered.update(dict.fromkeys(DAS_NUMBER_KEYS, number))
    row.clear()
    row.update(ordered)


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
    """Stop a refresh that produced a field FIELDS does not declare SCRAPED.

    THE DECLARATION IS BINDING ON THE SCRAPE, and this is the half --check cannot reach: it
    reads committed data and never runs a scrape, so it can only ask whether the rows it can
    see would survive. A field added to the scrape without being declared would make that
    simulation wrong in the direction that hides losses — the field would be compared as if
    curated and fail, or worse, be assumed rewritten — so the refresh that would introduce it
    stops here instead, before anything is written."""
    undeclared = {k for o in orgs for k in o} - SCRAPED_KEYS
    if undeclared:
        sys.exit(f"the scrape produced undeclared field(s) {sorted(undeclared)} — add them "
                 "to FIELDS (origin SCRAPED) before writing the registry")


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
    stopped matching anything."""
    curated_keys = CURATED_KEYS if curated_keys is None else curated_keys
    for o in prev_orgs:
        current = by_slug.get(o["slug"])
        if not current:
            continue
        for key in curated_keys:
            if key in o and key not in current:
                current[key] = o[key]


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
                note = "chapter page title not parseable; name from index (abbreviated)"
                fallbacks += 1
        except Exception as e:
            note = f"chapter page fetch failed ({e}); name from index (abbreviated)"
            fallbacks += 1
        orgs[i] = scraped_entry(name=name, oar_chapter=ch, raw_index_name=index_name,
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
        # NAME READER — MACHINERY: --refresh deriving a chapterless parent's name from the
        # common prefix of its children's chapter-page titles. Every name in play here is
        # one the scrape just produced, so it is the OAR name under either field; the row is
        # built by scraped_entry(), which writes it to both.
        child_names = [orgs[j]["name"] for j, e in enumerate(entries)
                       if e[2] == i and orgs[j]]
        prefixes = {n.split(", ")[0] for n in child_names if ", " in n}
        if len(prefixes) == 1:
            name = prefixes.pop()
            note = None
        else:
            name = index_name
            note = ("chapterless group; children's name prefixes don't agree "
                    f"({sorted(prefixes)}), name from index (abbreviated)")
        orgs[i] = scraped_entry(name=name, oar_chapter=None, raw_index_name=index_name,
                                source_url=INDEX_URL, note=note)

    by_slug = {}
    for o in orgs:
        if o["slug"] in by_slug:
            sys.exit(f"SLUG COLLISION: chapters {by_slug[o['slug']]['oar_chapter']} and "
                     f"{o['oar_chapter']} both slugify to {o['slug']!r} — needs a human "
                     "decision, not silent dedup")
        by_slug[o["slug"]] = o
    for i, (ch, _, parent_idx) in enumerate(entries):
        if parent_idx is not None:
            orgs[i]["parent_slug"] = orgs[parent_idx]["slug"]
            orgs[i]["parent_chapter"] = orgs[parent_idx]["oar_chapter"]

    assert_scrape_declared(orgs)

    if CATALOG.exists():
        prev_orgs = yaml.safe_load(CATALOG.read_text()).get("organizations", [])
        preserve_manual(prev_orgs, orgs, by_slug)
        preserve_curated(prev_orgs, by_slug)

    cat = {
        "note": ("Canonical registry of Oregon agencies and their sub-units, keyed on "
                 "the OAR chapter assignment scheme as presented by oregon.public.law/"
                 "rules (an unofficial but well-maintained mirror; official chapter "
                 "assignment lives with the SoS Administrative Rules Unit). Proper "
                 "names come from each chapter page's own title; the index tree "
                 "provides the parent/sub-unit hierarchy (parent_chapter/parent_slug). "
                 "Third registry source: a data.oregon.gov dataset and the SoS Blue "
                 "Book directory were both previously used and dropped after review "
                 "(2026-07-18/19). validate_frontmatter.py requires every content "
                 "file's agency: field to resolve to 'statewide', 'external', or a "
                 "slug here. oar_name is the OAR name — the chapter page's own title, "
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
                 "budget_agency_code is the same number under the name it used to carry, "
                 "readable for one deprecation cycle (ADR 0003); the two always hold the "
                 "same value. enabling_authority, where present, is what created the body "
                 "— an ORS citation, a constitutional article, or an executive order (ADR "
                 "0003) — or `none: ` and the reason there is none. It is hand-reviewed "
                 "(src/link_enabling_authority.py), is NOT scraped, and is preserved "
                 "across --refresh. An ABSENT enabling_authority means nobody has reviewed "
                 "this body yet; it never means the body has no enabling authority, which "
                 "is what the `none: ` form says and says with a reason."),
        "source_url": INDEX_URL,
        "retrieved": date.today().isoformat(),
        "organizations": sorted(orgs, key=lambda o: o["slug"]),
    }
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    n_sub = sum(1 for o in orgs if o["parent_slug"])
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
    identical bytes on all 189 committed rows, so any measurement of "which field does this
    consumer really read" run against committed data passes by construction. Promoting
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
# matched `name` alone until #187, and was unaffected in the data because `oar_name` holds
# the same bytes as `name` on all 189 rows — so the change is invisible against the
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


def simulate_refresh(prev_orgs, curated_keys=None):
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

    `name` is passed as the scrape's one name string because that is where the committed
    rows hold it today — `oar_name` holds the same bytes on all 189 of them. When ADR 0003
    makes `name` the statutory name the two stop agreeing, and this call has to read
    `oar_name` instead; nothing here would notice, because a scraped field is skipped by the
    survival comparison, so that step belongs with the change that splits them.
    """
    orgs, by_slug = [], {}
    for o in prev_orgs:
        if o.get("manual"):
            continue
        # NAME READER — MACHINERY: the survival simulation replaying the scrape from
        # committed values. `name` is passed as the scrape's one name string because that is
        # where the committed rows hold it; see this function's docstring for what has to
        # change here when ADR 0003 splits the two.
        row = scraped_entry(name=o.get("name"), oar_chapter=o.get("oar_chapter"),
                            raw_index_name=o.get("raw_index_name"),
                            source_url=o.get("source_url"), note=o.get("note"))
        row["parent_slug"] = o.get("parent_slug")
        row["parent_chapter"] = o.get("parent_chapter")
        orgs.append(row)
        # setdefault, not assignment: a slug claimed twice is unique-slug's failure to
        # report, and masking one of the two here would turn it into a survival failure
        # against the wrong row.
        by_slug.setdefault(row["slug"], row)
    preserve_manual(prev_orgs, orgs, by_slug)
    preserve_curated(prev_orgs, by_slug, curated_keys)
    return {o["slug"]: o for o in orgs}


def _row_id(o, i):
    """What to name a row in a failure. Falls back to its position, because a row missing
    the slug is exactly the row that most needs pointing at."""
    slug = o.get("slug") if isinstance(o, dict) else None
    return slug if isinstance(slug, str) and slug else f"organizations[{i}]"


def check_registry(cat, fields=None) -> list:
    """Every way the registry violates its contract, as Failures.

    `fields` is the declaration to check against, defaulting to the one this module ships.
    It is a PARAMETER so that --selftest can check a registry against a differently-declared
    table — the two ways a curated field goes missing from CURATED_KEYS are statements about
    the declaration, and no registry row can express either one."""
    fields = FIELDS if fields is None else fields
    curated = frozenset(k for k, f in fields.items() if f.origin == CURATED)
    scraped = frozenset(k for k, f in fields.items() if f.origin == SCRAPED)

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

    for i, o in enumerate(orgs):
        if not isinstance(o, dict):
            failures.append(Failure("readable-row", _row_id(o, i),
                                    "not a mapping, so no rule below could be evaluated "
                                    "against it"))
            continue
        for key in o:
            if key not in fields:
                failures.append(Failure(
                    "declared-field", _row_id(o, i),
                    f"field {key!r} is not declared in FIELDS — if it is curated, "
                    "--refresh will destroy it; declare it"))
        # An absent key and a null value are different claims: `parent_slug: null` says a
        # body has no parent, an absent parent_slug says nobody asked. Consumers read both
        # as "no parent", which is how the second silently becomes the first.
        for key, field in fields.items():
            if field.required and key not in o:
                failures.append(Failure("required-field", _row_id(o, i),
                                        f"required field {key!r} is absent (null is a "
                                        "value; absent is not)"))

    # Position is carried alongside, so a failure points at the row's place in the
    # committed file rather than its place among the rows that happened to be readable.
    rows = [(i, o) for i, o in enumerate(orgs) if isinstance(o, dict)]

    # ONE NUMBER, TWO KEYS, WHICH MAY NOT DRIFT APART. DAS_NUMBER_KEYS is the EXPAND half of
    # ADR 0003's rename, and a duplicated value is only safe while something states that the
    # copies agree. A row carrying the number under one key and not the other is the failure
    # that matters most: it does not look like an error from either side. Whichever consumer
    # reads the key that is missing sees a body with no DAS agency number, and this registry
    # is explicit that absence means no counterpart was found, never that nobody looked.
    for i, o in rows:
        held = {k: o[k] for k in DAS_NUMBER_KEYS if k in o}
        if not held:
            continue     # 109 bodies carry no number at all, which is not drift
        absent = [k for k in DAS_NUMBER_KEYS if k not in o]
        if absent:
            failures.append(Failure(
                "deprecated-key-agrees", _row_id(o, i),
                f"the DAS agency number is on {', '.join(sorted(held))} but absent from "
                f"{', '.join(absent)} — both keys are readable for one deprecation cycle "
                "(#177 removes the old one), so a row carrying one and not the other reads "
                "as 'no number' to whichever consumer read the other"))
        elif len(set(held.values())) > 1:
            failures.append(Failure(
                "deprecated-key-agrees", _row_id(o, i),
                f"the DAS agency number differs between its two keys ({held!r}) — one body "
                "has one number, and nothing in the row says which of these is the "
                "hand-reviewed one"))
    # THE ENABLING AUTHORITY'S THREE STATES, KEPT APART. A row carrying no key at all is
    # saying nobody has looked yet, which is the state all 189 rows are in and the only one
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

    # IDENTITY. The slug is the only thing a sibling corpus joins on, and the chapter is
    # what put most rows here; either one claimed twice attributes one body's documents to
    # another. --refresh already calls a slug collision a human decision rather than silent
    # dedup, and this is the same rule applied to what is already committed.
    for key, rule in (("slug", "unique-slug"), ("oar_chapter", "unique-chapter")):
        seen = {}
        for i, o in rows:
            value = o.get(key)
            if value is None:   # 19 bodies hold no chapter, which is not a collision
                continue
            if value in seen:
                failures.append(Failure(rule, _row_id(o, i),
                                        f"{key} {value!r} is already claimed by "
                                        f"{seen[value]!r}"))
            else:
                seen[value] = _row_id(o, i)

    # THE PARENT RELATION. ADR 0004 splits `parent_slug` into *part of* and *administered
    # by*, and both readings agree on this much: the relation names a body this registry
    # carries. A pointer at a slug nobody has states a hierarchy no reader can check, and
    # parent_chapter is the same pointer written twice — when the two disagree, each
    # consumer resolves the parent differently depending on which half it read.
    by_slug = {o["slug"]: o for _, o in rows if isinstance(o.get("slug"), str)}
    for i, o in rows:
        parent_slug = o.get("parent_slug")
        if parent_slug is None:
            continue
        parent = by_slug.get(parent_slug)
        if parent is None:
            failures.append(Failure("parent-resolves", _row_id(o, i),
                                    f"parent_slug {parent_slug!r} is not a slug in this "
                                    "registry"))
            continue
        if o.get("parent_chapter") != parent.get("oar_chapter"):
            failures.append(Failure(
                "parent-agrees", _row_id(o, i),
                f"parent_chapter {o.get('parent_chapter')!r} but {parent_slug!r} holds "
                f"chapter {parent.get('oar_chapter')!r}"))

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

    # CALLING A FIELD SCRAPED IS A CLAIM ABOUT THE CODE, so it is checked against the code.
    # The survival comparison below skips scraped fields on the grounds that the refresh
    # rewrites them; a curated field wrongly declared SCRAPED would therefore be skipped
    # while a real --refresh dropped it — a false pass, which is the one outcome a gate must
    # not produce. `scraped_entry()` is the only thing that writes a scraped field, so its
    # own key set settles the question. The probe passes a TRUTHY note on purpose: the
    # constructor omits that key when a chapter page parsed fine, which is most of the time.
    written = set(scraped_entry(name="probe", oar_chapter=None, raw_index_name=None,
                                source_url=None, note="probe"))
    for key in sorted(scraped - written):
        failures.append(Failure("scraped-field", "FIELDS",
                                f"{key!r} is declared SCRAPED but scraped_entry() does "
                                "not write it — --refresh would drop it"))
    for key in sorted(written - scraped):
        failures.append(Failure("scraped-field", "FIELDS",
                                f"scraped_entry() writes {key!r}, which FIELDS does not "
                                "declare SCRAPED"))

    # WHAT A --refresh WOULD LEAVE BEHIND. Everything above reads the registry as it stands;
    # this reads it as it would stand after the command that rebuilds it, which is the only
    # place curation has ever been lost. Compared for every field that is NOT scraped,
    # allowlist-style: whatever the refresh does not write, it has to preserve.
    #
    # A row with no name or no slug is one the simulation cannot run on at all: the refresh
    # derives the slug from the name, so there is nothing to rebuild and nothing to compare.
    # Such a row is REPORTED as unevaluated rather than crashed on or quietly left out of
    # the comparison — "could not check" is never reported as "is not there" (CONTEXT.md).
    simulatable, unevaluable = [], []
    for i, o in rows:
        # NAME READER — MACHINERY: whether a row can be simulated at all, which turns on
        # the PRESENCE of a name rather than on what it says.
        (simulatable if isinstance(o.get("name"), str) and isinstance(o.get("slug"), str)
         else unevaluable).append((i, o))
    for i, o in unevaluable:
        failures.append(Failure("survives-refresh", _row_id(o, i),
                                "no name or no slug, so a refresh cannot be simulated "
                                "against this row — it is unchecked, not clean"))
    survivors = simulate_refresh([o for _, o in simulatable], curated_keys=curated)
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
            elif got[key] != o[key]:
                failures.append(Failure("survives-refresh", _row_id(o, i),
                                        f"--refresh would change {key!r} from {o[key]!r} "
                                        f"to {got[key]!r}"))
    return failures


def cmd_check() -> int:
    """Report every contract violation in the committed registry. Exit 1 if any."""
    if not CATALOG.exists():
        print(f"FAIL [readable-registry] {CATALOG}: no registry to check", file=sys.stderr)
        return 1
    cat = load()
    failures = check_registry(cat)
    for f in failures:
        print(f"  FAIL [{f.rule}] {f.row}: {f.detail}", file=sys.stderr)
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
    # THE ENABLING AUTHORITY'S CENSUS, PRINTED RATHER THAN LEFT TO BE COUNTED.
    print(f"enabling authority: {authority_census(orgs)}")
    return 0


# ------------------------------------------------------------------------------ selftest
#
# THE PROOF THAT THE GATE ABOVE CAN FAIL. Every rule --check enforces is exercised here
# against a synthetic registry built to violate exactly one of them, because a check nobody
# has watched fail is not known to work — it is only known to be quiet. Synthetic fixtures:
# no network, no read of the committed registry.


def _fixture():
    """A registry that passes every rule. Each case below breaks exactly one thing."""
    das = scraped_entry(name="Department of Administrative Services", oar_chapter="125",
                        raw_index_name="Dept. of Administrative Services",
                        source_url=f"{BASE}/rules/oar_chapter_125")
    write_das_agency_number(das, "107")   # the pair, written the way every writer writes it
    # AN IMPOSSIBLE CITATION ON PURPOSE. This gate checks the FORM of an authority and
    # resolves nothing (link_enabling_authority.py --check does that, against the mirror),
    # and ORS has no chapter 999 — so the fixture exercises the field without asserting
    # what created the Department of Administrative Services, which is a question nobody
    # has reviewed. A real citation here would read as a verdict.
    das["enabling_authority"] = "ORS 999.999"
    cfo = scraped_entry(name="Chief Financial Office", oar_chapter="122",
                        raw_index_name="Chief Financial Office",
                        source_url=f"{BASE}/rules/oar_chapter_122")
    cfo["parent_slug"], cfo["parent_chapter"] = das["slug"], das["oar_chapter"]
    gov = scraped_entry(name="Office of the Governor", oar_chapter=None,
                        raw_index_name=None, source_url=None)
    gov["manual"] = True
    gov["aliases"] = ["Governor's Office"]
    return {"organizations": [das, cfo, gov]}


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
    """A row that dropped a field every row carries. `parent_slug: null` and no
    parent_slug at all read the same to a consumer and are not the same claim."""
    del cat["organizations"][1]["parent_slug"]


def _case_missing_oar_name(cat):
    """A row that carries a `name` but no `oar_name`. The whole point of landing the OAR
    name in its own field is that consumers can join on it INSTEAD of `name`, so a row
    missing one is a row those joins silently lose — and it is invisible from the outside,
    because `name` still holds the same string today. It stops holding it (ADR 0003), and
    then the gap is a body no OAR-derived join resolves."""
    del cat["organizations"][1]["oar_name"]


def _case_missing_name(cat):
    """A row that dropped `name`. The same deletion as the case above breaks two rules at
    once — nothing can be simulated for the row, AND a required field is gone — and a case
    asserts one rule, so each gets its own. `name` and `oar_name` are the two names a
    consumer can resolve a body by, and every row is required to carry both."""
    del cat["organizations"][1]["name"]


def _case_das_number_without_the_deprecated_key(cat):
    """The number under its own name only. Every consumer still reading
    `budget_agency_code` — 474 published documents' worth (#163) — silently loses this
    body's number, and loses it as "this body has none" rather than as an error, which is
    the state the deprecation cycle exists to make impossible."""
    del cat["organizations"][0]["budget_agency_code"]


def _case_deprecated_key_without_the_das_number(cat):
    """The number under the deprecated name only — a row the rename skipped. It reads
    clean to anyone still on the old key and reads as "no number" to everyone who has
    already moved, so the half-migrated row is invisible from both sides."""
    del cat["organizations"][0]["das_agency_number"]


def _case_das_number_keys_disagree(cat):
    """Two keys, two different numbers. Whichever a consumer read is the answer it got,
    so one body's spending attaches to two identities — and nothing in the row says which
    number is the reviewed one."""
    cat["organizations"][0]["budget_agency_code"] = "999"


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


def _case_parent_slug_resolves_to_nothing(cat):
    """A parent pointer aimed at no body. Whatever ADR 0004 splits `parent_slug` into,
    the relation names a body IN this registry; a dangling one states a hierarchy that
    cannot be checked and reads as a fact."""
    cat["organizations"][1]["parent_slug"] = "department-of-administrative-service"


def _case_parent_chapter_disagrees(cat):
    """The two halves of the same pointer disagreeing. Consumers use whichever half they
    happened to read, so the disagreement resolves differently per consumer."""
    cat["organizations"][1]["parent_chapter"] = "999"


def _case_slug_the_scrape_would_not_produce(cat):
    """A slug hand-edited away from the one slugify() derives from the name. --refresh
    rebuilds the row under the DERIVED slug, so the hand-edited row — and the curated
    fields riding on it — is not preserved onto anything; it just stops existing.

    The number is written by write_das_agency_number() rather than assigned, so this case
    breaks exactly one rule: setting one of the two keys by hand would also trip
    `deprecated-key-agrees`, and a case that fires two rules stops saying which one it is
    about."""
    write_das_agency_number(cat["organizations"][1], "107")
    cat["organizations"][1]["slug"] = "cfo"


def _case_field_the_refresh_drops(cat):
    """A non-scraped field that nothing preserves. `manual: false` is not the flag that
    keeps a row whole, so the row is rebuilt from the scrape and the key disappears —
    the silent-loss failure mode CURATED_KEYS exists to prevent, in a field that is not
    in it."""
    cat["organizations"][1]["manual"] = False


def _case_row_the_simulation_cannot_run_on(cat):
    """A row with no name. The refresh derives a slug from the name, so there is nothing
    to simulate — and a row that could not be evaluated must be REPORTED as unevaluated,
    never left out of the report as though it had passed."""
    del cat["organizations"][0]["name"]


def _case_registry_emptied(cat):
    """Every row gone. A gate that reports a registry with no bodies in it as clean is a
    gate that passes without checking anything — and every rule below is vacuously true of
    an empty list, so this one has to be stated separately."""
    cat["organizations"] = []


_CASES = [
    ("undeclared-field", _case_undeclared_field, "declared-field"),
    ("registry-emptied", _case_registry_emptied, "registry-populated"),
    ("row-the-simulation-cannot-run-on", _case_row_the_simulation_cannot_run_on,
     "survives-refresh"),
    ("slug-the-scrape-would-not-produce", _case_slug_the_scrape_would_not_produce,
     "survives-refresh"),
    ("field-the-refresh-drops", _case_field_the_refresh_drops, "survives-refresh"),
    ("parent-slug-resolves-to-nothing", _case_parent_slug_resolves_to_nothing,
     "parent-resolves"),
    ("parent-chapter-disagrees", _case_parent_chapter_disagrees, "parent-agrees"),
    ("duplicate-slug", _case_duplicate_slug, "unique-slug"),
    ("duplicate-chapter", _case_duplicate_chapter, "unique-chapter"),
    ("missing-required-field", _case_missing_required_field, "required-field"),
    ("missing-oar-name", _case_missing_oar_name, "required-field"),
    ("missing-name", _case_missing_name, "required-field"),
    # THE THREE WAYS THE TWO KEYS HOLDING THE DAS AGENCY NUMBER COME APART, which is the
    # whole risk this deprecation cycle carries: one key holding what the other does not,
    # in either direction, and the two holding different numbers.
    ("das-number-without-the-deprecated-key", _case_das_number_without_the_deprecated_key,
     "deprecated-key-agrees"),
    ("deprecated-key-without-the-das-number", _case_deprecated_key_without_the_das_number,
     "deprecated-key-agrees"),
    ("das-number-keys-disagree", _case_das_number_keys_disagree, "deprecated-key-agrees"),
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
    ("row-is-not-a-mapping", _case_row_is_not_a_mapping, "readable-row"),
    # THE TWO WAYS A BODY STOPS BEING FINDABLE BY A NAME IT HAS, which is what promoting
    # `name` (#168) must not be able to do to a reader.
    ("oar-name-that-matches-nothing", _case_oar_name_that_matches_nothing,
     "findable-by-both-names"),
    ("statutory-name-that-matches-nothing", _case_statutory_name_that_matches_nothing,
     "findable-by-both-names"),
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
# Both name `das_agency_number` — the FIELD OF RECORD for the number, not the deprecated
# `budget_agency_code` beside it. Either would demonstrate the mechanism today, because both
# are curated; the deprecated one goes away with #177, and a proof pinned to it would have to
# be repointed by whoever does that instead of just continuing to hold.
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
]


def _proof_refresh_rejects_an_undeclared_scraped_field() -> int:
    """--refresh's own half of the declaration, which --check cannot reach: it reads
    committed data and never runs a scrape, so a field the SCRAPE started writing without
    declaring it can only be caught where the scrape runs. Demonstrated failing here
    because a guard nobody has watched fire is not known to fire.

    The probe field is MADE UP, and it has to be. This proof used to name `oar_name` — a
    field ADR 0003 said the registry was going to carry — and the day it started carrying
    one the proof stopped proving anything: the guard correctly said nothing, and the only
    reason that surfaced as a red build rather than a quiet pass is that the assertion is on
    the guard firing. Any real field is a field FIELDS may legitimately declare tomorrow."""
    try:
        assert_scrape_declared([{"slug": "a-body", "headcount": 412}])
    except SystemExit as e:
        return 0 if "headcount" in str(e) else 1
    print("FAIL refresh-rejects-undeclared-scraped-field: the scrape guard did not fire",
          file=sys.stderr)
    return 1


# ------------------------------------------------------------------------- the search proof
#
# A BODY MUST STAY FINDABLE BY THE NAME ITS READER KNOWS, and after ADR 0003 there are two
# such names on every row. The fixture below is the only place they DIFFER: `name` and
# `oar_name` hold identical bytes on all 189 committed rows, so a proof taken from committed
# data passes whichever field the matcher reads and proves nothing about which it is.


def _search_fixture():
    """One body under three names: the statutory one ADR 0003 promotes into `name`, the
    rules index's title in `oar_name`, and a curated former name in `aliases`. Every one of
    the three is a name some Oregon source prints for the same body."""
    org = scraped_entry(name="Oregon Liquor and Cannabis Commission", oar_chapter="845",
                        raw_index_name="Liquor & Cannabis Comm'n",
                        source_url=f"{BASE}/rules/oar_chapter_845")
    org["name"] = "Oregon Liquor and Cannabis Commission"      # statutory (ORS 471.705)
    org["oar_name"] = "Oregon Liquor Control Commission"       # what the rules index prints
    org["aliases"] = ["OLCC"]
    return org


_SEARCH_CASES = [
    # (what a reader typed, whether it must find the body, why)
    ("liquor and cannabis", True, "its statutory name"),
    ("liquor control", True, "its OAR name — the name 36,953 rule documents carry"),
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
    nursing = scraped_entry(name="Board of Nursing", oar_chapter="851",
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
        failures = check_registry(_fixture(), fields=declaration)
        if not any(f.rule == rule for f in failures):
            print(f"FAIL {name}: expected a [{rule}] failure, got {failures}",
                  file=sys.stderr)
            bad += 1
    bad += _proof_refresh_rejects_an_undeclared_scraped_field()
    resolutions = 0
    for proof in (_proof_search_spans_every_name_a_body_is_known_by,
                  _proof_a_promoted_name_loses_no_resolution):
        failed, ran = proof()
        bad += failed
        resolutions += ran
    for name, mutate, rule in _CASES:
        cat = _fixture()
        assert not check_registry(cat), f"fixture does not pass cleanly ({name})"
        mutate(cat)
        failures = check_registry(cat)
        if not any(f.rule == rule for f in failures):
            print(f"FAIL {name}: expected a [{rule}] failure, got {failures}",
                  file=sys.stderr)
            bad += 1
    print(f"{len(_CASES) + len(_PROOFS) + 1} violation(s) demonstrated failing, "
          f"{resolutions} name resolution(s) proven"
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
