#!/usr/bin/env python3
"""Group-scoped upstream update checker — the engine behind the /check-updates skill.

Groups are data (_meta/sources/<group>.yml); this tool is generic and never needs
changing when knowledge bodies or agencies are added. Output is deliberately terse
(silent on unchanged sources) so an agent can drive it cheaply.

  --due                 no-network report: which groups are due per their recheck cadence
                        and, for a group declaring `recheck_phase` (#198), per when its own
                        cycle is anchored to land rather than raw days since last_checked
  --group NAME ...      check specific group(s)
  --all                 check every group
  --refresh             with a check: re-fetch changed docs and regenerate their
                        '## Full text' (ingest_lib.refresh_document); rebuild changed
                        listing snapshots. Never auto-ingests listing ADDED rows
                        (intake gate #1: a human vets the list first).
  --check               CI: the cadence a group may declare is declared ONCE, in CADENCES
                        below, and the schema's `recheck` node is derived from it. Fails
                        when the committed node is not the one that table renders, or when
                        a group declares a cadence nobody declared, or a phase (#198) on a
                        cadence CADENCES did not mark phase-capable. Also validates every
                        group in _meta/sources/ against source-group.schema.json (#199) and
                        prints the count checked, failing if jsonschema could not be
                        imported rather than reporting a silent zero as a clean pass.
  --sync-schema         rewrite the schema's `recheck` node from CADENCES
  --selftest            CI: every rule --check enforces, demonstrated failing, plus the
                        behaviours no rule can state (what a report does with data it
                        cannot read; where this cadence lands against the ballot cycle;
                        that a phased group registered mid-cycle lands on its own cycle
                        rather than staying mid-cycle forever, #198)
"""
import argparse
import json
import sys
from collections import namedtuple
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from repo_lib import (REPO_ROOT, SCHEMA_DIR, SOURCES_DIR, MissingContentDir, content_files,
                      content_hash, parse_frontmatter, source_groups)

SCHEMA = SCHEMA_DIR / "source-group.schema.json"

# `phase_capable` defaults False so every existing 2-arg `Cadence(days, note)` call site —
# fixtures included — keeps meaning what it always meant; a cadence opts IN to phase.
Cadence = namedtuple("Cadence", "days note phase_capable", defaults=(False,))

# One contract violation: which rule, which group (or file), and what is wrong with it. A
# type rather than a formatted string, so --selftest asserts on the RULE that fired instead
# of pattern-matching prose (catalog_agencies.py's Failure, same reason).
Failure = namedtuple("Failure", "rule row detail")

CADENCES = {
    "weekly": Cadence(7, "a listing that moves within a week"),
    "monthly": Cadence(30, "the Oregon Bulletin, first business day of each month"),
    "quarterly": Cadence(90, "a listing that moves a few times a year"),
    # phase_capable=True (#198): TWO groups can both be `biennial` and land on opposite
    # halves of the cycle — the ORS edition follows the odd-year session, but nothing about
    # the WORD `biennial` says which two-year-old date a given group's own edition landed
    # on. `recheck_phase` lets a group state that anchor instead of drifting from whatever
    # day it happened to be registered (see `_phase_aligned_due_date`).
    "biennial": Cadence(730, "the ORS edition, published after each ODD-YEAR "
                             "legislative session", phase_capable=True),
    "on_review_date": Cadence(365, "a document carrying its own printed review date, with "
                                   "the year as a backstop re-crawl rather than a signal"),
    # THE BALLOT-MEASURE CYCLE, and NOT a second spelling of `biennial` (ADR 0005). Both
    # cadences are two years long and they are two years apart in PHASE: the ORS edition
    # follows the ODD-year legislative session, while the Oregon Constitution is amended by
    # measures decided at the general election — the Tuesday after the first Monday in
    # November of EVEN-numbered years.
    #
    # 765 DAYS = 735 + 30, and each half is a fact rather than a round number. 735 is the
    # LONGEST span between two consecutive general elections (they run 728 or 735 days
    # apart through 2100, because the first-Tuesday-after-the-first-Monday rule slides
    # election day between November 2 and 8); taking the longest means a due date that
    # never lands before the election. The 30 is the margin in which the vote is canvassed
    # and an approved amendment takes effect — due on election night finds nothing to read.
    #
    # MEASURED over every anchor in the month after an election and every pair of elections
    # to 2100 (--selftest): this cadence comes due 30-67 days after the next election;
    # `biennial` comes due between 5 days BEFORE it and 32 days after. That is what refuses
    # the reuse — not that 730 never lands well, but that from the natural anchor (a check
    # made promptly after an election) it lands on the wrong side, and one value cannot
    # mean both.
    #
    # WHAT THIS INTERVAL CANNOT DO is hold its phase. `recheck` counts days since the last
    # check and `check_group()` re-anchors `last_checked` on the day the check RAN, so the
    # window above is a ONE-HOP property: each cycle the due date lands 30-37 days later
    # than the last (765 minus the 728-735 the cycle actually is). The walk is FORWARD by
    # construction, and that is the choice: a cadence shorter than the cycle walks backward
    # into an absorbing state — due before the election, finds nothing, re-anchors earlier,
    # never sees an amendment again — while walking late still catches them and lets an
    # out-of-phase group drift toward the window.
    #
    # #198 DECIDED: this stays a NAMED CADENCE, phase_capable left False (the default),
    # rather than becoming `biennial` + a `recheck_phase` anchor. Two reasons, not one. The
    # 765-day interval above is not a phase overlaid on `biennial`'s 730 — it is a
    # DIFFERENT number, measured (--selftest) as the one that keeps this cadence from ever
    # landing before an election, which `biennial` cannot do from the natural anchor;
    # collapsing the two into one interval plus a phase would need the phase to also change
    # the interval, which is a different mechanism from the one this ticket adds. And #198
    # is explicit that "any corpus's actual cadence values" is out of scope — the
    # constitution group already declares this cadence today, so rewriting it to
    # `biennial` + phase would be an in-scope tool change forcing an out-of-scope data
    # migration. The walk-forward drift this cadence still has is therefore unresolved by
    # this ticket, same as before; only groups declaring `biennial` gained the anchor.
    "even_year_general_election": Cadence(765, "constitutional amendments referred to "
                                               "voters and decided at the general "
                                               "election, November of EVEN-numbered "
                                               "years"),
}

# The cadence ADR 0005's source group takes, named once so the measurements in --selftest
# refer to the decision rather than repeat a string. Nothing else reads it: no gate is
# special-cased for this cadence, and the checker stays generic over whatever groups declare.
BALLOT_CADENCE = "even_year_general_election"


def days_since(iso: str) -> int:
    return (date.today() - datetime.strptime(iso, "%Y-%m-%d").date()).days


# THE STATES THAT ARE NEITHER DUE NOR OK, which may never be collapsed into those two: a
# group whose cadence nobody declared, or whose last check nothing can date, is a group
# nothing can say anything about. CONTEXT.md's overriding rule: "could not check" is never
# reported as "is not there". Both values come from _meta/sources/<group>.yml, which is data
# a human writes, so both are REPORTED against the group rather than raised out of it.
UNKNOWN_CADENCE = "UNKNOWN CADENCE"
UNREADABLE_DATE = "UNREADABLE DATE"
# #198: the two ways a declared `recheck_phase` can be a mistake in the group's own data,
# reported rather than raised or silently applied — same discipline as the two states above.
UNREADABLE_PHASE = "UNREADABLE PHASE"
PHASE_NOT_ADMITTED = "PHASE NOT ADMITTED"
UNREADABLE = (UNKNOWN_CADENCE, UNREADABLE_DATE, UNREADABLE_PHASE, PHASE_NOT_ADMITTED)


def _phase_aligned_due_date(anchor: date, days: int, checked: date) -> date:
    """#198: the next date on or after `checked` that lands on the ANCHOR's own cycle —
    `anchor` plus a whole number of `days`-long intervals — rather than `days` after
    whatever day `checked` happened to be. A group registered mid-cycle (`checked` before
    `anchor`) lands on `anchor` itself; one already past a cycle boundary lands on the next
    one strictly after `checked`, so a group just checked is never immediately due again."""
    k = (checked - anchor).days // days + 1
    return anchor + timedelta(days=k * days)


