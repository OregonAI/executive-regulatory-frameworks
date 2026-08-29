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

OUT OF SCOPE (#318): changing the sharding, the manifest, or any gate's own logic; making
this script itself a CI gate (CI already runs the gates -- this is the local mirror).
"""
import argparse
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


def cmd_run(gates, jobs=1, timeout=DEFAULT_TIMEOUT_SECONDS) -> int:
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

    if failed or errored:
        print("\nFAILING / COULD-NOT-RUN GATES, named together (not just the first):")
        for r in failed:
            print(f"  FAIL   {r.gate.name}  ({r.gate.shard_job})")
        for r in errored:
            print(f"  ERROR  {r.gate.name}  ({r.gate.shard_job}): {r.detail}")
        return 1

    print(f"\nall {len(results)} gate(s) green.")
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


def selftest() -> int:
    import tempfile

    checks = [
        ("does-not-stop-at-first-failure", _rule_does_not_stop_at_first_failure),
        ("could-not-run-is-distinct-from-failed", _rule_could_not_run_is_distinct_from_failed),
        ("missing-python-script-is-error", _rule_missing_python_script_is_error),
        ("zero-gates-is-a-failure", _rule_zero_gates_is_a_failure),
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

    guard_msg = _guard_a_fully_passing_run_reports_green()
    if guard_msg:
        fails.append(guard_msg)
    else:
        print("guard held: a fully passing run reports green")

    for f in fails:
        print(f)
    if fails:
        print(f"\n{len(fails)} rule(s) did not hold")
        return 1
    print(f"\n{len(checks) + 1} violation(s) demonstrated failing; "
          f"1 guard that must not fire held")
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
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    gates = load_gates()

    if args.list:
        sys.exit(cmd_list(gates))

    sys.exit(cmd_run(gates, jobs=max(1, args.jobs), timeout=args.timeout))


if __name__ == "__main__":
    main()
