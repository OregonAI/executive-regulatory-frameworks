#!/usr/bin/env python3
"""Enrich OAR rule frontmatter from the structured lines OARD prints inside every
rule's own verbatim text — pure mechanical parsing of already-committed content,
no new fetches, no fabrication (HC-1: anything that doesn't parse cleanly is left
null rather than guessed).

  python3 src/enrich_oar.py            # enrich every rules/**/oar-*.md in place
  python3 src/enrich_oar.py --check    # CI: fail if any rule's frontmatter drifts
                                       # from what its own body's lines say
  python3 src/enrich_oar.py oar-125-010-0005   # one rule (testing)

What gets filled, and from where (all inside the committed '## Full text'):
  legal_authority       <- "Statutory/Other Authority:" line (verbatim citations,
                           split on ','/'&'; bare section numbers re-prefixed with
                           the family of the preceding token, e.g. "ORS 279.015 &
                           279.055" -> ["ORS 279.015", "ORS 279.055"]; ranges kept
                           as printed)
  statutes_implemented  <- "Statutes/Other Implemented:" line, same parsing
  effective_date        <- the FIRST (newest) History action's effective date
                           ("effective 05/01/2026" | "cert. ef. 12-28-06" |
                           "f. & ef. 11-3-83"; 2-digit years pivot at 30)
  source_version        <- newest History action id + its date (e.g. "DAS 2-2026,
                           effective 05/01/2026")
  relationships.supersedes <- "renumbered from NNN-NNN-NNNN" in the newest action,
                           recorded as the citation string "OAR <old>"
  agency                <- rule's chapter -> _meta/catalog/agencies.yml org (keyed
                           by oar_chapter; sub-units get their own slug)
  issuing_body          <- that org's proper name

Used by ingest_oar.py at document-creation time too, so future imports are born
enriched; this script's file-rewrite mode exists for backfilling and for the CI
drift check."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml

from repo_lib import REPO_ROOT, content_files, parse_frontmatter

AUTH_RE = re.compile(r"Statutory/Other Authority:\s*(.*?)\s*(?=Statutes/Other Implemented:|History:|$)", re.S)
IMPL_RE = re.compile(r"Statutes/Other Implemented:\s*(.*?)\s*(?=Statutory/Other Authority:|History:|$)", re.S)
HIST_RE = re.compile(r"^History:\s*(.*)$", re.M)
# one History action: "DAS 2-2026, ..." / "OSCIO 1-2024, ..." / "GS 7-1983, ..."
ACTION_ID_RE = re.compile(r"([A-Z]{2,8} \d+-\d{4}(?:\(Temp\))?)")
EFF_LONG_RE = re.compile(r"effective (\d{2}/\d{2}/\d{4})")
EFF_SHORT_RE = re.compile(r"(?:cert\. ef\.|& ef\.|cert\. &? ?ef\.|ef\.)\s*(\d{1,2}-\d{1,2}-\d{2,4})")
RENUM_RE = re.compile(r"renumbered from (\d{3}-\d{3}-\d{4})")
CITE_FAMILY_RE = re.compile(r"^(ORS|OAR|OL|USC|CFR|Or Laws|Oregon Laws)\b", re.I)


def parse_citation_list(text: str) -> list:
    """'ORS 184.340, 278.405 & 655.520' -> ['ORS 184.340','ORS 278.405','ORS 655.520'].
    Ranges ('ORS 655.505 - 655.555') and non-standard cites kept as printed."""
    text = re.sub(r"\s+", " ", text).strip().rstrip(".,;")
    if not text:
        return []
    # protect range hyphens with spaces around them from being treated as separators
    parts = re.split(r",|\s&\s", text)
    out, family = [], None
    for p in parts:
        p = p.strip().rstrip(".,;")
        if not p:
            continue
        m = CITE_FAMILY_RE.match(p)
        if m:
            family = m.group(1)
            out.append(p)
        elif re.match(r"^\d", p) and family:
            out.append(f"{family} {p}")
        else:
            out.append(p)  # keep verbatim ("Chapter 690 Oregon Laws 1983", etc.)
    return out


def parse_effective(action_text: str):
    """Effective date (ISO) from one History action's text, or None."""
    m = EFF_LONG_RE.search(action_text)
    if m:
        mm, dd, yyyy = m.group(1).split("/")
        return f"{yyyy}-{mm}-{dd}"
    m = EFF_SHORT_RE.search(action_text)
    if m:
        mo, d, y = m.group(1).split("-")
        if len(y) == 2:
            y = ("20" if int(y) <= 30 else "19") + y
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return None


def parse_history(hist: str):
    """(newest_action_id, newest_effective_iso, renumbered_from) from a History line.
    Actions run newest-first; each starts with an id like 'DAS 2-2026'."""
    ids = list(ACTION_ID_RE.finditer(hist))
    if not ids:
        return None, parse_effective(hist), (RENUM_RE.search(hist).group(1)
                                             if RENUM_RE.search(hist) else None)
    first = ids[0]
    end = ids[1].start() if len(ids) > 1 else len(hist)
    newest = hist[first.start():end]
    renum = RENUM_RE.search(newest)
    return first.group(1), parse_effective(newest), (renum.group(1) if renum else None)


