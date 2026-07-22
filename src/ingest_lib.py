"""Ingestion/refresh machinery shared by intake batches and the check-updates skill.
HC-1: everything written into '## Full text' comes from the fetched snapshot text —
never from model knowledge. Effective/version dates are NEVER updated automatically;
a changed source gets a TODO marker for human transcription."""
import re
import subprocess
import urllib.request
from collections import Counter
from pathlib import Path

from repo_lib import (DIR_DOC_TYPE, JURISDICTION_WIDE_DIRS, REPO_ROOT, SNAPSHOT_DIR,
                      content_hash, normalize_ws, parse_frontmatter, snapshot_slice)

USER_AGENT = "Mozilla/5.0 (oregon-policy-repo updater; +https://github.com/morficflux/oregon-policy-repo)"

FURN_RE = re.compile(
    r"(Page[s]? \d+ of \d+\s*$)|(^Level 1, Published)|(^\.\d+ OF \.\d+$)|"
    r"(^Policy No: .*)|(^Statewide Procedure No: .*)|(^OAM \d\d\.\d\d\.\d\d.{0,40}$)|"
    r"(^Policy: \d.*Effective)")
FURN_HINTS = ("page", "oregon accounting manual", "policy no", "statewide policy",
              "level 1, published", "effective:", "reviewed:")

# Per-agency page-furniture patterns (BACKLOG: data, not one ever-growing regex). Each
# agency's PDFs have their own running header/footer; the shared FURN_RE handles DAS/OAM.
# A running footer whose page number varies per page ("Effective: 04/14/21  Page 3") is
# NOT caught by the repeated-identical-line rule below, so agencies with that style need
# an explicit pattern here. Keyed by registry slug.
AGENCY_FURNITURE = {
    "department-of-corrections": [
        re.compile(r"^Effective:\s*[\d/]+\s+Page\s+\d+"),   # per-page footer
    ],
    # ODHS|OHA shared "Operational Policy" template (OSH, ISPO, DHS agency policies):
    # per-page footer "Page N of M          <policy code> (mm/yy)" — the shared FURN_RE's
    # 'Page N of M' pattern requires end-of-line, but this template appends a trailing
    # policy-number/date, so it needs its own pattern.
    "oregon-health-authority": [
        re.compile(r"^Page\s+\d+\s+of\s+\d+\b"),
    ],
    "department-of-human-services": [
        re.compile(r"^Page\s+\d+\s+of\s+\d+\b"),
    ],
}


def clean_pdf_text(raw: str, agency: str | None = None):
    """Strip page furniture from pdftotext output. Returns (text, conversion_notes).
    `agency` (registry slug) adds that agency's furniture patterns to the shared ones."""
    extra = AGENCY_FURNITURE.get(agency or "", ())
    lines = raw.replace("\f", "\n").splitlines()
    counts = Counter(normalize_ws(l) for l in lines if normalize_ws(l))
    stripped = Counter()
    out = []
    for l in lines:
        nl = normalize_ws(l)
        low = nl.lower()
        if nl and len(nl) < 140 and (FURN_RE.search(nl) or any(p.search(nl) for p in extra)):
            stripped[re.sub(r"\d+", "N", nl)[:55]] += 1
            continue
        if nl and counts[nl] >= 3 and len(nl) < 130 and any(h in low for h in FURN_HINTS):
            stripped[nl[:55]] += 1
            continue
        if re.fullmatch(r"\d{1,3}", nl) and counts[nl] >= 2:
            stripped["(bare page numbers)"] += 1
            continue
        out.append(l.rstrip())
    res, blank = [], 0
    for l in out:
        if not l.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        res.append(l)
    notes = "; ".join(f"stripped page line '{k}' x{v}" for k, v in stripped.most_common(4))
    return "\n".join(res).strip("\n"), (notes or "no page furniture detected")


def flow_to_lines(norm_text: str) -> str:
    """Break a whitespace-collapsed slice at subsection markers (whitespace-only change)."""
    t = re.sub(r" (?=\(\d{1,2}\) )", "\n\n", norm_text)
    t = re.sub(r" (?=History: )", "\n\n", t)
    t = re.sub(r" (?=Statutory/Other Authority)", "\n\n", t)
    return t


