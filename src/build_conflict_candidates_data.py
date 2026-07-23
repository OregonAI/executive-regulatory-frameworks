#!/usr/bin/env python3
"""Cache the conflict-candidates dataset from _meta/catalog/conflict-candidates.yml (see
that file's note — it's an AI-assisted pilot snapshot, not mechanically derived and not
legally reviewed). The one thing this script DOES verify mechanically: every cited document
id must actually resolve in the corpus graph (or be explicitly marked not_found: true for
the one candidate whose entire point is a broken cross-reference) — a quote citing a
document that doesn't exist would be a fabrication, so this is a hard gate, not a warning.

  python3 src/build_conflict_candidates_data.py          # scan + write cache
  python3 src/build_conflict_candidates_data.py --check   # exit 1 if stale (CI)
"""
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT

CATALOG = REPO_ROOT / "_meta/catalog/conflict-candidates.yml"
GRAPH = REPO_ROOT / "_meta/graph.json"
OUT = REPO_ROOT / "_meta/conflict_candidates.json"


def compute() -> dict:
    cat = yaml.safe_load(CATALOG.read_text())
    g = json.loads(GRAPH.read_text())
    ids = {n["id"] for n in g["nodes"]}

    n_candidates = n_docs_checked = n_artifacts = 0
    for ch in cat["chapters"]:
        for cand in ch.get("candidates", []):
            n_candidates += 1
            for doc in cand["documents"]:
                n_docs_checked += 1
                exists = doc["id"] in ids
                expected = not doc.get("not_found", False)
                if exists != expected:
                    verb = "should exist but doesn't" if expected else "was marked not_found but does exist"
                    raise SystemExit(
                        f"conflict-candidates.yml: document id {doc['id']!r} "
                        f"(ORS chapter {ch['ors_chapter']}) {verb} in _meta/graph.json — "
                        "fix the citation before this cache can be trusted.")
        n_artifacts += len(ch.get("artifacts", []))

    n_clean = sum(1 for ch in cat["chapters"] if not ch.get("candidates"))
    return {
        "retrieved": cat["retrieved"],
        "note": cat["note"],
        "methodology": cat["methodology"],
        "n_chapters": len(cat["chapters"]),
        "n_clean_chapters": n_clean,
        "n_candidates": n_candidates,
        "n_artifacts": n_artifacts,
        "n_docs_verified": n_docs_checked,
        "chapters": cat["chapters"],
    }


def outputs():
    return {OUT: json.dumps(compute(), ensure_ascii=False, separators=(",", ":"))}


def main():
    outs = outputs()
    if "--check" in sys.argv:
        stale = [p for p, t in outs.items() if not p.exists() or p.read_text() != t]
        if stale:
            print(f"{OUT.relative_to(REPO_ROOT)} is stale — run: "
                  "python3 src/build_conflict_candidates_data.py")
            sys.exit(1)
        print("conflict_candidates.json is current.")
        return
    for p, t in outs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    d = json.loads(outs[OUT])
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {d['n_chapters']} chapters piloted, "
          f"{d['n_candidates']} candidates, {d['n_docs_verified']} citations verified "
          f"against the corpus graph")


if __name__ == "__main__":
    main()
