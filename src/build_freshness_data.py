#!/usr/bin/env python3
"""Cache the 'regulatory freshness' dataset — the functional age of every rule and policy,
and how far each lags the most-recent amendment of the statute it implements.

Heavy step (parses ~8k statute bodies + ~33k rule/policy frontmatters), so it runs once and
writes _meta/freshness.json, fingerprinted on the authority graph; build_freshness.py (the
HTML generator) just reads the cache, so its --check runs cheaply in CI.

  python3 src/build_freshness_data.py          # parse + write cache
  python3 src/build_freshness_data.py --check   # exit 1 if missing/stale vs graph.json

Method + honesty:
- rule / policy year   = the year of its `effective_date` frontmatter (its last recorded
  filing). ~98% of rules, ~90% of policies have one.
- statute year         = the MAX 4-digit year across the `[YYYY c.N …]` legislative-history
  brackets in the statute text (its last amendment). ~94% of cited statutes yield one; the
  rest are an explicit UNKNOWN bucket, never treated as fresh or stale.
- a rule implements a RANGE of statutes; we take the most-recently-amended one among its
  authorities, so the lag flags a rule "worth reviewing", NOT "definitively stale" — one
  changed section flags the rule even if it is not the relevant part.
"""
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from enrich_oar import load_registry_by_chapter
from repo_lib import REPO_ROOT

GRAPH = REPO_ROOT / "_meta/graph.json"
OUT = REPO_ROOT / "_meta/freshness.json"
EFF = re.compile(r'^effective_date:\s*"?(\d{4})', re.M)
LAST_AMENDED = re.compile(r"^last_amended:\s*(\d{4})", re.M)
# a statute cited by more than this many rules is a broad "enabling" statute (e.g. ORS
# 496.146 "additional powers of the commission"); one amendment to it isn't evidence any
# particular rule is stale, so it doesn't count as a rule's governing authority for flagging.
UBIQUITY_MAX = 75


def _fingerprint() -> str:
    return hashlib.sha256(GRAPH.read_bytes()).hexdigest()[:16]


def _statute_year(sid: str):
    """Last-amendment year from the statute's first-class `last_amended` frontmatter field
    (written by enrich_statutes.py from the section's own history notes)."""
    p = REPO_ROOT / f"statutes/{sid}.md"
    if not p.exists():
        return None
    parts = p.read_text(encoding="utf-8", errors="ignore").split("---")
    if len(parts) < 2:
        return None
    m = LAST_AMENDED.search(parts[1])
    return int(m.group(1)) if m else None


def _eff_year(path: str):
    txt = (REPO_ROOT / path).read_text(encoding="utf-8", errors="ignore")
    parts = txt.split("---")
    if len(parts) < 2:
        return None
    m = EFF.search(parts[1])
    return int(m.group(1)) if m else None


def compute() -> dict:
    g = json.loads(GRAPH.read_text())
    nodes = {n["id"]: n for n in g["nodes"]}
    reg = load_registry_by_chapter()
    names = {o["slug"]: o.get("name", o["slug"]) for o in
             yaml.safe_load((REPO_ROOT / "_meta/catalog/agencies.yml").read_text())["organizations"]}

    # authorities: doc -> statutes it implements; fan_in: how many rules cite each statute
    auth = defaultdict(list)
    fan_in = defaultdict(int)
    for e in g["edges"]:
        if e["type"] == "implements" and e["to"].startswith("ors-"):
            auth[e["from"]].append(e["to"])
            if e["from"].startswith("oar-"):
                fan_in[e["to"]] += 1
    cited = {s for v in auth.values() for s in v}
    syear = {s: _statute_year(s) for s in cited}
    # a statute counts as a "specific" (flag-worthy) authority only if it isn't ubiquitous
    specific = {s for s in cited if fan_in[s] <= UBIQUITY_MAX}

    def agency_of(doc_id):
        if doc_id.startswith("oar-"):
            org = reg.get(doc_id.split("-")[1])
            return names.get(org["slug"], org["slug"]) if org else None
        path = nodes.get(doc_id, {}).get("path", "")
        return names.get(path.split("/")[1], path.split("/")[1]) if path.startswith("agencies/") else None

    def best_authority(doc_id):
        """(statute id, year) of the most-recently-amended KNOWN, SPECIFIC (non-ubiquitous)
        authority, or (None, None) — so a rule isn't flagged merely because a broad enabling
        statute it cites was amended."""
        best_s, best_y = None, None
        for s in auth.get(doc_id, []):
            if s not in specific:
                continue
            y = syear.get(s)
            if y is not None and (best_y is None or y > best_y):
                best_s, best_y = s, y
        return best_s, best_y

    rules, policies = [], []
    for doc_id, node in nodes.items():
        dt = node["doc_type"]
        if dt not in ("rule", "policy", "procedure", "manual"):
            continue
        ag = agency_of(doc_id)
        yr = _eff_year(node["path"]) if node.get("path") else None
        sid, ay = best_authority(doc_id)
        # title is joined from the graph by the viz generator (only for flagged offenders),
        # keeping this cache lean
        rec = {"id": doc_id, "ag": ag, "yr": yr, "ay": ay, "sid": sid,
               "na": len(auth.get(doc_id, []))}
        (rules if dt == "rule" else policies).append(rec)

    return {"fingerprint": _fingerprint(),
            "rules": rules, "policies": policies,
            "note": "Functional age of Oregon rules/policies vs the last amendment of the "
                    "statute they implement. Flags are 'worth reviewing', not definitive; "
                    "non-authoritative — verify against each source."}


def main():
    if "--check" in sys.argv:
        if not OUT.exists():
            print("freshness.json missing — run: python3 src/build_freshness_data.py")
            sys.exit(1)
        if json.loads(OUT.read_text()).get("fingerprint") != _fingerprint():
            print("freshness.json is stale (graph changed) — rebuild it")
            sys.exit(1)
        print("freshness.json is current.")
        return
    data = compute()
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    nr = sum(1 for r in data["rules"] if r["yr"] and r["ay"])
    lag = sum(1 for r in data["rules"] if r["yr"] and r["ay"] and r["ay"] - r["yr"] >= 10)
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {len(data['rules']):,} rules "
          f"({nr:,} datable vs authority), {len(data['policies']):,} policies; "
          f"{lag:,} rules 10+ yrs behind their statute")


if __name__ == "__main__":
    main()
