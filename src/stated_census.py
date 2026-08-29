#!/usr/bin/env python3
"""Gate a figure written in prose against the census that produces it, for any document
this is pointed at (#306).

  python3 src/stated_census.py --check [PATH...]  # CI: every stated figure in PATH (default
                                                    #     CONTEXT.md) agrees with its
                                                    #     measurement, or is marked as one
                                                    #     that cannot drift; every docstring
                                                    #     citing CONTEXT.md by term names a
                                                    #     term CONTEXT.md actually has
  python3 src/stated_census.py --selftest          # CI: every rule --check enforces fires

WHY THIS EXISTS. On 2026-08-28, five of CONTEXT.md's figures were found stale --
`36,474`/`5,608` ingested, `34,836`/`2,083` legal status, `185` History lines, `81`
chapters, `81` relations -- staled by a commit that reached every generated view and did
not reach the glossary. They were corrected by hand in #304. That is the FIFTH hand sweep
of this shape: #299 and #279 are the same failure in docstrings, and `oar_watch_coverage.py`
calls its own instance "the ninth case of one fact declared twice with nothing gating
agreement." The repo had already built FOUR separate bespoke gates for exactly this --
`chapter-page-count-current`, `note-agrees-with-refresh`, `note-covers-fields`,
`oar_watch_coverage.py` -- each one regex, one comparison, one failure rule, for one figure.
This is the general form, so the fifth hand sweep does not need a sixth.

WHILE BUILDING THIS GATE AGAINST THE REAL CORPUS (not a fixture), it found a SIXTH instance
CONTEXT.md's own hand sweeps never suspected: the "Hash observation" glossary entry stated
"484 individual rule pages in chapters 105, 122, 125 and 128 ... THE OVERLAP IS ZERO", while
`oar_watch_coverage.py`'s OWN gate -- which checks the ADR, not CONTEXT.md -- had already
tracked the manifest's growth to 6,614 rule pages across 136 chapters and a 477-rule
overlap. The ADR stayed in sync because something reads it; the glossary drifted because
nothing did. Fixed in the same change that adds the gate, which is the point.

MECHANISM: AN ANCHORED TAG, NOT CONTAINMENT.

    `not_served` (49 <!--census:oar.not_served-->)

Containment (`if rendered not in text`, `oar_watch_coverage.py:94`'s shape before this
module existed) was CONSIDERED AND REJECTED: `not_served` drifting from 49 to 43 would pass
containment, because "43 of them" already appears elsewhere in CONTEXT.md by coincidence. A
guard that asserts "the right number appears somewhere" rather than "this number, right
here, is the right one" passes while the thing it names goes unverified. The tag is
ANCHORED to the one occurrence it gates: the number immediately before `<!--census:...-->`,
with nothing but whitespace between them -- a line wrap included, since this file wraps
prose at ~90 columns and a tag is routinely pushed to the following line, but no other word
or number.

EVERY NUMBER IS ACCOUNTED FOR. A figure in a glossary entry (a `**Term**:` block) is either
tagged to a census (compared against a measurement on every run) or marked an OBSERVATION
(`<!--observed:YYYY-MM-DD-->`, a dated fact that cannot drift and is never gated). An
untagged, unmarked figure is a FAILURE -- opt-in-only tagging reproduces the exact hole this
exists to close, since a curator who forgets to tag a new figure is the failure mode #304
found five instances of.

WHAT COUNTS AS A FIGURE, AND WHAT DOES NOT. A bare integer (optionally comma-grouped) is a
figure UNLESS it is an identifier rather than a measurement: preceded (allowing only commas,
"and"/"&" and further digits between, i.e. a LIST) by a word naming a citation scheme --
`ADR`, `OAR`, `ORS`, `EO`, `OAM`, `chapter(s)`, `division(s)`, `section(s)`, `article(s)`, or
a month name (`August 2026` names a month, not a count); an issue reference (`#229`,
excluded structurally by the number pattern itself, no space to insert a word between); part
of a `X.Y` citation (`ORS 684.130`) or a hyphenated identifier (`125-010-0005`, `2026-08-22`,
`20-03`) -- both excluded the same structural way, since a citation's parts are never
separated from their punctuation by whitespace the way a stated count is. See
`_excluded_by_context()` for the one regex this rule is, and `NUMBER_RE` for the structural
half. ONE EXPLICIT EXEMPTION, narrower than the rule: a number immediately followed by `+`
(`545+`) is a stated FLOOR, not an exact count -- CONTEXT.md's *Chapter selection* entry
phrases its one such figure that way on purpose, precisely so it cannot go stale by
construction, and converting it to a tagged exact count would be undoing that choice rather
than serving it.

THE SECOND RULE: A DOCSTRING'S CITED AUTHORITY MUST CONTAIN WHAT IT IS CITED FOR (#305's
follow-on). #305 found 25 sites citing `CONTEXT.md` as the source of a rule CONTEXT.md did
not, at the time, contain -- a citation is itself a stated fact ("this document says this")
and #305's fix was applied by hand, one docstring at a time, with no gate behind it. Every
citation this codebase writes in that shape names a GLOSSARY TERM: `CONTEXT.md, *Legal
status*`, `CONTEXT.md, *Registry slug*`. That is mechanically checkable the same way a
census tag is: read every such citation out of every module in `src/`, and refuse one naming
a term CONTEXT.md's own glossary does not carry as a `**Term**:` heading -- the general form
of the exact defect #305 fixed once.

DOCUMENT-AGNOSTIC. `cmd_check()` takes a list of paths; CONTEXT.md is the default and the
first adapter, not the only one a future document can point this at. The citation-integrity
rule is unscoped to the path argument -- it is a repo-wide invariant about `src/`, checked on
every run regardless of which document's figures were asked about.
"""
import argparse
import ast
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml

from repo_lib import REPO_ROOT

SRC = REPO_ROOT / "src"
DEFAULT_DOC = REPO_ROOT / "CONTEXT.md"

# Every rule this module can report. Declared rather than counted at run time so a rule
# added with no proof is visible as a list that did not grow, matching `legal_status.py`'s
# `CHECK_RULES` -- `--selftest` asserts every name here was watched firing during the run.
CHECK_RULES = (
    "document-is-readable",
    "known-census-namespace", "known-census-key", "census-is-measurable",
    "stated-figure-matches-its-census",
    "figure-is-accounted-for",
    "observation-date-is-valid",
    "citation-names-an-existing-term",
    "src-file-is-readable",
)

_FIRED: set = set()


class Failure:
    """One rule, the site it is about, and what is wrong -- recorded on construction (like
    `legal_status.Failure`) so no proof has to remember to say it fired."""
    __slots__ = ("rule", "site", "detail")

    def __init__(self, rule, site, detail):
        if rule not in CHECK_RULES:
            raise ValueError(f"{rule!r} is not a declared rule -- add it to CHECK_RULES")
        self.rule, self.site, self.detail = rule, site, detail
        _FIRED.add(rule)

    def __str__(self):
        return f"  FAIL [{self.rule}] {self.site}: {self.detail}"


def emitted_rules(source=None) -> set:
    """Every rule name this module can report, read out of its own syntax tree -- same
    arrangement as `legal_status.emitted_rules()`. `Failure.__init__` already refuses an
    undeclared rule name the moment that construction actually RUNS, but a site that is
    unreachable in every `--selftest` fixture never runs, so a dynamic-only check
    (`set(CHECK_RULES) - _FIRED`, below) is blind to it -- it would first crash in
    production, with a raw `ValueError`, the day some real document finally took that
    branch. Reading the AST instead catches it in `--selftest`, on every run, without
    needing the branch to execute."""
    tree = ast.parse(source if source is not None else Path(__file__).read_text())
    return {n.args[0].value for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "Failure" and n.args
            and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)}


# --------------------------------------------------------------------- the figure detector