def due_state(g, cadences=None):
    """(state, detail) for one group: is it due for a recheck, and on what reading.

    A cadence nobody declared, and a `last_checked` nothing can read, are REPORTED here
    rather than raised: a KeyError out of a dict lookup or a ValueError out of strptime
    names the dict or the format string instead of the group, and takes every other
    group's reading down with it. #198 adds the same discipline for `recheck_phase`: a
    group that declares none is untouched (the pre-#198 formula, unchanged); one that
    declares an anchor is scheduled against it via `_phase_aligned_due_date` instead of
    `age >= cadence.days`, unless the cadence never opted into phase (`phase_capable`) or
    the anchor itself cannot be read, either of which is reported rather than applied."""
    cadences = CADENCES if cadences is None else cadences
    cadence = cadences.get(g.get("recheck"))
    if cadence is None:
        return (UNKNOWN_CADENCE,
                f"recheck {g.get('recheck')!r} is not one of "
                f"{', '.join(sorted(cadences))}; cannot say whether this group is due")
    try:
        checked = datetime.strptime(g["last_checked"], "%Y-%m-%d").date()
    except (KeyError, TypeError, ValueError):
        return (UNREADABLE_DATE,
                f"last_checked {g.get('last_checked')!r} is not a YYYY-MM-DD date; "
                f"cannot say whether this group is due")
    # Parsed ONCE, here: `checked` (the date) feeds both the plain-age reading below and
    # the phase-aligned scheduling further down, so this field's format string is written
    # in exactly one place rather than twice — `days_since()` duplicated this same parse
    # until #198 gave the phase branch its own second copy to compute `checked` from.
    age = (date.today() - checked).days
    phase = g.get("recheck_phase")
    if phase is None:
        return ("DUE" if age >= cadence.days else "ok",
                f"last checked {age}d ago; cadence {g['recheck']}")
    if not cadence.phase_capable:
        return (PHASE_NOT_ADMITTED,
                f"recheck_phase {phase!r} declared but recheck {g['recheck']!r} "
                f"({cadence.days}d) admits no phase; cannot say whether this group is due")
    try:
        anchor = datetime.strptime(phase, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return (UNREADABLE_PHASE,
                f"recheck_phase {phase!r} is not a YYYY-MM-DD date; cannot say whether "
                f"this group is due")
    due_on = _phase_aligned_due_date(anchor, cadence.days, checked)
    return ("DUE" if date.today() >= due_on else "ok",
            f"last checked {age}d ago; cadence {g['recheck']} phased to {phase}, "
            f"next due {due_on.isoformat()}")


def report_due() -> int:
    """Print every group's due-state; return how many could not be read at all."""
    unreadable = 0
    for gpath, g in source_groups():
        state, detail = due_state(g)
        unreadable += state in UNREADABLE
        print(f"{g['group']}: {state} ({detail}; "
              f"{len(g['sources'])} source(s); signal: {g['upstream_signal']})")
    return unreadable


_DOC_PATHS_BY_ID_CACHE = {}


def doc_paths_by_id(dirs=None):
    """`snapshot_id`/`id` -> the document path(s) that carry it, across the corpus (or,
    with `dirs`, across only the content directories named -- see `_CHAPTER_HTML_DIRS`
    below for the one caller that scopes it, and why that scope is provably complete for
    what it asks).

    MEMOIZED per `dirs`, process-lifetime. Every caller in this file wants the answer for
    the SAME corpus: `check_group()` (below) runs once per source group under `--all` /
    `--refresh` -- up to 19 times in one process, one per file under `_meta/sources/` --
    and `_chapter_html_id_accounting()` runs it under `--check`. Measured before this
    cache existed: ~74-85s PER CALL (content_files() walks and parse_frontmatter() reads
    every document in scope), so a 19-group `--all` run paid to rebuild an identical map
    19 times, and `--check` alone was measured within ~1.5s of a bare single call -- the
    whole cost of `--check` is this one walk. `check_group()` (below) DOES mutate content
    documents mid-run, via `ingest_lib.refresh_document()` -- but never in a way this cache
    would need to see: `refresh_document()` rewrites `retrieved`, `source_sha256`,
    `conversion_notes` and `## Full text` in place on the SAME path it was given, and
    never touches `id` or `snapshot_id` (the two keys this map is built from) or adds or
    removes a document (a refreshed snapshot lands under `_meta/snapshots/`, outside
    CONTENT_DIRS entirely). So no call in this process, at any point, could see a set of
    id-to-path mappings a fresh walk would disagree with -- caching this is
    correctness-preserving, not an approximation."""
    key = tuple(sorted(dirs)) if dirs is not None else None
    if key not in _DOC_PATHS_BY_ID_CACHE:
        m = {}
        for p in content_files(dirs=dirs):
            fm, _ = parse_frontmatter(p)
            m.setdefault(fm.get("snapshot_id") or fm["id"], []).append(p)
            m.setdefault(fm["id"], []).append(p)
        _DOC_PATHS_BY_ID_CACHE[key] = m
    return _DOC_PATHS_BY_ID_CACHE[key]


def check_group(gpath, g, refresh, today):
    from ingest_lib import fetch
    changed = []
    # 1) listing diff for sp-listing groups
    if g["kind"] == "sp-listing":
        from sp_listing import check_sp_listing
        snap_name = g["listing_snapshot"].rsplit("/", 1)[-1]
        try:
            diffs = check_sp_listing(snap_name)
        except Exception as e:
            print(f"{g['group']}: LISTING CHECK FAILED ({e})")
            diffs = None
        if diffs:
            print(f"{g['group']}: LISTING CHANGED — {len(diffs)} difference(s):")
            for d in diffs[:25]:
                print(f"  {d}")
            changed.append("listing")
            if refresh:
                print(f"  (listing snapshot NOT auto-rebuilt; ADDED rows require intake "
                      f"gate #1 — see the check-updates skill)")
    # 2) content hash per source
    docs = doc_paths_by_id()
    for s in g["sources"]:
        path_url = s["url"].lower().split("?")[0]
        ext = path_url.rsplit(".", 1)[-1] if "." in path_url.rsplit("/", 1)[-1] else "html"
        fmt = ext if ext in ("pdf", "xls", "xlsx", "docx", "xml") else "html"
        try:
            new = content_hash(fetch(s["url"]), fmt)
        except Exception as e:
            print(f"{g['group']}/{s['id']}: FETCH FAILED ({e})")
            continue
        if new != s["sha256"]:
            print(f"{g['group']}/{s['id']}: CHANGED {s['sha256'][:10]}… -> {new[:10]}…")
            changed.append(s["id"])
            if refresh:
                from ingest_lib import refresh_document
                for p in sorted(set(docs.get(s["id"], []))):
                    res = refresh_document(p, today)
                    print(f"  refresh {p.relative_to(REPO_ROOT)}: {res}")
                s["sha256"] = new
    # 3) bump last_checked
    g["last_checked"] = today
    for s in g["sources"]:
        s["last_checked"] = today
    gpath.write_text(yaml.safe_dump(g, sort_keys=False, allow_unicode=True, width=110))
    return changed


# --------------------------------------------------------------- the cadence gate
#
# ONE DECLARATION, ONE DERIVATION. A cadence used to be written twice — this file's table
# and the schema's `recheck` enum — with nothing gating their agreement, which is the shape
# of #165's CURATED_KEYS: two hand-maintained lists of one fact, agreeing today and kept
# that way by nobody. The schema's node is now GENERATED from CADENCES (`--sync-schema`)
# and `--check` fails when the committed one has drifted, so a cadence cannot exist on one
# side only. The generation is one way round rather than the other because the interval is
# the half a JSON Schema has no keyword for: `enum` can hold the names and nothing standard
# can hold "765 days", so the table that knows both is the one that can produce the other.
def schema_node(schema=None):
    """The committed schema's `recheck` node."""
    schema = json.loads(SCHEMA.read_text()) if schema is None else schema
    return schema["properties"]["recheck"]


def recheck_node(cadences=None):
    """The `recheck` node the declaration means: which values are legal, and — printed
    where a curator reads them — what interval each one is."""
    cadences = CADENCES if cadences is None else cadences
    means = "; ".join(f"{n} = {c.days} days, {c.note}" for n, c in sorted(cadences.items()))
    return {
        "description": "How often this group is rechecked, and what each value means: "
                       + means + ". GENERATED from CADENCES in src/check_updates.py by "
                       "`python3 src/check_updates.py --sync-schema`, and gated by "
                       "`--check`: a value here that the checker declares no interval for "
                       "is a group nothing can report a due-state for.",
        "enum": sorted(cadences),
    }


def sync_schema(path=None) -> int:
    """Write the derived `recheck` node into the schema, leaving the rest of the file
    byte-for-byte alone (only this one node is generated; every other description in it is
    hand-written, which is why this splices text rather than re-dumping the document).

    THE SPLICE IS CHECKED BEFORE IT IS WRITTEN. Finding the node by text means finding the
    WRONG one is possible — a `"recheck": ` inside some other value would do it — and a
    mis-splice would corrupt a schema nobody validates against (#199) rather than failing.
    So the result is re-parsed and compared with the document this was supposed to produce,
    and anything else is refused with the file untouched."""
    path = SCHEMA if path is None else path
    text = path.read_text()
    key = '"recheck": '
    start = text.find(key)
    if start < 0:
        print(f"{path}: no `recheck` node to write", file=sys.stderr)
        return 1
    indent = " " * (start - text.rfind("\n", 0, start) - 1)
    open_brace = text.find("{", start + len(key))
    # BRACES INSIDE STRINGS ARE TEXT. A cadence note carrying a `}` is written into this
    # node's description, so a scan that counted it as structure would close the node early
    # on the NEXT run — idempotency is where that bites, not the write that introduced it.
    depth, end, in_string, escaped = 0, None, False, False
    for i in range(max(open_brace, 0), len(text)):
        c = text[i]
        if in_string:
            in_string = not (c == '"' and not escaped)
            escaped = c == "\\" and not escaped
            continue
        if c == '"':
            in_string, escaped = True, False
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if open_brace < 0 or end is None:
        print(f"{path}: the `recheck` node is not a closed object", file=sys.stderr)
        return 1
    rendered = json.dumps(recheck_node(), indent=2).replace("\n", "\n" + indent)
    new = text[:start] + key + rendered + text[end:]
    try:
        wanted = json.loads(text)
        wanted["properties"]["recheck"] = recheck_node()
        spliced = json.loads(new)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"{path}: refusing to write — the splice does not parse ({e})", file=sys.stderr)
        return 1
    if spliced != wanted:
        print(f"{path}: refusing to write — the splice changed something other than the "
              f"`recheck` node", file=sys.stderr)
        return 1
    if new == text:
        print(f"{path.name}: already current")
        return 0
    path.write_text(new)
    print(f"{path.name}: recheck node written from {len(CADENCES)} declared cadence(s)")
    return 0


def check_cadences(cadences=None, schema=None, groups=None):
    """Report every way the cadence declaration and its readers disagree."""
    cadences = CADENCES if cadences is None else cadences
    failures = []
    node = schema_node(schema)
    admitted = list(node.get("enum", []))
    for name in sorted(set(cadences) - set(admitted)):
        failures.append(Failure("schema-enum", name,
                                "the checker knows this cadence and the schema does not "
                                "admit it, so no group may declare it"))
    for name in sorted(set(admitted) - set(cadences)):
        failures.append(Failure("schema-enum", name,
                                "the schema admits this cadence and the checker declares "
                                "no interval for it, so a group declaring it cannot be "
                                "reported as due or not due"))
    want = recheck_node(cadences)
    if node.get("description") != want["description"]:
        failures.append(Failure("schema-description", SCHEMA.name,
                                "the schema's `recheck` description is not the one "
                                "CADENCES renders; run --sync-schema"))
    # AND THE WHOLE NODE, because the two rules above compare what a cadence IS and the
    # claim being gated is that the committed node is what the declaration PRODUCES. An
    # enum in another order or a keyword added by hand agrees on every value and is still
    # a file --sync-schema would rewrite — which is a derived file nothing holds to its
    # derivation, i.e. the hand-maintained second copy again. Reported only when the rules
    # above did not already say what is wrong.
    if node != want and not failures:
        failures.append(Failure("schema-node", SCHEMA.name,
                                "the committed `recheck` node is not the one CADENCES "
                                "renders (enum order, or a keyword nothing declares); "
                                "run --sync-schema"))
    # A GROUP IS DATA A HUMAN WRITES, so a cadence nobody declared is reported against the
    # file that declares it. ALLOWLIST: a value is legal because it appears in CADENCES,
    # never because it is not on a list of known-bad ones.
    groups = source_groups() if groups is None else groups
    for gpath, g in groups:
        name = g.get("recheck")
        if name not in cadences:
            failures.append(Failure("group-cadence", g.get("group", gpath.name),
                                    f"declares recheck {name!r}, which is not one of "
                                    f"{', '.join(sorted(cadences))}"))
        # #198: PHASE IS OPT-IN PER CADENCE, not automatic — `Cadence.phase_capable` is the
        # table CADENCES already is, so this reads it rather than repeating the decision.
        # Only checked when `name` resolved above; an unknown cadence is already reported.
        elif g.get("recheck_phase") is not None and not cadences[name].phase_capable:
            failures.append(Failure("group-phase", g.get("group", gpath.name),
                                    f"declares recheck_phase {g['recheck_phase']!r} but "
                                    f"recheck {name!r} ({cadences[name].days}d) admits no "
                                    f"phase — CADENCES marks which cadences do"))
    return failures


