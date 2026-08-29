#!/usr/bin/env python3
"""Keep the `generated-views` gate sweep sharded honestly (#268).

  python3 src/shard_generated_views.py --check          # exit 1 on any drift (CI)
  python3 src/shard_generated_views.py --selftest        # prove --check can fail
  python3 src/shard_generated_views.py --plan N          # bin-pack by seconds into N shards

`generated-views` used to be one job running every PR-tier gate serially -- 38.8
minutes against a 60-minute cap, headroom that only shrinks as the corpus grows
(#267 raised the cap once already; the count went from 55 gates to 71 in two days).
It is now a FAN-IN job (unchanged name -- branch protection requires it BY NAME,
so the required check keeps reporting) that depends on several
`generated-views-shard-N` jobs running the same gates in parallel.

THE FAILURE MODE THIS FILE EXISTS TO CATCH: a gate silently dropped during the
split. Nothing stops a future edit from adding a step to one shard job and
forgetting the others exist, or moving a step between shards without updating the
manifest that says where it lives. `--check` reads the ACTUAL steps committed in
`.github/workflows/validate-frontmatter.yml` and the ACTUAL manifest
(`.github/generated-views-manifest.yml`) and fails on any of three drifts:

  - a gate the workflow runs that the manifest does not name (dropped from cost
    accounting -- the shard it landed in may now be miscalibrated, or it may not
    be running as part of any shard's asserted total at all)
  - a gate the manifest names that no shard job actually runs (a stale entry --
    renamed, deleted, or never wired up)
  - a gate the manifest assigns to shard N that is actually a step under a
    DIFFERENT shard job in the workflow (the planning doc and the real placement
    disagree, which is exactly the drift a reviewable manifest is supposed to make
    visible instead of silent)

It also checks that the fan-in job's `needs:` list is exactly the set of shard
jobs the workflow defines -- a shard job nothing depends on is a shard whose
failure the required check would never see.

TWO MORE DRIFTS a code-review follow-up to #268 found this file did not check for,
because both are invisible to every rule above (they touch neither the gate steps
nor the manifest): shards 1-4 lost the corpus-toolkit install that shard-5 kept,
because nothing compared one shard's toolchain preamble against another's -- fixed
by `setup_steps_by_shard()`, asserting every shard's non-gate steps are identical;
and the fan-in job's `if: always()` could be dropped with every check above still
green, silently reintroducing "a skipped required check does not report a failure"
-- fixed by asserting `if: always()` directly on the fan-in job.

Nightly-only gates (`generated-views-nightly`, conditioned on
schedule/workflow_dispatch) are out of scope for this manifest by design -- #268
says explicitly they are "not what a PR waits on", so they carry no measured
PR-tier seconds and are not bin-packed.
"""
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github/workflows/validate-frontmatter.yml"
MANIFEST = REPO_ROOT / ".github/generated-views-manifest.yml"

FANIN_JOB = "generated-views"
SHARD_PREFIX = "generated-views-shard-"


def _yaml_load_workflow(text):
    # PyYAML treats the bare scalar `on:` as the boolean key `True` (YAML 1.1) --
    # harmless here since we only ever read `jobs`, but load with a loader that
    # keeps plain string keys so a future reader isn't surprised.
    return yaml.safe_load(text)


def shard_job_ids(doc):
    """Every `generated-views-shard-N` job id defined in the workflow, in file order."""
    jobs = doc.get("jobs", {})
    return [j for j in jobs if j.startswith(SHARD_PREFIX)]


NIGHTLY_JOB = "generated-views-nightly"


def gate_steps_for_job(doc, job_id):
    """[(gate name, run command), ...] for every named+run step in ONE job, in file
    order. A step missing either `name` or `run` (checkout, setup-python, pip
    install) is not a gate and is skipped -- gates are the steps this corpus's own
    code runs as a pass/fail check. This is the underlying filter every other
    gate-step reader in this module applies to a single job's `steps:` list; it
    exists so that filter is written once."""
    jobs = doc.get("jobs", {})
    steps = jobs.get(job_id, {}).get("steps", [])
    return [(s["name"], s["run"]) for s in steps if "name" in s and "run" in s]


def gate_steps_by_shard(doc):
    """{shard_job_id: [(gate name, run command), ...]} for every named+run step in
    each shard job, in file order -- `gate_steps_for_job` applied to every
    `generated-views-shard-N` job. This is the one parser of the workflow's
    PR-tier gate steps; `gates_by_shard` (the names alone, for the manifest-drift
    check below) and `check_all.py` (the runnable commands, #318) both read it
    rather than each holding its own regex over the YAML -- a second reader would
    be one fact declared twice with nothing gating agreement, the `CONTEXT.md`
    *Stated figure* defect class this repo keeps paying for.

    Deliberately excludes `generated-views-nightly` (see that job's steps via
    `gate_steps_for_job(doc, NIGHTLY_JOB)` instead) -- #268 scoped THIS shard/
    manifest/bin-packing system to what a PR waits on, and the nightly job's own
    `if:` keeps it off every PR run. `check_all.py` reads both, because "every
    gate CI runs" is a broader claim than "every gate the PR-tier manifest bin-
    packs" -- #329.
    """
    return {job_id: gate_steps_for_job(doc, job_id) for job_id in shard_job_ids(doc)}


