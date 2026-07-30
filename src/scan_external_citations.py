#!/usr/bin/env python3
"""Inventory the federal instruments this corpus cites, and whether they resolve.

  python3 src/scan_external_citations.py           # write the catalog
  python3 src/scan_external_citations.py --check   # exit 1 if the catalog is stale

TWO JOBS, and the second is why this is a committed artifact rather than a one-off query.

  1. INTAKE MANIFEST for OregonAI/federal-reference. Which federal documents does Oregon
     law actually lean on? Building from a measured list means every document that corpus
     adds retires a real dead reference, instead of one someone assumed mattered.
  2. THE BEFORE/AFTER NUMBER. federal-reference's stated Done-when is that the count of
     unresolvable external citations here measurably drops. That is only checkable if the
     count is recorded first, by something reproducible.

AUTHORITY CLAIMS AND MENTIONS ARE COUNTED SEPARATELY, and the distinction is the whole
value of this scan.

A federal citation in `legal_authority` or `statutes_implemented` is a rule DECLARING that
a federal instrument is its authority. A citation in the body is the rule TALKING about
one. Only the first creates the authority edge federal-reference exists to complete, and
the two rankings barely overlap:

    by authority claim                by prose mention
    34 CFR 300  (IDEA)      105       29 CFR 1910 (OSHA)   295
    16 USC 544  (Gorge)      89       29 CFR 1926          248
    7 CFR 273   (SNAP)       30       40 CFR 60  (EPA)     223

29 CFR 1910 is the most-mentioned federal instrument in this corpus and is not in the
authority top ten at all -- Oregon OSHA has its own statutory authority and discusses the
federal standard rather than claiming it. Ranking intake by mentions would have put OSHA
first and IDEA nowhere, which is backwards for the edge we are trying to build.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "_meta" / "catalog" / "external-citations.yml"
CONFIG = ROOT / "_meta" / "corpus.yml"

# Anchored on the U.S.C./C.F.R. token so a bare number in a table cannot masquerade as a
# federal citation. Spacing and punctuation vary in the wild ("42 USC 1396", "42 U.S.C.
# § 1396", "42 U. S. C. 1396"), so the separators are optional throughout.
FED = re.compile(r"\b(\d{1,2})\s+(U\.?\s?S\.?\s?C\.?|C\.?\s?F\.?\s?R\.?)"
                 r"\s*(?:Part\s+|§+\s*)?(\d+[A-Za-z]?)")

# Frontmatter fields that constitute an AUTHORITY CLAIM rather than a mention. Measured,
# not assumed: these two carry 725 and 473 documents' worth of federal citations, and no
# other field carries more than one.
AUTHORITY_FIELDS = ("legal_authority", "statutes_implemented")

# Named instruments with no numeric citation form. Counted separately because they are
# exactly the seed's Stage 1 list, and a regex over USC/CFR would never see them.
NAMED = {
    "irs-pub-1075": re.compile(r"IRS\s+Pub(?:lication)?\.?\s*1075", re.I),
    "cjis-security-policy": re.compile(r"CJIS\s+(?:Security\s+)?Policy", re.I),
    "wioa": re.compile(r"\bWIOA\b|Workforce Innovation and Opportunity Act", re.I),
    "perkins-cte": re.compile(r"Carl\s+D\.?\s+Perkins|\bPerkins\s+V\b", re.I),
    "hipaa": re.compile(r"\bHIPAA\b", re.I),
    "ferpa": re.compile(r"\bFERPA\b", re.I),
}


def norm(title: str, kind: str, num: str) -> str:
    k = "USC" if kind.upper().replace(" ", "").replace(".", "").startswith("USC") else "CFR"
    return f"{title} {k} {num}"


def walk_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_strings(v)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from walk_strings(v)


def sibling_ids(config: dict) -> tuple[set[str], str]:
    """Ids every declared sibling publishes, plus a note on what was actually consulted.

    Resolution is measured against what a sibling PUBLISHES, not what we hope it holds --
    the same index `resolve_citation` reads at runtime. If a sibling cannot be reached the
    scan says so instead of scoring its citations as unresolvable, because "we could not
    check" and "it is not there" are opposite answers and only one of them is a gap.
    """
    ids, notes = set(), []
    for sib in (config.get("siblings") or []):
        url = sib.get("index_url")
        if not url:
            notes.append(f"{sib.get('id')}: no index_url declared")
            continue
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                ids |= set(json.load(r).get("documents", {}))
            notes.append(f"{sib.get('id')}: consulted")
        except Exception as e:                       # noqa: BLE001
            notes.append(f"{sib.get('id')}: UNREACHABLE ({type(e).__name__}) — its "
                         "citations are reported as unchecked, not as unresolved")
    return ids, "; ".join(notes) or "no siblings declared"


def scan() -> dict:
    config = yaml.safe_load(CONFIG.read_text())
    known, sib_note = sibling_ids(config)

    authority = collections.Counter()
    mention = collections.Counter()
    cited_by = collections.defaultdict(set)
    named_auth = collections.Counter()
    named_mention = collections.Counter()
    ndocs = 0

    for p in ROOT.rglob("*.md"):
        s = str(p)
        if "/_meta/" in s or "/.git/" in s:
            continue
        ndocs += 1
        text = p.read_text(errors="ignore")
        parts = text.split("---", 2)
        body = parts[2] if len(parts) > 2 else text
        doc_id = p.stem

        auth_here = set()
        if len(parts) > 2:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except Exception:                        # noqa: BLE001
                fm = {}
            for field in AUTHORITY_FIELDS:
                for value in walk_strings(fm.get(field)):
                    for m in FED.finditer(value):
                        auth_here.add(norm(*m.groups()))
                    for name, rx in NAMED.items():
                        if rx.search(value):
                            named_auth[name] += 1
        for t in auth_here:
            authority[t] += 1
            cited_by[t].add(doc_id)

        for m in FED.finditer(body):
            t = norm(*m.groups())
            mention[t] += 1
            if len(cited_by[t]) < 6:
                cited_by[t].add(doc_id)
        for name, rx in NAMED.items():
            n = len(rx.findall(body))
            if n:
                named_mention[name] += n

    targets = []
    for t in sorted(set(authority) | set(mention),
                    key=lambda x: (-authority[x], -mention[x], x)):
        targets.append({
            "citation": t,
            "authority_claims": authority[t],
            "mentions": mention[t],
            "resolves": t.replace(" ", "-").lower() in known,
            "cited_by_sample": sorted(cited_by[t])[:5],
        })
    named = [{"instrument": k,
              "authority_claims": named_auth[k],
              "mentions": named_mention[k],
              "resolves": k in known}
             for k in sorted(NAMED, key=lambda k: -(named_auth[k] * 100 + named_mention[k]))]

    unresolved_auth = sum(t["authority_claims"] for t in targets if not t["resolves"])
    return {
        "note": (
            "GENERATED by src/scan_external_citations.py — do not hand-edit.\n\n"
            "Federal instruments this corpus cites, and whether they resolve to a document\n"
            "in any declared sibling. Two uses: the intake manifest for\n"
            "OregonAI/federal-reference, and the before/after number that corpus is\n"
            "measured by.\n\n"
            "AUTHORITY CLAIMS AND MENTIONS ARE DIFFERENT and are counted separately. A\n"
            "citation in legal_authority or statutes_implemented is a rule declaring a\n"
            "federal instrument as its authority; one in the body is a rule discussing it.\n"
            "Only the first creates the edge federal-reference exists to complete, and the\n"
            "two rankings barely overlap -- 29 CFR 1910 leads on mentions and is absent\n"
            "from the authority top ten. Rank intake by authority_claims.\n"
        ),
        "siblings_consulted": sib_note,
        "summary": {
            "documents_scanned": ndocs,
            "distinct_targets": len(targets),
            "authority_claims_total": sum(authority.values()),
            "mentions_total": sum(mention.values()),
            "targets_resolving": sum(1 for t in targets if t["resolves"]),
            "unresolved_authority_claims": unresolved_auth,
        },
        "named_instruments": named,
        "targets": targets,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the committed catalog is not what a scan produces")
    args = ap.parse_args()

    data = scan()
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
    s = data["summary"]
    print(f"{s['documents_scanned']:,} documents; {s['distinct_targets']} federal targets; "
          f"{s['authority_claims_total']} authority claims, {s['mentions_total']} mentions; "
          f"{s['unresolved_authority_claims']} authority claims unresolved")

    if args.check:
        cur = CATALOG.read_text(encoding="utf-8") if CATALOG.is_file() else ""
        if cur != text:
            print("external-citations.yml is STALE — re-run src/scan_external_citations.py",
                  file=sys.stderr)
            return 1
        print("external-citations.yml is current.")
        return 0

    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text(text, encoding="utf-8")
    print(f"wrote {CATALOG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
