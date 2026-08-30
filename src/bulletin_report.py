#!/usr/bin/env python3
"""The monthly Oregon Bulletin report: one issue per run, beside hashing (#231).

  python3 src/bulletin_report.py             # print the report; files NOTHING
  python3 src/bulletin_report.py --file-issue  # file the ONE issue this run has to file
  python3 src/bulletin_report.py --check     # CI: the report's rules, over committed data
  python3 src/bulletin_report.py --selftest  # CI: every rule --check enforces, fired

WHY THIS EXISTS. #226-#230 built a reader, a status writer and an automatic re-ingest, and
every one of them still depended on somebody remembering to run it and to read what it
said. corpus-toolkit#67 exists because two capped drift runs put their notice on stderr and
concluded `success`. So the reader runs on a cron and its findings arrive in the issue
tracker -- ONE issue per run, because August 2026 filed 418 actions against rules this
corpus holds and a 25-issue cap turns one-issue-per-rule into 393 findings nobody sees.

IT RUNS BESIDE HASHING, NOT INSTEAD OF IT. ADR 0006 rejected replacement: a silent upstream
correction files no notice, so under a Bulletin-only design "no filing this month" and
"nothing changed" become the same observation. The four cases, and neither signal is the
other's arbiter:

  | Bulletin | hash | meaning |
  |---|---|---|
  | names a rule | unchanged | filed but not yet served -- recorded, no alarm |
  | SILENT | MOVED | a change nobody announced -- THE LOUD ONE, reported first |
  | names a rule | moved | agreement |
  | silent | unchanged | quiet -- counted, not listed |

THE FIFTH CASE, WHICH THE TABLE DOES NOT HAVE, AND WHICH IS THE WHOLE OF THIS MONTH.
The table assumes both signals cover the same rules. They do not. `_meta/sources/oar.yml`
watches 484 sources and every one of them is an individual RULE page in chapters 105, 122,
125 and 128; the August 2026 bulletin named 534 rules, in 35 OTHER chapters. THE OVERLAP IS
ZERO. So for every rule the Bulletin named there is NO HASH OBSERVATION AT ALL, and reading
its absence from the drift file as "the hash did not move" would be the substitution this
repository refuses everywhere: could not check reported as is not there. `NOT_WATCHED` is
its own outcome, counted and named, and `filed but not yet served` is claimed ONLY for a
rule the manifest actually watches and this run actually compared. The coverage gap itself
is #247; this module reports around it rather than papering over it.

THE GUARD THAT KEEPS THE LOUD CASE HONEST. `changed`-with-no-filing is the finding this
whole series is for, and it is exactly the finding a stale baseline manufactures in bulk.
It is manufacturing one right now: #244 -- the OARD page footer prints the app version
inside the hashed text and `v2.1.7` became `v2.1.8`, so every recorded baseline over an
OARD page is stale: every such document's `source_sha256` and all 484 of this manifest's.
Measured here on 2026-08-23, a full `corpus-detect-changes --group oar` run reported 484 of
484 sources CHANGED. Named per rule, that is 484 confident "changed with nobody announcing
it" claims of which zero are about a rule's text. So when the moved share of the compared sources exceeds
`GROUP_WIDE_SHARE`, per-rule attribution is WITHHELD: the run reports ONE group-wide move,
says how many rules it declined to name and why, and never emits the per-rule claim. That
is corpus-toolkit's ADR 0010 one level up -- a group drift finding reports correlation, not
cause -- and it is the manufactured-absence failure inverted, which is the thing #226-#231
exist to prevent.

WHAT THIS RUN NEVER DOES. It files at most ONE issue, and files none at all when there is
nothing to report; it writes no file in the repository and pushes no commit; THIS MODULE
touches the network in no mode -- the Bulletin reading is `check_bulletin.py`'s committed
worklist and the hash reading is whatever `changed-sources.tsv` it finds in the working
tree, so `--check`, `--report` and `--file-issue` all fetch nothing (the crawl that
produces that file is a SEPARATE STEP of `bulletin-report.yml`, before this one, and
`the-scheduled-run-fetches-the-group-this-reader-joins` is what holds the two together);
and it files nothing unless `--file-issue` is passed, so the default of every command anybody types by hand is a dry run.

WHAT `--check` READS, AND WHY IT IS NOT SATISFIABLE BY REPORTING LESS. Every rule about the
report's SHAPE is satisfied by a report that carries nothing. So the gate reads the NOTICE
-- the committed worklist -- and demands that the body carry every unread filing and every
coverage-gap rule it names, and that the counts partition its rows exactly. A report that
dropped the 121 missing-from-mirrored-chapter rules would pass every other rule here."""
import argparse
import ast
import json
import re
import subprocess
import sys
from collections import Counter, namedtuple
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml

import check_bulletin
import legal_status
# The one reader of the one file `check_bulletin.py` writes, and one printer for the
# failures -- a second copy of either is where the two spellings drift apart.
from legal_status import load_worklist, report
from repo_lib import REPO_ROOT, Checks

WORKLIST = check_bulletin.WORKLIST
# The manifest whose sources ARE the hash observation's universe: what hashing can even
# see. Read for the join and for the denominator of the group-wide share; never written.
MANIFEST = REPO_ROOT / "_meta/sources/oar.yml"
DRIFT_GROUP = "oar"

# THE WORKLIST STATE THIS REPORT LISTS AS A COVERAGE GAP -- `check_bulletin.py`'s
# vocabulary, SPELLED A SECOND TIME HERE. A rename there would leave this filtering on a
# value the notice no longer writes, which matches NOTHING and reads exactly like a month
# with no coverage gaps -- the measurement error ADR 0006 records itself making, 121 rules
# wide. So `the-vocabulary-the-census-counts-is-the-readers` compares the two, and until
# it does this constant is not trusted. Same arrangement as `reingest_oar.HELD`.
MISSING_STATE = "missing_from_mirrored_chapter"

# WHERE THE HASH READING COMES FROM. `corpus-detect-changes` writes this file into the
# corpus root on every run -- four tab-separated columns, `id url old new`, one row per
# source that differed from its recorded baseline. It is the toolkit's PUBLIC surface for
# corpus repos (its own docstring says so), and it is the reason this module re-fetches
# nothing: the drift job already paid for the crawl.
#
# TWO SPELLINGS OF ONE FACT, GATED. The name is a literal there and a literal here, and a
# rename upstream would leave this reading a file that is never written -- which produces
# "no observation" on every run, indistinguishable from a corpus nobody is hashing.
# `the-drift-observation-is-the-file-the-toolkit-writes` compares the two.
DRIFT_FILE = "changed-sources.tsv"

# THE WORKFLOW THIS MODULE IS THE BODY OF, and the one that must keep hashing alive beside
# it. Both are read as TEXT by `--check`: a cadence that lives in a comment is a cadence
# nobody is running, and ADR 0006's "runs beside hashing" is a claim about a file on disk.
WORKFLOW = REPO_ROOT / ".github/workflows/bulletin-report.yml"
DRIFT_WORKFLOW = REPO_ROOT / ".github/workflows/scheduled.yml"

# THE CADENCE, DECLARED HERE AND CHECKED THERE. The Oregon Bulletin appears on the FIRST
# BUSINESS DAY of each month, so a monthly cron is the matching cadence and any day-of-month
# below 2 can fire before the bulletin it is meant to read exists. The 6th, a day after
# `scheduled.yml`'s monthly drift run on the 5th, because this report READS that run's
# `changed-sources.tsv` and a report that ran first would have no hash reading at all.
CRON = "0 15 6 * *"
# THE EARLIEST DAY A RUN CAN HONESTLY CLAIM TO HAVE READ THIS MONTH'S BULLETIN. The first
# BUSINESS day is as late as the 4th: the 1st a Saturday, the 2nd a Sunday, the 3rd a
# Monday holiday. A run before it reads LAST month's bulletin and reports it as this
# month's -- and `check_bulletin.bulletin_date()` takes the same care in the other
# direction, using the 1st as the EARLIEST a named bulletin can exist. Set to 2 this
# guard passed a cron on the 2nd and the 3rd, both of which can precede publication:
# the number has to be the latest the Bulletin can appear, not the earliest.
EARLIEST_DAY = 4

# THE SHARE OF COMPARED SOURCES ABOVE WHICH A MOVE IS THE GROUP'S AND NOT ANY RULE'S.
# A genuinely unannounced rule change is rare -- 484 of them in a month is a template, a
# footer, or a stale baseline (#244), and naming them one by one publishes 484 confident
# false findings under provenance.
#
# NOT `check_bulletin.SYSTEMIC_SHARE`, WHICH HOLDS THE SAME NUMBER AND MEANS SOMETHING
# ELSE, and deliberately not derived from it. That one is the share of a month's filings
# that may be UNREADABLE before the run is called a failure -- a threshold on fetches that
# did not succeed. This one is a threshold on fetches that all succeeded and all disagreed
# with their baseline. Two facts that happen to have been set to the same value; gating
# their agreement would make a future argument for moving one an argument for moving the
# other, which is the collapse CONTEXT.md's *Group-wide move* entry warns about by name.
GROUP_WIDE_SHARE = 0.20

# The one issue a run files, and the strings that make a second run recognise the first.
# TITLED BY BULLETIN, not by date: two runs in the same month must find each other, and a
# run in the next month must not.
ISSUE_TITLE = "Bulletin report — {bulletin}"
ISSUE_LABELS = ("source-change", "needs-triage")
# How many issues the duplicate scan reads before it refuses to answer. Every issue the
# repository has ever had, with room -- the scan compares titles EXACTLY rather than
# trusting a search query, and a window that filled up is reported as "cannot tell"
# rather than as "not there".
ISSUE_SCAN_LIMIT = 1000

# GitHub refuses an issue body over 65,536 characters. A report that silently truncated its
# lists to fit would be corpus-toolkit#67 again, so the size is a rule rather than a slice.
BODY_LIMIT = 65536

REGENERATE = "python3 src/bulletin_report.py"

