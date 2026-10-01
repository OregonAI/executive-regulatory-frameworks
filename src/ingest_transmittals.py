#!/usr/bin/env python3
"""Pilot-ingest ODHS Policy Transmittals as `doc_type: transmittal` (issue #79).

The grilling comment on #79 resolves the scope question the issue opened with:
transmittals come in as their own doc_type, full text, behind a pilot allowed to fail.
Scope is **Policy Transmittals only** (Action Requests and Information Memoranda are
explicitly out) from **one ODHS program**, capped at ~25 documents.

This repo holds 17 DHS policies, all Director's Office / agency-wide administrative
policies (public records, bilingual services, equity, donated funds, access to records...).
A 2026-10-01 survey assumed "the program owning the dhs-010-* series" as the pilot target;
verified against ODHS's own site, no such program exists -- `_meta/sources/
department-of-human-services-policies.yml` already records that the 010-series comes from
the agency-wide "policiesguidelines" SharePoint list, filtered to `Agency_x0020_1 == 'ODHS'`
exactly, "not the separate program Transmittals system". ODHS runs Policy Transmittals per
case-service program (APD, CW, ODDS, OEP, SSP, VR -- confirmed from /odhs/transmittals'
own nav and each program's `ListUrl`), each with its own policy/rule numbering (OAR
chapters, Collective Bargaining Agreements, or the program's own prior transmittals) that
is NOT the dhs-0XX-0XX numbering the 17 held policies carry.

Pilot target: **APD** (Aging and People with Disabilities) -- the single largest Policy
Transmittal system (309 of its 1,636 transmittals are type Policy, more than any other
program's Policy-type count except ODDS's 344, and APD's are a SharePoint *document*
library with full PDFs, where ODDS's and others' SharePoint *list* items point to similarly
templated PDFs). Selection rule: the 25 most recent APD Policy-type transmittals by
`Date`, an unbiased recency cut, not picked for topical closeness to the 17 held policies.

Each APD Policy Transmittal is a templated form (`pdftotext -layout`) with its own labeled
"Policy/rule numbers:" field -- the transmittal's OWN verbatim statement of what it
announces. `extract_announces` reads that field and keeps only tokens shaped like this
corpus's dhs-0XX-0XX policy ids (never inferred from the transmittal's topic/subject, which
AGENTS.md's anti-fabrication rule forbids). Measured against the 25-document pilot set:
zero cite a dhs-0XX-0XX number (see CHANGELOG and .out-of-scope/ for the pilot's full
accounting against the issue's bar).

  python3 src/ingest_transmittals.py --discover --program apd --limit 25
        # query the live SharePoint list, print the Policy-type selection (does not write
        # anything -- the pilot's source manifest, _meta/sources/
        # department-of-human-services-transmittals.yml, was hand-assembled from this output)
  python3 src/ingest_transmittals.py --ingest --program apd --limit 25
        # fetch + ingest the 25 most recent APD Policy transmittals
  python3 src/ingest_transmittals.py --selftest
        # prove the Policy/rule-numbers -> announces extraction can both match and fail
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))

from ingest_lib import fetch, output_dir_for
from repo_lib import REPO_ROOT, SNAPSHOT_DIR, content_hash, content_files, normalize_ws, parse_frontmatter

TODAY = date.today().isoformat()
HANDLE = "@morficflux"
AGENCY = "department-of-human-services"
ISSUING_BODY = "Oregon Department of Human Services, Aging and People with Disabilities"

TRANSMITTALS_WEB = "/odhs/transmittals"
PROGRAM_LISTS = {
    # program -> (list_url, kind). "doclib" = SharePoint document library (FileRef is the
    # PDF itself, Transmittal_x0020_type is the Policy/Action/Info field); "list" = a
    # SharePoint custom list whose Transmittal field is a URL pointing at the PDF
    # elsewhere, same as ingest_policies.py's DEQ precedent.
    "apd": ("/odhs/transmittals/APDTransmittals", "doclib"),
}

# A dhs-0XX-0XX style policy number, as it appears bare in a transmittal's own
# "Policy/rule numbers:" field -- the SAME shape used throughout
# _meta/sources/department-of-human-services-policies.yml's `id: dhs-0XX-0XX[-0X]`.
DHS_POLICY_NUM_RE = re.compile(r"\b0\d{2}-0\d{2}(?:-0\d)?\b")

# The structured header a transmittal's OWN text carries (never inferred from the subject
# line or filename). `(?:s)?` and the optional parenthetical cover the two label spellings
# observed on real APD transmittals ("Policy/rule numbers:" vs "Policy/rule number(s):").
POLICY_NUMBERS_RE = re.compile(
    r"Policy/rule\s+numbers?(?:\(s\))?:\s*(.*?)(?:Release\s+number|Effective\s+date|References:|$)",
    re.IGNORECASE | re.DOTALL,
)
EFFECTIVE_DATE_RE = re.compile(
    r"Effective\s+date:[ \t]*(.*?)[ \t]*(?:Expiration\s+date|$)",
    re.IGNORECASE | re.MULTILINE,
)
ISSUE_DATE_RE = re.compile(r"Issue\s+date:\s*([0-9/]+)", re.IGNORECASE)
# Subject often wraps onto a second line (e.g. APD-PT-26-005): keep taking lines until a
# blank line or the next form field ("Transmitting (check the box...)").
SUBJECT_RE = re.compile(r"Subject:\s*(.+(?:\n(?!\s*\n|Transmitting).+)*)")
# Some older APD transmittals (e.g. APD-PT-24-028, 25-014, 25-015) use a "Policy/rule
# title:" field in place of "Subject:" -- same meaning, different label. It also wraps
# onto a second line (24-028); keep taking lines until a blank line or the next form
# field ("Policy/rule number(s):").
POLICY_RULE_TITLE_RE = re.compile(
    r"Policy/rule\s+title:\s*(.+(?:\n(?!\s*\n|\s*Policy/rule\s+number).+)*)",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"Number:\s*(\S+)")
AUTHORIZED_BY_RE = re.compile(r"Authorized by:\s*(.+)")


def known_dhs_policy_ids() -> set[str]:
    """Every dhs-0XX-0XX[-0X] policy id this corpus actually holds -- the ONLY ids
    `extract_announces` is allowed to assert a transmittal announces. Read live from the
    DHS policies directory rather than hardcoded, so a future DHS policy addition/removal
    is picked up without touching this file."""
    out = set()
    policies_dir = REPO_ROOT / "agencies" / AGENCY / "policies"
    if policies_dir.is_dir():
        for p in policies_dir.glob("*.md"):
            if p.name.startswith("_") or p.name == "CHANGELOG.md":
                continue  # _index.md / CHANGELOG.md are not content documents
            fm, _ = parse_frontmatter(p)
            if fm.get("doc_type") == "policy":
                out.add(p.stem)
    return out


def extract_announces(raw_text: str, known_ids: set[str]) -> list[str]:
    """The ids of held DHS policies this transmittal's OWN "Policy/rule numbers:" field
    names -- never the transmittal's topic or subject line (HC-1 / AGENTS.md anti-
    fabrication: a derived link must come from the document's own text, not an inference).

    Returns [] both when the field is blank and when it cites numbers that are not any
    policy this corpus holds (e.g. an OAR chapter, a Collective Bargaining Agreement, or
    another transmittal) -- those are real citations, just not ones this join can resolve."""
    m = POLICY_NUMBERS_RE.search(raw_text)
    if not m:
        return []
    field = m.group(1)
    found = []
    for mnum in DHS_POLICY_NUM_RE.finditer(field):
        doc_id = f"dhs-{mnum.group(0)}"
        if doc_id in known_ids and doc_id not in found:
            found.append(doc_id)
    return found


def parse_apd_transmittal(raw_text: str, known_ids: set[str] | None = None) -> dict:
    """Pure parse of one APD Policy Transmittal's `pdftotext -layout` text into the
    structured fields this ingester needs. Nothing here touches the network or disk --
    the seam `--selftest` exercises directly."""
    known_ids = known_ids if known_ids is not None else known_dhs_policy_ids()

    def _one(rx, text=raw_text):
        m = rx.search(text)
        return normalize_ws(m.group(1)) if m else ""

    number = _one(NUMBER_RE)
    subject = _one(SUBJECT_RE) or _one(POLICY_RULE_TITLE_RE)
    issue_date_raw = _one(ISSUE_DATE_RE)
    effective_date_raw = _one(EFFECTIVE_DATE_RE)
    authorized_by = _one(AUTHORIZED_BY_RE)
    return {
        "number": number,
        "subject": subject,
        "issue_date_raw": issue_date_raw,
        "issue_date_iso": _iso_mdy(issue_date_raw),
        "effective_date_raw": effective_date_raw,
        "effective_date_iso": _iso_mdy(effective_date_raw),
        "authorized_by": authorized_by,
        "announces": extract_announces(raw_text, known_ids),
    }


def _iso_mdy(s: str) -> str | None:
    """'2/19/2026' -> '2026-02-19', or 'January 1, 2026' / 'May 01, 2026' -> the same, via
    the two literal-date shapes real APD transmittals use. None for anything else (e.g.
    'Upon release', 'Immediately', 'Upon Receipt') -- never guessed (HC-1)."""
    s = (s or "").strip()
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        mo, d, y = (int(x) for x in m.groups())
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    try:
        return datetime.strptime(s, "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------------------
# Discovery: the live SharePoint RenderListDataAsStream API, same technique as
# ingest_policies.py's _sp_pdf_rows (ADR 0016's fetch discipline is honored by routing the
# actual PDF fetch through ingest_lib.fetch; this metadata call is a single small JSON
# request per program, not a per-document fetch, and carries its own honest UA).
# ---------------------------------------------------------------------------------------
def _sp_rows(list_url: str, fields: list[str]) -> list[dict]:
    import urllib.request
    url = (f"https://www.oregon.gov{TRANSMITTALS_WEB}/_api/web/GetList(%27"
          f"{quote(list_url, safe='')}%27)/RenderListDataAsStream")
    field_refs = "".join(f"<FieldRef Name='{f}'/>" for f in fields)
    vx = (f"<View Scope='RecursiveAll'><ViewFields>{field_refs}</ViewFields>"
         "<RowLimit>5000</RowLimit></View>")
    body = json.dumps({"parameters": {"__metadata": {"type": "SP.RenderListDataParameters"},
                                      "RenderOptions": 2, "ViewXml": vx}}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": "OregonAI-CivicCorpus (executive-regulatory-frameworks; "
                      "public-records archival; +https://github.com/OregonAI/"
                      "executive-regulatory-frameworks)",
        "Accept": "application/json;odata=verbose",
        "Content-Type": "application/json;odata=verbose"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read()).get("Row", [])


def discover(program: str, policy_only: bool, limit: int | None) -> list[dict]:
    list_url, kind = PROGRAM_LISTS[program]
    if kind != "doclib":
        raise NotImplementedError(f"program {program!r} is not a 'doclib' list")
    rows = _sp_rows(list_url, ["FileLeafRef", "FileRef", "Title", "Transmittal_x0020_type",
                               "Date", "Status", "Subject"])
    if policy_only:
        rows = [r for r in rows if r.get("Transmittal_x0020_type") == "Policy"]

    def _dt(r):
        try:
            return datetime.strptime(r["Date"], "%m/%d/%Y")
        except Exception:
            return datetime.min
    rows.sort(key=_dt, reverse=True)
    return rows[:limit] if limit else rows


def transmittal_doc_id(prof_number: str) -> str:
    """'APD-PT-26-011' -> 'dhs-apd-pt-26-011'. The transmittal's own number already names
    its program (APD/SSP/...), so prefixing the program again would double it."""
    return f"dhs-{prof_number.lower()}"


# LEGAL STATUS - NOT-A-RULE: a Policy Transmittal is an agency change-announcement memo,
# issued and withdrawn by ODHS itself, not filed in the Oregon Bulletin, so ADR 0006's
# one-writer rule for a RULE's legal status does not reach the `status: current` below
# (same reasoning as src/ingest_policies.py's identical marker for DAS policies).
def doc_markdown(prof_number: str, program: str, row: dict, url: str, sha: str,
                 raw_text: str, parsed: dict) -> tuple[str, str]:
    doc_id = transmittal_doc_id(prof_number)
    title = parsed["subject"] or row.get("Subject") or prof_number
    citation = f"ODHS Policy Transmittal {prof_number}"
    eff_iso = parsed["effective_date_iso"]
    eff_field = f'"{eff_iso}"' if eff_iso else "null"
    src_ver = (f"Effective: {parsed['effective_date_raw']}" if parsed["effective_date_raw"]
              else "")
    announces = parsed["announces"]
    announces_yaml = ("[]" if not announces else
                      "\n" + "\n".join(f"  - {a}" for a in announces))
    body = raw_text.strip() + "\n"
    fm = f"""---