# STRUCTURAL exclusion: a number directly touching a `#`, a letter, a `.` or a `-` on either
# side is part of an identifier (an issue ref, a citation, a hyphenated id) rather than a
# bare stated count, and is never a candidate figure at all -- no context lookup needed,
# because a genuine stated count is never glued to its neighbouring punctuation this way.
NUMBER_RE = re.compile(r"(?<![\w#.\-])(?P<num>\d{1,3}(?:,\d{3})+|\d+)(?![\w.\-])")

CENSUS_TAG_RE = re.compile(
    r"<!--census:(?P<ns>[a-z_]+)\.(?P<key>[A-Za-z0-9_-]+)-->")
OBSERVED_TAG_RE = re.compile(r"<!--observed:(?P<date>\d{4}-\d{2}-\d{2})-->")

# CONTEXTUAL exclusion: a number that survives the structural filter but sits in a LIST
# introduced by a citation-scheme word or a month name -- "chapters 105, 122, 125 and 128",
# "August 2026" -- is still naming which thing, not counting how many. The lookback window is
# generous (80 chars) because a list can run several items long; what stops it from matching
# across a real sentence boundary is that every character between the introducing word and
# here must itself be a digit, comma, "and"/"&", or whitespace -- any other word breaks it.
_EXCLUDED_CONTEXT_RE = re.compile(
    r"\b(chapters?|divisions?|sections?|articles?|adr|oar|ors|eo|oam|"
    r"january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\b(?:[\s,]|and|&|\d)*$", re.I)


def _excluded_by_context(text: str, start: int) -> bool:
    """Whether the number at `start` is an identifier named in a citation-scheme or
    month-name list, rather than a stated count -- see the module docstring's
    "WHAT COUNTS AS A FIGURE" section for the full reasoning and examples."""
    return bool(_EXCLUDED_CONTEXT_RE.search(text[max(0, start - 80):start]))


TERM_HEADER_RE = re.compile(r"^\*\*([^*]+)\*\*:", re.M)
SECTION_HEADER_RE = re.compile(r"^##[ \t]", re.M)


def glossary_blocks(text: str) -> list:
    """[(term, start, end), ...] -- the span of every `**Term**:` glossary entry in `text`,
    from its own header to the next header of EITHER kind (a new term, or a `##` section
    break). Figures are only ever accounted for INSIDE a block: the file's introductory
    prose and its section headings state no glossary figures of their own."""
    headers = sorted(
        [(m.start(), m.group(1)) for m in TERM_HEADER_RE.finditer(text)]
        + [(m.start(), None) for m in SECTION_HEADER_RE.finditer(text)])
    blocks = []
    for i, (pos, term) in enumerate(headers):
        if term is None:
            continue
        end = headers[i + 1][0] if i + 1 < len(headers) else len(text)
        blocks.append((term, pos, end))
    return blocks


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


# ------------------------------------------------------------------------- the censuses

# {namespace: () -> {key: int}}. Each callable reads COMMITTED data fresh on every call --
# no caching across a run, matching how `legal_status.py` and `oar_watch_coverage.py` read
# their sources once per invocation -- so a --check run always measures the corpus as it
# stands right now, never a value memoized from an earlier document read in the same run.


def _oar_measurement() -> dict:
    """`_meta/catalog/oar.yml`'s ingest-status tally (CONTEXT.md's *Ingest status*),
    read via `catalog_oar.status_counts()` -- the one place that count is computed."""
    import catalog_oar
    counts = catalog_oar.status_counts(catalog_oar.load_catalog())
    return {k: v for k, v in counts.items() if isinstance(v, int)}


def _agencies_measurement() -> dict:
    """The agency registry's four censuses (#306's own `*_counts()` additions to
    `catalog_agencies.py`), flattened into one namespace with a category prefix per
    function so `authority_total`, `chapter_total` and `relation_total_orgs` -- three
    different counts that could otherwise collide on a bare `total` -- stay distinguishable.
    `relation_counts()` is itself already prefixed (`kind__...`, `source__...`,
    `basis__...`), so its keys arrive here as e.g. `relation_kind__undetermined`."""
    import catalog_agencies as ca
    cat = ca.load()
    orgs = cat.get("organizations") or []
    rows = [o for o in orgs if isinstance(o, dict)]
    out = {}
    out.update({f"authority_{k}": v for k, v in ca.authority_counts(orgs).items()})
    out.update({f"chapter_{k}": v for k, v in ca.chapter_counts(orgs).items()})
    out.update({f"name_{k}": v for k, v in ca.name_counts(orgs).items()
               if isinstance(v, int)})
    out.update({f"relation_{k}": v for k, v in ca.relation_counts(rows).items()})
    return out


