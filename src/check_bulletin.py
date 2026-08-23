#!/usr/bin/env python3
"""Oregon Bulletin pilot (#78): read ONE document a month instead of hashing 36k rules.

The Oregon Bulletin is the official monthly digest of rule filings ("first business
day monthly" — _meta/sources/oar.yml's upstream_signal). This script fetches the
CURRENT bulletin and emits `_meta/bulletin-worklist.yml`: every OAR rule number the
bulletin's permanent/temporary/minor-correction filings adopt, amend, repeal,
renumber or suspend — the re-ingest worklist that issue #78 calls "the approach
worth building".

WHAT A WORKLIST ROW SAYS ABOUT THIS CORPUS IS THREE THINGS, NOT TWO (#227, ADR 0006).
`in_corpus: true|false` collapsed a rule MISSING FROM A CHAPTER THIS CORPUS MIRRORS
into a rule in a chapter that was never in the selection. The first is a coverage gap
and the second is a boundary, and 121 rows of the August 2026 bulletin stood in the
first while being written as the second — 74 adoptions, 43 AMENDMENTS (so the rules
existed, and their text changed, and this mirror never had them), 1 repeal and 3
suspensions. The field is `corpus_state` now, with the three values CORPUS_STATES
names; a renamed field rather than a widened one, because every value of a two-state
field is truthy and a consumer reading the new spelling off the old name would find
every row held.

A RENUMBER SAYS WHERE THE TEXT WENT, OR SAYS IT COULD NOT (#233). `RENUMBER: X to Y`
used to be read as two rules that were both renumbered, so Y — where the text went —
was reported as a rule this corpus was told had changed, and the move X made had no
target for anyone to follow. `renumbered_to` carries the destination or the literal
`unknown`, which is deliberately not spellable as an action: renumbered, renumbered
with an unknown target and repealed are three states and only the last means the text
is gone.

AND THE FILE SAYS HOW MUCH OF THE MONTH IT IS. `filings` and `unread_filings` are what
keep a month whose filings could not be fetched from reading as a month in which
little was filed — the substitution ADR 0006 exists to prevent, which the worklist
itself had no field to record.

How the Bulletin is actually published (investigated 2026-08-02, all discovered from
the SoS pages themselves, not guessed):

  1. https://sos.oregon.gov/archives/Pages/default.aspx links "Oregon Bulletin" to
     the OARD app: https://secure.sos.state.or.us/oard/displayBulletins.action —
     an accordion of per-month links `displayBulletin.action?bulltnRsn=<n>`.
  2. A month's bulletin is NOT one PDF. It is an HTML page with two tables:
       "Notices of Proposed Rulemaking"                    (proposals — no rule text
                                                            changed yet; ignored here)
       "Permanent, Temporary, and Statutory Minor
        Correction Filings"                                (the operative changes:
                                                            chapter, agency, filing
                                                            AON, type, caption, and a
                                                            per-filing "View PDF")
  3. Each filing's "View PDF" (`viewReceiptTRIM.action?ptId=<id>`) 302-redirects to
     `https://records.sos.state.or.us/ORSOSCMSearch/Search/RecordViewer.aspx?uri=<id>`
     — a pdf.js viewer page with the filing's PDF EMBEDDED AS BASE64 (`JVBERi…`).
     The `uri` equals the `ptId`, so this script requests the viewer directly.
  4. Inside each filing PDF (pdftotext -layout), the operative lines are anchored at
     column 0: `AMEND: 407-007-0210`, `ADOPT: …`, `REPEAL: …`, also compounds like
     `AMEND & RENUMBER:` and `Temporary` prefixes. Rule numbers ALSO appear in prose
     (need/justification sections cite other agencies' rules), so only the
     action-anchored lines are parsed — a bare NNN-NNN-NNNN elsewhere is a citation,
     not a change.

So "reading one document a month" is really ~1 index page + N filing PDFs (July 2026:
190 filings). Still O(one bulletin), not O(36k rules).

Usage:
  python3 src/check_bulletin.py               # current (latest listed) bulletin
  python3 src/check_bulletin.py --rsn 1741    # a specific bulltnRsn
  python3 src/check_bulletin.py --list        # list available bulletins and exit
  python3 src/check_bulletin.py --check       # CI: audit the committed worklist (offline)
  python3 src/check_bulletin.py --selftest    # CI: prove every rule here can fail

Needs `pdftotext` (poppler-utils) on PATH for the fetching modes. Failures on
individual filings are reported and tolerated (same philosophy as
corpus-detect-changes >= v1.22.0); a systemic failure — more than `SYSTEMIC_SHARE`
of the month's filings, see the constant — exits 1 and writes nothing, because the
rows such a run holds are an unknown fraction of the month.

EVERY RULE THIS MODULE APPLIES IS NAMED, AND NAMING THEM IS THE POINT (#226). Before
this, the module skipped, warned and refused in nine places and none of them had ever
been watched fail — a refusal nobody has seen fire is not known to work, it is only
known to be quiet. Each is now a `Problem` carrying the RULE that produced it, so
`--selftest` asserts on the rule rather than pattern-matching prose (the way a proof
starts passing for the wrong reason: catalog_agencies.Failure, link_enabling_authority
.Problem, derive_relation_kinds.Problem, same lesson).

NEITHER GATE TOUCHES THE NETWORK, which is the discipline every other gate in
.github/workflows/validate-frontmatter.yml states for itself. Fetching stays behind
the modes that already did it. `--check` reads the committed worklist, the committed
OAR catalog, the committed source manifest and the mirrored rules, and nothing else;
`--selftest` reads none of them, because a proof that reads committed data is one that
starts passing for whatever that data happens to say.

WHAT `--check` CAN AND CANNOT SAY. The worklist is GENERATED, so this is a generated
file asserted against committed data — the same shape as `review_queue.py --check`,
and the same remedy line ("run: …"). It can say the worklist contradicts what this
corpus holds, contradicts itself, or is older than the OAR group's own last look
upstream. It cannot say the Bulletin was read correctly; only re-reading it can, and
re-reading needs the network. So a clean `--check` means the committed worklist is
consistent and attributable, never that the month was quiet.

THE BULLETIN IS AUTHORITY ABOUT WHAT WAS FILED (ADR 0006), and this file does not
arbitrate anything against `corpus-detect-changes`'s observation of what is served.
Nothing here writes a legal status onto any document; the worklist stays what it has
always been, a list of rule numbers and the action a filing took against them.
"""
from __future__ import annotations

import argparse
import base64
import collections
import html
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml

from repo_lib import REPO_ROOT

OARD = "https://secure.sos.state.or.us/oard"
VIEWER = "https://records.sos.state.or.us/ORSOSCMSearch/Search/RecordViewer.aspx?uri={}"
UA = {"User-Agent": "executive-regulatory-frameworks bulletin check (github.com/OregonAI)"}
WORKLIST = REPO_ROOT / "_meta" / "bulletin-worklist.yml"
CATALOG = REPO_ROOT / "_meta" / "catalog" / "oar.yml"
SOURCE_GROUP = REPO_ROOT / "_meta" / "sources" / "oar.yml"
RULES_DIR = REPO_ROOT / "rules"
REGENERATE = "python3 src/check_bulletin.py"

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
MONTH_LINK_RE = re.compile(
    r"displayBulletin\.action[^?']*\?bulltnRsn=(\d+)'[^>]*>([A-Z][a-z]+)&nbsp;&nbsp;(\d{4})")
FILING_TABLE_MARK = "Permanent, Temporary, and Statutory Minor"
ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
PTID_RE = re.compile(r"viewReceiptTRIM\.action[^?']*\?ptId=(\d+)")
B64_PDF_RE = re.compile(r"(JVBERi[0-9A-Za-z+/=]{100,})")
# THE ACTIONS A FILING CAN TAKE, WRITTEN ONCE. This is both the vocabulary a worklist
# row may carry and the alternation the reader recognises at the head of a filing line,
# and it used to be written twice — the verbs inside ACTION_LINE_RE and the list a
# consumer branches on. Two spellings of one fact is the drift this repository keeps
# finding (#175's `das_agency_number`, ADR 0003's `manual: true`), and here it would be
# silent in the direction that matters: a verb added to the regex and not to the
# vocabulary produces worklist rows nothing has a case for.
ACTIONS = ("adopt", "amend", "renumber", "repeal", "suspend")
# WHAT THIS CORPUS KNOWS ABOUT A RULE THE BULLETIN NAMES, and it is three things, not
# two (ADR 0006). `in_corpus: true|false` collapsed the last two: a rule absent from a
# chapter this corpus MIRRORS is a coverage gap, and a rule in a chapter that was never
# in the selection is a boundary. 121 rows of the August 2026 worklist stood in the
# first and were written as the second — 74 adopts, 43 AMENDMENTS (rules that existed
# and changed), 1 repeal, 3 suspensions — so the collision this state exists to prevent
# had already happened 121 times in one month and nothing could see it. Written once,
# for the reason ACTIONS is: the writer's mapping and the checker's vocabulary are the
# same list, and a state one end can produce and the other has no case for is drift.
CORPUS_STATES = ("held", "missing_from_mirrored_chapter", "chapter_not_mirrored")
# What is at stake in each, said where the rule that reports a disagreement can quote it,
# so the finding names the harm rather than only the mismatch.
_STATE_HARM = {
    "held": "rules/ serves this rule, so a filing that changed its text leaves this "
            "corpus publishing superseded text under provenance while the row sits "
            "outside the re-ingest worklist — the failure the worklist exists to "
            "prevent, and the silent direction",
    "missing_from_mirrored_chapter":
        "this corpus mirrors the chapter and holds no document for the rule, which is a "
        "COVERAGE GAP recorded as something else — and if the filing amended it, the "
        "rule existed and changed while this mirror never had it",
    "chapter_not_mirrored":
        "the chapter is outside this corpus's selection, so the row points a consumer "
        "at a rule nothing here ever undertook to hold",
}
_VERBS = "|".join(a.upper() for a in ACTIONS)
# Line-anchored action headers inside a filing PDF's text. Compounds ("AMEND &
# RENUMBER") report each verb for the numbers on the line.
ACTION_LINE_RE = re.compile(
    rf"^\s*((?:{_VERBS})(?:\s*&\s*(?:{_VERBS}))*)\s*:\s*(.*)$", re.M)
RULE_NO_RE = re.compile(r"\b(\d{3}-\d{3}-\d{4})\b")
# `RENUMBER: 918-674-0900 to 918-674-0910` — the source, and WHERE THE TEXT WENT. The
# reader used to pair every number on the line with every verb, so the destination was
# filed as a rule that had itself been renumbered (#233) and the move had no target at
# all. One line can carry several pairs, and a chain (`A to B, B to C`) makes B both.
RENUMBER_PAIR_RE = re.compile(
    r"\b(\d{3}-\d{3}-\d{4})\s+to\s+(\d{3}-\d{3}-\d{4})\b", re.I)
# What a renumber records when the filing line does not say where the text went. NOT a
# member of ACTIONS and deliberately not spellable as one: it is the value of the target
# field, so no consumer branching on `action` can arrive at it, and no row can read as a
# repeal because its destination is unknown.
UNKNOWN_TARGET = "unknown"

# The share of a month's filings that may be unreadable before the run is called a
# failure rather than noise. Individual filings fail (a records-app hiccup, a PDF with
# no text layer); a fifth of them failing is an outage or a format change.
SYSTEMIC_SHARE = 0.20

# What the worklist states about itself, and the shape each field is in. All three are
# required TOGETHER: the pair (which bulletin, when it was read) is what makes a stale
# worklist visible without re-fetching, and any one of them alone cannot.
BULLETIN_RE = re.compile(r"^([A-Z][a-z]+)\s+(\d{4})\s+\(bulltnRsn=(\d+)\)$")
URL_RSN_RE = re.compile(r"[?&]bulltnRsn=(\d+)")
RETRIEVED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# The RecordViewer link out of a filing problem's detail, so `unread_filings` carries the
# page a human would open rather than only the filing's name.
_UNREAD_PTID_RE = re.compile(r"RecordViewer\.aspx\?uri=(\d+)")

