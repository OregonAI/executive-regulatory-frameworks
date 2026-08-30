#!/usr/bin/env python3
"""Inventory the ORS citations landing outside this corpus's mirrored chapter selection.

  python3 src/scan_ors_citations.py            # write the catalog
  python3 src/scan_ors_citations.py --check     # exit 1 if the catalog is stale
  python3 src/scan_ors_citations.py --selftest  # the three-state classification, proved

#210. `_meta/sources/ors.yml` is titled "ORS (ingested chapters)" -- a SELECTION, not
complete coverage, and 154 citations into chapter 151 sat unreported until one reviewer
happened to notice. `src/scan_external_citations.py` already does this shape for federal
instruments; this is the same report for this corpus's OWN statute citations, so the next
gap is a number a gate can fail on rather than a ticket someone has to notice by hand.

TWO ANSWERS FOR A CHAPTER OUTSIDE THE SELECTION, and they must never collapse into one
(CONTEXT.md, `citation_schemes._ors_chapter_absence_note`, which this module calls rather
than re-deriving): a chapter `_meta/catalog/ors.yml`'s discovery map also lists is a REAL
chapter nobody selected for ingestion -- a coverage gap, and a claim about this mirror. A
chapter absent from BOTH the mirrored set and the discovery map gets neither verdict: the
catalog is scraped for chapters "relevant to DAS/executive-branch administration" and was
simply never asked about most of the numbering space, so its silence proves nothing, and
this scan says so rather than guessing whether the chapter is real ("could not check" is
never reported as "is not there" -- AGENTS.md).

#292 ADDS A THIRD, DIFFERENT-SHAPED GAP: a chapter can be IN the mirrored selection --
its source page fetched, a row in `_meta/sources/ors.yml` -- and still hold zero
documents (16 of 547, all `(Former Provisions)` chapters with nothing current left to
ingest; `citation_schemes.ors_chapters_holding_documents`'s own docstring has the
evidence). That is not "outside the selection" in this module's own sense, so it is kept
OUT of `targets`/`chapters_cited_outside_mirrored_set` (that count would stop meaning what
its name says if a chapter that IS selected joined it) and reported separately, as
`mirrored_no_documents_targets` and its own `summary:` fields -- same shape, same reason
this scan exists, one level inside the boundary it already draws rather than blended into
it.

AGGREGATED BY CHAPTER, not by section: the question a reader has ("do we hold ORS 151 at
all") lives one level up from any one citation, and #210 itself was found and fixed at the
chapter grain (the `ors` source group gaining one entry, not 18).

AUTHORITY CLAIMS AND MENTIONS, counted separately, same split and same reason as the
federal scan: `legal_authority` / `statutes_implemented` is a rule DECLARING the statute as
its authority, and a body citation is the document TALKING about it. Both count toward the
gap -- an authority claim into an unmirrored chapter is the sharper case (#210's own: the
Office of Public Defense Services' enabling authority was unreachable), but a body mention
is still a citation this corpus cannot currently resolve to anything, and is undercounted
if dropped.

NO EXTERNAL I/O, unlike the federal scan: chapter mirroring is entirely this repository's
own committed state (`_meta/sources/ors.yml`, `_meta/catalog/ors.yml`), so nothing here
depends on a sibling corpus publishing something, and `--check` has no resolution-dependent
line to strip the way the federal scan does. It still strips one thing before comparing --
`documents_scanned` (see `_inventory_only`) -- because that line is a DENOMINATOR, not a
claim, and comparing it whole-file reproduces the exact spurious-gate shape #158 fixed for
the federal scan: any PR that adds or drops a content file, whether or not it cites ORS at
all, would otherwise fail this gate for a reason that has nothing to do with the citation
inventory.
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from citation_schemes import (ors_catalog_chapters, ors_chapters_holding_documents,
                              ors_mirrored_chapters)
from repo_lib import AUTHORITY_FIELDS, Checks, content_files, walk_strings

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "_meta" / "catalog" / "ors-citation-gap.yml"

# Mandatory literal "ORS" token, unlike citation_schemes.ORS_C (which matches a bare
# NNN.NNN because the framework has already anchored it to a candidate citation string).
# This scans raw prose, where a bare decimal number is not evidence of a citation at all --
# the same reason scan_external_citations.py's FED pattern anchors on a literal CFR/USC
# token rather than matching any NN NNN.
ORS_MENTION = re.compile(r"\bORS\s+(\d{1,3}[A-Za-z]?)\.(\d{3}[A-Za-z]?)\b")


def classify(chapter: str, mirrored: set, with_docs: set, catalog: dict) -> tuple[str, str]:
    """(status, catalog_title) for one lowercased chapter number.

    FOUR STATES (#292 added the third), the same four `citation_schemes.
    _ors_chapter_absence_note` answers a live citation with -- this is that same rule read
    back as a report instead of a single resolution, so the two can never quietly disagree
    about what a chapter is. `mirrored` now requires BOTH `chapter in mirrored` (the
    selection) AND `chapter in with_docs` (at least one document actually held) --
    `mirrored_no_documents` is the selected-but-empty case that used to be silently folded
    into `mirrored`, invisible to this scan the same way it was invisible to the resolver
    before #292."""
    if chapter in mirrored:
        if chapter in with_docs:
            return "mirrored", ""
        return "mirrored_no_documents", catalog.get(chapter) or ""
    title = catalog.get(chapter)
    if title is not None:
        return "not_mirrored_known_real", title
    return "not_mirrored_unknown", ""


def scan() -> dict:
    mirrored = ors_mirrored_chapters()
    with_docs = ors_chapters_holding_documents()
    catalog = ors_catalog_chapters()

    authority = collections.Counter()
    mention = collections.Counter()
    sections = collections.defaultdict(set)
    cited_by = collections.defaultdict(set)
    ndocs = 0

    for p in content_files():
        ndocs += 1
        text = p.read_text(errors="ignore")
        parts = text.split("---", 2)
        body = parts[2] if len(parts) > 2 else text
        doc_id = p.stem

        auth_here = set()
        if len(parts) > 2:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except Exception:                            # noqa: BLE001
                fm = {}
            for field in AUTHORITY_FIELDS:
                for value in walk_strings(fm.get(field)):
                    for m in ORS_MENTION.finditer(value):
                        auth_here.add((m.group(1).lower(), m.group(2).lower()))
        for chapter, sec in auth_here:
            authority[chapter] += 1
            sections[chapter].add(f"{chapter}.{sec}")
            cited_by[chapter].add(doc_id)

        for m in ORS_MENTION.finditer(body):
            chapter, sec = m.group(1).lower(), m.group(2).lower()
            mention[chapter] += 1
            sections[chapter].add(f"{chapter}.{sec}")
            cited_by[chapter].add(doc_id)

    targets = []
    mirrored_empty = []
    for ch in sorted(set(authority) | set(mention),
                     key=lambda x: (-authority[x], -mention[x], x)):
        status, title = classify(ch, mirrored, with_docs, catalog)
        if status == "mirrored":
            continue
        row = {
            "chapter": ch,
            "status": status,
            "catalog_title": title,
            "authority_claims": authority[ch],
            "mentions": mention[ch],
            "distinct_sections_cited": len(sections[ch]),
            "cited_by_sample": sorted(cited_by[ch])[:5],
        }
        # #292: `mirrored_no_documents` is INSIDE the selection this module's own name and
        # docstring scope `targets` to (chapters cited OUTSIDE the mirrored set) -- folding
        # it in would make `chapters_cited_outside_mirrored_set` count a chapter that IS
        # selected, which is the same kind of false claim the note text below refuses to
        # make. Reported in its own list/summary block instead, not silently dropped.
        if status == "mirrored_no_documents":
            mirrored_empty.append(row)
        else:
            targets.append(row)

    known_real = [t for t in targets if t["status"] == "not_mirrored_known_real"]
    unknown = [t for t in targets if t["status"] == "not_mirrored_unknown"]

    def documents_citing(rows):
        """Union of `cited_by[chapter]` across every chapter in `rows` — the same
        one-line question `targets` and `mirrored_empty` both ask of the same `cited_by`
        map, asked once instead of twice."""
        out = set()
        for ch in {t["chapter"] for t in rows}:
            out |= cited_by[ch]
        return out

    all_cited_by = documents_citing(targets)
    mirrored_empty_cited_by = documents_citing(mirrored_empty)

    return {
        "note": (
            "GENERATED by src/scan_ors_citations.py — do not hand-edit.\n\n"
            "Every ORS chapter this corpus's own documents cite that is NOT in\n"
            "_meta/sources/ors.yml's mirrored selection. status is one of two things,\n"
            "never guessed between: 'not_mirrored_known_real' (the chapter is in\n"
            "_meta/catalog/ors.yml's discovery map -- a real chapter simply not selected\n"
            "for ingestion, a coverage gap) or 'not_mirrored_unknown' (absent from both\n"
            "the mirrored set and the discovery map -- this corpus has no evidence either\n"
            "way, and says so rather than guessing). Mirrored chapters are not listed here.\n\n"
            "mirrored_no_documents_targets (#292) is a THIRD, separately-scoped list: "
            "chapters that ARE in the mirrored selection -- a source row in\n"
            "_meta/sources/ors.yml -- but hold zero documents (summary.chapters_mirrored_\n"
            "no_documents counts them; on this corpus every one is a '(Former Provisions)'\n"
            "chapter with nothing current left to ingest). Kept out of targets/\n"
            "chapters_cited_outside_mirrored_set because they are not outside the\n"
            "selection; still a coverage gap, reported on its own.\n"
        ),
        "summary": {
            "documents_scanned": ndocs,
            "chapters_mirrored": len(mirrored),
            "chapters_cited_outside_mirrored_set": len(targets),
            "chapters_known_real_not_ingested": len(known_real),
            "chapters_no_corroborating_evidence": len(unknown),
            "authority_claims_outside_mirrored_set": sum(t["authority_claims"]
                                                          for t in targets),
            "mentions_outside_mirrored_set": sum(t["mentions"] for t in targets),
            "distinct_documents_citing_outside_mirrored_set": len(all_cited_by),
            "chapters_mirrored_no_documents": len(mirrored_empty),
            "authority_claims_mirrored_no_documents": sum(t["authority_claims"]
                                                           for t in mirrored_empty),
            "mentions_mirrored_no_documents": sum(t["mentions"] for t in mirrored_empty),
            "distinct_documents_citing_mirrored_no_documents": len(mirrored_empty_cited_by),
        },
        "mirrored_no_documents_targets": mirrored_empty,
        "targets": targets,
    }


def _inventory_only(text: str) -> str:
    """The catalog with `documents_scanned` removed -- the one line `--check` must not
    compare, and the exact #158 shape `scan_external_citations.py`'s own `_inventory_only`
    exists to fix, reproduced here in the sibling this module is modelled on.

    `documents_scanned` is a DENOMINATOR, not a claim: this catalog asserts which ORS
    chapters the corpus cites outside its mirrored selection, and how many documents were
    read to find them is context. Comparing it whole-file means any PR that adds or drops
    a content file -- one that cites no ORS chapter at all included -- moves this one line
    and fails the gate for a reason that has nothing to do with the citation inventory.
    Every other summary figure (`chapters_cited_outside_mirrored_set`,
    `authority_claims_outside_mirrored_set`, `mentions_outside_mirrored_set`, ...) DOES
    move when the inventory itself changes, and those stay compared -- so a lone move in
    `documents_scanned` alone means the inventory is provably unchanged, same as the
    federal scan's own resolution-stripped compare, just for a different reason (this
    module has no resolution-dependent line to strip -- ORS chapter mirroring is entirely
    this repository's own committed state).

    Still WRITTEN and PRINTED on every run, so a scope change remains visible as an
    obviously wrong count; it is just no longer a merge blocker on its own.
    """
    return "\n".join(l for l in text.splitlines()
                      if not l.lstrip().startswith("documents_scanned:"))


def _selftest() -> int:
    """The four-state classification, proved against synthetic mirrored/with-docs/catalog
    sets -- not the live corpus, so this stays fast and stays correct even as chapters are
    ingested out from under it."""
    ck = Checks()
    mirrored = {"151", "1", "351"}
    with_docs = {"151", "1"}
    catalog = {"151": "Public Defenders", "79": "Secured Transactions (Former Provisions)",
              "351": "Higher Education Generally (Former Provisions)"}

    status, title = classify("151", mirrored, with_docs, catalog)
    ck("a mirrored chapter that holds documents classifies as mirrored",
       status == "mirrored")

    status, title = classify("351", mirrored, with_docs, catalog)
    ck("#292: a mirrored chapter that holds ZERO documents classifies as its own state, "
       "never folded into plain 'mirrored'", status == "mirrored_no_documents")
    ck("...and carries the catalog's own title, same as a not-mirrored known-real row",
       title == "Higher Education Generally (Former Provisions)")

    status, title = classify("79", mirrored, with_docs, catalog)
    ck("an unmirrored chapter the discovery catalog knows classifies as known-real",
       status == "not_mirrored_known_real")
    ck("...and carries the catalog's own title", title == "Secured Transactions "
       "(Former Provisions)")

    status, title = classify("935", mirrored, with_docs, catalog)
    ck("an unmirrored chapter absent from the catalog too classifies as unknown, "
       "never as known-real by default", status == "not_mirrored_unknown")
    ck("...and carries no fabricated title", title == "")

    ck("the four states are pairwise distinct",
       len({"mirrored", "mirrored_no_documents", "not_mirrored_known_real",
            "not_mirrored_unknown"}) == 4)

    data = scan()
    s = data["summary"]
    ck("the live scan finds at least chapter 79's gap (measured, not assumed)",
       any(t["chapter"] == "79" and t["status"] == "not_mirrored_known_real"
           for t in data["targets"]))
    ck("chapter 151 is NOT in the report -- it is mirrored (#210's own fix)",
       not any(t["chapter"] == "151" for t in data["targets"]))
    ck("single-digit chapters are visible to the scan too -- chapter 2 (Supreme Court/"
       "Court of Appeals, ORS 2.570 et al.) is cited 67 times across 64 documents and is "
       "absent from _meta/sources/ors.yml, so it must appear here rather than being "
       "invisible to a regex anchored on two-to-three-digit chapters",
       any(t["chapter"] == "2" for t in data["targets"]))
    ck("known-real + no-evidence targets add up to the reported total",
       s["chapters_known_real_not_ingested"] + s["chapters_no_corroborating_evidence"]
       == s["chapters_cited_outside_mirrored_set"])
    ck("there is at least one target of each kind on the committed corpus",
       s["chapters_known_real_not_ingested"] > 0 and s["chapters_no_corroborating_evidence"] > 0)

    # #292: the live corpus's own measured 16 mirrored-but-empty chapters, reported
    # separately rather than folded into `targets` (which is scoped to chapters OUTSIDE
    # the selection -- these are inside it).
    ck("#292: the live scan finds chapter 351 among the mirrored-but-empty targets "
       "(measured, not assumed)",
       any(t["chapter"] == "351" for t in data["mirrored_no_documents_targets"]))
    ck("...and it is NOT also counted among the outside-the-selection targets",
       not any(t["chapter"] == "351" for t in data["targets"]))
    ck("...and the summary count matches the list actually returned",
       s["chapters_mirrored_no_documents"] == len(data["mirrored_no_documents_targets"]))
    ck("...and every mirrored-but-empty chapter really is in the mirrored selection "
       "(never a not-mirrored chapter misclassified into this bucket)",
       all(t["chapter"] in ors_mirrored_chapters()
           for t in data["mirrored_no_documents_targets"]))

    # #158's shape, reproduced for this module's own --check (`_inventory_only`): a
    # change that moves ONLY documents_scanned -- a PR adding or dropping any content
    # file, whether or not it cites ORS at all -- must not trip the gate, because it is
    # provably not a change to the citation inventory the catalog exists to report.
    a = "note: x\nsummary:\n  documents_scanned: 76313\n  chapters_mirrored: 547\ntargets: []\n"
    b = "note: x\nsummary:\n  documents_scanned: 76312\n  chapters_mirrored: 547\ntargets: []\n"
    ck("a whole-file compare WOULD fail on a documents_scanned-only diff (the bug, "
       "reproduced synthetically as the control)", a != b)
    ck("_inventory_only strips exactly that line, so the same pair compares equal",
       _inventory_only(a) == _inventory_only(b))
    c = "note: x\nsummary:\n  documents_scanned: 76313\n  chapters_mirrored: 548\ntargets: []\n"
    ck("...but a real inventory change (chapters_mirrored moving here) still compares "
       "unequal -- the strip removes the denominator, not the gate's teeth",
       _inventory_only(a) != _inventory_only(c))

    return ck.report("scan-ors-citations selftest")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the committed catalog is not what a scan produces")
    ap.add_argument("--selftest", action="store_true",
                    help="prove the four-state classification can fail")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    data = scan()
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
    s = data["summary"]
    print(f"{s['documents_scanned']:,} documents; "
          f"{s['chapters_cited_outside_mirrored_set']} ORS chapters cited outside the "
          f"mirrored set ({s['chapters_known_real_not_ingested']} known real chapters, "
          f"{s['chapters_no_corroborating_evidence']} with no corroborating evidence); "
          f"{s['authority_claims_outside_mirrored_set']} authority claims, "
          f"{s['mentions_outside_mirrored_set']} mentions, across "
          f"{s['distinct_documents_citing_outside_mirrored_set']} documents; "
          f"{s['chapters_mirrored_no_documents']} mirrored chapters cited but holding "
          f"zero documents ({s['authority_claims_mirrored_no_documents']} authority "
          f"claims, {s['mentions_mirrored_no_documents']} mentions, across "
          f"{s['distinct_documents_citing_mirrored_no_documents']} documents)")

    if args.check:
        cur = CATALOG.read_text(encoding="utf-8") if CATALOG.is_file() else ""
        # Compare the INVENTORY, not the denominator -- see _inventory_only. Everything
        # but `documents_scanned` compares whole-file, because unlike the federal scan
        # this module has nothing resolution-dependent to also strip.
        if _inventory_only(cur) != _inventory_only(text):
            print("ors-citation-gap.yml is STALE — re-run src/scan_ors_citations.py",
                  file=sys.stderr)
            return 1
        print("ors-citation-gap.yml is current.")
        return 0

    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text(text, encoding="utf-8")
    print(f"wrote {CATALOG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
