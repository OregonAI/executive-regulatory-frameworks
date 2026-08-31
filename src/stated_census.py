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

THE FLOOR (#341). Everything above gates a figure that IS tagged -- but content stating a
figure can be deleted outright, or a glossary entry can lose the header that put it in
`glossary_blocks()`'s scan (measured: only when that entry is the FIRST `**Term**:` after a
`##` break, with no earlier entry in the same section to absorb its span -- rewording or
deleting any OTHER entry's header just merges its content into the PRECEDING entry, so its
figures are still scanned, only re-attributed). Either way, `--check` can end up quietly
verifying fewer things than last time and exiting 0 -- not a `figure-is-accounted-for`
failure, because there is no longer a figure there to call untagged. Per AGENTS.md's "before
gating a figure, ask whether it should exist," the fix is not a hand-maintained
expected-count in prose (one more figure to keep in sync by hand, the exact disease this
module treats) -- it is DERIVED: `coverage-has-not-regressed` reads each PATH's own text as
of `repo_lib.resolve_base_ref()` (merge-base with origin/main, else HEAD~1 -- the same
"before this change" `changed_content_files` already uses) and refuses a run whose
accounted-for count (tagged + marked, matching or not) is lower than that commit's. A PATH
new since the base ref, or a base ref git cannot resolve, has nothing to compare against --
the floor is then silently satisfied, not silently failed; `cmd_check` reports which case
happened rather than leaving "no floor" indistinguishable from "floor held." A path RENAMED
since the base ref is not "new" either -- `repo_lib.committed_text()` resolves a same-range
rename to the old name's text (code review of this fix: a rename used to read as "nothing to
compare against" too, silently disabling the floor for exactly the document it renamed).
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml

from check_rule_ledger import RuleLedger
from repo_lib import REPO_ROOT, committed_text, resolve_base_ref

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
    "coverage-has-not-regressed",
)

# THE CHECK-RULE LEDGER (#319). Recording a rule when a Failure is built, the AST scan of
# this module's own source for the rule names it can emit, and the both-directions
# comparison against `CHECK_RULES` used to be hand-rolled here -- `legal_status.py` carried
# the identical shape, character for character, and this is the one copy both now share.
_LEDGER = RuleLedger(CHECK_RULES, __file__)


class Failure(_LEDGER.Failure):
    """One rule, the site it is about, and what is wrong -- recorded on construction by the
    shared ledger (like `legal_status.Failure`) so no proof has to remember to say it fired.
    Only `__str__` is added here: `cmd_check()` prints a failure directly."""
    __slots__ = ()

    def __str__(self):
        return f"  FAIL [{self.rule}] {self.site}: {self.detail}"


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
# generous (80 chars) because a list can run several items long.
#
# #315: the first version of this pattern (`\b(word)\b(?:[\s,]|and|&|\d)*$`) let a bare
# "and"/"&" match ANYWHERE after the introducing word, with no digit required in between --
# so "12 divisions and 43 people attended" excluded the real count 43 as though it were a
# fourth list item, because "divisions" appeared upstream followed only by whitespace and
# the literal word "and" before the target number. Narrowed here to require the introducing
# word be followed by AT LEAST ONE digit before any "and"/"&"/comma is accepted -- an
# optional group, so "chapters 105" (the word directly before the FIRST list item, nothing
# to require yet) still matches, but "divisions and 43" (the word, then a bare "and" with no
# digit of its own) no longer does. Verified against every figure in CONTEXT.md's glossary
# (30 currently excluded): identical 30/30 before and after this narrowing.
#
# THIS IS STILL A HEURISTIC, not a parse of English -- a pathological construction can still
# fool it (comma-then-and combinations one item longer than the digit-list group allows, for
# instance), and by design it fails toward REQUIRING a tag rather than toward silently
# excluding, so a construction it cannot classify confidently makes `--check` demand a
# <!--census:--> or <!--observed:--> mark rather than passing it through unseen. `cmd_check`
# additionally reports the COUNT and SITE of every number `check_figures` passed over on
# every run -- both this contextual exclusion AND the separate `+`-floor exemption below,
# via the ONE walk both share (`_figure_sites`) -- so what it declined to check is never
# indistinguishable from what it checked and found to agree (AGENTS.md's overriding rule).
# NOT COVERED by that report: the STRUCTURAL half (`NUMBER_RE`, above) is a pattern match,
# not an enumeration -- a number this heuristic never recognizes as number-shaped at all
# (`1.5`, glued to a decimal point; `137-odd`, glued to a hyphen -- both structurally
# indistinguishable from a citation's own punctuation, see the module docstring's "WHAT
# COUNTS AS A FIGURE" section) cannot be counted or sited by a walk built on `NUMBER_RE`
# matches, because it produces no match to walk. That is a known limit of the structural
# design, not something this report closes.
_EXCLUDED_CONTEXT_RE = re.compile(
    r"\b(chapters?|divisions?|sections?|articles?|adr|oar|ors|eo|oam|"
    r"january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\b"
    r"(?:\s*\d+(?:\s*,\s*\d+)*\s*(?:,|and|&)?)?"
    r"\s*$", re.I)