schema_version: 1
corpus: "executive-regulatory-frameworks"
jurisdiction: "oregon"
id: {doc_id}
title: "{title.replace(chr(34), chr(39))}"
doc_type: transmittal
citation: "{citation}"
authority_level: agency_guidance
issuing_body: "{ISSUING_BODY}"
agency: {AGENCY}
legal_authority: []
source_url: "{url}"
source_format: pdf
retrieved: "{TODAY}"
source_sha256: "{sha}"
effective_date: {eff_field}
last_reviewed: null
source_version: "{src_ver}"
status: current
supersedes: null
content_mode: verbatim
conversion_notes: ""
last_verified: ""
verified_by: ""
maintainer: "{HANDLE}"
announces: {announces_yaml}
relationships:
  implements: []
  implemented_by: []
  references_external: []
  related: []
  supersedes: []
tags: ['department-of-human-services', 'transmittal', '{program}']
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated copy of the
> official text. Verify against the official source: <{url}> (retrieved {TODAY}).

# {title} ({prof_number})

## At a glance

{citation} — {title}. {ISSUING_BODY}.{(" Effective " + parsed['effective_date_raw'] + ".") if parsed['effective_date_raw'] else ""}

## Full text

{body}

## Provenance & change history

- Source: <{url}> · retrieved {TODAY} · sha256 `{sha}`
- Snapshot: `_meta/snapshots/{doc_id}.pdf`
- `announces`: {announces if announces else "none (this transmittal's own \"Policy/rule numbers\" field does not cite a DHS policy this corpus holds)"}
- See [CHANGELOG](../../../CHANGELOG.md).
"""
    return doc_id, fm


def ingest_one(program: str, row: dict, known_ids: set[str]) -> dict:
    fref = row["FileRef"]
    url = f"https://www.oregon.gov{fref}"
    prov_id = row["Title"]
    try:
        raw = fetch(url)
    except Exception as e:
        return {"status": "fail", "id": prov_id, "msg": f"FETCH_FAIL {prov_id}: {e}"}
    if raw[:5] != b"%PDF-":
        return {"status": "skip", "id": prov_id, "msg": f"NOT_PDF {prov_id}"}
    doc_id = transmittal_doc_id(prov_id)
    pdf_path = SNAPSHOT_DIR / f"{doc_id}.pdf"
    pdf_path.write_bytes(raw)
    raw_text = subprocess.run(["pdftotext", "-layout", str(pdf_path), "-"],
                              capture_output=True).stdout.decode("utf-8", errors="replace")
    if len(normalize_ws(raw_text)) < 200:
        pdf_path.unlink(missing_ok=True)
        return {"status": "skip", "id": prov_id, "msg": f"NO_TEXT {prov_id}"}
    (SNAPSHOT_DIR / f"{doc_id}.txt").write_text(raw_text, encoding="utf-8")
    sha = content_hash(raw, "pdf")
    parsed = parse_apd_transmittal(raw_text, known_ids)
    out_dir = output_dir_for("transmittal", AGENCY)
    out_dir.mkdir(parents=True, exist_ok=True)
    _id, text = doc_markdown(prov_id, program, row, url, sha, raw_text, parsed)
    (out_dir / f"{doc_id}.md").write_text(text, encoding="utf-8")
    return {"status": "ok", "id": doc_id, "sha": sha, "url": url, "announces": parsed["announces"],
            "msg": f"OK {doc_id} (announces={parsed['announces']})"}


def _selftest() -> int:
    """`extract_announces`/`_iso_mdy` must be able to both MATCH and FAIL -- a rule that
    always answers the same way is not a check (AGENTS.md)."""
    known = {"dhs-010-010", "dhs-010-031-01"}
    fails = []

    def check(name, cond):
        print(("PASS " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # 1. A transmittal that cites a held DHS policy number verbatim -> resolves.
    text_match = (
        "Policy Transmittal\n\nNumber: APD-PT-26-900\nIssue date: 2/19/2026\n"
        "Subject: Records requests from federal agencies\n\n"
        "Policy/rule numbers: 010-031-01                   Release number:\n"
        "Effective date: Upon release                       Expiration date:\n"
    )
    check("cites a held DHS policy number -> announces resolves it",
         extract_announces(text_match, known) == ["dhs-010-031-01"])

    # 2. The real, measured shape: an OAR citation only -> resolves to nothing (not
    # fabricated as a DHS-policy link just because a number is present).
    text_oar_only = (
        "Policy Transmittal\n\nNumber: APD-PT-26-003\nIssue date: 2/19/2026\n"
        "Policy/rule numbers: OAR 411-015-0030                Release number:\n"
    )
    check("an OAR-only citation -> announces stays empty (not fabricated)",
         extract_announces(text_oar_only, known) == [])

    # 3. A blank field -> empty, not a crash.
    text_blank = "Policy Transmittal\n\nPolicy/rule numbers:\nRelease number:\n"
    check("a blank Policy/rule numbers field -> announces is []",
         extract_announces(text_blank, known) == [])

    # 4. _iso_mdy: a literal date resolves; a non-date phrase (as real transmittals carry)
    # must come back None, never guessed.
    check("'2/19/2026' -> ISO", _iso_mdy("2/19/2026") == "2026-02-19")
    check("'Upon release' -> None (never guessed)", _iso_mdy("Upon release") is None)
    check("'Immediately' -> None (never guessed)", _iso_mdy("Immediately") is None)
    check("'Upon Receipt' -> None (never guessed)", _iso_mdy("Upon Receipt") is None)
    check("'January 1, 2026' -> ISO", _iso_mdy("January 1, 2026") == "2026-01-01")
    check("'May 01, 2026' -> ISO", _iso_mdy("May 01, 2026") == "2026-05-01")

    # 5. Full-template parse end to end.
    parsed = parse_apd_transmittal(text_match, known)
    check("parse_apd_transmittal reads Number/Subject/announces together",
         parsed["number"] == "APD-PT-26-900"
         and parsed["subject"] == "Records requests from federal agencies"
         and parsed["announces"] == ["dhs-010-031-01"])

    # 6. The real, measured shape: "Effective date:" and "Expiration date:" on SEPARATE
    # lines (most committed snapshots, e.g. 25-016 through 26-009) -- EFFECTIVE_DATE_RE
    # must still capture the value without crossing into other fields, and a literal
    # 'Month D, YYYY' value on its own line must come back ISO via _iso_mdy.
    text_separate_lines = (
        "Policy Transmittal\n\nNumber: APD-PT-26-006\nIssue date: 4/01/2026\n"
        "Subject: Something\n\n"
        "Policy/rule numbers:\nRelease number:\n"
        "Effective date: May 01, 2026\n"
        "Expiration date:\n"
        "References:\n"
    )
    parsed_sep = parse_apd_transmittal(text_separate_lines, known)
    check("'Effective date' / 'Expiration date' on separate lines -> captured, not empty",
         parsed_sep["effective_date_raw"] == "May 01, 2026"
         and parsed_sep["effective_date_iso"] == "2026-05-01")

    # 7. An M/D/YYYY effective date on its own line (e.g. 25-024's '10/01/2025') must also
    # resolve, not just the same-line case.
    text_mdy_own_line = (
        "Policy Transmittal\n\nNumber: APD-PT-25-024\n"
        "Effective date: 10/01/2025\n"
        "Expiration date: N/A\n"
    )
    parsed_mdy = parse_apd_transmittal(text_mdy_own_line, known)
    check("M/D/YYYY effective date on its own line -> ISO",
         parsed_mdy["effective_date_iso"] == "2025-10-01")

    # 8. A subject that wraps onto a second line (e.g. APD-PT-26-005's real subject) must
    # be captured in full, not truncated at the line break.
    text_wrapped_subject = (
        "Policy Transmittal\n\n"
        "Subject: Homecare Worker, Personal Support Worker and Personal Care Attendant Rural\n"
        "Mileage\n\n"
        "Transmitting (check the box that best applies)\n"
    )
    parsed_wrap = parse_apd_transmittal(text_wrapped_subject, known)
    check("a subject wrapped onto a second line is captured in full, not truncated",
         parsed_wrap["subject"] == "Homecare Worker, Personal Support Worker and "
         "Personal Care Attendant Rural Mileage")

    # 9. Older APD transmittals (e.g. APD-PT-24-028) use "Policy/rule title:" in place of
    # "Subject:" -- must still resolve a real subject, not fall through to the bare
    # transmittal number. The real 24-028 case also wraps onto a second line.
    text_policy_rule_title = (
        "Policy Transmittal\n\n Number: APD-PT-24-028\n\n"
        " Policy/rule title:       APS Screening Decisions: Documentation and Notification to\n"
        "                          Reporters\n"
        " Policy/rule number(s):   OAR Chapter 411, Division 020,     Release number:\n"
        "                          Adult Protective Services\n"
    )
    parsed_prt = parse_apd_transmittal(text_policy_rule_title, known)
    check("'Policy/rule title:' (no 'Subject:' field) resolves the real subject, wrapped line included",
         parsed_prt["subject"] == "APS Screening Decisions: Documentation and "
         "Notification to Reporters")

    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--program", default="apd", choices=sorted(PROGRAM_LISTS))
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    if args.selftest:
        sys.exit(_selftest())

    # Policy-only is the issue's fixed scope (Action Requests / Information Memoranda are
    # explicitly out) -- not a flag, so there is nothing to toggle off.
    if args.discover:
        rows = discover(args.program, True, args.limit)
        print(f"{len(rows)} {args.program.upper()} Policy transmittal(s) selected "
             f"(most-recent-first cut, limit={args.limit}):")
        for r in rows:
            print(f"  {r['Title']}\t{r['Date']}\t{r.get('Subject', '')}")
        return

    if args.ingest:
        known_ids = known_dhs_policy_ids()
        rows = discover(args.program, True, args.limit)
        results = [ingest_one(args.program, r, known_ids) for r in rows]
        ok = [r for r in results if r["status"] == "ok"]
        resolved = [r for r in ok if r["announces"]]
        for r in results:
            print(r["msg"])
        print(f"\n{len(ok)}/{len(results)} ingested; {len(resolved)}/{len(ok)} announce "
             "a DHS policy this corpus holds.")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
