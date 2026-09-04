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
    """GATE_SLICE=n/k keeps every k-th gate starting at n, in name order, WITHIN each phase.

    The first CI run of this suite measured why: four full-corpus walks on one 4-core
    runner ran 4-5x slower than locally (410 s for a 92 s gate) and one gate hit a budget
    written for a runner to itself. Every gate's timeout in the registry assumes exclusive
    use of a runner, as the old shards gave it. So CI runs one gate at a time per runner and
    spreads the gates over runners instead -- round-robin by sorted name, computed here at
    collection time, so the registry stays the only list and nothing is bin-packed by hand.
    Unset (a developer's `pytest -n auto`) means every gate; fast machines parallelise fine.
    """
    spec = os.environ.get("GATE_SLICE", "").strip()
    if not spec:
        return lambda i: True
    n, k = (int(x) for x in spec.split("/"))
    assert 1 <= n <= k, f"GATE_SLICE={spec!r}: expected n/k with 1 <= n <= k"
    return lambda i: i % k == n - 1


def _params():
    keep = _slice()
    by_phase = {"check": [], "selftest": []}
    for g in sorted(GATES, key=lambda g: (g.tier, g.name)):
        by_phase["selftest" if g.serial else "check"].append(g)
    chosen = {id(g) for phase in by_phase.values() for i, g in enumerate(phase) if keep(i)}
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