# THE SECTION HEADINGS TWO RULES READ THE BODY THROUGH, declared where the body writes
# them. `an-unannounced-change-is-reported-first` compares their positions and
# `no-observation-is-not-no-disagreement` slices between them; spelled twice, a heading
# reworded in `issue_body` would leave both searching for a section that is not there --
# and a search that finds nothing returns the same clean answer as one that finds
# everything in order.
LOUD_HEADING = "## Changed with nobody announcing it"
# WHAT THE LOUD SECTION SAYS WHEN THERE WAS NOTHING TO OBSERVE, declared rather than left
# as prose. `no-observation-is-not-no-disagreement` reads it back, and a gate that matched
# on a sentence would go quiet the first time somebody reworded the sentence -- which is
# the failure mode of every check that greps for English.
NOT_COMPUTED = "**Not computed.**"
# A per-rule count of anything, in the section that must carry none when no source was
# compared. Structural, so it survives a rewording that keeps the claim.
A_COUNT_OF_RULES_RE = re.compile(r"\b\d+ rule\(s\)")
UNCHECKED_HEADING = "## Could not check"
CALM_HEADING = "## Filed, no movement observed (no alarm)"
COUNTS_HEADING = "## Counts"

_FIRED = set()


class Failure(legal_status.Failure):
    """One rule, the thing it is about, and what is wrong with it.

    Subclassed so this module's rule names are counted in ITS OWN `_FIRED` set: sharing
    `legal_status`'s would let a rule that never fired here be reported as watched
    because a rule of the same name fired there."""

    __slots__ = ()

    def __new__(cls, rule, site, detail):
        _FIRED.add(rule)
        return tuple.__new__(cls, (rule, site, detail))


# EVERY RULE THIS MODULE CAN REPORT, each demonstrated failing by a proof below and
# compared against what the code actually emits, read out of this module's own syntax
# tree, so the declaration cannot drift from it.
CHECK_RULES = (
    # the notice, and the vocabulary it is counted through
    "the-notice-is-readable", "the-vocabulary-the-census-counts-is-the-readers",
    # the half no rule about the report's shape can state
    "the-census-accounts-for-every-filing", "an-unread-filing-reaches-the-report",
    "a-coverage-gap-reaches-the-report",
    # what a run files, and when it files nothing
    "the-run-files-one-issue", "a-run-with-nothing-to-report-files-nothing",
    # ADR 0006's four cases, and the fifth the table does not have
    "an-unannounced-change-is-reported-first", "a-filing-with-no-movement-is-not-an-alarm",
    "an-unwatched-rule-is-not-an-unchanged-one", "no-observation-is-not-no-disagreement",
    "the-observation-accounts-for-every-watched-source",
    # the guard that keeps the loud case from being manufactured in bulk
    "a-group-wide-move-is-not-per-rule-notice",
    # the two facts that live in workflow files
    "the-reader-runs-on-the-bulletins-cadence", "hash-drift-still-runs",
    "the-scheduled-run-fetches-the-group-this-reader-joins",
    "the-drift-observation-is-the-file-the-toolkit-writes",
)


# ------------------------------------------------------------------ what the Bulletin said


class Census(namedtuple("Census", "bulletin url retrieved filings rows by_action "
                                  "by_state unread gaps unknown_targets")):
    """Everything the committed worklist says, counted. Nothing derived from a fetch.

    `by_action` and `by_state` are Counters over the SAME rows, so each is a partition of
    `rows` and either one disagreeing with it is a row that was dropped on the way to the
    report -- which is the one way a report like this passes by carrying less."""

    __slots__ = ()


def months_unread(bulletin: str, today) -> int:
    """How many bulletins have been published since the one this worklist reports.

    THE PREMISE OF THE WHOLE SERIES IS THAT THE MECHANISM STOPS DEPENDING ON ANYBODY
    REMEMBERING, and without this it still does. `bulletin_report.py` reads the COMMITTED
    worklist; `check_bulletin.py` -- the thing that fetches a new one -- writes a file, and
    a scheduled job may not commit one, so nothing on a cron reads September's bulletin.
    Left alone, the 6 September run rebuilds August's report, matches August's issue title,
    prints `already filed` and exits 0: A GREEN RUN THAT FILES NOTHING, for a month nobody
    read. That is a quiet month and an unread one producing the identical outcome, which is
    the substitution this repository refuses.

    So the run counts them and REPORTS the count. It is not a `--check` rule: that gate runs
    on every pull request, and a rule that goes red the moment the month turns would block
    every unrelated change until somebody re-ran the reader -- #245's shape, a gate red for
    a reason nobody's patch caused. The mechanism is what `--check` gates; the fact is what
    the issue carries.

    Dates come from `check_bulletin.bulletin_date()`, the one place that knows a bulletin
    is named for the month it appears in."""
    published = check_bulletin.bulletin_date(bulletin)
    if published is None:
        return 0  # unreadable -- `check_bulletin.py --check` owns that failure
    return max(0, (today.year - published.year) * 12 + today.month - published.month)


def census(worklist) -> Census:
    """Count the worklist. One counter, because `--report`, `--check` and the issue body
    all state these numbers and three copies is three chances for them to disagree."""
    rows = list(worklist.get("rules") or [])
    return Census(
        bulletin=str(worklist.get("bulletin") or ""),
        url=str(worklist.get("bulletin_url") or ""),
        retrieved=str(worklist.get("retrieved") or ""),
        filings=worklist.get("filings"),
        rows=rows,
        by_action=Counter(str(r.get("action")) for r in rows),
        by_state=Counter(str(r.get("corpus_state")) for r in rows),
        unread=list(worklist.get("unread_filings") or []),
        # THE COVERAGE GAP, NAMED. 121 rules in August 2026, 43 of them amendments to
        # rules that existed and changed in chapters this corpus claims to mirror. A count
        # sends nobody anywhere; the numbers are what a person opens OARD with.
        gaps=[str(r.get("number")) for r in rows
              if r.get("corpus_state") == MISSING_STATE],
        # A renumber whose filing line did not say where the text went. NOT a repeal --
        # `check_bulletin.UNKNOWN_TARGET` exists so no consumer can read it as one -- and
        # not something this report may quietly drop either.
        unknown_targets=[str(r.get("number")) for r in rows
                         if r.get("renumbered_to") == check_bulletin.UNKNOWN_TARGET],
    )


def check_census(c: Census, actions, states) -> list:
    """Every way the census stops being a faithful count of the notice.

    THE VOCABULARY IS CHECKED, NOT TRUSTED, for the reason `reingest_oar.py` checks its
    own: `check_bulletin.py` writes these values and a rename there leaves this counting
    rows under a heading no reader recognises, or -- worse -- filtering `gaps` on a state
    the writer no longer emits, which matches NOTHING and looks exactly like a month with
    no coverage gaps. Every argument is passed in so the rule can be fired on synthetic
    vocabularies."""
    failures = []
    for s in sorted(set(c.by_state) - set(states)):
        failures.append(Failure(
            "the-vocabulary-the-census-counts-is-the-readers", s,
            f"is a corpus state in the committed worklist that "
            f"`check_bulletin.CORPUS_STATES` does not contain ({', '.join(states)}). The "
            "report counts it under no heading -- and if the coverage-gap value is the one "
            "that moved, `gaps` is empty for a reason that is not `there were none`"))
    for a in sorted(set(c.by_action) - set(actions)):
        failures.append(Failure(
            "the-vocabulary-the-census-counts-is-the-readers", a,
            f"is an action in the committed worklist that `check_bulletin.ACTIONS` does "
            f"not contain ({', '.join(actions)}). The report counts it under a heading no "
            "consumer has a case for"))
    if MISSING_STATE not in states:
        failures.append(Failure(
            "the-vocabulary-the-census-counts-is-the-readers",
            MISSING_STATE,
            f"is the worklist state this report lists as a coverage gap, and "
            f"`check_bulletin.py` writes {', '.join(states)}. A list filtered on a value "
            "the notice no longer uses is empty, and an empty list of coverage gaps reads "
            "exactly like a month that had none")
        )
    for name, counted in (("action", c.by_action), ("corpus_state", c.by_state)):
        if sum(counted.values()) != len(c.rows):
            failures.append(Failure(
                "the-census-accounts-for-every-filing", name,
                f"counts {sum(counted.values())} of the worklist's {len(c.rows)} row(s). "
                "The counts are a partition of the same rows, so a total that is short is "
                "a filing this report is not telling anybody about"))
    return failures


# --------------------------------------------------------------- what the hashing observed


class Observation(namedtuple("Observation", "moved watched seeded unjoinable unseeded")):
    """What one `corpus-detect-changes` run saw, joined to rule numbers.

    `moved` is rules whose fetched bytes differed from a RECORDED baseline. `seeded` is the
    watched rules that HAD a baseline to differ from -- the denominator of the group-wide
    share, and the only honest one: a source with no baseline reports CHANGED every run and
    is not a changed source (ADR 0010, corpus-toolkit#145), so `unseeded` is held apart
    rather than folded into `moved`, and a source that is watched but unseeded is not one
    this run may say held still.

    `unjoinable` is watched sources whose id names no rule number. They are carried rather
    than dropped: a manifest that grew a chapter-level or index source would silently
    shrink the universe this report believes it is watching."""

    __slots__ = ()

    @property
    def compared(self) -> int:
        """How many sources this run could have seen move. DERIVED from `seeded` rather
        than carried beside it: a denominator stored separately is one that can disagree
        with the set it is meant to count."""
        return len(self.seeded)

    @property
    def share(self) -> float:
        return len(self.moved) / self.compared if self.compared else 0.0

    @property
    def group_wide(self) -> bool:
        """Whether this run's movement is the group's rather than any rule's."""
        return self.compared > 0 and self.share > GROUP_WIDE_SHARE


SOURCE_ID_RE = re.compile(r"^oar-(\d{3}-\d{3}-\d{4})$")


def watched_sources(manifest) -> tuple:
    """(rule number -> source id for every watched rule, ids that name no rule).

    The join runs off the MANIFEST, not off the drift file: the manifest is what this
    corpus undertook to watch, and a drift file lists only what moved -- deriving the
    watched set from it would make "watched" mean "changed"."""
    by_rule, unjoinable = {}, []
    for s in (manifest.get("sources") or []):
        sid = str(s.get("id") or "")
        m = SOURCE_ID_RE.match(sid)
        if m:
            by_rule.setdefault(m.group(1), sid)
        else:
            unjoinable.append(sid)
    return by_rule, unjoinable


