"""Shared helpers for repo validation tooling."""
import datetime
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIRS = ["statutes", "rules", "executive-orders", "agencies", "external-references"]
SNAPSHOT_DIR = REPO_ROOT / "_meta" / "snapshots"
SCHEMA_DIR = REPO_ROOT / "_meta" / "schema"
MANIFEST_PATH = REPO_ROOT / "_meta" / "source-manifest.yml"

NON_CONTENT_NAMES = {"CHANGELOG.md"}


def content_files():
    """Yield every content document (excludes _index.md and CHANGELOG.md)."""
    for d in CONTENT_DIRS:
        root = REPO_ROOT / d
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.md")):
            if p.name.startswith("_") or p.name in NON_CONTENT_NAMES:
                continue
            yield p


def parse_frontmatter(path: Path):
    """Return (frontmatter dict, body str). Raises ValueError if malformed."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("missing YAML frontmatter (file must start with ---)")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError("unterminated YAML frontmatter")
    fm = yaml.safe_load(text[4:end])
    if not isinstance(fm, dict):
        raise ValueError("frontmatter is not a YAML mapping")
    body = text[end + 4:]
    return _stringify_dates(fm), body


def _stringify_dates(value):
    """YAML parses bare dates into datetime.date; canonicalize to ISO strings."""
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _stringify_dates(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_stringify_dates(v) for v in value]
    return value


_PUNCT_MAP = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', " ": " "})


def ws_only(s: str) -> str:
    """Collapse whitespace runs WITHOUT touching punctuation — for producing rendered
    text (e.g. '## Full text' slices) where original curly quotes must be preserved."""
    return re.sub(r"\s+", " ", s).strip()


def normalize_ws(s: str) -> str:
    """Collapse whitespace runs to single spaces (PDF extraction wraps lines) and map
    curly quotes/apostrophes to straight ones, so punctuation style in the rendered
    Markdown never causes a false quote mismatch."""
    return re.sub(r"\s+", " ", s.translate(_PUNCT_MAP)).strip()


# Quotes are authored between straight double quotes; curly quotes are reserved for
# quotation marks inside the quoted text.
VERBATIM_RE = re.compile(r"\*\*\[VERBATIM\]\*\*\s*\"(.*?)\"", re.DOTALL)


def extract_verbatim_quotes(body: str):
    """Return the quoted text of every **[VERBATIM]** "..." block, blockquote markers stripped."""
    cleaned = re.sub(r"^\s*>\s?", "", body, flags=re.MULTILINE)
    return [m.group(1) for m in VERBATIM_RE.finditer(cleaned)]


FULLTEXT_RE = re.compile(r"^## Full text\s*$(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)


def extract_fulltext(body: str):
    """Return the '## Full text' section body, or None if absent."""
    m = FULLTEXT_RE.search(body)
    return m.group(1) if m else None


ITCS_FAMILY_CODES = ["AC", "AT", "AU", "CA", "CM", "CP", "IA", "IR", "MA", "MP",
                     "PE", "PL", "PS", "RA", "SA", "SC", "SI", "SR"]
_ITCS_HEAD = re.compile(r"^\s*([A-Z ,&–()-]+?)\s*[–(-]\s*\(?([A-Z]{2})\)?\s*$")


def _itcs_bounds(lines):
    """Line index of each ITCS family section start (body, not TOC)."""
    starts = {}
    for i, ln in enumerate(lines):
        if i < 450:
            continue
        m = _ITCS_HEAD.match(ln)
        if m and m.group(2) in ITCS_FAMILY_CODES and m.group(2) not in starts:
            starts[m.group(2)] = i
    return starts


def snapshot_slice(doc_id: str, snapshot_id: str, raw_text: str) -> str:
    """The portion of a shared snapshot's text that a document's '## Full text' covers.
    Used identically by the migration generator and verify_provenance so coverage is
    measured against the same slice that was transcribed. Default: whole text."""
    if snapshot_id == "ors-chapter-276a":
        sec = doc_id.replace("ors-", "").upper().replace("276A", "276A")  # e.g. 276A.300
        norm = ws_only(raw_text)
        matches = list(re.finditer(re.escape(sec) + r" [A-Z“\"]", norm))
        if not matches:
            return norm
        start = matches[-1].start()
        nxt = re.search(r"\b\d{3}[A-Z]?\.\d{3} [A-Z“\"]", norm[start + 10:])
        end = start + 10 + nxt.start() if nxt else len(norm)
        return norm[start:end]
    if doc_id.startswith("oar-"):
        # OARD page text includes site chrome; the rule text runs from the rule number
        # heading to OARD's bookmark hint.
        num = doc_id.replace("oar-", "").replace("-", "-")
        norm = ws_only(raw_text)
        rule_num = doc_id.replace("oar-", "")
        i = norm.find(rule_num)
        j = norm.find("Please use this link to bookmark")
        if i > -1:
            return norm[i:j] if j > i else norm[i:]
        return norm
    if snapshot_id == "eis-css-itcs":
        lines = raw_text.splitlines()
        starts = _itcs_bounds(lines)
        order = sorted(starts.items(), key=lambda kv: kv[1])
        if doc_id == "eis-css-itcs":
            first = order[0][1] if order else len(lines)
            return "\n".join(lines[:first])
        code = doc_id.rsplit("-", 1)[-1].upper()
        if code in starts:
            i = [k for k, _ in order].index(code)
            end = order[i + 1][1] if i + 1 < len(order) else len(lines)
            return "\n".join(lines[starts[code]:end])
    return raw_text


# Byte patterns that change on every fetch without any content change (session ids,
# Cloudflare email-protection keys). HTML snapshots are stored and hashed with these
# stripped, and detect_changes strips them before comparing, so hash drift means real
# content drift.
VOLATILE_PATTERNS = [
    rb";JSESSIONID_OARD=[^?'\" >]*",
    rb"/cdn-cgi/l/email-protection#[0-9a-f]+",
    rb"data-cfemail=\"[0-9a-f]+\"",
]


def normalize_volatile(data: bytes) -> bytes:
    for pat in VOLATILE_PATTERNS:
        data = re.sub(pat, b"", data)
    return data


def content_hash(raw: bytes, fmt: str) -> str:
    """Content hash of a freshly-fetched source: sha256 of the whitespace-normalized
    extracted text (pdftotext for PDFs, tag-stripping for HTML). Some servers stamp
    different bytes on every download (Cloudflare scripts, PDF metadata), so raw-byte
    hashes drift without content change. Falls back to the raw-byte hash when extraction
    yields <200 chars (e.g. image-only scans), where text hashing would be meaningless.

    Used only by detect_changes.py (comparing a fresh fetch against the manifest) and at
    ingestion time. NOT used by verify_provenance.py — pdftotext's output can differ by
    poppler version, so re-deriving text from the .pdf at CI verification time is
    nondeterministic across machines. See hash_snapshot() for the CI-stable check, which
    hashes the .txt already committed alongside the .pdf instead of re-extracting it."""
    import hashlib
    if fmt == "pdf":
        import subprocess
        proc = subprocess.run(["pdftotext", "-layout", "-", "-"], input=raw,
                              capture_output=True, check=False)
        text = proc.stdout.decode("utf-8", errors="replace") if proc.returncode == 0 else ""
    elif fmt in ("html", "xml"):
        from html_to_text import html_to_text
        text = html_to_text(normalize_volatile(raw))
    else:
        # binary formats with no text extractor (xls/xlsx/docx): raw-byte hash
        return hashlib.sha256(raw).hexdigest()
    norm = normalize_ws(text)
    if len(norm) >= 200:
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()
    return hashlib.sha256(raw).hexdigest()


def hash_snapshot(doc_id: str, fmt: str, snapshot_dir: Path = SNAPSHOT_DIR) -> str:
    """CI-stable content hash: sha256 of the whitespace-normalized text already
    committed in <id>.txt (produced once at ingestion time), never re-derived from the
    .pdf/.html at verification time. Falls back to the raw source file's bytes if no
    .txt exists or it's too short to be meaningful (image-only scans)."""
    import hashlib
    raw = (snapshot_dir / f"{doc_id}.{fmt}").read_bytes()
    txt_path = snapshot_dir / f"{doc_id}.txt"
    if txt_path.is_file():
        norm = normalize_ws(txt_path.read_text(encoding="utf-8", errors="replace"))
        if len(norm) >= 200:
            return hashlib.sha256(norm.encode("utf-8")).hexdigest()
    return hashlib.sha256(raw).hexdigest()


class Reporter:
    def __init__(self):
        self.errors = 0

    def error(self, path, msg):
        print(f"ERROR   {path}: {msg}")
        self.errors += 1

    def warn(self, path, msg):
        print(f"warning {path}: {msg}")

    def finish(self, ok_msg):
        if self.errors:
            print(f"\nFAILED with {self.errors} error(s).")
            sys.exit(1)
        print(ok_msg)
