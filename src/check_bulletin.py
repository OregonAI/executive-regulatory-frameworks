#!/usr/bin/env python3
"""Oregon Bulletin pilot (#78): read ONE document a month instead of hashing 36k rules.

The Oregon Bulletin is the official monthly digest of rule filings ("first business
day monthly" — _meta/sources/oar.yml's upstream_signal). This script fetches the
CURRENT bulletin and emits `_meta/bulletin-worklist.yml`: every OAR rule number the
bulletin's permanent/temporary/minor-correction filings adopt, amend, repeal,
renumber or suspend, with `in_corpus: true|false` — the re-ingest worklist that
issue #78 calls "the approach worth building".

How the Bulletin is actually published (investigated 2026-08-02, all discovered from
the SoS pages themselves, not guessed):

  1. https://sos.oregon.gov/archives/Pages/default.aspx links "Oregon Bulletin" to
     the OARD app: https://secure.sos.state.or.us/oard/displayBulletins.action —
     an accordion of per-month links `displayBulletin.action?bulltnRsn=<n>`.
  2. A month's bulletin is NOT one PDF. It is an HTML page with two tables:
       "Notices of Proposed Rulemaking"                    (proposals — no rule text
                                                            changed yet; ignored here)
       "Permanent, Temporary, and Statutory Minor
        Correction Filings"                                (the operative changes:
                                                            chapter, agency, filing
                                                            AON, type, caption, and a
                                                            per-filing "View PDF")
  3. Each filing's "View PDF" (`viewReceiptTRIM.action?ptId=<id>`) 302-redirects to
     `https://records.sos.state.or.us/ORSOSCMSearch/Search/RecordViewer.aspx?uri=<id>`
     — a pdf.js viewer page with the filing's PDF EMBEDDED AS BASE64 (`JVBERi…`).
     The `uri` equals the `ptId`, so this script requests the viewer directly.
  4. Inside each filing PDF (pdftotext -layout), the operative lines are anchored at
     column 0: `AMEND: 407-007-0210`, `ADOPT: …`, `REPEAL: …`, also compounds like
     `AMEND & RENUMBER:` and `Temporary` prefixes. Rule numbers ALSO appear in prose
     (need/justification sections cite other agencies' rules), so only the
     action-anchored lines are parsed — a bare NNN-NNN-NNNN elsewhere is a citation,
     not a change.

So "reading one document a month" is really ~1 index page + N filing PDFs (July 2026:
190 filings). Still O(one bulletin), not O(36k rules).

Usage:
  python3 src/check_bulletin.py               # current (latest listed) bulletin
  python3 src/check_bulletin.py --rsn 1741    # a specific bulltnRsn
  python3 src/check_bulletin.py --list        # list available bulletins and exit

Needs `pdftotext` (poppler-utils) on PATH. Failures on individual filings are
reported and tolerated (same philosophy as corpus-detect-changes >= v1.22.0);
a systemic failure (>20% of filings) exits 1.
"""
import argparse
import base64
import html
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from repo_lib import REPO_ROOT

OARD = "https://secure.sos.state.or.us/oard"
VIEWER = "https://records.sos.state.or.us/ORSOSCMSearch/Search/RecordViewer.aspx?uri={}"
UA = {"User-Agent": "executive-regulatory-frameworks bulletin check (github.com/OregonAI)"}
WORKLIST = REPO_ROOT / "_meta" / "bulletin-worklist.yml"

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
MONTH_LINK_RE = re.compile(
    r"displayBulletin\.action[^?']*\?bulltnRsn=(\d+)'[^>]*>([A-Z][a-z]+)&nbsp;&nbsp;(\d{4})")
FILING_TABLE_MARK = "Permanent, Temporary, and Statutory Minor"
ROW_RE = re.compile(r"<tr>\s*(<td.*?)</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
PTID_RE = re.compile(r"viewReceiptTRIM\.action[^?']*\?ptId=(\d+)")
B64_PDF_RE = re.compile(r"(JVBERi[0-9A-Za-z+/=]{100,})")
# Line-anchored action headers inside a filing PDF's text. Compounds ("AMEND &
# RENUMBER") report each verb for the numbers on the line.
ACTION_LINE_RE = re.compile(
    r"^\s*((?:ADOPT|AMEND|REPEAL|RENUMBER|SUSPEND)(?:\s*&\s*"
    r"(?:ADOPT|AMEND|REPEAL|RENUMBER|SUSPEND))*)\s*:\s*(.*)$", re.M)
RULE_NO_RE = re.compile(r"\b(\d{3}-\d{3}-\d{4})\b")


def fetch(url: str, tries: int = 3) -> bytes:
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=90) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 — reported, retried, then surfaced
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def list_bulletins():
    page = fetch(f"{OARD}/displayBulletins.action").decode("utf-8", "replace")
    out = []
    for rsn, month, year in MONTH_LINK_RE.findall(page):
        if month in MONTHS:
            out.append((int(year), MONTHS.index(month) + 1, month, int(rsn)))
    if not out:
        raise SystemExit("ERROR: no bulletin links found on displayBulletins.action — "
                         "the index page format changed; re-investigate before parsing")
    return sorted(out)


