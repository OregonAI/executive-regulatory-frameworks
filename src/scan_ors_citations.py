#!/usr/bin/env python3
"""Inventory the ORS citations landing outside this corpus's mirrored chapter selection.

  python3 src/scan_ors_citations.py            # write the catalog
  python3 src/scan_ors_citations.py --check     # exit 1 if the catalog is stale
  python3 src/scan_ors_citations.py --selftest  # the three-state classification, proved

#210. `_meta/sources/ors.yml` is titled "ORS (ingested chapters)" -- a SELECTION, not
complete coverage, and 59 citations into chapter 151 sat unreported until one reviewer
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
depends on a sibling corpus publishing something, and `--check` compares the WHOLE
generated file rather than stripping resolution-dependent lines the way the federal scan
must.
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from citation_schemes import _ors_catalog_chapters, _ors_mirrored_chapters
from repo_lib import Checks, content_files

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "_meta" / "catalog" / "ors-citation-gap.yml"

# Mandatory literal "ORS" token, unlike citation_schemes.ORS_C (which matches a bare
# NNN.NNN because the framework has already anchored it to a candidate citation string).
# This scans raw prose, where a bare decimal number is not evidence of a citation at all --
# the same reason scan_external_citations.py's FED pattern anchors on a literal CFR/USC
# token rather than matching any NN NNN.
ORS_MENTION = re.compile(r"\bORS\s+(\d{2,3}[A-Za-z]?)\.(\d{3}[A-Za-z]?)\b")

AUTHORITY_FIELDS = ("legal_authority", "statutes_implemented")


def walk_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_strings(v)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from walk_strings(v)


def classify(chapter: str, mirrored: set, catalog: dict) -> tuple[str, str]:
    """(status, catalog_title) for one lowercased chapter number.

    THREE STATES, the same three `citation_schemes._ors_chapter_absence_note` answers a
    live citation with -- this is that same rule read back as a report instead of a single
    resolution, so the two can never quietly disagree about what a chapter is."""
    if chapter in mirrored:
        return "mirrored", ""
    title = catalog.get(chapter)
    if title is not None:
        return "not_mirrored_known_real", title
    return "not_mirrored_unknown", ""


def scan() -> dict:
    mirrored = _ors_mirrored_chapters()
    catalog = _ors_catalog_chapters()

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
    for ch in sorted(set(authority) | set(mention),
                     key=lambda x: (-authority[x], -mention[x], x)):
        status, title = classify(ch, mirrored, catalog)
        if status == "mirrored":
            continue
        targets.append({
            "chapter": ch,
            "status": status,
            "catalog_title": title,
            "authority_claims": authority[ch],
            "mentions": mention[ch],
            "distinct_sections_cited": len(sections[ch]),
            "cited_by_sample": sorted(cited_by[ch])[:5],
        })

    known_real = [t for t in targets if t["status"] == "not_mirrored_known_real"]
    unknown = [t for t in targets if t["status"] == "not_mirrored_unknown"]
    all_cited_by = set()
    for ch in {t["chapter"] for t in targets}:
        all_cited_by |= cited_by[ch]

    return {
        "note": (
            "GENERATED by src/scan_ors_citations.py — do not hand-edit.\n\n"
            "Every ORS chapter this corpus's own documents cite that is NOT in\n"
            "_meta/sources/ors.yml's mirrored selection. status is one of two things,\n"
            "never guessed between: 'not_mirrored_known_real' (the chapter is in\n"
            "_meta/catalog/ors.yml's discovery map -- a real chapter simply not selected\n"
            "for ingestion, a coverage gap) or 'not_mirrored_unknown' (absent from both\n"
            "the mirrored set and the discovery map -- this corpus has no evidence either\n"
            "way, and says so rather than guessing). Mirrored chapters are not listed.\n"
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
        },
        "targets": targets,
    }


def _selftest() -> int:
    """The three-state classification, proved against synthetic mirrored/catalog sets --
    not the live corpus, so this stays fast and stays correct even as chapters are ingested
    out from under it."""
    ck = Checks()
    mirrored = {"151", "1"}
    catalog = {"151": "Public Defenders", "79": "Secured Transactions (Former Provisions)"}

    status, title = classify("151", mirrored, catalog)
    ck("a mirrored chapter classifies as mirrored", status == "mirrored")

    status, title = classify("79", mirrored, catalog)
    ck("an unmirrored chapter the discovery catalog knows classifies as known-real",
       status == "not_mirrored_known_real")
    ck("...and carries the catalog's own title", title == "Secured Transactions "
       "(Former Provisions)")

    status, title = classify("935", mirrored, catalog)
    ck("an unmirrored chapter absent from the catalog too classifies as unknown, "
       "never as known-real by default", status == "not_mirrored_unknown")
    ck("...and carries no fabricated title", title == "")

    ck("the three states are pairwise distinct",
       len({"mirrored", "not_mirrored_known_real", "not_mirrored_unknown"}) == 3)

    data = scan()
    s = data["summary"]
    ck("the live scan finds at least chapter 79's gap (measured, not assumed)",
       any(t["chapter"] == "79" and t["status"] == "not_mirrored_known_real"
           for t in data["targets"]))
    ck("chapter 151 is NOT in the report -- it is mirrored (#210's own fix)",
       not any(t["chapter"] == "151" for t in data["targets"]))
    ck("known-real + no-evidence targets add up to the reported total",
       s["chapters_known_real_not_ingested"] + s["chapters_no_corroborating_evidence"]
       == s["chapters_cited_outside_mirrored_set"])
    ck("there is at least one target of each kind on the committed corpus",
       s["chapters_known_real_not_ingested"] > 0 and s["chapters_no_corroborating_evidence"] > 0)

    return ck.report("scan-ors-citations selftest")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the committed catalog is not what a scan produces")
    ap.add_argument("--selftest", action="store_true",
                    help="prove the three-state classification can fail")
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
          f"{s['distinct_documents_citing_outside_mirrored_set']} documents")

    if args.check:
        cur = CATALOG.read_text(encoding="utf-8") if CATALOG.is_file() else ""
        if cur != text:
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
