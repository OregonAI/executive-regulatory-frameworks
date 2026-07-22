#!/usr/bin/env python3
"""Mechanically ingest an agency's published policy PDFs as full-text-first documents.

Generalizes agency-policy intake (agency #2+; DAS was done ad hoc). Driven by a policies
source group under _meta/sources/<slug>-policies.yml. Two phases:

  python3 src/ingest_policies.py <group> --discover   # parse the agency's listing page,
                                                       # write the sources: list (GATE #1:
                                                       # a human reviews the list)
  python3 src/ingest_policies.py <group>               # ingest every source in the group
  python3 src/ingest_policies.py <group> --only doc-10-1-2 [...]   # subset
  python3 src/ingest_policies.py <group> --limit 5     # first N (build/verify)

Per source: fetch the PDF (magic-byte check) -> snapshot _meta/snapshots/<id>.pdf +
pdftotext -layout <id>.txt -> content-hash -> emit a verbatim doc via the policy template,
placed with ingest_lib.output_dir_for. Header fields (title, policy number, effective /
supersedes dates) are transcribed from the PDF's OWN labeled header — never inferred (HC-1).
Idempotent/resumable; a fetch/parse failure is logged and skipped, never fabricated.

Adding agency #3: add a POLICY_PROFILES entry (listing url + link/header regexes + citation
format) and, if its PDFs have running furniture, an AGENCY_FURNITURE entry in ingest_lib.
"""
import argparse
import html
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from ingest_lib import clean_pdf_text, fetch, output_dir_for
from repo_lib import REPO_ROOT, SNAPSHOT_DIR, content_hash, normalize_ws

SOURCES_DIR = REPO_ROOT / "_meta" / "sources"
TODAY = date.today().isoformat()
HANDLE = "@morficflux"


_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}


def iso_date(s: str) -> str | None:
    """'04/14/21' / '4/14/2021' / 'October 28, 2015' -> ISO. None if unparseable (never guessed)."""
    s = (s or "").strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$", s)
    if m:
        mo, d, y = (int(x) for x in m.groups())
        if y < 100:
            y += 2000 if y < 70 else 1900
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    m = re.match(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})\s*$", s)
    if m and m.group(1).lower() in _MONTHS:
        try:
            return date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
        except ValueError:
            return None
    return None


def _sp_pdf_rows(web: str, list_url: str) -> list[dict]:
    """All PDF files (recursively) in a SharePoint document library, via the anonymous
    RenderListDataAsStream API (same technique as detect_changes._fetch_view_rows). Returns
    [{FileLeafRef, FileRef}, ...]."""
    from urllib.parse import quote
    url = (f"https://www.oregon.gov{web}/_api/web/GetList('{quote(list_url)}')/"
           "RenderListDataAsStream")
    vx = ("<View Scope='RecursiveAll'><ViewFields><FieldRef Name='FileLeafRef'/>"
          "<FieldRef Name='FileRef'/></ViewFields><RowLimit>5000</RowLimit></View>")
    body = json.dumps({"parameters": {"__metadata": {"type": "SP.RenderListDataParameters"},
                                      "RenderOptions": 2, "ViewXml": vx}}).encode()
    import urllib.request
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": "Mozilla/5.0 (oregon-policy-repo updater)",
        "Accept": "application/json;odata=verbose",
        "Content-Type": "application/json;odata=verbose"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        rows = json.loads(resp.read()).get("Row", [])
    return [r for r in rows if str(r.get("FileLeafRef", "")).lower().endswith(".pdf")]


def _sp_list_items(web: str, list_url: str, fields: list[str]) -> list[dict]:
    """All items (recursively) of a SharePoint custom LIST (not a document library — no
    FileLeafRef/FileRef file-download shape), via the anonymous RenderListDataAsStream API.
    Requests only `fields` to keep the payload small. Used for lists whose items are metadata
    rows pointing at content elsewhere (e.g. DEQ's Internal Management Directives list, whose
    'Directive' field links to an external records-viewer page, not a downloadable file)."""
    from urllib.parse import quote
    url = (f"https://www.oregon.gov{web}/_api/web/GetList('{quote(list_url)}')/"
           "RenderListDataAsStream")
    field_refs = "".join(f"<FieldRef Name='{f}'/>" for f in fields)
    vx = f"<View Scope='RecursiveAll'><ViewFields>{field_refs}</ViewFields><RowLimit>5000</RowLimit></View>"
    body = json.dumps({"parameters": {"__metadata": {"type": "SP.RenderListDataParameters"},
                                      "RenderOptions": 2, "ViewXml": vx}}).encode()
    import urllib.request
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": "Mozilla/5.0 (oregon-policy-repo updater)",
        "Accept": "application/json;odata=verbose",
        "Content-Type": "application/json;odata=verbose"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read()).get("Row", [])