def read_drift(path: Path, manifest) -> Observation:
    """The drift run's reading, or None where there is no reading at all.

    None IS A DISTINCT ANSWER and this module never lets it collapse into "nothing moved":
    an absent `changed-sources.tsv` means nobody hashed anything, which is the observation
    a broken fetcher and a quiet month both produce."""
    by_rule, unjoinable = watched_sources(manifest)
    ids = {sid: number for number, sid in by_rule.items()}
    # THE DENOMINATOR MATCHES `moved`'s UNIVERSE, AND IT IS A SET RATHER THAN A COUNT. Only
    # a source this join can reach AND that carries a recorded baseline could ever land in
    # `moved`. As a count it made the group-wide share smaller than the fraction of things
    # that actually moved -- a threshold quietly harder to cross, in the direction that
    # lets the per-rule claim through -- and, worse, it could not say WHICH rules had a
    # baseline, so a watched-but-unseeded rule the Bulletin named was reported as one whose
    # hash held still. It never was compared to anything.
    seeded = {ids[str(s.get("id"))] for s in (manifest.get("sources") or [])
              if str(s.get("sha256") or "").strip() and str(s.get("id")) in ids}
    try:
        raw = path.read_text()
    except OSError:
        return None
    moved, unseeded = set(), set()
    for line in raw.splitlines():
        cols = line.split("\t")
        if len(cols) < 4 or cols[0] not in ids:
            continue  # another group's source, or a row this join has no rule for
        (moved if cols[2].strip() else unseeded).add(ids[cols[0]])
    return Observation(moved=moved, watched=set(by_rule), seeded=seeded,
                       unjoinable=unjoinable, unseeded=unseeded)


# ----------------------------------------------------------------- where the two disagree


class Disagreement(namedtuple("Disagreement", "unannounced withheld agreement "
                                              "filed_not_moved not_watched quiet "
                                              "group_wide share compared")):
    """ADR 0006's four cases over one month, plus the fifth the table does not have.

    `unannounced` is the loud one and is EMPTY whenever `withheld` is not: a group-wide
    move is one event, and splitting it into N per-rule findings states N times something
    nobody observed N times."""

    __slots__ = ()

    def moved_total(self) -> list:
        """Every rule this run observed move, announced or not. Computed from the three
        buckets a moved rule can land in rather than kept as a fourth field: a total that
        is stored separately is a total that can disagree with its own parts."""
        return sorted(set(self.unannounced) | set(self.withheld) | set(self.agreement))


def classify(named: set, observation: Observation) -> Disagreement:
    """Join the notice to the observation. Pure; every input passed in.

    THE ASYMMETRY IS DELIBERATE. `moved` is positive evidence, so `unannounced` and
    `agreement` are claims this run can support. "Did not move" is not observed anywhere
    -- it is an absence from the drift file -- so `filed_not_moved` is claimed ONLY for a
    rule the manifest watches AND this run had a baseline for, and every other named rule
    goes to `not_watched`, which says no hash reading exists rather than saying the hash
    held still."""
    if observation is None:
        return None
    watched, moved = observation.watched, observation.moved
    # THE ONLY RULES THIS RUN MAY SAY HELD STILL. Watched is not enough: a source with no
    # recorded baseline was compared to nothing, and one this run reported as unseeded was
    # compared to nothing on this run either. Both are absent from `moved` for a reason
    # that is not "the bytes are the same".
    comparable = (watched & observation.seeded) - observation.unseeded
    unannounced = sorted(moved - named)
    group_wide = observation.group_wide
    return Disagreement(
        # WITHHELD, NOT DROPPED. The count and the reason are the finding; the names are
        # the thing this run declines to assert.
        unannounced=[] if group_wide else unannounced,
        withheld=unannounced if group_wide else [],
        agreement=sorted(named & moved),
        filed_not_moved=sorted((named & comparable) - moved),
        # EVERY NAMED RULE THIS RUN HAS NO READING FOR -- not watched at all, or watched
        # with nothing to compare against. Both are `could not check`, and the section that
        # prints them says which.
        not_watched=sorted(named - comparable - moved),
        quiet=len(comparable - moved - named),
        group_wide=group_wide, share=observation.share, compared=observation.compared,
    )


def check_disagreement(named: set, observation: Observation, d: Disagreement) -> list:
    """Every way the join stops being what ADR 0006 decided.

    Fired on whatever is passed in, so `--selftest` can hand it a mutated classification
    and watch each rule go red -- a rule that can only run against `classify()`'s own
    output is one that agrees with the code by construction."""
    failures = []
    if d is None:
        return failures
    comparable = (observation.watched & observation.seeded) - observation.unseeded
    for n in d.filed_not_moved:
        if n not in comparable:
            why = ("no source in the manifest watches it" if n not in observation.watched
                   else "the source that watches it carries no recorded baseline"
                   if n not in observation.seeded
                   else "this run reported its source as having no baseline to compare")
            failures.append(Failure(
                "an-unwatched-rule-is-not-an-unchanged-one", n,
                f"was filed against by the Bulletin and {why}, so no hash was compared. "
                "Reporting it as `filed, not yet served` reads its ABSENCE from the drift "
                "file as an observation that it held still -- could not check, published "
                "as is not there"))
        if n in observation.moved:
            failures.append(Failure(
                "a-filing-with-no-movement-is-not-an-alarm", n,
                "moved and was filed against: that is agreement, the third case of ADR "
                "0006's table, and it belongs in neither the without-alarm list nor the "
                "loud one"))
    for n in d.unannounced:
        if n in named:
            failures.append(Failure(
                "a-filing-with-no-movement-is-not-an-alarm", n,
                "was named by the Bulletin, so its movement was announced. Reporting it "
                "as a change nobody announced is the loud case fired on the quiet one, "
                "and the loud case is only worth anything if it is rare"))
        if n not in observation.moved:
            failures.append(Failure(
                "an-unannounced-change-is-reported-first", n,
                "is reported as a change nobody announced and this run did not observe it "
                "move. The claim rests on no evidence at all"))
    if d.group_wide and d.unannounced:
        failures.append(Failure(
            "a-group-wide-move-is-not-per-rule-notice", f"{len(d.unannounced)} rule(s)",
            f"are named individually as changes nobody announced, out of a run where "
            f"{d.share:.0%} of the {d.compared} compared source(s) moved together. A move "
            "that took the whole group is ONE event with one cause (ADR 0010) -- a footer, "
            "a template, or a stale baseline (#244) -- and naming it per rule publishes "
            "that many confident findings about rule text that nobody observed"))
    if d.group_wide and not d.withheld and (observation.moved - named):
        failures.append(Failure(
            "a-group-wide-move-is-not-per-rule-notice", "withheld",
            "is empty on a group-wide run that had unannounced movement to withhold. The "
            "finding is the count and the reason; dropping both satisfies the rule above "
            "by reporting nothing at all"))
    if observation.unjoinable:
        failures.append(Failure(
            "the-observation-accounts-for-every-watched-source",
            ", ".join(sorted(observation.unjoinable)[:5]),
            f"{len(observation.unjoinable)} watched source(s) carry an id that names no "
            "rule number, so nothing in this report can be joined to them. They are "
            "outside the universe this run believes it is watching, and a watched set "
            "that quietly shrank is a denominator that quietly moved"))
    return failures


# ---------------------------------------------------------------------------- the report


class Report(namedtuple("Report", "census disagreement drift_path unread_months")):
    """One run's whole finding: what was filed, and where it disagrees with what moved."""

    __slots__ = ()

    def findings(self) -> list:
        """(label, count) for everything this run has to say, in reporting order.

        ONE DEFINITION, because "is there anything to report" and "what does the issue
        say" are the same question and answering it twice is how a run files an empty
        issue -- or files none while holding a finding."""
        c, d = self.census, self.disagreement
        out = [("month(s) whose bulletin NOBODY HAS READ -- the newest filings this "
                "report knows nothing about", self.unread_months),
               ("changes nobody announced", len(d.unannounced) if d else 0),
               ("a group-wide move, per-rule attribution withheld",
                len(d.withheld) if d else 0),
               ("rules filed against with no hash observation at all",
                len(d.not_watched) if d else 0)]
        # An absent observation is a finding only where the Bulletin named something: with
        # nothing filed AND nothing hashed there is genuinely nothing this report knows,
        # and an issue that says so every month trains its readers to close it unread.
        if d is None and self.census.rows:
            out.append(("the disagreement could not be computed: no hash observation", 1))
        out += [("rule actions filed", len(c.rows)),
                ("filings this reader could not open", len(c.unread)),
                ("rules missing from a chapter this corpus mirrors", len(c.gaps)),
                ("renumbers whose destination the filing did not state",
                 len(c.unknown_targets))]
        return [(label, n) for label, n in out if n]

    def should_file(self) -> bool:
        """Whether this run has anything to file an issue about.

        A run with nothing to report files NO issue -- the acceptance criterion, and the
        reason this is `any(findings)` rather than a flag somebody sets."""
        return bool(self.findings())


def _bullets(numbers, per_line=8) -> list:
    """Rule numbers, wrapped. Every one of them: a list that said `and 400 more` would be
    corpus-toolkit#67 with extra steps."""
    return [", ".join(numbers[i:i + per_line]) for i in range(0, len(numbers), per_line)]


def issue_title(c: Census) -> str:
    return ISSUE_TITLE.format(bulletin=c.bulletin or "unknown bulletin")