def _excluded_by_context(text: str, start: int) -> bool:
    """Whether the number at `start` is an identifier named in a citation-scheme or
    month-name list, rather than a stated count -- see the module docstring's
    "WHAT COUNTS AS A FIGURE" section for the full reasoning and examples, and #315's
    comment above `_EXCLUDED_CONTEXT_RE` for what this heuristic still cannot resolve."""
    return bool(_EXCLUDED_CONTEXT_RE.search(text[max(0, start - 80):start]))


def _figure_sites(text: str) -> list:
    """[(pos, end, line, term, stated, skip), ...] for every `NUMBER_RE` match inside a
    glossary block of `text` -- ONE walk, shared by `check_figures` (what to gate) and
    `cmd_check`'s summary (what was skipped, and which of the two reasons). `skip` is
    `None` for a candidate figure `check_figures` goes on to require a tag for,
    `"floor"` for a stated FLOOR (`545+`, exempt by design -- see the module docstring),
    or `"context"` for an identifier `_excluded_by_context` names (a citation-scheme or
    month-name list).

    Three copies of this exact walk used to exist -- `check_figures`, the summary
    counter in `cmd_check`, and an earlier version of this function that only handled
    the `"context"` case -- and the THIRD one is why #315's own report stayed blind to
    the `+`-floor skip: it re-implemented just the context-exclusion half of the walk it
    was supposed to describe, so a number `check_figures` skipped for the OTHER reason
    was never listed as skipped at all. One walk, three consumers, cannot drift apart
    the same way."""
    sites = []
    for term, start, end in glossary_blocks(text):
        block = text[start:end]
        for m in NUMBER_RE.finditer(block):
            pos = start + m.start("num")
            end_abs = start + m.end("num")
            stated = m.group("num")
            if text[end_abs:end_abs + 1] == "+":
                skip = "floor"
            elif _excluded_by_context(text, pos):
                skip = "context"
            else:
                skip = None
            sites.append((pos, end_abs, line_of(text, pos), term, stated, skip))
    return sites


def _skipped_figures(text: str) -> list:
    """[(line, stated, skip), ...] for every figure `_figure_sites` marked `"floor"` or
    `"context"` -- everything `check_figures` passed over without comparing to a
    measurement, and why, so a caller can SAY what this run skipped rather than let a
    declined check look identical to a passed one (#315, AGENTS.md's overriding rule)."""
    return [(line, stated, skip) for _, _, line, _, stated, skip in _figure_sites(text)
            if skip is not None]


