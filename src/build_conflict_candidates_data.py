#!/usr/bin/env python3
"""REGENERATION ORDER MATTERS. This embeds the mechanical scan's counts, so
`detect_mechanical.py --write` must run BEFORE this script; otherwise the page shows the
previous scan's numbers while claiming to be current. The --check gates catch it either
way — this one goes stale the moment the mechanical catalog changes — but the correct
order is: detect_mechanical --write, then this, then build_conflict_candidates.py.

Cache the conflict-candidates dataset from _meta/catalog/conflict-candidates.yml (see
that file's note — it's an AI-assisted pilot snapshot, not mechanically derived and not
legally reviewed).

Two mechanical verifications run here, both aimed at the same thing: an LLM-authored
claim about a document must be checkable against the corpus, not taken on faith.

1. CITATION EXISTENCE (hard gate). Every cited document id must resolve in the corpus
   graph, or be explicitly marked not_found: true. Citing a document that doesn't exist
   would be a fabrication, so this exits non-zero.

2. QUOTE GROUNDING (reported, not fatal by default; --strict-quotes to enforce). Each
   document's `quote` is checked against that document's own '## Full text' AND against
   its declared `statutes_implemented`. This catches the failure the citation gate
   cannot: a real document cited with words it does not contain.

   Both haystacks, because a candidate may legitimately be ABOUT the declaration rather
   than the operative text (#62 counts 26 of them), and searching only the full text
   marked every one of those as fabricated.

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
import hashlib
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

# The same floor against the DECLARED-AUTHORITY haystack, which is a ~100-character list
# of citations rather than a 40,000-character rule body. Ten characters of prose proves
# nothing inside a rule; ten characters matching inside one document's
# `statutes_implemented` names a specific statute, which is the whole claim. Measured
# rather than picked: over the 60-chapter catalog, 10 is the length of the shortest
# faithful declared-authority quote there is (`163.165(2)`, OAR 213-005-0001), and
# lowering it to 8 or 6 recovers no further quote — so this admits every real one and
# buys nothing by going lower.
_MIN_DECLARED_CHARS = 10

# How a rule's declared `statutes_implemented` list is flattened into one line. Shared
# with analyze_conflicts.render_user ON PURPOSE: the bundle shows the model this exact
# string, and a faithful quote of it is checked against this exact string. If the two
# ever joined the list differently, every quote of the declaration would read as
# ungrounded and nothing would say why.
DECLARED_AUTHORITY_SEP = ", "


def declared_authority(fm: dict) -> str:
    """A document's declared `statutes_implemented`, as the single line the model is
    shown and a quote is checked against. Empty string when the field is absent."""
    v = fm.get("statutes_implemented") or []
    items = [str(x).strip() for x in (v if isinstance(v, list) else [v]) if str(x).strip()]
    return DECLARED_AUTHORITY_SEP.join(items)


def grounding_sources(path) -> tuple[str, str]:
    """(folded '## Full text', folded declared authority) — the two places in a document
    a quote may legitimately be drawn from.

    One function, because three consumers check quotes (this cache builder,
    eval_conflicts.py, validate_candidates.py) and a haystack that differs between them
    would make the same candidate grounded in one report and fabricated in another."""
    fm, body = parse_frontmatter(path)
    ft = extract_fulltext(body) or ""
    return (fold(ft) if ft else ""), fold(declared_authority(fm))


def _segments_in_order(quote: str, hay: str, min_chars: int) -> bool:
    """Every segment of `quote` appears in `hay` IN ORDER, where segments are split on
    '...' and on bracketed editorial spans.

    Order matters: it stops a quote being 'verified' by words scattered across unrelated
    subsections. The evidence-length floor stops the opposite failure — a quote that is
    almost entirely brackets/elision would otherwise have nothing left to check and match
    vacuously."""
    segments = [s for s in (fold(p) for p in _ELISION_RE.split(quote)) if s]
    if sum(len(s) for s in segments) < min_chars:
        return False
    pos = 0
    for seg in segments:
        i = hay.find(seg, pos)
        if i == -1:
            return False
        pos = i + len(seg)
    return True


def quote_is_grounded(quote: str, full_text: str, declared: str = "") -> bool:
    """True if `quote` is grounded in the document's operative text OR in its declared
    `statutes_implemented`.

    WHY TWO HAYSTACKS (#62). Prompt v5 asks the model to quote a rule's DECLARED
    authority — #62 counts 26 catalog candidates resting on it — and `render_user` puts
    that declaration in the bundle. But this check only ever searched `extract_fulltext(body)`,
    which excludes frontmatter, so the entire wrong_authority class was unverifiable by
    construction and read as fabricated. Measured on run haiku-v5-think-328332: 8/10
    grounded, and BOTH failures were correct quotes of a declaration the checker could
    not see. Grounding is the signal used to decide whether a model can be trusted at
    all, so an error in this direction is the worst one available.

    The declaration is corpus data — it comes from the document's own frontmatter — not
    the label `render_user` prints above it. Quoting that label must still fail, or the
    check would be verifying a quote against words this pipeline wrote itself."""
    return (_segments_in_order(quote, full_text, _MIN_EVIDENCE_CHARS)
            or (bool(declared)
                and _segments_in_order(quote, declared, _MIN_DECLARED_CHARS)))


# An absence-claim asserts the source does NOT say something, so it can never match the
# source. Shape-detected so it can be excluded from the ungrounded count rather than
# silently inflating it.
#
# The frontmatter branch takes a DOTTED PATH (#67). It used to require the colon
# immediately after the field name, so `relationships.implements: [..., ors-435.120];
# body text cites only "42 CFR 435.926" ...` — an observation about frontmatter, exactly
# what this branch is for — fell through and was counted as an ungrounded quote instead.
# One quote in the catalog today (ORS 435, oar-461-135-0010), but the shape is what a
# model naturally writes when told to cite a nested field, and the miscount is invisible
# in the aggregate. Only the dotted SUFFIX is allowed; no field names were added on
# speculation, because a name nobody has seen written would be an unmeasured widening of
# the one bucket that excuses a quote from the grounding rate.
_ABSENCE_RE = re.compile(
    r"^\(|"                                   # "(full text has no operative subsections)"
    r"^no\s|^none\b|"                         # "no end date", "no flexibility clause"
    r"^(statutes_implemented|relationships|implemented_by|history)"
    r"(\.[a-z_]+)*\s*:",                      # frontmatter ref, incl. relationships.implements:
    re.I)


def looks_like_absence_claim(quote: str) -> bool:
    return bool(_ABSENCE_RE.search(quote.strip()))


GRADES = (None, "low", "medium", "high")
TRIAGE_STATES = ("unreviewed", "confirmed", "dismissed")


# A subsection path inside a citation: "(4)", "(1)(c)", "(12)(a)(B)", "(1)(b)(A)(i)".
# Bounded on purpose — 1-3 digits or 1-2 letters — so descriptive parentheticals a model
# writes ("(entire rule)", "(CC5)", "(frontmatter)") are not mistaken for subsections.
_SUBSECTION_RE = re.compile(r"\((\d{1,3}|[A-Za-z]{1,2})\)")


def _citation_key(citation: str) -> str:
    """The identity-bearing content of a free-text citation: its subsection path, and
    nothing else.

    WHY PROSE IS DISCARDED (#63). The previous key was every alphanumeric character of
    the citation, so two runs that found the SAME conflict in the SAME two provisions got
    different fingerprints whenever they described the pointer differently. Measured: the
    pilot wrote `OAR 581-026-0600, statutes_implemented`, Haiku v4 wrote
    `OAR 581-026-0600 (entire rule)`, Haiku v5 wrote `OAR 581-026-0600, declared
    statutes_implemented and rule title` — one finding stored three times, and two arms
    scored as having MISSED a candidate their own output contains. A declared-authority
    pointer has no canonical form, so this only gets worse as v5 runs at scale.

    Containment (#58) cannot reach it: the pair-sets overlap but neither contains the
    other, so `_contained_match` correctly declines. The fix has to be here, in what a
    citation contributes to identity at all.

    WHAT IS KEPT, and why it is not looser than this. The subsection path stays, because
    it is the thing that makes two findings over the same document pair distinct — ORS
    435's `(3)` vs `(6)` and `(1)(c)` vs `(1)(c)`, the case that refuted keying on
    document ids alone. Tokens are joined with '.' so `(1)(3)` cannot collide with `(13)`.
    Case is folded, matching the previous key's behaviour: models write `(2)(A)` and
    `(2)(a)` for the same provision often enough that preserving case would reintroduce
    the drift this function exists to remove.

    Measured before adopting, the way #58 was: over the whole catalog — 153 candidates,
    60 chapters — this key merges exactly one group (the three ORS 332.158 /
    OAR 581-026-0600 records above) and breaks no existing containment relation.

    Known limit: two genuinely distinct findings about the same document, neither citing
    a subsection and distinguished ONLY by their prose, now share a key. None exists in
    the catalog today; if one appears it surfaces as a corroboration stamp on a finding
    it does not belong to, which is the same failure mode #58's ambiguity rule guards
    against and is visible in `corroborated_by`."""
    return ".".join(t.lower() for t in _SUBSECTION_RE.findall(citation or ""))


def candidate_fingerprint(ors_chapter: str, cand: dict) -> str:
    """Stable identity of a candidate ACROSS RUNS: its chapter plus the set of
    (document, cited subsection) pairs it is about.

    Deliberately NOT the summary. Two runs describing the same tension between the same
    provisions are the same finding for triage purposes even when they word it
    differently, and a rewording must not resurrect something a human dismissed.

    Deliberately NOT document ids alone, either — that was the first design and the
    corpus refuted it immediately. ORS 435 carries two distinct findings over the same
    pair of documents: one about ORS 435.254(3) vs OAR 333-505-0120(6), another about
    (1)(c) vs (1)(c). Keying on ids alone would have forced two real findings to merge.
    The subsection is what makes them different, so the subsection is in the key.

    Deliberately NOT the citation's PROSE, since #63. "statutes_implemented" and
    "declared statutes_implemented and rule title" point at the same place; keying on the
    words made one finding into three and scored two arms as having missed it. What each
    citation contributes is now only its subsection path — see `_citation_key`.

    Known limit: a re-run that writes a subsection in a form with no parentheses
    ("subsection 3" rather than "(3)") contributes no subsection path at all, so it keys
    as though the whole document were cited. No catalog citation is written that way
    today (0 of the catalog's 297 citations contain the word subsection or paragraph), so
    it is a shape to watch for rather than one to normalise blind.

    Known limit, and handled elsewhere: a run citing the same conflict plus one EXTRA
    supporting provision gets a different set, hence a different hash. Because that is an
    exact-hash scheme it cannot see the containment itself; `merge_into_catalog` compares
    the raw pair sets from `candidate_pairs()` to catch it (#58)."""
    return hashlib.sha256(
        "|".join([str(ors_chapter), *sorted(candidate_pairs(cand))]).encode()
    ).hexdigest()[:16]


def candidate_pairs(cand: dict) -> frozenset:
    """The (document, cited subsection) pairs a candidate is about — the raw material
    `candidate_fingerprint` hashes.

    Exposed unhashed because containment is invisible once hashed, and containment is
    exactly the relation that tells a genuine re-discovery citing extra support apart
    from a new finding."""
    return frozenset(
        f"{d['id']}#{_citation_key(d.get('citation'))}"
        for d in cand.get("documents") or [] if d.get("id"))


def validate_envelope(ors_chapter: str, cand: dict, seen: dict) -> None:
    """Enforce the v2 provenance/triage envelope. These are hard failures: the whole point
    of the schema is that an ungraded or untriaged candidate cannot masquerade as a
    reviewed one."""
    for field in ("confidence", "severity"):
        if cand.get(field) not in GRADES:
            raise SystemExit(
                f"conflict-candidates.yml (ORS {ors_chapter}): {field}="
                f"{cand.get(field)!r} — must be one of {GRADES!r}. null means NOT "
                "RECORDED; do not use it to mean 'low'.")
    triage = cand.get("triage") or {}
    if triage.get("status") not in TRIAGE_STATES:
        raise SystemExit(
            f"conflict-candidates.yml (ORS {ors_chapter}): triage.status="
            f"{triage.get('status')!r} — must be one of {TRIAGE_STATES!r}.")
    if triage["status"] == "dismissed" and not (triage.get("note") or "").strip():
        raise SystemExit(
            f"conflict-candidates.yml (ORS {ors_chapter}): a dismissed candidate must "
            "carry triage.note saying why — an unexplained dismissal is indistinguishable "
            f"from an oversight. Candidate: {cand.get('summary', '')[:80]!r}")
    if not cand.get("run_id"):
        raise SystemExit(
            f"conflict-candidates.yml (ORS {ors_chapter}): candidate has no run_id — "
            "every candidate must be attributable to the run that produced it.")

    fp = candidate_fingerprint(ors_chapter, cand)
    if fp in seen:
        raise SystemExit(
            f"conflict-candidates.yml (ORS {ors_chapter}): two candidates cite the same "
            f"documents at the same subsections "
            f"({sorted({d['id'] for d in cand.get('documents') or []})}), so they share a "
            "triage fingerprint and a re-run could not tell them apart. Fold them with "
            "`python3 src/analyze_conflicts.py --dedupe`, or make them cite the "
            "provisions they actually differ on. Citation PROSE does not distinguish "
            "them — it is not part of the key (#63).")
    seen[fp] = True
    cand["fingerprint"] = fp


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
            # NAME READER — DISPLAY: the agency label shown beside a conflict candidate, and
            # the key the list is ordered by. The BODY is reached by its OAR chapter through
            # enrich_oar.load_registry_by_chapter(), which is an OAR-derived join and is
            # keyed on the chapter number, not on any name; only the label is read here, so
            # it stays on `name` — the statutory name after ADR 0003, which is what a
            # reader of the conflict view is shown.
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

    src_cache: dict[str, tuple[str, str]] = {}

    def sources(doc_id: str) -> tuple[str, str]:
        if doc_id not in src_cache:
            src_cache[doc_id] = grounding_sources(REPO_ROOT / paths[doc_id])
        return src_cache[doc_id]

    status_cache: dict = {}

    def doc_status(doc_id):
        """A document's frontmatter `status`, cached. `repealed` is the value that
        matters: 2,031 of the corpus's 36,953 rules carry it."""
        if doc_id not in status_cache:
            path = paths.get(doc_id)
            status_cache[doc_id] = (parse_frontmatter(REPO_ROOT / path)[0].get("status")
                                    if path else None)
        return status_cache[doc_id]

    n_candidates = n_docs_checked = n_artifacts = n_repealed = 0
    n_grounded = n_absence = n_ungrounded = 0
    all_agencies = {}
    triage_counts = dict.fromkeys(TRIAGE_STATES, 0)
    severity_counts = {g or "ungraded": 0 for g in GRADES}
    seen_fingerprints: dict = {}
    for ch in cat["chapters"]:
        for cand in ch.get("candidates", []):
            n_candidates += 1
            validate_envelope(ch["ors_chapter"], cand, seen_fingerprints)
            # A candidate resting on a REPEALED rule is not a live conflict. The rule is
            # gone; whatever it said no longer binds anyone. These are marked rather than
            # deleted — the finding was true when made, and silently dropping catalog rows
            # would leave the count unexplainable — and the page hides them by default.
            cand["cites_repealed"] = sorted(
                {d["id"] for d in cand["documents"] if doc_status(d.get("id")) == "repealed"})
            if cand["cites_repealed"]:
                n_repealed += 1
            triage_counts[cand["triage"]["status"]] += 1
            severity_counts[cand.get("severity") or "ungraded"] += 1
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

                # Quote grounding. Only meaningful for documents that exist and carry
                # SOMETHING to check against — a verbatim '## Full text', or a declared
                # `statutes_implemented` for candidates that are about the declaration.
                if not exists or not doc.get("quote"):
                    doc["quote_verified"] = None
                    continue
                ft, declared = sources(doc["id"])
                if not ft and not declared:
                    doc["quote_verified"] = None      # summary-only doc: nothing to diff
                elif quote_is_grounded(doc["quote"], ft, declared):
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
        # Per-CANDIDATE agencies, from the OAR documents that candidate actually cites.
        # The chapter-level list is the union across a whole ORS chapter, so filtering on
        # it alone shows every finding in any chapter the agency touches — including
        # findings that are entirely another agency's. Derived from the same registry
        # mapping as _chapter_agencies so the filter dropdown and the per-candidate tags
        # can never disagree about what an agency is called.
        for cand in ch.get("candidates", []):
            slugs = {}
            for doc in cand["documents"]:
                did = str(doc.get("id") or "")
                if not did.startswith("oar-"):
                    continue
                org = registry_by_chapter.get(did.split("-")[1])
                if org:
                    # NAME READER — DISPLAY: same label, per candidate document.
                    slugs[org["slug"]] = org["name"]
            cand["agency_slugs"] = sorted(slugs)
        for a in agencies:
            all_agencies[a["slug"]] = all_agencies.get(a["slug"], 0) + 1

    n_clean = sum(1 for ch in cat["chapters"] if not ch.get("candidates"))
    # NAME READER — DISPLAY: the labels already recorded in the catalog's per-chapter
    # agency_list, re-indexed by slug for the page's agency filter.
    agency_names = {a["slug"]: a["name"] for ch in cat["chapters"] for a in ch["agency_list"]}

    # The MECHANICAL pass, surfaced beside the model-derived candidates. Its counts are far
    # larger and a reader who meets them without explanation will reasonably assume the
    # corpus is broken — so the page carries the reasoning, not just the number.
    mech_path = REPO_ROOT / "_meta/catalog/mechanical-findings.yml"
    mech = None
    if mech_path.is_file():
        m = yaml.safe_load(mech_path.read_text())
        mech = {"counts": m["counts"], "note": m["note"],
                "by_cause": m.get("dead_citations_by_cause", {}),
                "cause_meanings": m.get("cause_meanings", {}),
                "corpus_gap_note": m.get("corpus_gap_note", ""),
                "most_cited": (m.get("most_cited_dead_targets") or [])[:10],
                "scanned_rules": m.get("scanned_rules")}

    return {
        "mechanical": mech,
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
        # Surfaced, not silent: the page hides these by default and says how many.
        "n_candidates_citing_repealed": n_repealed,
        "schema_version": cat.get("schema_version", 1),
        "triage_counts": triage_counts,
        "severity_counts": severity_counts,
        # NAME READER — DISPLAY: the agency filter's own list, ordered by the label it
        # shows.
        "all_agencies": sorted(
            [{"slug": s, "name": agency_names[s], "chapters": n} for s, n in all_agencies.items()],
            key=lambda a: a["name"]),
        "chapters": cat["chapters"],
    }


def outputs(collect=None):
    return {OUT: json.dumps(compute(collect), ensure_ascii=False, separators=(",", ":"))}


def _quote_summary(d: dict) -> str:
    checked = d["n_quotes_grounded"] + d["n_quotes_absence_claim"] + d["n_quotes_ungrounded"]
    return (f"quotes: {d['n_quotes_grounded']}/{checked} grounded in source full text or "
            f"declared authority, "
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
                  "these words are in neither its '## Full text' nor its declared "
                  "statutes_implemented:\n")
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