DEQ_URI_RE = re.compile(r"uri=\s*(\d+)")


def _discover_deq_imd(prof: dict) -> tuple[list, str]:
    """DEQ's 'Internal Management Directives' SharePoint LIST (not a document library): each
    row names a directive and links to an external records-management viewer page
    (ormswd2.synergydcs.com/.../RecordViewer.aspx?uri=NNNNNN) rather than a downloadable file
    — see _fetch_synergy_pdf for how the actual PDF is recovered from that page. Identity is
    the stable numeric 'uri' from the Directive link (survives a title rename); one real
    source-side duplicate exists (two titled rows linking to the same uri) and collapses to a
    single entry, keeping the first title encountered."""
    rows = _sp_list_items("/deq/Get-Involved", "/deq/Get-Involved/Lists/Internal Management Directives",
                          ["Title", "Directive", "Division", "Year_x0020_Issued"])
    seen, sources = set(), []
    for row in rows:
        m = DEQ_URI_RE.search(row.get("Directive") or "")
        if not m:
            continue
        uri = m.group(1)
        if uri in seen:
            continue
        seen.add(uri)
        title = re.sub(r"\s+", " ", row.get("Title") or "").strip()
        div = row.get("Division") or ""
        year = row.get("Year_x0020_Issued") or ""
        # notes carries num|title|division|year_issued — the last two are DEQ-specific extra
        # fields; path-identity unpacking in ingest_one treats them as optional (blank for
        # every other path-identity profile's 2-part notes).
        sources.append({"id": f"deq-imd-{uri}", "url": row["Directive"].replace(" ", ""),
                        "sha256": "TODO", "last_checked": TODAY,
                        "notes": f"{uri}|{title}|{div}|{year}"})
    return sources, ("SharePoint LIST 'Internal Management Directives' at "
                     "/deq/Get-Involved/Lists/Internal Management Directives, queried via "
                     "RenderListDataAsStream. Freshness: re-query and diff the item set.")


def _fetch_synergy_pdf(viewer_url: str) -> bytes:
    """The DEQ records-viewer page (ormswd2.synergydcs.com RecordViewer.aspx) embeds the full
    PDF inline as a base64 JS variable (`var myPdfBase64 = '...'`) for client-side pdf.js
    rendering — no separate document-download endpoint exists. Fetch the page and decode that
    variable to recover the real PDF bytes. Raises ValueError if the page has no such variable
    (e.g. an unexpected page shape) — never fabricates content."""
    import base64
    html = fetch(viewer_url).decode("utf-8", errors="replace")
    m = re.search(r"var myPdfBase64\s*=\s*'([^']+)'", html)
    if not m:
        raise ValueError(f"no embedded PDF found at {viewer_url}")
    return base64.b64decode(m.group(1))


def _omd_header(raw_txt: str):
    """(division, title) from an OMD 'AGP-' policy header: 'ADJUTANT GENERAL PERSONNNEL'
    banner line + a 'SUBJECT: ...' line."""
    m = re.search(r"SUBJECT:\s*(.+)", raw_txt)
    title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    return "Adjutant General Personnel (Oregon Military Department)", title