def issue_body(r: Report) -> str:
    """The one issue's body. THE LOUD CASE IS FIRST, and everything counted is listed.

    Section order is a rule (`an-unannounced-change-is-reported-first`), not a preference:
    a finding a reader has to scroll past a 549-row census to reach is one nobody reads,
    which is the whole of corpus-toolkit#67."""
    c, d = r.census, r.disagreement
    L = [f"Generated by `{REGENERATE}` from the committed "
         f"`_meta/bulletin-worklist.yml`. Nothing here was re-fetched.", "",
         f"**{c.bulletin}** — {c.url}", "",
         f"Read {c.retrieved}; {c.filings} filing(s), {len(c.rows)} rule action(s).", ""]

    if r.unread_months:
        L += [f"> ⚠️ **{r.unread_months} bulletin(s) have been published since "
              f"{c.bulletin} and nobody has read them.** Everything below describes "
              f"{c.bulletin} and says NOTHING about the months since. Run "
              "`python3 src/check_bulletin.py` and commit the worklist.", ""]
    L += ["## What this run found", ""]
    L += [f"- {n} {label}" for label, n in r.findings()] or ["- nothing", ""]
    L += [""]

    L += [LOUD_HEADING, ""]
    if d is None:
        L += [f"{NOT_COMPUTED} No hash observation was available — `{r.drift_path}` "
              "was not written by this run, so no source was compared. That is not the "
              "same as nothing having moved: a corpus nobody hashed and a corpus where "
              "nothing changed produce the identical empty file (ADR 0006).", ""]
    elif d.group_wide:
        L += [f"**Per-rule attribution withheld.** {len(d.moved_total())} of the "
              f"{d.compared} compared source(s) moved in the same run "
              f"({d.share:.0%}), of which **{len(d.withheld)}** were not named by any "
              "filing. A move that took the whole group is one event with one cause — a "
              "footer, a template, or a stale baseline — not that many independent "
              "unannounced rule changes, so this run reports the group and declines to "
              "name the rules (ADR 0010; #244 is the live instance).", ""]
    elif d.unannounced:
        L += [f"**{len(d.unannounced)} rule(s) moved and no filing named them.** This is "
              "the one combination that means something changed that nobody announced.",
              ""] + [f"    {line}" for line in _bullets(d.unannounced)] + [""]
    else:
        L += ["None. Every source this run compared and saw move was named by a filing.",
              ""]

    L += [UNCHECKED_HEADING, ""]
    if d is None:
        L += ["Every rule the Bulletin named: no hash observation exists for this run.", ""]
    else:
        L += [f"**{len(d.not_watched)} rule(s)** the Bulletin filed against have no hash "
              "reading at all — no source in `_meta/sources/oar.yml` watches them, or the "
              "source that does carries no recorded baseline to differ from. Nothing here "
              "says whether their text moved.", ""]
        if d.not_watched:
            L += [f"    {line}" for line in _bullets(d.not_watched)] + [""]

    L += [CALM_HEADING, ""]
    if d is None:
        L += ["Not computed — see above.", ""]
    else:
        L += [f"{len(d.filed_not_moved)} rule(s) were filed against, are watched, carry a "
              "recorded baseline, and this run did not report them as moved: filed but not "
              "yet served, or served identically. Recorded, not a fault. `changed-sources."
              "tsv` lists only what CHANGED, so a source whose fetch failed is absent from "
              "it exactly as an unchanged one is (corpus-toolkit#160) — a failed fetch "
              "would land here.", ""]
        if d.filed_not_moved:
            L += [f"    {line}" for line in _bullets(d.filed_not_moved)] + [""]
        L += [f"{len(d.agreement)} rule(s) were filed against and moved (agreement); "
              f"{d.quiet} compared source(s) were silent in both signals.", ""]

    L += [COUNTS_HEADING, "", "| action | rules |", "|---|---|"]
    L += [f"| {a} | {c.by_action.get(a, 0)} |" for a in check_bulletin.ACTIONS]
    L += ["", "| what this corpus knows | rules |", "|---|---|"]
    L += [f"| {s} | {c.by_state.get(s, 0)} |" for s in check_bulletin.CORPUS_STATES]
    L += [""]

    L += ["## Unknowns", ""]
    if c.unread:
        L += [f"**{len(c.unread)} filing(s) could not be read**, so the rules they name "
              "are not in the worklist for a reason that is not *nothing happened to "
              "them*:", ""]
        for u in c.unread:
            link = f" — {u.get('url')}" if u.get("url") else ""
            L += [f"- `{u.get('filing')}` ({u.get('reason')}){link}"]
        L += [""]
    else:
        L += ["Every filing in the operative table was read.", ""]
    if c.unknown_targets:
        L += [f"**{len(c.unknown_targets)} renumber(s) did not state a destination.** A "
              "renumber with an unknown target is not a repeal — the text is somewhere:",
              ""] + [f"    {line}" for line in _bullets(c.unknown_targets)] + [""]

    L += ["## Missing from a chapter this corpus mirrors", ""]
    if c.gaps:
        L += [f"**{len(c.gaps)} rule(s)** were filed against in chapters this corpus "
              "mirrors and are absent from `rules/`. A coverage gap, not a boundary:", ""]
        L += [f"    {line}" for line in _bullets(c.gaps)] + [""]
    else:
        L += ["None.", ""]
    return "\n".join(L).rstrip() + "\n"


def check_body(r: Report, body: str) -> list:
    """Everything the census counted must be IN the body, and the body must fit.

    This is the half no rule about the report's shape can state: a report that dropped the
    121 coverage-gap rules, or every unread filing, satisfies every other rule in this
    module and tells a reader that the month was clean."""
    failures = []
    for u in r.census.unread:
        if str(u.get("filing")) not in body:
            failures.append(Failure(
                "an-unread-filing-reaches-the-report", str(u.get("filing")),
                "is a filing this reader could not open and the issue body does not name "
                "it. Its rules are missing from the worklist for a reason that is not "
                "`nothing happened to them`, and an issue that does not say so publishes "
                "a parse failure as a quiet month"))
    for n in r.census.gaps:
        if n not in body:
            failures.append(Failure(
                "a-coverage-gap-reaches-the-report", n,
                "is a rule filed against in a chapter this corpus mirrors and absent from "
                "`rules/`, and the issue body does not name it. The count alone sends "
                "nobody anywhere"))
    # THE ORDER, GATED RATHER THAN ASSERTED IN A DOCSTRING. `issue_body` says the loud
    # case is first and two constants are declared for reading it back, and until this
    # rule existed nothing in `--check` compared their positions: a reworded or reordered
    # section passed CI with the finding buried under a 549-row census, which is
    # corpus-toolkit#67's failure reproduced inside the fix for it.
    where = {h: body.find(h) for h in (LOUD_HEADING, UNCHECKED_HEADING, CALM_HEADING,
                                       COUNTS_HEADING)}
    for h, at in where.items():
        if at < 0:
            failures.append(Failure(
                "an-unannounced-change-is-reported-first", h,
                "is a section this module declares and the body does not contain. The two "
                "rules that read the body back find nothing, and a search that finds "
                "nothing returns the same clean answer as one that finds everything in "
                "the right order"))
    if all(at >= 0 for at in where.values()) and not (
            where[LOUD_HEADING] < where[UNCHECKED_HEADING] < where[CALM_HEADING]
            < where[COUNTS_HEADING]):
        failures.append(Failure(
            "an-unannounced-change-is-reported-first",
            " then ".join(h for h, _ in sorted(where.items(), key=lambda kv: kv[1])),
            f"is the order this body puts its sections in. `{LOUD_HEADING}` is the one "
            "combination that means something changed nobody announced, and a finding a "
            "reader reaches only after scrolling past the census is one nobody reads"))
    if len(body) > BODY_LIMIT:
        failures.append(Failure(
            "the-run-files-one-issue", f"{len(body)} characters",
            f"is over GitHub's {BODY_LIMIT}-character issue body limit, so the filing "
            "would fail or be cut. Report less by REPORTING FEWER FINDINGS, never by "
            "silently truncating the lists"))
    return failures


def issues_for(r: Report) -> list:
    """The issues this run files: exactly one, or none.

    A LIST, so `the-run-files-one-issue` has something to count. The number this returns
    is the whole of ADR 0006's "one issue per run, not per rule": August 2026 named 549
    rule actions and a 25-issue cap makes per-rule filing a way of reporting 25 of them."""
    if not r.should_file():
        return []
    return [(issue_title(r.census), issue_body(r))]


def check_filing(r: Report, planned: list) -> list:
    failures = []
    if len(planned) > 1:
        failures.append(Failure(
            "the-run-files-one-issue", f"{len(planned)} issues",
            f"would be filed by one run over {len(r.census.rows)} rule action(s). ADR "
            "0006 files ONE issue per run: the tracker caps a drift run at 25 issues, so "
            "a per-rule filing reports the first 25 findings and drops the rest on "
            "stderr, which is corpus-toolkit#67"))
    if planned and not r.should_file():
        failures.append(Failure(
            "a-run-with-nothing-to-report-files-nothing", f"{len(planned)} issue(s)",
            "would be filed by a run holding no finding at all. An issue that says "
            "nothing trains its readers to close this report unread"))
    if r.should_file() and not planned:
        failures.append(Failure(
            "a-run-with-nothing-to-report-files-nothing",
            "; ".join(f"{n} {l}" for l, n in r.findings()),
            "are findings this run holds and it plans to file nothing. The rule is that a "
            "run with NOTHING to report files nothing -- satisfying it by filing nothing "
            "ever is the same silence corpus-toolkit#67 is about"))
    return failures


def check_no_observation(r: Report, body: str) -> list:
    """A run with no hash reading must SAY it has none.

    The failure this rule exists for is a body that renders `0 changes nobody announced`
    from an observation it never had: a positive claim about Oregon rule text derived from
    an empty file."""
    if r.disagreement is not None:
        return []
    # SCOPED TO THE SECTION, because "None." is a truthful answer under other headings
    # and a substring search over the whole body would report the coverage-gap section's
    # honest `None.` as a disagreement claim -- a guard firing on the wrong condition.
    section = body.split(LOUD_HEADING, 1)[-1].split("\n## ", 1)[0]
    if A_COUNT_OF_RULES_RE.search(section) or NOT_COMPUTED not in section:
        return [Failure(
            "no-observation-is-not-no-disagreement", r.census.bulletin or "this run",
            "has no hash observation and its issue body reports a disagreement result "
            "anyway. `changed-sources.tsv` absent means nobody hashed anything, which is "
            "exactly the file a corpus with no drift produces -- reporting the second is "
            "the substitution ADR 0006 rejected replacement over")]
    return []


# ------------------------------------------------------- the two facts in workflow files


CRON_RE = re.compile(r"^\s*-\s*cron:\s*[\"']([^\"']+)[\"']", re.M)


