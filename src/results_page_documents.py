#!/usr/bin/env python3
"""A document mirroring an OARD search-results list is recorded as one, never passed off
as the rule.

  python3 src/results_page_documents.py --check      every rule document
  python3 src/results_page_documents.py --selftest   every rule, watched failing

WHY THIS EXISTS (#251). OARD serves a RESULTS LIST, not a rule, when a number is
ambiguous -- two rules share 836-054-0020 in the same chapter. The page still carries the
number, still slices to something over the length floor, and still hashes, so every guard
the ingest had passed it. What got published was the titles of the rules that matched plus
the site footer -- a fax number, a copyright line -- under a document claiming to mirror
one rule. 39 documents corpus-wide.

`ingest_oar` and `reingest_oar` now refuse to publish or refresh from such a page. This
gate is about the ones ALREADY PUBLISHED, and it is deliberately not satisfiable by
deleting them: ADR 0006 is explicit that deleting a document breaks every citation
pointing at it. The rule is that the catalog SAYS SO -- so a new one arriving unrecorded
fails, and the known 39 stay readable and honestly labelled.
"""
import argparse
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# SEARCH_RESULTS_MARK: THE ONE DECLARATION (#334 code review) lives in ingest_oar.py, the
# writer -- imported here rather than retyped, same discipline as is_search_results_page
# below and catalog_oar.py's own marks (CLAIMED_ELSEWHERE_DIVISION_MARK etc., imported by
# review_queue.py the same way).
from ingest_oar import SEARCH_RESULTS_MARK, is_search_results_page  # noqa: E402
from repo_lib import REPO_ROOT, ws_only  # noqa: E402

CATALOG = REPO_ROOT / "_meta/catalog/oar.yml"
MARK = SEARCH_RESULTS_MARK


def catalog_notes() -> dict:
    d = yaml.safe_load(CATALOG.read_text())
    return {r["number"]: (r.get("note") or "")
            for ch in d["chapters"] for dv in ch["divisions"] for r in (dv.get("rules") or [])}


def survey(root: Path = None, notes: dict = None):
    """(unrecorded, recorded, checked) over every committed rule document."""
    notes = catalog_notes() if notes is None else notes
    root = (REPO_ROOT / "rules") if root is None else root
    unrecorded, recorded, checked = [], 0, 0
    for p in sorted(root.rglob("oar-*.md")):
        checked += 1
        if not is_search_results_page(ws_only(p.read_text(encoding="utf-8", errors="replace"))):
            continue
        number = p.stem.replace("oar-", "")
        if MARK in notes.get(number, ""):
            recorded += 1
        else:
            unrecorded.append(number)
    return unrecorded, recorded, checked


def cmd_check() -> int:
    unrecorded, recorded, checked = survey()
    if unrecorded:
        for n in unrecorded[:20]:
            print(f"  FAIL [a-results-page-document-is-recorded-as-one] {n}: this document's "
                  f"full text is an OARD search-results list, not the rule, and the catalog "
                  f"does not say so. A reader gets the titles of the rules that matched and "
                  f"the site footer, presented as Oregon law — record it (#251); do not "
                  f"delete it (ADR 0006)")
        if len(unrecorded) > 20:
            print(f"  … and {len(unrecorded) - 20} more")
        print(f"\n{len(unrecorded)} unrecorded results-page document(s), of {checked} checked.")
        return 1
    print(f"results-page documents: {checked} rule document(s) checked; {recorded} mirror an "
          f"OARD search-results list and every one is recorded as such in the catalog.")
    return 0


def cmd_selftest() -> int:
    import tempfile
    fails = []
    body = ("(1) A rule body long enough to be sliced and hashed like any other, with "
            "enough prose to clear every length floor this pipeline applies. " * 3)
    page = "836-054-0020 returned 2 results. New Search | Modify Search Rows per page: 25"

    def run(text, notes):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "oar-836-054-0020.md").write_text(text, encoding="utf-8")
            return survey(Path(d), notes)

    # THE CASE #251 FOUND, watched failing: a results page published with nothing saying so.
    bad, _, checked = run(page + body, {})
    if bad != ["836-054-0020"]:
        fails.append(f"FAIL an-unrecorded-results-page-document-is-caught: got {bad}")
    if checked != 1:
        fails.append(f"FAIL the-case-is-actually-checked: checked {checked}, not 1")

    # ...AND RECORDING IT IS WHAT CLEARS IT -- not deleting it (ADR 0006).
    bad, rec, _ = run(page + body, {"836-054-0020": f"OARD serves a {MARK} for this number"})
    if bad or rec != 1:
        fails.append(f"FAIL recording-it-clears-the-finding: bad={bad} recorded={rec}")

    # THE GUARD THAT MUST NOT FIRE: an ordinary rule is not a results page, recorded or not.
    bad, rec, _ = run(body, {})
    if bad or rec:
        fails.append(f"FAIL an-ordinary-rule-is-not-a-finding: bad={bad} recorded={rec}")

    # AND A NOTE ALONE CANNOT CREATE ONE -- otherwise the count could be inflated by prose.
    bad, rec, _ = run(body, {"836-054-0020": f"OARD serves a {MARK} for this number"})
    if bad or rec:
        fails.append(f"FAIL a-note-on-an-ordinary-rule-does-not-make-it-one: recorded={rec}")

    for f in fails:
        print(f)
    if fails:
        print(f"{len(fails)} rule(s) did not hold")
        return 1
    print("1 violation demonstrated failing; 3 guard(s) that must not fire held")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    return cmd_selftest() if a.selftest else cmd_check()


if __name__ == "__main__":
    sys.exit(main())
