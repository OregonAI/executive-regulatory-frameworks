#!/usr/bin/env python3
"""Oregon Bulletin pilot (#78): read ONE document a month instead of hashing 36k rules.

The Oregon Bulletin is the official monthly digest of rule filings ("first business
day monthly" — _meta/sources/oar.yml's upstream_signal). This script fetches the
CURRENT bulletin and emits `_meta/bulletin-worklist.yml`: every OAR rule number the
bulletin's permanent/temporary/minor-correction filings adopt, amend, repeal,
renumber or suspend, with `in_corpus: true|false` — the re-ingest worklist that
issue #78 calls "the approach worth building".

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
ROW_RE = re.compile(r"<tr>\s*(<td.*?)</tr>", re.S)
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
_VERBS = "|".join(a.upper() for a in ACTIONS)
# Line-anchored action headers inside a filing PDF's text. Compounds ("AMEND &
# RENUMBER") report each verb for the numbers on the line.
ACTION_LINE_RE = re.compile(
    rf"^\s*((?:{_VERBS})(?:\s*&\s*(?:{_VERBS}))*)\s*:\s*(.*)$", re.M)
RULE_NO_RE = re.compile(r"\b(\d{3}-\d{3}-\d{4})\b")

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

# One thing wrong, and which RULE says so: the rule name, the thing it is about, and
# what is wrong with it. A type rather than a formatted string, for the reason the
# sibling modules give — `--selftest` asserts on the rule that fired, so a proof cannot
# start passing because some other rule happened to produce similar prose.
Problem = collections.namedtuple("Problem", "rule subject detail")

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


def filing_rows(bulletin_html: str) -> list:
    """(chapter, agency, aon, filed, type, caption, ptId) per operative filing.

    Only the operative table. The bulletin's other table is Notices of Proposed
    Rulemaking, where no rule text has changed yet, and a reader that took both would
    report proposals as filings."""
    idx = bulletin_html.find(FILING_TABLE_MARK)
    if idx < 0:
        raise Refusal(Problem(
            "filing-table", "displayBulletin.action",
            "the bulletin page has no operative-filings table — the format changed; "
            "re-investigate before parsing, because a bulletin parsed without its "
            "filings table yields zero filings and says nothing about why"))
    section = bulletin_html[idx:]
    rows = []
    for row in ROW_RE.findall(section):
        cells = [html.unescape(re.sub(r"<[^>]+>", " ", c)).strip()
                 for c in CELL_RE.findall(row)]
        m = PTID_RE.search(row)
        if m and len(cells) >= 6:
            rows.append(Filing(*[re.sub(r"\s+", " ", c) for c in cells[:6]],
                               m.group(1)))
    return rows


def actions_in(text: str):
    """Yield (rule_number, action) from a filing's action-anchored lines only.

    A bare NNN-NNN-NNNN anywhere else in the filing is a CITATION — the need and
    justification sections cite other agencies' rules constantly — and taking one as a
    change would report a rule as amended on the strength of somebody mentioning it."""
    for verbs, rest in ACTION_LINE_RE.findall(text):
        for verb in re.split(r"\s*&\s*", verbs):
            for num in RULE_NO_RE.findall(rest):
                yield num, verb.lower()


def read_bulletin(rows, read_filing, held, progress=None) -> Reading:
    """Read every filing in a month and return its worklist rows and its problems.

    `read_filing` is passed in and never defaulted to the fetching one: every proof
    below runs on synthetic filings, and a default that reached the network would be a
    proof that starts fetching the day someone forgets an argument.

    A FILING THAT COULD NOT BE READ IS RECORDED, NEVER DROPPED (ADR 0006). It is also
    not the same event as a filing that read fine and named no rules — the first is this
    module failing, the second is a filing a human has to look at — so they are two
    rules and not one count."""
    seen, out, problems, unreadable = set(), [], [], 0
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
        parsed = list(actions_in(text))
        for num, action in parsed:
            if (num, action) in seen:
                continue
            seen.add((num, action))
            out.append({"number": num, "action": action, "in_corpus": num in held})
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
    if rows and unreadable / len(rows) > SYSTEMIC_SHARE:
        problems.append(Problem(
            "filing-systemic", f"{unreadable}/{len(rows)} filings",
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


def render_worklist(month, year, rsn, url, retrieved, rows) -> str:
    """The worklist file's bytes. One writer, so `--check` audits what this emits."""
    lines = [
        "# Generated by src/check_bulletin.py — the monthly OAR re-ingest worklist (#78).",
        "# `in_corpus: true` rows are held rules whose text changed upstream this month",
        "# (re-ingest candidates); `false` rows are rules this corpus does not hold.",
        f"bulletin: {month} {year} (bulltnRsn={rsn})",
        f"bulletin_url: {url}",
        f"retrieved: '{retrieved}'",
        "rules:",
    ]
    for r in rows:
        lines.append(f"- number: {r['number']}")
        lines.append(f"  action: {r['action']}")
        lines.append(f"  in_corpus: {'true' if r['in_corpus'] else 'false'}")
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