def cadence_census(groups=None):
    """How many groups declare each cadence, ZEROES INCLUDED — a declared cadence nothing
    uses yet is a fact to report on every run, not an absence to stop noticing."""
    counts = dict.fromkeys(sorted(CADENCES), 0)
    for _, g in (source_groups() if groups is None else groups):
        # `.get`, and a key this table does not have: an undeclared cadence is what
        # `group-cadence` reports, and the census must be able to count the thing the
        # gate is reporting rather than raise beside it.
        counts[g.get("recheck")] = counts.get(g.get("recheck"), 0) + 1
    return ", ".join(f"{n}={c}" for n, c in counts.items())


def check_schema(groups=None):
    """(failures, checked) — every group in `groups` (default: every file in
    `_meta/sources/`) validated against `_meta/schema/source-group.schema.json` (#199).

    `_meta/corpus.yml`'s `extra_schema_checks` already runs this same schema over the same
    glob in CI (`corpus-validate-frontmatter`'s `_check_corpus_config`, unconditional even
    on `--changed` runs with nothing changed) — so this is not the first thing to validate
    these 19 files, and every one already passes it. What it adds: a fast, local, printed-
    count companion in the shape this repo already gives every other domain rule
    (`--check`/`--selftest` beside a corpus-toolkit config check), and a single
    implementation `seed_oar_watch.py` now calls instead of running its own copy.
    Returning the count alongside the failures, rather than failures alone, is deliberate:
    a run that validated zero groups because `jsonschema` was not importable must be able
    to say so — printed as `0 of 19`, not silently indistinguishable from `19 of 19`
    groups that happened to pass.

    Every keyword a group violates is reported (`iter_errors`, not `validate`, which stops
    at the first), and the row is the FILE (`gpath.name`), never the group's own `group`
    field — a group whose `group` key is itself what is wrong should still be reported
    against something a curator can open, and `group` is data a human wrote, not an
    identity this function should have to trust to report on it.

    A schema that fails to parse, or is not itself a valid schema, is reported as ONE
    `group-schema` failure with `checked=0` rather than raised. `seed_oar_watch.findings()`
    calls this function with no try/except of its own (#199) — a traceback here would
    surface exactly where that ticket's brief says a malformed input must not."""
    try:
        import jsonschema
    except ImportError:
        return [], 0
    groups = list(source_groups() if groups is None else groups)
    try:
        schema = json.loads(SCHEMA.read_text())
        validator = jsonschema.Draft202012Validator(schema)
        validator.check_schema(schema)
    except (OSError, json.JSONDecodeError, jsonschema.exceptions.SchemaError) as e:
        return [Failure("group-schema", SCHEMA.name,
                        f"{SCHEMA.name} could not be used to validate: "
                        f"{type(e).__name__}: {e}")], 0
    failures = []
    for gpath, g in groups:
        for e in validator.iter_errors(g):
            failures.append(Failure("group-schema", gpath.name, e.message))
    return failures, len(groups)


# --------------------------------------------------------- #287: chapter-html id accounting
#
# `source-group.schema.json` (`check_schema` above) validates SHAPE only: a `sources[].id`
# is a string, full stop. It cannot say whether a `chapter-html` group's declared id
# corresponds to anything real -- a `chapter-html` group's id is a SHARED SNAPSHOT id
# (`ingest_ors.py`'s `snap_id = f"ors-chapter-{ch.lower()}"`, or the constitution's single
# `oregon-constitution`), and every document sliced out of that snapshot carries it as its
# `snapshot_id`. This closes HALF of that gap: an id must be either the `snapshot_id`/`id`
# of some document this corpus actually holds, or -- `ors` only -- a chapter the ORS catalog
# itself records as carrying zero sections.
#
# THE OTHER HALF IS STILL OPEN, and still #287: this only walks source-id -> document. #287
# asks for an id that is "EXACTLY the snapshot ids its member documents declare" -- a
# bidirectional property -- and a document carrying a chapter-shaped `snapshot_id` that NO
# group declares (upstream adds a chapter and nobody updates `ors.yml`) is unwatched by
# anything here. Left undone rather than folded into this pass on purpose: closing it needs
# a real design call this comment cannot make for a future reader by itself -- which
# documents in the WHOLE corpus count as "a chapter-html group's member" for this purpose
# (a `snapshot_id` shape match risks a false positive on an unrelated future id that happens
# to look like one), and that determination is exactly the kind of judgment AGENTS.md asks
# be made deliberately, not folded into an unrelated pass as a side effect. Measured on the
# corpus committed alongside this change: no live violation today (548 declared, 532 of them
# document-backed, matching exactly the 532 chapter-shaped `snapshot_id`s the corpus holds)
# -- latent, not live, which is why #287 stays open rather than being reopened as new.
#
# THAT SECOND BRANCH IS NOT DECORATION. Measured against the corpus committed alongside this
# change (2026-08-29): of `ors.yml`'s 547 source ids, 16 name no document at all --
# `ors-chapter-156`, `-181`, `-285`, `-286`, `-351`, `-419`, `-445`, `-472`, `-475b`, `-483`,
# `-487`, `-579`, `-606`, `-657a`, `-722`, `-761`. Every one of those 16 IS a real chapter
# in `_meta/catalog/ors.yml`, and every one carries `sections: []` -- the Oregon
# Legislature's own "(Former Provisions)" chapters, repealed down to nothing but still
# fetched and hashed here because an amendment REVIVING one would move the hash and this
# corpus wants to notice. `ingest_ors.py` never writes a document for a chapter with no
# sections, so these 16 ids legitimately name no document, by design, not by drift -- a
# strict "every id equals some document's snapshot_id" gate would come up red on correct,
# unchanged data on day one, which is worse than not gating at all (a gate that cries wolf
# on its own committed corpus gets silenced, not trusted). The `constitution` group's own
# single id (`oregon-constitution`) needs no such exemption: it names the one document
# ADR 0005 mirrors the whole page into, with no per-chapter absence possible.
#
# THE EXEMPTION IS SCOPED BY GROUP NAME, not granted to every chapter-html group -- a
# THIRD such group, were one ever added, would need either every source id to have a
# document or its own accounting branch here, the same way `check_group()` already
# special-cases `kind == "sp-listing"` by importing `sp_listing` rather than pretending
# every kind reduces to the same shape.

def _ors_empty_chapter_ids(catalog=None) -> set:
    """Chapter-html source ids `_meta/catalog/ors.yml` itself records as carrying NO
    sections -- read from the ONE place that decision is recorded (`ingest_ors.py` writes
    `sections: []` there when a chapter's page prints no live section), not re-derived
    here from the absence alone, because an absence with no recorded reason is exactly the
    'could not check' AGENTS.md forbids reporting as 'is not there'. `catalog=None` reads
    the committed file; a dict lets `--selftest` fire this against a synthetic catalog
    without touching the real one. A catalog that cannot be read or parsed grants no
    exemptions at all (empty set) rather than being silently skipped as if it had none to
    give -- the caller still reports every id this leaves unaccounted for."""
    if catalog is None:
        try:
            catalog = yaml.safe_load(
                (REPO_ROOT / "_meta/catalog/ors.yml").read_text())
        except (OSError, yaml.YAMLError):
            return set()
    return {f"ors-chapter-{c['chapter'].lower()}"
            for c in catalog.get("chapters", []) if not c.get("sections")}


# THE WALK doc_paths_by_id() DOES NOT NEED. #287's rule tests 548 chapter-html source ids
# for membership; building the FULL id index first (81,921 documents, 82,453 id keys once
# each document's `id` and, where distinct, its `snapshot_id` are both indexed -- ~74-85s
# of disk and YAML parsing) to answer that is doing 150x the reading this rule needs. But
# scoping the walk is only safe where it is PROVEN safe, not assumed: `ingest_ors.py`
# writes every ORS chapter slice into statutes/ and nowhere else, `ingest_constitution.py`
# (ADR 0005) writes the constitution's one document into constitution/ and nowhere else,
# and `ors` and `constitution` are the only two `chapter-html` groups this corpus declares today
# (`grep -l 'kind: chapter-html' _meta/sources/*.yml`, verified 2026-09-02) -- so a
# snapshot_id or id any chapter-html group's source could match was never going to be
# found under rules/, agencies/, executive-orders/ or external-references/, which together
# hold more than half this corpus's documents. `_chapter_html_scope()` checks that
# assumption at runtime rather than baking it in silently: every chapter-html group
# actually present must be one of the two names this scope was measured against, or the
# scope is refused and the caller walks the whole corpus instead (slower, never wrong) --
# the same "scoped by name, not granted to every group of this kind" discipline
# `_ors_empty_chapter_ids`'s own exemption already uses one function up.
_CHAPTER_HTML_DIRS = ("statutes", "constitution")
_CHAPTER_HTML_GROUP_NAMES = {"ors", "constitution"}


