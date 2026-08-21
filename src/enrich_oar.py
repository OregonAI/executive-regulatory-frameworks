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
  issuing_body          <- that org's OAR NAME (`oar_name`), the name the rules index
                           gives the body — an OAR-derived join, from an OAR chapter to
                           the body that holds it, so it matches on the OAR name and not
                           on `name`, which ADR 0003 promotes to the statutory name

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
REPEAL_RE = re.compile(r"\brepeal", re.I)
# RCW is Washington's code. It appears in the Gorge Commission's rules alongside ORS and
# survived the bug only because it does not start with a digit; naming it explicitly
# makes that correctness deliberate rather than accidental, and lets a bare section
# following it inherit RCW instead of the list's opening family.
CITE_FAMILY_RE = re.compile(
    r"^(ORS|OAR|OL|USC|CFR|RCW|Or Laws|Oregon Laws|Ch\.?|Chapter|Sec\.?|Section)\b", re.I)
# A year-led session-law or bill citation ("2013 HB 2633", "2010 OL Ch. 30") starts with a
# digit like a bare continuation number would, but is a citation in its own right — never
# ORS-prefixed, and doesn't change what family a later bare digit continues.
SESSION_OR_BILL_RE = re.compile(r"^\d{4}\s+(OL|Oregon Laws|c\.|HB|SB)\b", re.I)
# A bare "42 CFR 441.505" / "45 USC 1234" starts with a digit too, but is its own family.
# THE PERIODS MATTER. This first accepted only unpunctuated "CFR"/"USC", so the form
# Oregon actually publishes — "16 U.S.C. § 544c(b)" — fell through to the bare-digit
# rule below and inherited the list's leading "ORS", producing "ORS 16 U.S.C. § 544c(b)"
# on 272 documents. Oregon Revised Statutes and the United States Code are different
# bodies of law; that citation cannot exist. It came from OAR chapter 350, the Columbia
# River Gorge Commission, whose rules cite Oregon, Washington and federal law in one
# list precisely because the compact is bi-state.
CFR_USC_BARE_RE = re.compile(r"^\d+(\.\d+)?\s+(C\.?\s?F\.?\s?R|U\.?\s?S\.?\s?C)\.?(?=\s|$|\W)", re.I)
# A bare parenthetical ("(4)", "(1)(yy)") split off by the '&'/',' splitter is a subsection
# continuation of the PREVIOUS citation, not a new one.
CONTINUATION_RE = re.compile(r"^\(")


def parse_citation_list(text: str) -> list:
    """'ORS 184.340, 278.405 & 655.520' -> ['ORS 184.340','ORS 278.405','ORS 655.520'].
    Ranges ('ORS 655.505 - 655.555') and non-standard cites kept as printed.

    Splitting a compound citation on ','/'&' can strand fragments that aren't citations on
    their own: a bare subsection continuation ('& (4)'), a session-law/bill year+id that
    happens to start with a digit ('2013 HB 2633'), or a bare CFR/USC cite. Each is handled
    below rather than falling through to the bare-digit ORS/OAR re-prefix rule, which would
    otherwise fabricate a citation family the source text never asserted (e.g. 'ORS 723' for
    what the source actually means as 'Ch. 723', or 'ORS 2013 HB 2633')."""
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
        if CONTINUATION_RE.match(p) and out:
            out[-1] = f"{out[-1]} & {p}"
            continue
        m = CITE_FAMILY_RE.match(p)
        if m:
            # "Ch"/"Sec" match without their optional period (a word boundary sits right
            # after the letters, before "."), so normalize for a consistent later prefix
            family = m.group(1).rstrip(".")
            if family in ("Ch", "Sec"):
                family += "."
            out.append(p)
        elif SESSION_OR_BILL_RE.match(p) or CFR_USC_BARE_RE.match(p):
            out.append(p)  # own family; doesn't inherit or set `family`
        elif re.match(r"^\d", p) and family:
            out.append(f"{family} {p}")
        else:
            out.append(p)  # keep verbatim ("Chapter 690 Oregon Laws 1983", etc.)
    # merge an "OL <year>" immediately followed by "Ch./Chapter <n>" into one citation
    # (the source usually means "chapter N, Oregon Laws <year>" split across '&'/',')
    merged = []
    for p in out:
        if (merged and re.match(r"^(OL|Oregon Laws)\s+\d{4}$", merged[-1], re.I)
                and re.match(r"^(Ch\.?|Chapter)\s+\d", p, re.I)):
            merged[-1] = f"{merged[-1]} {p}"
        else:
            merged.append(p)
    return merged


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
    """(newest_action_id, newest_effective_iso, renumbered_from, repealed) from a History
    line. Actions run newest-first; each starts with an id like 'DAS 2-2026'. `repealed`
    reflects ONLY the newest action — an older action mentioning "repealed by ... enacted
    in lieu of" must not mark a rule that was later re-adopted as currently repealed."""
    ids = list(ACTION_ID_RE.finditer(hist))
    if not ids:
        return (None, parse_effective(hist),
                (RENUM_RE.search(hist).group(1) if RENUM_RE.search(hist) else None),
                bool(REPEAL_RE.search(hist)))
    first = ids[0]
    end = ids[1].start() if len(ids) > 1 else len(hist)
    newest = hist[first.start():end]
    renum = RENUM_RE.search(newest)
    return (first.group(1), parse_effective(newest), (renum.group(1) if renum else None),
            bool(REPEAL_RE.search(newest)))