# One thing wrong, and which RULE says so: the rule name, the thing it is about, and
# what is wrong with it. A type rather than a formatted string, for the reason the
# sibling modules give — `--selftest` asserts on the rule that fired, so a proof cannot
# start passing because some other rule happened to produce similar prose.
Problem = collections.namedtuple("Problem", "rule subject detail")

# One thing a filing line says was done to one rule, and — for a renumber — where the
# text went. `target` is None for every other verb, because a repeal or an amendment has
# no destination and a field that was optional in both directions could not tell a
# renumber that lost its target from one that never had a place for it.
Action = collections.namedtuple("Action", "number verb target")

# What one filing's text yielded: the actions it names and every rule that fired reading
# it. A bare action list could not say whether it is short because the filing named
# little or because a continuation line could not be recovered — the same substitution
# `Reading` exists to prevent, one level down.
Parse = collections.namedtuple("Parse", "actions problems")

# One month's reading: the worklist rows it produced, and every rule that fired while
# producing them. The two travel together because a row list on its own cannot say
# whether it is short because the month was quiet or because a fifth of the filings
# could not be read — which is the substitution this module exists to prevent.
Reading = collections.namedtuple("Reading", "rows problems")

# One row of a bulletin's operative-filings table: the six cells it prints and the id
# of the PDF behind its "View PDF" link. A type rather than a seven-tuple because three
# of the seven are carried only so a problem can name the filing a human has to open,
# and a positional unpacking that lists them to ignore them is a reader that has to be
# counted rather than read.
Filing = collections.namedtuple(
    "Filing", "chapter agency aon filed kind caption pt_id")

# A month's operative-filings table: the filings it yielded and every row that could not
# be made into one. The second half used to be nothing at all — a `<tr>` carrying cells
# but no "View PDF" link was dropped where nobody could see it (#233) — and a table
# reported as N filings when it printed N+1 rows is a month short by a filing that reads
# exactly like a month that had one fewer.
Table = collections.namedtuple("Table", "rows problems")

# What this corpus holds, and what it claims to mirror — the two facts a rule's corpus
# state is decided from, TRAVELLING TOGETHER. They are two different reads of `rules/`
# (the documents, and the chapter directories) and separating them is how the third
# state gets decided from one of them alone: the correction to #227 was made by a query
# that built the mirrored-chapter set with a pattern matching nothing, so every rule fell
# into "chapter not mirrored" and the resulting zero was reported as a finding. A pair
# that arrives together can be checked against itself, and `coverage_gaps` does.
Coverage = collections.namedtuple("Coverage", "held chapters")


class Refusal(Exception):
    """The reader stopping rather than reporting a number it does not believe.

    Three situations refuse: the bulletin index yielding no bulletins, a `--rsn` the
    index does not list, and a bulletin page with no operative-filings table. All three
    mean the pages moved under a parser that was written against them by hand, and in
    all three the alternative to refusing is a confident zero — a month with no filings
    is a thing that happens, so a parse failure that produced one would be indis-
    tinguishable from a quiet month. It carries its Problem so `--selftest` can assert
    on the rule rather than on the message.

    AN `Exception`, NOT A `SystemExit`. It is caught for its payload rather than
    thrown to end the process, and a `BaseException` carrying a payload slips straight
    through every `except Exception` in this file with nothing saying so. `main()`
    turns it into the exit code, in one place, where the other exit codes are."""

    def __init__(self, problem: Problem):
        self.problem = problem
        super().__init__(f"ERROR [{problem.rule}] {problem.subject}: {problem.detail}")


def fetch(url: str, tries: int = 3) -> bytes:
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=90) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 — reported, retried, then surfaced
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def parse_bulletin_index(page: str) -> list:
    """(year, month number, month name, bulltnRsn) for every bulletin the index lists.

    REFUSES ON AN EMPTY RESULT rather than returning one. Discovery is a hand-written
    pattern against a page nobody here controls, so "no bulletins" is what a layout
    change looks like as well as what an empty index would look like, and only one of
    those has ever happened."""
    out = []
    for rsn, month, year in MONTH_LINK_RE.findall(page):
        if month in MONTHS:
            out.append((int(year), MONTHS.index(month) + 1, month, int(rsn)))
    if not out:
        raise Refusal(Problem(
            "index-layout", "displayBulletins.action",
            "no bulletin links found on the index page — the layout changed under a "
            "pattern written against it by hand; re-investigate before parsing, "
            "because the alternative to refusing is reporting a month with no filings"))
    return sorted(out)


def pick_bulletin(bulletins, rsn=None):
    """The bulletin to read: the one named, or the latest the index lists."""
    if rsn is None:
        return bulletins[-1]
    pick = next((b for b in bulletins if b[3] == rsn), None)
    if pick is None:
        raise Refusal(Problem(
            "bulletin-not-listed", f"bulltnRsn={rsn}",
            "the index does not list this bulletin — check --list; reading it anyway "
            "would attribute a worklist to a bulletin nobody can find again"))
    return pick


def filing_rows(bulletin_html: str) -> Table:
    """The operative filings, and the rows that could not be made into one.

    Only the operative table. The bulletin's other table is Notices of Proposed
    Rulemaking, where no rule text has changed yet, and a reader that took both would
    report proposals as filings.

    A ROW THAT CANNOT BE READ IS RECORDED, NEVER DROPPED (ADR 0006, #233). Measured
    against August 2026 (bulltnRsn 1761) nothing is dropped today — 160 `<tr>` tags, 159
    filings, one header — so this is latent rather than occurring, and latent is exactly
    when a silent drop is cheapest to fix and most expensive to notice.

    AND A TABLE THAT YIELDS NOTHING IS A REFUSAL. `filing-table` catches the table going
    missing; this catches the rows inside it changing shape, which leaves the mark in
    place and the count at zero — the same confident zero as a quiet month."""
    idx = bulletin_html.find(FILING_TABLE_MARK)
    if idx < 0:
        raise Refusal(Problem(
            "filing-table", "displayBulletin.action",
            "the bulletin page has no operative-filings table — the format changed; "
            "re-investigate before parsing, because a bulletin parsed without its "
            "filings table yields zero filings and says nothing about why"))
    section = bulletin_html[idx:]
    rows, problems = [], []
    for row in ROW_RE.findall(section):
        if "<td" not in row:
            continue          # the header row, which prints `<th>` and no filing
        cells = [html.unescape(re.sub(r"<[^>]+>", " ", c)).strip()
                 for c in CELL_RE.findall(row)]
        m = PTID_RE.search(row)
        if m and len(cells) >= 6:
            rows.append(Filing(*[re.sub(r"\s+", " ", c) for c in cells[:6]],
                               m.group(1)))
        else:
            problems.append(Problem(
                "filing-row-unreadable", (cells[2] if len(cells) > 2 else repr(row[:60])),
                f"is a row of the operative table with {len(cells)} cell(s) and "
                f"{'no' if not m else 'a'} filing link, so no filing could be made of "
                "it. The rules it acts on are absent from this worklist for a reason "
                "that is not 'nothing happened'"))
    if not rows:
        raise Refusal(Problem(
            "filing-table-empty", "displayBulletin.action",
            f"the operative-filings table yielded no filings from {len(problems)} "
            "unreadable row(s) — the row layout changed under a parser written against "
            "it by hand. Zero filings is also what a quiet month looks like, and the "
            "reader refuses rather than writing a worklist that cannot tell them apart"))
    return Table(rows, problems)


def corpus_state(number: str, coverage: Coverage) -> str:
    """Which of the three things this corpus knows about a rule the Bulletin names.

    Held is a document on disk. The other two are both "not held" and they are NOT the
    same fact: `missing_from_mirrored_chapter` is a rule absent from a chapter this
    corpus claims to mirror — a gap — and `chapter_not_mirrored` is a rule outside the
    selection, which is a boundary and not a fault."""
    if number in coverage.held:
        return "held"
    if number.split("-")[0] in coverage.chapters:
        return "missing_from_mirrored_chapter"
    return "chapter_not_mirrored"


def coverage_gaps(coverage: Coverage) -> set:
    """Chapters holding a mirrored rule that the mirrored-chapter set does not name.

    THE ONE CHECK THAT WOULD HAVE CAUGHT THE MEASUREMENT ERROR IN #227. The two halves
    of a `Coverage` are independent reads of `rules/` — the documents and the chapter
    directories — so a listing or a pattern that matched nothing shows up here as held
    rules whose chapters are unaccounted for, and an EMPTY chapter set against a
    non-empty corpus is the loudest case rather than the quietest. Deriving the chapters
    from the held rules instead would make this vacuous: it would agree by construction,
    which is exactly how a query that matched nothing returned a clean answer."""
    return {n.split("-")[0] for n in coverage.held} - set(coverage.chapters)