def _chapter_html_scope(groups):
    """`_CHAPTER_HTML_DIRS` if every `chapter-html` group in `groups` is one that scope
    was proven against, else `None` (walk the whole corpus) -- a chapter-html group under
    a name this list does not know is not assumed to write into the same two directories,
    so it gets the safe, unscoped answer rather than a silently incomplete one."""
    names = {g.get("group") for _, g in groups if g.get("kind") == "chapter-html"}
    return _CHAPTER_HTML_DIRS if names and names <= _CHAPTER_HTML_GROUP_NAMES else None


_ChapterHtmlAccounting = namedtuple(
    "_ChapterHtmlAccounting", "verified exempt failures content_dir_error")


def _chapter_html_id_accounting(groups=None, doc_ids=None, ors_empty=None):
    """The full per-id classification #287's rule is built on -- for every `chapter-html`
    group's declared source id, which of three states it is in: VERIFIED (the
    `snapshot_id`, or lacking one the `id`, of a document this corpus holds), EXEMPT
    (the `ors` group only -- a chapter `_ors_empty_chapter_ids` says carries zero
    sections by design), or unaccounted, which becomes a Failure -- #287's whole point.
    `check_chapter_html_ids()` below is a thin wrapper returning only the `failures`
    field, kept for the callers and proofs written against a plain failures list;
    `cmd_check()`'s summary uses the full breakdown so an EXEMPTED id is never printed
    identically to one actually matched to a document (AGENTS.md's overriding rule: a
    skipped check is not a green one).

    `doc_ids=None` reads the live corpus via `doc_paths_by_id()`, which walks
    `content_files()` and can raise `MissingContentDir` -- #316's lesson applied here: a
    missing or unreadable content dir is a corpus this process could not read, never one
    confirmed to hold nothing. Caught and reported as a single named `Failure` (also
    left on `content_dir_error` for a caller that wants the exception itself) rather than
    raised, so `--check` fails toward one honest refusal instead of either a traceback or
    -- worse -- every declared id coming back 'names nothing real', which would misdescribe
    'could not check' as 'is not there'. On that path `verified`/`exempt` are both empty:
    nothing below was accounted for one way or the other, not confirmed absent.

    `doc_ids`/`ors_empty`/`groups` default to reading the live corpus, catalog and
    `_meta/sources/` -- `None` for any of the three reads fresh, a value lets
    `--selftest` fire this against a synthetic corpus without touching the real one."""
    groups = list(source_groups() if groups is None else groups)
    if doc_ids is None:
        try:
            doc_ids = set(doc_paths_by_id(dirs=_chapter_html_scope(groups)))
        except MissingContentDir as e:
            failure = Failure(
                "chapter-html-content-dir-readable", "content_files()",
                f"could not enumerate this corpus's documents to verify chapter-html "
                f"source ids against them ({e}) -- a content directory that cannot be "
                "read is never reported as an id naming nothing real")
            return _ChapterHtmlAccounting(verified=set(), exempt=set(),
                                           failures=[failure], content_dir_error=e)
    ors_empty = _ors_empty_chapter_ids() if ors_empty is None else ors_empty
    verified, exempt, failures = set(), set(), []
    for gpath, g in groups:
        if g.get("kind") != "chapter-html":
            continue
        group_exempt = ors_empty if g.get("group") == "ors" else set()
        for s in g.get("sources", []):
            sid = s.get("id")
            if sid in doc_ids:
                verified.add(sid)
            elif sid in group_exempt:
                exempt.add(sid)
            else:
                extra = (", and the ORS catalog does not record it as a zero-section "
                         "chapter either" if g.get("group") == "ors" else "")
                failures.append(Failure(
                    "chapter-html-id-names-something-real", f"{gpath.name}/{sid}",
                    f"{sid!r} is not the snapshot_id/id of any document in this "
                    f"corpus{extra} -- a chapter-html source id must name something "
                    "real, not just be a well-formed string"))
    return _ChapterHtmlAccounting(verified=verified, exempt=exempt, failures=failures,
                                   content_dir_error=None)


def check_chapter_html_ids(groups=None, doc_ids=None, ors_empty=None) -> list:
    """Failures for every `chapter-html` group's source id that names nothing real
    (#287) -- the content half of what `check_schema` can only check the shape of. An id
    is accounted for when it is the `snapshot_id` (or, lacking one, the `id`) of some
    document this corpus holds, or -- the `ors` group only -- a chapter
    `_ors_empty_chapter_ids` says carries zero sections by design. Every other
    unaccounted id is reported: a `chapter-html` source id that is a well-formed string
    and names nothing real is exactly the gap #287 opened this to close.

    `doc_ids`/`ors_empty`/`groups` default to reading the live corpus, catalog and
    `_meta/sources/` -- `None` for any of the three reads fresh, a value lets
    `--selftest` fire this against a synthetic corpus without touching the real one.
    Thin wrapper over `_chapter_html_id_accounting` -- see it for the full
    verified/exempt/failures breakdown `cmd_check()`'s summary uses."""
    return _chapter_html_id_accounting(groups, doc_ids, ors_empty).failures


def cmd_check() -> int:
    """Report every cadence violation in the committed declaration, schema and groups,
    every group in `_meta/sources/` that does not validate against
    `source-group.schema.json` (#199), and every `chapter-html` source id that names
    nothing real (#287)."""
    groups = list(source_groups())  # read ONCE; every consumer below shares this list
    failures = check_cadences(groups=groups)
    schema_failures, schema_checked = check_schema(groups=groups)
    failures = failures + schema_failures
    chapter_html_groups = [(p, g) for p, g in groups if g.get("kind") == "chapter-html"]
    chapter_html = _chapter_html_id_accounting(groups=chapter_html_groups)
    failures = failures + chapter_html.failures
    for f in failures:
        print(f"  FAIL [{f.rule}] {f.row}: {f.detail}", file=sys.stderr)
    if failures:
        print(f"\n{len(failures)} contract violation(s)", file=sys.stderr)
        return 1
    print(f"{len(CADENCES)} cadence(s) declared, each admitted by "
          f"{SCHEMA.name} with the interval it means")
    print(f"groups per cadence: {cadence_census(groups=groups)}")
    total_groups = len(groups)
    checked_all = schema_checked == total_groups
    print(f"{schema_checked} of {total_groups} source group(s) validated against "
          f"{SCHEMA.name}" + ("" if checked_all else " (jsonschema not installed)"))
    n_chapter_html_ids = sum(len(g.get("sources", [])) for _, g in chapter_html_groups)
    print(f"{len(chapter_html.verified)} of {n_chapter_html_ids} chapter-html source "
          f"id(s) across {len(chapter_html_groups)} group(s) verified to name a real "
          "snapshot")
    if chapter_html.exempt:
        # A skipped check is not a green one (AGENTS.md's overriding rule) -- these ids
        # were never compared against a document, they were excused BY NAME as
        # zero-section "(Former Provisions)" chapters (#287, `_ors_empty_chapter_ids`).
        # Printed identically to a verified id, this line would say "checked and agrees"
        # for something that was "not gated, and here is why" instead.
        print(f"{len(chapter_html.exempt)} more exempt as zero-section chapters, not "
              "gated (the ORS catalog records them as carrying no sections):")
        for sid in sorted(chapter_html.exempt):
            print(f"  {sid}")
    if not checked_all:
        # A run that validated zero groups must not exit the way a run that validated
        # every one of them does — CONTEXT.md's overriding rule, applied to this gate's
        # own exit code rather than only to what it prints: "could not check" is never
        # reported as "is not there". `--due`, twenty lines of this file away, already
        # exits non-zero for the equivalent case (a group nothing can be said about); this
        # is the same choice made for `--check`.
        print(f"\n{SCHEMA.name} was not checked against any group — jsonschema is not "
              f"importable, so this run reported nothing rather than a clean pass",
              file=sys.stderr)
        return 1
    return 0


# ------------------------------------------------------------------------ selftest
# THE PROOF THAT THE GATE ABOVE CAN FAIL. Every rule --check enforces is exercised against
# a synthetic declaration, schema and group built to violate exactly one of them: a check
# nobody has watched fail is not known to work, it is only known to be quiet.
def _schema_fixture(cadences=None):
    """A schema node that agrees with the declaration it is rendered from."""
    return {"properties": {"recheck": recheck_node(cadences)}}


def _proof_a_cadence_missing_from_the_schema_is_reported():
    """A cadence the checker knows and the schema does not. A group may not declare it:
    the schema is what a human reads to learn which values exist, so the interval is
    unreachable and the cadence is one nobody can ask for."""
    declared = dict(CADENCES, invented=Cadence(11, "not in the schema"))
    return "schema-enum", check_cadences(cadences=declared, schema=_schema_fixture(),
                                         groups=[])


def _proof_a_stale_interval_in_the_schema_is_reported():
    """The schema PRINTS each cadence's interval, so a curator reading it learns what
    `quarterly` means without opening the checker. That printing is generated from the
    same table the intervals come from, and a hand-edit of it — or an interval changed on
    one side only — is drift of exactly the kind this gate exists to refuse."""
    stale = _schema_fixture()
    stale["properties"]["recheck"]["description"] = "weekly, monthly, quarterly, biennial"
    return "schema-description", check_cadences(schema=stale, groups=[])


def _proof_a_node_the_declaration_would_rewrite_is_reported():
    """A node that agrees on WHICH cadences are legal and is still not the node CADENCES
    renders — an enum in another order, a keyword someone added by hand. `--sync-schema`
    would rewrite it, so the committed file is not the derivation's output, and a derived
    file that nothing holds to its derivation is back to being a second hand-maintained
    copy."""
    reordered = _schema_fixture()
    node = reordered["properties"]["recheck"]
    node["enum"] = list(reversed(node["enum"]))
    node["type"] = "string"
    return "schema-node", check_cadences(schema=reordered, groups=[])


def _proof_a_cadence_missing_from_the_declaration_is_reported():
    """A cadence the schema admits and the checker does not know. This is the direction
    that ends in a traceback: the schema tells a curator the value is legal, the group
    declares it, and `report_due()` looks up an interval that was never declared."""
    admits = _schema_fixture()
    admits["properties"]["recheck"]["enum"].append("fortnightly")
    return "schema-enum", check_cadences(schema=admits, groups=[])


def _group_fixture(**over):
    """One update group, of the shape _meta/sources/*.yml carries."""
    g = {"group": "oregon-constitution", "title": "Oregon Constitution",
         "kind": "content-hash", "recheck": "biennial", "last_checked": "2026-08-01",
         "upstream_signal": "one page carrying all 18 articles", "sources": []}
    g.update(over)
    return SOURCES_DIR / f"{g['group']}.yml", g