def workflow(text):
    """A workflow file's crons and its LIVE run commands, or None if it does not parse.

    STRUCTURE, NOT A SUBSTRING SCAN. Both gates below used to ask whether a string appeared
    anywhere in the file, which a COMMENTED-OUT job satisfies -- `scheduled.yml` explains
    its own history in 60 lines of comments, and the words `--group oar` sit in them. A job
    switched off with `if: false`, or a step commented out, would have kept both gates green
    while nothing ran. `on:` is read under both spellings because YAML 1.1 parses the bare
    word as the boolean True and PyYAML still does."""
    try:
        d = yaml.safe_load(text) if text is not None else None
    except yaml.YAMLError:
        return None
    if not isinstance(d, dict):
        return None
    on = d.get("on", d.get(True)) or {}
    sched = (on.get("schedule") or []) if isinstance(on, dict) else []
    crons = [str(s.get("cron")) for s in sched if isinstance(s, dict) and s.get("cron")]
    runs = []
    for j in (d.get("jobs") or {}).values():
        if not isinstance(j, dict) or str(j.get("if", "")).strip().lower() == "false":
            continue
        for st in (j.get("steps") or []):
            if isinstance(st, dict) and "run" in st \
                    and str(st.get("if", "")).strip().lower() != "false":
                runs.append(" ".join(str(st["run"]).split()))
    return crons, runs


def _runs_that(runs, needle) -> bool:
    """Whether any LIVE run step carries `needle`.

    ONE PREDICATE, because two rules ask it of two different files for two different
    reasons -- that THIS workflow produces the observation, and that the DRIFT workflow
    keeps producing one beside it -- and a second spelling is where a flag reworded
    upstream stops being recognised in one place and not the other."""
    return any(needle in r for r in runs)


def check_schedule(text) -> list:
    """The reader runs on a cron, and the cron is the Bulletin's cadence.

    READ OFF THE WORKFLOW FILE, because that is where the cadence actually lives -- the
    same argument `scheduled.yml`'s own header makes about `recheck:` configuring nothing.
    A schedule that exists only in a docstring is a schedule nobody is running."""
    parsed = workflow(text)
    if parsed is None:
        return [Failure("the-reader-runs-on-the-bulletins-cadence", str(WORKFLOW),
                        "does not exist or does not parse, so nothing runs this reader on "
                        "a schedule and the mechanism is back to depending on somebody "
                        "remembering")]
    crons, runs = parsed
    failures = []
    if CRON not in crons:
        failures.append(Failure(
            "the-reader-runs-on-the-bulletins-cadence", ", ".join(crons) or "no cron",
            f"is what the workflow schedules and this module declares {CRON!r}. Two "
            "spellings of one cadence is the drift this repository keeps finding"))
    for c in crons:
        parts = c.split()
        if len(parts) != 5:
            failures.append(Failure("the-reader-runs-on-the-bulletins-cadence", c,
                                    "is not a five-field cron expression"))
            continue
        _, _, dom, month, _ = parts
        if month != "*" or not dom.isdigit():
            failures.append(Failure(
                "the-reader-runs-on-the-bulletins-cadence", c,
                "is not MONTHLY on a fixed day. The Oregon Bulletin is published on the "
                "first business day of every month, so a reader on any other cadence "
                "either re-reads a bulletin it has read or skips one entirely -- and a "
                "skipped month is a repeal served here as though nothing had happened"))
        elif int(dom) < EARLIEST_DAY:
            failures.append(Failure(
                "the-reader-runs-on-the-bulletins-cadence", c,
                f"fires on day {dom} of the month and the Bulletin appears on the first "
                f"BUSINESS day, which is as late as the {EARLIEST_DAY}th -- the 1st a "
                "Saturday, the 2nd a Sunday, the 3rd a Monday holiday. A run before it is "
                "published reads last month's bulletin and reports it as this month's"))
    if not _runs_that(runs, f"--group {DRIFT_GROUP}"):
        failures.append(Failure(
            "the-scheduled-run-fetches-the-group-this-reader-joins", f"--group {DRIFT_GROUP}",
            "is the group this reader joins the drift observation on, and the workflow "
            "fetches a different one. The run would produce a `changed-sources.tsv` with "
            "no source this module can join, which is byte-identical to a group where "
            "nothing moved"))
    if not _runs_that(runs, "bulletin_report.py"):
        failures.append(Failure(
            "the-reader-runs-on-the-bulletins-cadence", str(WORKFLOW),
            "schedules no LIVE step that invokes this reader. A cron on a workflow whose "
            "only mention of the module is a comment, or a step switched off with "
            "`if: false`, is a cadence that runs nothing"))
    return failures


def check_drift_still_runs(text) -> list:
    """Hashing still runs beside this, which ADR 0006 requires and this file cannot assume.

    ADR 0006 REJECTED REPLACEMENT. Hashing is kept for exactly one job it alone can do --
    detecting change nobody announced -- so a change that quietly dropped `--group oar`
    from the monthly drift job would leave the loud case of the four-case table
    permanently empty, and an empty loud case looks like good news."""
    parsed = workflow(text)
    if parsed is None:
        return [Failure("hash-drift-still-runs", str(DRIFT_WORKFLOW),
                        "does not exist or does not parse, so nothing hashes the OAR "
                        "sources on a schedule. ADR 0006 keeps hashing for the one job it "
                        "alone can do")]
    crons, runs = parsed
    failures = []
    if not crons:
        failures.append(Failure("hash-drift-still-runs", str(DRIFT_WORKFLOW),
                                "schedules no cron at all, so the drift detection this "
                                "report reads runs only when somebody asks for it"))
    if not _runs_that(runs, f"--group {DRIFT_GROUP}"):
        failures.append(Failure(
            "hash-drift-still-runs", f"--group {DRIFT_GROUP}",
            "is in no LIVE step of the scheduled drift workflow, so the OAR sources are "
            "no longer "
            "hashed on the monthly cadence. Hashing is the ONLY signal that can see a "
            "change nobody announced, and without it `silent` and `unchanged` become the "
            "same observation -- the substitution ADR 0006 rejected replacement over"))
    return failures


def check_drift_filename(source) -> list:
    """The file this reads is the file the toolkit writes.

    `changed-sources.tsv` is a literal in `corpus_toolkit.sources.changes` and a literal
    here, with nothing between them. Renamed there, this reads a file nothing writes --
    and `read_drift` correctly returns None for a file that is not there, so every run
    would report NO HASH OBSERVATION forever, which is a defensible answer to a question
    nobody is asking any more."""
    if source is None:
        return [Failure(
            "the-drift-observation-is-the-file-the-toolkit-writes", DRIFT_FILE,
            "could not be checked against corpus-toolkit: "
            "`corpus_toolkit.sources.changes` is not importable here. That is a rule this "
            "run did not apply, not a rule that passed")]
    if DRIFT_FILE not in source:
        return [Failure(
            "the-drift-observation-is-the-file-the-toolkit-writes", DRIFT_FILE,
            "is the drift observation this module reads and "
            "`corpus_toolkit.sources.changes` no longer writes a file by that name. This "
            "report would find no observation on every run, which is indistinguishable "
            "from a corpus where nothing ever moves")]
    return []


def _toolkit_source():
    try:
        from corpus_toolkit.sources import changes
        return Path(changes.__file__).read_text()
    except Exception:
        return None


def _text(path: Path):
    try:
        return path.read_text()
    except OSError:
        return None


# ------------------------------------------------------------------------------ commands


def drift_path() -> Path:
    return REPO_ROOT / DRIFT_FILE


def build() -> tuple:
    """(Report, failures) from committed data plus whatever drift reading exists."""
    worklist = load_worklist()
    if not isinstance(worklist, dict):
        return None, [Failure(
            "the-notice-is-readable", str(WORKLIST),
            "is absent or unreadable, so this run has no notice to report. A report built "
            "from no worklist is an empty one, and an empty one reads like a quiet month")]
    c = census(worklist)
    try:
        manifest = yaml.safe_load(MANIFEST.read_text())
    except (OSError, yaml.YAMLError):
        # NAMED, NOT RAISED. Without the manifest the watched set is unknown, so every
        # named rule would fall outside it and the whole month would report as `not
        # watched` -- a clean, wrong answer. A gate that dies instead of naming its rule
        # is what #226 exists to close.
        return Report(census=c, disagreement=None, drift_path=drift_path().name,
                      unread_months=months_unread(c.bulletin, date.today())), [Failure(
            "the-observation-accounts-for-every-watched-source", str(MANIFEST),
            "is absent or unreadable, so this run does not know which rules hashing "
            "watches. Every rule would classify as never watched and the report would say "
            "so with the same confidence it uses for a rule that genuinely has no source")]
    path = drift_path()
    observation = read_drift(path, manifest)
    named = {str(r.get("number")) for r in c.rows}
    d = classify(named, observation)
    failures = check_census(c, check_bulletin.ACTIONS, check_bulletin.CORPUS_STATES)
    failures += check_disagreement(named, observation, d)
    return Report(census=c, disagreement=d, drift_path=path.name,
                  unread_months=months_unread(c.bulletin, date.today())), failures


def cmd_check() -> int:
    r, failures = build()
    if r is not None:
        body = issue_body(r)
        failures += check_body(r, body) + check_filing(r, issues_for(r))
        failures += check_no_observation(r, body)
    failures += check_schedule(_text(WORKFLOW))
    failures += check_drift_still_runs(_text(DRIFT_WORKFLOW))
    failures += check_drift_filename(_toolkit_source())
    if report(failures):
        print(f"\n{len(failures)} bulletin-report violation(s)", file=sys.stderr)
        return 1
    _census_line(r)
    return 0


def _census_line(r: Report) -> None:
    """The numbers, on every run. A guarantee that can only be watched NOT firing is one
    nobody can tell from a guard that stopped running."""
    d = r.disagreement
    print(f"{r.census.bulletin}: " + ", ".join(f"{n} {l}" for l, n in r.findings()))
    if d is None:
        print(f"no hash observation ({r.drift_path} absent) — the disagreement was NOT "
              "computed, which is not the same as no disagreement")
    else:
        print(f"hash: {len(d.moved_total())} of {d.compared} compared source(s) moved "
              f"({d.share:.0%}){' — GROUP-WIDE, per-rule attribution withheld' if d.group_wide else ''}; "
              f"{len(d.agreement)} agreement, {len(d.filed_not_moved)} filed and still, "
              f"{len(d.not_watched)} filed and never watched, {d.quiet} quiet")
    print(f"{len(issues_for(r))} issue(s) would be filed")


