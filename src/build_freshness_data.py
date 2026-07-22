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
YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")
BRACKET = re.compile(r"\[[^\]]*\]")
EFF = re.compile(r'^effective_date:\s*"?(\d{4})', re.M)


def _fingerprint() -> str:
    return hashlib.sha256(GRAPH.read_bytes()).hexdigest()[:16]


def _statute_year(sid: str):
    p = REPO_ROOT / f"statutes/{sid}.md"
    if not p.exists():
        return None
    body = p.read_text(encoding="utf-8", errors="ignore").split("## Provenance")[0]
    yrs = [int(y) for br in BRACKET.findall(body)
           if ("c." in br or "Amended" in br or "Formerly" in br)
           for y in YEAR.findall(br)]
    return max(yrs) if yrs else None


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

    # authorities: doc -> statutes it implements
    auth = defaultdict(list)
    for e in g["edges"]:
        if e["type"] == "implements" and e["to"].startswith("ors-"):
            auth[e["from"]].append(e["to"])
    cited = {s for v in auth.values() for s in v}
    syear = {s: _statute_year(s) for s in cited}

    def agency_of(doc_id):
        if doc_id.startswith("oar-"):
            org = reg.get(doc_id.split("-")[1])
            return names.get(org["slug"], org["slug"]) if org else None
        path = nodes.get(doc_id, {}).get("path", "")
        return names.get(path.split("/")[1], path.split("/")[1]) if path.startswith("agencies/") else None

    def best_authority(doc_id):
        """(statute id, year) of the most-recently-amended KNOWN authority, or (None, None)."""
        best_s, best_y = None, None
        for s in auth.get(doc_id, []):
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
