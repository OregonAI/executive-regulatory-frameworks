#!/usr/bin/env python3
"""Populate _meta/catalog/ors.yml with a new ORS chapter's table of contents
(Gate A input for corpus growth: run this, review the printed summary, THEN run
ingest_ors.py on the approved chapters). Idempotent -- safe to rerun.

  python3 src/catalog_ors.py 240 276 278 279A 279B 279C 282 283 292

Fetches the chapter HTML (same snapshot ingest_ors.py will reuse), locates the
table-of-contents span right after the "EDITION" marker (bounded by the first
prose marker: "(1)" or "means"), and extracts (section, catchline) pairs. Junk
entries (bare cross-references, repealed/renumbered stubs with no real catchline)
are dropped -- never fabricated, only parsed from what the source actually prints.
"""
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError

import yaml

from html_to_text import html_to_text
from ingest_lib import fetch
from repo_lib import REPO_ROOT, SNAPSHOT_DIR, ws_only, snapshot_text

CATALOG = REPO_ROOT / "_meta/catalog/ors.yml"

CHAPTER_TITLES = {
    "174": "Construction of Statutes; General Definitions",
    "176": "Governor",
    "177": "Secretary of State",
    "178": "State Treasurer",
    "179": "Administration of State Institutions",
    "180": "Attorney General; Department of Justice",
    "181A": "State Police; Public Safety Standards and Training",
    "182": "State Administrative Agencies Generally",
    "185": "Oregon Disabilities Commission; Commissions on Hispanic Affairs, Black Affairs, and Asian and Pacific Islander Affairs; Commission for Women",
    "240": "State Personnel Relations",
    "276": "Public Facilities",
    "278": "Insurance for Public Bodies",
    "279A": "Public Contracting - General Provisions",
    "279B": "Public Contracting - Public Procurements",
    "279C": "Public Contracting - Public Improvements",
    "282": "Public Printing",
    "283": "Interagency Services",
    "292": "Salaries and Expenses of State Officers and Employees",
}


# oregonlegislature.gov zero-pads the numeric part to three digits: ors025.html, not
# ors25.html (which 404s). Every chapter below 100 was silently unreachable until this
# was fixed, which is why 54 of them were missing from the catalog entirely.
def chapter_url(ch):
    m = re.fullmatch(r"(\d+)([A-Za-z]?)", str(ch))
    slug = f"{int(m.group(1)):03d}{m.group(2).lower()}" if m else str(ch).lower()
    return f"https://www.oregonlegislature.gov/bills_laws/ors/ors{slug}.html"


def fetch_chapter(ch):
    snap_id = f"ors-chapter-{ch.lower()}"
    html_path = SNAPSHOT_DIR / f"{snap_id}.html"
    if not html_path.exists():
        url = chapter_url(ch)
        time.sleep(1.0)  # bulk runs walk hundreds of chapters; don't hammer the source
        raw = fetch(url)
        html_path.write_bytes(raw)
        (SNAPSHOT_DIR / f"{snap_id}.txt").write_text(snapshot_text(raw), encoding="utf-8")
    return (SNAPSHOT_DIR / f"{snap_id}.txt").read_text(encoding="utf-8", errors="replace")


# #415: both title caps below used to be a bare `[:160]`, unmeasured since the original
# mass-ingest commit (`ed04bec8`) that introduced this module -- no comment anywhere tied
# 160 to an actual technical constraint (a YAML line-length limit, a display width), and
# #397's own review flagged it as possibly-deliberate but explicitly declined to call it a
# bug for lack of evidence ("This may be an intentional display-width choice ... not
# asserting the cap itself is wrong"). #415 is that evidence: measured 2026-09-13 against a
# fresh, uncapped re-parse of all 569 committed chapters (after #411/#412's fix above, since
# a glued heading/Note artificially inflates a title's length and would otherwise be
# counted as "real" content the cap cuts) -- 406 of 37,744 section titles and 5 of 569
# chapter titles genuinely exceed 160 characters, 303 of the 406 cut MID-WORD
# ("...advertising discriminatory preference prohibited; allowance for reas[onable
# modification...]", 659A.145). That is real catchline text, deleted, not a display choice
# -- the content policy this repo runs on (AGENTS.md: full-text-first, never truncate real
# source content) applies to a title exactly as it does to a `## Full text` section.
# The longest real title measured, section or chapter, either before or after this fix:
# 314.057 at 504 characters (a citation-heavy catchline naming nine separate federal
# session laws by name and public-law number -- see `_selftest`'s own worked example).
# Chosen over removing the cap outright ("do not silently remove a constraint someone chose
# on purpose"): a cap is still cheap insurance against `parse_toc`'s density-boundary logic
# someday running unbounded into body prose the way `_RECOVERED_TAIL_CAP` already guards
# the RECOVERED branch against -- it costs nothing on today's corpus (every real title
# clears it) and only ever fires on a future pathology, exactly the same shape of tradeoff
# `_HEADING_WINDOW`'s own 700,000 already makes. Set with the same margin this module's
# other measured bounds use (`_CATCHLINE_WINDOW`: 372 measured -> 600, ~1.6x): 504 * 1.6 ≈
# 806, rounded to 800. If some future title exceeds 800, it is truncated again -- reported
# the same way this one was, by a fresh full-corpus measurement, not assumed away.
_TITLE_CAP = 800


def extract_chapter_title(raw_text, ch):
    """Pull the chapter's real title from the source ("Chapter 305. Administration of
    Revenue and Tax Laws; Appeals ... 306. ...") so mass-catalogued chapters aren't all
    labeled "Chapter NNN". Returns None if the pattern isn't found.

    Two heading forms occur. The dominant one on the chapter pages themselves is an em
    dash ("Chapter 25 — Child Support Services 2025 EDITION"); only the period form was
    handled originally, which is why 371 of 433 catalogued chapters carry a bare label.
    The title runs until the edition banner or the first TOC section number."""
    t = ws_only(raw_text)
    # Some chapters carry a legislative-session notice between the heading and the edition
    # banner; without it as a terminator the notice is swallowed into the title.
    notice = (r"New sections of law|(?:ORS|Uncodified) sections (?:in this chapter|printed)|Note:"
              r"|TITLE\s+\d+|_{3,}")
    m = re.search(rf"Chapter\s+{re.escape(ch)}\s*[—–-]\s*(.+?)\s+"
                  rf"(?:\d{{4}}\s+EDITION|{notice}|\d{{1,3}}[A-Z]?\.\d{{3}}\b)", t)
    if not m:
        m = re.search(rf"Chapter\s+{re.escape(ch)}\.\s*(.+?)\s+\d{{2,3}}[A-Z]?\.\s", t)
    if not m:
        # Repealed/renumbered chapters print "Chapter 181 (Former Provisions) State Police;
        # ..." with the title running until the first all-caps part heading. Keeping the
        # marker in the title is the point: these are not current law.
        m = re.search(rf"Chapter\s+{re.escape(ch)}\s+\(Former Provisions\)\s+"
                      rf"(.+?)\s+(?=TITLE\s+\d+|[A-Z][A-Z ']{{7,}})", t)
        if m:
            return f"{m.group(1).strip(' .;')} (Former Provisions)"[:_TITLE_CAP]
    if not m:
        # A fourth heading form, with NO separator between the number and the title — the
        # edition banner sits between them instead: "Chapter 5 2025 EDITION County Courts
        # (Judicial Functions)". Both patterns above need a dash or a period after the
        # chapter number, so this one fell through to the bare "Chapter 5" label. The title
        # runs until the all-caps repeat of itself that heads the chapter body.
        m = re.search(rf"Chapter\s+{re.escape(ch)}\s+\d{{4}}\s+EDITION\s+"
                      rf"(.+?)\s+(?=TITLE\s+\d+|[A-Z][A-Z ']{{7,}})", t)
    if not m:
        return None
    title = m.group(1).strip(" .;")
    return title[:_TITLE_CAP] if len(title) >= 3 else None


