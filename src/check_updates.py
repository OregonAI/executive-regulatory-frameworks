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
                        below, and the schema's enum is derived from it. Fails when the
                        two have drifted or a group declares a cadence nobody declared.
  --sync-schema         rewrite the schema's `recheck` node from CADENCES
  --selftest            CI: every rule --check enforces, demonstrated failing
"""
import argparse
import json
import sys
from collections import namedtuple
from datetime import date, datetime, timedelta

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
    # November of EVEN-numbered years. A group on `biennial` comes due 730 days after its
    # last check, which against the even-year cycle lands on the wrong side of the election
    # it exists to catch (selftest measures both).
    #
    # 765 DAYS = 735 + 30, and each half is a fact rather than a round number. 735 is the
    # LONGEST span between two consecutive general elections (they run 728 or 735 days
    # apart through 2100, because the first-Tuesday-after-the-first-Monday rule slides
    # election day between November 2 and 8); taking the longest means the due date never
    # lands before the election. The 30 is the margin in which the vote is canvassed and an
    # approved amendment takes effect — due on election night finds nothing to check yet.
    #
    # WHAT THIS INTERVAL CANNOT DO is set its own phase: `recheck` is a number of days
    # since the last check, so a group first registered mid-cycle stays mid-cycle forever
    # and reports `ok` the whole time. Whoever creates the group (#194, #197) puts it on
    # phase by setting `last_checked` to a date after a general election; #198 is the
    # cadence that could express the phase itself.
    "even_year_general_election": Cadence(765, "constitutional amendments referred to "
                                               "voters and decided at the general "
                                               "election, November of EVEN-numbered "
                                               "years"),
}

# The cadence ADR 0005's source group takes, named once so the selftest and the gate below
# refer to the decision rather than to a string.
BALLOT_CADENCE = "even_year_general_election"


def days_since(iso: str) -> int:
    return (date.today() - datetime.strptime(iso, "%Y-%m-%d").date()).days


# THE THIRD STATE, which may never be collapsed into the other two: a group whose cadence
# nobody declared is not due and is not ok — it is a group nothing can say anything about.
# CONTEXT.md's overriding rule: "could not check" is never reported as "is not there".
UNKNOWN_CADENCE = "UNKNOWN CADENCE"


def due_state(g, cadences=None):
    """(state, detail) for one group: is it due for a recheck, and on what reading.

    A cadence nobody declared is REPORTED here rather than raised. The value comes from
    _meta/sources/<group>.yml, which is data a human writes, so the mistake belongs to
    that file — and a KeyError out of a dict lookup names the dict instead of the group,
    and takes every other group's reading down with it."""
    cadences = CADENCES if cadences is None else cadences
    cadence = cadences.get(g.get("recheck"))
    if cadence is None:
        return (UNKNOWN_CADENCE,
                f"recheck {g.get('recheck')!r} is not one of "
                f"{', '.join(sorted(cadences))}; cannot say whether this group is due")
    age = days_since(g["last_checked"])
    return ("DUE" if age >= cadence.days else "ok",
            f"last checked {age}d ago; cadence {g['recheck']}")


def report_due() -> int:
    """Print every group's due-state; return how many could not be read at all."""
    unreadable = 0
    for gpath, g in source_groups():
        state, detail = due_state(g)
        unreadable += state == UNKNOWN_CADENCE
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


