#!/usr/bin/env python3
"""Run every gate CI runs, locally, in one command (#318).

  python3 src/check_all.py               # run every gate; exit non-zero if any failed
  python3 src/check_all.py --list        # print what would run, without running it
  python3 src/check_all.py --selftest    # prove every property below can fail
  python3 src/check_all.py -j 4          # run non-selftest gates with 4 workers

WHY THIS EXISTS. `main` went red three times from one ingest (#238), and each round only
surfaced the NEXT layer: GitHub stops a job at its first failing step, so a shard with five
broken gates reports exactly one failure, and fixing it just unmasks the next. There was no
local command that ran every gate CI runs, so the only way to discover the full set was to
push and wait -- the #309 and #318 sweeps were both reconstructed by grepping the workflow
YAML by hand. This is that command.

THE GATE LIST IS DERIVED, NEVER RESTATED. `src/shard_generated_views.py` already parses the
workflow's shard jobs and holds that list against `.github/generated-views-manifest.yml` --
`gate_steps_by_shard()` there is the one parser of "what does the workflow actually run", and
this module imports it rather than holding a second regex over the same YAML. A second reader
would be one fact declared twice with nothing gating agreement -- the `CONTEXT.md` *Stated
figure* defect class this repo keeps paying for.

FOUR PROPERTIES MATTER MORE THAN THE ERGONOMICS (#318's acceptance criteria):

  1. It does NOT stop at the first failure -- every failing gate is named together at the
     end, the opposite of what CI itself does and the entire reason this exists.
  2. A gate that COULD NOT BE RUN (missing command, timeout) is reported as its own status,
     distinct from one that ran and failed -- neither a pass nor a silent skip (`AGENTS.md`:
     could not check is never reported as is not there).
  3. Discovering ZERO gates is a FAILURE, not a green run. A parse change that silently
     emptied the list must never be able to print "0 gates, all passed".
  4. `--selftest` gates mutate fixtures in the working tree (they break something, watch a
     rule fire, restore it), so they must never run concurrently with anything else -- not
     each other, not a plain `--check` gate racing beside them. `-j` parallelizes only the
     non-selftest gates; every `--selftest` gate then runs alone, one at a time, after the
     parallel pool has fully drained.

OUT OF SCOPE (#318): changing the sharding, or any gate's own logic; making this script
itself a CI gate (CI already runs the gates -- this is the local mirror). The manifest's
`seconds:` COLUMN is now IN scope, narrowly: #359 (below) found it can drift arbitrarily
far from reality with nothing catching it, including this very script, which measures
every gate's real cost and used to throw the number away unread. Checking and correcting
that one column is additive to #318's own job -- this section does not touch the
sharding, gate discovery, or gate logic #318 put out of scope, and does not make this
script itself a CI gate either (see REPORT, NOT (SILENTLY) PASS below for why running
locally and exiting non-zero is not the same thing).

DECLARED-COST DRIFT (closing #359). #359 found
`.github/generated-views-manifest.yml` declaring 0.7s for a gate that actually cost 40.1s
(measured 82.5s/81.3s before a cache+scope fix to `check_updates.py`'s corpus walk, still
40.1s after it) -- wrong by two orders of magnitude, and NOTHING caught it:
`shard_generated_views.py --check` only verifies gate EXISTENCE and shard PLACEMENT
against the manifest, never the declared `seconds:` figure against a real measurement.
This module already measures every gate's real wall-clock (`GateResult.seconds`) and, per
its own docstring above, used to throw that number away the moment it was printed.
`--check-drift` (on by default for a `-j 1` run; skipped, not silently trusted, at `-j
>1`) compares each measured second against the manifest's declared one and reports every
gate whose ratio clears `DRIFT_RATIO_THRESHOLD`. `--refresh-manifest` writes the measured
numbers back, so "hand-edit the YAML" -- how #359's own 0.7s got stale in the first
place -- stops being the only way to correct it. #359 itself asked whether local timing is
even representative of CI's; it is not answered here, because it cannot be from local
data alone -- see the CI paragraph below.

THE THRESHOLD (`DRIFT_RATIO_THRESHOLD = 4.0`), justified from measured spread, not a round
number picked in the abstract. One data point anchors the REAL-drift side, a real
measurement, not an estimate: this repo's known real drift is 0.7s declared vs 40.1s
measured, a 57x ratio. NO CI figure anchors it on that side, honestly: CI never
completed this gate's step even once after the accounting #359 traces the drift to was
added -- every post-#287 run was killed by the step's own `timeout-minutes` ceiling before
finishing (see the workflow's own comment on this step for the measured shape of that),
so there is no CI-measured number for the unscoped work to compare against, faster or
slower, and none is claimed here. The last CI runs that DID complete this step, before
that accounting landed, measured 4s each -- faster than local, the opposite of what would
make 57x look aggressive. Absent a completed CI measurement, 57x stands as the only real
anchor, and it is treated as conservative on that basis alone, not backed by a second,
faster-than-local data point that does not exist. This repo's known NOISE is the rest of
the manifest: `check_all.py` itself, run three times back to back on this warm checkout
while calibrating this feature (this branch's own measurement, not any prior commit's),
varied by at most ~1% run to run (82.5s/81.3s, 40.1s/40.1s/40.4s) --
and the four gates with the most declared/measured headroom on record (`Relationship graph`
81.7s declared, `STATUS.md` 69.2s, `External-citation catalog` 90.8s, `A snapshot's two
spellings` 33.8s) all sit within the 1.0x-1.1x band when measured, the "noise" example this
ticket was handed (81.7s declared vs ~90s measured is noise). 4x sits an order of magnitude
above the highest noise ever observed on this repo (~1.1x) and well under two orders of
magnitude below the smallest real drift on record (57x) -- there is no measured data point
anywhere near the middle of that gap to place the line more precisely, so it is placed with
maximum margin on both sides rather than split arbitrarily.

MACHINE TIMING VARIANCE. Two guards, not one, keep this from becoming noise on a slower or
busier machine: (1) drift is computed ONLY against a `-j 1` (serial, uncontended) run --
`-j >1` gates are already documented as up to 3.2x inflated by oversubscription (#331), and
comparing THAT number to a serial-measured manifest would manufacture drift out of pure
contention, so `--check-drift` is skipped outright at `-j >1`, with a note saying why, not
silently computed and printed as if trustworthy. (2) the 4x threshold has real headroom on
BOTH sides in ratio terms, not just in raw distance: 4x / 1.1x (the highest noise measured)
is ~3.6x of margin above typical noise, and 57x / 4x (the smallest confirmed real drift) is
~14x of margin below it. A machine running every gate more than ~3.6x slower, uniformly,
than this checkout would be needed before a currently-honest gate's ratio alone crossed 4x
and false-flagged -- and that same uniform slowdown would still leave a genuine 57x drift
enormously over the line, not anywhere near it. A gate whose measured
cost is also close to its own workflow `timeout-minutes` is flagged as a separate NOTE
(not gated by the ratio) since that is a distinct risk (the run may itself be at genuine
risk of a CI timeout) from "the declared number in the manifest is stale."

REPORT, NOT (SILENTLY) PASS: `cmd_run`'s exit code goes non-zero if drift is found, same as
a failed or errored gate, printed in its own section so a reader never confuses "a gate's
own check disagreed with reality" with "the manifest's cost figure disagreed with reality."
Reporting-only was considered and rejected: a run that finds a gate declared at 0.7s costing
40x that and still exits 0 is the exact shape of defect this repo's `check_rule_ledger.py`
and `stated_census.py` both exist to refuse elsewhere (a check that found a problem and said
nothing is not a check). This script staying "not a CI gate" (the #318 scope note above)
means no workflow step runs `check_all.py` itself -- it says nothing about what a human
running it locally should see when it finds a stale figure the same class of bug already
took `main` down over.
"""
import argparse
import re
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shard_generated_views as shard  # noqa: E402  -- the one parser; see module docstring

