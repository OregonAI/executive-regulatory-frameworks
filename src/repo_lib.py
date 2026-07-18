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
    else:
        from html_to_text import html_to_text
        text = html_to_text(normalize_volatile(raw))
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