def _accounted_count(text: str) -> int:
    """How many figures in `text` are IN SCOPE to be gated at all -- every `_figure_sites`
    site that is not a `"floor"`/`"context"` skip, whether or not it turns out to carry a
    tag `check_figures` accepts (this counts CANDIDATES for that check, not its verdicts --
    an untagged figure `check_figures` would go on to fail is still counted here; only a
    `"floor"`/`"context"` skip removes a site from this count). This is the number
    `coverage-has-not-regressed` (#341) compares between this run's text and the base ref's:
    a glossary entry taken out of `glossary_blocks()`'s scan (its own figures deleted, or --
    only when it is the FIRST `**Term**:` after a `##` break, with no earlier entry to
    absorb its span -- its header reworded or removed) drops its figures from this count
    with no other rule noticing, because there is no longer a figure there to call
    untagged."""
    return sum(1 for _, _, _, _, _, skip in _figure_sites(text) if skip is None)


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
# no caching ACROSS a run, matching how `legal_status.py` and `oar_watch_coverage.py` read
# their sources once per invocation -- so a --check run always measures the corpus as it
# stands right now, never a value memoized from an earlier document read in the same run.


_OAR_CATALOG_CACHE = {}


def _oar_catalog() -> dict:
    """`_meta/catalog/oar.yml`, parsed ONCE PER PROCESS and shared by every namespace that
    reads it (`oar`, `legal_status_docs`) -- not a value carried between separate `--check`
    invocations (the banner comment above still holds: each run is its own process, and
    this cache does not survive past it), but two namespaces in the SAME run independently
    calling `catalog_oar.load_catalog()` is the same source read twice for one measurement
    #307 exists to close everywhere else -- found by code review measuring
    `stated_census.py --check`'s wall time: parsing this 42,615-entry catalog is most of
    the run's cost, and `catalog_force_action_counts()`'s own default read (added by that
    review, to the `legal_status_docs` namespace) paid it a second time until this existed.
    `measured()`'s per-namespace `cache` (below) cannot hold this, because it is keyed by
    the very namespaces that need to SHARE one parse."""
    if "catalog" not in _OAR_CATALOG_CACHE:
        import catalog_oar
        _OAR_CATALOG_CACHE["catalog"] = catalog_oar.load_catalog()
    return _OAR_CATALOG_CACHE["catalog"]


def _oar_measurement() -> dict:
    """`_meta/catalog/oar.yml`'s ingest-status tally (CONTEXT.md's *Ingest status*),
    read via `catalog_oar.status_counts()` -- the one place that count is computed."""
    import catalog_oar
    counts = catalog_oar.status_counts(_oar_catalog())
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


def _legal_status_docs_measurement() -> dict:
    """`legal_status.py`'s three censuses (#307): the `status:` distribution over every
    committed rule document (CONTEXT.md's *Legal status*), the temporary-suspension
    History count (CONTEXT.md's *Filed force action*), and the Bulletin-filed force-action
    tally over the committed OAR catalog (CONTEXT.md's *Legal status* and *Filed force
    action* -- "66 repeals and 34 suspensions", added by #307 code review: `legal_status.py
    --check` already printed this `Counter` every run, and it sat as an `observed:` mark
    only because nothing exposed it by name). All THREE count something different --
    document status VALUES, History TEXT, and catalog-row ACTIONS -- unlike
    `legal_status.census()`, which counts legal-status WRITE SITES in src/ MODULES. Same
    word, four different measurements; kept as separate functions in that module rather
    than one overloading another's name (see its "the document-level censuses" section
    banner). `status_*`, `temp_suspend_*` and `filed_*` prefix the three so their keys can
    never collide the way `authority_total` and `chapter_total` would without
    `_agencies_measurement`'s own prefixing."""
    import legal_status as ls
    # ONE PASS OVER THE CORPUS, shared by the first two, AT FLAT MEMORY -- `document_
    # censuses()` reads each document once and discards it rather than materializing every
    # document's text into a list first (`_rule_document_texts()`'s shape, which this
    # replaced at both live call sites after #307 code review measured it at 2.3x peak RSS
    # -- see that function's own docstring). THE CATALOG READ SHARES `_oar_catalog()`'s
    # process cache with the `oar` namespace, rather than calling `catalog_force_action_
    # counts()` with no argument (which would parse the same 42,615-entry
    # `_meta/catalog/oar.yml` a second time in this run -- code review found exactly this
    # after the first version of this line shipped, see `_oar_catalog()`'s own docstring).
    status_counts, temp_counts = ls.document_censuses()
    out = {}
    out.update({f"status_{k}": v for k, v in status_counts.items()})
    out.update({f"temp_suspend_{k}": v for k, v in temp_counts.items()})
    out.update({f"filed_{k}": v
               for k, v in ls.catalog_force_action_counts(_oar_catalog()).items()})
    return out