def output_dir_for(doc_type: str, agency: str | None = None) -> Path:
    """The one correct directory for a new document of this doc_type — the single
    place ingestion code should derive a target path from, instead of hand-typing
    'agencies/<slug>/policies' (or similar) and risking the procedures/policies mixup
    this function exists to prevent. Mirrors DIR_DOC_TYPE / validate_frontmatter.py's
    CI-enforced check, so a mistake here would be caught even without this helper —
    but using it means new code is correct by construction."""
    body_dir = next((d for d, dt in DIR_DOC_TYPE.items() if dt == doc_type), None)
    if body_dir is None:
        raise ValueError(f"no known directory for doc_type {doc_type!r}")
    if body_dir in JURISDICTION_WIDE_DIRS:
        return REPO_ROOT / body_dir
    if not agency:
        raise ValueError(f"doc_type {doc_type!r} is agency-scoped; pass agency=")
    return REPO_ROOT / "agencies" / agency / body_dir


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def build_fulltext(fm: dict) -> tuple:
    """(full text, conversion notes) for a doc from its committed snapshot. None if no text."""
    doc_id = fm["id"]
    snap_id = fm.get("snapshot_id") or doc_id
    txt_path = SNAPSHOT_DIR / f"{snap_id}.txt"
    if not txt_path.is_file():
        return None, None
    raw = txt_path.read_text(encoding="utf-8", errors="replace")
    if len(normalize_ws(raw)) < 200:
        return None, None
    sl = snapshot_slice(doc_id, snap_id, raw)
    if doc_id.startswith(("ors-", "oar-")):
        return flow_to_lines(sl), ("sliced the document's own text out of the shared snapshot; "
                                   "line breaks inserted at subsection markers (whitespace-only)")
    if snap_id != doc_id:
        text, notes = clean_pdf_text(sl, fm.get("agency"))
        return text, f"slice of the shared snapshot; {notes}"
    return clean_pdf_text(raw, fm.get("agency"))


def refresh_document(md_path: Path, today: str) -> str:
    """Re-fetch a document's source. Returns 'unchanged' | 'updated' | 'error: ...'.
    On change: refreshes snapshot (+.txt), frontmatter retrieved/source_sha256/
    conversion_notes, and regenerates ONLY the '## Full text' section. Effective/version
    dates get a TODO marker — humans transcribe those from the new source (HC-1)."""
    fm, _ = parse_frontmatter(md_path)
    snap_id = fm.get("snapshot_id") or fm["id"]
    fmt = fm["source_format"]
    try:
        raw = fetch(fm["source_url"])
    except Exception as e:
        return f"error: fetch failed ({e})"
    if fmt == "pdf" and raw[:5] != b"%PDF-":
        return "error: fetched content is not a PDF"
    new_sha = content_hash(raw, fmt)
    if new_sha == fm["source_sha256"]:
        return "unchanged"

    raw_path = SNAPSHOT_DIR / f"{snap_id}.{fmt}"
    raw_path.write_bytes(raw)
    if fmt == "pdf":
        subprocess.run(["pdftotext", "-layout", str(raw_path),
                        str(SNAPSHOT_DIR / f"{snap_id}.txt")], capture_output=True)
    elif fmt in ("html", "xml"):
        from html_to_text import html_to_text
        (SNAPSHOT_DIR / f"{snap_id}.txt").write_text(html_to_text(raw), encoding="utf-8")

    text = md_path.read_text()
    text = re.sub(r'^retrieved: .*$', f'retrieved: "{today}"', text, count=1, flags=re.M)
    text = text.replace(fm["source_sha256"], new_sha)
    fm["source_sha256"] = new_sha
    ft, conv = build_fulltext(fm)
    if ft is not None and "## Full text" in text:
        text = re.sub(r"^## Full text\s*$.*?(?=^## |\Z)",
                      f"## Full text\n\n{ft}\n\n", text, count=1, flags=re.M | re.S)
        text = re.sub(r'^conversion_notes: .*$',
                      f'conversion_notes: "{(conv or "").replace(chr(34), chr(39))}"',
                      text, count=1, flags=re.M)
    # dates must be re-transcribed by a human from the new source, never assumed
    if "TODO: human verification required" not in text:
        text = re.sub(r'^(effective_date: .*)$',
                      r'\1  # <!-- TODO: human verification required: source changed; re-transcribe effective/reviewed/version dates from the new source -->',
                      text, count=1, flags=re.M)
    md_path.write_text(text)
    return "updated"