def derive(body: str, doc_id: str, registry_by_chapter: dict) -> dict:
    """All derivable frontmatter values for one rule, from its own body text."""
    d = {}
    m = AUTH_RE.search(body)
    d["legal_authority"] = parse_citation_list(m.group(1)) if m else []
    m = IMPL_RE.search(body)
    d["statutes_implemented"] = parse_citation_list(m.group(1)) if m else []
    m = HIST_RE.search(body)
    action_id = eff = renum = None
    repealed = False
    if m:
        action_id, eff, renum, repealed = parse_history(m.group(1))
    d["effective_date"] = eff
    d["source_version"] = (f"{action_id}, effective {eff}" if action_id and eff
                           else action_id)
    d["renumbered_from"] = renum
    d["status"] = "repealed" if repealed else "current"
    ch = doc_id.split("-")[1]
    org = registry_by_chapter.get(ch)
    if org is None:
        raise SystemExit(f"{doc_id}: chapter {ch} not in the agency registry — run "
                         "catalog_agencies.py --refresh first")
    d["agency"] = org["slug"]
    # NAME READER — JOIN (OAR-derived). THE MOST CONSEQUENTIAL NAME READ IN THIS REPOSITORY:
    # it stamps a registry string into 36,953 rule documents' frontmatter. The document says
    # who issued the rule, the rule reached this body through its OAR chapter, and the name
    # every one of those documents carries today is the rules index's title — so the field
    # read here is `oar_name` (CONTEXT.md, *OAR name*: "the string OAR-derived joins must
    # match"). Reading `name` instead would leave newly enriched documents carrying a
    # statutory issuing body while 36,953 existing ones carry the OAR title, with nothing
    # reporting the split; `expected_mismatch` below now compares the field, so a split that
    # does happen is reported by --check rather than discovered later.
    if not org.get("oar_name"):
        raise SystemExit(f"{doc_id}: registry row {org.get('slug')!r} carries no oar_name — "
                         "the issuing body cannot be stamped from a name no row states; run "
                         "catalog_agencies.py --check")
    d["issuing_body"] = org["oar_name"]
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
    text = re.sub(r'^status: .*$', f'status: {d["status"]}', text, count=1, flags=re.M)
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
    # THE ISSUING BODY, COMPARED RATHER THAN ASSUMED. This field was written by `apply()`
    # and checked by nothing, so a document whose issuing body had drifted from the registry
    # read exactly like one that agreed with it. It matters now because ADR 0003 splits the
    # two names apart: `name` becomes the statutory name while `oar_name` keeps the string
    # these 36,953 documents hold, and the only way "nothing changed" is a measurement
    # rather than an assumption is if the disagreement is reported. Measured across the
    # whole corpus when this comparison landed: 0 of 36,953 documents disagree.
    if fm.get("issuing_body") != d["issuing_body"]:
        bad.append("issuing_body")
    if fm.get("status") != d["status"]:
        bad.append("status")
    return bad