REPO_ROOT = shard.REPO_ROOT
WORKFLOW = shard.WORKFLOW

# Generous backstop, not a re-tuned budget: mirrors the reasoning in the workflow's own
# per-shard timeout-minutes comment -- this exists to catch a genuine hang (a step blocked
# on stdin), not to be the thing that ordinarily fires. Individual step timeout-minutes in
# the workflow run from 2 to 8; 600s (10 min) sits comfortably above all of them.
DEFAULT_TIMEOUT_SECONDS = 600

# Exit codes a POSIX shell uses to say "I could not even start this", never "I ran it and it
# disagreed": 126 (found, not executable) and 127 (not found at all). Anything else nonzero
# is the gate's own program disagreeing with reality, i.e. an ordinary failure.
SHELL_DISPATCH_FAILURE_CODES = {126, 127}

# 126/127 alone leave the "could not run" status unreachable for the large majority of this
# repo's real gates (#330; 74 of 76 measured -- almost every gate but not a number worth
# restating here a second time and letting it drift, see CONTEXT.md's *Stated figure*):
# nearly every gate is `python3 src/<script>.py ...`, and a MISSING script is not a shell
# dispatch failure -- the shell found and ran `python3` just fine. `python3` itself then
# exits 2 ("can't open file ... No such file or directory"), indistinguishable by exit code
# alone from a gate script's own `sys.exit(2)`. So this repo's realistic "command missing"
# case is checked for directly, before the subprocess ever starts, rather than inferred from
# an exit code shared with an ordinary failure.
_SCRIPT_INTERPRETERS = {"python3", "python"}

# See the module docstring's DECLARED-COST DRIFT section for the measured justification.
DRIFT_RATIO_THRESHOLD = 4.0

# When even the LARGER of declared/measured is under this many seconds, a ratio is
# meaningless noise -- a gate declared at 0.0s (rounds anything under ~0.05s) measuring
# 0.3s is technically "infinite" drift and is really just subprocess-startup jitter
# (measured: a bare `python3 src/foo.py --selftest` with near-nothing to do costs
# 0.04s-0.27s on this checkout). Below this floor, drift is judged on absolute seconds
# instead of a ratio; at or above it, a fixed multiple is used against the smaller
# number (floored only at DRIFT_RATIO_MIN_DENOMINATOR, a numerical safety rail, not a
# second dampener) -- deliberately NOT "both numbers must clear the floor": a gate
# measured well above the floor with a small declared figure (found live on this
# checkout: "The monthly Bulletin report must file one issue, or none", 0.7s declared,
# ~3.1s measured three times running, 4.4-4.5x) is exactly the shape of drift this
# exists to catch, and requiring the SMALL side to also clear the floor would have
# hidden it by construction.
DRIFT_FLOOR_SECONDS = 2.0
# The absolute-seconds rule that applies only when BOTH numbers are under the floor
# above (so both are always < DRIFT_FLOOR_SECONDS apart by construction): flag it if
# they differ by more than this many seconds even though neither alone clears the
# floor. MUST stay strictly below DRIFT_FLOOR_SECONDS or this branch becomes
# unreachable (caught by this module's own --selftest).
DRIFT_FLOOR_ABS_SECONDS = 1.0
# Purely a division-by-zero guard for the ratio branch (declared or measured can be
# exactly 0.0) -- NOT a second noise dampener the way flooring at DRIFT_FLOOR_SECONDS
# would be; that dampening already happens by routing anything with max < the floor
# into the absolute-difference branch above instead.
DRIFT_RATIO_MIN_DENOMINATOR = 0.01

# A gate whose measured cost eats more than this fraction of its OWN workflow step's
# timeout-minutes is flagged as a separate note, regardless of manifest drift -- the
# `check_updates.py --check` gate #359 traces the drift to is fine on this axis after the
# cache+scope fix (40.1s against the raised 300s/5min timeout) but was NOT fine before it
# in CI specifically: its step was killed by its own 2-minute `timeout-minutes` ceiling on
# every one of the five runs that turned `main` red, never a clean pass or fail (see the
# workflow's own comment on that step), so this is worth surfacing even on a gate whose
# declared manifest figure happens to still be honest.
TIMEOUT_HEADROOM_WARN_FRACTION = 0.5


def _missing_script(run_cmd: str):
    """None if `run_cmd` does not invoke `python3 <script>` at all, or if it does and the
    script file exists. Otherwise, the missing path, as a string, for the "error" detail.

    Deliberately narrow: only a bare positional script argument is checked (`-c`, `-m`,
    and any other flag-shaped second token are left alone -- there is no script FILE to
    have gone missing). A command this can't parse (mismatched quotes) is left to the
    shell to report as an ordinary failure, same as before this existed."""
    try:
        tokens = shlex.split(run_cmd)
    except ValueError:
        return None
    if len(tokens) < 2 or tokens[0] not in _SCRIPT_INTERPRETERS:
        return None
    script = tokens[1]
    if script.startswith("-"):
        return None
    path = Path(script)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return None if path.is_file() else script


