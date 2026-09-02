"""Shared helpers for repo validation tooling."""
import argparse
import ast
import datetime
import hashlib
import html
import os
import re
import subprocess
import sys
from collections import namedtuple
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIRS = ["statutes", "rules", "executive-orders", "agencies", "external-references",
                "constitution"]
SNAPSHOT_DIR = REPO_ROOT / "_meta" / "snapshots"
SCHEMA_DIR = REPO_ROOT / "_meta" / "schema"
SOURCES_DIR = REPO_ROOT / "_meta" / "sources"

_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def assigned_string_constants(node) -> set:
    """The string constants an AST expression can EVALUATE TO, rather than merely mention.

    `"repealed" if gone else "current"` yields both; `[r for r in rows if r["status"] ==
    "current"]` yields none, and the difference is a filter versus a decision. The narrowing
    matters in both directions -- a walk of every constant under the node reports the test of
    a conditional as though it were the answer, and `d["status"] = d.get("status") if
    any(r.get("status") == "ingested" for ...) else "not_ingested"` would name `ingested`,
    `status` and `rules` as vocabulary the ingester writes.

    SHARED BY `legal_status.py` (which vocabulary a write DECIDES a document's legal status
    with) and `ingest_status.py` (which vocabulary `ingest_oar.py`/`catalog_oar.py` write to
    the catalog's own `status` field, #333) -- two different AST scans over two different
    vocabularies, reading the same shape of expression. A THIRD private copy of this is
    exactly the failure both of those modules exist to refuse elsewhere, so it lives here
    once instead."""
    if isinstance(node, ast.Constant):
        return {node.value} if isinstance(node.value, str) else set()
    if isinstance(node, ast.IfExp):
        return assigned_string_constants(node.body) | assigned_string_constants(node.orelse)
    if isinstance(node, ast.BoolOp):
        return set().union(*(assigned_string_constants(v) for v in node.values))
    return set()


def oar_rule_path(number: str, root: Path = REPO_ROOT) -> Path:
    """Where an OAR rule document for `number` lives (or would live) on disk --
    rules/{chapter}/{division}/oar-{number}.md. THE ONE DEFINITION (#334 code review):
    `ingest_oar.py`'s renumbered-write site and `catalog_oar.py`'s
    `renumbered_without_path()` both need this path, and used to compute it independently
    -- the same writer/reader-drift shape #334 exists to close for this catalog's other
    fields, just not yet closed for this one. `root` is a parameter, not always
    `REPO_ROOT`, so a `--selftest` can point this at a temporary directory and prove the
    disk check both ways without touching or depending on the real `rules/` tree."""
    ch, div, _ = number.split("-")
    return root / "rules" / ch / div / f"oar-{number}.md"


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


class MissingContentDir(RuntimeError):
    """Raised by content_files() when a directory CONTENT_DIRS declares does not exist on
    disk, OR EXISTS BUT COULD NOT BE WALKED TO THE BOTTOM (permissions, a bad mount, a `git
    sparse-checkout` slice). CONTENT_DIRS is a fixed, declared list -- a missing or
    unreadable entry is not an empty corpus section, it is a corpus this process COULD NOT
    READ (AGENTS.md's overriding rule: could not check is never reported as is not there).
    Silently skipping the missing case (#316, measured on `main` at 7e850ecca6) let a
    one-character typo in a directory name drop the yield from 81,921 to 39,360 documents --
    42,561 gone, exit 0, no warning -- and every gate that says "measured across the corpus"
    walks this function, so each of them would have reported green on a corpus half its size
    with a wrong denominator in every finding. THE UNREADABLE CASE IS THE SAME SUBSTITUTION
    ONE LEVEL DOWN, and #316 names it explicitly: `Path.rglob` swallows a `PermissionError`
    from any directory it cannot list and simply yields fewer files -- no exception, no
    warning (measured: `list(unreadable_dir.rglob("*.md"))` is `[]` on Python 3.12.3, not a
    raise). A directory that exists but cannot be listed reads exactly like one that was
    walked and genuinely holds zero documents unless something probes it on purpose."""


def content_files(dirs=None):
    """Yield every content document (excludes _index.md and CHANGELOG.md).

    Checks every directory in scope exists, and eagerly walks all of them to
    the bottom, BEFORE returning anything to the caller (#316) -- content_files() forces
    `_walk_content_dirs()`'s generator to completion and hands back an iterator over the
    materialized result, rather than being a generator function itself whose body (and these
    checks with it) would not run a single line until the caller's first `next()`. Raising
    eagerly, at call time, means a refusal -- missing directory, or one `os.walk` could not
    read all the way down -- cannot be hidden by a caller who only partially consumes the
    result (`itertools.islice`, a `break` after the first few) -- every real caller in this
    repo just does `for p in content_files():`, so MissingContentDir propagates as a loud
    crash the moment it's called, never a quietly undercounted corpus that happens not to
    hit the missing or unreadable directory before the caller stops looking.

    `dirs=None` (every existing caller) walks all of CONTENT_DIRS, unchanged. `dirs=(...)`
    scopes the WALK (the expensive part -- `os.walk` plus every caller's own frontmatter
    parse) to that subset, for a caller that can prove, from where the corpus's ingest
    scripts actually write, that what it is looking for could never be under the
    directories it left out (see `check_updates.py`'s `_CHAPTER_HTML_DIRS`).

    The #316 missing/unreadable checks below are NOT scoped by `dirs` -- they always run
    over the full, declared CONTENT_DIRS, regardless of what the caller asked to walk.
    Checking a directory's existence and top-level readability is an `is_dir()` plus one
    `os.scandir()` peek per entry -- O(#CONTENT_DIRS), not O(#files) -- so scoping it
    would buy no measurable speed while quietly narrowing what every caller of a scoped
    walk is protected against: a caller that asks only for `("statutes", "constitution")`
    is still told, loudly, if `rules/` went missing or unreadable, even though it never
    reads a document from `rules/`. A directory a caller chose not to WALK is still one
    this function has an opinion about; only the file-materialization step below is
    limited to what was actually requested.
    """
    missing = [d for d in CONTENT_DIRS if not (REPO_ROOT / d).is_dir()]
    if missing:
        raise MissingContentDir(
            f"CONTENT_DIRS declares {missing} but "
            + ("it does" if len(missing) == 1 else "they do")
            + " not exist on disk under REPO_ROOT -- a missing declared content directory "
            "is a corpus this process could not read, never an empty one")
    # A directory can exist and still refuse to be listed (chmod 000, a failed bind mount, a
    # sparse-checkout slice) -- `Path.is_dir()` above is silent about that, and so is
    # `Path.rglob` further down, which is why this checks each declared top-level dir
    # directly with `os.scandir` before ever walking into it.
    unreadable = []
    for d in CONTENT_DIRS:
        try:
            next(os.scandir(REPO_ROOT / d), None)
        except OSError as e:
            unreadable.append((d, e))
    if unreadable:
        names = [d for d, _ in unreadable]
        detail = "; ".join(f"{d}: {e.strerror or e}" for d, e in unreadable)
        raise MissingContentDir(
            f"CONTENT_DIRS declares {names} but "
            + ("it exists and could not be listed" if len(names) == 1
               else "they exist and could not be listed")
            + f" ({detail}) -- a directory that exists but cannot be read is a corpus this "
            "process could not read, never one confirmed empty")
    scope = CONTENT_DIRS if dirs is None else list(dirs)
    return iter(list(_walk_content_dirs(scope)))


