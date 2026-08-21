"""Shared helpers for repo validation tooling."""
import datetime
import hashlib
import html
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIRS = ["statutes", "rules", "executive-orders", "agencies", "external-references",
                "constitution"]
SNAPSHOT_DIR = REPO_ROOT / "_meta" / "snapshots"
SCHEMA_DIR = REPO_ROOT / "_meta" / "schema"
SOURCES_DIR = REPO_ROOT / "_meta" / "sources"

_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def repo_state() -> str:
    """Cheap fingerprint of the corpus: HEAD commit + hash of `git status` porcelain
    (captures uncommitted adds/edits well enough for a cache key). Shared by every
    module-level cache keyed on "has the corpus changed" (mcp_lib's FTS index,
    agency_profile's derived stats) so they invalidate together and consistently."""
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                          capture_output=True, text=True).stdout.strip()
    status = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT,
                            capture_output=True, text=True).stdout
    return head + ":" + hashlib.sha256(status.encode()).hexdigest()[:16]


def yaml_load(text: str):
    """yaml.safe_load, but via the libyaml-backed CSafeLoader when available. Matters at
    this corpus's scale: the big catalogs (oar.yml ~3.8MB, ors.yml ~4.5MB) take ~24-28s each
    under PyYAML's pure-Python SafeLoader vs ~5s under CSafeLoader — a real cost when paid
    repeatedly (every MCP corpus_overview/resolve_citation call, every full-corpus script
    run) rather than once. Falls back to plain SafeLoader if libyaml bindings aren't
    installed in a given environment; same result either way, just slower."""
    return yaml.load(text, Loader=_YAML_LOADER)


def source_groups():
    """Yield (path, parsed dict) for every update-group file in _meta/sources/."""
    for p in sorted(SOURCES_DIR.glob("*.yml")):
        yield p, yaml.safe_load(p.read_text())

NON_CONTENT_NAMES = {"CHANGELOG.md"}

# Single source of truth for "which directory does this doc_type live in".
# Shared by validate_frontmatter.py (CI-enforced check) and ingest_lib.py
# (output_dir_for, so new ingestion code can't hand-type the wrong path).
# Jurisdiction-wide doc_types are NOT agency-scoped (top-level dir); the rest live
# under agencies/<agency>/<dir>/.
DIR_DOC_TYPE = {
    "statutes": "statute",
    "constitution": "constitutional_provision",
    "rules": "rule",
    "executive-orders": "executive_order",
    "external-references": "external_reference",
    "policies": "policy",
    "procedures": "procedure",
    "accounting-manual": "manual",
    "standards": "standard",
    # Special records-retention schedules, folded in from the retired
    # OregonAI/oregon-records-retention corpus. THIS TABLE HAND-DUPLICATES
    # _meta/corpus.yml's content_roots and every local script walks it rather than the
    # config — so a doc_type added to corpus.yml and not here passes every toolkit gate
    # while being invisible to all ~30 `--check` scripts. Both must move together.
    "schedules": "schedule",
}
JURISDICTION_WIDE_DIRS = {"statutes", "rules", "executive-orders", "external-references",
                          "constitution"}


def _is_content_path(p: Path) -> bool:
    """True if p is a content document (under a CONTENT_DIR, .md, not _index/CHANGELOG)."""
    if p.suffix != ".md" or p.name.startswith("_") or p.name in NON_CONTENT_NAMES:
        return False
    try:
        rel = p.resolve().relative_to(REPO_ROOT)
    except ValueError:
        return False
    return rel.parts and rel.parts[0] in CONTENT_DIRS


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


def changed_content_files(base_ref: str | None = None):
    """Content files added/modified relative to base_ref (default: merge-base with
    origin/main, else HEAD~1). Includes uncommitted working-tree changes. Returns a
    sorted list of existing paths — deletions are dropped (nothing to verify).

    Used by verify_provenance.py / validate_frontmatter.py --changed so PR CI only
    checks the diff; full-corpus runs stay on push-to-main / nightly."""
    import subprocess

    def _git(*args):
        return subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                              capture_output=True, text=True)

    if base_ref is None:
        base_ref = "HEAD~1"
        mb = _git("merge-base", "origin/main", "HEAD")
        if mb.returncode == 0 and mb.stdout.strip():
            base_ref = mb.stdout.strip()

    names = set()
    # committed diff base..HEAD, plus staged and unstaged working-tree changes
    for args in (("diff", "--name-only", "--diff-filter=d", f"{base_ref}...HEAD"),
                 ("diff", "--name-only", "--diff-filter=d", "HEAD"),
                 ("ls-files", "--others", "--exclude-standard")):
        res = _git(*args)
        if res.returncode == 0:
            names.update(n for n in res.stdout.splitlines() if n.strip())

    out = []
    for n in names:
        p = (REPO_ROOT / n)
        if p.is_file() and _is_content_path(p):
            out.append(p)
    return sorted(out)


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


RULE_TITLE_HTML_RE = re.compile(
    r"<strong>\s*(\S+)\s*</strong>\s*<br\s*/?>\s*<strong>(.*?)</strong>", re.S)


def rule_title_from_html(raw_html: str, target: str) -> str | None:
    """An OAR rule's real title, read from OARD's own markup: the rule number and its
    title both sit in their own <strong> tag, separated by a <br> — '<strong>817-010-0110
    </strong><br><strong>Walls and Ceilings</strong>'. Far more reliable than guessing a
    prose boundary in the flattened text: OARD titles are Title Case (most words
    capitalized), which defeats a first-capitalized-word heuristic almost immediately, and
    many rules have no numbered '(1)' subsection to anchor on either. None if not found."""
    m = RULE_TITLE_HTML_RE.search(raw_html)
    if not m or m.group(1) != target:
        # the target rule's tag pair isn't the first one on the page (e.g. OARD served a
        # renumbered page listing a neighbor first) — search all pairs for the right number
        for m in RULE_TITLE_HTML_RE.finditer(raw_html):
            if m.group(1) == target:
                break
        else:
            return None
    title = html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))
    return normalize_ws(title) or None