# A cross-reference embedded in an earlier entry's own catchline ("'Agency' defined for
# ORS 283.140 and 283.143") contains section-number-looking substrings that would
# otherwise be mistaken for real TOC-entry boundaries below, truncating the entry that
# contains them and stealing/discarding the real entry those numbers actually belong to.
#
# #286: was `(?:\s+and\s+\d{3}[A-Z]?\.\d{3})*` -- covered only an "and"-joined LIST
# ("283.140 and 283.143"), not a "to"-joined RANGE ("691.405 to 691.485"), Oregon's other
# ordinary way of citing a span of sections, or a chain mixing both ("824.020 to 824.042,
# 824.050 to 824.110 and 824.200 to 824.256" -- one "ORS" governing three ranges joined by
# comma and "and"). The uncovered continuation reproduced this exact bug ONE TOKEN OVER
# from the case the comment above already understood: `691.485` matched, mistaken for the
# START of a new TOC entry, and stole the bare part heading trailing it ("BOARD") --
# or, worse, both fed to `TRAILING_HEADING_RE` (452.300 stole "VECTOR CONTROL DISTRICTS",
# then lost everything but "VECTOR" to that SECOND regex) -- while the section's own real
# entry, appearing later with the same number, was silently dropped as a duplicate
# (#286's two heading-fragment cases, `691.485`/`452.300`). The same gap also TRUNCATED
# an entry whose own catchline names its own range ("735.345 Violation of ORS 735.300 to
# 735.365" cut to "...to" at the false boundary; "824.200 Definitions for ORS 824.200 to
# 824.256" the same way) -- #286's other two parser-attributed rows. `,`/`and`/`to` cover
# every join word measured across every xref chain on the committed chapter snapshots.
# #415 (757.015): a subsection citation -- "(1)", "(2)(a)" -- can sit between a number
# and the join word that follows it ("ORS 757.105 (1) and 757.495"), which the chain above
# never allowed: the regex jumped straight from a number to `(?:,|and|to)` with nothing in
# between, so this shape simply didn't match past the first number, leaving "757.495"
# unprotected and mistaken for a new TOC-entry boundary (truncating 757.015's own title at
# "...and"). `(?:\s*\([0-9a-zA-Z., ]+\))*` after EACH number, not just the first, since the
# same subsection-cite shape could in principle trail any number in a chain, not only the
# one right after "ORS " -- measured against every xref chain in the corpus, only 757.015
# needs it, but the chain shape itself doesn't privilege one position over another.
XREF_RE = re.compile(
    r"\bORS\s+\d{3}[A-Z]?\.\d{3}(?:\s*\([0-9a-zA-Z., ]+\))*"
    r"(?:\s*(?:,|and|to)\s*\d{3}[A-Z]?\.\d{3}(?:\s*\([0-9a-zA-Z., ]+\))*)*\b")
# A bare part/subpart heading ("TREATMENT OF PRISONERS") between two numbered TOC entries
# has no section number of its own, so it isn't a split boundary either — it trails onto
# the PRECEDING entry's catchline instead. Distinguished from real title text by being an
# all-caps multi-word run (ORS catchlines are Title Case); length-gated so a short acronym
# at the end of a real title ("...eligibility for TANF") isn't mistaken for one.
TRAILING_HEADING_RE = re.compile(r"\s+[A-Z][A-Z '\-]{7,}$")

# #397: `TRAILING_HEADING_RE` above guesses a heading from TEXT SHAPE (an all-caps run,
# length-gated so a short trailing acronym in a real catchline -- "...eligibility for
# TANF" -- isn't mistaken for one) and gets it wrong two ways, both measured (2026-09-10)
# against the committed catalog: a heading under its 8-character floor ("COURTS", "VENUE",
# "LOANS" -- 135 titles at the time), and a heading followed by its own parenthetical
# sub-heading, which the `$` anchor can never reach at all ("ART AND CRAFT MATERIALS
# (Generally)" -- 359 titles at the time). These two counts were superseded by code review
# (2026-09-12), which found three more causes of the identical bug (see `_HEADING_UNIT_RE`
# and `_toc_heading_phrases` below) -- `_selftest`'s own docstring carries the re-measured,
# current totals for both families.
#
# The source itself already marks the boundary -- it just isn't shape, it's LAYOUT:
# every heading and sub-heading in the TOC is typeset as its OWN paragraph, blank-line
# -delimited from the entries around it (measured on every chapter checked: the separator
# is `\n\n \xa0 \n\n`, a blank line, an isolated non-breaking-space line, a blank line).
# `ws_only()` collapses that structural signal away before `parse_toc` ever sees it, which
# is the actual reason the only prior mitigation had to guess from shape in the first place.
#
# Reading the source's own paragraphs instead of guessing from length is also why this does
# NOT eat a real trailing acronym: `279A.152`'s own catchline ends "...recycled PETE" with
# `PETE` wrapped onto the SAME paragraph as the rest of the sentence (a single `\n` line
# -wrap, no blank line before it) -- it is never its own paragraph, so it never enters
# `_toc_heading_phrases`' set at all, at any length. The boundary comes from structure, not
# from how long the trailing word is.
_PARA_SEP_RE = re.compile(r"\n\s*\n")
# Same char class as `TRAILING_HEADING_RE`, minus its length floor (paragraph isolation is
# what makes something a heading here, not how long it is) plus three characters real
# headings use that TRAILING_HEADING_RE never had to cover, because it only ever matched a
# heading with nothing else following -- the Unicode right single quote ("INJURED WORKERS’
# MEMORIAL SCHOLARSHIP", ch. 654), and comma/semicolon, which multi-clause part headings use
# routinely ("REGISTRATION, ENFORCEMENT AND MODIFICATION OF SUPPORT ORDERS", ch. 110;
# "LIQUOR; DRUGS", ch. 471/474). Safe to widen this far and no further: the match requires
# the ENTIRE isolated paragraph to be uppercase, and no real ORS catchline -- always Title
# Case -- is ever printed as its own all-uppercase paragraph, comma or not.
# Digits, and an optional trailing ALL-CAPS parenthetical on the SAME paragraph, both added
# by code review (2026-09-12) against all 569 committed chapters -- the original version of
# this regex (letters and the punctuation above only, no digits, no parens) left at least 21
# rows glued, in two shapes it never covered:
#   - A heading paragraph that happens to include a digit: a year ("WATER COMPANIES
#     ORGANIZED UNDER 1891 ACT", ch. 541), a population threshold ("PARK COMMISSION IN
#     CITIES OF 3,000 OR MORE", ch. 226), or a designation ("2-1-1 SYSTEM", ch. 403;
#     "PROHIBITIONS RELATED TO 340B DRUGS", ch. 689) -- the same gap TRAILING_HEADING_RE
#     already had, for the same reason.
#   - A heading and its OWN parenthetical sub-heading typeset as ONE paragraph, not two
#     ("FINANCING LOCAL IMPROVEMENTS (BANCROFT BONDING ACT)", ch. 223) -- distinct from the
#     two-paragraph heading+sub-heading combination a few lines down, and unreachable by
#     `_SUBHEADING_UNIT_RE` (which requires the WHOLE unit to start with `(`).
# Digits are safe to admit -- measured against the two real-corpus false-positive risks the
# committed comment (removed here) warned about, both still excluded: ch. 688's "SECTION 1.
# PURPOSE" and ch. 815's "ORS 803.430" each contain a period, which stays outside this
# class, and a bare page number ("94") in that same ch. 815 wrapped table is excluded by the
# `(?=.*[A-Z])` lookahead requiring at least one letter in the isolated paragraph. The
# trailing parenthetical is gated the same way as the heading text itself (all-caps, same
# character class) so it cannot admit a Title-Case sub-heading a real ORS catchline could
# ever produce.
# Not closed here (this residual is re-measured and reported, not asserted away): a heading
# with an embedded lowercase ordinal suffix ("OREGON EDUCATIONAL ACT FOR THE 21st CENTURY",
# ch. 329) is not all-uppercase and matches neither this regex nor TRAILING_HEADING_RE.
_HEADING_UNIT_RE = re.compile(
    r"^(?=.*[A-Z])[A-Z0-9][A-Z0-9 ,;'’\-]*(?:\([A-Z0-9][A-Z0-9 ,;'’\-]*\))?$")
# A sub-heading is Title Case, not ALL CAPS ("(Generally)", "(Regulation; Prohibited
# Acts)"), so it needs its own pattern -- matched purely by being its own parenthetical
# paragraph, with or without a heading paragraph immediately before it (several chapters
# use a bare sub-heading, with no heading of its own, for a later group under one a heading
# paragraph earlier already named -- ch. 453's "(Miscellaneous)" governing 453.135 is a
# real, committed example).
_SUBHEADING_UNIT_RE = re.compile(r"^\(.+\)$")
# #411/#412: the source's own editorial marginalia -- introduced by the literal word
# "Note" (with or without a following colon; both shapes are printed, measured against
# all 569 committed chapters: "Note Provision relating to fills ...--1989 c.45 §2" and
# "Note: Definitions in 25.010 and 25.011 apply to ORS chapter 107." both occur) -- is
# typeset exactly like a heading or sub-heading: its OWN blank-line-isolated paragraph
# (verified directly against the raw source for every row this fix corrects, not
# assumed; see `_toc_heading_phrases`'s own docstring). Unlike a heading, it is Title
# Case free prose of arbitrary length, so it needs its own pattern matched only at the
# unit's START (the paragraph boundary already did the isolating; there is no fixed
# shape the REST of a Note paragraph's text has to satisfy, the way a heading's ALL-CAPS
# run does). `\bNote\b` rather than a bare `Note` prefix so a real catchline that merely
# happens to start with a longer word sharing the prefix (there is no such word in
# English, but the boundary costs nothing to state precisely) is never mistaken for one.
_NOTE_UNIT_RE = re.compile(r"^Note\b")
# The binding quantity here is a RAW BYTE OFFSET, not an entry count -- entry count is how
# long a chapter's TOC *content* is, but this window has to reach the LAST heading-shaped
# paragraph in raw, uncollapsed text, which runs far longer per entry than `parse_toc`'s own
# ws_only'd window because of exactly the blank-line/nbsp paragraph padding this reads.
# Measured (2026-09-12) against all 569 committed chapter snapshots, with the digit- and
# embedded-parenthetical-permissive `_HEADING_UNIT_RE` above: 174 of 569 have their last
# heading-or-sub-heading-shaped paragraph beyond raw offset 150,000 (the prior value of
# this constant); the furthest is chapter 656 (~220 entries, the largest real chapter) at
# 636,548. At 150,000 those 174 chapters' TOC tail was silently out of reach for this
# function -- any governing heading positioned that late could not enter `phrases` at all,
# regardless of whether a title actually needed it. Widened to 700,000, comfortably past
# the measured maximum, with margin for a chapter that grows.
# Running past the real TOC into body text is harmless in the ordinary case -- a stray
# extra candidate phrase can only ever strip something if a title's own tail already ends
# in that exact literal text -- but this is NOT true for a phrase recovered by merging a
# paragraph the source wraps across a blank line (see the merge in `_toc_heading_phrases`):
# for those rows, correctness depends on the phrase's own text reappearing, unbroken,
# somewhere the title's tail can match against, which is a property of where the source
# happens to repeat itself, not something this window or the strip mechanism verifies.
# Measured against the current corpus: widening 150,000 to 700,000 does not change a single
# title across all 569 committed chapters (every governing heading a real row's title
# needed was already within the old window) -- this constant is prophylactic against a
# larger future chapter, not a fix for a defect visible in today's data.
_HEADING_WINDOW = 700_000