def _walk_content_dirs(dirs=None):
    for d in (CONTENT_DIRS if dirs is None else dirs):
        root = REPO_ROOT / d
        found = []

        def _onerror(err):
            # A directory nested under a declared content dir can be unreadable even when
            # the top-level scan above succeeded (chmod on a subdirectory, a partial mount).
            # `os.walk` swallows this silently unless `onerror` is given -- give it one that
            # refuses instead, the same substitution one level deeper than the top-level check.
            raise MissingContentDir(
                f"{d} could not be walked to the bottom -- {err.filename!r} raised "
                f"{err.strerror or err} -- a directory that exists but cannot be fully read "
                "is a corpus this process could not read, never one confirmed empty")

        for dirpath, _dirnames, filenames in os.walk(root, onerror=_onerror):
            found.extend(Path(dirpath) / name for name in filenames)
        for p in sorted(found):
            if p.suffix == ".md" and not p.name.startswith("_") and p.name not in NON_CONTENT_NAMES:
                yield p


# Frontmatter fields that constitute an AUTHORITY CLAIM rather than a mention -- a
# document DECLARING a citation as its own legal authority, as opposed to merely
# discussing it in the body. Shared by every citation-inventory scan
# (`scan_external_citations.py`, `scan_ors_citations.py`) rather than each keeping its own
# copy: the same distinction, the same two fields, in every scan built to this shape.
AUTHORITY_FIELDS = ("legal_authority", "statutes_implemented")


