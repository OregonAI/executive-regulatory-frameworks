"""The test surface for this corpus's gates (card 2 of the 2026-09-02 architecture review).

WHAT A GATE IS HERE. A subprocess, run from the repository root with exactly the argv CI ran
before this suite existed, that exits 0 or does not. `tests/gates.py` is the list; this file
is the discipline around running it: the working directory, the markers, and the guard that
keeps one serial gate's mutation from leaking into the next.

WHY A GUARD. A `--selftest` gate breaks a fixture in the working tree, watches a rule fire,
and restores it. One that dies mid-mutation leaves the tree dirty, and every gate after it
in the same job then fails for a reason that is not its own — under the old five-shard
workflow that poisoned the rest of the shard silently. Here the tree is checked after every
serial gate: a dirty tree fails THAT gate, by name, with the files listed, and is reset so
the next gate starts clean. Ignored files (`__pycache__`, caches) are left alone.
"""
import os
import pathlib
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def pytest_configure(config):
    config.addinivalue_line("markers", "check: a parallel-safe `--check` gate (phase 1)")
    config.addinivalue_line("markers", "selftest: a gate that mutates the working tree; runs serially (phase 2)")
    config.addinivalue_line("markers", "nightly: runs on schedule/workflow_dispatch only, never on a PR")
    os.chdir(REPO_ROOT)


def _dirty() -> list[str]:
    out = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [l for l in out.splitlines() if l.strip()]


@pytest.fixture
def clean_tree_after(request):
    """Fail the gate that left the tree dirty, and reset it for the next one."""
    before = _dirty()
    yield
    after = _dirty()
    leaked = sorted(set(after) - set(before))
    if leaked:
        # Reset ONLY what this gate leaked. A whole-tree `git checkout -- .` would also
        # discard a developer's own uncommitted work when the suite runs on a dirty branch,
        # which is exactly when it is run locally before a push.
        tracked = [l[3:] for l in leaked if not l.startswith("??")]
        untracked = [l[3:] for l in leaked if l.startswith("??")]
        if tracked:
            subprocess.run(["git", "checkout", "--", *tracked], cwd=REPO_ROOT, check=False)
        for path in untracked:
            target = REPO_ROOT / path
            if target.is_dir():
                import shutil; shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
        pytest.fail(f"{request.node.name} left the working tree dirty (those paths were reset "
                    f"before the next gate):\n  " + "\n  ".join(leaked))