def _oar_watch_measurement() -> dict:
    """The OAR hash watch's own coverage measurement (`oar_watch_coverage.measure()`,
    CONTEXT.md's *Hash observation*), with its two SET-valued fields (`watched_chapters`,
    `named_chapters`) reduced to their counts -- `measure()` returns the sets themselves
    because `oar_watch_coverage.py`'s own gate needs the members, not just how many; this
    namespace only ever needs the count a glossary sentence states."""
    import oar_watch_coverage as owc
    manifest = yaml.safe_load(owc.MANIFEST.read_text())
    worklist = yaml.safe_load(owc.WORKLIST.read_text())
    rules_dir = owc.REPO_ROOT / "rules"
    mirrored = {p.name for p in rules_dir.iterdir() if p.is_dir()} if rules_dir.is_dir() \
        else set()
    m = owc.measure(manifest, worklist, mirrored)
    return {
        "watched": m["watched"], "watched_chapters": len(m["watched_chapters"]),
        "named": m["named"], "named_chapters": len(m["named_chapters"]),
        "overlap": m["overlap"],
        "mirrored_chapters": m["mirrored_chapters"], "mirrored_rules": m["mirrored_rules"],
    }


CENSUSES = {
    "oar": _oar_measurement,
    "agencies": _agencies_measurement,
    "oar_watch": _oar_watch_measurement,
}


def measured(ns: str, cache: dict) -> dict:
    """`CENSUSES[ns]()`, computed once per `cache` (one per `--check` run) -- so a document
    naming the same namespace in five tags pays the read once, not five times."""
    if ns not in cache:
        cache[ns] = CENSUSES[ns]()
    return cache[ns]


# ------------------------------------------------------------------------- rule: figures

def check_figures(path: Path, text: str, cache: dict) -> list:
    """Every stated figure in `path`'s glossary blocks, tagged, marked, mismatched, or
    unaccounted for -- as Failures. `text` and `cache` are passed in (rather than read
    here) so `--selftest` can fire every rule against a synthetic document and a synthetic
    census without touching the committed corpus."""
    failures = []
    label = str(path)
    for term, start, end in glossary_blocks(text):
        block = text[start:end]
        for m in NUMBER_RE.finditer(block):
            pos = start + m.start("num")
            if text[start + m.end("num"):start + m.end("num") + 1] == "+":
                continue  # a stated FLOOR ("545+"), exempt by design -- see module docstring
            if _excluded_by_context(text, pos):
                continue  # an identifier (a chapter/ORS/ADR/month reference), not a count
            site = f"{label}:{line_of(text, pos)}"
            stated = m.group("num")

            after = text[start + m.end("num"):start + m.end("num") + 80]
            census_m = CENSUS_TAG_RE.match(after.lstrip())
            observed_m = OBSERVED_TAG_RE.match(after.lstrip())

            if census_m:
                ns, key = census_m.group("ns"), census_m.group("key")
                tag = f"census:{ns}.{key}"
                if ns not in CENSUSES:
                    failures.append(Failure(
                        "known-census-namespace", site,
                        f"{stated!r} is tagged {tag!r}, and {ns!r} is not a registered "
                        f"census namespace ({', '.join(sorted(CENSUSES))}). A tag naming an "
                        "unknown measurement is refused rather than skipped -- a mistyped "
                        "namespace must not read as 'nothing to check'"))
                    continue
                try:
                    values = measured(ns, cache)
                except Exception as e:
                    failures.append(Failure(
                        "census-is-measurable", site,
                        f"{stated!r} is tagged {tag!r}, and measuring {ns!r} raised "
                        f"{type(e).__name__}: {e}. Could not measure is never reported as "
                        "agrees -- fix the measurement, or the figure cannot be gated"))
                    continue
                if key not in values:
                    failures.append(Failure(
                        "known-census-key", site,
                        f"{stated!r} is tagged {tag!r}, and the {ns!r} census has no "
                        f"{key!r} -- it has {', '.join(sorted(values))}"))
                    continue
                measured_value = values[key]
                stated_value = int(stated.replace(",", ""))
                if stated_value != measured_value:
                    failures.append(Failure(
                        "stated-figure-matches-its-census", site,
                        f"states {stated!r} tagged {tag!r}, and the measurement reads "
                        f"{measured_value:,}. The stated figure and the census disagree"))
            elif observed_m:
                date = observed_m.group("date")
                try:
                    datetime.date.fromisoformat(date)
                except ValueError:
                    failures.append(Failure(
                        "observation-date-is-valid", site,
                        f"{stated!r} is marked <!--observed:{date}-->, and {date!r} is not "
                        "a real calendar date"))
                # An observed mark is accepted and never gated further -- CONTEXT.md's
                # *Observation* entry is what makes that promise, and this is where it is
                # kept: nothing here compares the figure to any measurement.
            else:
                failures.append(Failure(
                    "figure-is-accounted-for", site,
                    f"{stated!r} in the {term!r} entry carries neither a "
                    "<!--census:namespace.key--> tag nor an <!--observed:YYYY-MM-DD--> "
                    "mark. Every figure in a glossary entry must be tagged to the "
                    "measurement that produces it, or marked as a dated observation that "
                    "cannot drift -- an untagged figure is exactly how #304's five stale "
                    "figures went unnoticed"))
    return failures


