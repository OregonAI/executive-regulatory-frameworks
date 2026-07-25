#!/usr/bin/env python3
"""Cache the conflict-candidates dataset from _meta/catalog/conflict-candidates.yml (see
that file's note — it's an AI-assisted pilot snapshot, not mechanically derived and not
legally reviewed).

Two mechanical verifications run here, both aimed at the same thing: an LLM-authored
claim about a document must be checkable against the corpus, not taken on faith.

1. CITATION EXISTENCE (hard gate). Every cited document id must resolve in the corpus
   graph, or be explicitly marked not_found: true. Citing a document that doesn't exist
   would be a fabrication, so this exits non-zero.

2. QUOTE GROUNDING (reported, not fatal by default; --strict-quotes to enforce). Each
   document's `quote` is checked against that document's own '## Full text'. This catches
   the failure the citation gate cannot: a real document cited with words it does not
   contain.

   Why this is reported rather than fatal: the pilot overloaded `quote` to hold two
   different kinds of claim — verbatim source text AND deliberate observations of ABSENCE
   ("(no operative text)", "no end date", "implemented_by: oar-… — omits oar-…"). The
   latter are legitimate analytical findings that by definition cannot appear in the
   source, so failing on them would be wrong. `quote_verified` is emitted per document
   so the viz can show which claims are machine-grounded; splitting the field by kind is
   tracked as follow-up work.

   Matching folds quote marks, dashes, editorial [brackets], case, and whitespace before
   comparing, and treats '...' as elision (segments must appear IN ORDER). That folding
   is not cosmetic: without it 43 of 268 pilot quotes read as ungrounded purely because
   the source writes “curly doubles” where the catalog transcribed 'straight singles'.

  python3 src/build_conflict_candidates_data.py                  # scan + write cache
  python3 src/build_conflict_candidates_data.py --check          # exit 1 if stale (CI)
  python3 src/build_conflict_candidates_data.py --report-quotes  # list ungrounded quotes
  python3 src/build_conflict_candidates_data.py --strict-quotes  # exit 1 on any ungrounded
"""
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT, extract_fulltext, parse_frontmatter
from enrich_oar import load_registry_by_chapter

CATALOG = REPO_ROOT / "_meta/catalog/conflict-candidates.yml"
GRAPH = REPO_ROOT / "_meta/graph.json"
OUT = REPO_ROOT / "_meta/conflict_candidates.json"

# Fold every quote-mark and dash variant to nothing / '-' before comparing. Oregon's
# published text uses typographic quotes and en/em dashes; the catalog transcribed many
# of them as ASCII. Comparing raw would report faithful quotes as ungrounded.
_QUOTE_CHARS = dict.fromkeys(map(ord, "\"'‘’“”«»"), None)
_DASH_CHARS = {ord(c): "-" for c in "‐‑‒–—―−"}


def fold(s: str) -> str:
    """Normalize for quote comparison: drop quote marks, unify dashes, collapse
    whitespace, lowercase."""
    return re.sub(r"\s+", " ", s.translate(_QUOTE_CHARS).translate(_DASH_CHARS)).strip().lower()


# Elision boundaries. '...' is ordinary elision; '[...]' is the legal-quoting convention
# for an editorial insertion OR substitution — "[and] one-half cent" where the source
# reads "of one-half cent". Because a bracket may *replace* source words rather than add
# to them, bracketed spans are treated as wildcards, not as literal text.
_ELISION_RE = re.compile(r"\.\.\.|\[[^\]]*\]")

# Below this, a fragment is too generic to count as evidence ("the state agency" occurs
# in thousands of documents). Used only to reject a quote whose ENTIRE content folds away
# to such fragments — it never rejects a long quote for having a short tail.
_MIN_EVIDENCE_CHARS = 24


def quote_is_grounded(quote: str, full_text: str) -> bool:
    """True if every segment of `quote` appears in `full_text` IN ORDER, where segments
    are split on '...' and on bracketed editorial spans.

    Order matters: it stops a quote being 'verified' by words scattered across unrelated
    subsections. The evidence-length floor stops the opposite failure — a quote that is
    almost entirely brackets/elision would otherwise have nothing left to check and match
    vacuously."""
    segments = [s for s in (fold(p) for p in _ELISION_RE.split(quote)) if s]
    if sum(len(s) for s in segments) < _MIN_EVIDENCE_CHARS:
        return False
    pos = 0
    for seg in segments:
        i = full_text.find(seg, pos)
        if i == -1:
            return False
        pos = i + len(seg)
    return True


# An absence-claim asserts the source does NOT say something, so it can never match the
# source. Shape-detected so it can be excluded from the ungrounded count rather than
# silently inflating it.
_ABSENCE_RE = re.compile(
    r"^\(|"                                   # "(full text has no operative subsections)"
    r"^no\s|^none\b|"                         # "no end date", "no flexibility clause"
    r"^(statutes_implemented|relationships|implemented_by|history)\s*:",  # frontmatter ref
    re.I)


def looks_like_absence_claim(quote: str) -> bool:
    return bool(_ABSENCE_RE.search(quote.strip()))