def _after_edition(text, span):
    """The one place both `parse_toc` and `_toc_heading_phrases` used to separately
    duplicate "find the chapter's own `EDITION` banner, bail if it isn't there, slice a
    window right after it" -- on two different strings (this module's raw, unnormalized
    snapshot text for the latter; `ws_only`'d text for the former), so this takes `text` as
    a parameter rather than assuming which one. Returns `None`, not `""`, when the chapter
    has no such banner at all, so a caller can tell "no TOC region" apart from "an empty
    one" (38 of 569 committed chapters carry no `EDITION` token; see `_selftest`'s own #349
    measurement)."""
    i = text.find("EDITION")
    if i < 0:
        return None
    start = i + len("EDITION")
    return text[start:start + span]


def _toc_heading_phrases(raw_text):
    """Every isolated paragraph in the TOC region that is EITHER an all-caps section-group
    heading (optionally with its own all-caps parenthetical on the same paragraph) OR a
    parenthetical sub-heading of any case OR a `Note` editorial marginalia paragraph,
    normalized the same way `parse_toc` normalizes a catchline (`ws_only`) so they compare
    equal. This is broader than "heading or sub-heading" alone: any isolated parenthetical
    paragraph qualifies, which is also why a `(Temporary provisions relating to ...)`
    editorial compilation note -- furniture, not a section-group heading -- is collected and
    stripped the same way (measured 2026-09-12, all 569 committed chapters: 112 rows; #346's
    own thread already called this text garbage, so stripping it is not new policy, just an
    undocumented side effect of the same mechanism, documented here).
    A heading immediately followed by its own sub-heading PARAGRAPH is combined into one
    phrase ("ART AND CRAFT MATERIALS (Generally)"); either stands alone otherwise ("COURTS";
    a bare "(Miscellaneous)"). A parenthetical sub-heading the source itself wraps across a
    paragraph break ("(Educator Professional" / "Development Program)", ch. 329) is merged
    back into one unit before either pattern is tried, so it is not lost to being
    unbalanced-parenthesis in each half. Longest first, so a combined phrase is tried before
    its own bare-heading prefix would also match.

    #411/#412: a `Note ...` paragraph (see `_NOTE_UNIT_RE`) is collected as its own bare
    phrase, never combined with a neighbor -- unlike a heading, it never needs to be (a
    Note is never followed by its own separate sub-heading paragraph the way a section-
    group heading is), and the corpus prints more than one back to back often enough
    (401.123, 657B.430, 285B.799) that each must remain independently strippable by
    `_strip_glued_headings`'s own loop rather than assuming exactly one per gap."""
    window = _after_edition(raw_text, _HEADING_WINDOW)
    if window is None:
        return []
    units = [ws_only(u) for u in _PARA_SEP_RE.split(window)]
    # A parenthetical the source's own typesetting splits across a blank line opens a "("
    # with no closing ")" in its own unit -- merge it with the very next unit before either
    # heading pattern below ever sees it (a still-unbalanced merge simply matches neither
    # pattern, exactly as the un-merged fragments already didn't, so this cannot introduce a
    # false match).
    merged = []
    k = 0
    while k < len(units):
        u = units[k]
        if u.startswith("(") and ")" not in u and k + 1 < len(units):
            u = u + " " + units[k + 1]
            k += 1
        merged.append(u)
        k += 1
    units = merged
    phrases = []
    k = 0
    while k < len(units):
        u = units[k]
        if _HEADING_UNIT_RE.match(u):
            if k + 1 < len(units) and _SUBHEADING_UNIT_RE.match(units[k + 1]):
                phrases.append(u + " " + units[k + 1])
                k += 2
                continue
            phrases.append(u)
        elif _SUBHEADING_UNIT_RE.match(u):
            phrases.append(u)
        elif _NOTE_UNIT_RE.match(u):
            phrases.append(u)
        k += 1
    phrases.sort(key=len, reverse=True)
    return phrases


def _strip_glued_headings(rest, phrases):
    """Removes a KNOWN heading/sub-heading phrase (see `_toc_heading_phrases`) glued onto
    the tail of a catchline -- exact, structurally-sourced text, never a length guess.
    Loops rather than stripping once, because a bare heading paragraph, a separately
    -typeset sub-heading paragraph, and a `(Temporary provisions relating to ...)` note are
    not always combined into one phrase by `_toc_heading_phrases`, and a chapter's editors
    can stack more than one group of these onto the same gap (ORS 238.730, code review,
    2026-09-12: two section-group headings, each with its own bare sub-heading AND its own
    temporary-provisions note, seven strips deep). A fixed bound here is not a safe
    simplification: measured against all 569 committed chapters, `for _ in range(3)` --
    this function's own prior bound -- left exactly 2 rows (238.730 above; 526.905, the
    same stacking shape) only partially stripped, mid-phrase, for no reason a reader could
    see from the code. Looping until no phrase matches instead is provably bounded anyway:
    every successful strip removes at least one phrase plus its separating space, so `rest`
    strictly shortens each time and the loop ends in at most `len(rest)` iterations."""
    while True:
        for p in phrases:
            if rest == p:
                # `parse_toc`'s own `len(rest) < 3` filter drops whatever this returns --
                # an entry whose ENTIRE title, once the glued phrase is peeled off, is
                # nothing at all (the TOC printed only the group heading here, no real
                # catchline of its own). Fires on zero rows today (verified: identical
                # entry counts across all 569 committed chapters, no empty titles) -- this
                # is the brief's own explicitly out-of-scope "section-group heading
                # admitted as a section" class (#406), silently dropped rather than
                # cataloged, not a case this function is asked to solve.
                return ""
            if rest.endswith(" " + p):
                rest = rest[: -(len(p) + 1)].rstrip()
                break
        else:
            break
    return rest


# #346: the two shapes chapter furniture takes right after a chapter's own genuinely LAST
# TOC entry (measured against all 4 affected chapters -- see `_catchline_end`'s own
# docstring): the SAME all-caps part/subpart heading TRAILING_HEADING_RE already knows,
# here searched from the START of the tail rather than anchored to its end (there is no
# further real TOC entry to anchor an end-position search against); and a standalone
# "Note" -- the source's own marker introducing editorial marginalia ("Note: The following
# list ... is provided for the user's convenience"), Title Case rather than ALL CAPS, so
# the heading pattern alone does not catch it (measured: 171.992, 186.520 have no all-caps
# run before their own "Note", only 221.928 and 306.815 do).
_RECOVERED_ALLCAPS_RE = re.compile(r"[A-Z][A-Z '\-]{7,}")
_RECOVERED_NOTE_RE = re.compile(r"\bNote\b")
# A cap on how far a recovered entry's own catchline can run when NEITHER marker appears --
# not measured against any of the 4 known chapters (both markers appear in all four, well
# under this), but an explicit bound rather than the unbounded run into arbitrary body text
# the naive fix was rejected for producing (#346's thread).
_RECOVERED_TAIL_CAP = 2000


def _catchline_end(tail: str) -> int:
    """Where a RECOVERED final TOC entry's own catchline ends, within `tail` (the chapter
    text starting at that entry's own section-number match) -- the earliest of
    `_RECOVERED_ALLCAPS_RE`, `_RECOVERED_NOTE_RE`, or `_RECOVERED_TAIL_CAP`, never past the
    end of `tail` itself. Exists so a genuinely recovered entry (see `parse_toc`'s own
    comment at its `cut` computation) gets a boundary anchored to ITS OWN catchline rather
    than either silently dropping (the pre-#346 behavior) or running on into whatever
    chapter furniture follows (the naive fix #346's thread measured and rejected)."""
    limit = min(len(tail), _RECOVERED_TAIL_CAP)
    for pat in (_RECOVERED_ALLCAPS_RE, _RECOVERED_NOTE_RE):
        m = pat.search(tail[:limit])
        if m:
            limit = min(limit, m.start())
    return limit