def _proof_a_group_declaring_an_undeclared_cadence_is_reported():
    """A source group is data a human writes, so a cadence nobody declared is a mistake
    in that file and is REPORTED against it. Before this rule it was a KeyError raised
    from inside report_due(), which names the dict and not the group."""
    return "group-cadence", check_cadences(schema=_schema_fixture(),
                                          groups=[_group_fixture(recheck="ballot_measure")])


def _proof_a_group_declaring_a_phase_on_a_cadence_that_admits_none_is_reported():
    """#198: phase is opt-in PER CADENCE (`Cadence.phase_capable`), not automatic — a
    `weekly` listing has no meaningful 'wrong half' of a week to land on, so CADENCES
    admits no phase for it, and a group declaring `recheck_phase` anyway is a mistake in
    that group's own data rather than a value the phase math should silently apply."""
    return "group-phase", check_cadences(schema=_schema_fixture(),
        groups=[_group_fixture(recheck="weekly", recheck_phase="2026-08-01")])


def _proof_a_group_with_an_undeclared_key_is_reported():
    """`_meta/schema/source-group.schema.json` sets `additionalProperties: false` at the
    group level. `check_schema`'s own docstring is where the finding that this schema was
    already enforced corpus-wide lives (#199) -- this proof is only about the LOCAL copy of
    that rule added here.

    IN ITS OWN FIXTURE, and its own `_PROOFS` entry, rather than combined with the
    missing-required-key proof below: a combined fixture list still reports a
    `group-schema` failure with `additionalProperties: false` deleted from the schema
    ENTIRELY, because the other fixture's violation is still there to satisfy
    `any(f.rule == rule for f in failures)`. Proven by experiment while fixing #199: with
    the two violations sharing one list, deleting either half of the schema left this
    selftest passing."""
    _, extra = _group_fixture()
    extra = {**extra, "not_a_declared_key": True}
    failures, _ = check_schema(groups=[(SOURCES_DIR / "extra.yml", extra)])
    return "group-schema", failures


def _proof_a_group_missing_a_required_key_is_reported():
    """The sibling half of the proof above, isolated for the same reason: on its own, so
    dropping `sources` out of the schema's top-level `required` list cannot hide behind
    the OTHER fixture's failure the way the combined proof let it."""
    _, missing = _group_fixture()
    del missing["sources"]
    failures, _ = check_schema(groups=[(SOURCES_DIR / "missing.yml", missing)])
    return "group-schema", failures


def _proof_a_source_entry_missing_a_required_field_is_reported():
    """The schema's `required: [id, url, sha256]` applies to each entry INSIDE `sources`,
    not only to the group's own top-level keys -- #199's Agent Brief names this as its own
    acceptance criterion ('a source entry missing a required field fails, watched
    failing'), distinct from a group-level violation. Nothing before this proof watched it:
    every other fixture in this file either carries `sources: []` or breaks a top-level
    key, so a source ITEM's shape -- `sha256`'s 64-hex pattern, `url`'s `^https?://`
    pattern, or (here) a missing required key -- was never exercised. A source entry with
    no `sha256` is the shape a curator adding a source by hand is likeliest to leave
    incomplete."""
    _, g = _group_fixture(sources=[{"id": "oregon-constitution-full",
                                    "url": "https://example.invalid/full-text"}])
    failures, _ = check_schema(groups=[(SOURCES_DIR / "oregon-constitution.yml", g)])
    return "group-schema", failures


def _proof_a_misdeclared_phase_fails_schema_validation():
    """#198's schema half, gated: `recheck_phase` was added to
    `_meta/schema/source-group.schema.json` alongside the `recheck` node, but nothing else
    in this file ever ran a phased fixture through `check_schema` -- `check_cadences` only
    compares the `recheck` enum node, none of the 19 committed groups declares a phase, and
    `_proof_a_group_declaring_a_phase_on_a_cadence_that_admits_none_is_reported` (above)
    exercises only `check_cadences`'s `group-phase` rule, never the schema. AC #5's own
    text -- 'a group whose phase is misdeclared ... fails' -- names exactly this gap.
    Verified before this fix: deleting `recheck_phase` from a copy of the committed schema,
    or loosening its pattern to `.*`, left `--check` and `--selftest` both green.

    This validates a group with a non-ISO `recheck_phase` ('January 1, 2027') against the
    ACTUAL committed schema -- no `schema=` override, so this reads the same
    module-level `SCHEMA` `--check` reads -- because the pattern is the only thing that can
    catch it; deleting the property instead would ALSO fail this (via
    `additionalProperties: false`), which is why the companion proof below asserts the
    positive case too: a schema drifted back to not admitting the field at all must not be
    confused with one that merely stopped checking its format."""
    _, g = _group_fixture(recheck_phase="January 1, 2027")
    failures, _ = check_schema(groups=[(SOURCES_DIR / "oregon-constitution.yml", g)])
    return "group-schema", failures


def _proof_a_well_formed_phase_validates_against_the_committed_schema():
    """The additive-safety companion to the proof above, and to
    `_proof_a_group_declaring_no_phase_behaves_exactly_as_today`'s no-phase case: a group
    that DOES declare a well-formed `recheck_phase` must validate cleanly against the
    committed schema. Without this, a schema drifted to omit the property entirely would
    reject every phased group under `additionalProperties: false` -- silently breaking the
    feature -- while the proof above still reports a `group-schema` failure on the
    malformed fixture (for the wrong reason: the field is gone, not merely unchecked) and
    would look, at a glance, like nothing had drifted. `checked` must read 1: this proves a
    group was actually validated, not skipped."""
    _, g = _group_fixture(recheck_phase="2026-05-20")
    failures, checked = check_schema(groups=[(SOURCES_DIR / "oregon-constitution.yml", g)])
    if failures or checked != 1:
        print(f"FAIL well-formed recheck_phase should validate cleanly against the "
              f"committed schema; got failures={failures} checked={checked}",
              file=sys.stderr)
        return 1
    return 0