def sync_schema() -> int:
    """Write the derived `recheck` node into the schema, leaving the rest of the file
    byte-for-byte alone (only this one node is generated; every other description in it is
    hand-written)."""
    text = SCHEMA.read_text()
    key = '"recheck": '
    start = text.index(key)
    indent = " " * (start - text.rfind("\n", 0, start) - 1)
    open_brace = text.index("{", start + len(key))
    depth, end = 0, None
    for i in range(open_brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        print(f"cannot find the recheck node in {SCHEMA}", file=sys.stderr)
        return 1
    rendered = json.dumps(recheck_node(), indent=2).replace("\n", "\n" + indent)
    new = text[:start] + key + rendered + text[end:]
    if new == text:
        print(f"{SCHEMA.name}: already current")
        return 0
    SCHEMA.write_text(new)
    print(f"{SCHEMA.name}: recheck node written from {len(CADENCES)} declared cadence(s)")
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
    want = recheck_node(cadences)["description"]
    if node.get("description") != want:
        failures.append(Failure("schema-description", SCHEMA.name,
                                "the schema's `recheck` description is not the one "
                                "CADENCES renders; run --sync-schema"))
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
        counts[g["recheck"]] = counts.get(g["recheck"], 0) + 1
    return ", ".join(f"{n}={c}" for n, c in counts.items())


def cmd_check() -> int:
    """Report every cadence violation in the committed declaration, schema and groups."""
    failures = check_cadences()
    for f in failures:
        print(f"  FAIL [{f.rule}] {f.row}: {f.detail}", file=sys.stderr)
    if failures:
        print(f"\n{len(failures)} cadence violation(s)", file=sys.stderr)
        return 1
    print(f"{len(CADENCES)} cadence(s) declared, each admitted by "
          f"{SCHEMA.name} with the interval it means")
    print(f"groups per cadence: {cadence_census()}")
    return 0


# ------------------------------------------------------------------------ selftest
# THE PROOF THAT THE GATE ABOVE CAN FAIL. Every rule --check enforces is exercised against
# a synthetic declaration, schema and group built to violate exactly one of them: a check
# nobody has watched fail is not known to work, it is only known to be quiet.
def _schema_fixture(cadences=None):
    """A schema node that agrees with the declaration it is rendered from."""
    return {"properties": {"recheck": recheck_node(cadences or CADENCES)}}


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


def _proof_a_cadence_missing_from_the_declaration_is_reported():
    """A cadence the schema admits and the checker does not know. This is the direction
    that ends in a traceback: the schema tells a curator the value is legal, the group
    declares it, and `report_due()` looks up an interval that was never declared."""
    admits = _schema_fixture()
    admits["properties"]["recheck"]["enum"].append("fortnightly")
    return "schema-enum", check_cadences(schema=admits, groups=[])


def _group_fixture(**over):
    """One update group, of the shape _meta/sources/*.yml carries."""
    g = {"group": "oregon-constitution", "title": "Oregon Constitution", "kind": "content-hash",
         "recheck": "biennial", "last_checked": "2026-08-01",
         "upstream_signal": "one page carrying all 18 articles", "sources": []}
    g.update(over)
    return SOURCES_DIR / f"{g['group']}.yml", g


def _proof_a_group_declaring_an_undeclared_cadence_is_reported():
    """A source group is data a human writes, so a cadence nobody declared is a mistake
    in that file and is REPORTED against it. Before this rule it was a KeyError raised
    from inside report_due(), which names the dict and not the group."""
    return "group-cadence", check_cadences(groups=[_group_fixture(recheck="ballot_measure")])


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


def _measure_against_the_ballot_cycle(days):
    """How long after the NEXT general election a group checked the day after THIS one
    comes due, over every consecutive pair of elections this century. Returns (min, max)
    in days — negative means it came due before the election it exists to catch."""
    els = _general_elections()
    offsets = [((e + timedelta(days=1 + days)) - nxt).days for e, nxt in zip(els, els[1:])]
    return min(offsets), max(offsets)


def _proof_the_ballot_measure_cadence_lands_after_an_election():
    """THE DECISION ITSELF, measured. A group on this cadence, checked the day after a
    general election, must come due AFTER the next one — and after the ~30 days in which
    the vote is canvassed and an approved amendment takes effect, since a due date on
    election night finds nothing to check. It must also not wander a season past it.

    The same measurement is what refuses `biennial`: 730 days is the odd-year ORS
    session, and against the even-year ballot cycle it comes due on the wrong side of the
    election it exists to catch. That is the ambiguity ADR 0005 calls quiet."""
    bad = 0
    lo, hi = _measure_against_the_ballot_cycle(CADENCES[BALLOT_CADENCE].days)
    if not (30 <= lo and hi <= 90):
        print(f"FAIL {BALLOT_CADENCE}: comes due between {lo}d and {hi}d after the "
              f"general election it must follow; wanted the 30-90d window",
              file=sys.stderr)
        bad += 1
    reused_lo, reused_hi = _measure_against_the_ballot_cycle(CADENCES["biennial"].days)
    if 30 <= reused_lo and reused_hi <= 90:
        print(f"FAIL biennial: reaches the same window ({reused_lo}d-{reused_hi}d), so "
              f"{BALLOT_CADENCE} is a second name for a cadence that already exists",
              file=sys.stderr)
        bad += 1
    return bad


_BEHAVIOURS = [_proof_due_reports_an_undeclared_cadence_rather_than_raising,
               _proof_the_ballot_measure_cadence_lands_after_an_election]

_PROOFS = [
    ("a cadence declared in the checker and not the schema",
     _proof_a_cadence_missing_from_the_schema_is_reported),
    ("a cadence admitted by the schema and not declared in the checker",
     _proof_a_cadence_missing_from_the_declaration_is_reported),
    ("an interval the schema prints that the declaration no longer means",
     _proof_a_stale_interval_in_the_schema_is_reported),
    ("a source group declaring a cadence nobody declared",
     _proof_a_group_declaring_an_undeclared_cadence_is_reported),
]


def selftest() -> int:
    bad = 0
    for name, proof in _PROOFS:
        rule, failures = proof()
        if not any(f.rule == rule for f in failures):
            print(f"FAIL {name}: expected a [{rule}] failure, got {failures}",
                  file=sys.stderr)
            bad += 1
    for proof in _BEHAVIOURS:
        bad += proof()
    print(f"{len(_PROOFS) + len(_BEHAVIOURS)} violation(s) demonstrated failing" if not bad
          else f"{bad} rule(s) did not fire", file=sys.stderr if bad else sys.stdout)
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