def walk_strings(obj):
    """Yield every string in a nested frontmatter value (str, or list/dict of same) --
    `legal_authority` is sometimes a bare string and sometimes a list, so a caller reading
    it for citations needs every leaf string regardless of shape. Shared by the same
    citation-inventory scans as `AUTHORITY_FIELDS`, for the same reason."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_strings(v)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from walk_strings(v)


def _git(*args):
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                          capture_output=True, text=True)


def resolve_base_ref() -> str:
    """"Before this change" as a commit: merge-base with origin/main, else HEAD~1 --
    THE ONE RESOLUTION, shared by every gate that compares the working tree against
    "what was already committed" rather than a hand-maintained number (AGENTS.md
    "before gating a figure, ask whether it should exist" -- a floor derived from git
    history is not a number in prose). `changed_content_files` had this inline first;
    `stated_census.py`'s coverage floor (#341) is the second caller, so it moved here
    rather than becoming a second, driftable copy."""
    base_ref = "HEAD~1"
    mb = _git("merge-base", "origin/main", "HEAD")
    if mb.returncode == 0 and mb.stdout.strip():
        base_ref = mb.stdout.strip()
    return base_ref


def committed_text(path: Path, ref: str, head_ref: str = "HEAD") -> str | None:
    """`path`'s text as of `ref` -- or None if `path` did not exist at that ref under
    ANY name reachable by rename detection (a genuinely new file has nothing to compare
    against, not a regression) or `ref` cannot be read (no git history, a shallow clone
    missing that commit). `path` may be absolute or relative to REPO_ROOT.

    Tries the path's OWN name at `ref` first; if that misses, asks `git diff -M` for a
    committed rename between `ref` and `head_ref` (default `HEAD` -- every real caller's
    "now") whose NEW side is this path, and if one exists, reads the OLD side's text at
    `ref` instead -- found by code review: without this, a document renamed in the same
    commit/PR that also shrank it (`git show ref:new-name` -- nothing there under that
    name) reads as "new since `ref`, nothing to compare against" rather than "renamed,
    and its coverage dropped," silently disabling any caller (e.g. `stated_census.py`'s
    coverage floor, #341) that treats a miss here as vacuously satisfied. Only resolves
    a rename already committed to `head_ref` -- an uncommitted rename in the working
    tree (nothing unusual for local, uncommitted edits, but not the CI shape this
    closes) is not detected, since `git diff -M` between two commits never sees
    working-tree-only state. `head_ref` is a parameter (not hardcoded) only so
    `selftest()` can point it at a real historical rename commit instead of today's
    HEAD -- every production call site keeps the default."""
    try:
        rel = path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        rel = path
    rel_s = rel.as_posix()
    res = _git("show", f"{ref}:{rel_s}")
    if res.returncode == 0:
        return res.stdout
    status = _git("diff", "-M", "--name-status", ref, head_ref)
    if status.returncode == 0:
        for line in status.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[0].startswith("R") and parts[2] == rel_s:
                old = _git("show", f"{ref}:{parts[1]}")
                if old.returncode == 0:
                    return old.stdout
    return None


def changed_content_files(base_ref: str | None = None):
    """Content files added/modified relative to base_ref (default: merge-base with
    origin/main, else HEAD~1). Includes uncommitted working-tree changes. Returns a
    sorted list of existing paths — deletions are dropped (nothing to verify).

    Used by verify_provenance.py / validate_frontmatter.py --changed so PR CI only
    checks the diff; full-corpus runs stay on push-to-main / nightly."""
    if base_ref is None:
        base_ref = resolve_base_ref()

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
#
# ------------------------------------------------ WHAT AN ARTICLE'S IDENTITY IS (#195)
#
# THE DESIGNATION, PARENTHETICAL INCLUDED — not the roman numeral, and not a position on
# the page. Measured against the 2024 edition, which prints 40 article headings:
#
#   ARTICLE VII (Amended)   JUDICIAL BRANCH        both operative, both cited by Oregon
#   ARTICLE VII (Original)  THE JUDICIAL BRANCH    courts, and there is no bare ARTICLE VII
#   ARTICLE XI-F(1)         HIGHER EDUCATION …     two designations, not one printed twice
#   ARTICLE XI-F(2)         VETERANS' BONUS
#   ARTICLE XI-A            RURAL CREDITS          repealed 1942, heading + history only
#   ARTICLE XI-A            FARM AND HOME LOANS …  the article in force
#
# So `VII` alone names two documents and cannot be an identity, `XI-F` names neither of
# two, and `XI-A` is one designation printed twice — the last is the case the OCCURRENCE
# index below exists for, and it is the only one of the three that is not a difference in
# designation.
#
# THE SLUG IS THE DESIGNATION, PUNCTUATION FOLDED TO HYPHENS, and the fold is chosen so that
# an article with no parenthetical keeps the slug it already had: `VI` -> `vi`, so Article
# VI's ten published documents keep the ids they are live on (#194). A positional scheme
# (`vii-1`/`vii-2`) or a first-wins one would have re-keyed nothing today and everything on
# the next amendment, and neither is how the citation is written.
#
# THIS DECLARATION IS ALSO THE ARTICLE TOKEN BOTH CITATION FORMS ARE BUILT FROM —
# see ORCONST_ARTICLE_TOKEN below.
ORCONST_ARTICLE_RE = re.compile(
    r"(?P<roman>[IVXL]+)(?:-(?P<letter>[A-Z])(?:\((?P<index>\d)\))?)?"
    r"(?: \((?P<edition>Amended|Original)\))?", re.I)

# The ARTICLE half of a citation, as one regex source string. THE SINGLE DECLARATION
# criterion 4 of #195 asks for: `citation_schemes.OR_CONST_C` interpolates it and
# `catalog_agencies.AUTHORITY_FORMS` interpolates it, so the citation scheme and the
# enabling-authority form cannot answer "what is a constitutional article" differently.
# Before this, they disagreed in BOTH directions: the scheme accepted `Art. XI-A` and the
# form refused it, the form accepted `Art. VII (Amended)` and the scheme refused it.
#
# Written here rather than in either consumer because this is where the id shape lives, and
# the token and the id are the same fact read two ways — `orconst_article_slug` below turns
# one into the other. Kept as a SOURCE STRING, not a compiled pattern, because it is
# interpolated into TWO different patterns (`citation_schemes.OR_CONST_C` and
# `catalog_agencies.AUTHORITY_FORMS`' constitutional form) built with different flags, and a
# pre-compiled fragment cannot be spliced into another pattern's source text. Unrelated to
# #202 (misattributed to "corpus-toolkit#202" here before this correction) — that issue was
# about `register_scheme` losing a flag off an ALREADY-COMPLETE pattern at registration, and
# is fixed by passing the compiled object there, which this fragment is never passed to on
# its own.
#
# Deliberately exact about the space before `(Amended)`: an allowlist is widened by a
# decision, not by a `\s*`.
ORCONST_ARTICLE_TOKEN = (r"[IVXL]+(?:-[A-Z](?:\(\d\))?)?"
                         r"(?: \((?:Amended|Original)\))?")

# And the SECTION half, for the same reason and read off the same page. `9a` is the ordinary
# lettered section; the uppercase branch exists for exactly ONE section in the 2024 edition
# — Article XI section 11L, which the page prints between 11k and 12 in the article's own
# contents list. Read with a lowercase-only suffix it is not a section that failed a rule and
# got reported, it is a section nothing in the pipeline can see, so the count looks right
# while a section of the Oregon Constitution is missing.
ORCONST_SECTION_TOKEN = r"\d+[A-Za-z]?"

# The same shape as it appears in a document id, which is what the slicer parses back.
# `amended|original` is tried BEFORE the single-letter branch so that `vii-original` is not
# read as Article VII-O with a trailing `riginal`.
ORCONST_ARTICLE_SLUG = r"[ivxl]+(?:-(?:amended|original)|-[a-z](?:-\d)?)?"
# IDS ARE LOWERCASE, as every id in this repo is, so section 11L is `…-sec-11l`; the slicer
# matches the printed suffix case-insensitively to get back to `Section 11L.`, which is safe
# because no article prints both `Section 11l.` and `Section 11L.`.
ORCONST_ID_RE = re.compile(rf"^orconst-art-({ORCONST_ARTICLE_SLUG})-sec-(\d+[a-z]?)$")
_ORCONST_SLUG_RE = re.compile(
    r"^(?P<roman>[ivxl]+)(?:-(?P<edition>amended|original)"
    r"|-(?P<letter>[a-z])(?:-(?P<index>\d))?)?$")


def orconst_article_slug(article: str) -> str:
    """`VII (Amended)` -> `vii-amended`, `XI-F(1)` -> `xi-f-1`, `VI` -> `vi`.

    Refuses anything that is not an article designation the page prints, rather than
    lowercasing whatever it is handed: the id is the join between the published file, the
    citation scheme and the slicer, so a designation this cannot read is one of those three
    quietly disagreeing with the other two."""
    m = ORCONST_ARTICLE_RE.fullmatch(article.strip())
    if not m:
        raise ValueError(f"{article!r} is not an Oregon Constitution article designation")
    parts = [m.group("roman").lower()]
    if m.group("letter"):
        parts.append(m.group("letter").lower())
    if m.group("index"):
        parts.append(m.group("index"))
    if m.group("edition"):
        parts.append(m.group("edition").lower())
    return "-".join(parts)


def orconst_article_designation(slug: str) -> str:
    """The inverse of `orconst_article_slug`: `xi-f-1` -> `XI-F(1)`.

    THE SLICER'S ENTRY POINT REACHES THE ARTICLE THROUGH THIS, from the doc id alone —
    `snapshot_slice(doc_id, …)` is the signature the `snapshot_slice_module` plugin hook
    fixes, so an id that could not be turned back into the designation the page prints
    would publish documents whose provenance nothing could verify."""
    m = _ORCONST_SLUG_RE.match(slug)
    if not m:
        raise ValueError(f"{slug!r} is not an Oregon Constitution article slug")
    out = m.group("roman").upper()
    if m.group("letter"):
        out += "-" + m.group("letter").upper()
    if m.group("index"):
        out += f"({m.group('index')})"
    if m.group("edition"):
        out += f" ({m.group('edition').capitalize()})"
    return out


def orconst_id(article: str, section: str) -> str:
    """The document id one constitutional citation names: `Art. XI-A, sec. 9a` ->
    `orconst-art-xi-a-sec-9a`; `Art. VII (Amended), sec. 1` ->
    `orconst-art-vii-amended-sec-1`.

    ONE DEFINITION, THREE READERS: the ingest names the file with it, the citation scheme
    resolves to it, and ORCONST_ID_RE above parses it back into the coordinates the slicer
    needs. Written twice, a change to the shape would break the third silently."""
    return f"orconst-art-{orconst_article_slug(article)}-sec-{section.lower()}"


ArticleHeading = namedtuple("ArticleHeading", "designation occurrence text")

# WHAT A SECTION HEADING LOOKS LIKE, declared once. Measured on the 2024 edition: 381
# occurrences of `Section N. ` in the whole document and every one of them is a heading —
# the page's cross-references are lowercase ("See note at section 15, Article V"), which is
# what makes this safe both as an anchor and as a terminator. The trailing period is
# load-bearing in both directions: `Section 9. ` must not match `Section 9a. `, and
# `Section 9a. ` must not match `Section 9. `.
_SECTION_HEADING_RE = re.compile(rf"Section {ORCONST_SECTION_TOKEN}\. ")

# `ARTICLE VII (Amended)` — the heading, with the WHOLE designation, and a lookahead that
# refuses a partial one. Measured on the 2024 edition: `ARTICLE [IVXL]` occurs 40 times and
# every one of them is a heading, and all 40 are matched here in full. The lookahead is what
# stops `ARTICLE XI` matching the `ARTICLE XI-A` four articles down, and `(` is in it so
# that `ARTICLE XI-F` cannot match `ARTICLE XI-F(1)`.
#
# CASE MATTERS: the page's own contents list spells articles in mixed case ("Article VI
# Administrative Department") and cross-references inside section text say "Article V". Only
# the headings are capitalized.
_ARTICLE_HEADING_RE = re.compile(rf"ARTICLE ({ORCONST_ARTICLE_TOKEN})(?![-A-Za-z0-9(])")


def constitution_article_headings(norm_text: str) -> list:
    """Every ARTICLE heading the page prints, in the order it prints them: the designation,
    WHICH PRINT OF IT this is, and the text from this heading to the next one.

    THE DENOMINATOR FOR ARTICLES, and it is the page's headings rather than a list of
    eighteen roman numerals, for the same reason `discover_sections` reads section bodies
    rather than an article's contents list: an article the page prints and nobody looked at
    must not be indistinguishable from one the document does not carry. The 2024 edition
    prints 40 headings under 39 distinct designations — 18 roman numerals, the lettered
    articles under X and XI, ARTICLE VII twice as `(Amended)` and `(Original)`, and
    ARTICLE XI-A twice."""
    heads = list(_ARTICLE_HEADING_RE.finditer(norm_text))
    seen, out = {}, []
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(norm_text)
        designation = h.group(1)
        seen[designation] = seen.get(designation, -1) + 1
        out.append(ArticleHeading(designation, seen[designation],
                                  norm_text[h.start():end]))
    return out


def constitution_article_region(norm_text: str, article: str) -> str:
    """One article's text, as the SLICER sees it: heading to the next heading.

    ONE DESIGNATION IS NOT ALWAYS ONE HEADING. Measured on the 2024 edition, `ARTICLE XI-A`
    is printed TWICE — the repealed "RURAL CREDITS" (1916, repealed 1942), which the page
    keeps as a heading and a history bracket, and the current "FARM AND HOME LOANS TO
    VETERANS". A citation names one of them and this function is reached from a doc id
    alone, so it cannot be told which; it takes THE OCCURRENCE THAT PRINTS SECTION BODIES,
    which is what a citation to `Art. XI-A, sec. 1` can only mean — a repealed article is
    printed as its heading and its repeal bracket and nothing else.

    Three honest outcomes, and taking the first print was none of them: no such designation
    is "", every print sectionless is the first print (so the skip reason is read off a real
    region), and — the case that must not be guessed — MORE THAN ONE print carrying sections
    is "", because then nothing in the id says which the citation means. That last has no
    instance in the 2024 edition and is refused rather than left to first-wins.

    The occurrences themselves are `constitution_article_headings`, which is what the
    catalog is built from: this is the slicer's view, not the corpus's."""
    prints = [h for h in constitution_article_headings(norm_text)
              if h.designation == article]
    if not prints:
        return ""
    with_sections = [h for h in prints if _SECTION_HEADING_RE.search(h.text)]
    if len(with_sections) > 1:
        return ""
    return with_sections[0].text if with_sections else prints[0].text


# A repealed section is printed as its leadline, its legislative-history brackets and — often
# — a Legislative Counsel note, and nothing else. The letters left once all three are removed
# are what says whether a print carries text. The floor is the one
# `ingest_constitution.why_not_publishable` refuses at, and it is declared HERE because the
# SLICER needs it too: the print `constitution_section_slice` returns for a doubled section
# number must be the print the ingest would publish, or a document would be written from one
# print and have its provenance verified against another.
#
# EIGHT, AND IT IS MEASURED. Of the 381 section headings the 2024 edition prints, 40 carry
# ZERO letters by this measure and every one of the 40 is a repealed or superseded print; the
# next smallest carries 31 — "All elections shall be free and equal.", the whole of Article
# II section 1. The floor sits in that gap, so it is not a judgment about how short a section
# of the Oregon Constitution may be. #194's threshold was 120 characters of RAW SLICE, copied
# from `ingest_ors.py` where no section is that short, and it refused four real one-sentence
# sections — three of them in the Bill of Rights — with a reason saying the slice was too
# small to be the section's text when it was the whole of it.
CONST_SECTION_MIN_BODY_CHARS = 8


def constitution_section_anchor(section: str) -> str:
    """The regex that matches `Section 9a. ` at the head of that section's own text.

    CASE-INSENSITIVE ON THE SUFFIX ONLY, and that narrowness is the whole point. Ids are
    lowercase, so Article XI section 11L arrives here as `11l` and has to reach a heading the
    page prints as `Section 11L.`; an `re.I` on the WHOLE anchor reaches it and also reaches
    the page's lowercase cross-references — "see section 15. " inside prose — and two of them
    were then counted as a second PRINT of the section, which reported Article XI section 15
    and Article XV section 4 as citations too ambiguous to resolve. Both are ordinary
    sections. Measured: with the anchor built this way, the document's 381 `Section N.`
    headings are the only things it matches."""
    m = re.fullmatch(r"(\d+)([A-Za-z]?)", section)
    if not m:
        return ""
    digits, letter = m.groups()
    suffix = f"[{letter.lower()}{letter.upper()}]" if letter else ""
    return rf"Section {digits}{suffix}\. "


def constitution_section_body_chars(slice_text: str, section: str) -> int:
    """How many letters of the SECTION'S OWN TEXT this slice carries: everything but its
    printed leadline, its legislative-history brackets, and the Legislative Counsel notes
    the page prints after it.

    THE LEADLINE IS CUT BY MATCHING IT, never by counting a title's length off the front:
    the article's contents list and the section's own head print different strings ("County
    Officers" against "County Officers:", "Vacancies OF" against "Vacancies IN"), and every
    character of difference shifts the window in one direction or the other (#194's review
    found that bug and this is where the fix now lives, once). It also stops at `[`, because
    Article V section 15 is a heading and a bracket and NO leadline at all — read through
    the bracket, the cut ate "[This section … proposed by S.J.R. " and left the remainder of
    the redesignation note standing as twenty-four letters of apparent body text.

    THE NOTES ARE NOT THE SECTION'S TEXT. A slice runs heading to heading, so a Legislative
    Counsel note printed between two sections lands inside the first one's slice — 57 of
    them on the page. For a LIVE section that is the page's own adjacent text and it is
    mirrored as the page prints it. For a REPEALED one it is the only thing standing after
    the history bracket, and counting it as body text published four sections (Art. I sec.
    36, Art. IV sec. 1a, Art. VIII sec. 6, Art. XI sec. 11f) whose "full text" was a
    leadline, a repeal bracket and an editorial note about the repeal."""
    # The heading first, then the leadline if the print has one — two steps, because a
    # print may have a heading and no leadline (Article V section 15), and one regex
    # spanning both either cut nothing there or cut into the bracket.
    rest = re.sub("^" + constitution_section_anchor(section).replace("\\. ", r"\.\s+"),
                  "", slice_text, count=1)
    rest = re.sub(r"^[^\[]*?[.:](?:\s|$)", "", rest, count=1)
    rest = re.sub(r"\s*\bNote: .*$", "", rest, flags=re.S)
    return len(re.sub(r"[^A-Za-z]", "", re.sub(r"\[[^\]]*\]", "", rest)))


def constitution_section_prints(norm_text: str, article: str, section: str) -> list:
    """Every slice this article prints under this section number, in page order.

    Anchored on the BODY heading `Section 9a. `, never on the article's contents list,
    which prints the same numbers as `Sec.      9a.`.

    THE SLICE ENDS AT THE NEXT `Section N. ` (`_SECTION_HEADING_RE`), which is safe because
    the page's own cross-references are lowercase.

    USUALLY ONE. Measured on the 2024 edition: 381 section headings under 371 distinct
    (article, number) pairs — 9 numbers across 7 articles are printed more than once, 19
    prints in all, because the page keeps a superseded print of a section beside the one
    that replaced it."""
    return constitution_section_prints_in(
        constitution_article_region(norm_text, article), section)


def constitution_section_prints_in(region: str, section: str) -> list:
    """The same, for a caller that already holds the article's region.

    The catalog walks an article's own text once and needs every print of a number out of
    THAT text; the slicer arrives with a doc id and has to find the region first. One
    implementation, reached two ways, because a second copy of "where does a section's text
    start and stop" is the thing this file exists to prevent."""
    anchor = constitution_section_anchor(section)
    if not region or not anchor:
        return []
    out = []
    for start in re.finditer(anchor, region):
        body = region[start.start():]
        nxt = _SECTION_HEADING_RE.search(body, 1)
        out.append((body[:nxt.start()] if nxt else body).strip())
    return out


def constitution_section_slice(norm_text: str, article: str, section: str) -> str:
    """The text of the section one citation names, or "" if the page prints no such
    section — or prints it in a way that does not say which one is meant.

    WHICH PRINT A CITATION NAMES is decided HERE and not in the ingest, because this is the
    function `snapshot_slice` reaches from a doc id alone, and a rule that lived in the
    ingest would let the text published and the text verified drift apart.

    THE PRINT CARRYING TEXT, not the first and not the last — measured, because both of
    those are wrong on the 2024 edition. Article IV prints the operative section 1 FIRST and
    its superseded print second; Article XIV prints the superseded section 1 first and the
    one in force second; Article XI prints section 11 three times and means the third. Every
    superseded print is the shape of a repealed section.

    Three outcomes, none of them a guess: no print is "", exactly one print with text is
    that print, no print with text is the FIRST print (a real region for the ingest to
    report `history-only` against), and MORE THAN ONE print with text is "" — nothing in the
    citation says which, so nothing is sliced. That last has no instance today."""
    return operative_print(constitution_section_prints(norm_text, article, section), section)


def operative_print(prints: list, section: str) -> str:
    """Which of a section number's prints a citation to that number names.

    ONE RULE, TWO CALLERS. The slicer above reaches it from a doc id; the catalog reaches it
    to read the section's TITLE off the same print the text will come from. Written twice,
    a document could carry one print's leadline over another print's text.

    Four outcomes and none of them a guess:
      * no print                     -> ""
      * exactly one print with text  -> that print
      * no print with text           -> the FIRST print, so the caller has a real slice to
                                        report `history-only` against rather than a blank
      * more than one print with text -> "", because nothing in the citation says which,
                                         and choosing would publish text under a citation
                                         that does not name it. No instance on the 2024
                                         edition; refused rather than left to first-wins."""
    if not prints:
        return ""
    with_text = [p for p in prints
                 if constitution_section_body_chars(p, section)
                 >= CONST_SECTION_MIN_BODY_CHARS]
    if len(with_text) > 1:
        return ""
    return with_text[0] if with_text else prints[0]


def snapshot_slice(doc_id: str, snapshot_id: str, raw_text: str) -> str:
    """The portion of a shared snapshot's text that a document's '## Full text' covers.
    Used identically by the migration generator and verify_provenance so coverage is
    measured against the same slice that was transcribed. Default: whole text."""
    if snapshot_id == "oregon-constitution":
        m = ORCONST_ID_RE.match(doc_id)
        if not m:
            return ""
        return constitution_section_slice(ws_only(raw_text),
                                          orconst_article_designation(m.group(1)),
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
    # The OARD application's own version, printed in every rule page's footer (#244). It
    # moved v2.1.7 -> v2.1.8 and re-stamped every OAR hash without a word of rule text
    # changing. UNLIKE THE THREE ABOVE this one matches VISIBLE text -- html_to_text keeps
    # it -- which is exactly the case snapshot_identity.py (#207) was built to catch.
    rb"(?<=class=\"colophon\">)\s*v\d+\.\d+\.\d+",
]


def normalize_volatile(data: bytes) -> bytes:
    for pat in VOLATILE_PATTERNS:
        data = re.sub(pat, b"", data)
    return data


# A DIVISION'S INGEST STATUS IS DERIVED FROM ITS RULES', not written independently (#236).
# It used to be stored and could disagree: 2,716 divisions said `not_ingested` while every
# rule under them read `ingested`, because ingest_oar carried the previous value across on
# the branch that looked like it was promoting it. A stored value that nothing reconciles
# with the rows beneath it is a false statement about this mirror, which is CONTEXT.md's
# `could not check is never is not there` in its data form.
#
# FIVE WORDS, NOT THREE (#298). The original three-word aggregate (`ingested`,
# `partially_ingested`, `not_ingested`) counted only the literal rule-level word `ingested`
# and folded everything else -- no rules at all, every rule `renumbered`, every rule
# `not_served`, rules with an undeclared status -- into `not_ingested`. Three of those were
# wrong in different ways, measured on `main` at 7e850ecca6: NO RULES AT ALL is *could not
# check* reported as *is not there*, the exact substitution AGENTS.md's overriding rule
# names; EVERY RULE `renumbered` means the division IS served, just under other numbers --
# `not_ingested` is a false claim about the mirror, not merely an imprecise one; EVERY RULE
# `not_served` is a *reasoned* absence (OARD serves nothing recognizable for it, likely
# repealed) whose reason `not_ingested` throws away. `no_rules` and `not_served` are the two
# new words that give those states back a name; `renumbered` gets no new word of its own --
# it joins `ingested` in the HELD side of `ingest_status.HELD_INGEST_STATUSES`, which is
# exactly what "IS served, elsewhere" means at the granularity this aggregate already
# reports at (a `served_as` pointer is one attribute of a rule row, readable directly, not
# a distinction this coarser aggregate has ever tried to preserve for the literally-ingested
# case either).
# THE FIVE ORIGINAL WORDS, PLUS THE TWO REASONED-ABSENCE WORDS #298 LEFT GENERIC (below).
# `not_sliceable` and `needs_registry` are declared, specific ingest-status words
# (`ingest_status.INGEST_STATUS_VALUES`, #333) the same way `not_served` is -- a division
# whose rules are UNIFORMLY one of them is exactly the shape #298 already carved `not_served`
# out for, so it gets the same treatment rather than falling into the generic word. Neither
# has ever been written to a rule in this corpus (CONTEXT.md's *Ingest status* census reads
# 0 for both), so nothing in `division_status()` below could return either of these two
# TODAY -- they are declared here so that the day one is, the return value is a member of
# this tuple rather than a silent seventh word nothing named.
DIVISION_STATUSES = ("ingested", "partially_ingested", "not_ingested", "not_served",
                     "not_sliceable", "needs_registry", "no_rules")


def division_status(rules) -> str:
    """THE ONE DECLARATION: what a division's ingest status means relative to its rules.

    `partially_ingested` had been written onto exactly one row by nobody and read by
    nothing. Deriving gives it the meaning it never had -- SOME but not all -- rather than
    retiring a word the data turns out to need for a real, if small, share of divisions
    (`catalog_agreement.py --check` prints the live count on every run rather than this
    docstring restating one that would only go stale the way #306 already found one had).

    HELD comes from `ingest_status.HELD_INGEST_STATUSES` (#333's declared vocabulary),
    imported here rather than restated -- a rule counts toward this division being served
    if it is `ingested` OR `renumbered`, the same two words that vocabulary already marks
    held. Imported lazily (inside the function body, not at module top level): see
    `_ledger()`'s docstring below for why a top-level import of anything that itself
    imports `repo_lib` would be a real, invocation-order-dependent cycle from this
    particular module, not merely an unlikely one.
    """
    if not rules:
        # NO RULES AT ALL IS NOT A MEASUREMENT OF ZERO (#298). `division_status()` sees
        # only this list, never the division row it came from -- so even on the days every
        # committed empty division carries a mechanically-confirmed
        # CONFIRMED_EMPTY_DIVISION_MARK or CLAIMED_ELSEWHERE_DIVISION_MARK note
        # (`catalog_oar.py`'s own "AN EMPTY DIVISION IS A CLAIM, NOT A GAP"), THIS function
        # has no way to tell that confirmation apart from a division nobody has enumerated
        # yet -- so it names the state neutrally, `no_rules`, rather than asserting either.
        return "no_rules"
    from ingest_status import HELD_INGEST_STATUSES, INGEST_STATUS_VALUES
    held = sum(1 for r in rules if r.get("status") in HELD_INGEST_STATUSES)
    if held == len(rules):
        return "ingested"
    if held > 0:
        return "partially_ingested"
    # HELD == 0 from here down: nothing in this division is served. A REASONED ABSENCE --
    # not_served, not_sliceable, needs_registry: every declared word #333 marks NOT held and
    # is not the generic `not_ingested` -- keeps its own reason rather than being flattened,
    # the same move #298 made for `not_served` alone, generalized to every word that
    # vocabulary declares rather than one literal restated here (#298's own scope note: "or,
    # symmetrically, some other named state ... a judgment call for whoever picks this up").
    # A division whose rules mix TWO DIFFERENT reasoned-absence words, or mix a reasoned
    # word with a rule that literally says `not_ingested`, has no single reason to report and
    # still falls to the generic word -- #298 only names the UNIFORM case as a defect.
    reasoned = set(INGEST_STATUS_VALUES) - set(HELD_INGEST_STATUSES) - {"not_ingested"}
    statuses = {r.get("status") for r in rules}
    if len(statuses) == 1 and statuses <= reasoned:
        return next(iter(statuses))
    return "not_ingested"


def snapshot_text(raw: bytes) -> str:
    """THE TEXT OF AN HTML SNAPSHOT, declared once.

    Both spellings of a snapshot's identity start here: the `.txt` committed beside the
    `.html`, and the text `content_hash` hashes. They used to be derived separately --
    `html_to_text(raw)` for the .txt, `html_to_text(normalize_volatile(raw))` for the
    hash -- and agreed only by luck, because every volatile pattern happened to match
    markup `html_to_text` discarded anyway.

    #244 added a pattern that matches VISIBLE text (the OARD footer version), and the two
    derivations disagreed on every OAR rule at once. snapshot_identity.py (#207)
    caught it and named it; this function removes the second derivation so it cannot
    recur for the next pattern.
    """
    from html_to_text import html_to_text
    return html_to_text(normalize_volatile(raw))


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
    if fmt == "pdf":
        import subprocess
        proc = subprocess.run(["pdftotext", "-layout", "-", "-"], input=raw,
                              capture_output=True, check=False)
        text = proc.stdout.decode("utf-8", errors="replace") if proc.returncode == 0 else ""
    elif fmt in ("html", "xml"):
        text = snapshot_text(raw)
    else:
        # binary formats with no text extractor (xls/xlsx/docx): raw-byte hash
        return hashlib.sha256(raw).hexdigest()
    return normalized_text_hash(text) or hashlib.sha256(raw).hexdigest()


# Below this many characters of extracted text, hashing the text says nothing about the
# content (an image-only scan, a page that failed to render), so every caller falls back to
# the raw bytes it was extracted from.
MIN_HASHABLE_TEXT_CHARS = 200


def normalized_text_hash(text: str) -> str | None:
    """THE CONTENT HASH OF A PAGE, declared once: sha256 of its whitespace-normalized
    extracted text. None when there is too little text for that to mean anything.

    Three callers need the same number from three starting points — a fresh fetch
    (`content_hash`), the committed .txt beside a snapshot (`hash_snapshot`), and a
    candidate page held as text (`ingest_constitution.py --drift`) — and a second spelling
    of it would make a drift report and the group's recorded sha256 disagree about whether
    the page moved."""
    norm = normalize_ws(text)
    if len(norm) < MIN_HASHABLE_TEXT_CHARS:
        return None
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def hash_snapshot(doc_id: str, fmt: str, snapshot_dir: Path = SNAPSHOT_DIR) -> str:
    """CI-stable content hash: sha256 of the whitespace-normalized text already
    committed in <id>.txt (produced once at ingestion time), never re-derived from the
    .pdf/.html at verification time. Falls back to the raw source file's bytes if no
    .txt exists or it's too short to be meaningful (image-only scans)."""
    raw = (snapshot_dir / f"{doc_id}.{fmt}").read_bytes()
    txt_path = snapshot_dir / f"{doc_id}.txt"
    if txt_path.is_file():
        committed = normalized_text_hash(
            txt_path.read_text(encoding="utf-8", errors="replace"))
        if committed:
            return committed
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


# ------------------------------------------------------------------------------ check rules
#
# THE TWO PROPERTIES #316 AND #298 FIXED, given named rules and a `--selftest` that watches
# each one fire -- `content-dir-declared-present` against a real fixture on disk, broken and
# restored; `division-status-not-collapsed` against `division_status()`, a pure function,
# fed each collapsed state's input directly rather than a fixture mutated on disk -- the same
# discipline every other `--check`/`--selftest` pair in this repo proves itself with, adopted
# here via `check_rule_ledger.RuleLedger` (#319) rather than a fourth hand-rolled `_FIRED` set.

CHECK_RULES = (
    "content-dir-declared-present",
    "division-status-not-collapsed",
)

# BUILT LAZILY, NOT AT MODULE TOP LEVEL. `check_rule_ledger.py` itself does `from repo_lib
# import Checks` -- a top-level `from check_rule_ledger import RuleLedger` HERE would be a
# real, invocation-order-dependent cycle, not merely an unlikely one: every existing
# `--check`/`--selftest` that imports `check_rule_ledger` (legal_status.py, ingest_status.py,
# catalog_agencies.py, catalog_oar.py, and check_rule_ledger.py's own `--selftest`) imports
# IT first, which starts loading THIS file fresh to satisfy `from repo_lib import Checks` --
# and if this file's own top level then tried `import check_rule_ledger`, Python would find
# `check_rule_ledger` already registered in `sys.modules` but paused mid-execution, at the
# exact line waiting on THIS import, with its `RuleLedger` class not yet defined --
# `ImportError: cannot import name 'RuleLedger' from partially initialized module`, on the
# single most common invocation shape in this repo's CI. Deferred to call time instead: by
# the time any code actually CALLS `_ledger()`, this module -- whatever name it was loaded
# under -- has already finished executing its own top level, so there is nothing left to be
# circular about. `division_status()` above imports `ingest_status` the same way and for
# the same reason.
_LEDGER = None
Failure = None  # bound by _ledger(); AST-scanned by name, so proofs below call it bare


def _ledger():
    global _LEDGER, Failure
    if _LEDGER is None:
        from check_rule_ledger import RuleLedger
        _LEDGER = RuleLedger(CHECK_RULES, __file__)
        Failure = _LEDGER.Failure
    return _LEDGER


def _proof_missing_content_dir_refuses(check) -> None:
    """#316, broken on a scratch tree standing in for REPO_ROOT -- never the real corpus --
    so this proves the refusal without depending on `rules/` actually existing to fail.

    TWO WAYS TO BREAK IT, because #316 names two: a declared dir that does not exist, and one
    that exists but cannot be listed (permissions, a bad mount, a `git sparse-checkout`
    slice) -- `Path.rglob` silently drops the latter's files rather than raising, so a
    `--selftest` that only proved the first case would leave the second exactly as blind as
    the defect it was written to catch."""
    import tempfile
    global REPO_ROOT
    real_root = REPO_ROOT
    try:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in CONTENT_DIRS:
                (root / name).mkdir()
            REPO_ROOT = root
            check("every declared content dir present yields no findings and raises nothing",
                  list(content_files()) == [])

            (root / "rules").rmdir()  # BREAK IT: one declared dir goes missing
            raised = None
            try:
                list(content_files())
            except MissingContentDir as e:
                raised = e
            if raised is not None:
                Failure("content-dir-declared-present", "content_files()", str(raised))
            check("a missing declared content dir raises MissingContentDir, naming it",
                  raised is not None and "rules" in str(raised))

            # THE SCOPED-CALLER CASE (`dirs=(...)`, added for check_updates.py's
            # `_chapter_html_scope()`): the #316 guarantee must hold even for a caller
            # that never asked about `rules/` -- a missing/unreadable check that only
            # covered the requested subset would let a scoped caller report a clean,
            # narrower corpus while a directory it never looked at silently vanished.
            raised_scoped = None
            try:
                list(content_files(dirs=("statutes", "constitution")))
            except MissingContentDir as e:
                raised_scoped = e
            check("a missing content dir OUTSIDE a caller's requested `dirs=` scope still "
                  "raises MissingContentDir, naming it (the #316 guarantee is not narrowed "
                  "by scoping the walk)",
                  raised_scoped is not None and "rules" in str(raised_scoped))

            # `rules` is left missing here on purpose -- both branches below re-create it
            # themselves (present-but-unreadable needs it to exist first).

            running_as_root = os.geteuid() == 0 if hasattr(os, "geteuid") else True
            if running_as_root:
                # Permission bits don't restrict root, so chmod 000 can't reproduce the
                # unreadable case here -- report that honestly rather than letting a
                # would-be-refusal read as one that fired (the same substitution this rule
                # exists to catch, one level up: an environment that could not exercise the
                # mutation is not an environment that found the guard unnecessary).
                check("present-but-unreadable content dir raises MissingContentDir, naming it "
                      "(SKIPPED: running as root, permission bits do not apply)", True)
            else:
                (root / "rules").mkdir()  # BREAK IT DIFFERENTLY: present, but unlistable
                os.chmod(root / "rules", 0o000)
                raised = None
                try:
                    list(content_files())
                except MissingContentDir as e:
                    raised = e
                finally:
                    os.chmod(root / "rules", 0o755)  # RESTORE IT -- TemporaryDirectory
                    # cleanup below has to be able to walk back into this directory
                if raised is not None:
                    Failure("content-dir-declared-present", "content_files()", str(raised))
                check("a present-but-unreadable content dir raises MissingContentDir, naming it",
                      raised is not None and "rules" in str(raised))
    finally:
        REPO_ROOT = real_root  # RESTORE IT


def _proof_committed_text_resolves_a_rename(check) -> None:
    """Code review of #341: `committed_text()` used to answer "nothing to compare against"
    for a path renamed in the same commit range it is being compared across -- exactly the
    silence a caller like `stated_census.py`'s coverage floor treats as vacuously satisfied,
    so a renamed-and-shrunk document passed with no warning at all. A disposable git repo
    (never REPO_ROOT -- `git diff -M`/`git show` must never run against the real corpus
    mid-selftest) proves the fix directly: commit A creates `old.md`; commit B (`git mv`)
    renames it to `new.md` with different content. `committed_text(new.md, A, head_ref=B)`
    must recover commit A's TEXT UNDER THE OLD NAME, not None."""
    import subprocess
    import tempfile
    global REPO_ROOT
    real_root = REPO_ROOT
    try:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)

            def g(*args):
                return subprocess.run(["git", "-C", str(root), *args],
                                      capture_output=True, text=True, check=True)
            g("init", "-q")
            g("config", "user.email", "selftest@example.invalid")
            g("config", "user.name", "selftest")
            # Mostly-identical, longer content -- `git diff -M`'s DEFAULT 50% similarity
            # threshold does not pair a tiny file whose content changes as much as the
            # shrink itself does (measured: a one-line "12 things" -> "5 things" file was
            # NOT detected as a rename at all, understating what real prose looks like).
            body = "figure: 12 things\n" + ("filler line unrelated to the count\n" * 20)
            (root / "old.md").write_text(body)
            g("add", "old.md")
            g("commit", "-q", "-m", "A")
            commit_a = g("rev-parse", "HEAD").stdout.strip()
            g("mv", "old.md", "new.md")
            (root / "new.md").write_text(body.replace("12 things", "5 things"))  # shrunk,
            g("commit", "-a", "-q", "-m", "B: rename and shrink")               # same commit
            commit_b = g("rev-parse", "HEAD").stdout.strip()

            REPO_ROOT = root
            got = committed_text(Path("new.md"), commit_a, head_ref=commit_b)
            check("a same-range rename is resolved to the OLD name's text at the base ref, "
                  "not reported as nothing-to-compare", got == body)

            still_new = committed_text(Path("genuinely-new.md"), commit_a, head_ref=commit_b)
            check("a path that is genuinely new since the base ref (no rename pairs with "
                  "it) is still None, not a false match", still_new is None)
    finally:
        REPO_ROOT = real_root  # RESTORE IT