# ---- per-agency profiles ----
# Each profile knows how to (a) discover its listing and (b) read its PDF header.
POLICY_PROFILES = {
    "department-of-corrections": {
        "agency": "department-of-corrections",
        "listing_url": "https://www.oregon.gov/doc/rules-and-policies/pages/policies.aspx",
        "site_root": "https://www.oregon.gov",
        # PDF links on the listing page
        "link_re": re.compile(r'href="(/doc/rules-and-policies/Documents/[^"]+\.pdf)"', re.I),
        # the doc's own header (page 1)
        "title_re": re.compile(r"Title:\s*(.+?)\s{2,}DOC Policy:", re.I),
        "num_re": re.compile(r"DOC Policy:\s*([\d.]+)", re.I),
        "effective_re": re.compile(r"Effective:\s*([\d/]+)", re.I),
        "supersedes_re": re.compile(r"Supersedes:\s*([\d/]+)", re.I),
        # the sub-banner line after "DEPARTMENT OF CORRECTIONS" is the issuing division
        "division_re": re.compile(r"DEPARTMENT OF CORRECTIONS\s+([A-Z][A-Za-z /&,-]{2,60}?)\s+Title:", re.S),
        "citation": lambda num: f"DOC Policy {num}",
        "id": lambda num: "doc-" + num.replace(".", "-"),
        "issuing_default": "Oregon Department of Corrections",
        "authority_level": "state_policy",
        "tags": ["department-of-corrections", "policy"],
    },
    # OHA Oregon State Hospital: SharePoint document library; each policy is a numbered
    # folder (1.002 …) containing the PDF. Identity from the FileRef path; PDF only for the
    # verbatim body + effective date. DISCONTINUED folders are dropped. Attributed to the OHA
    # parent slug (OSH is not a separate registry org).
    "oregon-health-authority-osh": {
        "agency": "oregon-health-authority",
        "discovery": "sharepoint",
        "identity": "path",
        "sp_lists": [{"web": "/oha/osh", "list_url": "/oha/OSH/Policies"}],
        "fileref_re": re.compile(r"/(\d+\.\d+)\s+([^/]+?)/[^/]+\.pdf$", re.I),
        "exclude_re": re.compile(r"\(DISCONTINUED\)|/Superseded/|/Archive", re.I),
        "effective_re": re.compile(
            r"DATE:\s*([A-Za-z]+\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})", re.I),
        "citation": lambda num: f"OSH Policy {num}",
        "id": lambda num: "oha-osh-" + num.replace(".", "-"),
        "issuing_default": "Oregon State Hospital (Oregon Health Authority)",
        "authority_level": "state_policy",
        "tags": ["oregon-health-authority", "oregon-state-hospital", "policy"],
    },
    # OHA Information Security & Privacy Office (ISPO): the numbered ODHS|OHA shared
    # 090-xxx/100-xxx info-security & privacy policies, sourced from the SharePoint LIST
    # behind /odhs/rules-policy (Lists/policiesguidelines) rather than a document library —
    # the list's own Agency/PolicyNumber/PDF-link columns give clean identity, so (like OSH)
    # we use identity: 'path' and skip prof['discovery'] entirely; the manifest was built by
    # hand from that list's rows (see recon notes in the group file). PDFs are served from
    # sharedsystems.dhsoha.state.or.us, which sends an incomplete TLS chain (missing DigiCert
    # intermediate) — ingest with SSL_CERT_FILE pointed at a bundle that adds that
    # intermediate; this is a legitimate chain completion, not verification bypass.
    "oregon-health-authority-ispo": {
        "agency": "oregon-health-authority",
        "identity": "path",
        "effective_re": re.compile(r"Original date:\s*([\d/]+)", re.I),
        "citation": lambda num: f"ODHS|OHA Policy {num}",
        "id": lambda num: "oha-ispo-" + num,
        "issuing_default": "Oregon Health Authority (Information Security & Privacy Office)",
        "authority_level": "state_policy",
        "tags": ["oregon-health-authority", "information-security", "privacy", "policy"],
    },
    # DHS-only administrative/agency policies from the same /odhs/rules-policy SharePoint
    # LIST, filtered to rows whose Agency column is 'ODHS' (not shared with OHA, not the
    # program Transmittals system — this is a distinct list). identity: 'path'; manifest
    # built by hand from the list (see oregon-health-authority-ispo comment above; same
    # sharedsystems.dhsoha.state.or.us TLS-chain caveat applies).
    "department-of-human-services": {
        "agency": "department-of-human-services",
        "identity": "path",
        "effective_re": re.compile(r"Original date:\s*([\d/]+)", re.I),
        "citation": lambda num: f"ODHS Policy {num}",
        "id": lambda num: "dhs-" + num,
        "issuing_default": "Oregon Department of Human Services",
        "authority_level": "state_policy",
        "tags": ["department-of-human-services", "policy"],
    },
    # OHA Public Health IRB Policy & Procedures Manual + standalone IRB policies: a small
    # static listing (no numbering scheme) at .../InstitutionalReviewBoard/Pages/policy.aspx.
    # identity: 'path'; id/title come from the manifest (title = the page's own link text for
    # each PDF, slugified for id). No discovery function fits (the built-in static-HTML
    # discovery hardcodes DOC's 'doc-' id prefix/numbering) so the manifest was built by hand.
    "oregon-health-authority-irb": {
        "agency": "oregon-health-authority",
        "identity": "path",
        "effective_re": re.compile(r"(?!x)x"),  # these PDFs carry no labeled effective date
        "citation": lambda num: f"OHA Public Health IRB — {num}",
        "id": lambda num: "oha-irb-" + re.sub(r"[^a-z0-9]+", "-", re.sub(r"[&']", "", num.lower())).strip("-"),
        "issuing_default": "Oregon Health Authority (Public Health Institutional Review Board)",
        "authority_level": "state_policy",
        "tags": ["oregon-health-authority", "institutional-review-board", "policy"],
    },
    # Oregon Youth Authority: a static listing whose OWN link text is "NUM  TITLE" for every
    # policy PDF (e.g. "0-2.0    Principles of Conduct"), so discovery needs no PDF header
    # parsing at all (discovery: 'link-list', identity: 'path'). effective_date comes from the
    # per-page footer ("Effective: MM/DD/YYYY"); OYA's "Supersedes:" table lists prior
    # effective dates of the SAME policy number (a revision history), not a distinct
    # predecessor policy the way DOC's does — left null rather than mis-mapped.
    "oregon-youth-authority": {
        "agency": "oregon-youth-authority",
        "discovery": "link-list",
        "identity": "path",
        "listing_url": "https://www.oregon.gov/oya/pages/policies/policy_list.aspx",
        "site_root": "https://www.oregon.gov",
        "link_re": re.compile(r'<a href="(/oya/policies/[^"]+\.pdf)">([^<]+)</a>'),
        "label_re": re.compile(r"^([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\.\d+[A-Za-z]?)\s+(.+)$"),
        "effective_re": re.compile(r"Effective:\s*([\d/]+)"),
        "citation": lambda num: f"OYA Policy {num}",
        "id": lambda num: "oya-" + num.lower().replace(".", "-"),
        "issuing_default": "Oregon Youth Authority",
        "authority_level": "state_policy",
        "tags": ["oregon-youth-authority", "policy"],
    },
    # Oregon Military Department: its "Employee Resources > Policies" page mostly re-links
    # DAS statewide HR policies (header 'STATEWIDE POLICY') and bare forms/attachments — NOT
    # OMD's own body. Its genuinely agency-authored documents carry a distinct header
    # ('OREGON MILITARY DEPARTMENT ... NUMBER: AGP-XX.XXX.XX ... SUBJECT: ...', 'AGP' =
    # Adjutant General Personnel). Manifest hand-built from a header-by-header classification
    # of every /omd/ PDF on the page (2026-07-21): 4 have real AGP-numbered text; 2 more
    # (AGP-99.100.18, AGP-99.100.20) are AGP policies but image-only PDFs with no text layer
    # (HC-1: never OCR — left out, needs future human review), the rest are DAS-owned or forms.
    "oregon-military-department": {
        "agency": "oregon-military-department",
        "num_re": re.compile(r"NUMBER:\s*(AGP-[\d.]+)", re.I),
        "effective_re": re.compile(r"EFFECTIVE DATE:\s*([A-Za-z]+\.?\s+\d{1,2},?\s*\d{4}|[\d/]+)", re.I),
        "header_parser": _omd_header,
        "citation": lambda num: f"OMD Policy {num}",
        "id": lambda num: "omd-" + num.lower().replace(".", "-"),
        "issuing_default": "Oregon Military Department",
        "authority_level": "state_policy",
        "tags": ["oregon-military-department", "policy"],
    },
    # Oregon Watershed Enhancement Board: a tiny "Statutes & Policies" page — only 3 real
    # named policies (a parking-map PDF on the same page is excluded), no numbering scheme,
    # each with its own header layout. identity: 'path' (manifest hand-built); title comes
    # from the manifest notes. Two of the three carry only a blank 'Effective:'/'Approved By:'
    # label with no machine-readable date next to it (the actual date appears to be an image
    # signature-stamp, not text) — effective_re intentionally only matches the one doc that
    # has a real transcribable date; the other two get a null effective_date rather than a
    # guess from the filename.
    "oregon-watershed-enhancement-board": {
        "agency": "oregon-watershed-enhancement-board",
        "identity": "path",
        "effective_re": re.compile(r"EFFECTIVE DATE:\s*([A-Za-z]+\.?\s+\d{1,2},?\s+\d{4})", re.I),
        "citation": lambda num: "OWEB Policy",  # no numbering scheme; num is only an id key
        "id": lambda num: "oweb-" + re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-"),
        "issuing_default": "Oregon Watershed Enhancement Board",
        "authority_level": "state_policy",
        "tags": ["oregon-watershed-enhancement-board", "policy"],
    },
    # Public Utility Commission: a single 30-page governance document (how the Commission
    # runs open meetings, rulemakings, and contested cases), not a numbered series — one
    # manifest entry, identity: 'path'. Its "ORDER NO." field is a per-page stamp/image with
    # no extractable text value and no adoption date appears anywhere in the extracted text,
    # so effective_date is intentionally left unset (no effective_re) rather than guessed.
    "public-utility-commission": {
        "agency": "public-utility-commission",
        "identity": "path",
        "effective_re": re.compile(r"(?!x)x"),  # no machine-readable date in this document
        "citation": lambda num: "PUC Internal Operating Guidelines",
        "id": lambda num: "puc-" + num,
        "issuing_default": "Public Utility Commission of Oregon",
        "authority_level": "state_policy",
        "tags": ["public-utility-commission", "policy", "governance"],
    },
    # DEQ Internal Management Directives: discovered from a SharePoint LIST (not a document
    # library — see _discover_deq_imd); each item's PDF lives behind an external
    # records-management viewer page, recovered via _fetch_synergy_pdf (base64-embedded for
    # client-side pdf.js rendering, no separate download endpoint). identity: 'path'; num is
    # the stable numeric "uri" from the Directive link, division/year_issued come from the
    # list's own fields (not from parsing the PDF — the PDFs' own cover-page dates are
    # inconsistent free text across documents, so day-level effective_date is intentionally
    # left unset; year_issued is recorded as a coarse, explicitly-labeled signal instead).
    "department-of-environmental-quality": {
        "agency": "department-of-environmental-quality",
        "discovery": "deq-imd",
        "identity": "path",
        "fetch": "synergy-viewer",
        "effective_re": re.compile(r"(?!x)x"),  # no reliable machine-readable date across docs
        "citation": lambda num: "DEQ Internal Management Directive",
        "id": lambda num: "deq-imd-" + num,
        "issuing_default": "Oregon Department of Environmental Quality",
        "authority_level": "state_policy",
        "tags": ["department-of-environmental-quality", "policy", "internal-management-directive"],
    },
}


