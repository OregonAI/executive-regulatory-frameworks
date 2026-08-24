"""Shared helpers for repo validation tooling."""
import datetime
import hashlib
import html
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
# one into the other. Kept as a SOURCE STRING, not a compiled pattern, because
# `register_scheme` compiles pattern strings itself (corpus-toolkit#202) and a compiled
# object would have to be unwrapped again at every use.
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
DIVISION_STATUSES = ("ingested", "partially_ingested", "not_ingested")


def division_status(rules) -> str:
    """THE ONE DECLARATION: what a division's ingest status means relative to its rules.

    `partially_ingested` had been written onto exactly one row by nobody and read by
    nothing. Deriving gives it the meaning it never had -- SOME but not all -- rather than
    retiring a word the data turns out to need for 43 divisions.
    """
    if not rules:
        return "not_ingested"
    ingested = sum(1 for r in rules if r.get("status") == "ingested")
    if ingested == len(rules):
        return "ingested"
    return "not_ingested" if ingested == 0 else "partially_ingested"


def snapshot_text(raw: bytes) -> str:
    """THE TEXT OF AN HTML SNAPSHOT, declared once.

    Both spellings of a snapshot's identity start here: the `.txt` committed beside the
    `.html`, and the text `content_hash` hashes. They used to be derived separately --
    `html_to_text(raw)` for the .txt, `html_to_text(normalize_volatile(raw))` for the
    hash -- and agreed only by luck, because every volatile pattern happened to match
    markup `html_to_text` discarded anyway.

    #244 added a pattern that matches VISIBLE text (the OARD footer version), and the two
    derivations disagreed on all 36,953 OAR rules at once. snapshot_identity.py (#207)
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