def audit(doc, held, catalogued, last_checked) -> list:
    """Every way the committed worklist is unattributable, stale, self-contradictory or
    at odds with what this corpus holds.

    Everything it reads is passed in. `held` is the rule numbers `rules/` holds,
    `catalogued` is every number the OAR catalog names (including the served-as numbers
    a renumbered row files under), and `last_checked` is the OAR source group's own
    record of when it last looked upstream."""
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
    if not held or not catalogued:
        return [Problem(
            "corpus-absent", "rules/ and _meta/catalog/oar.yml",
            f"name {len(held)} mirrored rule(s) and {len(catalogued)} catalogued "
            "rule(s) between them, so there is nothing to audit the worklist against. "
            "This gate refuses rather than reporting every held row as drift")]

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

    rows = doc.get("rules")
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
        number, action, in_corpus = row.get("number"), row.get("action"), \
            row.get("in_corpus")
        if not isinstance(number, str) or not RULE_NO_RE.fullmatch(number):
            problems.append(Problem("row-shape", where,
                                    f"has number {number!r}, which is not an OAR rule "
                                    "number in the form NNN-NNN-NNNN"))
            continue
        if not isinstance(in_corpus, bool):
            problems.append(Problem("row-shape", number,
                                    f"has in_corpus {in_corpus!r} — the field states "
                                    "whether this corpus holds the rule and only true "
                                    "or false states it"))
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
        if isinstance(in_corpus, bool):
            if in_corpus and number not in held:
                problems.append(Problem(
                    "in-corpus-agrees", number,
                    "is marked held and rules/ has no document for it — the worklist "
                    "would send a re-ingest at a rule this corpus does not have"))
            if not in_corpus and number in held:
                problems.append(Problem(
                    "in-corpus-agrees", number,
                    "is marked not held and rules/ holds a document for it — a rule "
                    "whose text changed upstream is sitting outside the re-ingest "
                    "worklist, which is the failure the worklist exists to prevent"))
            if in_corpus and number not in catalogued:
                problems.append(Problem(
                    "catalog-knows-the-rule", number,
                    "is marked held and the OAR catalog names no such rule. The "
                    "catalog writes and the document reads, so a document unreachable "
                    "from the catalog is drift rather than an accident"))
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
    problems = unreadable or audit(doc, held_rules(), catalogued_rules(),
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
    n_in = sum(1 for r in rows if r["in_corpus"])
    print(f"{doc['bulletin']}: {len(rows)} rule action(s), {n_in} against rules held "
          f"here, {len(rows) - n_in} against rules this corpus does not hold")
    print("  " + ", ".join(f"{a}: {counts.get(a, 0)}" for a in ACTIONS))
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
    "101": "REPEAL: 999-001-0020\nRENUMBER: 999-001-0030\n",
    "102": "ADOPT: 999-002-0010\nSUSPEND: 999-002-0020\n",
}

_HELD = {"999-001-0010", "999-001-0020", "999-001-0030"}
_CATALOGUED = _HELD | {"999-002-0010", "999-002-0020"}
_RSN = 1741
_URL = f"{OARD}/displayBulletin.action?bulltnRsn={_RSN}"


def _read_filing(pt_id: str) -> str:
    if pt_id not in _FILINGS:
        raise RuntimeError(f"RecordViewer uri={pt_id}: no embedded base64 PDF")
    return _FILINGS[pt_id]


def _reading(pt_ids=("100", "101", "102"), read_filing=_read_filing) -> Reading:
    return read_bulletin(filing_rows(_bulletin_page(pt_ids)), read_filing, _HELD)