# #415 (279C.337): the committed snapshot's own TOC region already carries a stray SPACE
# right after a "/" ("construction manager/ general contractor services") that this
# section's own three committed body occurrences -- extracted by the same `html_to_text`
# pipeline, from the same page -- do not carry ("manager/general" throughout). It is not a
# `ws_only` collapse this module introduces (the character on this exact byte, checked
# directly against the committed snapshot, is already a literal space, not a newline
# `ws_only` turned into one), so it cannot be fixed by changing how whitespace is collapsed
# -- it has to be removed as its own normalization. Measured against the full corpus: this
# is the ONLY TOC title containing a "/" followed by a space, so collapsing that pattern out
# of a title's tail is narrow by measurement, not merely by construction, and matches the
# convention every other slash-joined term in this corpus (verified against the committed
# body text, not assumed) actually uses -- no surrounding space.
_SLASH_SPACE_RE = re.compile(r"/\s+")


def parse_toc(raw_text, ch):
    t = ws_only(raw_text)
    # Wide enough for any chapter's real TOC (the largest, ORS 656, has ~220 entries) --
    # the old fixed 30,000-char window plus a first-match-of-"(1)"/"means" boundary was too
    # small AND too fragile for large chapters: it broke whenever an early section's own
    # catchline happened to contain either phrase (e.g. ORS 656.010 "Treatment by spiritual
    # means"), silently truncating the TOC to a handful of entries. Instead, find every
    # real (non-cross-reference) section-number match in a wide window, and use match
    # DENSITY to find the boundary: the TOC is a dense run of "NUM catchline NUM catchline
    # ..." (each entry a few dozen characters), while body prose is not -- the first big
    # gap between consecutive matches marks the transition to body text.
    chunk = _after_edition(t, 600_000)
    if chunk is None:
        return []
    heading_phrases = _toc_heading_phrases(raw_text)
    xref_spans = [m.span() for m in XREF_RE.finditer(chunk)]
    # #412 (569.995): a `Note` paragraph's OWN text can itself list a run of the
    # chapter's own bare section numbers with no `ORS` prefix ("Note: 569.010, 569.020,
    # ..., 569.160, all relating to lime manufacture and distribution, repealed by 1953
    # c.41 §2."), because it is naming sections repealed out of THIS chapter, not citing
    # another one -- XREF_RE never matches these (it requires the literal `ORS ` the
    # source only prints before a cross-CHAPTER citation), so without this exclusion
    # `num_re` below mistakes the first bare number inside the Note for a new TOC-entry
    # boundary and truncates the entry the Note is glued to right at the Note's own
    # opening words, before `_strip_glued_headings` ever gets a complete phrase to match
    # against. Excluded the same way `xref_spans` already is: every Note phrase this
    # chapter's `_toc_heading_phrases` collected is exact, structurally-sourced text (see
    # `_NOTE_UNIT_RE`), so its own span in `chunk` -- found by searching for that literal
    # text, not guessed -- is furniture, never a real TOC-entry boundary.
    note_spans = [m.span() for p in heading_phrases if _NOTE_UNIT_RE.match(p)
                  for m in re.finditer(re.escape(p), chunk)]

    def real_boundary(m):
        return (not any(a <= m.start() < b for a, b in xref_spans)
                and not any(a <= m.start() < b for a, b in note_spans))

    # The UCC chapters (71-80) number sections with FOUR digits after the point --
    # 72.1010, not 72.101 -- so a hard \d{3}\b matched nothing and silently yielded an
    # empty TOC for every one of them. Case-insensitive because a lettered chapter is
    # printed uppercase in the text (86A.095) whatever case the caller passed.
    num_re = re.compile(re.escape(ch) + r"[A-Z]?\.\d{3,4}\b", re.I)
    all_matches = [m for m in num_re.finditer(chunk) if real_boundary(m)]
    if not all_matches:
        return []
    GAP = 600
    # #346: when the chapter's own genuinely LAST TOC entry is itself immediately
    # followed by a >600-char gap (no nearby xref keeps the density high past it),
    # `all_matches[cut]` here IS that last entry, not a body reoccurrence -- unconditionally
    # excluding it from `bounds` would drop it from the catalog entirely (measured: 8 of the
    # 569 committed chapters reach this branch -- 171, 186, 191, 199, 221, 237, 306, 358 --
    # though only 4 of those eight -- 171, 186, 221, 306, named in `_selftest` below -- go on
    # to survive the downstream `[`-split and length/case filters a few lines down; the other
    # four recover a repealed-section bracket artifact that those filters correctly drop).
    cut = len(all_matches) - 1
    for k in range(len(all_matches) - 1):
        if all_matches[k + 1].start() - all_matches[k].start() > GAP:
            cut = k
            break
    last = all_matches[cut]

    # A body reoccurrence of an already-claimed number (the ordinary case: `last`'s own
    # number matches an EARLIER bound) means `all_matches[cut]` really is the TOC/body
    # boundary -- exclude it, exactly as before. Otherwise `last` is a genuine, never-yet
    # -seen entry with no next TOC match near enough to bound it, and it gets included as
    # one more bound, with `_catchline_end` giving IT a boundary anchored to its own
    # catchline rather than the unbounded run into chapter furniture a plain "include it"
    # fix was measured and rejected for (#346's thread: recovers the entry but glues on
    # a heading, a temporary-provisions note, or both).
    earlier_numbers = {m.group(0).upper() for m in all_matches[:cut]}
    if last.group(0).upper() in earlier_numbers:
        toc = chunk[:last.start()]
        bounds = [m.start() for m in all_matches[:cut]]
    else:
        toc = chunk[:last.start() + _catchline_end(chunk[last.start():])]
        bounds = [m.start() for m in all_matches[:cut]] + [last.start()]
    parts = [toc[b:(bounds[i + 1] if i + 1 < len(bounds) else len(toc))]
             for i, b in enumerate(bounds)]
    out, seen = [], set()
    for p in parts:
        pm = re.match(r"(" + re.escape(ch) + r"\.\d{3,4})\s+(.*)", p.strip(), re.I)
        if not pm:
            continue
        num, rest = pm.groups()
        # #412 (413.805, 458.740): stripping a trailing PERIOD here, before
        # `_strip_glued_headings` runs, discards it even when that period is the LAST
        # character of a glued `Note ...` phrase's own exact text (a Note is a full
        # sentence and always ends with one) -- so when nothing else follows the Note in
        # this segment, the period this early strip removes is exactly the character
        # `_strip_glued_headings`'s own suffix match needs to see, and the match silently
        # fails. Whitespace only here; the period still comes off in the ORDINARY case
        # (no glued phrase) via the unconditional `.strip(" .")` two lines down, which
        # runs AFTER the strip has had its chance to match the phrase's own full text.
        rest = re.split(r"\[", rest)[0].strip()
        rest = _strip_glued_headings(rest, heading_phrases).strip(" .")
        rest = TRAILING_HEADING_RE.sub("", rest).strip(" .")
        rest = _SLASH_SPACE_RE.sub("/", rest)
        # a heavily-renumbered chapter (e.g. 279, split into 279A/B/C in 2003) often carries
        # a "repealed sections" summary elsewhere on the page listing old numbers with their
        # repeal year in a bracket ("279.435 [... repealed by ... in 1989]") -- these also
        # match the section-number pattern but aren't real TOC entries. A real catchline is
        # always capitalized; a lowercase-first fragment like "in 1989]" is this artifact.
        if num in seen or len(rest) < 3 or rest.lower() in ("to", "enacted in lieu of") \
                or not (rest[0].isupper() or rest[0] in "“‘\"'"):
            continue
        seen.add(num)
        out.append({"number": num, "title": rest[:_TITLE_CAP], "status": "not_ingested"})
    return out