def profile_for(group_data: dict) -> dict:
    slug = group_data["group"].replace("-policies", "")
    prof = POLICY_PROFILES.get(slug)
    if not prof:
        sys.exit(f"no POLICY_PROFILES entry for agency {slug!r} — add one (see module docstring)")
    return prof


# ---- discovery ----
def _discover_static_html(prof: dict) -> tuple[list, str]:
    """DOC-style: scrape PDF <a href> links from a static listing page. Identity comes from
    the PDF header at ingest time (identity: 'header')."""
    html = fetch(prof["listing_url"]).decode("utf-8", errors="replace")
    seen, sources = set(), []
    for href in prof["link_re"].findall(html):
        fname = href.rsplit("/", 1)[-1]
        mnum = re.match(r"(\d+-\d+-\d+)", fname)
        pid = "doc-" + mnum.group(1) if mnum else "doc-" + re.sub(r"\.pdf$", "", fname)
        if pid in seen:
            continue
        seen.add(pid)
        sources.append({"id": pid, "url": prof["site_root"] + href, "sha256": "TODO",
                        "last_checked": TODAY, "notes": fname})
    return sources, (f"Static HTML listing of numbered policy PDFs at {prof['listing_url']}. "
                     "Freshness: re-fetch the page and diff the PDF-link set; re-hash members.")


