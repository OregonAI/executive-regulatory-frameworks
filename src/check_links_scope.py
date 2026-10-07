#!/usr/bin/env python3
"""The weekly lychee scan covers the links THIS corpus publishes, and not the law it mirrors (#435).

  python3 src/check_links_scope.py --check      # CI: the caller's exclude-paths vs the tree
  python3 src/check_links_scope.py --selftest   # CI: every rule below, watched failing

WHY THIS EXISTS. `check-links.yml` ran lychee over every one of ~81k markdown files and never
passed: ~45-60 minutes and red through 2026-09-14, then cancelled at the six-hour job limit
three Mondays running. Almost every one of those files is `content_mode: verbatim` -- a
faithful copy of an OAR/ORS/EO/policy -- and a faithful copy of a page that cites a URL that
died years ago is ACCURATE, not link rot. "Fixing" it would mean editing the law.

The scope is expressed in the caller's `exclude-paths`, which the toolkit's reusable workflow
hands to lychee as one `--exclude-path <regex>` per line. A hand-kept list of 80k paths is not
an option and a hand-kept list of prefixes silently rots the day a new agency's policies land,
so THIS GATE derives the truth from the tree (each document's own `content_mode`) and compares
it to what the workflow excludes, in both directions:

  verbatim-not-excluded    a mirrored document lychee would scan: the scan grows back toward
                           the six-hour wall, one new agency prefix at a time. Add its prefix
                           to `exclude-paths`.
  curated-excluded         a document that is OURS (`summary`, an `_index.md`, a CHANGELOG, a
                           README) that the workflow hides from lychee. Hiding our own prose
                           from the link check is the opposite of the point. Where lychee's
                           path regex cannot express "this verbatim prefix except those
                           files" (it has no look-ahead), the loss is DECLARED in
                           `KNOWN_UNCOVERED` with its reason, never silent.
  stale-declaration        a `KNOWN_UNCOVERED` entry that is no longer excluded or no longer
                           curated: a declaration about the world that stopped being true.
  unsafe-pattern           a character outside `[A-Za-z0-9_./-]`. The reusable workflow splices
                           these lines into a shell command unquoted, so a glob or regex
                           metacharacter is a different pattern in lychee than it is here.

What is NOT checked here: that lychee's `--exclude-path` is a regular-expression SEARCH over
the path (its documented behaviour as of v0.24.2). The patterns are written to mean the same
thing under a plain substring reading, which is the weaker of the two, so this gate and
lychee agree under either. The first dispatched run's "Excluded"/"Total" counts are the
live confirmation.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ".github/workflows/check-links.yml"

# Paths the workflow has always excluded for reasons that are not about verbatim law
# (snapshots and templates are inputs/fixtures). They are exempt from `curated-excluded`.
INFRA_EXCLUDES = ("_meta/snapshots", "_meta/templates")

SAFE = re.compile(r"^[A-Za-z0-9_./-]+$")

# Curated (`content_mode: summary`) documents the verbatim prefixes in `exclude-paths` also
# hide, because the prefix cannot tell them from the verbatim siblings that share it. Their
# own `source_url`s are still fetched by `src/check_source_urls.py`; their body links are the
# only thing not scanned. Each entry is (path, why).
KNOWN_UNCOVERED = {
    ".out-of-scope/dhs-policy-transmittals-full-ingest.md":
        "our own decision record, hidden dir; shares the `/dhs-` prefix with the verbatim DHS policies",
    "executive-orders/eo-12-09.md": "summary EO; shares the `executive-orders/eo-` prefix with 524 verbatim EOs",
    "executive-orders/eo-16-15.md": "summary EO; shares the `executive-orders/eo-` prefix with 524 verbatim EOs",
    "agencies/department-of-administrative-services/accounting-manual/oam-55-30-00-appendix-b.md":
        "summary OAM exhibit; shares the `/oam-` prefix with 170 verbatim chapters",
    "agencies/department-of-administrative-services/accounting-manual/oam-75-35-12-fo.md":
        "summary OAM exhibit; shares the `/oam-` prefix with 170 verbatim chapters",
    "agencies/department-of-administrative-services/accounting-manual/oam-75-40-01-fo.md":
        "summary OAM exhibit; shares the `/oam-` prefix with 170 verbatim chapters",
}

FM = re.compile(r"\A---\r?\n(.*?)\r?\n---", re.S)
MODE = re.compile(r"^content_mode:\s*['\"]?([A-Za-z_-]+)", re.M)


def content_mode(text: str) -> str | None:
    """The document's own `content_mode`, or None when it has no frontmatter / no field."""
    m = FM.match(text)
    if not m:
        return None
    mm = MODE.search(m.group(1))
    return mm.group(1) if mm else None


def exclude_patterns(workflow_text: str) -> list[str]:
    wf = yaml.safe_load(workflow_text)
    raw = wf["jobs"]["links"]["with"].get("exclude-paths", "") or ""
    return [ln.strip() for ln in raw.splitlines() if ln.strip()]


def scan_inputs(root: Path):
    """Files lychee may be handed: `./**/*.md` and `llms.txt`. Hidden directories are INCLUDED
    (only `.git` and `.toolkit` are not): whether lychee's glob descends into them is not
    verified, and the gate errs toward over-checking, so a verbatim document placed under a
    hidden directory cannot escape it. The first run's "Total" count shows which it is."""
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in (".git", ".toolkit"))
        for f in sorted(files):
            if f.endswith(".md"):
                yield Path(dirpath, f).relative_to(root).as_posix()
    if (root / "llms.txt").exists():
        yield "llms.txt"