def _selftest() -> int:
    """#286. `XREF_RE` widened to cover "to"-joined ranges and comma/"and"/"to" chains,
    not just an "and"-joined list -- proved against the actual committed chapter
    snapshots that produced the bug, the same reproduction #286 itself measured with,
    #346 too (see the second block below) -- neither is a synthetic fixture; both are the
    real 569 `_meta/snapshots/ors-chapter-*.txt` this parser runs against in production.
    A third block, #349, is different: zero of the 569 committed chapters reach
    `_RECOVERED_TAIL_CAP`, so nothing real is left to pin it against -- that block's
    fixture is synthetic on purpose, standing in for a corpus case that does not exist
    today.
    A fourth block, #397, is real chapters again: a following section-group heading (and,
    fixed in the same change for the same structural reason, a bare parenthetical
    sub-heading with no heading of its own) glued onto the PRECEDING entry's title. Measured
    (2026-09-12, code review, against a fresh re-parse of all 569 committed chapters vs. the
    committed catalog, excluding 16 rows of pre-existing unrelated catalog drift -- wording
    fixes and one already-separately-fixed xref-truncation row not yet backfilled): **2,486**
    titles change -- 326 bare-heading, 402 heading+parenthetical, 1,646 bare-subheading, and
    112 a fourth family this docstring did not originally name: a `(Temporary provisions
    relating to ...)` editorial compilation note (see `_toc_heading_phrases`'s own docstring).
    203 of the 2,486 recover from a committed title that was truncated exactly at the
    160-char cap by the glued text; of those, 2 (`441.427`, `466.530`) recover a REAL trailing
    acronym (`HIV`, `PCB`) that the pre-#397 code's shape-only `TRAILING_HEADING_RE` had eaten
    outright -- the other 201 simply lose glued noise the cap had been truncating, no content
    at risk either way. See `_toc_heading_phrases`'s own docstring for why a real trailing
    acronym still attached to its sentence (`279A.152`'s "...recycled PETE") is never at risk.
    Of the 2,486, 24 rows are corrected ONLY because of three additional causes found by code
    review and fixed in the same change (not present in the original count of "1 of 2,465"):
    a digit inside an otherwise-isolated heading paragraph (18 rows, e.g. `541.990`'s "WATER
    COMPANIES ORGANIZED UNDER 1891 ACT"), an ALL-CAPS parenthetical on the heading's OWN
    paragraph rather than a separate one (3 rows, e.g. `223.161`'s "FINANCING LOCAL
    IMPROVEMENTS (BANCROFT BONDING ACT)"), and a parenthetical sub-heading the source itself
    wraps across a blank line (2 rows, `329.820`, `455.453`) -- one row (`801.610`) needed
    both the digit and embedded-parenthetical fixes. TRUE RESIDUAL, re-measured after all of
    the above: **5 rows** still carry a known phrase glued mid-title rather than at the tail
    -- a `Note ...` editorial marginalia (Title Case, not parenthetical, so `_toc_heading_
    phrases` never captures it) or a second heading/note follows the first before the next
    real section number, so the exact-suffix strip in `_strip_glued_headings` cannot reach
    it. Tracked, not fixed here: issue filed, see its number in the PR body.
    `python3 src/catalog_ors.py --selftest`."""
    from repo_lib import Checks
    ck = Checks()

    def secs(ch: str) -> dict:
        path = SNAPSHOT_DIR / f"ors-chapter-{ch.lower()}.txt"
        raw = path.read_text(encoding="utf-8", errors="replace")
        return {s["number"]: s["title"] for s in parse_toc(raw, ch)}

    # THE TWO HEADING-FRAGMENT CASES: an in-catchline "to" range's own tail number
    # ("...ORS 691.405 to 691.485") used to be an uncovered false TOC-entry boundary,
    # stealing a bare part heading ("BOARD") as 691.485's title while the real entry
    # later in the text was dropped as a `seen` duplicate.
    s691 = secs("691")
    ck("691.485 no longer captures the bare 'BOARD' heading fragment",
       s691.get("691.485") == "Board of Licensed Dietitians")
    s452 = secs("452")
    ck("452.300 no longer captures 'VECTOR' (TRAILING_HEADING_RE's own further bite "
       "into the stolen heading text)",
       s452.get("452.300") == "Oregon Health Authority vector control program")

    # THE TWO IN-CHAPTER XREF-TRUNCATION CASES: a section naming its OWN range in its
    # own catchline ("735.345 Violation of ORS 735.300 to 735.365; penalties") used to
    # be truncated at the false boundary the untracked "to" continuation created.
    s735 = secs("735")
    ck("735.345 is no longer truncated at the in-catchline 'to'",
       s735.get("735.345") == "Violation of ORS 735.300 to 735.365; penalties")
    s824 = secs("824")
    ck("824.200 is no longer truncated at the in-catchline 'to'",
       s824.get("824.200") == "Definitions for ORS 824.200 to 824.256")

    # A COLLATERAL CASUALTY OF THE SAME BUG, not named in #286's own list: the false
    # boundary a section's OWN self-referencing range created also shadowed the LATER,
    # genuinely separate entry sharing that same number (735.365 itself, "Short
    # title") via the `seen` dedup -- fixed by the same regex change, not a second fix.
    ck("735.365 (the range's own endpoint, a separate real entry) is no longer "
       "shadowed by the false boundary inside 735.345's catchline",
       s735.get("735.365") == "Short title")

    # THE ORIGINAL "and"-ONLY CASE THIS REGEX ALREADY COVERED MUST KEEP WORKING: an
    # "and"-joined cross-reference embedded in an earlier entry's own catchline
    # ("283.130 'Agency' defined for ORS 283.140 and 283.143") must still not be
    # mistaken for a real TOC-entry boundary -- 283.140 and 283.143 must each keep
    # their OWN separate, correct titles, not 283.130's leftover text.
    s283 = secs("283")
    ck("283.130 keeps its own full catchline, not truncated at the embedded xref",
       s283.get("283.130") == "“Agency” defined for ORS 283.140 and 283.143")
    ck("283.140 (the xref's first target) keeps its own real title",
       s283.get("283.140") == "Telephone and telecommunications, mail, shuttle bus "
       "and messenger services; recovery of costs; rules")
    ck("283.143 (the xref's second target) keeps its own real title",
       s283.get("283.143") == "Surcharge for telecommunications services; purpose; "
       "exempt agencies")

    # #346: THE FOUR CHAPTERS MEASURED AFFECTED (of all 569 committed snapshots) by the
    # cut-exclusion off-by-one -- each chapter's own genuinely last TOC entry, previously
    # dropped from the catalog entirely because `all_matches[cut]` unconditionally excluded
    # it rather than checking whether it was a body reoccurrence. Two shapes of chapter
    # furniture follow the real catchline in these four: an ALL-CAPS part/subpart heading
    # (221, 306) and a standalone "Note" introducing editorial marginalia (171, 186,
    # arriving with no all-caps heading first) -- `_catchline_end` covers both, and each
    # assertion below is exact-match against the SOURCE's own text, not a substring, so a
    # regression that reintroduces the dropped-entry bug OR reintroduces the naive fix's
    # garbage-suffixed title (measured and rejected in #346's own thread) both fail here.
    s171 = secs("171")
    ck("171.992 (last TOC entry, immediately followed by a standalone 'Note', no "
       "all-caps heading first) is recovered, not dropped, and not garbage-suffixed",
       s171.get("171.992") == "Civil penalty for violation of lobby regulation")
    s186 = secs("186")
    ck("186.520 (same 'Note'-first shape as 171.992) is recovered clean",
       s186.get("186.520") == "Compact provisions")
    s221 = secs("221")
    ck("221.928 (last TOC entry, followed by an ALL-CAPS part heading before its own "
       "'Note') is recovered, not dropped, and not garbage-suffixed with the heading or "
       "the temporary-provisions note that follow it in the source",
       s221.get("221.928") == "Record of ordinances; compilation accepted as evidence")
    s306 = secs("306")
    ck("306.815 (same ALL-CAPS-heading-first shape as 221.928) is recovered clean",
       s306.get("306.815") == "Tax on transfer of real property prohibited; exceptions")

    # THE ORDINARY CASE (523 of the 569 committed chapters end this way; the other 46 split
    # into the 8 that reach the RECOVERED branch below and the 38 whose snapshot carries no
    # "EDITION" token at all, so `parse_toc` returns `[]` before this decision point is ever
    # reached -- see #349's own measurement a few lines down) MUST KEEP WORKING: chapter 691's
    # own density-cut match (691.405) IS a body reoccurrence already claimed by an earlier
    # bound, so it must still be EXCLUDED exactly as before -- not turned into a spurious
    # extra entry now that the cut can also recover a genuine last entry. 8 sections, ending
    # at 691.485 (already loaded above for the unrelated heading-fragment case), is this
    # chapter's true, unchanged catalog.
    ck("an ordinary chapter's density-cut match is still excluded as a body reoccurrence, "
       "not turned into a spurious extra entry",
       len(s691) == 8 and s691.get("691.485") == "Board of Licensed Dietitians")

    # #349: `_RECOVERED_TAIL_CAP` itself has never fired against real corpus data -- a full
    # offline scan of all 569 committed chapter snapshots (measured 2026-09-10, against
    # `_meta/catalog/ors.yml`'s own chapter list), reconciling with the counts named above,
    # partitions into all three buckets, the zero-count one named rather than left silent:
    #   523 ordinary (the density-cut match is a body reoccurrence, as with 691 above)
    #     8 reach the RECOVERED branch at all (171, 186, 191, 199, 221, 237, 306, 358) --
    #       of those, the 4 named a few lines up (171, 186, 221, 306) go on to survive
    #       parse_toc's own downstream `[`-split and length/case filters; the other 4
    #       (191, 199, 237, 358) recover a repealed-section bracket artifact those filters
    #       correctly drop, so they never reach the catalog either
    #    38 have no "EDITION" token at all, so `parse_toc` returns `[]` before the
    #       recovered/ordinary decision point is ever reached
    #   523 + 8 + 38 = 569.
    # In every one of the 8 that reach the branch, `_catchline_end` stops at
    # `_RECOVERED_ALLCAPS_RE` or `_RECOVERED_NOTE_RE` well under the 2000-char cap -- ZERO
    # reach the cap itself. So the cap is dead on today's corpus, which per #349's own
    # decision tree means a synthetic fixture is the right move: a future change to the cap
    # should be a deliberate edit of an assertion here, not a silent behavior change nothing
    # would catch.
    #
    # Two assertions below, because one alone conflates two different things this parser
    # does to a recovered entry's title. The FIRST fixture reproduces #349's own worked
    # example: a genuine last TOC entry ("999.030") followed by ordinary sentence-case prose
    # carrying neither marker, run out past the 2000-char cap -- the same garbage-suffixed
    # -title failure mode #346's thread measured and rejected for the naive "just include
    # it" fix, now happening on purpose. But its title, like every entry's, still passes
    # through `parse_toc`'s own `rest[:_TITLE_CAP]` truncation below -- so what this
    # fixture's `literal_title == _TITLE_CAP` chars actually pins is that ordinary
    # truncation, not the recovery cap: measured, sweeping `_RECOVERED_TAIL_CAP` over
    # 5000/1000/500/300/200/175 leaves this assertion green throughout, because the
    # `_TITLE_CAP`-char truncation is what the comparison sees regardless of where the
    # recovery cap sits above it. The SECOND assertion below calls `_catchline_end`
    # directly against a markerless tail longer than the cap and pins the literal 2000 --
    # verified sensitive: it goes red the moment `_RECOVERED_TAIL_CAP` moves away from
    # 2000 in either direction.
    literal_title = (
        "Third and last entry title the body of the chapter continues here with "
        "ordinary sentence case prose that carries no capitalised heading and no "
        "marker word of any other kind, running on past what this parser now keeps "
        "for an ordinary title before the boundary this fixture actually means to "
        "test, repeating itself in plain words to reach the exact length this proof "
        "needs without resorting to a marker word "
        + "and repeating some more harmless words to be sure of it, " * 8
    )[:800]
    assert len(literal_title) == 800, "fixture text must be trimmed/padded to exactly " \
        "_TITLE_CAP characters for the truncation assertion below to mean anything"
    filler = (" and it just keeps going in ordinary sentence case well past both the "
              "eight hundred characters this parser keeps for any title and the two "
              "thousand character boundary this fixture means to reach, so the "
              "fallback this proof pins is the cap itself and not the tail's own "
              "natural end, repeating some more harmless words to be sure of it, ") * 20
    raw999 = ("SOME PREAMBLE TEXT 2025 EDITION "
              "999.010 First entry title. "
              "999.020 Second entry title. "
              "999.030 " + literal_title + filler)
    s999 = {s["number"]: s["title"] for s in parse_toc(raw999, "999")}
    ck("a synthetic chapter whose recovered last entry carries neither marker within "
       "2000 chars still gets the ordinary _TITLE_CAP-char title truncation every entry "
       "gets -- this does NOT pin the recovery cap itself (see the next assertion for "
       "that)",
       s999.get("999.030") == literal_title)
    tail999 = "999.030 " + literal_title + filler
    ck("the markerless tail's own boundary, checked directly against `_catchline_end`, is "
       "the recovery cap itself, 2000 chars, and not the tail's length or the title's "
       "_TITLE_CAP-char truncation -- this is the assertion that goes red if "
       "`_RECOVERED_TAIL_CAP` moves",
       _catchline_end(tail999) == _RECOVERED_TAIL_CAP == 2000)

    # #397: a bare section-group heading, and a heading followed by its own parenthetical
    # sub-heading, glued onto the PRECEDING section's title -- measured against origin/main's
    # committed catalog at 135 bare-heading and 359 heading+parenthetical titles (494 total).
    # All four real chapters below are the actual committed `_meta/snapshots/ors-chapter-*
    # .txt`, not synthetic fixtures, per this module's own established practice.
    s1 = secs("1")
    ck("1.860 (bare heading 'COURTS', 6 chars -- under TRAILING_HEADING_RE's 8-char floor, "
       "the exact shape that regex could never catch) is recovered clean",
       s1.get("1.860") == "Reports relating to municipal courts and justice courts")

    s453 = secs("453")
    # THE HEADING+PARENTHETICAL SHAPE: `TRAILING_HEADING_RE`'s `$` anchor can never reach an
    # all-caps heading followed by its own parenthetical sub-heading, because the
    # parenthetical -- not the heading -- is what sits at the true end of the glued string.
    ck("453.185 ('ART AND CRAFT MATERIALS (Generally)' glued on, #397's own worked example) "
       "is recovered clean",
       s453.get("453.185") == "False representation by purchaser prohibited")

    # A THIRD SHAPE FOUND FIXING THE SAME FUNCTION, SAME PARAGRAPH-STRUCTURE MECHANISM,
    # FIXED IN THIS SAME CHANGE (AGENTS.md's "found a defect? fix it" -- not a new issue,
    # not a review finding filed separately): a bare parenthetical SUB-heading with no
    # heading paragraph of its own immediately before it, because it names a later group
    # under a heading already stated earlier in the same chapter. Neither shape #397
    # measured (it counted only heading-led glue), so this is reported separately, not
    # folded into that 494.
    ck("453.135 (bare sub-heading '(Miscellaneous)' with no heading paragraph of its own -- "
       "it names a later group under 'HAZARDOUS SUBSTANCES', stated earlier in the same "
       "chapter) is recovered clean",
       s453.get("453.135") == "Notice required prior to institution of criminal "
       "proceedings")
    ck("453.025 (same bare-sub-heading shape, '(Regulation; Prohibited Acts)') keeps its "
       "own in-catchline xref range intact AND loses only the glued sub-heading",
       s453.get("453.025") == "Certain practices not affected by ORS 453.005 to 453.135")

    # MUST NOT REGRESS: a real trailing acronym that is NOT its own paragraph in the source
    # (it wraps onto the SAME line as the rest of its sentence) must survive untouched, at
    # any length -- the boundary here is the source's own paragraph layout, not a length
    # floor, so this is not "the floor, lowered further" and does not start eating
    # legitimate short trailing words the way that would.
    s279a = secs("279A")
    ck("279A.152's own real trailing acronym ('...recycled PETE', never its own paragraph "
       "in the source) is NOT stripped",
       s279a.get("279A.152") == "Assessment of procurement practices related to recycled "
       "products and materials and recycled PETE")

    # THE INTERACTION #397 FLAGGED BUT DID NOT ASSERT WAS A BUG: a glued heading long enough
    # to push a title past the (then-160-char) cap used to truncate mid-word ("...INJU")
    # instead of being stripped, because the cap ran before the strip. Removing the glued
    # heading first is what fixes this -- a change to WHERE the strip runs relative to the
    # cap, not to the cap's own mechanism (`title[:_TITLE_CAP]`; #415 later changes the
    # VALUE, not this ordering).
    s654 = secs("654")
    ck("654.196's glued heading ('INJURED WORKERS' MEMORIAL SCHOLARSHIP', including the "
       "source's own Unicode right single quote) no longer survives far enough to be cut "
       "mid-word by the cap",
       s654.get("654.196") == "Rules on contents of piping systems; posting notice on "
       "right to be informed of hazardous substances; withholding of information under "
       "certain circumstances")

    # THE #348 TRUNCATION SHAPE MUST STAY UNTOUCHED: a dangling in-catchline cross-reference
    # ("Definitions for ORS 1.010 to") is a different bug (#348, unresolved TOC/body
    # disagreement over where the range's own second number lives), not this one, and this
    # fix must not touch it -- #397's own brief was explicit that mixing the two would make
    # both unreviewable.
    ck("1.194 (the #348 dangling-xref shape, unrelated to this fix) is unchanged",
       s1.get("1.194") == "Definitions for ORS")

    # CODE-REVIEW FOLLOW-UP (F1): three more causes of the SAME glued-heading bug, found
    # measuring this fix's own residual against all 569 committed chapters -- not a new
    # issue, the same one, undercounted.
    #
    # (a) A HEADING PARAGRAPH WITH A DIGIT IN IT: `_HEADING_UNIT_RE` required every
    # character of the isolated paragraph to be a letter (or the small punctuation set
    # above), so a heading that happens to include a digit -- a year ("... UNDER 1891 ACT"),
    # a population threshold ("... CITIES OF 3,000 OR MORE"), or a designation
    # ("2-1-1 SYSTEM", "340B DRUGS") -- fell through untouched, at any length, the same gap
    # `TRAILING_HEADING_RE` already had. Widening the class to admit digits (and letting the
    # first character be one too, for "2-1-1 SYSTEM") does NOT reopen the false-positive risk
    # measured against ch. 688's "SECTION 1. PURPOSE" or ch. 815's "ORS 803.430" -- both
    # contain a period, which stays outside the class -- nor against a bare page number ("94")
    # in ch. 815's own wrapped table, which the added `(?=.*[A-Z])` lookahead excludes by
    # requiring at least one letter in the isolated paragraph.
    s541 = secs("541")
    ck("541.990's glued heading ('WATER COMPANIES ORGANIZED UNDER 1891 ACT', a digit inside "
       "an all-caps heading paragraph) is recovered clean",
       s541.get("541.990") == "Penalties")
    s689 = secs("689")
    ck("689.813's glued heading ('PROHIBITIONS RELATED TO 340B DRUGS', a digit-letter "
       "designation inside an all-caps heading paragraph) is recovered clean",
       s689.get("689.813") == "Exemption from drug labeling requirements")

    # (b) AN ALL-CAPS PARENTHETICAL ON THE HEADING'S OWN PARAGRAPH -- the shape #397's own
    # issue was filed against, but not the shape its fix actually caught: here the heading
    # and its parenthetical sub-heading are ONE paragraph, not two ("FINANCING LOCAL
    # IMPROVEMENTS\n(BANCROFT BONDING ACT)" is a single blank-line-delimited unit), so neither
    # the heading+next-paragraph combination logic below nor `_SUBHEADING_UNIT_RE` (which
    # requires the WHOLE unit to start with `(`) ever saw it. Letting `_HEADING_UNIT_RE`
    # itself match an optional trailing all-caps parenthetical closes this without touching
    # the two-paragraph combination logic at all.
    s223 = secs("223")
    ck("223.161's glued heading+parenthetical, both on ONE paragraph ('FINANCING LOCAL "
       "IMPROVEMENTS (BANCROFT BONDING ACT)'), is recovered clean",
       s223.get("223.161") == "Effect of local improvement districts or urban renewal "
       "districts")
    s343 = secs("343")
    ck("343.534's glued heading+parenthetical, both on ONE paragraph ('APPROPRIATE LEARNING "
       "MEDIA FOR BLIND STUDENTS (BRAILLE)'), is recovered clean",
       s343.get("343.534") == "Allocation of state funds to approved providers")

    # (c) A PARENTHETICAL SUB-HEADING WRAPPED ACROSS A PARAGRAPH BREAK: the source
    # occasionally breaks a parenthetical sub-heading's OWN text across a blank line
    # ("(Educator Professional\n\nDevelopment Program)" -- the source's typesetting, not a
    # snapshot artifact), so `_PARA_SEP_RE` splits it into two units, "(Educator
    # Professional" and "Development Program)", neither of which is a complete, balanced
    # parenthetical -- `_SUBHEADING_UNIT_RE` matches neither half. Merging a unit that opens
    # a paren it never closes with the very next unit (see `_toc_heading_phrases`) restores
    # the single phrase without touching any other unit.
    s329 = secs("329")
    ck("329.820's sub-heading, wrapped across a paragraph break ('(Educator Professional' / "
       "'Development Program)'), is recovered clean",
       s329.get("329.820") == "Evaluation of programs; donations")
    s455 = secs("455")
    ck("455.453's sub-heading, wrapped the same way ('(Specialty Code Inspection and' / "
       "'Building Plan Review)'), is recovered clean",
       s455.get("455.453") == "Additional prohibitions")

    # CODE-REVIEW FOLLOW-UP (judgement call): `_strip_glued_headings`'s own bound used to be
    # a fixed `for _ in range(3)`, unmeasured. Measured against all 569 committed chapters:
    # a chapter can stack MORE than one section-group heading (each with its own bare
    # sub-heading AND its own temporary-provisions note) into the same gap, and a fixed
    # bound of 3 left exactly these two rows only partially stripped, mid-phrase.
    s238 = secs("238")
    ck("238.730 (two stacked section-group headings, each with its own sub-heading and its "
       "own temporary-provisions note, seven strips deep -- more than a fixed bound of 3 "
       "reaches) is recovered clean",
       s238.get("238.730") == "Unfunded Actuarial Liability Resolution Program")
    s526 = secs("526")
    ck("526.905 (the same stacked shape as 238.730) is recovered clean",
       s526.get("526.905") == "Management plans or policies to reduce risk of loss of "
       "forest resources")

    # SPEC: the brief's own three named must-fix rows (none of these were asserted before,
    # though all three were already correct).
    s131 = secs("131")
    ck("131.235 (one of the brief's three named must-fix rows) is correct",
       s131.get("131.235") == "Criminal homicide")
    s164 = secs("164")
    ck("164.388 (one of the brief's three named must-fix rows) is correct",
       s164.get("164.388") == "Preemption")
    s109 = secs("109")
    ck("109.834 (one of the brief's three named must-fix rows) is correct",
       s109.get("109.834") == "Severability clause")

    # #411/#412: a `Note ...` editorial marginalia paragraph -- Title Case, not
    # parenthetical, so it was invisible to `_toc_heading_phrases` before this fix --
    # glues onto the preceding title the same way a heading or sub-heading does, because
    # it is typeset exactly the same way: its OWN blank-line-isolated paragraph (verified
    # directly against the raw source for every row below, not assumed). #411 named the
    # shape where a KNOWN heading phrase sits between the real title and the Note, past
    # what an exact-suffix strip could reach without Note recognition too; #412 named the
    # shape where the Note glues directly with no heading in front of it at all. Both are
    # the same underlying gap in the SAME function and are fixed by the SAME change here
    # -- recognizing a `Note` paragraph as its own furniture unit, parallel to how a
    # heading/sub-heading paragraph already is -- so they are asserted together.
    #
    # Re-measured 2026-09-13 against a fresh re-parse of all 569 committed chapters:
    # #411's claimed 5 rows are exactly right (196.692, 311.701, 454.380, 469.619,
    # 476.290 -- no more, no fewer). #412's claimed 47 undercounts: the true population
    # sharing this defect is 59 -- the issue's list plus 12 more (107.843, 109.990,
    # 163A.110, 195.912, 196.993, 197A.820, 285C.659, 367.850, 411.990, 413.805, 458.740,
    # 569.995) carrying a differently-worded but structurally identical marginalia
    # paragraph ("Note: Definitions in ... apply to ORS chapter N" / "Note: N.NNN
    # contains definitions for ORS chapter N", a recurring chapter-definitions notice,
    # rather than #412's own named shape, a one-off session-law citation after "Note").
    # Every expected title below is the section's OWN printed body catchline (via
    # `ingest_ors._CATCHLINE_END_RE`/`repo_lib.snapshot_slice`, the same ground truth
    # `statute_title_agreement._snapshot_catchline` and `anchor_ok` both check against),
    # not a guess at what the strip should produce.
    s196 = secs("196")
    ck("196.692 (#411: heading 'REMOVAL OF MATERIAL; FILLING (Streamlining)' then a "
       "separate 'Note ...' paragraph, both between the title and the next real "
       "section) is recovered clean",
       s196.get("196.692") == "Rules")
    s311 = secs("311")
    ck("311.701 (#411: heading, then Note, then a SECOND heading -- three stacked units "
       "-- is recovered clean",
       s311.get("311.701") == "Senior Property Tax Deferral Revolving Account; "
       "sources; uses")
    s454 = secs("454")
    ck("454.380 (#411: bare heading 'BIOSOLIDS' then a 'Note ...' paragraph) is "
       "recovered clean",
       s454.get("454.380") == "Limitation on spending for nonconstruction items; "
       "exception")
    s469 = secs("469")
    ck("469.619 (#411: parenthetical sub-heading '(Offshore Wind Energy)' then a "
       "'Note ...' paragraph) is recovered clean",
       s469.get("469.619") == "State Department of Energy to make federal regulations "
       "available")
    s476 = secs("476")
    ck("476.290 (#411's own worked example: heading 'FIRE PREVENTION AND CONTROL ON "
       "CERTAIN LANDS NOT OTHERWISE PROTECTED' then a 'Note ...' paragraph, previously "
       "hidden from view entirely by the 160-char cap before the strip even ran) is "
       "recovered clean",
       s476.get("476.290") == "Billing owner of property for cost of extinguishing "
       "fire; cost limited; collection; action for recovery of cost")

    s172 = secs("172")
    ck("172.130 (#412's own worked example: a bare 'Note ...' with no heading in front "
       "of it at all) is recovered clean",
       s172.get("172.130") == "Executive Officer and employees")
    s743a = secs("743A")
    ck("743A.168 (#412, same bare-Note shape) is recovered clean",
       s743a.get("743A.168") == "Behavioral health treatment; qualified providers; "
       "rules")
    s107 = secs("107")
    ck("107.843 (the 12-row remainder #412 undercounted: a recurring chapter-"
       "definitions notice, 'Note: Definitions in 25.010 and 25.011 apply to ORS "
       "chapter 107', structurally the same bare-Note glue as #412's own examples "
       "despite the different wording) is recovered clean",
       s107.get("107.843") == "Supplemental judgments")
    s401 = secs("401")
    ck("401.123 (two stacked bare 'Note ...' paragraphs back to back, no heading "
       "involved) is recovered clean",
       s401.get("401.123") == "Support for community organizations active in disaster")
    s657b = secs("657B")
    ck("657B.430 (same two-stacked-Note shape as 401.123) is recovered clean",
       s657b.get("657B.430") == "Paid Family and Medical Leave Insurance Fund")
    s285b = secs("285B")
    ck("285B.799 (a bare Note followed by a SECOND, differently-worded bare Note -- "
       "'Note Program evaluation...' then 'Note: 285A.010 contains definitions...') "
       "is recovered clean",
       s285b.get("285B.799") == "Biennial report by Oregon Business Development "
       "Department to legislature")
    s569 = secs("569")
    ck("569.995 (the one row of the 59 where the Note's OWN text lists a run of bare "
       "chapter-own section numbers with no 'ORS' prefix -- '569.010, 569.020, ...' -- "
       "which, uncorrected, are mistaken for new TOC-entry boundaries and truncate the "
       "entry before the strip mechanism ever runs) is recovered clean",
       s569.get("569.995") == "Civil penalties")

    # #412: the OTHER two rows of the 59 needing a second, distinct fix -- a real TOC
    # entry immediately follows the glued Note (no trailing heading paragraph after it to
    # protect the period), so the period this Note phrase's own text ends in was already
    # stripped by `rest`'s early `.strip(" .")` before `_strip_glued_headings` ever ran,
    # and the exact-suffix match silently failed on a one-character mismatch it should
    # never have had to survive in the first place.
    s413 = secs("413")
    ck("413.805 (glued Note ends in a period with a real TOC entry, not another heading, "
       "immediately following it) is recovered clean",
       s413.get("413.805") == "Services for children and youth under K Plan")
    s458 = secs("458")
    ck("458.740 (same immediately-followed-by-a-real-entry shape as 413.805) is "
       "recovered clean",
       s458.get("458.740") == "Project facilitation")

    # #415: the `_TITLE_CAP` cap (see its own docstring above `extract_chapter_title`) was
    # truncating real catchline text, sometimes mid-word. Every expected value below is the
    # section's own full, real printed title (the two named-truncated rows verified against
    # the section's own body catchline in the committed snapshot; 314.057 verified directly
    # against its own TOC entry, since its body catchline is itself a DIFFERENT, unrelated,
    # pre-existing defect in `ingest_ors._CATCHLINE_END_RE` -- that regex's first-period
    # match lands on the abbreviation "P.L." rather than the sentence's real end, so the
    # body-derived ground truth `statute_title_agreement.py` relies on is wrong for this one
    # row too; not fixed here, out of this file, reported separately).
    s659a = secs("659A")
    ck("659A.145 (#415's own worked example: used to cut mid-word, '...allowance for "
       "reas') now carries its full real title",
       s659a.get("659A.145") == "Discrimination against individual with disability in "
       "real property transactions prohibited; advertising discriminatory preference "
       "prohibited; allowance for reasonable modification; assisting discriminatory "
       "practices prohibited")
    s455 = secs("455")
    ck("455.097 (#415's other named mid-word cut, '...construction-related service in') "
       "now carries its full real title",
       s455.get("455.097") == "Electronic access system development and implementation; "
       "uniform form and format for electronic exchange of building program and "
       "construction-related service information; waiver of contrary form and format "
       "requirements; rules")
    s314 = secs("314")
    ck("314.057 (the longest real title measured anywhere in the corpus, 504 characters -- "
       "not a defect, a citation-heavy catchline naming nine federal session laws by name "
       "and public-law number) survives complete, not cut at the old 160-char cap or "
       "anywhere else",
       s314.get("314.057") == "Application of Economic Stimulus Act of 2008 (P.L. "
       "110-185), Heroes Earnings Assistance and Relief Tax Act of 2008 (P.L. 110-245), "
       "Food, Conservation, and Energy Act of 2008 (P.L. 110-246), Housing and Economic "
       "Recovery Act of 2008 (P.L. 110-289), Emergency Economic Stabilization Act of 2008, "
       "Energy Improvement and Extension Act of 2008, Tax Extenders and Alternative "
       "Minimum Tax Relief Act of 2008 (P.L. 110-343) and Fostering Connections to "
       "Success and Increasing Adoptions Act of 2008 (P.L. 110-351)")

    # #415: the identical `[:_TITLE_CAP]` cap on `extract_chapter_title` (CHAPTER titles,
    # not section titles) has the same defect, measured the same way: 5 of 569 chapter
    # titles were cut at exactly 160 characters. Fixed by the same constant, in the same
    # file, same change -- not a separate issue (AGENTS.md: "found while doing something
    # else" is the reason it's cheap, not a reason to defer it).
    raw688 = (SNAPSHOT_DIR / "ors-chapter-688.txt").read_text(encoding="utf-8",
                                                                errors="replace")
    ck("chapter 688's real title (previously cut mid-word at 160 chars, "
       "'...Hemodialysis Technicians; Athletic T') survives complete",
       extract_chapter_title(raw688, "688") == "Therapeutic and Technical Services: "
       "Physical Therapists; Medical Imaging Practitioners and Limited X-Ray Machine "
       "Operators; Hemodialysis Technicians; Athletic Trainers; Respiratory Therapists "
       "and Polysomnographic Technologists")

    # #415: two rows named as a DIFFERENT shape than the cap -- a TOC line-wrap, not
    # truncation. `757.015`'s own in-catchline cross-reference wraps a subsection cite,
    # "ORS 757.105 (1) and 757.495", between the first number and the join word -- a shape
    # `XREF_RE` (built for #286's plain "NNN.NNN and NNN.NNN" and "NNN.NNN to NNN.NNN"
    # chains) never covered, so the bare "757.495" was mistaken for a new TOC-entry
    # boundary and the real continuation was cut. This is NOT #348 (1.194's own dangling
    # xref, deliberately left alone below): #348's cause is a citation to a chapter number
    # under 3 digits, which `XREF_RE`'s own `\d{3}` can never match at all; 757's citation
    # is 3-digit chapters throughout and fails only because of the injected "(1)".
    s757 = secs("757")
    ck("757.015 (in-catchline xref 'ORS 757.105 (1) and 757.495' -- a subsection cite "
       "between the number and the join word, not covered by the plain #286 xref chain) "
       "keeps its full continuation",
       s757.get("757.015") == "“Affiliated interest” defined for ORS 757.105 "
       "(1) and 757.495")

    # #415: `279C.337`'s own committed TOC region already carries a stray SPACE right
    # after the "/" in "construction manager/ general contractor" (verified byte-for-byte
    # against the committed snapshot: the character there is a literal space, not a
    # newline `ws_only` collapsed into one), which none of the section's own three
    # committed body occurrences carry -- unlike 315.123/470.540's mid-word HYPHEN, a
    # genuine SOURCE artifact `anchor_ok`'s own docstring already documents as deliberately
    # NOT corrected, this is the opposite case: an artifact of THIS extraction, not one the
    # source itself prints in the body. Measured: this is the only row in the corpus with a
    # "/ " (slash then space) anywhere in its title.
    s279c = secs("279C")
    ck("279C.337 ('manager/general', not 'manager/ general') has no stray space after "
       "the slash",
       s279c.get("279C.337") == "Procurement of construction manager/general contractor "
       "services")

    return ck.report("catalog-ors selftest")