def gates_by_shard(doc):
    """{shard_job_id: [gate name, ...]} -- the names alone, off gate_steps_by_shard."""
    return {job_id: [name for name, _run in steps]
            for job_id, steps in gate_steps_by_shard(doc).items()}


def setup_steps_by_shard(doc):
    """{shard_job_id: [step, ...]} for every step that is NOT a gate -- the toolchain
    preamble (checkout / setup-python / composite action) each shard runs before its
    own gates. The inverse selection from gates_by_shard's: a step missing `name` or
    `run` is setup, not a gate.

    This is what shards 1-4 losing the corpus-toolkit install (the HARD finding this
    file's own #268 code-review follow-up fixed) would have been caught by, had it
    existed then: shard-5 kept two setup steps its siblings silently dropped, and
    nothing compared the shards' preambles against each other.
    """
    jobs = doc.get("jobs", {})
    out = {}
    for job_id in shard_job_ids(doc):
        steps = jobs[job_id].get("steps", [])
        out[job_id] = [s for s in steps if not ("name" in s and "run" in s)]
    return out


def fanin_needs(doc):
    jobs = doc.get("jobs", {})
    fanin = jobs.get(FANIN_JOB, {})
    needs = fanin.get("needs", [])
    if isinstance(needs, str):
        needs = [needs]
    return list(needs)


def load_manifest(path=MANIFEST):
    data = yaml.safe_load(path.read_text())
    return data.get("gates", [])


def diff(workflow_doc, manifest_gates):
    """Return a list of human-readable failure strings; empty means consistent.

    Pure function of two already-parsed structures so --selftest can drive it
    against synthetic fixtures without touching the committed files.
    """
    fails = []

    by_shard = gates_by_shard(workflow_doc)
    workflow_gate_names = set()
    gate_actual_shard = {}
    for job_id, names in by_shard.items():
        for n in names:
            if n in workflow_gate_names:
                fails.append(f"duplicate gate name across shard jobs: {n!r} "
                             f"appears more than once in the workflow")
            workflow_gate_names.add(n)
            gate_actual_shard[n] = job_id

    manifest_by_name = {}
    for g in manifest_gates:
        name = g["name"]
        if name in manifest_by_name:
            fails.append(f"duplicate manifest entry: {name!r}")
        manifest_by_name[name] = g

    manifest_names = set(manifest_by_name)

    dropped = workflow_gate_names - manifest_names
    for n in sorted(dropped):
        fails.append(f"gate runs in the workflow (job {gate_actual_shard[n]}) but is "
                      f"absent from the manifest: {n!r}")

    orphaned = manifest_names - workflow_gate_names
    for n in sorted(orphaned):
        fails.append(f"manifest names a gate no shard job runs: {n!r}")

    for n in sorted(workflow_gate_names & manifest_names):
        entry = manifest_by_name[n]
        want_job = f"{SHARD_PREFIX}{entry['shard']}"
        actual_job = gate_actual_shard[n]
        if want_job != actual_job:
            fails.append(f"manifest assigns {n!r} to shard {entry['shard']} "
                          f"({want_job}) but the workflow runs it under {actual_job!r}")

    workflow_shards = set(shard_job_ids(workflow_doc))
    needs = set(fanin_needs(workflow_doc))
    missing_needs = workflow_shards - needs
    for j in sorted(missing_needs):
        fails.append(f"shard job {j!r} exists but {FANIN_JOB!r} does not depend on it "
                      f"-- its failure would never be asserted")
    stale_needs = needs - workflow_shards
    for j in sorted(stale_needs):
        fails.append(f"{FANIN_JOB!r} needs {j!r}, which no longer exists as a job")

    # A shard silently missing a setup step (e.g. the corpus-toolkit install) is not a
    # drift the checks above can see at all -- they only look at gate steps. Compare
    # every shard's non-gate preamble against the first shard's; any shard whose setup
    # differs is exactly the "subtly less capable sibling" the HARD finding found.
    setup = setup_steps_by_shard(workflow_doc)
    if setup:
        reference_job = min(setup)  # stable, file-order-independent pick
        reference = setup[reference_job]
        for job_id in sorted(setup):
            if setup[job_id] != reference:
                fails.append(
                    f"{job_id!r}'s setup steps differ from {reference_job!r}'s -- every "
                    f"shard must share one toolchain preamble (#268 code review)")

    # `if: always()` is what makes the fan-in step run -- and its assertion fire -- when
    # a shard fails, is cancelled, or is skipped, rather than the fan-in job itself being
    # SKIPPED (a skipped required check does not report a failure). Losing this line is
    # invisible to every check above: the `needs:` list, the gate/manifest parity, and
    # the shard steps themselves are all untouched.
    fanin_job = workflow_doc.get("jobs", {}).get(FANIN_JOB, {})
    if fanin_job.get("if") != "always()":
        fails.append(
            f"{FANIN_JOB!r} must be `if: always()` -- without it, a failing shard "
            f"SKIPS the fan-in instead of failing it, and a skipped required check "
            f"does not report a failure (#268)")

    return fails