# -------------------------------------------------------------- rule: docstring citations

# `CONTEXT.md, *Term*` -- the one citation shape every module in src/ that names CONTEXT.md
# by term uses (#305's follow-on). `/` separates more than one term cited together
# (`CONTEXT.md, *Legal status* / *Ingest status*`).
CITATION_RE = re.compile(r"CONTEXT\.md,\s*(\*[^*]+\*(?:\s*/\s*\*[^*]+\*)*)")
TERM_RE = re.compile(r"\*([^*]+)\*")


def cited_terms(source: str) -> list:
    """[(term, line), ...] for every glossary term a `CONTEXT.md, *Term*` citation in
    `source` names, split on `/` for a citation naming more than one."""
    out = []
    for m in CITATION_RE.finditer(source):
        line = source.count("\n", 0, m.start()) + 1
        for t in TERM_RE.finditer(m.group(1)):
            out.append((t.group(1), line))
    return out


def citable_paths() -> list:
    """Every `src/*.py` this module's citation rule reads -- EXCLUDING ITSELF.
    `stated_census.py` is the one file in `src/` whose job is to talk ABOUT the
    `CONTEXT.md, *Term*` citation shape -- its own docstring and its own selftest fixtures
    necessarily contain literal example occurrences of it (including the very f-string this
    rule's own failure message is built from), and none of them is a refusal citing
    CONTEXT.md as its authority. Scanning itself would be the pattern matching its own
    definition, not a second instance of #305's defect -- the same reason a proof function
    is not counted as a writer elsewhere in this codebase (`legal_status.PROOF_FUNCTIONS`).

    The ONE place this exclusion is applied, so `check_citations()`'s count of what it
    checked and `cmd_check()`'s printed count of what it claims to have checked cannot
    drift apart the way they did before this function existed (#311)."""
    return sorted(p for p in SRC.glob("*.py") if p.resolve() != Path(__file__).resolve())


