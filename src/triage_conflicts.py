#!/usr/bin/env python3
"""Interactive triage of conflict candidates: a human verdict, recorded where the
schema always meant it to live.

  python3 src/triage_conflicts.py                 # review unreviewed, best-first
  python3 src/triage_conflicts.py --limit 30
  python3 src/triage_conflicts.py --report        # counts by triage status
  python3 src/triage_conflicts.py --selftest      # CI: the write path loses nothing

WHY THIS EXISTS. All 1,398 candidates carry triage.status: unreviewed. The schema was
built for verdicts ("triage is what makes re-analysis safe: a dismissed finding stays
dismissed") and never exercised — and the publish rule for anything conflict-shaped is
that unreviewed model output is never presented as findings. This is the gate.

ORDERING. Candidates whose cited documents also appear in Audits Division report
citations come FIRST (the issue-#82 overlap — the ones with external corroboration
waiting), then by the model's own severity x confidence, then the rest. Ordering is
advisory; every candidate remains reachable.

WRITE PATH. Verdicts are saved after EVERY keypress (crash-safe). The catalog is
machine-generated YAML; the first save may renormalize formatting once — --selftest
asserts the round-trip preserves every candidate and every field, which is the
guarantee that matters (the #66/#68 lesson class: a merge that drops candidates).
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
import textwrap
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG = REPO_ROOT / "_meta/catalog/conflict-candidates.yml"
DERIVED = REPO_ROOT / "_meta/conflict_candidates.json"


def weak_quote_fingerprints() -> tuple[set, set]:
    """(absence-claim, ungrounded) candidate fingerprints from the derived JSON.

    These are the two classes machine verification cannot bless — an omission has
    nothing to string-match, and an ungrounded quote failed the match — so they go to
    the FRONT of the human queue (right after the audit-corroborated set): the places a
    confident fabrication could survive are the places a human should look first."""
    import json
    if not DERIVED.is_file():
        return set(), set()
    absence, ungrounded = set(), set()
    for ch in json.loads(DERIVED.read_text()).get("chapters", []):
        for c in ch.get("candidates", []):
            states = {d.get("quote_verified") for d in c.get("documents", [])}
            if "absence" in states:
                absence.add(c.get("fingerprint"))
            if False in states:
                ungrounded.add(c.get("fingerprint"))
    return absence, ungrounded
_AUDITS_CANDIDATES = (REPO_ROOT.parent / "oregon-audits" / "_meta" / "graph.json",
                      Path.home() / "oregon-audits" / "_meta" / "graph.json")
AUDITS_GRAPH = next((p for p in _AUDITS_CANDIDATES if p.is_file()),
                    _AUDITS_CANDIDATES[0])
REVIEWER = "@morficflux"

_RANK = {"high": 2, "medium": 1, "low": 0, None: -1}


def doc_url(doc_id: str) -> str:
    base = "https://github.com/OregonAI/executive-regulatory-frameworks/blob/main"
    if doc_id.startswith("ors-"):
        return f"{base}/statutes/{doc_id}.md"
    m = re.match(r"oar-(\d+)-(\d+)-", doc_id)
    if m:
        return f"{base}/rules/{m.group(1)}/{m.group(2)}/{doc_id}.md"
    return f"https://github.com/OregonAI/executive-regulatory-frameworks/search?q={doc_id}"


def audit_cited_ids() -> set[str]:
    """ERF doc ids the audit corpus cites — read from a sibling checkout when present.
    Absence just means the overlap ordering is skipped, and says so."""
    if not AUDITS_GRAPH.is_file():
        return set()
    import json
    out = set()
    for e in json.loads(AUDITS_GRAPH.read_text()).get("edges", []):
        m = re.match(r"^ORS\s+(\d+[A-Z]?)\.(\d+[a-z]?)$", e.get("to", ""))
        if m:
            out.add(f"ors-{m.group(1).lower()}.{m.group(2)}")
        m = re.match(r"^OAR\s+(\d+)-(\d+)-(\d+)$", e.get("to", ""))
        if m:
            out.add(f"oar-{m.group(1)}-{m.group(2)}-{m.group(3)}")
    return out


def load():
    return yaml.safe_load(CATALOG.read_text(encoding="utf-8"))


def save(cat) -> None:
    CATALOG.write_text(
        yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8")


def walk(cat):
    for ch in cat.get("chapters", []):
        for cand in ch.get("candidates", []) or []:
            yield ch, cand


def selftest() -> int:
    """The write path must lose nothing: same candidates, same fields, byte-stable on
    a second pass."""
    cat = load()
    before = [(ch["ors_chapter"], c["summary"], sorted(c)) for ch, c in walk(cat)]
    once = yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100)
    reloaded = yaml.safe_load(once)
    after = [(ch["ors_chapter"], c["summary"], sorted(c)) for ch, c in walk(reloaded)]
    if before != after:
        print("FAIL: round-trip altered candidates", file=sys.stderr)
        return 1
    twice = yaml.safe_dump(reloaded, sort_keys=False, allow_unicode=True, width=100)
    if once != twice:
        print("FAIL: dump is not stable across passes", file=sys.stderr)
        return 1
    bad = [c["summary"][:60] for _, c in walk(cat)
           if (c.get("triage") or {}).get("status")
           not in ("unreviewed", "confirmed", "dismissed")]
    if bad:
        print(f"FAIL: {len(bad)} candidate(s) with an illegal triage status: {bad[:3]}",
              file=sys.stderr)
        return 1
    print(f"round-trip preserves all {len(before)} candidates; statuses legal.")
    return 0


def report(cat) -> int:
    from collections import Counter
    c = Counter((cand.get("triage") or {}).get("status", "unreviewed")
                for _, cand in walk(cat))
    for k, v in c.most_common():
        print(f"  {k}: {v}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--export-eval", action="store_true",
                    help="write confirmed/dismissed verdicts to _meta/eval/"
                         "triage-verdicts.yml — human ground truth that grows from "
                         "review sessions (confirmed = positives, dismissed = hard "
                         "negatives for future model evals)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.export_eval:
        cat = load()
        out = REPO_ROOT / "_meta/eval/triage-verdicts.yml"
        verdicts = [{"fingerprint": c.get("fingerprint"),
                     "chapter": ch["ors_chapter"], "summary": c["summary"],
                     **{k: v for k, v in (c.get("triage") or {}).items()}}
                    for ch, c in walk(cat)
                    if (c.get("triage") or {}).get("status") in ("confirmed", "dismissed")]
        out.parent.mkdir(exist_ok=True)
        out.write_text(yaml.safe_dump(
            {"note": "GENERATED by triage_conflicts.py --export-eval. Human verdicts as "
                     "eval material: confirmed = positives a model should find, "
                     "dismissed = hard negatives it should not. Grows with every review "
                     "session; eval_conflicts can score against it as a second, "
                     "human-authored ground-truth arm.",
             "n": len(verdicts), "verdicts": verdicts},
            sort_keys=False, allow_unicode=True, width=100))
        print(f"wrote {out.relative_to(REPO_ROOT)}: {len(verdicts)} verdict(s)")
        return 0
    cat = load()
    if args.report:
        return report(cat)

    audited = audit_cited_ids()
    if not audited:
        print("(no oregon-audits checkout beside this repo — audit-overlap ordering "
              "skipped; severity ordering only)\n")

    queue = [(ch, c) for ch, c in walk(cat)
             if (c.get("triage") or {}).get("status", "unreviewed") == "unreviewed"]
    absence, ungrounded = weak_quote_fingerprints()
    def fp(cand):
        return cand.get("fingerprint")
    queue.sort(key=lambda t: (
        -int(any(d["id"] in audited for d in t[1].get("documents", []))),
        -int(fp(t[1]) in absence or fp(t[1]) in ungrounded),
        -_RANK.get(t[1].get("severity")), -_RANK.get(t[1].get("confidence"))))
    if args.limit:
        queue = queue[:args.limit]

    print(f"{len(queue)} unreviewed candidate(s) queued. "
          f"[c]onfirm  [d]ismiss  [s]kip  [q]uit\n")
    done = 0
    for ch, cand in queue:
        overlap = any(d["id"] in audited for d in cand.get("documents", []))
        print("=" * 78)
        print(f"ORS chapter {ch['ors_chapter']}"
              + ("   ** cited by Audits Division reports **" if overlap else ""))
        print(f"severity: {cand.get('severity')}  confidence: {cand.get('confidence')}  "
              f"run: {cand.get('run_id')}")
        print(textwrap.fill(cand["summary"], 78), "\n")
        for d in cand.get("documents", []):
            print(f"  {d['citation']}  ({d['id']})")
            print(f"    {doc_url(d['id'])}")
            if d.get("quote"):
                print(textwrap.indent(textwrap.fill(f"“{d['quote']}”", 74), "    "))
        if cand.get("note"):
            print("\n  note:", textwrap.fill(str(cand["note"]), 74))
        try:
            key = input("\n[c/d/s/q] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            key = "q"
        if key == "q":
            break
        if key in ("c", "d"):
            note = input("optional note > ").strip()
            cand["triage"] = {
                "status": "confirmed" if key == "c" else "dismissed",
                "reviewed_by": REVIEWER,
                "reviewed_on": datetime.date.today().isoformat(),
                **({"note": note} if note else {})}
            save(cat)        # after every verdict: a crash loses nothing
            done += 1
        print()
    print(f"\n{done} verdict(s) recorded.")
    if done:
        print("Follow up: python3 src/build_conflict_candidates.py && "
              "python3 src/build_site.py   # the viz and site must reflect the verdicts")
        report(cat)
    return 0


if __name__ == "__main__":
    sys.exit(main())