def check(workflow_path=None, manifest_path=None) -> int:
    workflow_path = workflow_path or WORKFLOW
    manifest_path = manifest_path or MANIFEST
    doc = _yaml_load_workflow(workflow_path.read_text())
    gates = load_manifest(manifest_path)
    fails = diff(doc, gates)
    if fails:
        for f in fails:
            print(f"FAIL  {f}")
        print(f"\n{len(fails)} drift(s) between the workflow and "
              f"{manifest_path.name}.")
        return 1
    n_shards = len(shard_job_ids(doc))
    print(f"manifest and workflow agree: {len(gates)} gate(s) across {n_shards} shard(s), "
          f"{FANIN_JOB!r} depends on all of them.")
    return 0


# ---- synthetic fixtures for --selftest ----

def _fixture_workflow(shard2_names=("gate-b",), shard2_setup=None):
    setup = [{"uses": "./.github/actions/generated-views-setup"}]
    return {
        "jobs": {
            "generated-views-shard-1": {
                "steps": setup + [
                    {"name": "gate-a", "run": "true"},
                ]
            },
            "generated-views-shard-2": {
                "steps": (shard2_setup if shard2_setup is not None else setup)
                + [{"name": n, "run": "true"} for n in shard2_names]
            },
            FANIN_JOB: {
                "needs": ["generated-views-shard-1", "generated-views-shard-2"],
                "if": "always()",
            },
        }
    }


def _fixture_manifest(entries=(("gate-a", 1), ("gate-b", 2))):
    return [{"name": n, "seconds": 1.0, "shard": s} for n, s in entries]


def selftest() -> int:
    fails = []

    # RULE 1: a gate the workflow runs that the manifest does not name is caught.
    wf = _fixture_workflow()
    mf = _fixture_manifest(entries=[("gate-a", 1)])  # gate-b missing
    found = diff(wf, mf)
    if not any("gate-b" in f and "absent from the manifest" in f for f in found):
        fails.append("FAIL dropped-gate-is-caught: removing gate-b from the manifest "
                      f"produced {found!r}")

    # RULE 2: a manifest entry naming a gate nothing runs is caught.
    wf = _fixture_workflow()
    mf = _fixture_manifest(entries=[("gate-a", 1), ("gate-b", 2), ("gate-ghost", 2)])
    found = diff(wf, mf)
    if not any("gate-ghost" in f and "no shard job runs" in f for f in found):
        fails.append("FAIL orphaned-manifest-entry-is-caught: adding gate-ghost to the "
                      f"manifest produced {found!r}")

    # RULE 3: a manifest shard assignment that disagrees with where the step
    # actually lives is caught -- gate-b really runs under shard-2, manifest says 1.
    wf = _fixture_workflow()
    mf = _fixture_manifest(entries=[("gate-a", 1), ("gate-b", 1)])
    found = diff(wf, mf)
    if not any("gate-b" in f and "shard 1" in f and "generated-views-shard-2" in f
               for f in found):
        fails.append("FAIL shard-mismatch-is-caught: manifest claiming shard 1 for a "
                      f"gate that runs under shard-2 produced {found!r}")

    # RULE 4: a shard job the fan-in does not depend on is caught.
    wf = _fixture_workflow()
    wf["jobs"][FANIN_JOB]["needs"] = ["generated-views-shard-1"]  # shard-2 dropped
    mf = _fixture_manifest()
    found = diff(wf, mf)
    if not any("generated-views-shard-2" in f and "does not depend on it" in f
               for f in found):
        fails.append("FAIL unwatched-shard-is-caught: a shard the fan-in does not need "
                      f"produced {found!r}")

    # RULE 5: a stale `needs:` entry naming a shard that no longer exists is caught.
    wf = _fixture_workflow()
    wf["jobs"][FANIN_JOB]["needs"] = ["generated-views-shard-1",
                                       "generated-views-shard-2",
                                       "generated-views-shard-9"]
    mf = _fixture_manifest()
    found = diff(wf, mf)
    if not any("generated-views-shard-9" in f and "no longer exists" in f for f in found):
        fails.append("FAIL stale-needs-entry-is-caught: needing a job that does not "
                      f"exist produced {found!r}")

    # RULE 6: a shard whose setup steps differ from its siblings' is caught -- this is
    # precisely how shards 1-4 lost the corpus-toolkit install while shard-5 kept it.
    wf = _fixture_workflow(shard2_setup=[{"uses": "actions/checkout@v4"}])  # no toolkit
    mf = _fixture_manifest()
    found = diff(wf, mf)
    if not any("generated-views-shard-2" in f and "setup steps differ" in f for f in found):
        fails.append("FAIL divergent-shard-setup-is-caught: shard-2 missing the toolkit "
                      f"install produced {found!r}")

    # RULE 7: a fan-in missing `if: always()` is caught -- without it, a failing shard
    # SKIPS the fan-in instead of failing it, and a skipped required check does not
    # report a failure.
    wf = _fixture_workflow()
    del wf["jobs"][FANIN_JOB]["if"]
    mf = _fixture_manifest()
    found = diff(wf, mf)
    if not any(FANIN_JOB in f and "always()" in f for f in found):
        fails.append("FAIL missing-if-always-is-caught: dropping `if: always()` from the "
                      f"fan-in produced {found!r}")

    # GUARD THAT MUST NOT FIRE: a fully consistent fixture reports nothing.
    wf = _fixture_workflow()
    mf = _fixture_manifest()
    found = diff(wf, mf)
    if found:
        fails.append(f"FAIL a-consistent-manifest-produces-no-finding: {found!r}")

    for f in fails:
        print(f)
    if fails:
        print(f"{len(fails)} rule(s) did not hold")
        return 1
    print("7 violation(s) demonstrated failing; 1 guard that must not fire held")
    return 0