def _proof_division_status_distinguishes_the_five_states(check) -> None:
    """#298, exercised directly -- division_status() is a pure function, so "break it" is
    feeding it each collapsed state's input rather than mutating a fixture on disk.

    Every case below also has its return value checked against DIVISION_STATUSES -- the
    declared table this function may return from -- so a case that started returning a
    seventh word nothing declared would fail here even though nothing scans for it the way
    `ingest_status.py`'s AST-based ledger scans a vocabulary's writers."""
    def in_table(word):
        return word in DIVISION_STATUSES

    no_rules = division_status([])
    check("a division with no rules at all is not conflated with not_ingested",
          no_rules == "no_rules" and in_table(no_rules))

    check("every rule explicitly not_ingested is genuinely not_ingested",
          division_status([{"status": "not_ingested"}]) == "not_ingested")

    every_not_served = division_status(
        [{"status": "not_served"}, {"status": "not_served"}])
    check("every rule not_served keeps its own reasoned word, not the generic one",
          every_not_served == "not_served" and in_table(every_not_served))

    # THE SAME TREATMENT, FOR THE OTHER TWO REASONED-ABSENCE WORDS #333 DECLARES. Neither
    # has ever been written to a real rule (CONTEXT.md's census reads 0 for both), so this is
    # the only place either composition is exercised at all -- a `--selftest` that only
    # proved `not_served` would leave `not_sliceable` and `needs_registry` exactly as
    # untested as the defect #298 exists to catch, one word over.
    every_not_sliceable = division_status(
        [{"status": "not_sliceable"}, {"status": "not_sliceable"}])
    check("every rule not_sliceable keeps its own reasoned word too",
          every_not_sliceable == "not_sliceable" and in_table(every_not_sliceable))
    every_needs_registry = division_status([{"status": "needs_registry"}])
    check("...and so does every rule needs_registry",
          every_needs_registry == "needs_registry" and in_table(every_needs_registry))

    every_renumbered = division_status([{"status": "renumbered"}])
    check("every rule renumbered means the division IS served, not not_ingested",
          every_renumbered == "ingested" and in_table(every_renumbered))

    ingested_and_not_served = division_status(
        [{"status": "ingested"}, {"status": "not_served"}])
    check("ingested beside not_served -- the shape nearly every real partially_ingested "
          "division in the committed catalog actually has -- is partially, not fully, ingested",
          ingested_and_not_served == "partially_ingested" and in_table(ingested_and_not_served))
    check("renumbered and ingested rules together are still fully served",
          division_status([{"status": "renumbered"}, {"status": "ingested"}]) == "ingested")
    check("one held rule among several unheld ones is partially, not not, ingested",
          division_status([{"status": "renumbered"}, {"status": "not_ingested"}])
          == "partially_ingested")
    check("a mix of two DIFFERENT reasoned-absence words has no single reason to report "
          "and falls to the generic word",
          division_status([{"status": "not_served"}, {"status": "not_sliceable"}])
          == "not_ingested")
    check("a mix of not_served and other unheld reasons falls to the generic word",
          division_status([{"status": "not_served"}, {"status": "not_ingested"}])
          == "not_ingested")
    check("a status nobody declared is not silently counted as held",
          division_status([{"status": "an-undeclared-word"}]) == "not_ingested")

    if (no_rules == "no_rules" and every_not_served == "not_served"
            and every_not_sliceable == "not_sliceable"
            and every_needs_registry == "needs_registry"
            and every_renumbered == "ingested"
            and ingested_and_not_served == "partially_ingested"):
        Failure("division-status-not-collapsed", "division_status()",
                "no rules, every reasoned-absence word (not_served, not_sliceable, "
                "needs_registry) and every-renumbered are told apart from not_ingested and "
                "from each other, rather than all of them reading as one word")