def _action_lines(text: str, subject: str, problems: list):
    """(verbs, rule-number text) per action-anchored line, wrapped lines rejoined.

    A line ending in a comma has promised more numbers. The continuation is the next
    line, unless that line is blank, opens a new action, or names no rule number — in
    each of which the numbers the comma promised are NOT THERE and cannot be recovered,
    which is a Problem and never a silent short read."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = ACTION_LINE_RE.match(lines[i])
        i += 1
        if not m:
            continue
        verbs, rest = m.group(1), m.group(2).rstrip()
        while rest.endswith(","):
            nxt = lines[i] if i < len(lines) else None
            if (nxt is None or not nxt.strip() or ACTION_LINE_RE.match(nxt)
                    or not RULE_NO_RE.search(nxt)):
                problems.append(Problem(
                    "action-line-truncated", subject,
                    f"an action line ends `{rest[-40:].strip()}` and what follows it "
                    "continues no list of rule numbers, so the rules the comma promised "
                    "cannot be recovered. They are absent from this worklist for a "
                    "reason that is not 'nothing happened to them'"))
                break
            rest = (rest + " " + nxt.strip()).rstrip()
            i += 1
        yield verbs, rest


def actions_in(text: str, subject: str = "filing") -> Parse:
    """Every action a filing's action-anchored lines take, and what could not be read.

    A bare NNN-NNN-NNNN anywhere else in the filing is a CITATION — the need and
    justification sections cite other agencies' rules constantly — and taking one as a
    change would report a rule as amended on the strength of somebody mentioning it.

    A RENUMBER LINE NAMES TWO KINDS OF NUMBER and they are not interchangeable: the rule
    that was renumbered, and where its text went. Only the first is a rule something was
    filed against. Destinations are dropped from EVERY verb on the line, which is what
    stops `AMEND & RENUMBER: X to Y` reporting Y as amended as well (#233).

    `to` is read as a move ONLY on a line that renumbers. On any other verb it is prose,
    and a pair rule applied there would silently swallow the second number of a range.

    A FILING LINE IS NOT ALWAYS A LINE. A filing that lists more rule numbers than fit
    wraps them, and this reader was line-anchored (#233) — everything after the trailing
    comma was lost, and the rules on the second line were absent from the worklist for a
    reason indistinguishable from "nothing happened to them". A wrapped line is followed
    while it keeps promising more; when the promise cannot be kept, that is RECORDED and
    not tolerated silently."""
    actions, problems = [], []
    for verbs, rest in _action_lines(text, subject, problems):
        verb_list = [v.lower() for v in re.split(r"\s*&\s*", verbs)]
        pairs = RENUMBER_PAIR_RE.findall(rest) if "renumber" in verb_list else []
        target_of = dict(pairs)
        # A number that is a destination AND a source on the same line is a chain
        # (`A to B, B to C`): it stays, because something WAS filed against it.
        destinations = {d for _, d in pairs} - set(target_of)
        seen = set()
        for num in RULE_NO_RE.findall(rest):
            if num in destinations or num in seen:
                continue
            seen.add(num)
            for verb in verb_list:
                actions.append(Action(
                    num, verb,
                    target_of.get(num, UNKNOWN_TARGET) if verb == "renumber" else None))
    return Parse(actions, problems)


def read_bulletin(table, read_filing, coverage, progress=None) -> Reading:
    """Read every filing in a month and return its worklist rows and its problems.

    `read_filing` is passed in and never defaulted to the fetching one: every proof
    below runs on synthetic filings, and a default that reached the network would be a
    proof that starts fetching the day someone forgets an argument.

    A FILING THAT COULD NOT BE READ IS RECORDED, NEVER DROPPED (ADR 0006). It is also
    not the same event as a filing that read fine and named no rules — the first is this
    module failing, the second is a filing a human has to look at — so they are two
    rules and not one count."""
    # THE TABLE'S OWN LOSSES COUNT AS THIS MONTH'S LOSSES. A `<tr>` that could not be
    # made into a filing is a filing never attempted, so it belongs in the numerator and
    # the denominator alike — counting only the fetch failures would let a layout change
    # that mangled a third of the rows read as a healthy month.
    rows = table.rows
    problems = list(table.problems)
    seen, out, unreadable = {}, [], len(table.problems)
    total = len(rows) + len(table.problems)
    for i, filing in enumerate(rows, 1):
        subject = filing.aon or f"ptId={filing.pt_id}"
        try:
            text = read_filing(filing.pt_id)
        except Exception as e:  # noqa: BLE001 — recorded as a rule that fired
            unreadable += 1
            problems.append(Problem(
                "filing-unreadable", subject,
                f"could not be fetched or parsed ({e}) — the rules it acts on are "
                f"absent from this worklist for a reason that is not 'nothing "
                f"happened': {VIEWER.format(filing.pt_id)}"))
            continue
        parse = actions_in(text, subject)
        problems.extend(parse.problems)
        parsed = parse.actions
        for act in parsed:
            row = seen.get((act.number, act.verb))
            if row is not None:
                # THE SAME ACTION FILED TWICE IS ONE ROW — except that a renumber
                # carries a second fact, and two filings can name different destinations
                # for one rule. Keyed on (number, action) alone the later reading is
                # simply dropped, so the destination that survives is whichever filing
                # the month's table happened to list first: one fact written twice, the
                # spellings disagreeing, and nothing gating the agreement.
                if act.verb == "renumber" and act.target != row["renumbered_to"]:
                    if row["renumbered_to"] == UNKNOWN_TARGET:
                        row["renumbered_to"] = act.target   # a filing that said, over one that did not
                    elif act.target != UNKNOWN_TARGET:
                        problems.append(Problem(
                            "renumber-destination-conflict", act.number,
                            f"is renumbered to {row['renumbered_to']} by one of this "
                            f"month's filings and to {act.target} by another. Both "
                            "cannot be where the text went; the worklist keeps the "
                            f"first and this is the record that it did — check "
                            f"{subject} by hand: {VIEWER.format(filing.pt_id)}"))
                continue
            row = {"number": act.number, "action": act.verb,
                   "corpus_state": corpus_state(act.number, coverage)}
            if act.verb == "renumber":
                row["renumbered_to"] = act.target
            seen[(act.number, act.verb)] = row
            out.append(row)
        # `parsed`, not seen-set growth: a filing whose every action duplicates an
        # earlier filing's (same rule corrected twice in a month) parsed fine.
        if not parsed:
            problems.append(Problem(
                "filing-no-actions", subject,
                f"({filing.kind}, ch. {filing.chapter}) no action-anchored rule "
                f"lines parsed — check the filing by hand: "
                f"{VIEWER.format(filing.pt_id)}"))
        if progress:
            progress(i, len(rows))
    if total and unreadable / total > SYSTEMIC_SHARE:
        problems.append(Problem(
            "filing-systemic", f"{unreadable}/{total} filings",
            "more than a fifth of the month's filings could not be read — an outage or "
            "a format change, not noise; the worklist this run would write is missing "
            "an unknown share of the month"))
    out.sort(key=lambda r: (r["number"], r["action"]))
    return Reading(out, problems)


def month_is_whole(reading: Reading) -> bool:
    """Whether this reading may be written over the last worklist that was whole.

    THE WRITER'S DECISION, IN A FUNCTION, so that a proof can watch it say no. Left
    inline in the fetching path it would be the one branch here nothing could reach
    without the network — and the branch matters more than most: the rows a systemic
    run holds are an unknown fraction of the month, and a short worklist is indis-
    tinguishable from a quiet one, so writing it would leave `--check` auditing the
    damage and printing a clean census over it."""
    return not any(p.rule == "filing-systemic" for p in reading.problems)


def _quoted(value: str) -> str:
    """A YAML double-quoted scalar. An unread filing is recorded by its AON as the
    bulletin printed it, and a colon in one would end the key and take the record of the
    filing down with it — the one line in this file whose whole job is to survive."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_worklist(month, year, rsn, url, retrieved, rows, filings, unread) -> str:
    """The worklist file's bytes. One writer, so `--check` audits what this emits.

    IT SAYS HOW MUCH OF THE MONTH IT READ. Without that a filing that could not be
    fetched left its rules simply ABSENT, and absent is what a quiet month looks like
    too (ADR 0006, #233) — so a consumer could not tell a rule nothing was filed against
    from a rule whose filing this reader failed to open. `filings` is every row of the
    operative table, read or not; `unread_filings` NAMES the ones whose rules are
    therefore unknown, with the link a human would follow to find out."""
    lines = [
        "# Generated by src/check_bulletin.py — the monthly OAR re-ingest worklist (#78).",
        "# corpus_state: held                          — this corpus holds the rule; if the",
        "#   filing changed its text it is a re-ingest candidate.",
        "# corpus_state: missing_from_mirrored_chapter — this corpus mirrors the chapter and",
        "#   does not hold the rule. A COVERAGE GAP, not a boundary.",
        "# corpus_state: chapter_not_mirrored          — the chapter is outside this corpus's",
        "#   selection. Not a fault.",
        f"bulletin: {month} {year} (bulltnRsn={rsn})",
        f"bulletin_url: {url}",
        f"retrieved: '{retrieved}'",
        f"filings: {filings}",
    ]
    if unread:
        lines.append("unread_filings:")
        for problem in unread:
            link = _UNREAD_PTID_RE.search(problem.detail)
            # QUOTED: the subject is a filing's AON as the bulletin printed it, and a
            # colon in one would end the key and take the record of an unread filing
            # down with it — the one line in this file whose job is to survive.
            lines.append(f"- filing: {_quoted(problem.subject)}")
            lines.append(
                f"  url: {_quoted(VIEWER.format(link.group(1)) if link else '')}")
    else:
        lines.append("unread_filings: []")
    lines.append("rules:")
    for r in rows:
        lines.append(f"- number: {r['number']}")
        lines.append(f"  action: {r['action']}")
        lines.append(f"  corpus_state: {r['corpus_state']}")
        if "renumbered_to" in r:
            lines.append(f"  renumbered_to: {r['renumbered_to']}")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------ audit


def bulletin_date(stated: str):
    """The earliest date the bulletin the worklist names can have been published.

    The Bulletin appears on the first BUSINESS day of the month it is named for, so the
    first of that month is the earliest it can exist. The earliest is the right end to
    take: this date is compared against a last-looked-upstream date to decide whether
    the reading is behind, and taking the later end would let a reading be called
    current on days it demonstrably was not."""
    m = BULLETIN_RE.match(str(stated).strip())
    if not m or m.group(1) not in MONTHS:
        return None
    return date(int(m.group(2)), MONTHS.index(m.group(1)) + 1, 1)


def months_skipped(bulletin_month, last_checked) -> int:
    """Whole months between the last look upstream and the bulletin this worklist read.

    The Oregon Bulletin is MONTHLY (`_meta/sources/oar.yml`'s upstream_signal: "first
    business day monthly"), so the month after a look upstream is the month that should
    have been read next. Two apart means one bulletin was never opened — and a worklist
    that skipped one is not stale by any measure the file itself carries: it names the
    newest bulletin, its retrieved date is today's, and every row in it is correct."""
    return max(0, (bulletin_month.year - last_checked.year) * 12
               + bulletin_month.month - last_checked.month - 1)


def audit(doc, coverage, catalogued, last_checked) -> list:
    """Every way the committed worklist is unattributable, stale, self-contradictory or
    at odds with what this corpus holds.

    Everything it reads is passed in. `coverage` is what `rules/` holds and which
    chapters it mirrors, `catalogued` is every number the OAR catalog names (including
    the served-as numbers a renumbered row files under), and `last_checked` is the OAR
    source group's own record of when it last looked upstream."""
    problems = []
    if not isinstance(doc, dict):
        return [Problem("worklist-attribution", "_meta/bulletin-worklist.yml",
                        "is not a mapping — nothing can be read from it; regenerate "
                        f"with: {REGENERATE}")]
    # NOTHING TO CHECK AGAINST IS NOT A CLEAN BILL, AND IT IS NOT EVIDENCE OF DRIFT
    # EITHER. Every `in_corpus: true` row would be reported as naming a rule this corpus
    # does not hold, which is hundreds of confident findings derived from the checker
    # having read nothing — "could not check" rendered as "is not there", the exact
    # substitution CONTEXT.md forbids. link_enabling_authority.py refuses on an empty
    # `constitution/` for the same reason.
    if not coverage.held or not catalogued:
        return [Problem(
            "corpus-absent", "rules/ and _meta/catalog/oar.yml",
            f"name {len(coverage.held)} mirrored rule(s) and {len(catalogued)} "
            "catalogued rule(s) between them, so there is nothing to audit the worklist "
            "against. This gate refuses rather than reporting every held row as drift")]
    # AND THE SAME REFUSAL ONE LEVEL IN, for the half `corpus-absent` cannot see. The
    # third corpus state is decided from the mirrored-CHAPTER set, so a chapter listing
    # that came back short — or empty, which is what the #227 measurement error produced
    # — would file rules this corpus is missing as rules it never wanted, silently and in
    # the safe-looking direction. Held rules whose chapter is unaccounted for is proof
    # the chapter set is not what it claims to be, and the gate stops rather than
    # reporting a boundary it cannot tell from a gap.
    gaps = coverage_gaps(coverage)
    if gaps:
        return [Problem(
            "mirrored-chapters-unreadable", "rules/",
            f"holds rules in {len(gaps)} chapter(s) the mirrored-chapter listing does "
            f"not name ({', '.join(sorted(gaps)[:5])}…) out of {len(coverage.chapters)} "
            "listed. The chapter set is what decides whether a rule this corpus does not "
            "hold is a coverage gap or outside the selection, and one that cannot "
            "account for the corpus's own rules cannot decide it")]

    stated = doc.get("bulletin")
    when = bulletin_date(stated) if stated is not None else None
    if when is None:
        problems.append(Problem(
            "worklist-attribution", "bulletin",
            f"is {stated!r}, not `<Month> <YYYY> (bulltnRsn=<n>)` — a worklist that "
            "cannot name the bulletin it came from cannot be told from a current one "
            "without re-fetching, which is the whole reason the field exists"))
    url = doc.get("bulletin_url")
    if not url or not URL_RSN_RE.search(str(url)):
        problems.append(Problem(
            "worklist-attribution", "bulletin_url",
            f"is {url!r} and names no bulltnRsn — the link is what makes the claim "
            "checkable by a human, and one that cannot be followed is not a citation"))
    retrieved = doc.get("retrieved")
    if not retrieved or not RETRIEVED_RE.match(str(retrieved)):
        problems.append(Problem(
            "worklist-attribution", "retrieved",
            f"is {retrieved!r}, not an ISO date — without it the worklist states which "
            "bulletin it read and not when, so nothing can say how old the reading is"))

    m = BULLETIN_RE.match(str(stated).strip()) if stated is not None else None
    in_url = URL_RSN_RE.search(str(url)) if url else None
    if m and in_url and m.group(3) != in_url.group(1):
        problems.append(Problem(
            "bulletin-identity", "bulletin / bulletin_url",
            f"name different bulletins (bulltnRsn={m.group(3)} and "
            f"{in_url.group(1)}) — one fact written twice, and the two spellings "
            f"disagree, so the worklist cannot say which bulletin produced it"))

    if when is not None and last_checked is not None and when < last_checked:
        problems.append(Problem(
            "worklist-stale", str(stated),
            f"was published no later than {when.isoformat()} and the OAR source group "
            f"last looked upstream on {last_checked.isoformat()} — filings made since "
            f"this bulletin have not been read, so a repeal or suspension in them is "
            f"served here as though nothing had happened; re-run: {REGENERATE}"))

    # HOW MUCH OF THE MONTH THIS FILE IS. A short worklist is what a quiet month and a
    # month the reader could not read both produce, and nothing downstream could tell
    # them apart while `render_worklist` carried no completeness field (#233). The rules
    # below are about the file being ABLE to say it, which is why an absent key fails
    # rather than defaulting to "nothing was unread" — that default is a positive claim
    # made out of missing evidence.
    filings, unread = doc.get("filings"), doc.get("unread_filings")
    if not isinstance(filings, int) or isinstance(filings, bool) or filings < 0:
        problems.append(Problem(
            "worklist-completeness", "filings",
            f"is {filings!r}, not a count of the operative filings this reading "
            "covered. Without it the file cannot say whether it is short because little "
            "was filed or because filings could not be read, and those are the two "
            "things ADR 0006 exists to keep apart"))
    if not isinstance(unread, list):
        problems.append(Problem(
            "worklist-completeness", "unread_filings",
            f"is {unread!r}, not a list of the filings whose rules are unknown. An "
            "absent key reads as none unread, which is the month declared whole on the "
            "strength of nobody having written down that it was not"))
    else:
        for i, entry in enumerate(unread):
            if not isinstance(entry, dict) or not entry.get("filing"):
                problems.append(Problem(
                    "worklist-completeness", f"unread_filings[{i}]",
                    f"is {entry!r} and names no filing — an unknown recorded so that "
                    "nobody can go and look is not far from not recording it"))
        if isinstance(filings, int) and not isinstance(filings, bool):
            if len(unread) > filings:
                problems.append(Problem(
                    "worklist-completeness", "unread_filings",
                    f"names {len(unread)} unread filing(s) out of {filings} the file "
                    "says the month had — one fact written twice, and the two spellings "
                    "cannot both be true"))
            elif filings and len(unread) / filings > SYSTEMIC_SHARE:
                problems.append(Problem(
                    "worklist-completeness", "unread_filings",
                    f"names {len(unread)} of {filings} filings unread, more than the "
                    f"{SYSTEMIC_SHARE:.0%} past which this reader refuses to write at "
                    "all. A committed worklist in this state was not written by this "
                    "module, and its rows are an unknown fraction of the month being "
                    "served as a census"))

    # A MISSED MONTH IS AN ERROR, NOT A QUIET ONE. `worklist-stale` above catches a
    # worklist whose bulletin is OLDER than the last look upstream; this catches the gap
    # on the other side, where the worklist reads the newest bulletin and the months
    # between it and the last look were never opened. Nothing else here can see that: the
    # file names one bulletin, so a month it never read leaves no trace in it at all.
    if when is not None and last_checked is not None:
        skipped = months_skipped(when, last_checked)
        if skipped:
            problems.append(Problem(
                "bulletin-month-skipped", str(stated),
                f"is {skipped} month(s) past the OAR source group's last look upstream "
                f"({last_checked.isoformat()}), and the Bulletin is published monthly — "
                f"so {skipped} bulletin(s) between them were never read. Their filings "
                "are absent from every worklist this corpus holds, which is indis"
                f"tinguishable from months in which nothing was filed; re-run per month "
                f"with --rsn, oldest first: {REGENERATE} --rsn <n>"))

    rows = doc.get("rules")
    if isinstance(rows, list) and rows and filings == 0:
        problems.append(Problem(
            "worklist-completeness", "filings",
            f"is 0 and the file carries {len(rows)} rule action(s). Rule actions come "
            "from filings, so the two statements contradict each other and the worklist "
            "cannot say what it read"))
    if not isinstance(rows, list) or not rows:
        problems.append(Problem(
            "worklist-empty", "rules",
            f"holds no rule actions ({rows!r}). Every bulletin measured here has named "
            "hundreds; an empty list is what a refused parse and a quiet month look "
            f"like alike, and it is not a state this reader has ever produced"))
        return problems

    keys = []
    for i, row in enumerate(rows):
        where = f"rules[{i}]"
        if not isinstance(row, dict):
            problems.append(Problem("row-shape", where,
                                    f"is {row!r}, not a mapping of number/action/"
                                    "in_corpus"))
            continue
        number, action, state = row.get("number"), row.get("action"), \
            row.get("corpus_state")
        if not isinstance(number, str) or not RULE_NO_RE.fullmatch(number):
            problems.append(Problem("row-shape", where,
                                    f"has number {number!r}, which is not an OAR rule "
                                    "number in the form NNN-NNN-NNNN"))
            continue
        if state not in CORPUS_STATES:
            problems.append(Problem(
                "corpus-state-vocabulary", number,
                f"has corpus_state {state!r} — what this corpus knows about a rule the "
                f"Bulletin names is one of {', '.join(CORPUS_STATES)}, and anything "
                "else (a bare true/false among them) collapses a coverage gap into a "
                "boundary, which is the substitution this field exists to prevent"))
        if action not in ACTIONS:
            problems.append(Problem(
                "action-vocabulary", number,
                f"carries action {action!r}, which this reader does not produce — the "
                f"actions a filing can take are {', '.join(ACTIONS)}, and a row with "
                "any other arrived from something that is not this module"))
        # `action` is put in the ordering key only once it is known to be a string.
        # Sorting a str against a None is a TypeError, and a gate that dies with a
        # traceback instead of naming its rule is the thing #226 exists to close.
        keys.append((number, action if isinstance(action, str) else ""))
        target = row.get("renumbered_to")
        if action == "renumber":
            # A RENUMBER SAYS WHERE THE TEXT WENT, OR SAYS IT COULD NOT. The field's
            # ABSENCE is the failure and not the default: a criterion satisfiable by
            # deleting the key is not a criterion, and a renumber recording nothing is
            # what a consumer cannot tell from a repeal — the one action that means the
            # text is gone.
            if "renumbered_to" not in row:
                problems.append(Problem(
                    "renumber-destination", number,
                    "was renumbered and records no destination at all. Renumbered, "
                    f"renumbered with an unknown target ({UNKNOWN_TARGET}) and repealed "
                    "are three states and only the last means the text is gone; a row "
                    "silent about the move cannot be told from the last of them"))
            elif not (target == UNKNOWN_TARGET
                      or (isinstance(target, str) and RULE_NO_RE.fullmatch(target))):
                problems.append(Problem(
                    "renumber-destination", number,
                    f"has renumbered_to {target!r}, which is neither an OAR rule number "
                    f"nor {UNKNOWN_TARGET!r} — the field is joined on by number, so any "
                    "other value follows to nothing while still looking answered"))
            elif target == number:
                problems.append(Problem(
                    "renumber-destination", number,
                    "was renumbered to itself, which no filing says — a source read as "
                    "its own destination is a parse that lost the move"))
        elif "renumbered_to" in row:
            problems.append(Problem(
                "renumber-destination", number,
                f"carries renumbered_to {target!r} on a {action!r}. Only a renumber "
                "moves text, so a destination on any other action is a second claim "
                "about the rule that no filing line produced"))
        if state in CORPUS_STATES:
            actual = corpus_state(number, coverage)
            if state != actual:
                problems.append(Problem(
                    "corpus-state-agrees", number,
                    f"is recorded {state} and this corpus is in fact {actual} for it. "
                    + _STATE_HARM[actual]))
            if state == "held" and number not in catalogued:
                problems.append(Problem(
                    "catalog-knows-the-rule", number,
                    "is recorded held and the OAR catalog names no such rule. The "
                    "catalog writes and the document reads, so a document unreachable "
                    "from the catalog is drift rather than an accident"))
    # #233, AUDITED. `RENUMBER: X to Y` used to emit Y as a rule that was itself
    # renumbered, with no destination of its own — so a destination standing in the file
    # as a targetless renumber source is the exact shape the July worklist carried. A
    # genuine chain (X to Y, Y to Z) is not this: Y would name Z.
    targets = {r.get("renumbered_to") for r in rows if isinstance(r, dict)}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if (row.get("action") == "renumber"
                and row.get("renumbered_to") == UNKNOWN_TARGET
                and row.get("number") in targets):
            problems.append(Problem(
                "renumber-destination-as-source", row["number"],
                "is named as another row's renumber destination AND filed as a rule "
                "that was itself renumbered with no destination. It is where a text "
                "went, not a rule anything was filed against — reporting it as one "
                "tells this corpus a rule changed when it did not, and leaves the move "
                "a consumer would follow pointing nowhere"))
    if keys != sorted(set(keys)):
        problems.append(Problem(
            "rows-ordered", "rules",
            "are not the sorted, deduplicated rows this module writes — a repeated or "
            "out-of-order (number, action) pair means the file was edited by hand or "
            f"produced by something else; regenerate with: {REGENERATE}"))
    return problems


def held_rules() -> set:
    """Every OAR rule number this corpus holds a document for."""
    return {p.stem[len("oar-"):] for p in RULES_DIR.rglob("oar-*.md")}


def mirrored_chapters() -> set:
    """Every OAR chapter this corpus mirrors, from the chapter DIRECTORIES under rules/.

    `rules/` is chapter/division/oar-NNN-NNN-NNNN.md, so the chapters are directory
    names — three digits, no `oar-` prefix. Reading them off the rule FILENAMES instead
    would make `coverage_gaps` agree with itself by construction; reading them off a
    pattern that assumed `rules/oar-*.md` is how #227 came to be measured as zero."""
    if not RULES_DIR.exists():
        return set()          # reported by `corpus-absent`, never a traceback
    return {d.name for d in RULES_DIR.iterdir() if d.is_dir() and d.name.isdigit()}


def corpus_coverage() -> Coverage:
    """What this corpus holds and what it claims to mirror, read together."""
    return Coverage(held_rules(), mirrored_chapters())


def catalogued_rules() -> set:
    """Every OAR rule number the catalog names — requested AND served.

    A renumbered row is filed under the number OARD actually served, so both numbers
    name the same document and a check that knew only one of them would report the
    other as drift."""
    if not CATALOG.exists():
        return set()          # reported by `corpus-absent`, never a traceback
    cat = yaml.safe_load(CATALOG.read_text())
    out = set()
    for chapter in cat.get("chapters") or []:
        for division in chapter.get("divisions") or []:
            rules = division.get("rules")
            if not isinstance(rules, list):
                continue
            for rule in rules:
                out.add(rule.get("number"))
                if rule.get("served_as"):
                    out.add(rule["served_as"])
    out.discard(None)
    return out


def group_last_checked():
    """When the OAR source group last looked upstream, or None if it does not say."""
    group = yaml.safe_load(SOURCE_GROUP.read_text()) or {}
    value = group.get("last_checked")
    if isinstance(value, date):
        return value
    if isinstance(value, str) and RETRIEVED_RE.match(value):
        return date.fromisoformat(value)
    return None


def _unreadable(error) -> Problem:
    """The worklist failing to parse at all, as a Problem like every other rule here —
    the one rule that fires before `audit()` sees anything, and therefore the one that
    would otherwise be a hand-formatted string no proof could assert on."""
    return Problem("worklist-attribution", str(WORKLIST.name),
                   f"is not readable as YAML ({error}); regenerate with: {REGENERATE}")


def _report(problems) -> None:
    for p in problems:
        print(f"  FAIL [{p.rule}] {p.subject}: {p.detail}", file=sys.stderr)


def check() -> int:
    """Audit the committed worklist from committed data alone. No network."""
    unreadable = []
    try:
        doc = yaml.safe_load(WORKLIST.read_text()) if WORKLIST.exists() else None
    except yaml.YAMLError as e:
        doc, unreadable = None, [_unreadable(e)]
    problems = unreadable or audit(doc, corpus_coverage(), catalogued_rules(),
                                   group_last_checked())
    if problems:
        print("_meta/bulletin-worklist.yml does not hold up:", file=sys.stderr)
        _report(problems)
        return 1
    rows = doc["rules"]
    counts = collections.Counter(r["action"] for r in rows)
    # THE CENSUS, ON EVERY RUN, so that a worklist quietly shrinking is visible in the
    # log even on a green build (link_enabling_authority.py --check's line, same
    # reason). The number that would be easiest to print is the row count; the one that
    # matters is how many of those rows are rules this corpus actually serves.
    states = collections.Counter(r.get("corpus_state") for r in rows)
    print(f"{doc['bulletin']}: {len(rows)} rule action(s), "
          f"{states['held']} against rules held here")
    print("  " + ", ".join(f"{a}: {counts.get(a, 0)}" for a in ACTIONS))
    # THE THIRD STATE, COUNTED OUT LOUD, because it is the one a census that printed
    # "not held" would bury. A rule this corpus does not hold in a chapter it mirrors is
    # a gap; a rule outside the selection is a boundary; printing one number over both is
    # what let 121 of the first be served as the second for a month.
    gap = states["missing_from_mirrored_chapter"]
    gap_actions = collections.Counter(
        r["action"] for r in rows
        if r.get("corpus_state") == "missing_from_mirrored_chapter")
    print(f"  {gap} MISSING from chapters this corpus mirrors "
          f"({', '.join(f'{a}: {gap_actions[a]}' for a in ACTIONS if gap_actions[a])})"
          f"; {states['chapter_not_mirrored']} in chapters outside its selection")
    print(f"  read {doc['retrieved']}; OAR group last looked upstream "
          f"{group_last_checked()}")
    return 0



# ------------------------------------------------------------------------------ selftest
#
# THE PROOF THAT EVERY RULE ABOVE CAN FAIL, on synthetic bulletins and a synthetic
# worklist: no network, no read of the committed worklist, no read of the mirrored
# rules, no read of the catalog. A rule nobody has watched fail is not known to work —
# it is only known to be quiet, and before #226 all nine of the reader's rules stood
# exactly there.
#
# EVERY RULE NUMBER HERE IS MADE UP, and has to be. Oregon has no OAR chapter 999, so a
# fixture cannot be mistaken for a claim about a real rule's legal force — which is the
# claim this whole spec exists to stop being made carelessly.


def _index_page() -> str:
    """The bulletin index, in the shape the OARD app publishes it."""
    return ("<div id='accordion'>"
            "<a href='displayBulletin.action?bulltnRsn=1741'>July&nbsp;&nbsp;2026</a>"
            "<a href='displayBulletin.action?bulltnRsn=1761'>August&nbsp;&nbsp;2026</a>"
            "</div>")


def _bulletin_page(pt_ids=("100", "101", "102")) -> str:
    """A bulletin page: the proposals table, then the operative-filings table.

    THE PROPOSALS TABLE IS IN THE FIXTURE ON PURPOSE. It sits above the operative one
    on the real page and looks exactly like it, so a fixture without it could not tell
    a reader that takes the right table from one that takes both — and a reader that
    took both would report proposed rulemaking as filed changes."""
    proposals = ("<h2>Notices of Proposed Rulemaking</h2><table>"
                 "<tr><td>999</td><td>Board of Imaginary Affairs</td><td>PR 1</td>"
                 "<td>2026-06-01</td><td>Proposed</td><td>A proposal</td>"
                 "<td><a href='viewReceiptTRIM.action?ptId=900'>View PDF</a></td>"
                 "</tr></table>")
    rows = "".join(
        f"<tr><td>999</td><td>Board of Imaginary Affairs</td><td>AON {i}-2026</td>"
        f"<td>2026-06-15</td><td>Permanent</td><td>Filing {i}</td>"
        f"<td><a href='viewReceiptTRIM.action?ptId={i}'>View PDF</a></td></tr>"
        for i in pt_ids)
    return (proposals + f"<h2>{FILING_TABLE_MARK} Correction Filings</h2><table>"
            + rows + "</table>")


# Three filings, holding between them one of every action the reader recognises. The
# first also CITES two rules it does not change, in the prose the real filings carry —
# the need and justification sections quote other agencies' rules constantly, and a
# reader that took those would report a rule as amended because somebody mentioned it.
_FILINGS = {
    "100": ("AMEND: 999-001-0010\n"
            "\n"
            "RULE SUMMARY: This rule is amended for consistency with 999-003-0099,\n"
            "and the fee schedule at 999-004-0088 is unaffected.\n"),
    "101": ("REPEAL: 999-001-0020\n"
            "RENUMBER: 999-001-0030\n"
            "AMEND & RENUMBER: 999-001-0040 to 999-001-0050\n"),
    "102": "ADOPT: 999-002-0010\nSUSPEND: 999-002-0020\nADOPT: 998-001-0010\n",
}

# THE CLEAN MONTH CARRIES ALL THREE CORPUS STATES, which is what makes the round-trip
# and vocabulary proofs below say anything: 999-001-* are held, 999-002-* are absent from
# a chapter this fixture corpus mirrors (a GAP), and chapter 998 is outside its selection
# (a BOUNDARY). A fixture whose rules were all held could not tell a reader that keeps
# the last two apart from one that collapses them, which is the whole of #227.
_HELD = {"999-001-0010", "999-001-0020", "999-001-0030", "999-001-0040"}
_CHAPTERS = {"999"}
_COVERAGE = Coverage(_HELD, _CHAPTERS)
_CATALOGUED = _HELD | {"999-002-0010", "999-002-0020"}
_RSN = 1741
_URL = f"{OARD}/displayBulletin.action?bulltnRsn={_RSN}"


def _read_filing(pt_id: str) -> str:
    if pt_id not in _FILINGS:
        raise RuntimeError(f"RecordViewer uri={pt_id}: no embedded base64 PDF")
    return _FILINGS[pt_id]


def _reading(pt_ids=("100", "101", "102"), read_filing=_read_filing) -> Reading:
    return read_bulletin(filing_rows(_bulletin_page(pt_ids)), read_filing, _COVERAGE)


def _fixture() -> dict:
    """A clean month, and the audit's view of the corpus it is checked against.

    THE WORKLIST IS THE READER'S OWN OUTPUT, rendered and parsed back, never a mapping
    written out by hand beside it. A hand-written fixture would be a second spelling of
    what the writer emits, and the day the two spellings drifted this gate would go on
    passing against a file the writer no longer produces — which is the one failure a
    generated-file check cannot afford."""
    text = render_worklist("July", 2026, _RSN, _URL, "2026-07-02", _reading().rows,
                           8, [])
    return {"doc": yaml.safe_load(text),
            "coverage": Coverage(set(_HELD), set(_CHAPTERS)),
            "catalogued": set(_CATALOGUED), "last_checked": date(2026, 6, 15)}


def _audit(f) -> list:
    return audit(f["doc"], f["coverage"], f["catalogued"], f["last_checked"])


def _check_text(text) -> list:
    """The problems `--check` produces for worklist bytes, without touching the
    committed file: the parse and the audit, in the order `check()` runs them."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return [_unreadable(e)]
    return audit(doc, Coverage(set(_HELD), set(_CHAPTERS)), set(_CATALOGUED),
                 date(2026, 6, 15))


def _refused_or_problems(page: str) -> list:
    """The problems reading a bulletin page's filings table produced, refusal or not."""
    try:
        return list(filing_rows(page).problems)
    except Refusal as r:
        return [r.problem]


def _refused(fn, *args) -> list:
    """The Problem a refusal carried, or nothing if it did not refuse."""
    try:
        fn(*args)
    except Refusal as r:
        return [r.problem]
    return []


def _case_worklist_that_is_not_a_mapping(f):
    """The file replaced by something that is not a worklist at all — a stray list, a
    truncated write, the absent file `--check` passes as None. Nothing can be read from
    it, and reading nothing from it must not read as a clean month."""
    f["doc"] = ["not", "a", "worklist"]
    return _audit(f)


def _case_worklist_that_is_not_readable_as_yaml(f):
    """Bytes that are not YAML. `--check` parses the file before the audit sees it, so
    this is the one rule that fires outside `audit()` — and a branch outside the audit
    is exactly where an unwatched refusal hides."""
    return _check_text("bulletin: [unclosed\n")


def _case_row_that_is_not_a_mapping(f):
    """A row that is a bare string. The list is what a consumer iterates, so an entry
    it cannot read `.get()` on stops the consumer rather than this gate."""
    f["doc"]["rules"][0] = "999-001-0010 amend"
    return _audit(f)


def _case_row_with_no_action_at_all(f):
    """A row whose action key is gone, sharing its number with another row. It is
    reported as an action this reader does not produce — the point of the case is that
    it is REPORTED: ordering the rows puts a string beside a None, which used to be a
    TypeError out of `--check`, and a gate that dies with a traceback names no rule and
    tells nobody which row to look at."""
    row = dict(f["doc"]["rules"][0])
    del row["action"]
    f["doc"]["rules"].append(row)
    return _audit(f)


def _case_bulletin_line_missing(f):
    """A worklist that does not say which bulletin produced it. It reads exactly like a
    current one, and nothing short of re-fetching can tell them apart."""
    del f["doc"]["bulletin"]
    return _audit(f)


def _case_bulletin_line_unreadable(f):
    """A bulletin line a human wrote in their own words. It names a month, which is why
    this is the dangerous shape: it looks attributed and carries no bulltnRsn, so
    nothing can follow it back to the page it claims to have read."""
    f["doc"]["bulletin"] = "the July bulletin"
    return _audit(f)


def _case_bulletin_url_missing(f):
    """No link to the bulletin. The citation is what makes the claim checkable by a
    human; a worklist that cannot be followed back is an assertion on nobody."""
    del f["doc"]["bulletin_url"]
    return _audit(f)


def _case_retrieved_missing(f):
    """The worklist says WHICH bulletin it read and not WHEN. Both are needed: a
    bulletin is a fixed document, so its name alone can never say how old the reading
    of it is."""
    del f["doc"]["retrieved"]
    return _audit(f)


def _case_bulletin_named_twice_and_disagreeing(f):
    """The bulltnRsn is written twice — in the `bulletin` line and inside the URL — and
    nothing gated their agreement before this rule. Two spellings of one fact is the
    drift this repository keeps finding, and here it means the worklist cannot say
    which bulletin produced its rows."""
    f["doc"]["bulletin_url"] = f"{OARD}/displayBulletin.action?bulltnRsn=1761"
    return _audit(f)


def _case_bulletin_older_than_the_last_look_upstream(f):
    """The state the committed worklist was actually in when #226 was written: a July
    bulletin recorded while the OAR group had already looked upstream on 18 July. Every
    filing between the two dates is unread, and a repeal among them is served here as
    though nothing had happened."""
    f["last_checked"] = date(2026, 7, 18)
    return _audit(f)


def _case_a_month_that_was_never_read_at_all(f):
    """The OAR group last looked upstream in April and the worklist reads July. MAY AND
    JUNE WERE NEVER READ, and nothing said so: the worklist is not stale — its bulletin
    is the newest one — and every rule rule the reader applies to it passes. The bulletins
    are monthly and their identifiers monotonic, so a month with no reading behind it is
    detectable, and a repeal filed in one of them is served here as though the filing had
    never happened. Two months of filings, missing, behind a green check."""
    f["last_checked"] = date(2026, 4, 20)
    return _audit(f)


def _case_worklist_that_does_not_say_how_much_of_the_month_it_read(f):
    """The completeness header deleted. A parse failure and a quiet month produce the
    same short worklist (ADR 0006), and the only thing that can tell them apart is the
    file saying how many filings it read and which it could not — so its ABSENCE is the
    failure and not the default. A criterion satisfiable by deleting the field is not a
    criterion."""
    del f["doc"]["filings"]
    return _audit(f)


def _case_worklist_that_does_not_say_which_filings_it_could_not_read(f):
    """`filings` kept and `unread_filings` gone. The count alone cannot say WHICH filing
    a human has to open, and an absent key reads as none unread — a positive claim (the
    month is whole) made from the absence of evidence."""
    del f["doc"]["unread_filings"]
    return _audit(f)


def _case_worklist_with_rules_and_no_filings(f):
    """Rows from a month the file says had no filings. One fact stated twice — the rows
    and the census — and the two spellings contradict each other, so the worklist cannot
    say what it read."""
    f["doc"]["filings"] = 0
    return _audit(f)


def _case_worklist_that_was_written_from_a_fraction_of_a_month(f):
    """A committed worklist declaring more of the month unread than the writer will
    write over — the writer refuses past a fifth (`month_is_whole`), so a committed file
    saying otherwise was produced by something that is not this module, and its rows are
    an unknown fraction of the month presented as a census."""
    f["doc"]["filings"] = 4
    f["doc"]["unread_filings"] = [
        {"filing": f"AON {i}-2026", "url": VIEWER.format(900 + i)} for i in range(3)]
    return _audit(f)


def _case_worklist_with_no_rows(f):
    """An empty worklist passes every row rule there is, which is exactly why it needs
    a rule of its own: a criterion satisfiable by DELETING the rows is not a criterion.
    A quiet month and a refused parse produce the same empty list, and every bulletin
    measured here has named hundreds of actions."""
    f["doc"]["rules"] = []
    return _audit(f)


def _case_row_that_is_not_a_rule_number(f):
    """A row citing a rule the way prose cites it. The worklist is joined on this field
    by number, so a value in any other shape matches nothing and drops silently out of
    every consumer rather than failing in one of them."""
    f["doc"]["rules"][0]["number"] = "OAR 999-001-0010"
    return _audit(f)


def _case_row_that_does_not_say_what_this_corpus_knows(f):
    """A row carrying the OLD two-state field's value — a bare `true`. It is the shape
    this worklist used to be written in, and it is refused rather than read as `held`:
    every value of a two-state field is truthy or falsy, so accepting one would let the
    collapsed spelling go on being audited as though it said which of the three."""
    f["doc"]["rules"][0]["corpus_state"] = True
    return _audit(f)


def _case_action_this_reader_does_not_produce(f):
    """An action outside the vocabulary. The verbs are what the filings' action-anchored
    lines say, and a row carrying anything else came from something that is not this
    module — the two-writers drift, in the one field a consumer branches on."""
    f["doc"]["rules"][0]["action"] = "amended"
    return _audit(f)


def _case_rows_not_as_this_module_writes_them(f):
    """A row appearing twice. The writer sorts and deduplicates, so a repeat means the
    file was hand-edited or produced by something else — and a duplicated repeal is a
    consumer doing the same irreversible thing twice."""
    f["doc"]["rules"].append(dict(f["doc"]["rules"][0]))
    return _audit(f)


def _case_missing_from_a_chapter_we_mirror_called_out_of_scope(f):
    """THE 121. A rule this corpus does not hold, in a chapter it DOES mirror, recorded
    as though the chapter were outside the selection. Those are different facts and only
    one of them is a coverage gap: 121 rows of the August worklist stand here, 43 of them
    amendments — rules that existed, changed, and are absent from chapters this corpus
    claims to mirror."""
    for row in f["doc"]["rules"]:
        if row["number"] == "999-002-0010":       # adopted into a chapter we mirror
            row["corpus_state"] = "chapter_not_mirrored"
    return _audit(f)


def _case_marked_held_and_not_held(f):
    """A row claiming this corpus holds a rule it does not. The worklist would send a
    re-ingest at a document that is not there."""
    f["coverage"].held.discard("999-001-0010")
    return _audit(f)


def _case_marked_not_held_and_held(f):
    """THE DIRECTION THAT MATTERS. A rule whose text changed upstream, marked as not
    held while `rules/` serves it — so it sits outside the re-ingest worklist and this
    corpus goes on serving superseded text under provenance. The other direction is
    loud; this one is silent, and it is the failure the worklist exists to prevent."""
    f["coverage"].held.add("999-002-0010")
    return _audit(f)


def _case_a_renumber_that_does_not_say_where_the_text_went(f):
    """The destination key deleted from a renumber row. A criterion satisfiable by
    DELETING the field is not a criterion, so its absence is the failure and not the
    default: a renumber that records nothing is indistinguishable from a repeal to every
    consumer, and only one of the two means the text is gone."""
    for row in f["doc"]["rules"]:
        if row["action"] == "renumber":
            row.pop("renumbered_to", None)
    return _audit(f)


def _case_a_destination_filed_as_a_rule_that_was_renumbered(f):
    """#233, AS IT STOOD IN THE COMMITTED JULY WORKLIST. `RENUMBER: X to Y` paired every
    number on the line with every verb, so Y — where the text WENT — was filed as a rule
    that was itself renumbered, with no destination of its own. A rule this corpus is
    told changed when it did not, and the move a consumer would follow left dangling."""
    dest = next(r["renumbered_to"] for r in f["doc"]["rules"]
                if r["action"] == "renumber" and r["renumbered_to"] != "unknown")
    f["doc"]["rules"].append({"number": dest, "action": "renumber",
                              "corpus_state": "missing_from_mirrored_chapter",
                              "renumbered_to": "unknown"})
    f["doc"]["rules"].sort(key=lambda r: (r["number"], r["action"]))
    return _audit(f)


def _case_a_destination_on_an_action_that_has_none(f):
    """`renumbered_to` on a repeal. The field is what says the text moved, and a repeal
    that carries one is two claims about force at once — the reader produces it for
    renumbers and nothing else, so a row with one arrived from something that is not
    this module."""
    for row in f["doc"]["rules"]:
        if row["action"] == "repeal":
            row["renumbered_to"] = "999-001-0099"
    return _audit(f)


def _case_held_rule_the_catalog_does_not_name(f):
    """A document `rules/` holds that the OAR catalog knows nothing about. The catalog
    writes and the document reads, so a document unreachable from it is drift — and a
    worklist row is the first place that drift shows up as a rule nobody can route."""
    f["catalogued"].discard("999-001-0010")
    return _audit(f)


def _case_a_chapter_listing_that_matched_nothing(f):
    """THE MEASUREMENT ERROR IN #227, AS A CASE. The mirrored-chapter set comes back
    empty — a pattern written against the wrong path, a listing that matched no
    directories — while `rules/` still holds its documents. Every rule this corpus is
    MISSING would be filed as a rule it never wanted, quietly and in the reassuring
    direction. The gate refuses instead: a chapter set that cannot account for the
    corpus's own rules cannot say which side of the boundary anything is on."""
    f["coverage"] = Coverage(f["coverage"].held, set())
    return _audit(f)


def _case_nothing_to_check_the_worklist_against(f):
    """The mirrored rules unreadable — a bad path, a checkout that did not fetch them,
    a rename. Every held row would be reported as naming a rule this corpus does not
    hold: hundreds of confident findings produced by a checker that read nothing. The
    gate refuses instead, because "could not check" is never "is not there"."""
    f["coverage"], f["catalogued"] = Coverage(set(), set()), set()
    return _audit(f)


def _case_index_page_whose_layout_moved(f):
    """The index still serves a page; it no longer serves the links. Returning no
    bulletins would be a confident zero — and there is no such thing as a month the
    Secretary of State published no bulletin for, so the reader refuses instead."""
    return _refused(parse_bulletin_index,
                    _index_page().replace("displayBulletin.action", "showBulletin.do"))


def _case_bulletin_the_index_does_not_list(f):
    """`--rsn` naming a bulletin that is not on the index. Reading it anyway would
    attribute a worklist to a bulletin nobody can find again."""
    return _refused(pick_bulletin, parse_bulletin_index(_index_page()), 9999)


def _case_bulletin_page_without_its_filings_table(f):
    """A bulletin page whose operative-filings table is gone. Zero filings is what this
    looks like, and zero filings is also what a quiet month looks like — the reader
    refuses rather than writing a worklist that cannot tell the two apart."""
    return _refused(filing_rows,
                    _bulletin_page().replace(FILING_TABLE_MARK, "Filings This Month"))


def _case_filings_table_that_yielded_no_filings(f):
    """The table is still there and its rows no longer parse — a cell count that moved,
    a link renamed. ZERO FILINGS IS THE ANSWER, and zero filings is also what a quiet
    month looks like, so the reader refuses rather than writing a worklist that cannot
    tell a layout change from a month the Secretary of State published nothing in. The
    mark being present is exactly why `filing-table` cannot catch this."""
    return _refused(filing_rows,
                    _bulletin_page().replace("viewReceiptTRIM.action", "getReceipt.do"))


def _case_filing_row_that_could_not_be_read(f):
    """One row of the operative table carrying cells and no "View PDF" link (#233). It
    is dropped today and nothing says so — a filing that could not be processed leaving
    no trace, which ADR 0006 forbids in the same words it forbids a dropped filing. ONE
    BAD ROW AMONG GOOD ONES deliberately, so the case cannot be satisfied by the
    whole-table refusal above."""
    page = _bulletin_page()
    return _refused_or_problems(page.replace(
        "</table>",
        "<tr><td>999</td><td>Board of Imaginary Affairs</td><td>AON 9-2026</td>"
        "<td>2026-06-15</td><td>Permanent</td><td>A filing with no link</td></tr>"
        "</table>"))


def _case_filing_that_could_not_be_read(f):
    """One filing the records app would not serve, in a month of eight. Its rules are
    absent from the worklist for a reason that is not "nothing happened", so the run
    records it (ADR 0006: a thing that could not be processed is recorded, never
    dropped). ONE IN EIGHT IS UNDER THE SYSTEMIC SHARE deliberately — a case that also
    tripped `filing-systemic` would prove the two rules only ever fire together, and
    tolerating the individual failure is what this reader claims to do."""
    return _reading(("100", "101", "102", "100", "101", "102", "100", "999")).problems


def _case_most_of_the_month_unreadable(f):
    """An outage, not noise. Individual filings fail; a fifth of them failing means the
    worklist this run would write is missing an unknown share of the month, and the run
    has to fail rather than commit it."""
    def _never(pt_id):
        raise RuntimeError("records app returned 503")
    return _reading(read_filing=_never).problems


def _case_one_rule_renumbered_to_two_different_places(f):
    """Two filings in one month naming the same rule and different destinations. The
    reader keys a worklist row on (number, action), so the second reading of the pair is
    dropped and the FIRST destination wins by arrival order — one fact written twice,
    with nothing gating the agreement and the disagreement resolved silently in favour of
    whichever filing the table happened to list first."""
    return read_bulletin(filing_rows(_bulletin_page(("100", "101"))),
                         lambda pt_id: {
                             "100": "RENUMBER: 999-001-0030 to 999-001-0060\n",
                             "101": "RENUMBER: 999-001-0030 to 999-001-0070\n",
                         }[pt_id], _COVERAGE).problems


def _case_action_line_that_runs_off_the_end_of_itself(f):
    """A filing line that ends in a comma with nothing beneath it that could continue it
    (#233). Rule numbers were promised and are not there. The parser cannot recover
    them, and the only two things it may do are recover them or SAY IT COULD NOT — a
    tolerated under-report with nothing recording that it happened is a worklist short
    by an unknown number of rules that reads exactly like a complete one."""
    return read_bulletin(filing_rows(_bulletin_page(("100",))),
                         lambda pt_id: "AMEND: 999-001-0010, 999-001-0020,\n"
                                       "\nRULE SUMMARY: unrelated prose.\n",
                         _COVERAGE).problems


def _case_filing_naming_no_rules(f):
    """A filing that read fine and named no rules. NOT the same event as one that could
    not be read — this one is a human's to look at, that one is this module failing —
    so they are two rules and not one count."""
    return read_bulletin(filing_rows(_bulletin_page(("100",))),
                         lambda pt_id: "NOTICE OF PROPOSED RULEMAKING HEARING\n",
                         _COVERAGE).problems


_CASES = [
    ("worklist-that-is-not-a-mapping", _case_worklist_that_is_not_a_mapping,
     "worklist-attribution"),
    ("worklist-that-is-not-readable-as-yaml",
     _case_worklist_that_is_not_readable_as_yaml, "worklist-attribution"),
    ("row-that-is-not-a-mapping", _case_row_that_is_not_a_mapping, "row-shape"),
    ("row-with-no-action-at-all", _case_row_with_no_action_at_all,
     "action-vocabulary"),
    ("bulletin-line-missing", _case_bulletin_line_missing, "worklist-attribution"),
    ("bulletin-line-unreadable", _case_bulletin_line_unreadable, "worklist-attribution"),
    ("bulletin-url-missing", _case_bulletin_url_missing, "worklist-attribution"),
    ("retrieved-missing", _case_retrieved_missing, "worklist-attribution"),
    ("bulletin-named-twice-and-disagreeing",
     _case_bulletin_named_twice_and_disagreeing, "bulletin-identity"),
    ("bulletin-older-than-the-last-look-upstream",
     _case_bulletin_older_than_the_last_look_upstream, "worklist-stale"),
    ("a-month-that-was-never-read-at-all", _case_a_month_that_was_never_read_at_all,
     "bulletin-month-skipped"),
    ("worklist-that-does-not-say-how-much-of-the-month-it-read",
     _case_worklist_that_does_not_say_how_much_of_the_month_it_read,
     "worklist-completeness"),
    ("worklist-that-does-not-say-which-filings-it-could-not-read",
     _case_worklist_that_does_not_say_which_filings_it_could_not_read,
     "worklist-completeness"),
    ("worklist-with-rules-and-no-filings", _case_worklist_with_rules_and_no_filings,
     "worklist-completeness"),
    ("worklist-that-was-written-from-a-fraction-of-a-month",
     _case_worklist_that_was_written_from_a_fraction_of_a_month,
     "worklist-completeness"),
    ("worklist-with-no-rows", _case_worklist_with_no_rows, "worklist-empty"),
    ("row-that-is-not-a-rule-number", _case_row_that_is_not_a_rule_number, "row-shape"),
    ("row-that-does-not-say-what-this-corpus-knows",
     _case_row_that_does_not_say_what_this_corpus_knows, "corpus-state-vocabulary"),
    ("action-this-reader-does-not-produce",
     _case_action_this_reader_does_not_produce, "action-vocabulary"),
    ("rows-not-as-this-module-writes-them",
     _case_rows_not_as_this_module_writes_them, "rows-ordered"),
    ("missing-from-a-chapter-we-mirror-called-out-of-scope",
     _case_missing_from_a_chapter_we_mirror_called_out_of_scope, "corpus-state-agrees"),
    ("marked-held-and-not-held", _case_marked_held_and_not_held, "corpus-state-agrees"),
    ("marked-not-held-and-held", _case_marked_not_held_and_held, "corpus-state-agrees"),
    ("a-renumber-that-does-not-say-where-the-text-went",
     _case_a_renumber_that_does_not_say_where_the_text_went, "renumber-destination"),
    ("a-destination-filed-as-a-rule-that-was-renumbered",
     _case_a_destination_filed_as_a_rule_that_was_renumbered,
     "renumber-destination-as-source"),
    ("a-destination-on-an-action-that-has-none",
     _case_a_destination_on_an_action_that_has_none, "renumber-destination"),
    ("held-rule-the-catalog-does-not-name",
     _case_held_rule_the_catalog_does_not_name, "catalog-knows-the-rule"),
    ("a-chapter-listing-that-matched-nothing",
     _case_a_chapter_listing_that_matched_nothing, "mirrored-chapters-unreadable"),
    ("nothing-to-check-the-worklist-against",
     _case_nothing_to_check_the_worklist_against, "corpus-absent"),
    ("index-page-whose-layout-moved", _case_index_page_whose_layout_moved,
     "index-layout"),
    ("bulletin-the-index-does-not-list", _case_bulletin_the_index_does_not_list,
     "bulletin-not-listed"),
    ("bulletin-page-without-its-filings-table",
     _case_bulletin_page_without_its_filings_table, "filing-table"),
    ("filings-table-that-yielded-no-filings",
     _case_filings_table_that_yielded_no_filings, "filing-table-empty"),
    ("filing-row-that-could-not-be-read", _case_filing_row_that_could_not_be_read,
     "filing-row-unreadable"),
    ("filing-that-could-not-be-read", _case_filing_that_could_not_be_read,
     "filing-unreadable"),
    ("most-of-the-month-unreadable", _case_most_of_the_month_unreadable,
     "filing-systemic"),
    ("one-rule-renumbered-to-two-different-places",
     _case_one_rule_renumbered_to_two_different_places, "renumber-destination-conflict"),
    ("action-line-that-runs-off-the-end-of-itself",
     _case_action_line_that_runs_off_the_end_of_itself, "action-line-truncated"),
    ("filing-naming-no-rules", _case_filing_naming_no_rules, "filing-no-actions"),
]


def _proof_a_clean_month_produces_no_finding() -> int:
    """THE MUST-NOT-FIRE GUARD. A bulletin that read cleanly and the worklist it wrote
    must produce nothing at all — from the reader and from the audit alike — so that a
    blanket "always report" cannot pass this file. This project has shipped a guard that
    could not fail more than once."""
    bad = 0
    reading = _reading()
    if reading.problems:
        print(f"FAIL a-clean-month-produces-no-finding: the reader reported "
              f"{reading.problems}", file=sys.stderr)
        bad += 1
    problems = _audit(_fixture())
    if problems:
        print(f"FAIL a-clean-worklist-produces-no-finding: {problems}", file=sys.stderr)
        bad += 1
    return bad


def _proof_what_the_reader_writes_is_what_the_check_accepts() -> int:
    """The writer and the checker are two readings of one file format, and nothing
    gated their agreement. Render a month, parse it back, audit it: the rows must
    survive intact and the audit must be silent. Without this the two could drift until
    `--check` was passing a file the reader no longer produces — the one failure a
    generated-file gate cannot afford."""
    f = _fixture()
    rows = _reading().rows
    got = f["doc"]["rules"]
    if got != rows:
        print(f"FAIL what-the-reader-writes-survives-the-round-trip: {got!r} != "
              f"{rows!r}", file=sys.stderr)
        return 1
    return 0


def _proof_a_prose_citation_is_not_a_change() -> int:
    """Filing 100 amends one rule and CITES two others in its summary. Only the
    action-anchored line is a change; taking a cited number would report a rule as
    amended because another agency's filing mentioned it.

    The expected numbers are written out rather than re-derived the way the reader
    derives them, which would pass whatever it said."""
    got = sorted(actions_in(_FILINGS["100"]).actions)
    if got != [Action("999-001-0010", "amend", None)]:
        print(f"FAIL a-prose-citation-is-not-a-change: {got!r}", file=sys.stderr)
        return 1
    return 0


def _proof_a_compound_verb_reports_every_action_it_names() -> int:
    """`AMEND & RENUMBER: 999-005-0010` is two things happening to one rule, and a
    consumer acts differently on each — an amendment is a text refresh, a renumber
    moves where the text lives. Reporting only the first verb would lose the move."""
    got = sorted(actions_in("AMEND & RENUMBER: 999-005-0010\n").actions)
    if got != [Action("999-005-0010", "amend", None),
               Action("999-005-0010", "renumber", UNKNOWN_TARGET)]:
        print(f"FAIL a-compound-verb-reports-every-action-it-names: {got!r}",
              file=sys.stderr)
        return 1
    return 0


def _proof_every_named_action_is_one_the_reader_parses() -> int:
    """The vocabulary and the parser are now one declaration, and this is what says the
    declaration is USED at both ends rather than merely shared. Each verb is put at the
    head of a filing line and must come back as that action; a vocabulary entry the
    reader cannot produce would be a row `--check` accepts and no bulletin can create.

    The expected pairs are written out from ACTIONS rather than derived the way
    `actions_in` derives them, which would pass whatever it said."""
    bad = 0
    for action in ACTIONS:
        got = sorted(actions_in(f"{action.upper()}: 999-006-0010\n").actions)
        want = [Action("999-006-0010", action,
                       UNKNOWN_TARGET if action == "renumber" else None)]
        if got != want:
            print(f"FAIL every-named-action-is-one-the-reader-parses: {action} -> "
                  f"{got!r}", file=sys.stderr)
            bad += 1
    return bad


def _proof_a_tolerated_filing_failure_is_not_a_systemic_one() -> int:
    """The two filing rules are separate claims and must be separately reachable. One
    unreadable filing in eight is tolerated — recorded, and the month still written; a
    fifth of them is an outage and the month is not written at all. A pair of rules that
    only ever fire together is one rule with two names, and the tolerance this reader
    documents would be untested."""
    tolerated = _reading(("100", "101", "102", "100", "101", "102", "100", "999"))
    outage = _reading(("999", "998"))
    bad = 0
    # THE WRITER'S DECISION, not merely the rule that informs it. A month the reader
    # could not read must not be written over the last one that was whole, and a month
    # that lost one filing in eight must still be written — otherwise a single records-
    # app hiccup would freeze the worklist for a month.
    if not month_is_whole(tolerated):
        print("FAIL a-tolerated-filing-failure-still-gets-written: one unreadable "
              "filing in eight refused the whole month", file=sys.stderr)
        bad += 1
    if month_is_whole(outage):
        print("FAIL a-month-the-reader-could-not-read-is-not-written: the run would "
              "overwrite the last worklist that was whole", file=sys.stderr)
        bad += 1
    if any(p.rule == "filing-systemic" for p in tolerated.problems):
        print(f"FAIL a-tolerated-filing-failure-is-not-a-systemic-one: one in eight "
              f"tripped the systemic rule: {tolerated.problems}", file=sys.stderr)
        bad += 1
    if not tolerated.rows:
        print("FAIL a-tolerated-filing-failure-still-yields-a-month: no rows survived",
              file=sys.stderr)
        bad += 1
    if not any(p.rule == "filing-systemic" for p in outage.problems):
        print(f"FAIL an-outage-is-a-systemic-failure: {outage.problems}",
              file=sys.stderr)
        bad += 1
    return bad


def _proof_one_action_taken_twice_is_written_once() -> int:
    """The same rule corrected twice in a month is one row, not two — and the filing
    that repeated it still counts as a filing that named rules, so it must NOT be
    reported as naming none. That is the distinction the reader draws on `parsed`
    rather than on the seen-set growing."""
    reading = read_bulletin(filing_rows(_bulletin_page(("100", "100"))),
                            _read_filing, _COVERAGE)
    bad = 0
    if reading.rows != [{"number": "999-001-0010", "action": "amend",
                         "corpus_state": "held"}]:
        print(f"FAIL one-action-taken-twice-is-written-once: {reading.rows!r}",
              file=sys.stderr)
        bad += 1
    if reading.problems:
        print(f"FAIL a-duplicate-filing-is-not-a-filing-that-named-nothing: "
              f"{reading.problems!r}", file=sys.stderr)
        bad += 1
    return bad


def _proof_every_corpus_state_is_one_the_reader_produces() -> int:
    """The three states are one declaration, and this is what says the declaration is
    USED at both ends rather than merely shared — the same job `_proof_every_named_action
    _is_one_the_reader_parses` does for the verbs. A state `--check` accepts and the
    reader cannot produce is a vocabulary entry nothing can create; a state the reader
    produces and `--check` does not name is a row the gate rejects on sight.

    The coverage each state is asked for is written out rather than derived the way
    `corpus_state` derives it, which would pass whatever it said."""
    corpus = Coverage({"999-001-0010"}, {"999"})
    want = {
        "held": "999-001-0010",                          # a document on disk
        "missing_from_mirrored_chapter": "999-001-0020",  # chapter mirrored, rule absent
        "chapter_not_mirrored": "998-001-0010",           # outside the selection
    }
    bad = 0
    if set(want) != set(CORPUS_STATES):
        print(f"FAIL every-corpus-state-is-one-the-reader-produces: the vocabulary is "
              f"{CORPUS_STATES!r} and this proof knows {sorted(want)!r}", file=sys.stderr)
        return 1
    for state, number in want.items():
        got = corpus_state(number, corpus)
        if got != state:
            print(f"FAIL every-corpus-state-is-one-the-reader-produces: {number} -> "
                  f"{got!r}, wanted {state!r}", file=sys.stderr)
            bad += 1
    return bad


def _proof_a_renumber_reports_its_source_and_never_its_destination() -> int:
    """`RENUMBER: X to Y` is ONE rule that was renumbered and one place its text went.
    Reporting Y as a renumbered rule (#233) tells this corpus a rule changed when it did
    not, and leaves the move with no target for anyone to follow.

    The expected rows are written out rather than re-derived the way the parser derives
    them, which would pass whatever it said."""
    got = sorted(actions_in("RENUMBER: 999-007-0010 to 999-007-0020\n").actions)
    want = [Action("999-007-0010", "renumber", "999-007-0020")]
    if got != want:
        print(f"FAIL a-renumber-reports-its-source-and-never-its-destination: {got!r}",
              file=sys.stderr)
        return 1
    return 0


def _proof_a_compound_renumber_amends_the_source_alone() -> int:
    """`AMEND & RENUMBER: X to Y` amends X and moves it to Y. Y is additionally reported
    as AMENDED by the pairing #233 describes — a text change asserted against a rule
    nobody filed anything against."""
    got = sorted(actions_in("AMEND & RENUMBER: 999-007-0030 to 999-007-0040\n").actions)
    want = sorted([Action("999-007-0030", "amend", None),
                   Action("999-007-0030", "renumber", "999-007-0040")])
    if got != want:
        print(f"FAIL a-compound-renumber-amends-the-source-alone: {got!r}",
              file=sys.stderr)
        return 1
    return 0


def _proof_a_renumber_with_no_destination_is_not_a_repeal() -> int:
    """THE THIRD STATE, IN THE BYTES. A filing line that renumbers without saying where
    must reach the worklist as a renumber whose destination is unknown — never as a
    repeal, and never as a renumber with the field quietly absent. Renumbered, renumbered
    with unknown target and repealed are three states and only the last means the text is
    gone; a consumer that read the first two as the last would delete a rule that moved.

    Asserted on the RENDERED worklist, because that is what a consumer reads."""
    rows = read_bulletin(filing_rows(_bulletin_page(("101",))), _read_filing,
                         _COVERAGE).rows
    text = render_worklist("July", 2026, _RSN, _URL, "2026-07-02", rows, 8, [])
    doc = yaml.safe_load(text)
    moved = [r for r in doc["rules"] if r["number"] == "999-001-0030"]
    bad = 0
    if moved != [{"number": "999-001-0030", "action": "renumber",
                  "corpus_state": "held", "renumbered_to": "unknown"}]:
        print(f"FAIL a-renumber-with-no-destination-is-not-a-repeal: {moved!r}",
              file=sys.stderr)
        bad += 1
    if "unknown" in ACTIONS:
        print("FAIL an-unknown-destination-is-not-an-action: 'unknown' is in the action "
              "vocabulary, so a consumer branching on `action` could reach it",
              file=sys.stderr)
        bad += 1
    return bad


def _proof_an_action_line_is_read_past_its_own_end() -> int:
    """A filing that lists more rule numbers than fit on one line wraps them, and the
    reader was line-anchored (#233): everything after the trailing comma was lost. Two
    rules of a three-rule amendment would reach the worklist and the third would be
    absent for a reason that looks exactly like "nothing happened to it".

    The expected numbers are written out rather than re-derived the way the reader
    derives them, which would pass whatever it said."""
    parse = actions_in("AMEND: 999-008-0010, 999-008-0020,\n"
                       "       999-008-0030\n")
    got = sorted(a.number for a in parse.actions)
    bad = 0
    if got != ["999-008-0010", "999-008-0020", "999-008-0030"]:
        print(f"FAIL an-action-line-is-read-past-its-own-end: {got!r}", file=sys.stderr)
        bad += 1
    if parse.problems:
        print(f"FAIL a-recovered-continuation-is-not-a-loss: {parse.problems!r}",
              file=sys.stderr)
        bad += 1
    # A WRAPPED LINE IS NOT AN OPEN INVITATION. The next action header ends the previous
    # line whatever it ended with, or a truncated AMEND would swallow the REPEAL under it
    # and report those rules as amended.
    parse = actions_in("AMEND: 999-008-0040,\nREPEAL: 999-008-0050\n")
    got = sorted((a.number, a.verb) for a in parse.actions)
    if got != [("999-008-0040", "amend"), ("999-008-0050", "repeal")]:
        print(f"FAIL a-wrapped-line-stops-at-the-next-action: {got!r}", file=sys.stderr)
        bad += 1
    if not any(p.rule == "action-line-truncated" for p in parse.problems):
        print(f"FAIL a-line-that-lost-its-continuation-says-so: {parse.problems!r}",
              file=sys.stderr)
        bad += 1
    return bad


def _proof_a_parse_failure_and_a_quiet_month_are_not_the_same_worklist() -> int:
    """THE SUBSTITUTION ADR 0006 NAMES, IN THE BYTES A CONSUMER READS. A month one of
    whose filings could not be fetched holds fewer rules than it should, and so does a
    month in which little was filed. Nothing downstream could tell them apart, because
    `render_worklist` carried no completeness field at all (#233) — so the rules of the
    unreadable filing were simply absent, which is how "could not check" is served as
    "is not there".

    The two worklists below are built from the SAME clean rows on purpose: if the only
    difference the file records is the row count, the proof cannot hold."""
    rows = _reading().rows
    quiet = yaml.safe_load(render_worklist("July", 2026, _RSN, _URL, "2026-07-02",
                                           rows, 8, []))
    lost = yaml.safe_load(render_worklist(
        "July", 2026, _RSN, _URL, "2026-07-02", rows, 8,
        [Problem("filing-unreadable", "AON 9-2026",
                 f"could not be fetched or parsed: {VIEWER.format(909)}")]))
    bad = 0
    if quiet["rules"] != lost["rules"]:
        print("FAIL the-two-worklists-differ-only-in-what-they-say-they-read",
              file=sys.stderr)
        bad += 1
    if quiet["unread_filings"] != []:
        print(f"FAIL a-quiet-month-says-it-read-everything: "
              f"{quiet['unread_filings']!r}", file=sys.stderr)
        bad += 1
    named = [u.get("filing") for u in (lost["unread_filings"] or [])]
    if named != ["AON 9-2026"]:
        print(f"FAIL an-unread-filing-is-named-so-a-human-can-open-it: {named!r}",
              file=sys.stderr)
        bad += 1
    if not (lost["unread_filings"] or [{}])[0].get("url"):
        print("FAIL an-unread-filing-carries-the-link-a-human-would-follow",
              file=sys.stderr)
        bad += 1
    return bad


_PROOFS = [
    _proof_a_clean_month_produces_no_finding,
    _proof_what_the_reader_writes_is_what_the_check_accepts,
    _proof_a_prose_citation_is_not_a_change,
    _proof_a_compound_verb_reports_every_action_it_names,
    _proof_every_named_action_is_one_the_reader_parses,
    _proof_one_action_taken_twice_is_written_once,
    _proof_every_corpus_state_is_one_the_reader_produces,
    _proof_a_renumber_reports_its_source_and_never_its_destination,
    _proof_a_compound_renumber_amends_the_source_alone,
    _proof_a_renumber_with_no_destination_is_not_a_repeal,
    _proof_an_action_line_is_read_past_its_own_end,
    _proof_a_parse_failure_and_a_quiet_month_are_not_the_same_worklist,
    _proof_a_tolerated_filing_failure_is_not_a_systemic_one,
]


def selftest() -> int:
    bad = sum(proof() for proof in _PROOFS)
    proofs = len(_PROOFS)
    for name, mutate, rule in _CASES:
        f = _fixture()
        assert not _audit(f), f"fixture does not pass cleanly ({name}): {_audit(f)}"
        problems = mutate(f)
        if not any(p.rule == rule for p in problems):
            print(f"FAIL {name}: expected a [{rule}] problem, got {problems}",
                  file=sys.stderr)
            bad += 1
    rules = len({rule for _, _, rule in _CASES})
    print(f"{len(_CASES)} violation(s) across {rules} rule(s) demonstrated failing, "
          f"{proofs} reader proof(s) held" if not bad
          else f"{bad} rule(s) did not fire")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rsn", type=int, help="specific bulltnRsn (default: latest)")
    ap.add_argument("--list", action="store_true", help="list bulletins and exit")
    ap.add_argument("--check", action="store_true",
                    help="audit the committed worklist (offline; CI)")
    ap.add_argument("--selftest", action="store_true",
                    help="prove every rule this module applies can fail")
    args = ap.parse_args()
    if args.check:
        return check()
    if args.selftest:
        return selftest()
    try:
        return read_a_bulletin(args)
    except Refusal as refusal:
        _report([refusal.problem])
        return 1


def read_a_bulletin(args) -> int:
    """The fetching mode, unchanged in what it does: read a bulletin and write the
    worklist. Every refusal it can raise is turned into an exit code by its caller."""
    bulletins = parse_bulletin_index(
        fetch(f"{OARD}/displayBulletins.action").decode("utf-8", "replace"))
    if args.list:
        for year, mnum, month, rsn in bulletins:
            print(f"{year}-{mnum:02d}  {month} {year}  bulltnRsn={rsn}")
        return 0
    year, mnum, month, rsn = pick_bulletin(bulletins, args.rsn)
    url = f"{OARD}/displayBulletin.action?bulltnRsn={rsn}"
    print(f"bulletin: {month} {year} (bulltnRsn={rsn})")

    table = filing_rows(fetch(url).decode("utf-8", "replace"))
    print(f"{len(table.rows)} operative filings "
          f"(permanent/temporary/minor-correction)")

    def read_filing(pt_id: str) -> str:
        page = fetch(VIEWER.format(pt_id)).decode("utf-8", "replace")
        m = B64_PDF_RE.search(page)
        if not m:
            raise RuntimeError(f"RecordViewer uri={pt_id}: no embedded base64 PDF")
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(base64.b64decode(m.group(1)))
            f.flush()
            text = subprocess.run(["pdftotext", "-layout", f.name, "-"],
                                  capture_output=True, text=True, check=True).stdout
        time.sleep(0.2)
        return text

    def progress(i, total):
        if i % 25 == 0:
            print(f"  …{i}/{total} filings")

    reading = read_bulletin(table, read_filing, corpus_coverage(), progress)
    _report(reading.problems)
    n_in = sum(1 for r in reading.rows if r["corpus_state"] == "held")
    unread = [p for p in reading.problems
              if p.rule in ("filing-unreadable", "filing-row-unreadable")]
    unreadable, filings = len(unread), len(table.rows) + len(table.problems)
    # A SYSTEMIC FAILURE MAY NOT OVERWRITE THE LAST WORKLIST THAT WAS WHOLE. The rows
    # this run holds are missing an unknown share of the month, and a short worklist is
    # indistinguishable from a quiet one — writing it would leave `--check` auditing the
    # damage and printing a clean census over it, which is "could not check" served as
    # "is not there" by the very file that exists to keep those apart.
    if not month_is_whole(reading):
        print(f"\nREFUSED to write {WORKLIST.relative_to(REPO_ROOT)}: {unreadable} of "
              f"{filings} filings could not be read, so these {len(reading.rows)} rule "
              f"action(s) are an unknown fraction of the month. The committed worklist "
              f"is left as it is; re-run when the source is healthy.", file=sys.stderr)
        return 1
    WORKLIST.write_text(render_worklist(month, year, rsn, url,
                                        date.today().isoformat(), reading.rows,
                                        filings, unread))
    print(f"\nwrote {WORKLIST.relative_to(REPO_ROOT)}: {len(reading.rows)} rule "
          f"action(s) from {filings - unreadable} filing(s); {n_in} affect rules held "
          f"in this corpus; {unreadable} filing fetch/parse failure(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