def _discover_sharepoint(prof: dict) -> tuple[list, str]:
    """SharePoint document-library listing (recursive). Identity is derived from the FileRef
    path (identity: 'path') via prof['fileref_re'] -> (number, title); the PDF is opened only
    for the verbatim body + effective date. prof['exclude_re'] drops folders (e.g. DISCONTINUED)."""
    from urllib.parse import quote
    fref_re, excl = prof["fileref_re"], prof.get("exclude_re")
    # A numbered policy folder often holds the main PDF plus attachments/forms; group
    # candidates by policy id and pick the MAIN policy PDF (not an attachment).
    ATTACH = re.compile(r"attachment|appendix|exhibit|\bform\b|\bflow\s?chart\b|checklist", re.I)
    cand: dict[str, list] = {}
    for lst in prof["sp_lists"]:
        for row in _sp_pdf_rows(lst["web"], lst["list_url"]):
            fref = row["FileRef"]
            if excl and excl.search(fref):
                continue
            m = fref_re.search(fref)
            if not m:
                continue                       # not a numbered policy (loose directive/form)
            num, title = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
            cand.setdefault(prof["id"](num), []).append(
                (num, title, fref, row.get("FileLeafRef", fref.rsplit("/", 1)[-1])))
    sources = []
    for pid, items in cand.items():
        # prefer non-attachment; then the filename that starts with the policy number;
        # then the shortest filename (the bare policy vs a long attachment name).
        def rank(it):
            _num, _t, _fref, leaf = it
            return (bool(ATTACH.search(leaf)), not leaf.startswith(_num), len(leaf))
        num, title, fref, _leaf = sorted(items, key=rank)[0]
        sources.append({"id": pid, "url": "https://www.oregon.gov" + quote(fref),
                        "sha256": "TODO", "last_checked": TODAY, "notes": f"{num}|{title}"})
    return sources, (f"SharePoint document library ({', '.join(l['list_url'] for l in prof['sp_lists'])}), "
                     "queried via RenderListDataAsStream. Freshness: re-query and diff the file set; re-hash members.")