def cmd_report() -> int:
    r, failures = build()
    if report(failures):
        return 1
    planned = issues_for(r)
    _census_line(r)
    print()
    for title, body in planned:
        print(f"=== {title} ===")
        print(body)
    print("DRY RUN — nothing was filed. Pass --file-issue to file it.")
    return 0


def _gh(args) -> subprocess.CompletedProcess:
    return subprocess.run(["gh"] + args, capture_output=True, text=True)


def cmd_file_issue() -> int:
    """File the one issue, once.

    IDEMPOTENT BY TITLE. A re-run in the same month must find the issue the first run
    opened rather than opening a second: the cron can fire twice, a `workflow_dispatch`
    can follow a schedule, and a report that stacked one issue per attempt is the per-rule
    filing this design rejected, arriving by another route."""
    r, failures = build()
    if report(failures):
        return 1
    planned = issues_for(r)
    _census_line(r)
    if not planned:
        print("nothing to report — no issue filed")
        return 0
    title, body = planned[0]
    # LISTED AND COMPARED EXACTLY, not searched. GitHub's search index lags a new issue by
    # seconds to minutes and its query grammar would have to survive an em dash, an equals
    # sign and a parenthesised `bulltnRsn` -- a search that silently matched nothing would
    # file a second issue for the month, which is the per-run guarantee broken by the one
    # mechanism meant to keep it.
    found = _gh(["issue", "list", "--state", "all", "--json", "number,title",
                 "--limit", str(ISSUE_SCAN_LIMIT)])
    if found.returncode != 0:
        print(f"gh issue list failed: {found.stderr.strip()}", file=sys.stderr)
        return 1
    existing = json.loads(found.stdout or "[]")
    for issue in existing:
        if issue.get("title") == title:
            print(f"already filed as #{issue['number']} — nothing to do")
            return 0
    if len(existing) >= ISSUE_SCAN_LIMIT:
        # REFUSE RATHER THAN RISK A DUPLICATE. The scan filled its page, so an issue with
        # this title may sit past the end of it and this run cannot tell. Filing anyway
        # trades a certain duplicate for an assumed absence.
        print(f"{len(existing)} issue(s) is the whole scan window, so this run cannot "
              f"tell whether {title!r} already exists. Refusing to file — raise "
              f"ISSUE_SCAN_LIMIT.", file=sys.stderr)
        return 1
    made = _gh(["issue", "create", "--title", title, "--body", body]
               + [a for label in ISSUE_LABELS for a in ("--label", label)])
    if made.returncode != 0:
        print(f"gh issue create failed: {made.stderr.strip()}", file=sys.stderr)
        return 1
    print(made.stdout.strip())
    return 0


# ------------------------------------------------------------------------------ selftest
#
# THE PROOF THAT EVERYTHING ABOVE CAN FAIL. Synthetic fixtures except where a proof says
# otherwise -- the two that matter most are fired against the COMMITTED worklist and the
# COMMITTED workflow files, because a rule proved only against a fixture is one nobody has
# watched work on the thing it governs.

FIXTURE_BULLETIN = "August 2026 (bulltnRsn=1761)"


def _fixture_worklist(*actions, unread=(), filings=3, bulletin=FIXTURE_BULLETIN) -> dict:
    """A worklist in `check_bulletin.render_worklist()`'s shape. Each action is
    (number, action, corpus_state) or (number, action, corpus_state, renumbered_to)."""
    rules = []
    for a in actions:
        row = {"number": a[0], "action": a[1], "corpus_state": a[2]}
        if len(a) > 3:
            row["renumbered_to"] = a[3]
        rules.append(row)
    return {"bulletin": bulletin,
            "bulletin_url": f"https://secure.sos.state.or.us/oard/displayBulletin.action",
            "retrieved": "2026-08-22", "filings": filings,
            "unread_filings": [dict(u) for u in unread], "rules": rules}


def _fixture_manifest(*numbers, seeded=True) -> dict:
    return {"group": DRIFT_GROUP, "sources": [
        {"id": f"oar-{n}", "url": f"https://x/{n}",
         "sha256": ("a" * 64) if seeded else ""} for n in numbers]}


def _fixture_drift(tmp: Path, *numbers, unseeded=()) -> Path:
    tmp.write_text("".join(f"oar-{n}\thttps://x/{n}\t{'b' * 64}\t{'c' * 64}\n"
                           for n in numbers)
                   + "".join(f"oar-{n}\thttps://x/{n}\t\t{'c' * 64}\n" for n in unseeded))
    return tmp


def _observe(tmp, manifest, *moved, unseeded=()):
    return read_drift(_fixture_drift(tmp, *moved, unseeded=unseeded), manifest)


def _report_of(worklist, observation, unread_months=0) -> Report:
    c = census(worklist)
    named = {str(r.get("number")) for r in c.rows}
    return Report(census=c, disagreement=classify(named, observation),
                  drift_path=DRIFT_FILE, unread_months=unread_months)


def _proof_the_census_is_a_faithful_count(check) -> None:
    """THE HALF NO RULE ABOUT THE REPORT'S SHAPE CAN STATE. Every rule about what the body
    looks like is satisfied by a body carrying nothing, so these are fired by taking
    information AWAY from a census that had it."""
    wl = _fixture_worklist(("999-001-0010", "amend", "held"),
                           ("999-002-0020", "adopt", MISSING_STATE))
    c = census(wl)
    check("a census with an action the reader never emits is caught",
          any(f.rule == "the-vocabulary-the-census-counts-is-the-readers" and f.site == "amend"
              for f in check_census(c, ("adopt",), check_bulletin.CORPUS_STATES)))
    check("a coverage-gap state the reader no longer writes is caught -- the filter that "
          "matches nothing and reads like a month with no gaps",
          any(f.rule == "the-vocabulary-the-census-counts-is-the-readers"
              and f.site == MISSING_STATE
              for f in check_census(c, check_bulletin.ACTIONS, ("held",))))
    # DISTINCT FROM THE RULE ABOVE: the coverage-gap value is still declared, and a row
    # arrived carrying a state nothing here has a heading for. Fired separately so the two
    # branches are not proved by one assertion that either could satisfy.
    stray = census(_fixture_worklist(("999-001-0010", "amend", "in_corpus")))
    check("a worklist row carrying a corpus state the reader never writes is caught",
          any(f.rule == "the-vocabulary-the-census-counts-is-the-readers"
              and f.site == "in_corpus"
              for f in check_census(stray, check_bulletin.ACTIONS,
                                    check_bulletin.CORPUS_STATES)))
    short = c._replace(by_action=Counter({"amend": 1}))
    check("counts that do not add up to the rows they came from are caught",
          any(f.rule == "the-census-accounts-for-every-filing" and f.site == "action"
              for f in check_census(short, check_bulletin.ACTIONS,
                                    check_bulletin.CORPUS_STATES)))
    check("...and the committed vocabularies are the ones this census counts through",
          not check_census(census(load_worklist()), check_bulletin.ACTIONS,
                           check_bulletin.CORPUS_STATES))
    check("the coverage gap is NAMED, not only counted", c.gaps == ["999-002-0020"])


def _proof_the_body_carries_what_it_counts(check) -> None:
    """A REPORT PASSES EVERY OTHER RULE HERE BY CARRYING LESS. Fired by deleting from the
    body, which is exactly what a well-meant `and 400 more` would do."""
    wl = _fixture_worklist(("999-001-0010", "amend", "held"),
                           ("999-002-0020", "adopt", MISSING_STATE),
                           ("999-003-0030", "renumber", "held",
                            check_bulletin.UNKNOWN_TARGET),
                           unread=[{"filing": "AON 12-2026", "reason": "filing-unreadable",
                                    "url": "https://records/1"}])
    r = _report_of(wl, None)
    body = issue_body(r)
    check("the committed shape of an unread filing reaches the body", "AON 12-2026" in body)
    check("a body that dropped the unread filing is caught",
          any(f.rule == "an-unread-filing-reaches-the-report"
              for f in check_body(r, body.replace("AON 12-2026", "AON 99-9999"))))
    check("the coverage-gap rule number reaches the body", "999-002-0020" in body)
    check("a body that dropped the coverage-gap rules is caught",
          any(f.rule == "a-coverage-gap-reaches-the-report" and f.site == "999-002-0020"
              for f in check_body(r, body.replace("999-002-0020", ""))))
    check("a body that put the counts above the loud case is caught",
          any(f.rule == "an-unannounced-change-is-reported-first"
              for f in check_body(r, COUNTS_HEADING + "\n" + body)))
    check("a body that dropped a section the two body-readers slice on is caught",
          any(f.rule == "an-unannounced-change-is-reported-first"
              and f.site == CALM_HEADING
              for f in check_body(r, body.replace(CALM_HEADING, "## Something else"))))
    check("...and the real body is in the declared order",
          not [f for f in check_body(r, body)
               if f.rule == "an-unannounced-change-is-reported-first"])
    check("a body over GitHub's issue limit is caught rather than truncated",
          any(f.rule == "the-run-files-one-issue"
              for f in check_body(r, "x" * (BODY_LIMIT + 1))))
    check("a renumber with no stated destination is reported and is not a repeal",
          "999-003-0030" in body and "not a repeal" in body)
    check("...and the committed worklist's own body carries all of its coverage gaps",
          not check_body(*(lambda x: (x, issue_body(x)))(build()[0])))


def _proof_one_issue_or_none(check) -> None:
    """ONE ISSUE PER RUN, AND NONE WHEN THERE IS NOTHING. Both directions, because a
    `should_file` that always says no satisfies the acceptance criterion by never
    reporting anything -- the silence corpus-toolkit#67 is about."""
    many = _fixture_worklist(*[(f"999-001-{i:04d}", "amend", "held") for i in range(40)])
    r = _report_of(many, None)
    check("40 rule actions produce exactly ONE issue", len(issues_for(r)) == 1)
    check("a run that planned an issue per rule is caught",
          any(f.rule == "the-run-files-one-issue" for f in check_filing(
              r, [(f"t{i}", "b") for i in range(40)])))
    empty = _report_of(_fixture_worklist(filings=0), None)
    check("a run with nothing filed, nothing unread and no observation has no finding",
          empty.findings() == [] and not empty.should_file())
    check("...and files no issue", issues_for(empty) == [])
    check("a run that filed an issue holding no finding is caught",
          any(f.rule == "a-run-with-nothing-to-report-files-nothing"
              for f in check_filing(empty, [("t", "b")])))
    check("a run holding findings and filing nothing is caught -- the other direction, "
          "which a always-file-nothing implementation would pass",
          any(f.rule == "a-run-with-nothing-to-report-files-nothing"
              for f in check_filing(r, [])))
    check("...and the COMMITTED worklist is a run that must file",
          build()[0].should_file() and len(issues_for(build()[0])) == 1)