def filing_rows(bulletin_html: str):
    """(chapter, agency, aon, filed, type, caption, ptId) per operative filing."""
    idx = bulletin_html.find(FILING_TABLE_MARK)
    if idx < 0:
        raise SystemExit("ERROR: bulletin page lacks the operative-filings table — "
                         "format changed; re-investigate before parsing")
    section = bulletin_html[idx:]
    rows = []
    for row in ROW_RE.findall(section):
        cells = [html.unescape(re.sub(r"<[^>]+>", " ", c)).strip()
                 for c in CELL_RE.findall(row)]
        m = PTID_RE.search(row)
        if m and len(cells) >= 6:
            rows.append((*[re.sub(r"\s+", " ", c) for c in cells[:6]], m.group(1)))
    return rows


def filing_pdf_text(pt_id: str) -> str:
    page = fetch(VIEWER.format(pt_id)).decode("utf-8", "replace")
    m = B64_PDF_RE.search(page)
    if not m:
        raise RuntimeError(f"RecordViewer uri={pt_id}: no embedded base64 PDF")
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(base64.b64decode(m.group(1)))
        f.flush()
        return subprocess.run(["pdftotext", "-layout", f.name, "-"],
                              capture_output=True, text=True, check=True).stdout


def actions_in(text: str):
    """Yield (rule_number, action) from a filing's action-anchored lines only."""
    for verbs, rest in ACTION_LINE_RE.findall(text):
        for verb in re.split(r"\s*&\s*", verbs):
            for num in RULE_NO_RE.findall(rest):
                yield num, verb.lower()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rsn", type=int, help="specific bulltnRsn (default: latest)")
    ap.add_argument("--list", action="store_true", help="list bulletins and exit")
    args = ap.parse_args()

    bulletins = list_bulletins()
    if args.list:
        for year, mnum, month, rsn in bulletins:
            print(f"{year}-{mnum:02d}  {month} {year}  bulltnRsn={rsn}")
        return
    if args.rsn:
        pick = next((b for b in bulletins if b[3] == args.rsn), None)
        if not pick:
            raise SystemExit(f"ERROR: bulltnRsn={args.rsn} not on the index")
    else:
        pick = bulletins[-1]
    year, mnum, month, rsn = pick
    url = f"{OARD}/displayBulletin.action?bulltnRsn={rsn}"
    print(f"bulletin: {month} {year} (bulltnRsn={rsn})")

    rows = filing_rows(fetch(url).decode("utf-8", "replace"))
    print(f"{len(rows)} operative filings (permanent/temporary/minor-correction)")

    in_repo = {p.stem[len("oar-"):] for p in (REPO_ROOT / "rules").rglob("oar-*.md")}
    seen, results, failed = set(), [], []
    for i, (chapter, agency, aon, filed, ftype, caption, pt_id) in enumerate(rows, 1):
        try:
            text = filing_pdf_text(pt_id)
        except Exception as e:  # noqa: BLE001
            failed.append(aon or pt_id)
            print(f"FILING FAILED {aon} (ptId={pt_id}): {e}")
            continue
        parsed = list(actions_in(text))
        for num, action in parsed:
            if (num, action) in seen:
                continue
            seen.add((num, action))
            results.append({"number": num, "action": action,
                            "in_corpus": num in in_repo})
        # `parsed`, not seen-set growth: a filing whose every action duplicates an
        # earlier filing's (same rule corrected twice in a month) parsed fine.
        if not parsed:
            print(f"NOTE: {aon} ({ftype}, ch. {chapter}): no action-anchored rule "
                  f"lines parsed — check the filing by hand: {VIEWER.format(pt_id)}")
        if i % 25 == 0:
            print(f"  …{i}/{len(rows)} filings")
        time.sleep(0.2)

    results.sort(key=lambda r: (r["number"], r["action"]))
    n_in = sum(1 for r in results if r["in_corpus"])
    lines = [
        "# Generated by src/check_bulletin.py — the monthly OAR re-ingest worklist (#78).",
        "# `in_corpus: true` rows are held rules whose text changed upstream this month",
        "# (re-ingest candidates); `false` rows are rules this corpus does not hold.",
        f"bulletin: {month} {year} (bulltnRsn={rsn})",
        f"bulletin_url: {url}",
        f"retrieved: '{date.today().isoformat()}'",
        "rules:",
    ]
    for r in results:
        lines.append(f"- number: {r['number']}")
        lines.append(f"  action: {r['action']}")
        lines.append(f"  in_corpus: {'true' if r['in_corpus'] else 'false'}")
    WORKLIST.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {WORKLIST.relative_to(REPO_ROOT)}: {len(results)} rule action(s) "
          f"from {len(rows) - len(failed)} filing(s); {n_in} affect rules held in "
          f"this corpus; {len(failed)} filing fetch/parse failure(s).")
    if rows and len(failed) / len(rows) > 0.20:
        print(f"SYSTEMIC: {len(failed)}/{len(rows)} filings failed — outage or "
              f"format change, not noise.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
