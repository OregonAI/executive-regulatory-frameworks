#!/usr/bin/env python3
"""The conflict-scan coverage ledger: what has been screened, at what depth, by what —
and what the next run should read first.

  python3 src/build_conflict_coverage.py            # write _meta/catalog/conflict-coverage.yml
  python3 src/build_conflict_coverage.py --check    # CI: fail if stale

WHY. "172 of 245 chapters" mixed three depths of screening — whole-chapter frontier
reads, partial section-scoped sweeps, and re-runs superseding re-runs — so 'screened'
meant different things per chapter and nobody could say precisely what was left. This
ledger makes coverage a per-chapter fact with a stated depth, and orders the unscreened
frontier by expected value (agencies sharing the chapter x implementing rules x whether
the Audits Division cites it), so the next paid run starts where the value is instead
of where the token budget pointed (the batch-3 smallest-chapters bias, retired).

Derives everything from committed artifacts: the candidates catalog (run ids, models,
sections_reviewed), the authority graph (the shared-authority set and each chapter's
section/rule counts, via analyze_conflicts' own functions), and — when a sibling
oregon-audits checkout is present — its citation edges for the audit-overlap flag.
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_conflicts as AC  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG = REPO_ROOT / "_meta/catalog/conflict-candidates.yml"
OUT = REPO_ROOT / "_meta/catalog/conflict-coverage.yml"
# Sibling probe, the toolkit REGISTRY_CANDIDATES pattern: the repo may be checked out
# beside this one or beside the canonical home layout (worktrees break .parent).
AUDITS_GRAPH_CANDIDATES = (
    REPO_ROOT.parent / "oregon-audits" / "_meta" / "graph.json",
    Path.home() / "oregon-audits" / "_meta" / "graph.json",
)
AUDITS_GRAPH = next((p for p in AUDITS_GRAPH_CANDIDATES if p.is_file()),
                    AUDITS_GRAPH_CANDIDATES[0])

# Runs whose unit was the WHOLE chapter (statute + every implementing rule in one pass).
CHAPTER_SCOPED_RUNS = ("pilot-2026-07", "batch1", "batch3")


def audit_cited_chapters() -> set[str]:
    if not AUDITS_GRAPH.is_file():
        return set()
    out = set()
    for e in json.loads(AUDITS_GRAPH.read_text()).get("edges", []):
        m = re.match(r"^ORS\s+(\d+[A-Z]?)\.", e.get("to", ""))
        if m:
            out.add(m.group(1).lower())
    return out


def build() -> dict:
    graph = json.loads(AC.GRAPH.read_text())
    shared = AC.shared_authority_chapters(graph)
    cat = yaml.safe_load(CATALOG.read_text())

    # sections with at least one implementing rule, per chapter — the unit universe
    # the section-scoped runs draw from.
    sections_of = collections.defaultdict(set)
    rules_of = collections.defaultdict(set)
    for e in graph["edges"]:
        if (e["type"] == "implemented_by" and e["from"].startswith("ors-")
                and e["to"].startswith("oar-")):
            ch = e["from"].split("-", 1)[1].split(".", 1)[0]
            sections_of[ch].add(e["from"])
            rules_of[ch].add(e["to"])

    scanned: dict[str, dict] = {}
    for ch in cat.get("chapters", []):
        c = str(ch["ors_chapter"]).lower()
        runs = sorted({ch.get("run_id") or ""}
                      | {cand.get("run_id") or "" for cand in ch.get("candidates") or []})
        runs = [r for r in runs if r]
        reviewed = ch.get("sections_reviewed") or []
        chapter_scoped = any(any(r.startswith(p) or p in r for p in CHAPTER_SCOPED_RUNS)
                             for r in runs) or not reviewed
        scanned[c] = {"runs": runs, "chapter_scoped": chapter_scoped,
                      "sections_reviewed": sorted(str(s).lower() for s in reviewed)}

    audit_chs = audit_cited_chapters()
    inherited = False
    if not audit_chs and OUT.is_file():
        # CI runners have no sibling checkout; regenerating there with all-false flags
        # would diff against the committed truth and cry stale. Inherit the committed
        # flags instead — a machine WITH the sibling refreshes them for real.
        prev = yaml.safe_load(OUT.read_text()) or {}
        audit_chs = {r["chapter"] for r in prev.get("chapters", []) if r.get("audit_cited")}
        inherited = bool(audit_chs)
    rows = []
    for ch, agencies in sorted(shared.items()):
        n_sections = len(sections_of.get(ch, ()))
        s = scanned.get(ch)
        if s and s["chapter_scoped"]:
            depth, done = "chapter", n_sections
        elif s:
            done = len(set(s["sections_reviewed"]) & sections_of.get(ch, set()))
            depth = "sections-partial"
        else:
            depth, done = "unscreened", 0
        rows.append({
            "chapter": ch,
            "depth": depth,
            "sections_with_rules": n_sections,
            "sections_screened": done,
            "n_agencies": len(agencies),
            "n_rules": len(rules_of.get(ch, ())),
            "audit_cited": ch in audit_chs,
            "runs": (s or {}).get("runs", []),
            # Expected-value ordering for the NEXT run: agencies sharing the chapter,
            # its rule mass, audit corroboration waiting, and how much is unscreened.
            "priority": round(
                len(agencies) * (len(rules_of.get(ch, ())) ** 0.5)
                * (2.0 if ch in audit_chs else 1.0)
                * ((n_sections - done) / n_sections if n_sections else 0), 1),
        })
    rows.sort(key=lambda r: -r["priority"])

    counts = collections.Counter(r["depth"] for r in rows)
    return {
        "note": "GENERATED by src/build_conflict_coverage.py — do not hand-edit. One row "
                "per shared-authority chapter, with the DEPTH screening actually reached: "
                "'chapter' (a frontier model read the whole chapter's statute + rules), "
                "'sections-partial' (only the listed sections, with only their citing "
                "rules), or 'unscreened'. 'priority' orders the frontier for the next "
                "run by expected value, replacing the batch-3 smallest-first cost bias. "
                "audit_cited comes from a sibling oregon-audits checkout"
                + (" (INHERITED from the committed ledger — no sibling checkout at "
                   "generation)" if inherited else
                   "" if audit_chs else " (ABSENT at generation — flags all false, which "
                   "understates priority; regenerate with the sibling present)") + ".",
        "summary": {"shared_authority_chapters": len(rows), **counts,
                    "sections_screened_total": sum(r["sections_screened"] for r in rows),
                    "sections_with_rules_total": sum(r["sections_with_rules"] for r in rows)},
        "chapters": rows,
    }


def main() -> int:
    data = build()
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
    if "--check" in sys.argv:
        if not OUT.is_file() or OUT.read_text() != text:
            print(f"{OUT.relative_to(REPO_ROOT)} is stale — run: "
                  f"python3 src/build_conflict_coverage.py", file=sys.stderr)
            return 1
        print("conflict-coverage.yml is current.")
        return 0
    OUT.write_text(text)
    s = data["summary"]
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {s['shared_authority_chapters']} "
          f"shared-authority chapters — {s.get('chapter', 0)} chapter-scoped, "
          f"{s.get('sections-partial', 0)} partial, {s.get('unscreened', 0)} unscreened; "
          f"{s['sections_screened_total']:,}/{s['sections_with_rules_total']:,} "
          f"sections screened")
    return 0


if __name__ == "__main__":
    sys.exit(main())