def _proof_the_four_cases(check, tmp) -> None:
    """ADR 0006'S TABLE, AND THE FIFTH CASE THE TABLE DOES NOT HAVE.

    Every case is built from POSITIVE evidence in the fixture -- a rule that is watched, a
    rule that moved, a rule the bulletin named -- so no outcome here is reached by an
    absence being read as a fact."""
    # TWENTY WATCHED SOURCES AND TWO THAT MOVED, so the run is 10% and the group-wide
    # guard is NOT what decides these cases. A four-source fixture with two movers is 50%
    # and every per-rule outcome below would be withheld -- the guard passing the proofs
    # for the classification, which is a proof of the wrong thing.
    manifest = _fixture_manifest(*[f"999-001-{i:04d}" for i in range(10, 210, 10)])
    # 0010 named + moved (agreement); 0020 named + watched + still; 0030 moved + unnamed
    # (LOUD); the rest watched, still, unnamed (quiet); 888-001-0010 named + NOT watched.
    obs = _observe(tmp, manifest, "999-001-0010", "999-001-0030")
    named = {"999-001-0010", "999-001-0020", "888-001-0010"}
    d = classify(named, obs)
    check("named and moved is agreement", d.agreement == ["999-001-0010"])
    check("named and still is recorded WITHOUT alarm", d.filed_not_moved == ["999-001-0020"])
    check("moved and unnamed is the LOUD case", d.unannounced == ["999-001-0030"])
    check("silent and still is counted, not listed", d.quiet == 17)
    check("named and never watched is its own outcome, not `still`",
          d.not_watched == ["888-001-0010"]
          and "888-001-0010" not in d.filed_not_moved)
    body = issue_body(_report_of(_fixture_worklist(*[(n, "amend", "held") for n in
                                                     sorted(named)]), obs))
    check("the loud case is reported FIRST -- before the without-alarm section",
          body.index("Changed with nobody announcing it")
          < body.index("Filed, no movement observed"))
    check("...and before the counts a reader would otherwise scroll past",
          body.index("Changed with nobody announcing it") < body.index("## Counts"))
    # WATCHED BUT NEVER SEEDED is the quieter half of the same rule: the source exists,
    # so `watched` alone would let the claim through, and it has been compared to nothing.
    dry = dict(manifest)
    dry["sources"] = [dict(s, sha256="") if s["id"] == "oar-999-001-0020" else s
                      for s in manifest["sources"]]
    unbaselined = _observe(tmp, dry, "999-001-0010", "999-001-0030")
    check("a rule watched by a source with NO recorded baseline is `could not check`, "
          "never `filed, not yet served`",
          "999-001-0020" in classify(named, unbaselined).not_watched
          and "999-001-0020" not in classify(named, unbaselined).filed_not_moved)
    check("...and claiming it held still is caught",
          any(f.rule == "an-unwatched-rule-is-not-an-unchanged-one"
              and f.site == "999-001-0020"
              for f in check_disagreement(named, unbaselined, classify(
                  named, unbaselined)._replace(filed_not_moved=["999-001-0020"]))))
    check("an unwatched rule reported as `filed, not yet served` is caught",
          any(f.rule == "an-unwatched-rule-is-not-an-unchanged-one"
              and f.site == "888-001-0010"
              for f in check_disagreement(named, obs, d._replace(
                  filed_not_moved=["999-001-0020", "888-001-0010"]))))
    check("a rule the Bulletin NAMED reported as a change nobody announced is caught",
          any(f.rule == "a-filing-with-no-movement-is-not-an-alarm"
              and f.site == "999-001-0010"
              for f in check_disagreement(named, obs,
                                          d._replace(unannounced=["999-001-0010"]))))
    check("a rule reported as unannounced that this run never saw move is caught",
          any(f.rule == "an-unannounced-change-is-reported-first"
              and f.site == "999-009-9999"
              for f in check_disagreement(named, obs,
                                          d._replace(unannounced=["999-009-9999"]))))
    check("a rule that moved AND was filed against, put in the without-alarm list, is caught",
          any(f.rule == "a-filing-with-no-movement-is-not-an-alarm"
              and f.site == "999-001-0010"
              for f in check_disagreement(named, obs,
                                          d._replace(filed_not_moved=["999-001-0010"]))))
    check("...and the honest classification fires none of them",
          not check_disagreement(named, obs, d))
    # AN UNSEEDED SOURCE IS NOT A CHANGED SOURCE (ADR 0010, corpus-toolkit#145): it reports
    # CHANGED every run because it has nothing to differ from.
    unseeded = _observe(tmp, manifest, "999-001-0030", unseeded=("999-001-0040",))
    check("a source with no recorded baseline is not counted as one that moved",
          classify(named, unseeded).unannounced == ["999-001-0030"]
          and unseeded.unseeded == {"999-001-0040"})
    # A WATCHED SOURCE THAT NAMES NO RULE is carried, not dropped.
    odd = dict(manifest)
    odd["sources"] = manifest["sources"] + [{"id": "oar-chapter-125-index",
                                             "url": "https://x", "sha256": "a" * 64}]
    strange = _observe(tmp, odd, "999-001-0030")
    check("a watched source whose id names no rule is reported, not silently dropped",
          any(f.rule == "the-observation-accounts-for-every-watched-source"
              for f in check_disagreement(named, strange, classify(named, strange))))


def _proof_a_group_wide_move_is_not_per_rule_notice(check, tmp) -> None:
    """THE GUARD THAT KEEPS THE LOUD CASE HONEST, fired on the real shape of #244.

    This is the criterion this module could most easily satisfy vacuously: with no drift
    file the loud list is empty and every rule about it passes. So the guard is fired on a
    run where 100 of 100 compared sources moved -- what the OARD footer's version bump
    does to every recorded baseline -- and watched refusing to name them."""
    numbers = [f"999-001-{i:04d}" for i in range(100)]
    manifest = _fixture_manifest(*numbers)
    everything = _observe(tmp, manifest, *numbers)
    named = {"999-001-0000"}
    d = classify(named, everything)
    check("a run where every compared source moved is group-wide", d.group_wide
          and d.share == 1.0)
    check("...and names NOT ONE rule as a change nobody announced", d.unannounced == [])
    check("...while withholding, and saying how many, is the finding", len(d.withheld) == 99)
    check("...and the body says the attribution was withheld and why",
          "Per-rule attribution withheld" in issue_body(
              _report_of(_fixture_worklist(("999-001-0000", "amend", "held")), everything)))
    check("naming them per rule on a group-wide run is caught",
          any(f.rule == "a-group-wide-move-is-not-per-rule-notice"
              for f in check_disagreement(named, everything,
                                          d._replace(unannounced=sorted(set(numbers) - named)))))
    check("withholding the names AND the count -- reporting nothing at all -- is caught",
          any(f.rule == "a-group-wide-move-is-not-per-rule-notice" and f.site == "withheld"
              for f in check_disagreement(named, everything, d._replace(withheld=[]))))
    # AND THE GUARD MUST NOT SWALLOW THE FINDING IT EXISTS FOR. One rule moving out of a
    # hundred is the loud case and is named.
    one = _observe(tmp, manifest, "999-001-0050")
    check("a single unannounced change out of 100 compared sources is still NAMED",
          classify(named, one).unannounced == ["999-001-0050"]
          and not classify(named, one).group_wide)
    check("...and the threshold is where the two part company",
          classify(named, _observe(tmp, manifest, *numbers[:21])).group_wide
          and not classify(named, _observe(tmp, manifest, *numbers[:20])).group_wide)


def _proof_no_observation_is_not_no_disagreement(check, tmp) -> None:
    """COULD NOT CHECK IS NEVER REPORTED AS IS NOT THERE, on the signal whose absence is
    hardest to see: an unwritten `changed-sources.tsv` is byte-identical to the one a
    corpus with no drift produces."""
    manifest = _fixture_manifest("999-001-0010")
    missing = read_drift(tmp / "nothing-here.tsv", manifest)
    check("an absent drift file is None, not an empty observation", missing is None)
    wl = _fixture_worklist(("999-001-0010", "amend", "held"))
    r = _report_of(wl, missing)
    body = issue_body(r)
    check("the body says the disagreement was NOT COMPUTED", NOT_COMPUTED in body)
    section = body.split(LOUD_HEADING, 1)[-1].split("\n## ", 1)[0]
    check("...and states no count of rules at all in that section",
          not A_COUNT_OF_RULES_RE.search(section))
    check("...and the run still has a finding to file", r.should_file())
    check("a body that reported a clean disagreement result from no observation is caught",
          any(f.rule == "no-observation-is-not-no-disagreement"
              for f in check_no_observation(
                  r, body.replace(NOT_COMPUTED, "None. 0 rule(s) moved unannounced."))))
    check("...and a body that simply stopped mentioning it is caught too",
          any(f.rule == "no-observation-is-not-no-disagreement"
              for f in check_no_observation(r, LOUD_HEADING)))
    empty_file = _fixture_drift(tmp / "empty.tsv")
    check("an EMPTY drift file is an observation that nothing moved, and is not None",
          read_drift(empty_file, manifest) is not None
          and read_drift(empty_file, manifest).moved == set())


def _wf(cron=CRON, module="python3 src/bulletin_report.py --file-issue",
        group=None, job_if=None, step_if=None) -> str:
    """A workflow file in the committed one's shape. Real YAML, because both gates parse
    rather than scan -- a fixture that was only a string would prove nothing about the
    thing that broke them, which was a job switched off and a comment left behind."""
    group = f"changes --group {DRIFT_GROUP}" if group is None else group
    return yaml.safe_dump({
        "on": {"schedule": [{"cron": cron}] if cron else [], "workflow_dispatch": None},
        "jobs": {"report": dict(
            {"if": job_if} if job_if is not None else {},
            **{"steps": [{"run": group},
                         dict({"if": step_if} if step_if is not None else {},
                              **{"run": module})]})},
    }, sort_keys=False)