def _ors_citation_gap_measurement(text=None) -> dict:
    """The committed ORS chapter-gap catalog's `summary:` block AND per-chapter `targets:`
    figures (#307) -- CONTEXT.md's *Chapter selection* entry's "chapters cited outside the
    selection" figures, and any single chapter's own numbers (its "citations across N
    documents" line for the largest remaining gap, currently chapter 31). `scan_ors_
    citations.py --check` (CI, every PR) ALREADY computes these over the whole corpus and
    keeps `_meta/catalog/ors-citation-gap.yml` current; this reads that committed,
    already-gated view RATHER THAN RECOMPUTING -- re-running the scan here would pay its
    full-corpus cost a second time for numbers the view already carries, and it would let
    this reader's idea of the gap and the file's own summary drift into two different
    measurements of the same thing, which is the shape #307 exists to close everywhere else.

    Per-chapter keys are `target_<chapter>_<field>` for every integer field on every listed
    target (`authority_claims`, `mentions`, `distinct_sections_cited`) -- not just chapter
    31's, so a future entry naming a DIFFERENT chapter's gap does not need this reader
    extended first. `cited_by_sample` and `catalog_title` are not integers and are left out
    the same way `note` is below.

    `documents_scanned` IS DELIBERATELY EXCLUDED, even though it is an integer in
    `summary:`: it is the one figure `scan_ors_citations._inventory_only` refuses to compare
    on `--check` (a denominator, not a claim -- see that function's own docstring), so
    nothing keeps it current and a tag against it would be a gate that looks like evidence
    and is not (#307 code review). If a real gate for it is ever built, it should be added
    back here alongside that gate, not before.

    `text=None` reads the committed file; `--selftest` passes synthetic YAML text instead."""
    if text is None:
        path = REPO_ROOT / "_meta" / "catalog" / "ors-citation-gap.yml"
        text = path.read_text()
    data = yaml.safe_load(text) or {}
    summary = data.get("summary") if isinstance(data, dict) else None
    out = {k: v for k, v in (summary or {}).items()
          if isinstance(v, int) and k != "documents_scanned"}
    for t in (data.get("targets") or []) if isinstance(data, dict) else []:
        if not isinstance(t, dict) or t.get("chapter") is None:
            continue
        for field in ("authority_claims", "mentions", "distinct_sections_cited"):
            v = t.get(field)
            if isinstance(v, int):
                out[f"target_{t['chapter']}_{field}"] = v
    return out