def selftest() -> int:
    check = Checks()
    _ledger()  # binds the module-level `Failure` name before the proofs above call it bare
    _proof_missing_content_dir_refuses(check)
    _proof_committed_text_resolves_a_rename(check)
    _proof_division_status_distinguishes_the_five_states(check)

    gaps = _LEDGER.gaps()
    declared_gap = (f" (emitted-not-declared={sorted(gaps.emitted_but_undeclared)}, "
                    f"declared-not-emitted={sorted(gaps.unemitted_but_declared)})"
                    if gaps.emitted_but_undeclared or gaps.unemitted_but_declared else "")
    check("every rule this module can report is declared" + declared_gap, not declared_gap)
    unfired_gap = f" (unfired={sorted(gaps.unfired)})" if gaps.unfired else ""
    check("...and every declared rule was watched firing, not merely listed" + unfired_gap,
          not unfired_gap)
    return check.report(
        f"{_LEDGER.demonstrated_count} rule(s) declared, every one watched firing -- "
        "content-dir-declared-present against a broken fixture and restored, "
        "division-status-not-collapsed against every collapsed input directly -- selftest")


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0]
                                  if __doc__ else "repo_lib")
    ap.add_argument("--selftest", action="store_true",
                     help="prove content_files() and division_status() can each fail, "
                          "named rule by named rule")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