# ---- bin-packing planner ----

def plan(gates, n_shards, colocate=()):
    """Longest-Processing-Time-first bin packing into n_shards, by seconds.

    `colocate` is a sequence of (name-group, combined_seconds) pairs -- e.g. the
    two llms.txt gates, packed as one unit before the rest, per #268's
    "co-locate and build the fixture once" instruction. `combined_seconds` is
    the group's MEASURED combined runtime when run as the one shared-build
    invocation it becomes (`build_llms.py --check --selftest`), not the sum of
    the two gates' standalone seconds -- summing would double-count the build
    the co-location exists to stop paying twice. Pass None for a group to fall
    back to the sum (i.e. no sharing is actually happening, just adjacency).
    """
    by_name = {g["name"]: g["seconds"] for g in gates}
    units = []  # (total_seconds, [names])
    grouped = set()
    for group, combined_seconds in colocate:
        total = combined_seconds if combined_seconds is not None else sum(by_name[n] for n in group)
        units.append((total, list(group)))
        grouped.update(group)
    for g in gates:
        if g["name"] not in grouped:
            units.append((g["seconds"], [g["name"]]))
    units.sort(key=lambda u: -u[0])

    bins = [[] for _ in range(n_shards)]
    totals = [0.0] * n_shards
    for total, names in units:
        i = totals.index(min(totals))
        bins[i].extend(names)
        totals[i] += total
    return bins, totals


def cmd_plan(argv):
    try:
        n = int(argv[argv.index("--plan") + 1])
    except (ValueError, IndexError):
        print("usage: shard_generated_views.py --plan N", file=sys.stderr)
        return 2
    gates = load_manifest()
    # The two llms.txt gates used to be timed (and colocated here) separately; a
    # code-review follow-up to #268 folded them into one workflow step and one manifest
    # entry ("llms.txt must be current, and name every chapter we mirror", 86.7s combined
    # -- see build_llms.py's combined --check --selftest entry point), so the manifest
    # now carries the shared cost natively and no `colocate` group is needed to represent
    # it: plain bin-packing already treats it as the one unit it actually is.
    bins, totals = plan(gates, n)
    for i, (names, total) in enumerate(zip(bins, totals), start=1):
        print(f"shard {i}: {total:.1f}s ({len(names)} gates)")
        for name in names:
            print(f"    {name}")
    print(f"\nmakespan (slowest shard, local): {max(totals):.1f}s "
          f"(~{max(totals) * 1.7 / 60:.1f} min at CI's measured 1.7x)")
    return 0


def main():
    argv = sys.argv[1:]
    if "--selftest" in argv:
        sys.exit(selftest())
    if "--plan" in argv:
        sys.exit(cmd_plan(argv))
    if "--check" in argv:
        sys.exit(check())
    print(__doc__)
    sys.exit(2)


if __name__ == "__main__":
    main()
