#!/usr/bin/env python3
"""Generate REVIEW.md — the single place listing everything that needs human
intervention or review. DERIVED, never hand-edited: every entry is computed from
ground truth already in the repo (frontmatter fields, body markers, catalog
statuses), so regenerating after any change keeps it complete and current.

  python3 src/review_queue.py           # regenerate REVIEW.md
  python3 src/review_queue.py --check   # exit 1 if committed REVIEW.md is stale (CI)
"""
import re
import sys
from pathlib import Path

import yaml

from repo_lib import REPO_ROOT, content_files, parse_frontmatter

OUT = REPO_ROOT / "REVIEW.md"
TODO_MARK = "TODO: human verification required"

# doc_types where a rule/policy/procedure/standard with zero graph edges is a red
# flag: link_graph.py should have found an authority citation (or a naming-pair,
# for procedures) for every one of these. An unlinked doc usually means the
# citation text didn't match the extractor's patterns and needs a human look.
LINKABLE_DOC_TYPES = {"rule", "policy", "procedure", "standard"}
REL_KEYS = ["implements", "implemented_by", "references_external", "related", "supersedes"]


def scan():
    q = {
        "exception": [],   # content_exception docs — zero machine verification
        "todo": [],        # explicit TODO markers in bodies/frontmatter
        "pending": [],     # status proposed/draft docs
        "migration": [],   # migration_pending
        "discrepancy": [], # curator-noted source/listing discrepancies
        "unlinked": [],    # rule/policy/procedure/standard with zero graph edges
    }
    body_counts = {}
    for path in content_files():
        rel = str(path.relative_to(REPO_ROOT))
        fm, body = parse_frontmatter(path)
        top = rel.split("/")[0] if "/" not in rel.split("/", 2)[0] else rel
        body_key = "/".join(rel.split("/")[:-1])
        body_counts[body_key] = body_counts.get(body_key, 0) + 1
        if fm.get("content_exception"):
            q["exception"].append((rel, fm["content_exception"]))
        if fm.get("migration_pending"):
            q["migration"].append((rel, "legacy mixed-mode content awaiting full-text migration"))
        raw = path.read_text()
        if TODO_MARK in raw:
            for line in raw.splitlines():
                if TODO_MARK in line:
                    q["todo"].append((rel, line.strip()[:140]))
                    break
        if fm.get("status") in ("proposed", "draft"):
            q["pending"].append((rel, f"status: {fm['status']} — {fm.get('source_version', '')[:80]}"))
        if "Date discrepancy" in body:
            q["discrepancy"].append((rel, "document's printed date differs from the listing of record (see Curator notes)"))
        if fm.get("doc_type") in LINKABLE_DOC_TYPES:
            rels = fm.get("relationships") or {}
            if not any(rels.get(k) for k in REL_KEYS):
                # A rule whose own legal_authority cites only chapter-level or
                # not-ingested statutes is a correct non-link — say so, instead of
                # implying a linker gap that needs manual fixing.
                auth = fm.get("legal_authority") or []
                sectionless = [a for a in auth
                               if re.fullmatch(r"ORS \d{1,3}[A-Z]?", a)]
                if auth and fm["doc_type"] == "rule":
                    if sectionless and len(sectionless) == len(auth):
                        why = ("rule's authority is chapter-level only "
                               f"({', '.join(auth[:4])}) — no section exists to link to; "
                               "correct non-link")
                    else:
                        why = ("rule's cited authority is not in the corpus "
                               f"({', '.join(auth[:4])}{'…' if len(auth) > 4 else ''}) — "
                               "repealed/renumbered or an un-ingested chapter; verify, "
                               "don't hand-link")
                else:
                    why = (f"{fm['doc_type']} has zero relationship edges — "
                           "link_graph.py found no authority citation "
                           "(or naming pair) to resolve; add/verify one manually")
                q["unlinked"].append((rel, why))

    # catalog-derived items
    cat_items = {"not_sliceable": [], "renumbered": [], "gaps": [], "eo": []}
    eo_path = REPO_ROOT / "_meta/catalog/eo.yml"
    if eo_path.exists():
        eo = yaml.safe_load(eo_path.read_text())
        for o in eo.get("orders", []):
            if "human review" in str(o.get("duplicate_note", "")):
                cat_items["eo"].append(
                    (o["id"], f"two listing rows with different bytes "
                              f"({o['file_ref']} vs {', '.join(o.get('duplicate_file_refs', []))}) "
                              f"— confirm which file is the order of record"))
            if o.get("status") in ("fetch_failed", "not_pdf"):
                cat_items["eo"].append((o["id"], f"{o['status']}: {o.get('note', '')[:90]}"))
            if o.get("listing_metadata_mismatch"):
                cat_items["eo"].append((o["id"], o["listing_metadata_mismatch"][:130]))
    ors = yaml.safe_load((REPO_ROOT / "_meta/catalog/ors.yml").read_text())
    for c in ors["chapters"]:
        for s in c["sections"]:
            if s.get("status") == "not_sliceable":
                cat_items["not_sliceable"].append((f"ORS {s['number']}", s.get("note", "")[:100]))
    oar = yaml.safe_load((REPO_ROOT / "_meta/catalog/oar.yml").read_text())
    for c in oar["chapters"]:
        for d in c["divisions"]:
            rules = d.get("rules")
            if isinstance(rules, list):
                for r in rules:
                    if r.get("status") in ("renumbered", "not_served", "not_sliceable"):
                        cat_items["renumbered"].append(
                            (f"OAR {r['number']}", f"{r['status']}: {r.get('note', '')[:90]}"))
                if not rules and d.get("status") == "not_ingested":
                    cat_items["gaps"].append(
                        (f"OAR chapter {c['chapter']} division {d['division']} ({d['title'][:50]})",
                         "no rules enumerated — not mirrored on oregon.public.law; needs another enumeration route"))
            elif d.get("status") == "not_ingested":
                cat_items["gaps"].append(
                    (f"OAR chapter {c['chapter']} division {d['division']} ({d['title'][:50]})",
                     "division never enumerated"))
    return q, cat_items, body_counts