def check_citations(paths=None, glossary_text=None) -> list:
    """Every `CONTEXT.md, *Term*` citation in `paths` (default: `citable_paths()`) whose
    named term CONTEXT.md's own glossary does not carry -- the general form of the 25 sites
    #305 fixed by hand. `glossary_text` is CONTEXT.md's text, passed in so `--selftest` can
    fire this against a synthetic glossary without touching the committed file."""
    if paths is None:
        paths = citable_paths()
    if glossary_text is None:
        glossary_text = DEFAULT_DOC.read_text()
    known = {term for term, _, _ in glossary_blocks(glossary_text)}
    failures = []
    for p in paths:
        try:
            source = Path(p).read_text()
        except (OSError, UnicodeDecodeError) as e:
            # Could not check is never reported as is not there (AGENTS.md's overriding
            # rule): a src file this rule could not read had its citations NOT checked,
            # which is not the same as their all naming a real term. Before this rule
            # existed the bare `continue` this replaced reported the same outcome as a
            # file with no bad citations in it -- silently, with no rule behind it (#312).
            label = str(p)
            try:
                label = str(Path(p).relative_to(REPO_ROOT))
            except ValueError:
                pass
            failures.append(Failure(
                "src-file-is-readable", label,
                f"could not be read ({type(e).__name__}: {e}) -- its citations were not "
                "checked, which is not the same as their all naming a real term"))
            continue
        for term, line in cited_terms(source):
            if term not in known:
                label = str(p)
                try:
                    label = str(Path(p).relative_to(REPO_ROOT))
                except ValueError:
                    pass
                failures.append(Failure(
                    "citation-names-an-existing-term", f"{label}:{line}",
                    f"cites CONTEXT.md, *{term}* as authority, and CONTEXT.md carries no "
                    f"{term!r} glossary entry. A docstring citing a document as the "
                    "authority for a refusal must cite a document that CONTAINS the cited "
                    "text -- #305 found 25 sites doing exactly this for one phrase; this is "
                    "the general form"))
    return failures


# ---------------------------------------------------------------------------- commands

def check_document(path: Path, cache: dict) -> list:
    """Every figure-accounting failure in one document -- refuses (rather than skips) a
    document that cannot be read, per CONTEXT.md's *Could not check*: an unreadable
    document's figures are not verified, and that is a different finding from every figure
    in it agreeing."""
    try:
        text = path.read_text()
    except OSError as e:
        return [Failure("document-is-readable", str(path),
                        f"could not be read ({e}) -- its figures were not checked, which "
                        "is not the same as their all agreeing")]
    return check_figures(path, text, cache)


def cmd_check(paths) -> int:
    paths = [Path(p) for p in paths] if paths else [DEFAULT_DOC]
    cache: dict = {}
    failures = []
    for p in paths:
        failures += check_document(p, cache)
    failures += check_citations()

    if failures:
        for f in failures:
            print(f, file=sys.stderr)
        print(f"\n{len(failures)} stated-census violation(s)", file=sys.stderr)
        return 1

    n_tagged = n_marked = 0
    for p in paths:
        text = p.read_text()
        for term, start, end in glossary_blocks(text):
            block = text[start:end]
            for m in NUMBER_RE.finditer(block):
                pos = start + m.start("num")
                if text[start + m.end("num"):start + m.end("num") + 1] == "+":
                    continue
                if _excluded_by_context(text, pos):
                    continue
                after = text[start + m.end("num"):start + m.end("num") + 80].lstrip()
                if CENSUS_TAG_RE.match(after):
                    n_tagged += 1
                elif OBSERVED_TAG_RE.match(after):
                    n_marked += 1
    # SAME PATH LIST check_citations() ACTUALLY CHECKED, not a fresh `SRC.glob()` that
    # re-includes this module and reports a citation nothing above verified (#311).
    n_cited = sum(len(cited_terms(Path(p).read_text())) for p in citable_paths())
    print(f"{n_tagged} figure(s) tagged to a census, {n_marked} marked as observations, "
          f"across {len(paths)} document(s); {n_cited} CONTEXT.md citation(s) across "
          f"src/*.py, every one naming a term CONTEXT.md carries")
    return 0


# ------------------------------------------------------------------------------ selftest

def _fixture_glossary(body: str) -> str:
    """One glossary entry, `**Fixture**:`, wrapping `body` -- the minimal document
    `check_figures` can scan."""
    return f"**Fixture**:\nA fixture entry.\n{body}\n\n## Next section\nnothing here.\n"


def _fixture_cache(values: dict) -> dict:
    """A census cache pre-populated so `check_figures` never touches the committed corpus."""
    return {"fixture_ns": values}