def _discover_link_list(prof: dict) -> tuple[list, str]:
    """Static listing where the anchor text itself is 'NUM  TITLE' (e.g. OYA's
    '<a href=".../0-2.0.pdf">0-2.0    Principles of Conduct</a>') — identity: 'path'; num/title
    come straight from the link, so ingest_one only opens the PDF for the body + effective
    date, no header parsing needed. prof['link_re'] must capture (href, label)."""
    html_text = fetch(prof["listing_url"]).decode("utf-8", errors="replace")
    seen, sources = set(), []
    for href, label in prof["link_re"].findall(html_text):
        label = html.unescape(label).replace("\xa0", " ").replace("​", "")
        m = prof["label_re"].match(label.strip())
        if not m:
            continue
        num, title = m.group(1).strip(), re.sub(r"\s+", " ", m.group(2)).strip()
        pid = prof["id"](num)
        if pid in seen:
            continue
        seen.add(pid)
        sources.append({"id": pid, "url": prof["site_root"] + href, "sha256": "TODO",
                        "last_checked": TODAY, "notes": f"{num}|{title}"})
    return sources, (f"Static HTML listing (link text carries 'NUM TITLE') at "
                     f"{prof['listing_url']}. Freshness: re-fetch and diff the link set.")


def discover(group_path: Path, gd: dict, prof: dict):
    mode = prof.get("discovery")
    if mode == "sharepoint":
        sources, signal = _discover_sharepoint(prof)
    elif mode == "link-list":
        sources, signal = _discover_link_list(prof)
    elif mode == "deq-imd":
        sources, signal = _discover_deq_imd(prof)
    else:
        sources, signal = _discover_static_html(prof)
    gd["sources"] = sources
    gd["kind"] = "content-hash"
    gd["upstream_signal"] = signal
    gd["last_checked"] = TODAY
    group_path.write_text(yaml.safe_dump(gd, sort_keys=False, allow_unicode=True, width=100))
    print(f"discovered {len(sources)} policy PDFs -> {group_path.relative_to(REPO_ROOT)}")


_HDR_LABEL = re.compile(r"^(Applicability|Supersedes|Directives|Attachments|Security Level)\b", re.I)


def doc_header_title(raw_txt: str):
    """(division, title) from a DOC policy header. Handles both layouts: title on the
    'Title:' line, and title centered on separate lines above/below the label (long/
    two-line titles). The division is the banner's second line (e.g. 'Information Systems')."""
    head = re.split(r"\n\s*Effective:", raw_txt, 1)[0]
    lines = head.splitlines()
    bi = next((i for i, l in enumerate(lines) if "DEPARTMENT OF CORRECTIONS" in l.upper()), -1)
    division, title_parts = "", []
    for l in lines[bi + 1:] if bi >= 0 else lines:
        s = re.sub(r"\s+", " ", l).strip()
        if not s:
            continue
        if not division and "DOC Policy:" not in s and not s.lower().startswith("title:"):
            division = s
            continue
        if "Title:" in s or "DOC Policy:" in s:              # label line — may carry title text
            rest = re.sub(r"DOC Policy:.*", "", s)
            rest = re.sub(r".*Title:\s*", "", rest).strip()
            if rest:
                title_parts.append(rest)
            continue
        if _HDR_LABEL.match(s):
            continue
        title_parts.append(s)
    return division, re.sub(r"\s+", " ", " ".join(title_parts)).strip()