def _proof_check_schema_reports_a_malformed_schema_rather_than_raising():
    """`seed_oar_watch.findings()` calls `check_schema()` with no try/except of its own
    (#199) -- the narrowing that made that safe to do is IN `check_schema`, not at the call
    site, so it is proved here rather than there. Before this rule, a schema file that
    failed to parse, or that was not itself a valid schema, propagated as a traceback: the
    old call site's `except Exception: append a Failure` caught anything, and deduplicating
    the two validators narrowed that to `jsonschema.exceptions.ValidationError` only --
    exactly the 'surfaces as a traceback from whatever reads it next' shape #199's own body
    names as the thing to avoid. `checked` must read 0: a broken schema validated nothing,
    which is a different fact from every group failing it."""
    import tempfile
    global SCHEMA
    bad = json.dumps({"type": "not-a-real-type"})
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "broken.schema.json"
        p.write_text(bad)
        orig = SCHEMA
        SCHEMA = p
        try:
            failures, checked = check_schema(groups=[_group_fixture()])
        except Exception as e:
            print(f"FAIL check_schema on a malformed schema: raised "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
            return 1
        finally:
            SCHEMA = orig
    if checked != 0 or not any(f.rule == "group-schema" for f in failures):
        print(f"FAIL check_schema on a malformed schema: expected a [group-schema] "
              f"failure and checked=0, got failures={failures} checked={checked}",
              file=sys.stderr)
        return 1
    return 0


# ------------------------------------------------------------------------------------- #287

def _proof_a_chapter_html_id_naming_nothing_real_is_reported():
    """A `chapter-html` source id that is neither a document's `snapshot_id`/`id` NOR
    (the group is not `ors`, so the exemption cannot even apply) a zero-section chapter.
    `doc_ids=set()` and `ors_empty=set()` make this fixture fully synthetic -- no real
    corpus document or real ORS catalog entry happens to coincidentally carry the invented
    id, so a pass here would mean the rule never actually compared against anything."""
    _, g = _group_fixture(kind="chapter-html", group="fixture-group",
                          sources=[{"id": "fixture-chapter-999",
                                    "url": "https://example.invalid/x",
                                    "sha256": "0" * 64}])
    failures = check_chapter_html_ids(
        groups=[(SOURCES_DIR / "fixture-group.yml", g)], doc_ids=set(), ors_empty=set())
    return "chapter-html-id-names-something-real", failures


def _proof_chapter_html_id_accounting_is_scoped_correctly():
    """The two ways #287's rule accounts for an id, and the one way its exemption must
    NOT leak -- a rule proved only by its RED case (above) tells you it can fire, not
    that it fires on the RIGHT thing. Three checks: (1) an id matching a document's own
    `snapshot_id` is accounted for and never reported; (2) a zero-section chapter id is
    accounted for under the `ors` group specifically -- the branch measured load-bearing
    against the real corpus (16 of `ors.yml`'s 547 ids, see this module's #287 comment);
    (3) the SAME zero-section exemption set does not excuse a differently-named
    chapter-html group -- the exemption is scoped by group name, not granted to every
    group of this kind."""
    bad = 0
    _, g_doc = _group_fixture(kind="chapter-html", group="fixture-group",
                              sources=[{"id": "fixture-chapter-1",
                                        "url": "https://example.invalid/x",
                                        "sha256": "0" * 64}])
    failures = check_chapter_html_ids(
        groups=[(SOURCES_DIR / "fixture-group.yml", g_doc)],
        doc_ids={"fixture-chapter-1"}, ors_empty=set())
    if failures:
        print(f"FAIL a source id matching a real document's snapshot_id must not be "
              f"reported: {failures}", file=sys.stderr)
        bad += 1

    _, g_ors = _group_fixture(kind="chapter-html", group="ors",
                              sources=[{"id": "ors-chapter-999",
                                        "url": "https://example.invalid/x",
                                        "sha256": "0" * 64}])
    failures = check_chapter_html_ids(
        groups=[(SOURCES_DIR / "ors.yml", g_ors)],
        doc_ids=set(), ors_empty={"ors-chapter-999"})
    if failures:
        print(f"FAIL a zero-section ORS chapter id must be accounted for under the "
              f"`ors` group: {failures}", file=sys.stderr)
        bad += 1

    _, g_other = _group_fixture(kind="chapter-html", group="fixture-group",
                                sources=[{"id": "ors-chapter-999",
                                          "url": "https://example.invalid/x",
                                          "sha256": "0" * 64}])
    failures = check_chapter_html_ids(
        groups=[(SOURCES_DIR / "fixture-group.yml", g_other)],
        doc_ids=set(), ors_empty={"ors-chapter-999"})
    if not failures:
        print("FAIL the ORS zero-section exemption leaked to a differently-named "
              "chapter-html group", file=sys.stderr)
        bad += 1
    return bad


def _proof_ors_empty_chapter_ids_reads_the_catalogs_own_accounting():
    """`_ors_empty_chapter_ids` against a synthetic catalog: a chapter with `sections: []`
    grants its (lowercased) id, a chapter WITH sections grants nothing, and a chapter
    missing the key entirely (never populated) is treated the same as an explicit empty
    list -- `not c.get("sections")` -- rather than raising or silently granting nothing
    for a different, unintended reason. A catalog this cannot read grants NO exemptions
    (empty set), not all of them -- the missing-file/unparsable case must fail toward
    reporting more, never toward excusing more."""
    bad = 0
    catalog = {"chapters": [
        {"chapter": "156", "sections": []},
        {"chapter": "475B", "sections": []},
        {"chapter": "10", "sections": [{"number": "10.010"}]},
        {"chapter": "999"},
    ]}
    got = _ors_empty_chapter_ids(catalog)
    want = {"ors-chapter-156", "ors-chapter-475b", "ors-chapter-999"}
    if got != want:
        print(f"FAIL _ors_empty_chapter_ids over a synthetic catalog: want {want}, "
              f"got {got}", file=sys.stderr)
        bad += 1

    # THE UNREADABLE CASE fails toward reporting MORE, never toward excusing more: a
    # catalog that cannot be read or parsed grants zero exemptions, so every id that
    # would have relied on it is still reported unaccounted, exactly like #316's
    # unreadable-content-dir lesson applied to this one exemption instead of the whole
    # corpus walk.
    global REPO_ROOT
    import tempfile
    orig_root = REPO_ROOT
    with tempfile.TemporaryDirectory() as d:
        REPO_ROOT = Path(d)  # no _meta/catalog/ors.yml under here at all
        try:
            got_missing = _ors_empty_chapter_ids()
        finally:
            REPO_ROOT = orig_root
    if got_missing != set():
        print(f"FAIL an unreadable ORS catalog must grant zero exemptions, got "
              f"{got_missing}", file=sys.stderr)
        bad += 1
    return bad


def _proof_chapter_html_accounting_reports_an_unreadable_content_dir_rather_than_raising():
    """`_chapter_html_id_accounting()` calls `doc_paths_by_id()` when `doc_ids=None`,
    which walks `content_files()` (#316: raises `MissingContentDir` on a missing or
    unreadable declared content dir, never returns an empty corpus silently). Before
    this proof existed, `cmd_check()` had no try/except around that call at all, so an
    unreadable content dir turned `--check` into a traceback -- and worse, a caller that
    DID catch it and substituted an empty `doc_ids` would have every one of 548 real
    source ids come back 'names nothing real', misreporting 'could not check' as
    'confirmed absent' (AGENTS.md's overriding rule, the one this whole file exists to
    serve). Both failure shapes are checked: no raise escapes, and the single reported
    Failure names the refusal rather than 548 fabricated ones."""
    bad = 0
    global doc_paths_by_id
    orig = doc_paths_by_id

    def _raises(dirs=None):
        raise MissingContentDir("rules: declared but not on disk (fixture)")

    doc_paths_by_id = _raises
    try:
        result = _chapter_html_id_accounting(
            groups=[(SOURCES_DIR / "ors.yml",
                     {"kind": "chapter-html", "group": "ors",
                      "sources": [{"id": "ors-chapter-1"}]})])
    except MissingContentDir as e:
        print(f"FAIL _chapter_html_id_accounting raised MissingContentDir instead of "
              f"reporting it: {e}", file=sys.stderr)
        return bad + 1
    finally:
        doc_paths_by_id = orig

    if result.verified or result.exempt:
        print(f"FAIL an unreadable content dir must verify or exempt nothing, got "
              f"verified={result.verified} exempt={result.exempt}", file=sys.stderr)
        bad += 1
    if len(result.failures) != 1:
        print(f"FAIL an unreadable content dir must report exactly ONE refusal, not "
              f"one-per-id: {result.failures}", file=sys.stderr)
        bad += 1
    elif result.failures[0].rule != "chapter-html-content-dir-readable":
        print(f"FAIL the refusal must be distinguishable from 'names nothing real' by "
              f"rule name, got {result.failures[0].rule!r}", file=sys.stderr)
        bad += 1
    if not isinstance(result.content_dir_error, MissingContentDir):
        print(f"FAIL content_dir_error must carry the original exception, got "
              f"{result.content_dir_error!r}", file=sys.stderr)
        bad += 1
    return bad


def _proof_chapter_html_scope_falls_back_to_the_whole_corpus_when_unproven():
    """`_chapter_html_scope()` is the entire safety argument the `statutes`/`constitution`
    walk-scoping optimization rests on -- nothing had proved it can actually fall back
    before this. Four shapes: (1) only the two names the scope was measured against ->
    the scoped dirs; (2) a THIRD chapter-html group this scope was never checked against
    -> None (whole-corpus, slower, never wrong), not silently trusted as covered; (3) no
    chapter-html group at all (a `--check` run against a corpus with none declared) ->
    None, the same safe default; (4) an empty group list -> None, not a vacuous 'every
    known name is present' true."""
    bad = 0
    _, g_ors = _group_fixture(kind="chapter-html", group="ors")
    _, g_const = _group_fixture(kind="chapter-html", group="constitution")
    _, g_other = _group_fixture(kind="chapter-html", group="oar")
    _, g_not_chapter_html = _group_fixture(kind="listing", group="ors")

    got = _chapter_html_scope([("ors.yml", g_ors), ("constitution.yml", g_const)])
    if got != _CHAPTER_HTML_DIRS:
        print(f"FAIL both proven chapter-html group names must scope to "
              f"{_CHAPTER_HTML_DIRS!r}, got {got!r}", file=sys.stderr)
        bad += 1

    got = _chapter_html_scope([("ors.yml", g_ors), ("oar.yml", g_other)])
    if got is not None:
        print(f"FAIL an UNPROVEN chapter-html group name alongside a proven one must "
              f"fall back to None (whole corpus), not trust the scope anyway: {got!r}",
              file=sys.stderr)
        bad += 1

    got = _chapter_html_scope([("listing.yml", g_not_chapter_html)])
    if got is not None:
        print(f"FAIL no chapter-html group present must fall back to None, not "
              f"{got!r}", file=sys.stderr)
        bad += 1

    got = _chapter_html_scope([])
    if got is not None:
        print(f"FAIL an empty group list must fall back to None, not {got!r}",
              file=sys.stderr)
        bad += 1
    return bad


def _proof_due_reports_an_undeclared_cadence_rather_than_raising():
    """`--due` over a group whose cadence nobody declared. A traceback names the dict it
    was raised from and not the group that declares the value, and it takes every OTHER
    group's due-state down with it — so the reading a curator needs is the one they lose.
    CONTEXT.md's overriding rule applies: could not check is never reported as not due."""
    _, g = _group_fixture(recheck="ballot_measure")
    try:
        state, detail = due_state(g)
    except Exception as e:
        print(f"FAIL due-state on an undeclared cadence: raised "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    if state != UNKNOWN_CADENCE:
        print(f"FAIL due-state on an undeclared cadence: reported {state!r} ({detail}), "
              f"which reads as an answer", file=sys.stderr)
        return 1
    return 0


def _proof_the_writer_refuses_a_mis_splice():
    """THE WRITER'S OWN HALF, which --check cannot reach: it reads what was written and
    cannot see what writing it nearly did. The node is located by text, so a `"recheck": `
    standing somewhere else in the file is found first and the splice lands in the wrong
    place — on a schema nothing validates against (#199), a corrupt result is silent. The
    file must come back untouched."""
    import contextlib
    import io
    import tempfile
    # A second `recheck` key standing EARLIER in the file than the real one — a `$defs`
    # block is the way a schema most plausibly grows one. The text search finds that one.
    decoy = {"$defs": {"retired": {"recheck": {"enum": ["weekly"]}}},
             "properties": {"recheck": {"enum": ["weekly"]}}}
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "decoy.schema.json"
        before = json.dumps(decoy, indent=2)
        p.write_text(before)
        # Its refusal goes to stderr, and a selftest that passes must print nothing: a
        # CI log where the expected failure looks like a failure is a log nobody reads.
        with contextlib.redirect_stderr(io.StringIO()):
            rc = sync_schema(p)
        if rc == 0:
            print("FAIL mis-splice: the writer accepted a node it found in the wrong "
                  "place", file=sys.stderr)
            return 1
        if p.read_text() != before:
            print("FAIL mis-splice: the writer refused and wrote anyway", file=sys.stderr)
            return 1
    return 0


def _proof_due_reports_an_unreadable_last_checked_rather_than_raising():
    """The sibling field, and the same defect: `last_checked` is written by hand too, and
    `2026-7-1` or a missing key used to come out of `days_since()` as a ValueError naming
    the format string. A group whose age cannot be read is a group nothing can say a
    due-state for, which is the third state and not `ok`."""
    bad = 0
    # An UNQUOTED date in the YAML is the realistic one: `last_checked: 2026-08-01` parses
    # to a datetime.date rather than a string, and strptime raises TypeError on it. The
    # other two are the shapes a hand-edit leaves behind.
    for group in (_group_fixture(last_checked=date(2026, 8, 1)),
                  _group_fixture(last_checked="August 1, 2026"),
                  _group_fixture(last_checked=None)):
        _, g = group
        try:
            state, detail = due_state(g)
        except Exception as e:
            print(f"FAIL due-state on {g['last_checked']!r}: raised "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
            bad += 1
            continue
        if state != UNREADABLE_DATE:
            print(f"FAIL due-state on {g['last_checked']!r}: reported {state!r} "
                  f"({detail}), which reads as an answer", file=sys.stderr)
            bad += 1
    return bad


def _general_elections(first=2026, last=2100):
    """Oregon general elections: the Tuesday after the first Monday in November, in
    even-numbered years. Derived from the calendar rule rather than from anything in this
    file, so the window below is an independent fact this cadence is measured against."""
    out = []
    for y in range(first, last + 1, 2):
        d = date(y, 11, 1)
        while d.weekday() != 0:
            d += timedelta(days=1)
        out.append(d + timedelta(days=1))
    return out


# WHERE A CORRECTLY CREATED GROUP'S CLOCK STARTS: the month after a general election, once
# the vote is canvassed and an approved amendment has taken effect. Measuring a single
# anchor would prove almost nothing — `last_checked` is whatever day someone ran the check
# — so every measurement below quantifies over the whole window.
ANCHOR_WINDOW = range(0, 31)


def _election_spans():
    """Days between consecutive general elections: 728 or 735, never anything else."""
    els = _general_elections()
    return [(nxt - e).days for e, nxt in zip(els, els[1:])]


def _measure_against_the_ballot_cycle(days, window=ANCHOR_WINDOW):
    """How long after the NEXT general election a group comes due, for a last check
    anywhere in `window` days after THIS one, over every consecutive pair of elections to
    2100. (min, max) in days — negative means it came due before the election it exists to
    catch."""
    els = _general_elections()
    offsets = [((e + timedelta(days=a + days)) - nxt).days
               for e, nxt in zip(els, els[1:]) for a in window]
    return min(offsets), max(offsets)


def _proof_the_ballot_measure_cadence_lands_after_an_election():
    """THE DECISION ITSELF, measured, and measured over EVERY anchor in the month after an
    election rather than one flattering day. Three properties, and the third is the one a
    single-anchor measurement hides:

    1. From any anchor in that window, this cadence comes due AFTER the next election and
       after the ~30 days in which the vote is canvassed and an approved amendment takes
       effect — a due date on election night finds nothing to check — and not a season
       past it.
    2. `biennial` cannot do the same. It is not that 730 days never lands well: from a
       late anchor it does. It is that from the NATURAL anchor — a check made promptly
       after an election — it comes due BEFORE the next one, so reusing the value would
       make the good case and the useless case the same declaration.
    3. The phase walks FORWARD. Every check re-anchors `last_checked` on the day the check
       RAN, so an interval longer than the cycle lands later each time (here 30-37 days per
       cycle) and one shorter lands earlier. Later is recoverable — the group still catches
       the amendments, just later, and an out-of-phase group drifts toward the window.
       Earlier is ABSORBING: a group that comes due before an election finds nothing,
       re-anchors earlier still, and never sees an amendment again. Neither is a substitute
       for a cadence that can state its own phase (#198); this only picks the failure that
       can be walked out of."""
    bad = 0
    days = CADENCES[BALLOT_CADENCE].days
    lo, hi = _measure_against_the_ballot_cycle(days)
    if not (30 <= lo and hi <= 90):
        print(f"FAIL {BALLOT_CADENCE}: from an anchor in the month after an election it "
              f"comes due between {lo}d and {hi}d after the next one; wanted the 30-90d "
              f"window", file=sys.stderr)
        bad += 1
    reused_lo, _ = _measure_against_the_ballot_cycle(CADENCES["biennial"].days)
    if reused_lo >= 30:
        print(f"FAIL biennial: never comes due before the results are final either "
              f"(earliest {reused_lo}d after the election), so {BALLOT_CADENCE} is a "
              f"second name for a cadence that already exists", file=sys.stderr)
        bad += 1
    if days <= max(_election_spans()):
        print(f"FAIL {BALLOT_CADENCE}: {days}d is not longer than the longest span "
              f"between two general elections ({max(_election_spans())}d), so the phase "
              f"walks BACKWARD into the state it cannot leave", file=sys.stderr)
        bad += 1
    return bad


# #198: A REGISTERED-MID-CYCLE GROUP MUST LAND ON THE CYCLE IT EXISTS TO CATCH, not on
# `cadence.days` after whatever day registration happened to be. `recheck_phase` (an
# anchor date) is the fix; this proves the SCHEDULING, not merely that the field parses —
# a group checked before a known anchor must come DUE once that anchor has passed, which
# un-phased `age >= cadence.days` math would miss for up to two years.
def _proof_a_phased_group_registered_off_cycle_lands_on_the_intended_cycle():
    """THE #198 CASE ITSELF. A biennial group is registered (`last_checked`) 20 days ago —
    comfortably 'ok' under the un-phased formula, which would not call it due again until
    ~730 days from then. But its `recheck_phase` anchor — the date THIS group's cycle is
    known to land on, e.g. an edition date — fell 5 days ago, after registration and
    before today. Nothing has happened since registration to justify skipping that cycle,
    so a correct scheduler must already call the group due; the un-phased formula cannot
    see the anchor at all and would leave it 'ok' for up to two more years — exactly the
    'stays mid-cycle forever' defect #198 opens with.

    Asserts on the DATE `_phase_aligned_due_date` actually computed, not merely that the
    anchor appears somewhere in `detail`: the anchor is echoed verbatim in every phased
    group's `phased to {phase}` clause regardless of what the schedule computes (`phase ==
    anchor.isoformat()` by construction of this fixture), so a bare substring check on the
    anchor passes on that echo alone and proves nothing about the arithmetic — verified by
    mutation: replacing `_phase_aligned_due_date`'s body with `return anchor -
    timedelta(days=10000)` left this assertion (before this fix) green. Checking
    specifically for the compound `next due {anchor}` pins the computed value instead: it
    is only in `detail` when `due_on == anchor`, which is the one case this fixture can
    prove correct on its own — `checked` falls strictly before `anchor`, so a group
    registered mid-cycle must be scheduled to land ON the anchor itself (see
    `_phase_aligned_due_date`'s docstring). The sibling proof below,
    `_proof_a_phased_group_just_checked_is_not_immediately_due_again`, exercises the other
    arithmetic path — `checked` AFTER `anchor` — that this fixture cannot reach."""
    today = date.today()
    anchor = today - timedelta(days=5)
    checked = today - timedelta(days=20)
    _, g = _group_fixture(recheck="biennial", last_checked=checked.isoformat(),
                          recheck_phase=anchor.isoformat())
    state, detail = due_state(g)
    if state != "DUE":
        print(f"FAIL phased biennial group: anchor {anchor.isoformat()} has already "
              f"passed (last checked {checked.isoformat()}, 20d ago) so this must be DUE; "
              f"got {state!r} ({detail})", file=sys.stderr)
        return 1
    want = f"next due {anchor.isoformat()}"
    if want not in detail:
        print(f"FAIL phased biennial group: checked before its own anchor must be "
              f"scheduled to come due AT the anchor ({want!r}), got {detail!r}",
              file=sys.stderr)
        return 1
    return 0


def _proof_a_phased_group_just_checked_is_not_immediately_due_again():
    """THE OTHER HALF of `_phase_aligned_due_date`'s own docstring claim — 'a group just
    checked is never immediately due again' — which the proof above cannot see: it only
    ever checks a group BEFORE its anchor, where `k` (the docstring's whole-number-of-
    intervals term) is always 0 and `due_on` collapses to `anchor` itself regardless of
    whether the function's `+ 1` is even present. Here `checked` is TODAY and `anchor` is
    200 days in the past — inside the current biennial cycle, not before it — so the
    correct next due date is the FOLLOWING cycle's anchor, `anchor + cadence.days`,
    computed independently by plain addition rather than by re-deriving
    `_phase_aligned_due_date`'s own floor-division arithmetic.

    This catches what the sibling proof cannot: a mutant that drops the function's `+ 1`
    (the exact off-by-one its docstring warns against) computes `k=0` here too and
    schedules this group's due date AT the 200-day-old anchor — already past — which flips
    a freshly-checked group straight to DUE. That is the absorbing always-due state the
    `even_year_general_election` comment 40 lines above exists to warn a walk-forward
    cadence away from; verified by mutation before this fix (dropping the `+ 1` and
    checking a biennial group with `last_checked` today against a 100-days-back anchor)."""
    today = date.today()
    anchor = today - timedelta(days=200)
    days = CADENCES["biennial"].days
    _, g = _group_fixture(recheck="biennial", last_checked=today.isoformat(),
                          recheck_phase=anchor.isoformat())
    state, detail = due_state(g)
    if state != "ok":
        print(f"FAIL just-checked phased group: checked today, anchor "
              f"{anchor.isoformat()} 200d ago (mid-cycle, {days}d cadence) — the next "
              f"cycle isn't due for ~{days - 200} more days; expected 'ok', got "
              f"{state!r} ({detail})", file=sys.stderr)
        return 1
    want = f"next due {(anchor + timedelta(days=days)).isoformat()}"
    if want not in detail:
        print(f"FAIL just-checked phased group: expected {want!r} (the FOLLOWING cycle's "
              f"anchor) in detail, got {detail!r}", file=sys.stderr)
        return 1
    return 0


def _proof_a_group_declaring_no_phase_behaves_exactly_as_today():
    """ADDITIVE, ASSERTED RATHER THAN ASSUMED (#198's own acceptance criterion): a group
    that declares no `recheck_phase` must be untouched by any of this. Computed here
    independently of due_state() — the pre-#198 formula (age >= cadence.days) against the
    documented `biennial` constant — rather than by calling due_state() a second time, so a
    change to the phase branch that also perturbed the no-phase path could not hide behind
    an assertion that recomputes whatever the code now does.

    TWO CASES, not one: a fixture that is always old enough to be DUE samples only one
    side of `age >= cadence.days` — a mutant that made the un-phased branch return `DUE`
    unconditionally left this proof green when it sampled only that side (verified before
    this fix). The second case, checked TODAY, is comfortably 'ok' and exercises the
    branch the first case cannot reach."""
    bad = 0
    for checked in (date(2020, 1, 1), date.today()):
        _, g = _group_fixture(recheck="biennial", last_checked=checked.isoformat())
        state, detail = due_state(g)
        age = (date.today() - checked).days
        want_state = "DUE" if age >= CADENCES["biennial"].days else "ok"
        if state != want_state:
            print(f"FAIL unphased group (checked {checked.isoformat()}): expected "
                  f"{want_state!r} from the pre-#198 formula (age {age}d vs "
                  f"{CADENCES['biennial'].days}d), got {state!r} ({detail})",
                  file=sys.stderr)
            bad += 1
            continue
        if "phased" in detail:
            print(f"FAIL unphased group (checked {checked.isoformat()}): detail mentions "
                  f"phase with none declared: {detail!r}", file=sys.stderr)
            bad += 1
    return bad


def _proof_due_reports_an_unreadable_phase_rather_than_raising():
    """The sibling defect to unreadable `last_checked`, for the field this ticket adds: a
    hand-edited or generated `recheck_phase` that is not a YYYY-MM-DD date must be
    REPORTED, not raise — ADR 0006's overriding rule ('could not check is never reported
    as is not there') applied to the new field the same way #198's issue asked it applied
    to the old one."""
    bad = 0
    for group in (_group_fixture(recheck_phase=date(2027, 1, 1)),      # unquoted YAML date
                  _group_fixture(recheck_phase="January 1, 2027")):    # not YYYY-MM-DD
        _, g = group
        try:
            state, detail = due_state(g)
        except Exception as e:
            print(f"FAIL due-state on recheck_phase {g['recheck_phase']!r}: raised "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
            bad += 1
            continue
        if state != UNREADABLE_PHASE:
            print(f"FAIL due-state on recheck_phase {g['recheck_phase']!r}: reported "
                  f"{state!r} ({detail}), which reads as an answer", file=sys.stderr)
            bad += 1
    return bad


def _proof_two_groups_sharing_an_interval_on_opposite_phases_are_distinguished():
    """AC #1 ITSELF — #198's headline case, and the one no proof in this file asserted:
    'two groups sharing an interval but on opposite phases are distinguishable, and the
    due-check treats them differently at the right times.' Every other phase proof above
    uses exactly one phased group; this is the first (and only) place two phased biennial
    groups with the SAME `last_checked` and DIFFERENT anchors are compared against each
    other and against the un-phased control, so the feature's actual scheduling contract —
    not just that the phase branch runs — has an assertion behind it.

    Both groups were checked 400 days ago — under the un-phased formula that is a single
    'ok' (400d < 730d), which is also asserted here as the control. `anchor_due` sits 400
    days before `checked` (830 days ago), so its cycle's next occurrence, `anchor_due +
    730d`, already fell 70 days before today: DUE. `anchor_ok` sits only 300 days before
    `checked` (700 days ago) — 100 days later in the cycle, the 'opposite phase' the
    acceptance criterion names — so ITS next occurrence, `anchor_ok + 730d`, is still 30
    days away: ok. Same interval, same `last_checked`, different phase, different
    answer."""
    bad = 0
    checked = date.today() - timedelta(days=400)
    days = CADENCES["biennial"].days
    anchor_due = checked - timedelta(days=400)
    anchor_ok = checked - timedelta(days=300)
    _, g_due = _group_fixture(recheck="biennial", last_checked=checked.isoformat(),
                              recheck_phase=anchor_due.isoformat())
    _, g_ok = _group_fixture(recheck="biennial", last_checked=checked.isoformat(),
                             recheck_phase=anchor_ok.isoformat())
    _, g_control = _group_fixture(recheck="biennial", last_checked=checked.isoformat())
    state_due, detail_due = due_state(g_due)
    state_ok, detail_ok = due_state(g_ok)
    state_control, detail_control = due_state(g_control)
    want_due_on = (anchor_due + timedelta(days=days)).isoformat()
    want_ok_on = (anchor_ok + timedelta(days=days)).isoformat()
    if state_due != "DUE" or f"next due {want_due_on}" not in detail_due:
        print(f"FAIL opposite-phase pair (due side): anchor {anchor_due.isoformat()} "
              f"should be DUE with next due {want_due_on}, got {state_due!r} "
              f"({detail_due})", file=sys.stderr)
        bad += 1
    if state_ok != "ok" or f"next due {want_ok_on}" not in detail_ok:
        print(f"FAIL opposite-phase pair (ok side): anchor {anchor_ok.isoformat()} "
              f"should be ok with next due {want_ok_on}, got {state_ok!r} "
              f"({detail_ok})", file=sys.stderr)
        bad += 1
    if state_control != "ok" or "phased" in detail_control:
        print(f"FAIL un-phased control (400d < 730d, same last_checked as both phased "
              f"groups): expected 'ok' with no phase mention, got {state_control!r} "
              f"({detail_control})", file=sys.stderr)
        bad += 1
    if state_due == state_ok:
        print(f"FAIL opposite-phase pair: same interval, same last_checked "
              f"({checked.isoformat()}), different phase must give different states; "
              f"both read {state_due!r}", file=sys.stderr)
        bad += 1
    return bad


def _proof_due_reports_a_phase_on_a_cadence_that_admits_none_rather_than_raising():
    """RUNTIME half of the `group-phase` --check rule below: `--check` gates this at
    commit time, but due_state() must not trust that every committed group last passed it
    — a hand-edit after the last `--check` run must be reported, not silently mis-scheduled
    by applying phase math to a cadence (`weekly`) CADENCES never marked phase-capable."""
    _, g = _group_fixture(recheck="weekly", recheck_phase="2026-08-01")
    try:
        state, detail = due_state(g)
    except Exception as e:
        print(f"FAIL due-state on a phase declared for a non-phase-capable cadence: "
              f"raised {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    if state != PHASE_NOT_ADMITTED:
        print(f"FAIL due-state on a phase declared for a non-phase-capable cadence: "
              f"reported {state!r} ({detail}), which reads as an answer", file=sys.stderr)
        return 1
    return 0


# TWO KINDS OF PROOF, kept apart because they demonstrate different things. `_PROOFS`
# each break one rule of `check_cadences` and assert THAT rule fires. `_MEASURED` are the
# behaviours no --check rule can state: what a report does with data it cannot read, what
# the writer does with a splice it cannot trust, and where this cadence actually lands
# against the ballot cycle. Counting them in one total would let a measurement stand in
# for a rule nobody has watched fail.
_MEASURED = [_proof_due_reports_an_undeclared_cadence_rather_than_raising,
             _proof_due_reports_an_unreadable_last_checked_rather_than_raising,
             _proof_the_writer_refuses_a_mis_splice,
             _proof_check_schema_reports_a_malformed_schema_rather_than_raising,
             _proof_the_ballot_measure_cadence_lands_after_an_election,
             _proof_a_phased_group_registered_off_cycle_lands_on_the_intended_cycle,
             _proof_a_phased_group_just_checked_is_not_immediately_due_again,
             _proof_a_group_declaring_no_phase_behaves_exactly_as_today,
             _proof_two_groups_sharing_an_interval_on_opposite_phases_are_distinguished,
             _proof_due_reports_an_unreadable_phase_rather_than_raising,
             _proof_due_reports_a_phase_on_a_cadence_that_admits_none_rather_than_raising,
             _proof_a_well_formed_phase_validates_against_the_committed_schema,
             _proof_chapter_html_id_accounting_is_scoped_correctly,
             _proof_ors_empty_chapter_ids_reads_the_catalogs_own_accounting,
             _proof_chapter_html_accounting_reports_an_unreadable_content_dir_rather_than_raising,
             _proof_chapter_html_scope_falls_back_to_the_whole_corpus_when_unproven]

_PROOFS = [
    ("a cadence declared in the checker and not the schema",
     _proof_a_cadence_missing_from_the_schema_is_reported),
    ("a cadence admitted by the schema and not declared in the checker",
     _proof_a_cadence_missing_from_the_declaration_is_reported),
    ("an interval the schema prints that the declaration no longer means",
     _proof_a_stale_interval_in_the_schema_is_reported),
    ("a committed node the declaration would rewrite",
     _proof_a_node_the_declaration_would_rewrite_is_reported),
    ("a source group declaring a cadence nobody declared",
     _proof_a_group_declaring_an_undeclared_cadence_is_reported),
    ("a source group declaring a phase on a cadence that admits none",
     _proof_a_group_declaring_a_phase_on_a_cadence_that_admits_none_is_reported),
    ("a source group carrying a key its schema forbids",
     _proof_a_group_with_an_undeclared_key_is_reported),
    ("a source group missing a key its schema requires",
     _proof_a_group_missing_a_required_key_is_reported),
    ("a source entry missing a field its schema requires",
     _proof_a_source_entry_missing_a_required_field_is_reported),
    ("a source group declaring a misdeclared (non-ISO) recheck_phase",
     _proof_a_misdeclared_phase_fails_schema_validation),
    ("a chapter-html source id naming nothing real",
     _proof_a_chapter_html_id_naming_nothing_real_is_reported),
]


def selftest() -> int:
    bad = 0
    for name, proof in _PROOFS:
        rule, failures = proof()
        if not any(f.rule == rule for f in failures):
            print(f"FAIL {name}: expected a [{rule}] failure, got {failures}",
                  file=sys.stderr)
            bad += 1
    for proof in _MEASURED:
        bad += proof()
    print(f"{len(_PROOFS)} rule(s) demonstrated failing, {len(_MEASURED)} behaviour(s) "
          f"measured" if not bad else f"{bad} proof(s) did not hold",
          file=sys.stderr if bad else sys.stdout)
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--due", action="store_true")
    ap.add_argument("--group", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--sync-schema", action="store_true")
    args = ap.parse_args()

    if args.sync_schema:
        sys.exit(sync_schema())
    if args.check:
        sys.exit(cmd_check())
    if args.selftest:
        sys.exit(selftest())
    if args.due:
        # A group nothing can be said about exits non-zero: an unreadable cadence must not
        # be indistinguishable from a run where nothing was due.
        sys.exit(1 if report_due() else 0)

    groups = dict(source_groups())
    names = {g["group"]: (p, g) for p, g in groups.items()}
    targets = list(names) if args.all else args.group
    if not targets:
        print("nothing to do: pass --due, --group NAME, or --all")
        sys.exit(2)
    today = date.today().isoformat()
    total_changed = 0
    for t in targets:
        if t not in names:
            print(f"unknown group: {t} (available: {', '.join(sorted(names))})")
            sys.exit(2)
        gpath, g = names[t]
        changed = check_group(gpath, g, args.refresh, today)
        total_changed += len(changed)
        if not changed:
            print(f"{t}: no changes ({len(g['sources'])} source(s) checked)")
    print(f"done: {total_changed} change(s) across {len(targets)} group(s)")


if __name__ == "__main__":
    main()