def render(q, cat_items, body_counts):
    L = ["# Review queue — items needing human intervention",
         "",
         "**Generated by `src/review_queue.py` — do not edit by hand.** Every entry is",
         "derived from ground truth in the repo (frontmatter, body markers, catalogs);",
         "resolve an item at its source and regenerate. CI fails if this file is stale.",
         ""]

    def section(title, why, items, fmt=lambda a, b: f"- `{a}` — {b}"):
        L.append(f"## {title} ({len(items)})")
        L.append("")
        L.append(why)
        L.append("")
        for a, b in sorted(items):
            L.append(fmt(a, b))
        if not items:
            L.append("_(none)_")
        L.append("")

    # Executive orders are aggregated: hundreds of pre-digital orders are image-only
    # scans by nature; itemizing each would drown the section. The catalog carries the
    # per-order detail (text_layer field).
    eo_exc = [x for x in q["exception"] if x[0].startswith("executive-orders/")]
    other_exc = [x for x in q["exception"] if not x[0].startswith("executive-orders/")]
    if eo_exc:
        other_exc.append(
            (f"executive-orders/ ({len(eo_exc)} documents)",
             "image-only scans or unusable OCR layers — metadata stubs only; resolvable "
             "only by an OCR + human-verification pass; per-order detail in "
             "`_meta/catalog/eo.yml` (`text_layer` field)"))
    section("Documents with NO machine verification — highest review priority",
            "These carry `content_exception`: their sources are image-only scans or binary "
            "forms, so nothing diffs them against a snapshot. A human must check each "
            "against its `source_url`. Resolve by OCR + full-text migration, or confirm "
            "the summary and record review in the file.",
            other_exc)

    section("Explicit TODO markers",
            f"Files containing `{TODO_MARK}` — usually inserted by a source refresh: "
            "effective/version dates must be re-transcribed by a human from the changed "
            "source (HC-1 forbids assuming them). Resolve by editing the file and removing "
            "the marker.",
            q["todo"])

    section("Pending drafts — not current policy",
            "Documents whose own source (or the listing of record) marks them "
            "draft/proposed. No action needed until the upstream finalizes them "
            "(`/check-updates` will notice); review only if you need to know what's coming.",
            q["pending"])

    section("Source/listing discrepancies",
            "The document prints a different date than its listing of record (known site "
            "typos). This repo records what the document prints; each file's Curator notes "
            "explain. Review once; no fix needed unless upstream corrects itself.",
            q["discrepancy"])

    section("Unlinked rules/policies/procedures/standards — no graph edges",
            "`src/link_graph.py` found no authority citation (or, for procedures, no "
            "`_PR` naming match) connecting this document to anything else in the "
            "corpus. Usually means the source's authority/reference text doesn't match "
            "the extractor's citation patterns (a typo'd rule number, unusual wording) "
            "or the document genuinely has no printed authority — check the source and "
            "either fix the citation text or add a hand-authored relationship.",
            q["unlinked"])

    section("Catalog: sections with no sliceable body",
            "ORS catalog entries whose section text couldn't be found in the chapter HTML "
            "(likely renumbered/repealed or TOC noise). Verify against the printed ORS if "
            "any of these numbers matter; otherwise they stay intentionally not ingested.",
            cat_items["not_sliceable"])

    section("Catalog: renumbered / repealed rules (auto-resolved — verify mappings)",
            "OARD served a different rule number than requested; documents were filed "
            "under the served number and the mapping recorded. Spot-check that the "
            "mappings look right.",
            cat_items["renumbered"])

    section("Known enumeration gaps",
            "Corpus areas we know exist upstream but could not enumerate mechanically.",
            cat_items["gaps"])

    section("Executive-order catalog anomalies",
            "Oddities in the /gov/eo listing of record recorded by `src/ingest_eo.py` "
            "(duplicate rows with different file bytes, rows whose printed Year/Number "
            "metadata contradicts the filename, fetch failures). The repo trusts the "
            "filename (descriptions agree with it); spot-check each once against the "
            "official page.",
            cat_items["eo"])

    # Agency-profile curation debt: agencies whose data is in-repo but whose context
    # (governance class / publication status) is still a stub.
    prof_items = []
    prof_path = REPO_ROOT / "_meta/agency-profiles.yml"
    if prof_path.exists():
        profiles = (yaml.safe_load(prof_path.read_text()) or {}).get("profiles", {})
        content_agencies = set()
        for path in content_files():
            try:
                fm, _ = parse_frontmatter(path)
            except ValueError:
                continue
            if fm.get("agency") in profiles:
                content_agencies.add(fm["agency"])
        for a in sorted(content_agencies):
            p = profiles.get(a, {})
            gaps = []
            if p.get("governance") == "unclassified":
                gaps.append("governance unclassified (needs a class + citation basis)")
            if p.get("policies_published") == "unknown":
                gaps.append("policies_published unknown (where does this agency publish?)")
            if gaps:
                prof_items.append((f"_meta/agency-profiles.yml ({a})", "; ".join(gaps)))
    section("Agency profiles needing curation",
            "These agencies have in-repo content but their profile "
            "(`_meta/agency-profiles.yml`) still carries stub values — the model gets "
            "their data without its context until a human fills governance (with a "
            "citation) and publication status.",
            prof_items)

    if q["migration"]:
        section("Legacy migration pending", "Mixed-mode content awaiting full-text migration.",
                q["migration"])

    L += ["## Standing item: human verification stamps",
          "",
          "`verified_by`/`last_verified` across the corpus record *machine* verification at",
          "ingestion time. No document has yet had a human read-through against its official",
          "source. When you review a file, update its `last_verified` to that date — that is",
          "the attestation the review gates call for. Corpus size by directory:",
          ""]
    for k in sorted(body_counts):
        L.append(f"- `{k}/`: {body_counts[k]} documents")
    L.append("")
    return "\n".join(L)


def main():
    q, cat_items, body_counts = scan()
    text = render(q, cat_items, body_counts)
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            print("REVIEW.md is stale — run: python3 src/review_queue.py")
            sys.exit(1)
        print("REVIEW.md is current.")
        return
    OUT.write_text(text)
    total = sum(len(v) for v in q.values()) + sum(len(v) for v in cat_items.values())
    print(f"REVIEW.md regenerated: {total} item(s) across "
          f"{sum(1 for v in list(q.values()) + list(cat_items.values()) if v)} active section(s)")


if __name__ == "__main__":
    main()
