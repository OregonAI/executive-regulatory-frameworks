"""Run every gate in `tests/gates.py`, one test each, named for the gate.

    pytest -n auto -m "check and not nightly"           # phase 1: parallel-safe checks
    pytest -p no:xdist -m "selftest and not nightly"    # phase 2: tree-mutating gates, serial
    pytest -k "STATUS.md"                               # one gate
    pytest --durations=20                               # where the time goes

A failing gate prints its argv and the tail of its own output, which is what the old
workflow showed one step at a time. Timeouts are per gate, from the registry; the subprocess
is killed at that limit and the failure names the gate rather than cancelling a job.
"""
import os
import subprocess
import sys

import pytest

from conftest import REPO_ROOT
from gates import GATES

TAIL = 80


def _slice():
    """GATE_SLICE=n/k: this runner's share of each phase, balanced by the registry's timeouts.

    The first CI run of this suite measured why slices exist: four full-corpus walks on one
    4-core runner ran 4-5x slower than locally (410 s for a 92 s gate) and one gate hit a
    budget written for a runner to itself. So CI runs one gate at a time per runner and
    spreads the gates over runners. The second run measured why the spread must be
    cost-aware: round-robin by name put six of the heaviest walks on two runners -- 19.6 and
    13.2 minutes beside 2.3 and 1.8 -- for a 19.8-minute wall clock against 11.6 before.

    Each gate's `timeout` was set from its measured seconds with headroom, so it is the cost
    proxy the old manifest kept by hand, already in the registry. Gates are assigned longest
    budget first to the slice with the least budget so far (LPT), deterministically, within
    each phase. No manifest, no hand-packing; a gate added with an honest budget lands where
    it should. Unset (a developer's `pytest -n auto`) means every gate.
    """
    spec = os.environ.get("GATE_SLICE", "").strip()
    if not spec:
        return None
    n, k = (int(x) for x in spec.split("/"))
    assert 1 <= n <= k, f"GATE_SLICE={spec!r}: expected n/k with 1 <= n <= k"
    return n - 1, k


def assign_slices(gates, k):
    """Gate -> slice index, longest budget first onto the least-loaded slice (LPT)."""
    load = [0] * k
    out = {}
    for g in sorted(gates, key=lambda g: (-g.timeout, g.name)):
        i = min(range(k), key=lambda j: (load[j], j))
        out[id(g)] = i
        load[i] += g.timeout
    return out


def _params():
    spec = _slice()
    by_phase = {"check": [], "selftest": []}
    for g in GATES:
        by_phase["selftest" if g.serial else "check"].append(g)
    chosen = set()
    for phase_gates in by_phase.values():
        if spec is None:
            chosen.update(id(g) for g in phase_gates)
        else:
            n, k = spec
            chosen.update(gid for gid, i in assign_slices(phase_gates, k).items() if i == n)
    for g in GATES:
        if id(g) not in chosen:
            continue
        marks = [pytest.mark.selftest if g.serial else pytest.mark.check,
                 pytest.mark.timeout(g.timeout + 60)]  # backstop; the subprocess limit fires first
        if g.tier == "nightly":
            marks.append(pytest.mark.nightly)
        yield pytest.param(g, id=g.name, marks=marks)


@pytest.mark.parametrize("gate", list(_params()))
def test_gate(gate, request):
    if gate.serial:
        request.getfixturevalue("clean_tree_after")
    argv = [sys.executable, *gate.argv[1:]] if gate.argv[0] in ("python3", "python") else list(gate.argv)
    try:
        p = subprocess.run(argv, cwd=REPO_ROOT, capture_output=True, text=True, timeout=gate.timeout)
    except subprocess.TimeoutExpired as e:
        out = ((e.stdout or b"") if isinstance(e.stdout, bytes) else (e.stdout or "")).__str__()
        pytest.fail(f"TIMED OUT after {gate.timeout}s — could not run to completion, which is "
                    f"not a pass and not a failure of what it checks:\n  $ {' '.join(gate.argv)}")
    if p.returncode != 0:
        tail = "\n".join((p.stdout + p.stderr).splitlines()[-TAIL:])
        pytest.fail(f"exit {p.returncode}:\n  $ {' '.join(gate.argv)}\n{tail}")


@pytest.mark.check
def test_every_gate_has_a_unique_name_and_a_tier():
    """Runs in every check slice (it is not a gate, so it is never sliced away)."""
    names = [g.name for g in GATES]
    assert len(names) == len(set(names))
    assert {g.tier for g in GATES} <= {"pr", "nightly"}
    assert len(GATES) > 50, "discovering almost no gates is a failure, not a green run"