def main():
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    # ORS prints a lettered chapter uppercase (86A, 657B) and the catalog follows suit;
    # accept either case from the caller so "86a" doesn't create a duplicate entry.
    chapters = [c.upper() for c in sys.argv[1:]]
    if not chapters:
        print("usage: catalog_ors.py <chapter> [<chapter> ...]")
        sys.exit(2)
    cat = yaml.safe_load(CATALOG.read_text())
    by_num = {c["chapter"]: c for c in cat["chapters"]}

    def save():
        cat["chapters"].sort(key=lambda c: c["chapter"])
        CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))

    missing = []
    for n, ch in enumerate(chapters, 1):
        # Not every chapter number is a live page: repealed chapters are simply absent from
        # the site. A bulk run must survive that -- previously one 404 aborted the loop and,
        # because the catalog was only written at the end, discarded every chapter before it.
        try:
            raw = fetch_chapter(ch)
        except HTTPError as e:
            if e.code == 404:
                missing.append(ch)
                print(f"chapter {ch}: no page at {chapter_url(ch)} (HTTP 404) -- skipped")
                continue
            raise
        secs = parse_toc(raw, ch)
        # Prefer the curated title, then the one printed in the source, then a bare label.
        title = CHAPTER_TITLES.get(ch) or extract_chapter_title(raw, ch) or f"Chapter {ch}"
        existing = by_num.get(ch)
        if existing:
            have = {s["number"]: s for s in existing["sections"]}
            for s in secs:
                if s["number"] not in have:
                    existing["sections"].append(s)
            existing["sections"].sort(key=lambda s: s["number"])
            if existing.get("title", "").startswith("Chapter ") and not title.startswith("Chapter "):
                existing["title"] = title  # upgrade a bare label if we now have a real one
        else:
            entry = {"chapter": ch, "title": title, "url": chapter_url(ch), "sections": secs}
            cat["chapters"].append(entry)
            by_num[ch] = entry
        print(f"chapter {ch} ({title}): {len(secs)} sections found")
        if n % 10 == 0:
            save()  # checkpoint, so an interrupted bulk run keeps what it already parsed

    save()
    if missing:
        print(f"\n{len(missing)} chapter(s) have no page on the site: {' '.join(missing)}")


if __name__ == "__main__":
    main()
