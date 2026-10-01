#!/usr/bin/env python3
"""DHS Policy Transmittal freshness view -- the build-time join issue #79's pilot measures
itself against, and the exact mechanism ADR 0001 describes.

For each of the 17 DHS policies this corpus holds, this answers one question: does any
ingested `doc_type: transmittal` `announce` a change to it, and on what date? The answer is
COMPUTED HERE, every run, from the transmittal's own `announces`/`effective_date`
frontmatter -- never written back into the policy's own frontmatter (ADR 0001: a derived
date in that position would read as something the policy asserts about itself, which is
exactly the failure AGENTS.md's VERBATIM/SUMMARY split exists to prevent). Ingesting more
transmittals, or none, changes nothing about any committed policy document; it only changes
what this script, rerun, reports.

This also carries the pilot's own pass/fail accounting (`join_counts`) against the bar the
issue sets, as counts rather than adjectives:

  1. the pilot set resolves a supersession or effective date for >= 50% of the DHS
     policies it references, AND
  2. it surfaces >= 1 policy currently held that is demonstrably stale (a transmittal
     announces a change to it effective after the policy's own last-touched date).

  python3 src/build_dhs_transmittal_freshness.py           # -> _meta/dhs_transmittal_freshness.json
  python3 src/build_dhs_transmittal_freshness.py --check    # exit 1 if stale (CI)
  python3 src/build_dhs_transmittal_freshness.py --selftest # prove the bar can both pass and fail
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT, content_files, parse_frontmatter

OUT = REPO_ROOT / "_meta/dhs_transmittal_freshness.json"
AGENCY = "department-of-human-services"
TODAY = date.today()
RESOLUTION_BAR = 0.50   # issue #79's bar, leg 1: >= 50% of referenced policies resolved
STALE_BAR = 1            # issue #79's bar, leg 2: >= 1 policy surfaced as demonstrably stale


def join_counts(policy_ids: set, announcements: list[dict]) -> dict:
    """The pure join: PURE FUNCTION, no filesystem -- the seam `--selftest` exercises
    directly.

    `policy_ids`: every DHS policy id this corpus holds (the denominator the bar is
    measured against -- NOT just the ones a transmittal happens to announce, which would
    make the bar unfailable by construction).
    `announcements`: [{"transmittal_id", "policy_id", "effective_date" (ISO or None),
    "policy_last_touched" (ISO or None)}, ...] -- already-filtered to `policy_id in
    policy_ids` (a transmittal citing an id this corpus does not hold cannot resolve
    anything; that is a data problem for the ingester, not a join question).

    Returns per-policy resolution, the two bar legs as counts, and whether the pilot clears
    both (the pilot "can fail" -- this function says so when it does)."""
    resolved_for: dict[str, list[dict]] = {}
    for a in announcements:
        resolved_for.setdefault(a["policy_id"], []).append(a)

    per_policy = []
    stale_ids = []
    for pid in sorted(policy_ids):
        hits = resolved_for.get(pid, [])
        dated_hits = [h for h in hits if h.get("effective_date")]
        latest = max((h["effective_date"] for h in dated_hits), default=None)
        is_stale = False
        if latest and any(h.get("policy_last_touched") for h in dated_hits):
            is_stale = any(
                h["effective_date"] > h["policy_last_touched"]
                for h in dated_hits if h.get("policy_last_touched")
            )
        if is_stale:
            stale_ids.append(pid)
        per_policy.append({
            "policy_id": pid,
            "resolved": bool(hits),
            "transmittal_ids": sorted(h["transmittal_id"] for h in hits),
            "latest_effective_date": latest,
            "stale": is_stale,
        })

    n_total = len(policy_ids)
    n_resolved = sum(1 for p in per_policy if p["resolved"])
    resolution_rate = (n_resolved / n_total) if n_total else 0.0
    n_stale = len(stale_ids)

    bar1_pass = resolution_rate >= RESOLUTION_BAR
    bar2_pass = n_stale >= STALE_BAR
    return {
        "policies": per_policy,
        "n_policies_total": n_total,
        "n_policies_resolved": n_resolved,
        "resolution_rate": round(resolution_rate, 4),
        "resolution_bar": RESOLUTION_BAR,
        "bar1_resolution_pass": bar1_pass,
        "n_policies_stale": n_stale,
        "stale_bar": STALE_BAR,
        "bar2_stale_pass": bar2_pass,
        "pilot_passes": bar1_pass and bar2_pass,
    }


def _last_touched(fm: dict) -> str | None:
    """The LATER of effective_date and last_reviewed -- same rule as build_policy_age_data.py,
    so "stale" here means the same thing an existing reviewer-facing view already means by it."""
    vals = [fm.get("effective_date"), fm.get("last_reviewed")]
    vals = [v for v in vals if v]
    return max(vals) if vals else None


def compute() -> dict:
    policies = {}   # id -> last_touched
    announcements = []
    for p in content_files(("agencies",)):
        fm, _ = parse_frontmatter(p)
        if fm.get("agency") != AGENCY:
            continue
        if fm.get("doc_type") == "policy":
            policies[fm["id"]] = _last_touched(fm)
        elif fm.get("doc_type") == "transmittal":
            for pid in fm.get("announces") or []:
                announcements.append({
                    "transmittal_id": fm["id"],
                    "policy_id": pid,
                    "effective_date": fm.get("effective_date"),
                    "policy_last_touched": None,  # filled in below once `policies` is complete
                })
    for a in announcements:
        a["policy_last_touched"] = policies.get(a["policy_id"])
    # drop announcements aimed at an id this corpus does not (or no longer) hold -- the
    # join can only speak about policies actually present
    announcements = [a for a in announcements if a["policy_id"] in policies]

    result = join_counts(set(policies), announcements)
    result["generated"] = TODAY.isoformat()
    result["note"] = (
        "Per ADR 0001: every date here is COMPUTED by joining a transmittal's own "
        "`announces`/`effective_date` to the policy it names, every run -- nothing is ever "
        "written back into a policy's own frontmatter. Non-authoritative; verify against "
        "each document's own source_url."
    )
    return result


def outputs():
    return {OUT: json.dumps(compute(), ensure_ascii=False, indent=2, sort_keys=False) + "\n"}


def _stable(text: str) -> dict:
    d = json.loads(text)
    d.pop("generated", None)
    return d


def _selftest() -> int:
    """`join_counts` must be able to both PASS and FAIL the issue's bar -- a check that
    always answers the same way is not a check (AGENTS.md)."""
    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # Fixture A: the REAL measured shape of this pilot -- a policy set with no resolving
    # transmittal at all. Both bar legs must fail.
    r = join_counts({"dhs-010-010", "dhs-010-031-01"}, [])
    check("zero announcements -> 0% resolution, bar 1 fails",
         r["n_policies_resolved"] == 0 and r["resolution_rate"] == 0.0
         and r["bar1_resolution_pass"] is False)
    check("zero announcements -> 0 stale, bar 2 fails",
         r["n_policies_stale"] == 0 and r["bar2_stale_pass"] is False)
    check("either leg failing -> pilot_passes is False", r["pilot_passes"] is False)

    # Fixture B: a pilot that WOULD clear the bar -- 2 of 2 policies resolved (100% >= 50%),
    # one of them dated after the policy's own last-touched date (demonstrably stale).
    policy_ids = {"dhs-010-010", "dhs-010-031-01"}
    announcements = [
        {"transmittal_id": "dhs-apd-pt-26-900", "policy_id": "dhs-010-010",
         "effective_date": "2026-01-01", "policy_last_touched": "2008-06-09"},
        {"transmittal_id": "dhs-apd-pt-26-901", "policy_id": "dhs-010-031-01",
         "effective_date": "2020-01-01", "policy_last_touched": "2020-06-01"},
    ]
    r = join_counts(policy_ids, announcements)
    check("2/2 resolved -> 100% resolution, bar 1 passes",
         r["n_policies_resolved"] == 2 and r["resolution_rate"] == 1.0
         and r["bar1_resolution_pass"] is True)
    check("one announcement dated after its policy's last-touched -> that policy is stale",
         r["n_policies_stale"] == 1 and r["bar2_stale_pass"] is True)
    check("the OTHER resolved policy (announced before its own last-touched) is not stale",
         next(p for p in r["policies"] if p["policy_id"] == "dhs-010-031-01")["stale"] is False)
    check("both legs passing -> pilot_passes is True", r["pilot_passes"] is True)

    # Fixture C: an announcement pointing at a policy id NOT in the denominator (e.g. an
    # id this corpus does not hold) must be the caller's job to filter, not silently
    # counted here -- join_counts trusts its `policy_ids` as the universe.
    r = join_counts({"dhs-010-010"}, [{"transmittal_id": "t1", "policy_id": "dhs-999-999",
                                       "effective_date": "2026-01-01",
                                       "policy_last_touched": None}])
    check("an announcement for an id outside policy_ids does not inflate the denominator",
         r["n_policies_total"] == 1 and r["n_policies_resolved"] == 0)

    return 1 if fails else 0


def main():
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    outs = outputs()
    if "--check" in sys.argv:
        stale = [p for p, t in outs.items() if not p.exists() or _stable(p.read_text()) != _stable(t)]
        if stale:
            print(f"{OUT.relative_to(REPO_ROOT)} is stale — run: "
                 "python3 src/build_dhs_transmittal_freshness.py")
            sys.exit(1)
        print("dhs_transmittal_freshness.json is current.")
        return
    for p, t in outs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    d = json.loads(outs[OUT])
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {d['n_policies_resolved']}/{d['n_policies_total']} "
         f"DHS policies resolved ({d['resolution_rate']:.0%}, bar {d['resolution_bar']:.0%}: "
         f"{'PASS' if d['bar1_resolution_pass'] else 'FAIL'}); "
         f"{d['n_policies_stale']} stale (bar {d['stale_bar']}: "
         f"{'PASS' if d['bar2_stale_pass'] else 'FAIL'}); "
         f"pilot {'PASSES' if d['pilot_passes'] else 'FAILS'} the issue #79 bar.")


if __name__ == "__main__":
    main()