# ---- ingest one ----
def doc_markdown(prof, num, title, division, url, sha, effective, supersedes, raw_txt,
                 year_issued=""):
    doc_id = prof["id"](num)
    citation = prof["citation"](num).replace(chr(34), chr(39))  # keep frontmatter YAML valid
    eff_iso = iso_date(effective)
    body, conv = clean_pdf_text(raw_txt, prof["agency"])
    eff_field = f'"{eff_iso}"' if eff_iso else "null"
    # year_issued is a coarse (year-only) date signal from the source listing itself, used only
    # when no day-level effective date was transcribable from the document (never fabricated —
    # labeled as coming from the listing, not parsed from the doc's own text)
    src_ver = (f"Effective {effective}" if effective else
              (f"Year issued: {year_issued} (per the source listing)" if year_issued else ""))
    sup_field = f'"Superseded policy dated {supersedes}"' if supersedes else "null"
    glance = f"{citation} — {title}. {prof['issuing_default']}."
    if eff_iso:
        glance += f" Effective {effective}."
    elif year_issued:
        glance += f" Issued {year_issued}."
    fm = f"""---
id: {doc_id}
title: "{title.replace(chr(34), chr(39))}"
doc_type: policy
citation: "{citation}"
authority_level: {prof['authority_level']}
issuing_body: "{(division or prof['issuing_default']).replace(chr(34), chr(39))}"
agency: {prof['agency']}
legal_authority: []
source_url: "{url}"
source_format: pdf
retrieved: "{TODAY}"
source_sha256: "{sha}"
effective_date: {eff_field}
last_reviewed: null
source_version: "{src_ver}"
status: current
supersedes: {sup_field}
content_mode: verbatim
conversion_notes: "{conv.replace(chr(34), chr(39))}"
last_verified: "{TODAY}"
verified_by: "{HANDLE}"
maintainer: "{HANDLE}"
relationships:
  implements: []
  implemented_by: []
  references_external: []
  related: []
  supersedes: []
tags: {prof['tags']}
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated copy of the
> official text. Verify against the official source: <{url}> (retrieved {TODAY}).

# {title} ({citation})

## At a glance

{glance}

## Full text

{body}

## Provenance & change history

- Source: <{url}> · retrieved {TODAY} · sha256 `{sha}`
- Snapshot: `_meta/snapshots/{doc_id}.pdf`
- See [CHANGELOG](./CHANGELOG.md).
"""
    return doc_id, fm