def selftest() -> int:
    fails = []
    global CENSUSES
    real_censuses = CENSUSES
    CENSUSES = dict(real_censuses, fixture_ns=lambda: {})

    def fired(text, cache=None):
        return [f.rule for f in check_figures(Path("fixture.md"), text, cache or {})]

    # MUTATION 1: strike a digit -- a correctly tagged figure whose stated value no longer
    # matches the measurement.
    cache = _fixture_cache({"n": 49})
    text = _fixture_glossary("not_served (48 <!--census:fixture_ns.n-->)")
    got = fired(text, cache)
    if "stated-figure-matches-its-census" not in got:
        fails.append(f"FAIL struck-digit-is-caught: {got}")

    # The un-struck version must be clean.
    cache = _fixture_cache({"n": 49})
    text = _fixture_glossary("not_served (49 <!--census:fixture_ns.n-->)")
    got = fired(text, cache)
    if got:
        fails.append(f"FAIL a-correct-tag-produces-no-finding: {got}")

    # MUTATION 2: add an untagged number.
    text = _fixture_glossary("stray figure: 17 rules, no tag at all.")
    got = fired(text)
    if "figure-is-accounted-for" not in got:
        fails.append(f"FAIL untagged-number-is-caught: {got}")

    # MUTATION 3: retag to a different, REAL census whose value disagrees -- distinct from
    # an unknown namespace: this proves the resolver reads the NAMED key rather than
    # accepting any measurement anywhere that happens to match.
    cache = _fixture_cache({"n": 49, "m": 7})
    text = _fixture_glossary("not_served (49 <!--census:fixture_ns.m-->)")
    got = fired(text, cache)
    if "stated-figure-matches-its-census" not in got:
        fails.append(f"FAIL retag-to-a-disagreeing-census-is-caught: {got}")

    # MUTATION 4: name a census that does not exist.
    text = _fixture_glossary("not_served (49 <!--census:nonexistent.n-->)")
    got = fired(text, {})
    if "known-census-namespace" not in got:
        fails.append(f"FAIL unknown-namespace-is-caught: {got}")

    # A known namespace, unknown key.
    cache = _fixture_cache({"n": 49})
    text = _fixture_glossary("not_served (49 <!--census:fixture_ns.ghost-->)")
    got = fired(text, cache)
    if "known-census-key" not in got:
        fails.append(f"FAIL unknown-key-is-caught: {got}")

    # A namespace whose measurement function raises.
    boom_censuses = dict(CENSUSES)

    def _boom():
        raise RuntimeError("synthetic failure")
    boom_censuses["boom_ns"] = _boom
    CENSUSES = boom_censuses
    text = _fixture_glossary("not_served (49 <!--census:boom_ns.n-->)")
    got = fired(text, {})
    if "census-is-measurable" not in got:
        fails.append(f"FAIL unmeasurable-census-is-caught: {got}")
    CENSUSES = dict(real_censuses, fixture_ns=lambda: {})

    # An observed mark is ACCEPTED AND NEVER GATED -- any number, no measurement behind it.
    text = _fixture_glossary("some fact: 999999 <!--observed:2026-08-28-->")
    got = fired(text)
    if got:
        fails.append(f"FAIL an-observed-mark-is-never-gated: {got}")

    # ...unless the date itself is not a real one.
    text = _fixture_glossary("some fact: 5 <!--observed:2026-13-40-->")
    got = fired(text)
    if "observation-date-is-valid" not in got:
        fails.append(f"FAIL a-malformed-observed-date-is-caught: {got}")

    # A floor ("545+") is exempt entirely -- neither tagged nor marked, and clean.
    text = _fixture_glossary("545+ of Oregon's chapters, and growing")
    got = fired(text)
    if got:
        fails.append(f"FAIL a-stated-floor-is-exempt: {got}")

    # Citation-scheme and month-name identifiers are exempt entirely, single AND listed.
    text = _fixture_glossary(
        "see ADR 0006 and chapters 105, 122, 125 and 128; filed August 2026")
    got = fired(text)
    if got:
        fails.append(f"FAIL identifiers-are-not-figures: {got}")

    # An unreadable document is REFUSED, never reported as agreeing (CONTEXT.md's
    # overriding rule, applied to this gate itself).
    missing = Path("/nonexistent/path/for-stated-census-selftest.md")
    got = [f.rule for f in check_document(missing, {})]
    if got != ["document-is-readable"]:
        fails.append(f"FAIL an-unreadable-document-is-refused: {got}")

    CENSUSES = real_censuses

    # ---------------- citation-integrity rule (#305's follow-on) ----------------
    #
    # Exercised end to end through `check_citations()` itself against real temp files,
    # rather than reconstructed from `cited_terms()` alone -- so the proof covers the whole
    # rule, file-reading included.

    glossary = "**Real Term**:\nSomething real.\n"
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        # A citation naming a term CONTEXT.md does not carry is caught.
        bad = Path(d) / "bad.py"
        bad.write_text('"""CONTEXT.md, *Nonexistent Term* is why we refuse."""\n')
        found = [f.rule for f in check_citations(paths=[bad], glossary_text=glossary)]
        if "citation-names-an-existing-term" not in found:
            fails.append(f"FAIL a-citation-to-a-missing-term-is-caught: {found}")

        # A citation naming a term CONTEXT.md DOES carry is clean.
        good = Path(d) / "good.py"
        good.write_text('"""CONTEXT.md, *Real Term* is why we refuse."""\n')
        found = [f.rule for f in check_citations(paths=[good], glossary_text=glossary)]
        if found:
            fails.append(f"FAIL a-citation-to-a-real-term-produces-no-finding: {found}")

        # A compound citation splits on `/` and checks each half.
        compound = Path(d) / "compound.py"
        compound.write_text(
            '"""CONTEXT.md, *Real Term* / *Nonexistent Term* is why."""\n')
        found = [f.rule for f in check_citations(paths=[compound], glossary_text=glossary)]
        if "citation-names-an-existing-term" not in found:
            fails.append(f"FAIL a-compound-citation-checks-every-term: {found}")

        # A src file that cannot be read is REFUSED, never silently skipped as one with
        # no bad citations (#312) -- "could not check" reported as its own rule, matching
        # `document-is-readable` twenty lines above rather than a bare `continue`.
        missing_src = Path(d) / "does-not-exist.py"
        found = [f.rule for f in check_citations(paths=[missing_src], glossary_text=glossary)]
        if found != ["src-file-is-readable"]:
            fails.append(f"FAIL an-unreadable-src-file-is-refused: {found}")

    # THE DECLARATION, GATED FROM BOTH SIDES (#313, matching legal_status.py). A rule
    # can go undetected by BEING DECLARED WITH NO PROOF (below, dynamic: did it fire during
    # this run) or by BEING EMITTED WITH NO DECLARATION (here, static: does the AST agree
    # with CHECK_RULES) -- the second failure mode never reaches the first check at all if
    # the emitting branch is unreachable in every fixture above, so it needs its own gate.
    unemitted_but_declared = set(CHECK_RULES) - emitted_rules()
    emitted_but_undeclared = emitted_rules() - set(CHECK_RULES)
    if unemitted_but_declared or emitted_but_undeclared:
        fails.append(
            "FAIL every-declared-rule-is-emitted-and-every-emitted-rule-is-declared: "
            f"declared-not-emitted={sorted(unemitted_but_declared)} "
            f"emitted-not-declared={sorted(emitted_but_undeclared)}")

    unfired = set(CHECK_RULES) - _FIRED
    if unfired:
        fails.append(f"FAIL every-declared-rule-was-watched-firing: {sorted(unfired)}")

    for f in fails:
        print(f)
    if fails:
        print(f"{len(fails)} rule(s) did not hold")
        return 1
    print(f"{len(CHECK_RULES)} rule(s) declared, every one watched firing; "
          "guards that must not fire held")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("paths", nargs="*")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    return cmd_check(a.paths)


if __name__ == "__main__":
    sys.exit(main())