def excluded(path: str, regexes) -> bool:
    return any(r.search(path) for r in regexes)


def evaluate(root: Path, patterns: list[str], known=KNOWN_UNCOVERED, infra=INFRA_EXCLUDES):
    """Return (findings, counts). Findings are (rule, path-or-pattern, detail)."""
    findings = []
    for p in patterns:
        if not SAFE.match(p):
            findings.append(("unsafe-pattern", p, "outside [A-Za-z0-9_./-]"))
    regexes = [re.compile(p) for p in patterns if SAFE.match(p)]
    counts = {"scanned": 0, "excluded-verbatim": 0, "excluded-infra": 0, "excluded-curated": 0}
    still_excluded_curated = set()
    for rel in scan_inputs(root):
        if rel == "llms.txt":
            mode = None
        else:
            mode = content_mode((root / rel).read_text(encoding="utf-8", errors="replace"))
        ex = excluded(rel, regexes)
        if any(rel.startswith(i + "/") for i in infra) and ex:
            counts["excluded-infra"] += 1
        elif ex and mode == "verbatim":
            counts["excluded-verbatim"] += 1
        elif ex:
            counts["excluded-curated"] += 1
            still_excluded_curated.add(rel)
            if rel not in known:
                findings.append(("curated-excluded", rel, f"content_mode={mode!r} but hidden from lychee"))
        elif mode == "verbatim":
            findings.append(("verbatim-not-excluded", rel, "mirrored text lychee would scan"))
        else:
            counts["scanned"] += 1
    for rel in known:
        if rel not in still_excluded_curated:
            findings.append(("stale-declaration", rel, "KNOWN_UNCOVERED but not excluded-and-curated today"))
    return findings, counts


def check() -> int:
    patterns = exclude_patterns((ROOT / WORKFLOW).read_text())
    findings, counts = evaluate(ROOT, patterns)
    print(f"  exclude-paths: {len(patterns)} pattern(s)")
    print("  " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    if findings:
        by = {}
        for rule, path, detail in findings:
            by.setdefault(rule, []).append((path, detail))
        for rule, items in sorted(by.items()):
            print(f"FAIL {rule}: {len(items)}", file=sys.stderr)
            for path, detail in items[:10]:
                print(f"       {path}  ({detail})", file=sys.stderr)
            if len(items) > 10:
                print(f"       ... {len(items) - 10} more", file=sys.stderr)
        return 1
    print(f"ok: lychee scans {counts['scanned']} curated file(s); every verbatim document is out of scope "
          f"and {counts['excluded-curated']} curated file(s) are declared uncovered")
    return 0


def _w(root: Path, rel: str, mode: str | None):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = f"---\ncontent_mode: {mode}\n---\nbody\n" if mode else "no frontmatter\n"
    p.write_text(fm)


def selftest() -> int:
    fails = []

    def expect(name, got_rules, want_rules):
        if sorted(got_rules) != sorted(want_rules):
            fails.append(f"{name}: got {sorted(got_rules)}, want {sorted(want_rules)}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _w(root, "rules/101/oar-101-001-0001.md", "verbatim")
        _w(root, "rules/_index.md", None)
        _w(root, "README.md", None)
        _w(root, "agencies/a/policies/_index.md", None)
        _w(root, "agencies/a/policies/pol-1.md", "summary")
        _w(root, "_meta/templates/rule.md", "verbatim")
        _w(root, ".hidden/oar-x.md", "verbatim")  # hidden dirs are scanned by the gate
        (root / "llms.txt").write_text("x")

        f, c = evaluate(root, ["/oar-", "_meta/templates"], known={}, infra=("_meta/templates",))
        expect("clean scope is green", [r for r, *_ in f], [])
        if (c["scanned"], c["excluded-verbatim"], c["excluded-infra"]) != (5, 2, 1):
            fails.append(f"counts wrong: {c}")

        f, _ = evaluate(root, ["_meta/templates"], known={}, infra=("_meta/templates",))
        expect("verbatim doc left in scope fails (hidden dir included)", [r for r, *_ in f],
               ["verbatim-not-excluded", "verbatim-not-excluded"])

        f, _ = evaluate(root, ["/oar-", "pol-"], known={}, infra=("_meta/templates",))
        expect("curated doc hidden fails", [r for r, *_ in f],
               ["curated-excluded", "verbatim-not-excluded"])  # the template is no longer excluded

        f, _ = evaluate(root, ["/oar-", "pol-", "_meta/templates"],
                        known={"agencies/a/policies/pol-1.md": "declared"}, infra=("_meta/templates",))
        expect("declared curated loss is allowed", [r for r, *_ in f], [])

        f, _ = evaluate(root, ["/oar-", "_meta/templates"],
                        known={"agencies/a/policies/pol-1.md": "declared"}, infra=("_meta/templates",))
        expect("stale declaration fails", [r for r, *_ in f], ["stale-declaration"])

        f, _ = evaluate(root, ["/oar-", "_meta/templates", "rules/(a|b)"], known={}, infra=("_meta/templates",))
        expect("shell/regex metacharacter fails", [r for r, *_ in f], ["unsafe-pattern"])

    if content_mode("---\ncontent_mode: \"verbatim\"\n---\n") != "verbatim":
        fails.append("quoted content_mode not read")
    if content_mode("no frontmatter") is not None:
        fails.append("missing frontmatter must be None, not a mode")

    for m in fails:
        print("FAIL", m, file=sys.stderr)
    if fails:
        return 1
    print("selftest ok: scope rules fire (verbatim-not-excluded, curated-excluded, stale-declaration, unsafe-pattern)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    raise SystemExit(check() if a.check else selftest())