# ------------------------------------------------------ the Oregon Constitution (ADR 0005)
# ONE PAGE, EIGHTEEN ARTICLES. The Constitution is published as a single HTML document, so
# every section of it is sliced out of one shared snapshot — the `chapter-html` shape the
# ORS ingest already uses, with the article standing where the chapter does.
#
# The id carries both coordinates (`orconst-art-vi-sec-9a` = Article VI, section 9a), which
# is what lets this function be reached from a doc_id alone — the signature the
# `snapshot_slice_module` plugin hook fixes, and the reason ingestion and verification can
# read the same bytes.
ORCONST_ID_RE = re.compile(r"^orconst-art-([ivxl]+(?:-[a-z])?)-sec-(\d+[a-z]?)$")


def orconst_id(article: str, section: str) -> str:
    """The document id one constitutional citation names: `Art. XI-A, sec. 9a` ->
    `orconst-art-xi-a-sec-9a`. Lowercased, and otherwise the citation's own tokens.

    ONE DEFINITION, THREE READERS: the ingest names the file with it, the citation scheme
    resolves to it, and ORCONST_ID_RE above parses it back into the coordinates the slicer
    needs. Written twice, a change to the shape would break the third silently."""
    return f"orconst-art-{article.lower()}-sec-{section.lower()}"


def constitution_article_region(norm_text: str, article: str) -> str:
    """One article's text: its heading through the next article's heading.

    CASE AND BOUNDARY BOTH MATTER. `ARTICLE VI` appears exactly once in the published
    page — the document's own contents list spells articles in mixed case ("Article VI
    Administrative Department") and cross-references inside section text say "Article V",
    not "ARTICLE V". The lookahead is what stops `ARTICLE XI` matching `ARTICLE XI-A`,
    which is a real heading four articles further down."""
    head = re.search(rf"ARTICLE {re.escape(article)}(?![-A-Z0-9(])", norm_text)
    if not head:
        return ""
    nxt = re.compile(r"ARTICLE [IVXL]").search(norm_text, head.end())
    return norm_text[head.start():nxt.start() if nxt else len(norm_text)]


def constitution_section_slice(norm_text: str, article: str, section: str) -> str:
    """The text of one section of one article, or "" if the page does not print one.

    Anchored on the BODY heading `Section 9a. `, never on the article's contents list,
    which prints the same numbers as `Sec.      9a.`. The trailing period is load-bearing
    in both directions: `Section 9. ` must not match `Section 9a. `, and `Section 9a. `
    must not match `Section 9. `."""
    region = constitution_article_region(norm_text, article)
    if not region:
        return ""
    start = re.search(rf"Section {re.escape(section)}\. ", region)
    if not start:
        return ""
    body = region[start.start():]
    nxt = re.compile(r"Section \d+[a-z]?\. ").search(body, 1)
    return (body[:nxt.start()] if nxt else body).strip()


def snapshot_slice(doc_id: str, snapshot_id: str, raw_text: str) -> str:
    """The portion of a shared snapshot's text that a document's '## Full text' covers.
    Used identically by the migration generator and verify_provenance so coverage is
    measured against the same slice that was transcribed. Default: whole text."""
    if snapshot_id == "oregon-constitution":
        m = ORCONST_ID_RE.match(doc_id)
        if not m:
            return ""
        return constitution_section_slice(ws_only(raw_text), m.group(1).upper(),
                                          m.group(2))
    if snapshot_id.startswith("ors-chapter-"):
        sec = doc_id.replace("ors-", "").upper()  # e.g. 276A.300, 192.018
        norm = ws_only(raw_text)
        matches = list(re.finditer(re.escape(sec) + r" [A-Z“\"]", norm))
        if not matches:
            return ""
        start = matches[-1].start()
        window = norm[start + 10:]
        nxt = re.search(r"\b\d{3}[A-Z]?\.\d{3} [A-Z“\"]", window)
        # A bare part/subpart heading ("TREATMENT OF PRISONERS") right after this section's
        # closing citation bracket has no section number of its own, so the next-numbered-
        # section search above doesn't stop there — it would otherwise bleed into this
        # slice. If one immediately follows the bracket before the next real section, end
        # right after the bracket instead.
        head = re.search(r"\]\s+[A-Z][A-Z '\-]{7,}(?:\s|$)", window)
        candidates = [start + 10 + nxt.start()] if nxt else []
        if head:
            candidates.append(start + 10 + head.start() + 1)  # +1 = right after "]"
        end = min(candidates) if candidates else len(norm)
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


class Checks:
    """The PASS/FAIL lines a `--selftest` prints, and their tally.

    One shape rather than three closures: `agency_profile`, `enrich_oar` and `catalog_oar`
    each print one line per proof, and a selftest whose scaffolding is copied is one where
    the copies drift — a `check()` that forgets to count a failure reports a clean run for a
    proof that failed, which is the one thing a selftest may not do."""

    def __init__(self):
        self.failed = 0

    def __call__(self, name, condition):
        print(("PASS " if condition else "FAIL ") + name)
        if not condition:
            self.failed += 1

    def report(self, label: str = "selftest") -> int:
        """Print the verdict and return the exit code it means."""
        print(f"{label} {'OK' if not self.failed else 'FAILED'}")
        return 1 if self.failed else 0