def _proof_the_two_facts_in_workflow_files(check) -> None:
    """THE CADENCE AND THE OTHER SIGNAL, read off the files where they actually live.

    Both are fired on synthetic workflows FIRST -- a rule compared only against the
    committed file it was written from passes forever -- and then on the committed files.
    Every synthetic one is COMPLETE BUT FOR THE THING UNDER TEST, so a proof cannot pass
    because the fixture was missing something else."""
    check("a workflow with no cron at all is caught",
          any(f.rule == "the-reader-runs-on-the-bulletins-cadence"
              for f in check_schedule(_wf(cron=None))))
    check("a workflow file that does not exist is caught, and is not a pass",
          any(f.rule == "the-reader-runs-on-the-bulletins-cadence"
              for f in check_schedule(None)))
    check("a workflow file that does not parse is caught, and is not a pass",
          any(f.rule == "the-reader-runs-on-the-bulletins-cadence"
              for f in check_schedule("on: [\n  unbalanced")))
    check("a DAILY cron -- not the Bulletin's cadence -- is caught",
          any(f.rule == "the-reader-runs-on-the-bulletins-cadence"
              for f in check_schedule(_wf(cron="0 15 * * *"))))
    # THE DAY THE GUARD USED TO LET THROUGH. The first BUSINESS day is as late as the 4th
    # (1st Saturday, 2nd Sunday, 3rd a Monday holiday), and this rule passed days 2 and 3
    # while saying in its own message that they can precede publication.
    for day in (1, 2, 3):
        check(f"a monthly cron on day {day} is caught -- the Bulletin can appear as late "
              "as the 4th, and a run before it reads LAST month's",
              any(f.rule == "the-reader-runs-on-the-bulletins-cadence"
                  for f in check_schedule(_wf(cron=f"0 15 {day} * *"))))
    check("a cron that disagrees with the cadence this module declares is caught",
          any(f.rule == "the-reader-runs-on-the-bulletins-cadence"
              for f in check_schedule(_wf(cron="0 15 9 * *"))))
    check("a cron on a workflow that never invokes this reader is caught",
          any(f.rule == "the-reader-runs-on-the-bulletins-cadence"
              for f in check_schedule(_wf(module="python3 src/something.py"))))
    check("...and a workflow whose ONLY step invoking it is switched off with `if: false` "
          "is caught too -- the case a substring scan of the file passed",
          any(f.rule == "the-reader-runs-on-the-bulletins-cadence"
              for f in check_schedule(_wf(step_if=False))))
    check("a workflow that fetches a different group than this reader joins on is caught",
          any(f.rule == "the-scheduled-run-fetches-the-group-this-reader-joins"
              for f in check_schedule(_wf(group="changes --group something-else"))))
    check("...and the COMMITTED workflow satisfies every one of them",
          not check_schedule(_text(WORKFLOW)))
    drift = _wf(cron="0 14 5 * *", module="python3 -m corpus_toolkit.sources.changes")
    check("a drift workflow that stopped hashing the OAR group is caught -- the change "
          "that would leave the loud case permanently empty",
          any(f.rule == "hash-drift-still-runs"
              for f in check_drift_still_runs(_wf(cron="0 14 5 * *", group="changes"))))
    check("...and a drift JOB switched off with `if: false` is caught, which a scan of a "
          "file that explains its own history in sixty lines of comments would not be",
          any(f.rule == "hash-drift-still-runs"
              for f in check_drift_still_runs(_wf(cron="0 14 5 * *", job_if=False))))
    check("a drift workflow with its cron removed is caught",
          any(f.rule == "hash-drift-still-runs"
              for f in check_drift_still_runs(_wf(cron=None))))
    check("a missing drift workflow is caught, and is not a pass",
          any(f.rule == "hash-drift-still-runs" for f in check_drift_still_runs(None)))
    check("...and the COMMITTED drift workflow still hashes the OAR group on a cron, in a "
          "live step", not check_drift_still_runs(_text(DRIFT_WORKFLOW)))
    check("a toolkit that renamed the drift file out from under this reader is caught",
          any(f.rule == "the-drift-observation-is-the-file-the-toolkit-writes"
              for f in check_drift_filename("out = config.root / 'moved-sources.tsv'")))
    check("a toolkit that could not be read is reported as UNAPPLIED, never as passing",
          any(f.rule == "the-drift-observation-is-the-file-the-toolkit-writes"
              for f in check_drift_filename(None)))
    check("...and the INSTALLED corpus-toolkit still writes the file this reads",
          not check_drift_filename(_toolkit_source()))
    check("...and `drift` is a fixture this proof actually built", "cron" in drift)


def _proof_a_month_nobody_read_is_a_finding(check) -> None:
    """THE PREMISE OF THE SERIES, and the way this module would have quietly failed it.

    `bulletin_report.py` reads the COMMITTED worklist and nothing on a cron writes a new
    one, so without this the September run rebuilds August's report, matches August's issue
    title and exits 0 having filed nothing -- a green run for a month nobody read, which is
    indistinguishable from a month with nothing in it."""
    from datetime import date as _date
    check("a worklist read in its own month is not behind",
          months_unread("August 2026 (bulltnRsn=1761)", _date(2026, 8, 31)) == 0)
    check("a worklist two months old counts both",
          months_unread("August 2026 (bulltnRsn=1761)", _date(2026, 10, 2)) == 2)
    check("a bulletin line nothing can read is not counted as fresh OR as stale here -- "
          "`check_bulletin.py --check` owns that failure",
          months_unread("not a bulletin", _date(2026, 10, 2)) == 0)
    wl = _fixture_worklist(("999-001-0010", "amend", "held"))
    stale = _report_of(wl, None, unread_months=2)
    check("an unread month is a FINDING, so the run has something to file",
          any("NOBODY HAS READ" in label for label, _ in stale.findings())
          and stale.should_file())
    check("...and it is the FIRST thing the issue says, above the loud case",
          issue_body(stale).index("NOBODY HAS READ") < issue_body(stale).index(LOUD_HEADING))
    check("...while a run whose month WAS read says nothing of the kind",
          not any("NOBODY HAS READ" in label
                  for label, _ in _report_of(wl, None).findings()))
    # A MONTH NOBODY READ AND NOTHING ELSE TO SAY still files, which is the whole point.
    empty = _report_of(_fixture_worklist(filings=0), None, unread_months=1)
    check("an empty worklist that is a month behind still files an issue",
          empty.should_file() and len(issues_for(empty)) == 1)


def _proof_the_notice_must_be_readable(check) -> None:
    """A gate that dies instead of naming its rule is what #226 exists to close."""
    saved = legal_status.WORKLIST
    try:
        legal_status.WORKLIST = REPO_ROOT / "_meta/no-such-worklist.yml"
        r, failures = build()
        check("an unreadable worklist names its rule instead of raising",
              r is None and any(f.rule == "the-notice-is-readable" for f in failures))
    finally:
        legal_status.WORKLIST = saved
    check("...and the committed worklist reads", isinstance(load_worklist(), dict))
    saved_manifest = globals()["MANIFEST"]
    try:
        globals()["MANIFEST"] = REPO_ROOT / "_meta/sources/no-such-group.yml"
        r, failures = build()
        check("an unreadable source manifest names its rule instead of classifying every "
              "rule in the month as never watched",
              any(f.rule == "the-observation-accounts-for-every-watched-source"
                  for f in failures))
    finally:
        globals()["MANIFEST"] = saved_manifest
    check("...and the committed manifest reads", MANIFEST.exists())


def orphaned_proofs(source) -> set:
    """Proof functions defined in this module that `selftest()` never calls.

    A proof nobody runs is indistinguishable from one that passes, and it is worse than no
    proof at all: the file reads as though the rule were watched."""
    tree = ast.parse(source)
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name.startswith("_proof_")}
    body = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "selftest"), None)
    called = {n.func.id for n in ast.walk(body) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Name)} if body else set()
    return defined - called


def selftest() -> int:
    import tempfile
    check = Checks()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _proof_the_census_is_a_faithful_count(check)
        _proof_the_body_carries_what_it_counts(check)
        _proof_one_issue_or_none(check)
        _proof_the_four_cases(check, tmp / "drift.tsv")
        _proof_a_group_wide_move_is_not_per_rule_notice(check, tmp / "wide.tsv")
        _proof_no_observation_is_not_no_disagreement(check, tmp)
        _proof_the_two_facts_in_workflow_files(check)
        _proof_a_month_nobody_read_is_a_finding(check)
        _proof_the_notice_must_be_readable(check)
    check("every rule this module can report is declared",
          legal_status.emitted_rules(Path(__file__).read_text()) == set(CHECK_RULES))
    check("...and every declared rule was watched firing, not merely listed",
          set(CHECK_RULES) <= _FIRED)
    # AND EVERY PROOF IS ACTUALLY RUN. The two rules above compare the CHECK_RULES table
    # with the Failures this module emits, and neither can see a proof that was written and
    # never called -- which is how `_proof_a_month_nobody_read_is_a_finding` sat in this
    # file, fully written, contributing nothing, while the selftest reported OK. It could
    # not: `months_unread()` produces a FINDING rather than a Failure, so no rule name goes
    # missing when its proof stops running. Read out of this module's own syntax tree,
    # like `emitted_rules`.
    source = Path(__file__).read_text()
    check("a proof written in this file and never called is caught",
          orphaned_proofs(source.replace(
              "        _proof_a_month_nobody_read_is_a_finding(check)\n", ""))
          == {"_proof_a_month_nobody_read_is_a_finding"})
    check("...and every proof written in this file is one `selftest()` calls",
          orphaned_proofs(source) == set())
    return check.report(
        f"{len(CHECK_RULES)} rule(s) declared, every one both emitted by this module and "
        "watched firing here -- selftest")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    # THE OUTWARD-ACTING FLAG, AND IT IS NOT THE DEFAULT. Every command a person types by
    # hand prints the report and files nothing; only a caller that asked for it in so many
    # words reaches the tracker.
    ap.add_argument("--file-issue", action="store_true",
                    help="file the one issue this run has to file (needs `gh`)")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.check:
        return cmd_check()
    if a.file_issue:
        return cmd_file_issue()
    return cmd_report()


if __name__ == "__main__":
    raise SystemExit(main())