@dataclass
class Gate:
    name: str
    shard_job: str
    run_cmd: str

    @property
    def is_selftest(self) -> bool:
        """A `--selftest` gate mutates fixtures in the working tree and must never run
        concurrently with anything else. Token-matched (not substring) so a gate whose
        command merely mentions "--selftest" in a string argument isn't misclassified --
        every real gate command in the workflow is `python3 src/foo.py --selftest`, a
        literal argv token, so this is what actually distinguishes them today."""
        return "--selftest" in self.run_cmd.split()


@dataclass
class GateResult:
    gate: Gate
    status: str  # "pass" | "fail" | "error" -- see run_gate()
    seconds: float
    detail: str = ""


def load_gates(workflow_path=None) -> list:
    """Every gate the workflow runs, in shard/file order -- the one thing this module
    reads out of shard_generated_views.gate_steps_by_shard() rather than re-parsing.

    Includes generated-views-nightly's gates too (#329): that job is out of scope for
    shard_generated_views.py's manifest/bin-packing BY DESIGN (#268 -- it is "not what
    a PR waits on"), but it is still a job CI runs, on a schedule/workflow_dispatch,
    and #318's own binding scope decision (issue comment 2) named one of its gates,
    `review_queue`, as in-scope for this ticket. A tool that claims to be "the local
    mirror of every generated-views gate" (AGENTS.md, CONTRIBUTING.md) and silently
    excludes a whole job's worth is exactly the kind of omission AGENTS.md's overriding
    rule forbids: reported nowhere is not the same as checked and found green. Nightly
    gates surface under their own `generated-views-nightly` shard_job label in --list
    and --run output -- never merged into a shard-N bucket -- so a reader can still see
    at a glance which gates the PR-tier manifest actually costs and bin-packs and which
    it doesn't."""
    workflow_path = workflow_path or WORKFLOW
    doc = shard._yaml_load_workflow(workflow_path.read_text())
    steps_by_shard = shard.gate_steps_by_shard(doc)
    gates = []
    for job_id in shard.shard_job_ids(doc):
        for name, run_cmd in steps_by_shard.get(job_id, []):
            gates.append(Gate(name=name, shard_job=job_id, run_cmd=run_cmd))
    for name, run_cmd in shard.gate_steps_for_job(doc, shard.NIGHTLY_JOB):
        gates.append(Gate(name=name, shard_job=shard.NIGHTLY_JOB, run_cmd=run_cmd))
    return gates