def _chapter_agencies(ors_chapter: str, graph: dict, registry_by_chapter: dict) -> list:
    """Every agency (slug+name) with an OAR rule implementing this ORS chapter, derived
    the same way the catalog's per-chapter agency COUNT was originally computed: walk
    implemented_by edges from every ors-<chapter>.* statute to oar-* rules, then map each
    rule's own OAR chapter number to its issuing agency via agencies.yml."""
    prefix = f"ors-{ors_chapter.lower()}."
    slugs = {}
    for e in graph["edges"]:
        if e["type"] != "implemented_by" or not e["from"].startswith(prefix) or not e["to"].startswith("oar-"):
            continue
        rule_chapter = e["to"].split("-")[1]
        org = registry_by_chapter.get(rule_chapter)
        if org:
            slugs[org["slug"]] = org["name"]
    return sorted([{"slug": s, "name": n} for s, n in slugs.items()], key=lambda o: o["name"])


def _full_text_index(graph: dict) -> dict:
    """id -> folded '## Full text' of that document (built lazily by the caller)."""
    return {n["id"]: n["path"] for n in graph["nodes"]}


def compute(collect_ungrounded: list | None = None) -> dict:
    cat = yaml.safe_load(CATALOG.read_text())
    g = json.loads(GRAPH.read_text())
    ids = {n["id"] for n in g["nodes"]}
    paths = _full_text_index(g)
    registry_by_chapter = load_registry_by_chapter()

    ft_cache: dict[str, str] = {}

    def full_text(doc_id: str) -> str:
        if doc_id not in ft_cache:
            _, body = parse_frontmatter(REPO_ROOT / paths[doc_id])
            ft = extract_fulltext(body)
            ft_cache[doc_id] = fold(ft) if ft else ""
        return ft_cache[doc_id]

    n_candidates = n_docs_checked = n_artifacts = 0
    n_grounded = n_absence = n_ungrounded = 0
    all_agencies = {}
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

                # Quote grounding. Only meaningful for documents that exist and carry a
                # verbatim '## Full text' to check against.
                if not exists or not doc.get("quote"):
                    doc["quote_verified"] = None
                    continue
                ft = full_text(doc["id"])
                if not ft:
                    doc["quote_verified"] = None      # summary-only doc: nothing to diff
                elif quote_is_grounded(doc["quote"], ft):
                    doc["quote_verified"] = True
                    n_grounded += 1
                elif looks_like_absence_claim(doc["quote"]):
                    doc["quote_verified"] = "absence"  # asserts the source omits something
                    n_absence += 1
                else:
                    doc["quote_verified"] = False
                    n_ungrounded += 1
                    if collect_ungrounded is not None:
                        collect_ungrounded.append((ch["ors_chapter"], doc["id"], doc["quote"]))
        n_artifacts += len(ch.get("artifacts", []))

        agencies = _chapter_agencies(ch["ors_chapter"], g, registry_by_chapter)
        ch["agency_list"] = agencies
        for a in agencies:
            all_agencies[a["slug"]] = all_agencies.get(a["slug"], 0) + 1

    n_clean = sum(1 for ch in cat["chapters"] if not ch.get("candidates"))
    agency_names = {a["slug"]: a["name"] for ch in cat["chapters"] for a in ch["agency_list"]}
    return {
        "retrieved": cat["retrieved"],
        "note": cat["note"],
        "methodology": cat["methodology"],
        "n_chapters": len(cat["chapters"]),
        "n_clean_chapters": n_clean,
        "n_candidates": n_candidates,
        "n_artifacts": n_artifacts,
        "n_docs_verified": n_docs_checked,
        "n_quotes_grounded": n_grounded,
        "n_quotes_absence_claim": n_absence,
        "n_quotes_ungrounded": n_ungrounded,
        "all_agencies": sorted(
            [{"slug": s, "name": agency_names[s], "chapters": n} for s, n in all_agencies.items()],
            key=lambda a: a["name"]),
        "chapters": cat["chapters"],
    }


def outputs(collect=None):
    return {OUT: json.dumps(compute(collect), ensure_ascii=False, separators=(",", ":"))}


def _quote_summary(d: dict) -> str:
    checked = d["n_quotes_grounded"] + d["n_quotes_absence_claim"] + d["n_quotes_ungrounded"]
    return (f"quotes: {d['n_quotes_grounded']}/{checked} grounded in source full text, "
            f"{d['n_quotes_absence_claim']} absence-claims (unverifiable by nature), "
            f"{d['n_quotes_ungrounded']} ungrounded")


def main():
    report = "--report-quotes" in sys.argv
    strict = "--strict-quotes" in sys.argv
    ungrounded: list = []
    outs = outputs(ungrounded if (report or strict) else None)
    d = json.loads(outs[OUT])

    if report or strict:
        print(_quote_summary(d))
        if ungrounded:
            print(f"\nUngrounded quotes ({len(ungrounded)}) — cited document exists, but "
                  "these words are not in its '## Full text':\n")
            for chapter, doc_id, quote in ungrounded:
                print(f"  ORS {chapter}  {doc_id}\n    {quote[:150]}")
        if strict and ungrounded:
            sys.exit(1)
        if report:
            return

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
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {d['n_chapters']} chapters piloted, "
          f"{d['n_candidates']} candidates, {d['n_docs_verified']} citations verified "
          f"against the corpus graph; {_quote_summary(d)}")


if __name__ == "__main__":
    main()
