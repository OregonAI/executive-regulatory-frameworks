#!/usr/bin/env python3
"""Group-scoped upstream update checker — the engine behind the /check-updates skill.

Groups are data (_meta/sources/<group>.yml); this tool is generic and never needs
changing when knowledge bodies or agencies are added. Output is deliberately terse
(silent on unchanged sources) so an agent can drive it cheaply.

  --due                 no-network report: which groups are due per their recheck cadence
  --group NAME ...      check specific group(s)
  --all                 check every group
  --refresh             with a check: re-fetch changed docs and regenerate their
                        '## Full text' (ingest_lib.refresh_document); rebuild changed
                        listing snapshots. Never auto-ingests listing ADDED rows
                        (intake gate #1: a human vets the list first).
  --check               CI: the cadence a group may declare is declared ONCE, in CADENCES
                        below, and the schema's `recheck` node is derived from it. Fails
                        when the committed node is not the one that table renders, or when
                        a group declares a cadence nobody declared.
  --sync-schema         rewrite the schema's `recheck` node from CADENCES
  --selftest            CI: every rule --check enforces, demonstrated failing, plus the
                        behaviours no rule can state (what a report does with data it
                        cannot read; where this cadence lands against the ballot cycle)
"""
import argparse
import json
import sys
from collections import namedtuple
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from repo_lib import (REPO_ROOT, SCHEMA_DIR, SOURCES_DIR, content_files, content_hash,
                      parse_frontmatter, source_groups)

SCHEMA = SCHEMA_DIR / "source-group.schema.json"

Cadence = namedtuple("Cadence", "days note")

# One contract violation: which rule, which group (or file), and what is wrong with it. A
# type rather than a formatted string, so --selftest asserts on the RULE that fired instead
# of pattern-matching prose (catalog_agencies.py's Failure, same reason).
Failure = namedtuple("Failure", "rule row detail")

CADENCES = {
    "weekly": Cadence(7, "a listing that moves within a week"),
    "monthly": Cadence(30, "the Oregon Bulletin, first business day of each month"),
    "quarterly": Cadence(90, "a listing that moves a few times a year"),
    "biennial": Cadence(730, "the ORS edition, published after each ODD-YEAR "
                             "legislative session"),
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
    # out-of-phase group drift toward the window. A cadence that could state its own phase
    # is #198; until then the phase is a decision made when the group is created (#194,
    # #197) and re-made by hand when the walk has gone far enough.
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
UNREADABLE = (UNKNOWN_CADENCE, UNREADABLE_DATE)


def due_state(g, cadences=None):
    """(state, detail) for one group: is it due for a recheck, and on what reading.

    A cadence nobody declared, and a `last_checked` nothing can read, are REPORTED here
    rather than raised: a KeyError out of a dict lookup or a ValueError out of strptime
    names the dict or the format string instead of the group, and takes every other
    group's reading down with it."""
    cadences = CADENCES if cadences is None else cadences
    cadence = cadences.get(g.get("recheck"))
    if cadence is None:
        return (UNKNOWN_CADENCE,
                f"recheck {g.get('recheck')!r} is not one of "
                f"{', '.join(sorted(cadences))}; cannot say whether this group is due")
    try:
        age = days_since(g["last_checked"])
    except (KeyError, TypeError, ValueError):
        return (UNREADABLE_DATE,
                f"last_checked {g.get('last_checked')!r} is not a YYYY-MM-DD date; "
                f"cannot say whether this group is due")
    return ("DUE" if age >= cadence.days else "ok",
            f"last checked {age}d ago; cadence {g['recheck']}")


def report_due() -> int:
    """Print every group's due-state; return how many could not be read at all."""
    unreadable = 0
    for gpath, g in source_groups():
        state, detail = due_state(g)
        unreadable += state in UNREADABLE
        print(f"{g['group']}: {state} ({detail}; "
              f"{len(g['sources'])} source(s); signal: {g['upstream_signal']})")
    return unreadable


def doc_paths_by_id():
    m = {}
    for p in content_files():
        fm, _ = parse_frontmatter(p)
        m.setdefault(fm.get("snapshot_id") or fm["id"], []).append(p)
        m.setdefault(fm["id"], []).append(p)
    return m


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


def check_schema(groups=None, schema=None):
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
    groups that happened to pass."""
    schema = json.loads(SCHEMA.read_text()) if schema is None else schema
    groups = list(source_groups() if groups is None else groups)
    try:
        import jsonschema
    except ImportError:
        return [], 0
    failures = []
    for gpath, g in groups:
        try:
            jsonschema.validate(g, schema)
        except jsonschema.exceptions.ValidationError as e:
            failures.append(Failure("group-schema", g.get("group", gpath.name), e.message))
    return failures, len(groups)


def cmd_check() -> int:
    """Report every cadence violation in the committed declaration, schema and groups,
    plus every group in `_meta/sources/` that does not validate against
    `source-group.schema.json` (#199)."""
    failures = check_cadences()
    schema_failures, schema_checked = check_schema()
    failures = failures + schema_failures
    for f in failures:
        print(f"  FAIL [{f.rule}] {f.row}: {f.detail}", file=sys.stderr)
    if failures:
        print(f"\n{len(failures)} contract violation(s)", file=sys.stderr)
        return 1
    print(f"{len(CADENCES)} cadence(s) declared, each admitted by "
          f"{SCHEMA.name} with the interval it means")
    print(f"groups per cadence: {cadence_census()}")
    total_groups = len(list(source_groups()))
    print(f"{schema_checked} of {total_groups} source group(s) validated against "
          f"{SCHEMA.name}" +
          ("" if schema_checked == total_groups else " (jsonschema not installed)"))
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


def _proof_a_group_violating_its_schema_is_reported():
    """`_meta/schema/source-group.schema.json` describes every group's shape --
    `additionalProperties: false` at the group and source level, three required top-level
    keys. `check_schema`'s own docstring is where the finding that this schema was
    already enforced corpus-wide lives (#199) -- this proof is only about the LOCAL copy
    of that rule added here, watched failing on two independent violations (an extra key,
    a missing required one) so it is shown catching more than one shape of mistake."""
    _, extra = _group_fixture()
    extra = {**extra, "not_a_declared_key": True}
    _, missing = _group_fixture()
    del missing["sources"]
    failures, _ = check_schema(groups=[(SOURCES_DIR / "extra.yml", extra),
                                        (SOURCES_DIR / "missing.yml", missing)])
    return "group-schema", failures


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


# TWO KINDS OF PROOF, kept apart because they demonstrate different things. `_PROOFS`
# each break one rule of `check_cadences` and assert THAT rule fires. `_MEASURED` are the
# behaviours no --check rule can state: what a report does with data it cannot read, what
# the writer does with a splice it cannot trust, and where this cadence actually lands
# against the ballot cycle. Counting them in one total would let a measurement stand in
# for a rule nobody has watched fail.
_MEASURED = [_proof_due_reports_an_undeclared_cadence_rather_than_raising,
             _proof_due_reports_an_unreadable_last_checked_rather_than_raising,
             _proof_the_writer_refuses_a_mis_splice,
             _proof_the_ballot_measure_cadence_lands_after_an_election]

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
    ("a source group violating its schema (an extra key, a missing required one)",
     _proof_a_group_violating_its_schema_is_reported),
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