# ------------------------------------------------------------------------------ selftest
#
# THE PROOF THAT THE ENRICHER STAMPS THE OAR NAME, and the reason it is a synthetic fixture
# rather than a row from the committed registry: `name` and `oar_name` hold the same bytes
# on all 189 rows today, so a fixture taken from committed data passes whichever field the
# code reads. The fixture below is FAULT-INJECTED in the sense ADR 0003 makes real — `name`
# already moved to the statutory name, `oar_name` left where the rules index put it — which
# is the only state in which the two readings can be told apart.


def _fixture_registry():
    """One chapter, with the two names holding what ADR 0003 makes them hold. The statutory
    name here is the one ORS 184.305 gives the department; the OAR name is what the rules
    index prints as chapter 125's title (CONTEXT.md, *Statutory name* / *OAR name*)."""
    return {"125": {"slug": "department-of-administrative-services",
                    "name": "Oregon Department of Administrative Services",
                    "oar_name": "Department of Administrative Services"}}


_FIXTURE_BODY = """## Full text

Some rule text.

Statutory/Other Authority: ORS 184.340
Statutes/Other Implemented: ORS 279A.050
History: DAS 2-2026, effective 05/01/2026
"""


def selftest() -> int:
    bad = 0

    def check(name, cond):
        nonlocal bad
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            bad += 1

    reg = _fixture_registry()
    d = derive(_FIXTURE_BODY, "oar-125-010-0005", reg)
    # THE FIELD THE DOCUMENT CARRIES. `issuing_body` is stamped into 36,953 rule documents,
    # and the rules index's title is what every one of them holds today — so the enricher
    # reads the field that holds that string and keeps holding it after ADR 0003 promotes
    # `name`. Both halves are asserted: reading `name` would pass an equality test against
    # the OAR name on every committed row, and only the inequality catches it.
    check("issuing_body is the OAR name", d["issuing_body"] == reg["125"]["oar_name"])
    check("issuing_body is not the statutory name", d["issuing_body"] != reg["125"]["name"])
    check("agency is the slug", d["agency"] == reg["125"]["slug"])

    # THE DRIFT --check REPORTS. A document whose `issuing_body` disagrees with the registry
    # is the split this ticket exists to make visible: after ADR 0003 promotes `name`, a
    # re-enrichment that quietly restamped every document would be indistinguishable from
    # one that changed nothing unless the comparison is made and printed.
    fm_ok = {"issuing_body": reg["125"]["oar_name"], "agency": reg["125"]["slug"],
             "legal_authority": d["legal_authority"],
             "statutes_implemented": d["statutes_implemented"],
             "effective_date": d["effective_date"], "status": d["status"]}
    check("a document holding the OAR name is not drift",
          "issuing_body" not in expected_mismatch(fm_ok, d))
    check("a document holding the statutory name is drift",
          "issuing_body" in expected_mismatch(dict(fm_ok, issuing_body=reg["125"]["name"]), d))

    # A ROW WITH NO OAR NAME. `catalog_agencies.py --check` requires one on every row, so
    # this state should be unreachable — and if it is ever reached, the enricher must say so
    # rather than stamp a name no source states. Refused loudly, in the same form as a
    # chapter the registry does not carry.
    try:
        derive(_FIXTURE_BODY, "oar-125-010-0005",
               {"125": {"slug": "das", "name": "Oregon Department of Administrative Services"}})
        check("a registry row with no oar_name is refused", False)
    except SystemExit as e:
        check("a registry row with no oar_name is refused", "oar_name" in str(e))

    print(f"selftest {'OK' if not bad else 'FAILED'}")
    return 1 if bad else 0


def main():
    if "--selftest" in sys.argv:
        return selftest()
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