def derive(body: str, doc_id: str, registry_by_chapter: dict) -> dict:
    """All derivable frontmatter values for one rule, from its own body text."""
    d = {}
    m = AUTH_RE.search(body)
    d["legal_authority"] = parse_citation_list(m.group(1)) if m else []
    m = IMPL_RE.search(body)
    d["statutes_implemented"] = parse_citation_list(m.group(1)) if m else []
    m = HIST_RE.search(body)
    action_id = eff = renum = None
    if m:
        action_id, eff, renum = parse_history(m.group(1))
    d["effective_date"] = eff
    d["source_version"] = (f"{action_id}, effective {eff}" if action_id and eff
                           else action_id)
    d["renumbered_from"] = renum
    ch = doc_id.split("-")[1]
    org = registry_by_chapter.get(ch)
    if org is None:
        raise SystemExit(f"{doc_id}: chapter {ch} not in the agency registry — run "
                         "catalog_agencies.py --refresh first")
    d["agency"] = org["slug"]
    d["issuing_body"] = org["name"]
    return d


def load_registry_by_chapter():
    cat = yaml.safe_load((REPO_ROOT / "_meta/catalog/agencies.yml").read_text())
    return {o["oar_chapter"]: o for o in cat["organizations"] if o.get("oar_chapter")}


def _yaml_list_block(key: str, values: list) -> str:
    if not values:
        return f"{key}: []"
    return f"{key}:\n" + "\n".join(f'  - "{v}"' for v in values)


def apply(path: Path, d: dict) -> bool:
    """Rewrite one rule file's frontmatter to match the derived values (targeted
    line edits, preserving the file's formatting). Returns True if changed."""
    text = orig = path.read_text()

    text = re.sub(r"^legal_authority:(?:\s*\[\]|(?:\n  (?:-|\[\]).*)+)",
                  _yaml_list_block("legal_authority", d["legal_authority"]),
                  text, count=1, flags=re.M)
    if "statutes_implemented:" in text:
        text = re.sub(r"^statutes_implemented:(?:\s*\[\]|(?:\n  (?:-|\[\]).*)+)",
                      _yaml_list_block("statutes_implemented", d["statutes_implemented"]),
                      text, count=1, flags=re.M)
    elif d["statutes_implemented"]:
        text = re.sub(r"(^legal_authority:(?:\s*\[\]|(?:\n  .*)+))",
                      r"\1\n" + _yaml_list_block("statutes_implemented",
                                                 d["statutes_implemented"]),
                      text, count=1, flags=re.M)
    if d["effective_date"]:
        text = re.sub(r'^effective_date: .*$', f'effective_date: "{d["effective_date"]}"',
                      text, count=1, flags=re.M)
    if d["source_version"]:
        text = re.sub(r'^source_version: .*$', f'source_version: "{d["source_version"]}"',
                      text, count=1, flags=re.M)
    text = re.sub(r'^agency: .*$', f'agency: {d["agency"]}', text, count=1, flags=re.M)
    text = re.sub(r'^issuing_body: .*$', f'issuing_body: "{d["issuing_body"]}"',
                  text, count=1, flags=re.M)
    if d["renumbered_from"]:
        sup = f'OAR {d["renumbered_from"]}'
        if f'"{sup}"' not in text:
            text = re.sub(r'^  supersedes: \[\]$', f'  supersedes:\n    - "{sup}"',
                          text, count=1, flags=re.M)
    if text != orig:
        path.write_text(text)
        return True
    return False


def expected_mismatch(fm: dict, d: dict) -> list:
    """Field names where current frontmatter differs from the derived values."""
    bad = []
    if (fm.get("legal_authority") or []) != d["legal_authority"]:
        bad.append("legal_authority")
    if (fm.get("statutes_implemented") or []) != d["statutes_implemented"]:
        bad.append("statutes_implemented")
    if d["effective_date"] and str(fm.get("effective_date") or "") != d["effective_date"]:
        bad.append("effective_date")
    if fm.get("agency") != d["agency"]:
        bad.append("agency")
    return bad


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check = "--check" in sys.argv
    registry = load_registry_by_chapter()

    targets = []
    for p in content_files():
        if p.stem.startswith("oar-") and (not args or p.stem in args):
            targets.append(p)

    changed = drift = 0
    for p in targets:
        fm, body = parse_frontmatter(p)
        d = derive(body, fm["id"], registry)
        if check:
            bad = expected_mismatch(fm, d)
            if bad:
                print(f"DRIFT  {p.relative_to(REPO_ROOT)}: {', '.join(bad)}")
                drift += 1
        else:
            if apply(p, d):
                changed += 1
    if check:
        if drift:
            print(f"FAILED: {drift} rule(s) drifted from their own body's structured "
                  "lines — run: python3 src/enrich_oar.py")
            sys.exit(1)
        print(f"OK: {len(targets)} rule(s) match their own structured lines.")
    else:
        print(f"enriched {changed} of {len(targets)} rule file(s)")


if __name__ == "__main__":
    main()
