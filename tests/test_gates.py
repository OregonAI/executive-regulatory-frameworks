"""Run every gate in `tests/gates.py`, one test each, named for the gate.

    pytest -n auto -m "check and not nightly"           # phase 1: parallel-safe checks
    pytest -p no:xdist -m "selftest and not nightly"    # phase 2: tree-mutating gates, serial
    pytest -k "STATUS.md"                               # one gate
    pytest --durations=20                               # where the time goes

A failing gate prints its argv and the tail of its own output, which is what the old
workflow showed one step at a time. Timeouts are per gate, from the registry; the subprocess
is killed at that limit and the failure names the gate rather than cancelling a job.
"""
import subprocess
import sys

import pytest

from conftest import REPO_ROOT
from gates import GATES

TAIL = 80


def _params():
    for g in GATES:
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


def test_every_gate_has_a_unique_name_and_a_tier():
    names = [g.name for g in GATES]
    assert len(names) == len(set(names))
    assert {g.tier for g in GATES} <= {"pr", "nightly"}
    assert len(GATES) > 50, "discovering almost no gates is a failure, not a green run"