CENSUSES = {
    "oar": _oar_measurement,
    "agencies": _agencies_measurement,
    "oar_watch": _oar_watch_measurement,
    "legal_status_docs": _legal_status_docs_measurement,
    "ors_citation_gap": _ors_citation_gap_measurement,
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
    for pos, end_abs, line, term, stated, skip in _figure_sites(text):
        if skip == "floor":
            continue  # a stated FLOOR ("545+"), exempt by design -- see module docstring
        if skip == "context":
            continue  # an identifier (a chapter/ORS/ADR/month reference), not a count
        site = f"{label}:{line}"

        after = text[end_abs:end_abs + 80]
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


# -------------------------------------------------------------------- rule: coverage floor

def check_coverage_floor(path: Path, text: str, base_text) -> list:
    """#341: `text`'s accounted-for figure count must not be lower than `base_text`'s --
    `base_text` is the SAME path's text as of `repo_lib.resolve_base_ref()`, or `None` when
    there is nothing to compare against (a path new since that ref, or a ref git could not
    resolve). `base_text=None` is never a failure -- "no floor available" and "floor held"
    are different outcomes, and `cmd_check` reports which one happened rather than
    conflating them. Passed in explicitly (matching `check_figures`'s own `text`/`cache`
    parameters) so `--selftest` can fire this against synthetic before/after text without
    shelling out to git or touching the committed corpus."""
    if base_text is None:
        return []
    now = _accounted_count(text)
    was = _accounted_count(base_text)
    if now < was:
        return [Failure(
            "coverage-has-not-regressed", str(path),
            f"{now} figure(s) are accounted for (tagged or marked) in this run, down from "
            f"{was} at the comparison commit -- diff this document against the comparison "
            "commit directly to find which. Likely causes: a stated figure, or an entire "
            "glossary entry's body, deleted outright; or (only when the entry is the "
            "FIRST `**Term**:` after a `##` break, with no earlier entry in the same "
            "section to absorb its span) that entry's own header reworded or removed -- "
            "`glossary_blocks()` otherwise merges a reworded/removed header's content into "
            "the PRECEDING entry rather than dropping it, so that alone usually just "
            "re-attributes a figure, not loses it. This is not a lower figure count "
            "agreeing with a smaller corpus; it is `--check` quietly verifying fewer "
            "things than the commit it is compared against did")]
    return []


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

def check_document(path: Path, cache: dict, base_text) -> list:
    """Every figure-accounting failure in one document -- refuses (rather than skips) a
    document that cannot be read, per CONTEXT.md's *Could not check*: an unreadable
    document's figures are not verified, and that is a different finding from every figure
    in it agreeing. `base_text` feeds `check_coverage_floor` (#341) -- the SAME path's text
    as of `repo_lib.resolve_base_ref()`, or `None` when there is nothing to compare against.
    Required, not defaulted: the one real caller (`cmd_check`) already needs `committed_
    text(path, base_ref)` a second time for its own no-floor report, so it resolves the ref
    once and passes the text down rather than this function shelling out to git a second
    time per path for a value the caller already has."""
    try:
        text = path.read_text()
    except OSError as e:
        return [Failure("document-is-readable", str(path),
                        f"could not be read ({e}) -- its figures were not checked, which "
                        "is not the same as their all agreeing")]
    failures = check_figures(path, text, cache)
    failures += check_coverage_floor(path, text, base_text)
    return failures


def cmd_check(paths) -> int:
    paths = [Path(p) for p in paths] if paths else [DEFAULT_DOC]
    cache: dict = {}
    base_ref = resolve_base_ref()
    failures = []
    no_floor = []  # (path,) -- new since base_ref, or base_ref unreadable for it
    base_texts = {}  # path -> committed_text(path, base_ref), fetched once per path
    for p in paths:
        base_texts[p] = committed_text(p, base_ref)
        failures += check_document(p, cache, base_texts[p])
        if base_texts[p] is None:
            no_floor.append(p)
    failures += check_citations()

    if failures:
        for f in failures:
            print(f, file=sys.stderr)
        print(f"\n{len(failures)} stated-census violation(s)", file=sys.stderr)
        return 1

    n_tagged = n_marked = 0
    # #315: SAY what `check_figures` skipped, and which of the two reasons -- both drawn
    # from `_figure_sites`, the SAME walk `check_figures` itself used a few lines above,
    # so this report cannot describe a different walk than the one that actually ran.
    excluded_context = []  # (path, line, stated) -- an identifier, not a count
    excluded_floor = []    # (path, line, stated) -- a stated FLOOR ("545+"), exempt by design
    for p in paths:
        text = p.read_text()
        for pos, end_abs, line, term, stated, skip in _figure_sites(text):
            if skip == "floor":
                excluded_floor.append((p, line, stated))
                continue
            if skip == "context":
                excluded_context.append((p, line, stated))
                continue
            after = text[end_abs:end_abs + 80].lstrip()
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
    # #315: a number this heuristic decided is an identifier, or a stated floor, is
    # declared here rather than left indistinguishable from one that was checked and
    # agreed -- "could not check is never reported as is not there" applied to an
    # EXCLUSION, not just a failure. Printed every run, not gated behind a flag, so it
    # stays visible. Two categories, named separately (AGENTS.md: name every category,
    # the zeroes included) -- conflating them would say "identifier" of a number that is
    # actually a stated floor, which is not what either skip means.
    print(f"{len(excluded_context)} figure(s) excluded as identifiers (chapter/ORS/ADR/"
          "month lists), not gated:")
    for p, line, stated in excluded_context:
        print(f"  {p}:{line} {stated!r}")
    print(f"{len(excluded_floor)} figure(s) excluded as stated floors (a number "
          "immediately followed by '+'), not gated:")
    for p, line, stated in excluded_floor:
        print(f"  {p}:{line} {stated!r}+")
    # #341: the coverage floor held for every path with something to compare against --
    # named here so "held" and "nothing to compare" cannot look like the same silence.
    checked_floor = [p for p in paths if p not in no_floor]
    print(f"coverage floor (against {base_ref[:12]}): held for {len(checked_floor)} "
          f"document(s), no comparison available for {len(no_floor)} "
          f"(new since that commit, or unreadable at it):")
    for p in no_floor:
        print(f"  {p}")
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

    # #315 RED: the OLD context-exclusion regex swallowed a real count sitting downstream
    # of a citation-scheme word with a bare "and" and no digit of its own in between -- an
    # untagged genuine count read as though it were one more item in an upstream list. The
    # narrowed pattern must catch it as an ordinary unaccounted figure instead of excusing
    # it silently.
    # (Code review: asserting merely `"figure-is-accounted-for" not in got` does not
    # discriminate here -- "12" itself, with nothing preceding it in the block, was
    # ALREADY unaccounted for under the OLD regex too, so that assertion holds either
    # way and proves nothing about the narrowing. The real property is that BOTH "12"
    # and "43" are now unaccounted -- the OLD regex only ever caught "12".)
    text = _fixture_glossary("12 divisions and 43 people attended, no tag at all")
    got = fired(text)
    if got.count("figure-is-accounted-for") != 2:
        fails.append(
            "FAIL context-exclusion-does-not-swallow-a-real-count-after-a-bare-and: "
            f"want 2 unaccounted figures ('12' and '43'), got {got}")
    text = _fixture_glossary("see chapters and 43 items filed, no tag at all")
    got = fired(text)
    if "figure-is-accounted-for" not in got:
        fails.append(
            "FAIL context-exclusion-requires-a-digit-before-the-word-can-exclude: "
            f"{got}")

    # #315: the exclusion is not just narrower, it is also OBSERVABLE -- every number the
    # heuristic still passes over is reported, not left indistinguishable from one that was
    # checked and agreed.
    text = _fixture_glossary("see ADR 0006 and chapters 105, 122 and 128")
    got = [(line, stated) for line, stated, skip in _skipped_figures(text)
           if skip == "context"]
    if sorted(v for _, v in got) != ["0006", "105", "122", "128"]:
        fails.append(f"FAIL context-excluded-figures-are-reported: {got}")

    # #315 code review: the report above covered the context-exclusion path only -- the
    # SEPARATE `+`-floor exemption ("545+") was just as silently skipped by
    # `check_figures` and just as silently absent from what got reported. It is live
    # today, not hypothetical: CONTEXT.md's own *Chapter selection* entry states its one
    # figure this way.
    text = _fixture_glossary("545+ of Oregon's chapters, and growing")
    got = [(line, stated) for line, stated, skip in _skipped_figures(text)
           if skip == "floor"]
    if [v for _, v in got] != ["545"]:
        fails.append(f"FAIL floor-excluded-figures-are-reported: {got}")

    # An unreadable document is REFUSED, never reported as agreeing (CONTEXT.md's
    # overriding rule, applied to this gate itself).
    missing = Path("/nonexistent/path/for-stated-census-selftest.md")
    got = [f.rule for f in check_document(missing, {}, base_text=None)]
    if got != ["document-is-readable"]:
        fails.append(f"FAIL an-unreadable-document-is-refused: {got}")

    # -------------------------- #341: the coverage floor --------------------------
    #
    # `check_coverage_floor` directly, against synthetic before/after text -- no git, no
    # committed corpus -- so the RED case reproduces #341's own repro (a `**Term**:` header
    # reworded to plain prose, dropping a tagged figure out of scope entirely) as a
    # controlled mutation rather than a coincidence of today's CONTEXT.md.
    before = _fixture_glossary("not_served (49 <!--census:fixture_ns.n-->)")
    # THE MUTATION #341 NAMES: the header itself, reworded to plain prose -- the entry (and
    # its tagged figure) leaves glossary_blocks()'s scan entirely. Nothing about the figure
    # changed; only its header did.
    after_reworded = before.replace("**Fixture**:", "Fixture:")
    if _accounted_count(after_reworded) != 0 or _accounted_count(before) != 1:
        fails.append(
            "FAIL coverage-floor-fixture-shape: reworded header must drop the block from "
            f"scope (want 0, got {_accounted_count(after_reworded)}); the un-mutated "
            f"fixture must carry exactly one accounted figure (want 1, got "
            f"{_accounted_count(before)})")
    got = [f.rule for f in check_coverage_floor(Path("fixture.md"), after_reworded, before)]
    if "coverage-has-not-regressed" not in got:
        fails.append(f"FAIL a-reworded-header-drops-coverage-and-is-caught: {got}")

    # The un-mutated pair (same text both sides) is clean.
    got = [f.rule for f in check_coverage_floor(Path("fixture.md"), before, before)]
    if got:
        fails.append(f"FAIL unchanged-coverage-produces-no-finding: {got}")

    # MORE coverage than the base ref is never a failure -- the floor is a floor, not a
    # fixed target.
    grown = before + "\nmore_served (7 <!--census:fixture_ns.m-->)\n"
    got = [f.rule for f in check_coverage_floor(Path("fixture.md"), grown, before)]
    if got:
        fails.append(f"FAIL grown-coverage-produces-no-finding: {got}")

    # `base_text=None` (nothing to compare against -- a new path, or an unreadable base
    # ref) is satisfied vacuously, never a failure -- "no floor" is not "floor broken".
    got = [f.rule for f in check_coverage_floor(Path("fixture.md"), after_reworded, None)]
    if got:
        fails.append(f"FAIL no-base-text-is-not-a-failure: {got}")

    # Wired through check_document with an explicit base_text (no git, no _UNSET
    # resolution): the coverage failure surfaces alongside check_figures's own findings, for
    # a document actually READ off disk (check_document's real code path, not a stand-in).
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        reworded_doc = Path(d) / "reworded.md"
        reworded_doc.write_text(after_reworded)
        got = [f.rule for f in check_document(reworded_doc, {}, base_text=before)]
        if "coverage-has-not-regressed" not in got:
            fails.append(f"FAIL check-document-wires-the-coverage-floor: {got}")

    CENSUSES = real_censuses

    # ------------- #307: the ors_citation_gap reader reads its source, and moves --------
    #
    # `scan_ors_citations.py` ALREADY computes chapters-cited-outside-the-selection --
    # it is in the committed catalog's `summary:` block and in the printed line. This
    # namespace exposes those numbers as named quantities rather than recomputing them, so
    # the reading logic (not the scan itself, which is `scan_ors_citations.py --selftest`'s
    # job) is what needs proving here -- against synthetic YAML text, not the committed
    # catalog, so the mutation below is controlled rather than a coincidence of whatever
    # the corpus's gap happens to be today.
    synthetic_a = ("summary:\n  chapters_cited_outside_mirrored_set: 5\n"
                  "  chapters_known_real_not_ingested: 2\n"
                  "  chapters_no_corroborating_evidence: 3\n")
    got = _ors_citation_gap_measurement(synthetic_a)
    if got.get("chapters_cited_outside_mirrored_set") != 5:
        fails.append(f"FAIL ors-citation-gap-reader-parses-the-summary-block: {got}")
    # THE MUTATION: change the underlying data, watch the figure move.
    synthetic_b = ("summary:\n  chapters_cited_outside_mirrored_set: 6\n"
                  "  chapters_known_real_not_ingested: 2\n"
                  "  chapters_no_corroborating_evidence: 4\n")
    moved = _ors_citation_gap_measurement(synthetic_b)
    if moved.get("chapters_cited_outside_mirrored_set") != 6:
        fails.append(f"FAIL ors-citation-gap-reader-moves-with-its-source: {moved}")
    # A non-integer summary value (a string, a null) is left out rather than gated on --
    # `known-census-key` is what refuses a tag naming a key this reader did not carry.
    with_a_string = "summary:\n  chapters_mirrored: 5\n  note: not a count\n"
    stringy = _ors_citation_gap_measurement(with_a_string)
    if "note" in stringy or stringy.get("chapters_mirrored") != 5:
        fails.append(f"FAIL ors-citation-gap-reader-keeps-only-integers: {stringy}")

    # `documents_scanned` IS AN INTEGER AND IS STILL EXCLUDED -- code review of #307 found
    # it exposed here with no gate keeping it current (`scan_ors_citations._inventory_only`
    # deliberately excludes it from `--check`'s comparison, so a tag against it here would
    # be gated against a number nothing actually rechecks).
    with_scanned = "summary:\n  documents_scanned: 81921\n  chapters_mirrored: 5\n"
    scanned = _ors_citation_gap_measurement(with_scanned)
    if "documents_scanned" in scanned:
        fails.append("FAIL ors-citation-gap-reader-excludes-the-ungated-denominator: "
                     f"{scanned}")

    # PER-CHAPTER TARGET FIGURES are exposed too, prefixed `target_<chapter>_<field>` --
    # CONTEXT.md's *Chapter selection* entry cites a single chapter's own "N citations
    # across M documents" line, and that chapter's `mentions` is a committed, CI-gated
    # number the same file already carries (#307 code review).
    with_targets = (
        "summary:\n  chapters_mirrored: 5\n"
        "targets:\n"
        "- chapter: '31'\n  status: not_mirrored_unknown\n  catalog_title: ''\n"
        "  authority_claims: 0\n  mentions: 284\n  distinct_sections_cited: 13\n"
        "  cited_by_sample: []\n")
    targeted = _ors_citation_gap_measurement(with_targets)
    if targeted.get("target_31_mentions") != 284:
        fails.append(f"FAIL ors-citation-gap-reader-exposes-per-chapter-targets: {targeted}")
    # THE MUTATION: change the underlying data, watch the figure move.
    with_targets_moved = with_targets.replace("mentions: 284", "mentions: 285")
    moved_target = _ors_citation_gap_measurement(with_targets_moved)
    if moved_target.get("target_31_mentions") != 285:
        fails.append("FAIL ors-citation-gap-per-chapter-target-moves-with-its-source: "
                     f"{moved_target}")
    # `cited_by_sample` (a list) and `catalog_title` (a string) are not integers and are
    # left out, same as `note` above.
    if "target_31_cited_by_sample" in targeted or "target_31_catalog_title" in targeted:
        fails.append(f"FAIL ors-citation-gap-reader-keeps-only-integer-target-fields: "
                     f"{targeted}")

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

    # THE DECLARATION, GATED FROM BOTH SIDES (#313, matching legal_status.py; both directions
    # are `_LEDGER.gaps()`'s one call since #319). A rule can go undetected by BEING DECLARED
    # WITH NO PROOF (dynamic: did it fire during this run) or by BEING EMITTED WITH NO
    # DECLARATION (static: does the AST agree with CHECK_RULES) -- the second failure mode
    # never reaches the first check at all if the emitting branch is unreachable in every
    # fixture above, so it needs its own gate.
    gaps = _LEDGER.gaps()
    if gaps.unemitted_but_declared or gaps.emitted_but_undeclared:
        fails.append(
            "FAIL every-declared-rule-is-emitted-and-every-emitted-rule-is-declared: "
            f"declared-not-emitted={sorted(gaps.unemitted_but_declared)} "
            f"emitted-not-declared={sorted(gaps.emitted_but_undeclared)}")

    if gaps.unfired:
        fails.append(f"FAIL every-declared-rule-was-watched-firing: {sorted(gaps.unfired)}")

    for f in fails:
        print(f)
    if fails:
        print(f"{len(fails)} rule(s) did not hold")
        return 1
    print(f"{_LEDGER.demonstrated_count} rule(s) declared, every one watched firing; "
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