def run_gate(gate: Gate, timeout=DEFAULT_TIMEOUT_SECONDS) -> GateResult:
    """Run one gate's command for real (the seam this module tests at: a real subprocess
    boundary, not a mock of one). Never raises -- every way a gate can fail to even start
    is caught and reported as status "error", distinct from "fail" (ran, disagreed)."""
    start = time.monotonic()
    missing = _missing_script(gate.run_cmd)
    if missing is not None:
        return GateResult(gate, "error", time.monotonic() - start,
                           f"could not run: python3 script does not exist: {missing}")
    try:
        proc = subprocess.run(
            gate.run_cmd, shell=True, cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return GateResult(gate, "error", time.monotonic() - start,
                           f"timed out after {timeout}s")
    except OSError as e:
        return GateResult(gate, "error", time.monotonic() - start,
                           f"could not run: {e}")
    elapsed = time.monotonic() - start
    if proc.returncode in SHELL_DISPATCH_FAILURE_CODES:
        return GateResult(gate, "error", elapsed,
                           f"exit {proc.returncode} (shell could not dispatch it): "
                           + (proc.stderr or proc.stdout).strip()[-2000:])
    if proc.returncode == 0:
        return GateResult(gate, "pass", elapsed)
    return GateResult(gate, "fail", elapsed, (proc.stdout + proc.stderr).strip()[-2000:])


def run_all(gates, jobs=1, timeout=DEFAULT_TIMEOUT_SECONDS) -> list:
    """Run every gate and return every GateResult -- never stops at the first failure.

    `--selftest` gates never run concurrently with anything: they are held back into a
    second, strictly-serial phase that only starts once every non-selftest gate (run with
    up to `jobs` workers) has fully finished. This is what makes -j safe to offer at all.
    """
    regular = [g for g in gates if not g.is_selftest]
    selftest_gates = [g for g in gates if g.is_selftest]

    results = []
    if jobs > 1 and regular:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            for r in pool.map(lambda g: run_gate(g, timeout), regular):
                results.append(r)
    else:
        for g in regular:
            results.append(run_gate(g, timeout))

    # Phase boundary: every regular-gate subprocess above has returned before this line
    # runs (pool.map / the plain loop both block until done) -- so no selftest gate below
    # can ever overlap one.
    for g in selftest_gates:
        results.append(run_gate(g, timeout))

    return results


# ---- declared-cost drift (module docstring's DECLARED-COST DRIFT section) ----

@dataclass
class DriftResult:
    name: str
    declared: float
    measured: float
    gate_status: str  # the underlying gate's "pass"/"fail" -- informational only here
    ratio: float | None  # None when judged by the below-floor absolute rule instead
    drifted: bool
    reason: str


def compute_drift(results, manifest_gates) -> list:
    """One DriftResult per gate that has BOTH a real result and a manifest entry -- a
    gate the manifest has never heard of (nightly-only, out of PR-tier scope by design,
    see shard_generated_views.py's own module docstring) has nothing to compare against
    and is silently excluded here, not flagged as drifted.

    Only "pass"/"fail" results are compared. An "error" result (timeout, missing
    script) measures how long the harness waited before giving up, not how long the
    gate actually takes -- comparing THAT to a declared cost would manufacture drift
    out of a completely different, already separately-reported problem."""
    declared_by_name = {g["name"]: float(g["seconds"]) for g in manifest_gates}
    out = []
    for r in results:
        name = r.gate.name
        if name not in declared_by_name or r.status not in ("pass", "fail"):
            continue
        declared, measured = declared_by_name[name], r.seconds
        if max(declared, measured) < DRIFT_FLOOR_SECONDS:
            diff = abs(measured - declared)
            drifted = diff > DRIFT_FLOOR_ABS_SECONDS
            ratio = None
            reason = (f"declared {declared:.2f}s, measured {measured:.2f}s -- both under "
                      f"the {DRIFT_FLOOR_SECONDS:.0f}s floor, judged by absolute "
                      f"difference ({diff:.2f}s vs a {DRIFT_FLOOR_ABS_SECONDS:.0f}s limit)")
        else:
            hi = max(declared, measured)
            lo = max(min(declared, measured), DRIFT_RATIO_MIN_DENOMINATOR)
            ratio = hi / lo
            drifted = ratio >= DRIFT_RATIO_THRESHOLD
            reason = f"declared {declared:.1f}s, measured {measured:.1f}s ({ratio:.1f}x)"
        out.append(DriftResult(name, declared, measured, r.status, ratio, drifted, reason))
    return out


def _step_timeout_minutes(workflow_path=None) -> dict:
    """{gate name: timeout-minutes} for every named+run step in ANY job the workflow
    defines. A purely local, additive read of the already-parsed workflow doc: this is
    not a duplicate of shard_generated_views.py's "one parser" of gate steps (name+run,
    matched against the manifest) -- timeout-minutes appears in neither the manifest
    nor any comparison that module makes, so nothing there already owns reading it."""
    workflow_path = workflow_path or WORKFLOW
    doc = shard._yaml_load_workflow(workflow_path.read_text())
    out = {}
    for job in doc.get("jobs", {}).values():
        for step in job.get("steps", []):
            if "name" in step and "run" in step and "timeout-minutes" in step:
                out[step["name"]] = step["timeout-minutes"]
    return out


def timeout_headroom_notes(results) -> list:
    """One string per gate whose measured cost already eats more than
    TIMEOUT_HEADROOM_WARN_FRACTION of its OWN workflow step's timeout-minutes --
    independent of manifest drift, since a gate can have an honest declared figure and
    still be one slow CI runner away from a real timeout (the `check_updates.py --check`
    gate #359 traces the drift to measured 40.1s locally against a 300s timeout after the
    cache+scope fix, comfortable; the SAME unscoped work, in CI, never finished the step
    at all -- its own 2-minute timeout killed it on every one of the five runs that turned
    `main` red)."""
    timeouts = _step_timeout_minutes()
    notes = []
    for r in results:
        limit = timeouts.get(r.gate.name)
        if limit is None or r.status == "error":
            continue
        limit_seconds = limit * 60
        if limit_seconds <= 0:
            continue
        fraction = r.seconds / limit_seconds
        if fraction >= TIMEOUT_HEADROOM_WARN_FRACTION:
            notes.append(f"{r.gate.name!r}: measured {r.seconds:.1f}s is {fraction:.0%} of "
                         f"its {limit}-minute step timeout ({limit_seconds:.0f}s)")
    return notes


def refresh_manifest(results, manifest_path=None):
    """Rewrite `seconds:` in the manifest to each gate's just-measured cost, preserving
    every comment and every other field byte-for-byte -- a regex substitution over the
    manifest's own file text, not a YAML round-trip (`yaml.safe_load` + a plain `dump`
    would silently discard every explanatory comment the file carries, including the
    one this branch's own hand-made 0.7s -> 40.1s correction added to explain itself,
    while calibrating this feature -- see #359). Returns
    (new_text, [(name, old_seconds, new_seconds), ...]) for every entry actually
    changed -- the caller decides whether to write it and what to print.

    Only "pass"/"fail" results are eligible, for the same reason `compute_drift` only
    compares those two statuses: an "error" result's timing is how long the harness
    waited, not how long the gate takes, and writing that into the manifest would
    plant a new version of the exact bug this whole feature exists to catch."""
    manifest_path = manifest_path or shard.MANIFEST
    text = manifest_path.read_text()
    measured_by_name = {r.gate.name: r.seconds for r in results if r.status in ("pass", "fail")}

    name_re = re.compile(r'^(\s*-\s*name:\s*")([^"]*)("\s*)$')
    seconds_re = re.compile(r'^(\s*seconds:\s*)([0-9.]+)(\s*)$')
    # A comment or blank line between `name:` and `seconds:` (this branch's own manifest
    # correction, #359, added exactly this shape) must not make the scan give up on the entry --
    # only content that is neither the seconds line nor a comment/blank line abandons it,
    # as a safety rail against guessing across a genuinely malformed entry.
    comment_or_blank_re = re.compile(r'^\s*(#.*)?$')

    lines = text.splitlines(keepends=True)
    changed = []
    pending_name = None
    for i, raw in enumerate(lines):
        line = raw.rstrip("\r\n")
        nm = name_re.match(line)
        if nm:
            pending_name = nm.group(2)
            continue
        if pending_name is not None:
            sm = seconds_re.match(line)
            if sm:
                if pending_name in measured_by_name:
                    new_val = round(measured_by_name[pending_name], 1)
                    old_val = float(sm.group(2))
                    if old_val != new_val:
                        ending = raw[len(line):]  # the newline(s) stripped above, preserved
                        lines[i] = f"{sm.group(1)}{new_val}{sm.group(3)}{ending}"
                        changed.append((pending_name, old_val, new_val))
                pending_name = None
            elif not comment_or_blank_re.match(line):
                pending_name = None
    return "".join(lines), changed


def cmd_list(gates) -> int:
    if not gates:
        print("0 gates discovered -- refusing to print a plan for nothing.")
        return 1
    by_shard = {}
    for g in gates:
        by_shard.setdefault(g.shard_job, []).append(g)
    for job_id in sorted(by_shard):
        print(f"{job_id}:")
        for g in by_shard[job_id]:
            tag = " [selftest, serialized]" if g.is_selftest else ""
            print(f"    {g.name}{tag}\n        $ {g.run_cmd}")
    n_selftest = sum(1 for g in gates if g.is_selftest)
    print(f"\n{len(gates)} gate(s) across {len(by_shard)} shard(s) "
          f"({n_selftest} selftest gate(s), always serialized).")
    return 0


def cmd_run(gates, jobs=1, timeout=DEFAULT_TIMEOUT_SECONDS, check_drift=True,
            do_refresh_manifest=False, manifest_path=None) -> int:
    # PROPERTY: discovering zero gates is a FAILURE, never a green run -- a parse change
    # that silently emptied the list must not be able to print "0 gates, all passed".
    if not gates:
        print("FAIL  0 gates discovered. This is a parser defect, not a clean bill of "
              "health -- refusing to report success for a check that checked nothing.")
        return 1

    start = time.monotonic()
    results = run_all(gates, jobs=jobs, timeout=timeout)
    total = time.monotonic() - start

    # run_all reports the parallel-regular phase and the serial --selftest phase back to
    # back, so a straight loop over `results` prints every shard TWICE, split across a
    # boundary this output never names (#331). Reorder to the input `gates` order (the
    # same order --list prints) instead -- a reader diffing this run against --list then
    # sees one pass, shard by shard, matching what they already expect, and the phase
    # split stops being something they have to reverse-engineer from repeated shard names.
    by_gate_id = {id(r.gate): r for r in results}
    results = [by_gate_id[id(g)] for g in gates]

    for r in results:
        label = {"pass": "PASS ", "fail": "FAIL ", "error": "ERROR"}[r.status]
        print(f"{label} {r.gate.name}  ({r.gate.shard_job}, {r.seconds:.2f}s)")
        if r.status != "pass" and r.detail:
            for line in r.detail.splitlines()[-10:]:
                print(f"      | {line}")

    passed = [r for r in results if r.status == "pass"]
    failed = [r for r in results if r.status == "fail"]
    errored = [r for r in results if r.status == "error"]

    print(f"\n==== {len(results)} gate(s) across "
          f"{len({r.gate.shard_job for r in results})} shard(s) in {total:.1f}s ====")
    print(f"{len(passed)} passed, {len(failed)} failed, {len(errored)} could not be run.")
    if jobs > 1:
        print(f"NOTE: ran with -j {jobs} -- the seconds printed above are CONTENDED wall-clock "
              f"time, not gate cost (measured 3.2x inflation at oversubscription, #331). Do not "
              f"copy them into .github/generated-views-manifest.yml's cost column; re-run with "
              f"-j 1 (the default) first if you need real per-gate numbers.")

    # DECLARED-COST DRIFT (module docstring's DECLARED-COST DRIFT section). Only against
    # an uncontended (-j 1) run -- see that section for why -j >1 timings would manufacture
    # drift out of pure contention rather than a real stale manifest figure.
    resolved_manifest_path = manifest_path or shard.MANIFEST
    drifted = []
    if check_drift:
        if jobs > 1:
            print("\nNOTE: declared-cost drift check skipped -- ran with -j "
                  f"{jobs}, and drift is only meaningful against uncontended (-j 1) "
                  "timings (see NOTE above). Re-run with -j 1 to check drift.")
        else:
            manifest_gates = shard.load_manifest(resolved_manifest_path)
            drift_results = compute_drift(results, manifest_gates)
            drifted = [d for d in drift_results if d.drifted]
            if drifted:
                print(f"\nDECLARED-COST DRIFT ({len(drifted)} of {len(drift_results)} "
                      f"manifest-tracked gate(s) compared):")
                for d in sorted(drifted, key=lambda d: -(d.ratio or 0)):
                    print(f"  DRIFT  {d.name!r}: {d.reason}")
                print(f".github/generated-views-manifest.yml's declared seconds no longer "
                      f"reflect reality for the gate(s) above -- re-run with "
                      f"--refresh-manifest to correct them from this run's own measurements.")
            else:
                print(f"\ndeclared-cost drift: {len(drift_results)} manifest-tracked gate(s) "
                      f"compared, none drifted (ratio >= {DRIFT_RATIO_THRESHOLD:.0f}x, "
                      f"or >{DRIFT_FLOOR_ABS_SECONDS:.0f}s apart under the "
                      f"{DRIFT_FLOOR_SECONDS:.0f}s floor).")
            for note in timeout_headroom_notes(results):
                print(f"  NOTE (timeout headroom): {note}")

    if do_refresh_manifest:
        if jobs > 1:
            print("\nNOTE: --refresh-manifest skipped -- ran with -j "
                  f"{jobs}; refresh only writes from uncontended (-j 1) timings, the same "
                  "restriction as the drift check above. Re-run with -j 1.")
        else:
            new_text, changed = refresh_manifest(results, resolved_manifest_path)
            if changed:
                resolved_manifest_path.write_text(new_text)
                print(f"\nrefreshed {resolved_manifest_path}: "
                      f"{len(changed)} gate(s) corrected from this run's measurements:")
                for name, old, new in changed:
                    print(f"  {name!r}: {old:.1f}s -> {new:.1f}s")
            else:
                print("\n--refresh-manifest: every manifest-tracked gate's declared "
                      "seconds already matched this run's measurements -- nothing written.")

    if failed or errored or drifted:
        if failed or errored:
            print("\nFAILING / COULD-NOT-RUN GATES, named together (not just the first):")
            for r in failed:
                print(f"  FAIL   {r.gate.name}  ({r.gate.shard_job})")
            for r in errored:
                print(f"  ERROR  {r.gate.name}  ({r.gate.shard_job}): {r.detail}")
        if drifted:
            print("\nDRIFTED MANIFEST ENTRIES, named together:")
            for d in drifted:
                print(f"  DRIFT  {d.name!r}: {d.reason}")
        return 1

    print(f"\nall {len(results)} gate(s) green"
          + (", declared costs current" if check_drift and jobs == 1 else "") + ".")
    return 0


# ---- --selftest: prove each property above can fail ----

def _fake_gate(name, run_cmd, shard_job="fixture-shard-1"):
    return Gate(name=name, shard_job=shard_job, run_cmd=run_cmd)


def _rule_does_not_stop_at_first_failure():
    gates = [
        _fake_gate("first-fails", "false"),
        _fake_gate("second-fails", "exit 3"),
        _fake_gate("third-passes", "true"),
    ]
    results = run_all(gates, jobs=1)
    names_seen = {r.gate.name for r in results}
    if names_seen != {"first-fails", "second-fails", "third-passes"}:
        return (f"FAIL does-not-stop-at-first-failure: expected all 3 gates reported, "
                f"got {sorted(names_seen)!r} -- a run that stops early would report only "
                f"'first-fails'")
    statuses = {r.gate.name: r.status for r in results}
    if statuses != {"first-fails": "fail", "second-fails": "fail", "third-passes": "pass"}:
        return f"FAIL does-not-stop-at-first-failure: wrong statuses {statuses!r}"
    return None


def _rule_could_not_run_is_distinct_from_failed():
    missing = _fake_gate("missing-binary", "this-binary-does-not-exist-zzz --check")
    slow = _fake_gate("times-out", "sleep 5")
    ordinary_fail = _fake_gate("ordinary-fail", "exit 1")
    results = {r.gate.name: r.status
               for r in [run_gate(missing), run_gate(slow, timeout=0.2),
                         run_gate(ordinary_fail)]}
    if results.get("missing-binary") != "error":
        return (f"FAIL could-not-run-is-distinct: a missing binary reported "
                f"{results.get('missing-binary')!r}, wanted 'error'")
    if results.get("times-out") != "error":
        return (f"FAIL could-not-run-is-distinct: a timeout reported "
                f"{results.get('times-out')!r}, wanted 'error'")
    if results.get("ordinary-fail") != "fail":
        return (f"FAIL could-not-run-is-distinct: an ordinary nonzero exit reported "
                f"{results.get('ordinary-fail')!r}, wanted 'fail' -- 'error' must not "
                f"swallow real failures too")
    return None


def _rule_missing_python_script_is_error():
    """The realistic "could not run" shape for THIS repo (#330): almost every real gate is
    `python3 src/<script>.py ...`, not a bare missing binary -- `this-binary-does-not-
    exist-zzz` above proves the 126/127 path but is a command shape no real gate has.
    A script path that does not exist must report 'error', the same as a missing binary,
    never 'fail' -- python3 itself exiting 2 for "can't open file" must not be folded in
    with a gate script's own ordinary nonzero exit."""
    gate = _fake_gate("missing-python-script",
                       "python3 src/this_script_does_not_exist_selftest.py --check")
    result = run_gate(gate)
    if result.status != "error":
        return (f"FAIL missing-python-script-is-error: a missing python3 script reported "
                 f"{result.status!r}, wanted 'error' -- exit code alone cannot tell this "
                 f"apart from the script's own ordinary failure")
    return None


def _rule_zero_gates_is_a_failure():
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_run([])
    out = buf.getvalue()
    if rc == 0:
        return f"FAIL zero-gates-is-a-failure: cmd_run([]) exited 0, output: {out!r}"
    if "all passed" in out.lower() or "0 gate(s)" in out and "passed" in out:
        return f"FAIL zero-gates-is-a-failure: printed a passing-sounding message: {out!r}"
    return None


def _rule_selftest_gates_never_run_concurrently(tmp_path):
    """Two 'gates' that each do a classic read-sleep-write lost-update race on a shared
    counter file. Run concurrently (racing threads/processes), the window is wide enough
    that both read the same starting value and the final count is 1, not 2 -- a real,
    observable defect, not a mocked one. Both commands carry a literal `--selftest` token
    so run_all must hold them for the strictly-serial second phase regardless of `jobs`."""
    counter = tmp_path / "counter"
    counter.write_text("0")
    script = (
        f"v=$(cat {counter}); sleep 0.3; echo $((v+1)) > {counter}"
    )
    racy_a = _fake_gate("racy-a", f"bash -c '{script}' _ --selftest")
    racy_b = _fake_gate("racy-b", f"bash -c '{script}' _ --selftest")
    results = run_all([racy_a, racy_b], jobs=4)
    if any(r.status != "pass" for r in results):
        return f"FAIL selftest-never-concurrent: fixture gates themselves failed: {results!r}"
    final = counter.read_text().strip()
    if final != "2":
        return (f"FAIL selftest-never-concurrent: counter ended at {final!r}, wanted '2' -- "
                f"a value of '1' means both --selftest gates ran concurrently and lost an "
                f"update, exactly the fixture corruption #318 forbids")
    return None


def _guard_a_fully_passing_run_reports_green():
    """A mixed set -- one ordinary gate, one --selftest gate -- both passing, exercises
    both run_all() phases and must report green through cmd_run()'s real output path."""
    import contextlib
    import io
    gates = [
        _fake_gate("ok-regular", "true"),
        _fake_gate("ok-selftest", "true # --selftest"),
    ]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_run(gates)
    if rc != 0:
        return f"FAIL fully-passing-run-reports-green: exit {rc}, output: {buf.getvalue()!r}"
    return None


# ---- --selftest: declared-cost drift (see module docstring's DECLARED-COST DRIFT
# section) -- the two calibration points that section argues the threshold from, both
# proved directly against compute_drift() rather than a real gate's real timing, so
# these proofs are exact and fast rather than hostage to this machine's own jitter.

def _rule_drift_flags_real_drift_and_spares_noise():
    """#359's own defect (0.7s declared, 40.1s measured, 57x) must be flagged; this
    ticket's own 'noise' example (81.7s declared, ~90s measured, ~1.1x) must not."""
    manifest_gates = [
        {"name": "drifted-gate", "seconds": 0.7, "shard": 1},
        {"name": "noisy-gate", "seconds": 81.7, "shard": 1},
    ]
    results = [
        GateResult(_fake_gate("drifted-gate", "true"), "pass", 40.1),
        GateResult(_fake_gate("noisy-gate", "true"), "pass", 90.0),
    ]
    by_name = {d.name: d for d in compute_drift(results, manifest_gates)}
    if not by_name["drifted-gate"].drifted:
        return (f"FAIL drift-flags-real-drift: 0.7s declared vs 40.1s measured (57x, "
                f"#359's own defect) was not flagged: {by_name['drifted-gate']!r}")
    if by_name["noisy-gate"].drifted:
        return (f"FAIL drift-spares-noise: 81.7s declared vs 90.0s measured (~1.1x, "
                f"this ticket's own 'noise' example) was flagged: "
                f"{by_name['noisy-gate']!r}")
    return None


def _rule_drift_uses_ratio_when_only_one_side_clears_the_floor():
    """The exact shape live drift on this checkout took (#359's own manifest, found
    while calibrating this feature): a small DECLARED figure (well under the floor)
    against a MEASURED cost well above it. Requiring BOTH sides to clear the floor
    before trusting a ratio -- an earlier version of this rule -- would have floored
    the denominator at DRIFT_FLOOR_SECONDS and diluted a real ~4.4x drift down under
    the threshold; only the smaller-of-the-two mattering is what a lone big MEASURED
    number should not survive."""
    manifest_gates = [{"name": "small-declared-big-measured", "seconds": 0.7, "shard": 1}]
    results = [GateResult(_fake_gate("small-declared-big-measured", "true"), "pass", 3.1)]
    d = compute_drift(results, manifest_gates)[0]
    if d.ratio is None or d.ratio < DRIFT_RATIO_THRESHOLD:
        return (f"FAIL drift-uses-ratio-when-one-side-clears-floor: 0.7s declared vs "
                f"3.1s measured (4.4x, above the {DRIFT_RATIO_THRESHOLD:.0f}x threshold) "
                f"was not flagged -- a floored denominator would dilute this exact "
                f"live-found case: {d!r}")
    if not d.drifted:
        return f"FAIL drift-uses-ratio-when-one-side-clears-floor: ratio cleared the threshold but drifted was False: {d!r}"
    return None


def _rule_drift_below_floor_uses_absolute_difference():
    """A near-zero gate a whisker off in RATIO terms (0.0s declared, 0.3s measured is
    technically 'infinite' drift) must not be flagged -- that is subprocess-startup
    jitter, not drift, and the floor exists precisely to keep it from becoming noise.
    But real absolute growth while BOTH numbers stay under the ratio floor (0.1s ->
    1.9s) must still be caught -- the floor swaps the rule, it does not disable it."""
    manifest_gates = [
        {"name": "trivial-jitter", "seconds": 0.0, "shard": 1},
        {"name": "trivial-growth", "seconds": 0.1, "shard": 1},
    ]
    results = [
        GateResult(_fake_gate("trivial-jitter", "true"), "pass", 0.3),
        GateResult(_fake_gate("trivial-growth", "true"), "pass", 1.9),
    ]
    by_name = {d.name: d for d in compute_drift(results, manifest_gates)}
    if by_name["trivial-jitter"].drifted:
        return (f"FAIL drift-floor-absolute: 0.0s declared vs 0.3s measured (pure "
                f"subprocess jitter under the floor) was flagged: "
                f"{by_name['trivial-jitter']!r}")
    if not by_name["trivial-growth"].drifted:
        return (f"FAIL drift-floor-absolute: 0.1s declared vs 1.9s measured (1.8s "
                f"absolute growth, over the {DRIFT_FLOOR_ABS_SECONDS}s limit) was not "
                f"flagged even though both stay under the {DRIFT_FLOOR_SECONDS}s ratio "
                f"floor: {by_name['trivial-growth']!r}")
    return None


def _rule_a_run_that_finds_drift_does_not_exit_0():
    """The design decision the module docstring argues for: every gate can PASS and the
    run must still exit non-zero if the manifest's declared cost has drifted -- the
    'green run that hid a defect' shape #359 itself is built to refuse."""
    import contextlib
    import io
    import tempfile

    gate = _fake_gate("drift-guard-gate", "true")
    with tempfile.TemporaryDirectory() as td:
        manifest_path = Path(td) / "manifest.yml"
        # `true` measures near 0s; declared far above it clears the ratio threshold by
        # a wide margin (10.0s / ~0s, floored only at the numerical-safety epsilon).
        manifest_path.write_text(
            'gates:\n  - name: "drift-guard-gate"\n    seconds: 10.0\n    shard: 1\n'
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_run([gate], check_drift=True, manifest_path=manifest_path)
    if rc == 0:
        return (f"FAIL drift-fails-the-run: the only gate passed but its declared cost "
                f"(10.0s) drifted >=4x from what it measured -- exited 0 anyway: "
                f"{buf.getvalue()!r}")
    if "DRIFT" not in buf.getvalue():
        return (f"FAIL drift-fails-the-run: exited nonzero but printed no DRIFT line: "
                f"{buf.getvalue()!r}")
    return None


def _guard_no_drift_reports_green():
    """The companion guard: a gate whose measured cost still matches its declared one
    must not be reported as drifted, and the run must still exit 0."""
    import contextlib
    import io
    import tempfile

    gate = _fake_gate("no-drift-gate", "true")
    with tempfile.TemporaryDirectory() as td:
        manifest_path = Path(td) / "manifest.yml"
        manifest_path.write_text(
            'gates:\n  - name: "no-drift-gate"\n    seconds: 0.0\n    shard: 1\n'
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_run([gate], check_drift=True, manifest_path=manifest_path)
    if rc != 0:
        return (f"FAIL no-drift-reports-green: a gate matching its declared cost was "
                f"reported drifted, exit {rc}: {buf.getvalue()!r}")
    return None


def _rule_check_drift_is_skipped_at_j_greater_than_1():
    """-j >1 timings are contended (up to 3.2x inflated, #331) -- comparing THAT to a
    serially-measured manifest would manufacture drift out of pure contention, so the
    drift check must be skipped outright, not silently computed, above -j 1."""
    import contextlib
    import io
    import tempfile

    gate = _fake_gate("would-drift-if-checked", "true")
    with tempfile.TemporaryDirectory() as td:
        manifest_path = Path(td) / "manifest.yml"
        manifest_path.write_text(
            'gates:\n  - name: "would-drift-if-checked"\n    seconds: 999.0\n    shard: 1\n'
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cmd_run([gate], jobs=2, check_drift=True, manifest_path=manifest_path)
    if rc != 0:
        return (f"FAIL drift-skipped-at-j-gt-1: a gate that would drift under -j 1 "
                f"failed the run under -j 2, where drift is not meaningful: "
                f"{buf.getvalue()!r}")
    if "DRIFT" in buf.getvalue():
        return (f"FAIL drift-skipped-at-j-gt-1: printed a DRIFT line despite running "
                f"at -j 2: {buf.getvalue()!r}")
    return None


def _rule_refresh_manifest_rewrites_only_drifted_pass_fail_gates():
    """Three gates in one manifest, one text: a drifted PASS gets rewritten, a
    matching PASS is left untouched (no spurious diff when old==new), and an ERROR
    result's timing -- how long the harness waited, not how long the gate takes -- is
    never written, even though its declared figure is stale by the fixture's own
    construction. A hand-written comment between entries must survive verbatim."""
    manifest_text = (
        'gates:\n'
        '  - name: "refresh-me"\n'
        '    seconds: 1.0\n'
        '    shard: 1\n'
        '  # a comment that must survive the rewrite\n'
        '  - name: "leave-me-alone"\n'
        '    seconds: 2.0\n'
        '    shard: 2\n'
        '  - name: "errored-gate"\n'
        '    seconds: 3.0\n'
        '    shard: 3\n'
    )
    results = [
        GateResult(_fake_gate("refresh-me", "true"), "pass", 9.5),
        GateResult(_fake_gate("leave-me-alone", "true"), "pass", 2.0),
        GateResult(_fake_gate("errored-gate", "true"), "error", 600.0),
    ]
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "manifest.yml"
        p.write_text(manifest_text)
        new_text, changed = refresh_manifest(results, p)
    if [c[0] for c in changed] != ["refresh-me"]:
        return (f"FAIL refresh-manifest: expected only 'refresh-me' rewritten (an "
                f"unchanged value and an error-status result must both be left alone), "
                f"got {changed!r}")
    if "seconds: 9.5" not in new_text:
        return f"FAIL refresh-manifest: new measured value not written: {new_text!r}"
    if "a comment that must survive the rewrite" not in new_text:
        return "FAIL refresh-manifest: a hand-written comment was lost during rewrite"
    if "seconds: 3.0" not in new_text:
        return ("FAIL refresh-manifest: an ERROR-status gate's declared seconds was "
                 "overwritten with its timeout-bound elapsed time")
    return None


def _rule_refresh_manifest_rewrites_through_a_comment_between_name_and_seconds():
    """The exact shape this branch's own manifest correction added (see
    `.github/generated-views-manifest.yml`'s multi-line comment explaining the 40.1s
    figure, which sits between that gate's `name:` and `seconds:` lines): a comment (or
    several, or a blank line) between the two must not make the scan give up on the entry
    and silently skip it -- that would make `--refresh-manifest` claim 'nothing to
    correct' on an entry that visibly drifted, the exact false-green shape this whole
    feature exists to refuse."""
    manifest_text = (
        'gates:\n'
        '  - name: "commented-gate"\n'
        '    # why this gate costs what it costs, line one\n'
        '    # line two of the explanation\n'
        '\n'
        '    seconds: 0.7\n'
        '    shard: 1\n'
    )
    results = [GateResult(_fake_gate("commented-gate", "true"), "pass", 40.1)]
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "manifest.yml"
        p.write_text(manifest_text)
        new_text, changed = refresh_manifest(results, p)
    if [c[0] for c in changed] != ["commented-gate"]:
        return (f"FAIL refresh-manifest-through-comment: a comment (and a blank line) "
                f"between `name:` and `seconds:` made the scan lose track of the entry "
                f"-- expected 'commented-gate' rewritten, got {changed!r}")
    if "seconds: 40.1" not in new_text:
        return (f"FAIL refresh-manifest-through-comment: new measured value not "
                f"written: {new_text!r}")
    if "why this gate costs what it costs, line one" not in new_text:
        return "FAIL refresh-manifest-through-comment: the comment was lost during rewrite"
    return None


def selftest() -> int:
    import tempfile

    checks = [
        ("does-not-stop-at-first-failure", _rule_does_not_stop_at_first_failure),
        ("could-not-run-is-distinct-from-failed", _rule_could_not_run_is_distinct_from_failed),
        ("missing-python-script-is-error", _rule_missing_python_script_is_error),
        ("zero-gates-is-a-failure", _rule_zero_gates_is_a_failure),
        ("drift-flags-real-drift-and-spares-noise", _rule_drift_flags_real_drift_and_spares_noise),
        ("drift-uses-ratio-when-only-one-side-clears-the-floor",
         _rule_drift_uses_ratio_when_only_one_side_clears_the_floor),
        ("drift-below-floor-uses-absolute-difference", _rule_drift_below_floor_uses_absolute_difference),
        ("a-run-that-finds-drift-does-not-exit-0", _rule_a_run_that_finds_drift_does_not_exit_0),
        ("check-drift-is-skipped-at-j-greater-than-1", _rule_check_drift_is_skipped_at_j_greater_than_1),
        ("refresh-manifest-rewrites-only-drifted-pass-fail-gates",
         _rule_refresh_manifest_rewrites_only_drifted_pass_fail_gates),
        ("refresh-manifest-rewrites-through-a-comment-between-name-and-seconds",
         _rule_refresh_manifest_rewrites_through_a_comment_between_name_and_seconds),
    ]
    fails = []
    for label, fn in checks:
        msg = fn()
        if msg:
            fails.append(msg)
        else:
            print(f"demonstrated: {label}")

    with tempfile.TemporaryDirectory() as td:
        msg = _rule_selftest_gates_never_run_concurrently(Path(td))
        if msg:
            fails.append(msg)
        else:
            print("demonstrated: selftest-gates-never-run-concurrently")

    guards = [
        ("a fully passing run reports green", _guard_a_fully_passing_run_reports_green),
        ("a non-drifted gate reports green", _guard_no_drift_reports_green),
    ]
    for label, fn in guards:
        guard_msg = fn()
        if guard_msg:
            fails.append(guard_msg)
        else:
            print(f"guard held: {label}")

    for f in fails:
        print(f)
    if fails:
        print(f"\n{len(fails)} rule(s) did not hold")
        return 1
    print(f"\n{len(checks) + 1} violation(s) demonstrated failing; "
          f"{len(guards)} guard(s) that must not fire held")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true",
                     help="print every gate the workflow runs, without running it")
    ap.add_argument("--selftest", action="store_true",
                     help="prove each property above can fail, against synthetic fixtures")
    ap.add_argument("-j", "--jobs", type=int, default=1,
                     help="parallel workers for non-selftest gates (default 1, serial). "
                          "--selftest gates are ALWAYS run one at a time, after every "
                          "other gate has finished -- this flag never touches them.")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS,
                     help=f"per-gate timeout in seconds (default {DEFAULT_TIMEOUT_SECONDS})")
    ap.add_argument("--no-check-drift", action="store_true",
                     help="skip comparing measured seconds against "
                          ".github/generated-views-manifest.yml's declared seconds "
                          "(on by default for a -j 1 run; always skipped at -j >1)")
    ap.add_argument("--refresh-manifest", action="store_true",
                     help="after running (must be -j 1), rewrite "
                          ".github/generated-views-manifest.yml's declared seconds from "
                          "this run's own measurements, for every pass/fail gate whose "
                          "measured cost differs from what's declared")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    gates = load_gates()

    if args.list:
        sys.exit(cmd_list(gates))

    sys.exit(cmd_run(gates, jobs=max(1, args.jobs), timeout=args.timeout,
                      check_drift=not args.no_check_drift,
                      do_refresh_manifest=args.refresh_manifest))


if __name__ == "__main__":
    main()