def ingest_one(prof, src, out_dir) -> dict:
    """Returns {status, id, sha, msg}. status: 'ok' | 'skip' | 'fail'.

    identity 'header' (DOC): number/title/division come from the PDF header.
    identity 'path' (SharePoint): number/title come from the FileRef (stored in src.notes as
    'num|title'); the PDF is opened only for the verbatim body + effective date."""
    url, prov_id = src["url"], src["id"]
    path_identity = prof.get("identity") == "path"
    try:
        raw = _fetch_synergy_pdf(url) if prof.get("fetch") == "synergy-viewer" else fetch(url)
    except Exception as e:
        return {"status": "fail", "id": prov_id, "msg": f"FETCH_FAIL {prov_id}: {e}"}
    if raw[:5] != b"%PDF-":
        return {"status": "skip", "id": prov_id, "msg": f"NOT_PDF {prov_id}"}
    pdf_path = SNAPSHOT_DIR / f"{prov_id}.pdf"
    pdf_path.write_bytes(raw)
    raw_txt = subprocess.run(["pdftotext", "-layout", str(pdf_path), "-"],
                             capture_output=True).stdout.decode("utf-8", errors="replace")
    if len(normalize_ws(raw_txt)) < 200:
        pdf_path.unlink(missing_ok=True)
        return {"status": "skip", "id": prov_id,
                "msg": f"NO_TEXT {prov_id} (image-only/empty; needs OCR/human review)"}

    if path_identity:
        # notes is 'num|title' for most path-identity profiles, or 'num|title|division|
        # year_issued' for DEQ; the extra fields are blank (no-op) everywhere else.
        num, title, division, year_issued = (src["notes"].split("|") + ["", "", "", ""])[:4]
        doc_id = prov_id
    else:
        year_issued = ""
        mnum = prof["num_re"].search(raw_txt)
        if not mnum:
            pdf_path.unlink(missing_ok=True)
            return {"status": "skip", "id": prov_id,
                    "msg": f"NON_POLICY {prov_id} ({src.get('notes','')}) — no policy number "
                           "(attachment/form); dropped from manifest"}
        num = mnum.group(1)
        doc_id = prof["id"](num)
        division, title = prof.get("header_parser", doc_header_title)(raw_txt)
        if not title:
            title = src.get("notes", doc_id)
    me = prof["effective_re"].search(raw_txt)
    effective = me.group(1) if me else ""
    ms = prof["supersedes_re"].search(raw_txt) if prof.get("supersedes_re") else None
    supersedes = ms.group(1) if ms else ""

    if doc_id != prov_id:
        pdf_path.rename(SNAPSHOT_DIR / f"{doc_id}.pdf")
    (SNAPSHOT_DIR / f"{doc_id}.txt").write_text(raw_txt, encoding="utf-8")
    sha = content_hash(raw, "pdf")
    _id, text = doc_markdown(prof, num, title, division, url, sha, effective, supersedes,
                             raw_txt, year_issued)
    (out_dir / f"{doc_id}.md").write_text(text, encoding="utf-8")
    # path-identity manifests are keyed by 'num|title[|division|year_issued]' (read back on any
    # future re-ingest, e.g. --only); preserve that shape rather than a free-text
    # "title (citation)" summary, or a second run would parse the summary itself as num/title
    # and mis-derive doc_id.
    notes = (f"{num}|{title}|{division}|{year_issued}" if path_identity
            else f"{title} ({prof['citation'](num)})")
    return {"status": "ok", "id": doc_id, "sha": sha, "url": url,
            "notes": notes, "msg": f"OK {doc_id} ({prof['citation'](num)})"}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("group", help="source group name, e.g. department-of-corrections-policies")
    ap.add_argument("--discover", action="store_true", help="(re)build the sources: list from the listing page")
    ap.add_argument("--only", nargs="*", help="ingest only these source ids")
    ap.add_argument("--limit", type=int, help="ingest only the first N sources")
    args = ap.parse_args()

    group_path = SOURCES_DIR / f"{args.group}.yml"
    if not group_path.is_file():
        sys.exit(f"no such source group: {group_path}")
    gd = yaml.safe_load(group_path.read_text())
    prof = profile_for(gd)

    if args.discover:
        discover(group_path, gd, prof)
        return

    out_dir = output_dir_for("policy", prof["agency"])
    out_dir.mkdir(parents=True, exist_ok=True)
    sources = gd.get("sources") or []
    if args.only:
        sources = [s for s in sources if s["id"] in set(args.only)]
    if args.limit:
        sources = sources[:args.limit]
    if not sources:
        sys.exit("no sources to ingest (run --discover first?)")

    results = {}
    made = skipped = resumed = 0
    for s in sources:
        # resume: a source with a real hash was already ingested — skip (idempotent reruns)
        if not args.only and s.get("sha256") and s["sha256"] != "TODO":
            resumed += 1
            continue
        res = ingest_one(prof, s, out_dir)
        print(res["msg"])
        results[s["id"]] = res
        if res["status"] == "ok":
            made += 1
        else:
            skipped += 1

    # Write real sha256/id back into the manifest; drop processed non-policy attachments.
    # Sources not processed this run (subset --only/--limit) are left untouched. A transient
    # 'fail' (network/fetch error) is kept as-is (sha256 stays TODO) so the next run retries it
    # — only a content-based 'skip' (image-only/non-policy attachment, a stable fact about the
    # source) is dropped.
    new_sources = []
    for s in gd.get("sources") or []:
        r = results.get(s["id"])
        if r is None or r["status"] == "fail":
            new_sources.append(s)                       # not processed, or a transient failure
        elif r["status"] == "ok":
            new_sources.append({"id": r["id"], "url": r["url"], "sha256": r["sha"],
                                "last_checked": TODAY, "notes": r["notes"]})
        # status skip -> dropped (a stable fact: image-only / not a policy)
    gd["sources"] = new_sources
    gd["last_checked"] = TODAY
    group_path.write_text(yaml.safe_dump(gd, sort_keys=False, allow_unicode=True, width=100))
    print(f"\ndone: {made} ingested, {skipped} dropped/skipped, {resumed} already-done "
          f"(of {len(sources)}); manifest now has {len(new_sources)} sources")


if __name__ == "__main__":
    main()