def _fixture() -> dict:
    """A clean month, and the audit's view of the corpus it is checked against.

    THE WORKLIST IS THE READER'S OWN OUTPUT, rendered and parsed back, never a mapping
    written out by hand beside it. A hand-written fixture would be a second spelling of
    what the writer emits, and the day the two spellings drifted this gate would go on
    passing against a file the writer no longer produces — which is the one failure a
    generated-file check cannot afford."""
    text = render_worklist("July", 2026, _RSN, _URL, "2026-07-02", _reading().rows)
    return {"doc": yaml.safe_load(text), "held": set(_HELD),
            "catalogued": set(_CATALOGUED), "last_checked": date(2026, 6, 15)}


def _audit(f) -> list:
    return audit(f["doc"], f["held"], f["catalogued"], f["last_checked"])


def _check_text(text) -> list:
    """The problems `--check` produces for worklist bytes, without touching the
    committed file: the parse and the audit, in the order `check()` runs them."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return [_unreadable(e)]
    return audit(doc, set(_HELD), set(_CATALOGUED), date(2026, 6, 15))


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


def _case_row_that_does_not_say_whether_it_is_held(f):
    """`in_corpus` holding something that is neither true nor false. The field states
    whether this corpus holds the rule, and a consumer reading a string finds it
    truthy — so `in_corpus: 'false'` would queue a re-ingest for a rule that is not
    here."""
    f["doc"]["rules"][0]["in_corpus"] = "true"
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


def _case_marked_held_and_not_held(f):
    """A row claiming this corpus holds a rule it does not. The worklist would send a
    re-ingest at a document that is not there."""
    f["held"].discard("999-001-0010")
    return _audit(f)


def _case_marked_not_held_and_held(f):
    """THE DIRECTION THAT MATTERS. A rule whose text changed upstream, marked as not
    held while `rules/` serves it — so it sits outside the re-ingest worklist and this
    corpus goes on serving superseded text under provenance. The other direction is
    loud; this one is silent, and it is the failure the worklist exists to prevent."""
    f["held"].add("999-002-0010")
    return _audit(f)


def _case_held_rule_the_catalog_does_not_name(f):
    """A document `rules/` holds that the OAR catalog knows nothing about. The catalog
    writes and the document reads, so a document unreachable from it is drift — and a
    worklist row is the first place that drift shows up as a rule nobody can route."""
    f["catalogued"].discard("999-001-0010")
    return _audit(f)


def _case_nothing_to_check_the_worklist_against(f):
    """The mirrored rules unreadable — a bad path, a checkout that did not fetch them,
    a rename. Every held row would be reported as naming a rule this corpus does not
    hold: hundreds of confident findings produced by a checker that read nothing. The
    gate refuses instead, because "could not check" is never "is not there"."""
    f["held"], f["catalogued"] = set(), set()
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


def _case_filing_naming_no_rules(f):
    """A filing that read fine and named no rules. NOT the same event as one that could
    not be read — this one is a human's to look at, that one is this module failing —
    so they are two rules and not one count."""
    return read_bulletin(filing_rows(_bulletin_page(("100",))),
                         lambda pt_id: "NOTICE OF PROPOSED RULEMAKING HEARING\n",
                         _HELD).problems


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
    ("worklist-with-no-rows", _case_worklist_with_no_rows, "worklist-empty"),
    ("row-that-is-not-a-rule-number", _case_row_that_is_not_a_rule_number, "row-shape"),
    ("row-that-does-not-say-whether-it-is-held",
     _case_row_that_does_not_say_whether_it_is_held, "row-shape"),
    ("action-this-reader-does-not-produce",
     _case_action_this_reader_does_not_produce, "action-vocabulary"),
    ("rows-not-as-this-module-writes-them",
     _case_rows_not_as_this_module_writes_them, "rows-ordered"),
    ("marked-held-and-not-held", _case_marked_held_and_not_held, "in-corpus-agrees"),
    ("marked-not-held-and-held", _case_marked_not_held_and_held, "in-corpus-agrees"),
    ("held-rule-the-catalog-does-not-name",
     _case_held_rule_the_catalog_does_not_name, "catalog-knows-the-rule"),
    ("nothing-to-check-the-worklist-against",
     _case_nothing_to_check_the_worklist_against, "corpus-absent"),
    ("index-page-whose-layout-moved", _case_index_page_whose_layout_moved,
     "index-layout"),
    ("bulletin-the-index-does-not-list", _case_bulletin_the_index_does_not_list,
     "bulletin-not-listed"),
    ("bulletin-page-without-its-filings-table",
     _case_bulletin_page_without_its_filings_table, "filing-table"),
    ("filing-that-could-not-be-read", _case_filing_that_could_not_be_read,
     "filing-unreadable"),
    ("most-of-the-month-unreadable", _case_most_of_the_month_unreadable,
     "filing-systemic"),
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
    got = sorted(actions_in(_FILINGS["100"]))
    if got != [("999-001-0010", "amend")]:
        print(f"FAIL a-prose-citation-is-not-a-change: {got!r}", file=sys.stderr)
        return 1
    return 0


def _proof_a_compound_verb_reports_every_action_it_names() -> int:
    """`AMEND & RENUMBER: 999-005-0010` is two things happening to one rule, and a
    consumer acts differently on each — an amendment is a text refresh, a renumber
    moves where the text lives. Reporting only the first verb would lose the move."""
    got = sorted(actions_in("AMEND & RENUMBER: 999-005-0010\n"))
    if got != [("999-005-0010", "amend"), ("999-005-0010", "renumber")]:
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
        got = sorted(actions_in(f"{action.upper()}: 999-006-0010\n"))
        if got != [("999-006-0010", action)]:
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
    rows = filing_rows(_bulletin_page(("100", "100")))
    reading = read_bulletin(rows, _read_filing, _HELD)
    bad = 0
    if reading.rows != [{"number": "999-001-0010", "action": "amend",
                         "in_corpus": True}]:
        print(f"FAIL one-action-taken-twice-is-written-once: {reading.rows!r}",
              file=sys.stderr)
        bad += 1
    if reading.problems:
        print(f"FAIL a-duplicate-filing-is-not-a-filing-that-named-nothing: "
              f"{reading.problems!r}", file=sys.stderr)
        bad += 1
    return bad


_PROOFS = [
    _proof_a_clean_month_produces_no_finding,
    _proof_what_the_reader_writes_is_what_the_check_accepts,
    _proof_a_prose_citation_is_not_a_change,
    _proof_a_compound_verb_reports_every_action_it_names,
    _proof_every_named_action_is_one_the_reader_parses,
    _proof_one_action_taken_twice_is_written_once,
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
    print(f"{len(_CASES)} violation(s) demonstrated failing, {proofs} reader proof(s) "
          f"held" if not bad else f"{bad} rule(s) did not fire")
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

    rows = filing_rows(fetch(url).decode("utf-8", "replace"))
    print(f"{len(rows)} operative filings (permanent/temporary/minor-correction)")

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

    reading = read_bulletin(rows, read_filing, held_rules(), progress)
    _report(reading.problems)
    n_in = sum(1 for r in reading.rows if r["in_corpus"])
    unreadable = sum(1 for p in reading.problems if p.rule == "filing-unreadable")
    # A SYSTEMIC FAILURE MAY NOT OVERWRITE THE LAST WORKLIST THAT WAS WHOLE. The rows
    # this run holds are missing an unknown share of the month, and a short worklist is
    # indistinguishable from a quiet one — writing it would leave `--check` auditing the
    # damage and printing a clean census over it, which is "could not check" served as
    # "is not there" by the very file that exists to keep those apart.
    if not month_is_whole(reading):
        print(f"\nREFUSED to write {WORKLIST.relative_to(REPO_ROOT)}: {unreadable} of "
              f"{len(rows)} filings could not be read, so these {len(reading.rows)} rule "
              f"action(s) are an unknown fraction of the month. The committed worklist "
              f"is left as it is; re-run when the source is healthy.", file=sys.stderr)
        return 1
    WORKLIST.write_text(render_worklist(month, year, rsn, url,
                                        date.today().isoformat(), reading.rows))
    print(f"\nwrote {WORKLIST.relative_to(REPO_ROOT)}: {len(reading.rows)} rule "
          f"action(s) from {len(rows) - unreadable} filing(s); {n_in} affect rules held "
          f"in this corpus; {unreadable} filing fetch/parse failure(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
