#!/usr/bin/env python3
"""A document's retrieval date is written once in frontmatter, twice more in prose, and
the three are made to agree.

  python3 src/provenance_dates.py --check      every content document
  python3 src/provenance_dates.py --selftest   every rule, watched failing

WHY THIS EXISTS (#424). Every content document carries its retrieval date THREE times:

  frontmatter   retrieved: "YYYY-MM-DD"
  banner        > ... Verify against the official source: <url> (retrieved YYYY-MM-DD).
  prose         - Source: <url> · retrieved YYYY-MM-DD · sha256 `...`

`ingest_lib.refresh_document()` re-stamped the frontmatter field (and both spellings of
the hash) on every re-ingest, but never touched the two prose dates — the same class of
"one fact declared more than once with nothing gating agreement" bug `provenance_spelling.py`
was written for (#253), except for the retrieval date rather than the hash. Re-measured
2026-10-01: 131 documents (52 agencies, 79 rules) carry a prose date OLDER than frontmatter
— every one a document `refresh_document()` re-ingested a second time, worst case
`rules/414` with 44.

A prose date that DISAGREES with frontmatter in EITHER direction is the bug: `--check`
fails on `!=`, not only on strictly-older. An earlier version of this module treated a
banner date strictly AHEAD of frontmatter as a deliberate, non-failing case — supposedly
25 `executive-orders/*.md` documents where one commit "re-verified already-committed text
... without changing it". That account was false: all 25 are metadata stubs that commit
9662ead1f1 (15, 2026-07-25) or e1723c7f46 (10, 2026-08-02) gave their FIRST machine-
readable full text, OCR'd from a freshly re-fetched PDF — `content_mode` moved from
`summary` to `verbatim` and `source_sha256` changed (e.g. `eo-19-07`
`0656a47c9e4da0461d755aa409f2440abe5ee54d85b0fc0ddcfa390e80b619d7` ->
`053407585252e5ad7e0691c858ac4a710bdaddbbf89fd46af7d4c1fc55c6b374`). Frontmatter
`retrieved` and the provenance line were simply never re-stamped to the date that fetch
actually happened on — the #424 bug in the opposite direction, frontmatter and the
provenance line left behind a banner date that moved on. Those 25 have been corrected to
agree (frontmatter and the provenance line now read the banner's date), and the gate no
longer special-cases "ahead".

NOTHING HERE OPENS A FILE FOR WRITING, and every rule is decided from the document's text
alone -- so `--selftest` fires each one against a MUTATED COPY of a committed document
rather than a fixture, and cannot leave the working tree dirty the way #252 describes.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repo_lib import REPO_ROOT, content_files  # noqa: E402

# THE THREE SPELLINGS, declared here and nowhere else in this module.
# FM_RE: quotes are optional and either style — 74 content documents are single-quoted.
FM_RE = re.compile(r'^retrieved: [\'"]?(\d{4}-\d{2}-\d{2})[\'"]?\s*$', re.M)
# BANNER_RE: the date may be followed by a trailing qualifier before the close-paren —
# statute and constitution banners read "(retrieved D, 2025 Edition)" or
# "(retrieved D, in effect following ...)" (~37,870 documents), not just "(retrieved D)".
BANNER_RE = re.compile(r'\(retrieved (\d{4}-\d{2}-\d{2})[,)]')
PROSE_RE = re.compile(r'· retrieved (\d{4}-\d{2}-\d{2}) ·')

_FIRED: set[str] = set()


class Failure:
    __slots__ = ("rule", "site", "detail")

    def __init__(self, rule, site, detail):
        self.rule, self.site, self.detail = rule, site, detail
        _FIRED.add(rule)

    def __str__(self):
        return f"  FAIL [{self.rule}] {self.site}: {self.detail}"


def dates(text: str):
    """(frontmatter retrieved, banner retrieved, provenance-line retrieved) for one
    document; None where absent."""
    fm = FM_RE.search(text)
    banner = BANNER_RE.search(text)
    prose = PROSE_RE.search(text)
    return (fm.group(1) if fm else None,
            banner.group(1) if banner else None,
            prose.group(1) if prose else None)


def findings(site: str, text: str) -> list:
    """Every rule this module declares, decided from the document's text alone."""
    fm, banner, prose = dates(text)
    out = []
    if fm is None:
        return out

    # THE #424 BUG, either direction: a prose date that disagrees with frontmatter at
    # all, not only one left strictly behind -- see the module docstring for why "ahead"
    # is not a safe case to carve out.
    if banner and banner != fm:
        out.append(Failure(
            "the-banners-retrieved-date-does-not-match-frontmatter", site,
            f"frontmatter publishes retrieved \"{fm}\" but the non-authoritative banner "
            f"reads (retrieved {banner}) — a reader following the banner sees a "
            f"different retrieval date than frontmatter"))

    if prose and prose != fm:
        out.append(Failure(
            "the-provenance-lines-retrieved-date-does-not-match-frontmatter", site,
            f"frontmatter publishes retrieved \"{fm}\" but the provenance line "
            f"reads retrieved {prose} — a disagreement on the line "
            f"provenance_spelling.py's docstring calls \"the one a reader actually "
            f"follows\""))

    return out


def survey():
    """(findings, checked, no_banner_match, no_prose_match) over every content document.
    The last two count documents with a frontmatter retrieved date but no BANNER_RE /
    PROSE_RE match at all (e.g. a banner spelling this module's regexes don't yet cover)
    -- those are never compared, so --check reports how many were skipped rather than
    silently folding them into "checked"."""
    out, checked, no_banner_match, no_prose_match = [], 0, 0, 0
    for p in content_files():
        rel = p.relative_to(REPO_ROOT)
        text = p.read_text(encoding="utf-8", errors="replace")
        fm, banner, prose = dates(text)
        if fm is None:
            continue
        checked += 1
        if banner is None:
            no_banner_match += 1
        if prose is None:
            no_prose_match += 1
        out.extend(findings(str(rel), text))
    return out, checked, no_banner_match, no_prose_match


def cmd_check() -> int:
    bad, checked, no_banner_match, no_prose_match = survey()
    if bad:
        for f in bad[:20]:
            print(f)
        if len(bad) > 20:
            print(f"  … and {len(bad) - 20} more")
        print(f"\n{len(bad)} finding(s) over {checked} content document(s) carrying a "
              f"frontmatter retrieved date.")
        return 1
    print(f"provenance dates: {checked} content document(s) carry a frontmatter "
          f"retrieved date; every banner or provenance-line date found agrees with it. "
          f"{no_banner_match} document(s) had no banner this module's spelling matches "
          f"(never compared) and {no_prose_match} had no provenance line (never compared).")
    return 0


# ---------------------------------------------------------------- selftest

def _committed() -> tuple:
    """A real committed rule carrying all three dates in agreement, as (site, text).
    Proving these rules on a fixture would prove them about a document shape the corpus
    may not have."""
    for p in (REPO_ROOT / "rules").rglob("oar-*.md"):
        text = p.read_text()
        fm, banner, prose = dates(text)
        if fm and banner and prose and fm == banner == prose:
            rel = p.relative_to(REPO_ROOT)
            return str(rel), text
    raise SystemExit("no committed rule carries all three retrieved dates in agreement — "
                     "the corpus this gate governs does not have the shape it assumes")


def _case(fails: list, name: str, rule: str, site: str, text: str) -> None:
    got = [f.rule for f in findings(site, text)]
    if rule not in got:
        fails.append(f"FAIL {name}: expected [{rule}], got {got or 'no finding'} — the "
                     f"gate cannot see the case it exists for")


def _case_clean(fails: list, name: str, site: str, text: str) -> None:
    got = [f.rule for f in findings(site, text)]
    if got:
        fails.append(f"FAIL {name}: expected no finding, got {got}")


def _committed_statute() -> tuple:
    """A real committed statute or constitution document, whose banner is spelled
    "(retrieved D, 2025 Edition)" / "(retrieved D, in effect following ...)" rather than
    the bare "(retrieved D)" `rules/oar-*.md` use -- proving BANNER_RE against the
    spelling ~37,870 documents actually carry, not just the one _committed() finds."""
    for root in ("statutes", "constitution"):
        for p in (REPO_ROOT / root).rglob("*.md"):
            text = p.read_text(encoding="utf-8", errors="replace")
            fm, banner, prose = dates(text)
            if fm and banner and prose and fm == banner == prose:
                return str(p.relative_to(REPO_ROOT)), text
    raise SystemExit("no committed statute/constitution document carries all three "
                     "retrieved dates in agreement")


def _committed_single_quoted() -> tuple:
    """A real committed content document whose frontmatter `retrieved` is single-quoted
    -- 74 documents are -- proving FM_RE against that spelling too."""
    for p in content_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^retrieved: '\d{4}-\d{2}-\d{2}'$", text, re.M):
            fm, banner, prose = dates(text)
            if fm and banner and prose and fm == banner == prose:
                return str(p.relative_to(REPO_ROOT)), text
    raise SystemExit("no committed single-quoted-retrieved document carries all three "
                     "retrieved dates in agreement")


def cmd_selftest() -> int:
    fails = []
    site, text = _committed()

    # THE GUARD THAT MUST NOT FIRE, first: the unmutated document is clean. Without this
    # every case below could be firing on a document that was already broken.
    _case_clean(fails, "a-committed-document-produces-no-finding-unmutated", site, text)

    older = "2026-01-01"  # older than any committed retrieved date in this corpus

    # THE CASE #424 PRODUCED: a prose date left behind after frontmatter moved on.
    banner_stale = BANNER_RE.sub(f"(retrieved {older})", text, count=1)
    _case(fails, "a-banner-date-left-behind-frontmatter-is-caught",
          "the-banners-retrieved-date-does-not-match-frontmatter", site, banner_stale)

    prose_stale = PROSE_RE.sub(f"· retrieved {older} ·", text, count=1)
    _case(fails, "a-provenance-line-date-left-behind-frontmatter-is-caught",
          "the-provenance-lines-retrieved-date-does-not-match-frontmatter", site, prose_stale)

    # BOTH AT ONCE must fire both rules, not just the first one found.
    both_stale = PROSE_RE.sub(f"· retrieved {older} ·", banner_stale, count=1)
    got_both = {f.rule for f in findings(site, both_stale)}
    expected_both = {"the-banners-retrieved-date-does-not-match-frontmatter",
                     "the-provenance-lines-retrieved-date-does-not-match-frontmatter"}
    if got_both != expected_both:
        fails.append(f"FAIL both-prose-dates-stale-fires-both-rules: "
                     f"expected {sorted(expected_both)}, got {sorted(got_both)}")

    # THE 25 EXECUTIVE-ORDERS SHAPE: a banner date AHEAD of frontmatter IS a finding
    # (the opposite-direction #424 bug — see the module docstring). An earlier version of
    # this gate carved "ahead" out as deliberate; that was wrong, and this case locks in
    # the correction instead.
    newer = "2099-01-01"
    banner_ahead = BANNER_RE.sub(f"(retrieved {newer})", text, count=1)
    _case(fails, "a-banner-date-ahead-of-frontmatter-is-caught",
          "the-banners-retrieved-date-does-not-match-frontmatter", site, banner_ahead)

    # THE STATUTE/CONSTITUTION BANNER SPELLING: "(retrieved D, 2025 Edition)" /
    # "(retrieved D, in effect following ...)", not the bare "(retrieved D)" rules use.
    # BANNER_RE must still match it, and still catch a stale date inside it.
    stat_site, stat_text = _committed_statute()
    stat_stale = BANNER_RE.sub(f"(retrieved {older},", stat_text, count=1)
    _case(fails, "a-statute-banners-qualified-date-left-behind-is-caught",
          "the-banners-retrieved-date-does-not-match-frontmatter", stat_site, stat_stale)

    # THE SINGLE-QUOTED FRONTMATTER SPELLING: `retrieved: 'D'`, not only `retrieved: "D"`.
    sq_site, sq_text = _committed_single_quoted()
    _case_clean(fails, "a-single-quoted-frontmatter-document-produces-no-finding-unmutated",
                sq_site, sq_text)
    sq_stale = BANNER_RE.sub(f"(retrieved {older})", sq_text, count=1)
    _case(fails, "a-single-quoted-frontmatter-documents-banner-mismatch-is-caught",
          "the-banners-retrieved-date-does-not-match-frontmatter", sq_site, sq_stale)

    # NOTHING IN THIS PROOF WROTE TO THE WORKING TREE (#252).
    if (REPO_ROOT / site).read_text() != text:
        fails.append("FAIL nothing-in-this-proof-wrote-to-the-working-tree: "
                     f"{site} changed while the selftest ran")
    if (REPO_ROOT / stat_site).read_text() != stat_text:
        fails.append("FAIL nothing-in-this-proof-wrote-to-the-working-tree: "
                     f"{stat_site} changed while the selftest ran")
    if (REPO_ROOT / sq_site).read_text() != sq_text:
        fails.append("FAIL nothing-in-this-proof-wrote-to-the-working-tree: "
                     f"{sq_site} changed while the selftest ran")

    declared = {"the-banners-retrieved-date-does-not-match-frontmatter",
                "the-provenance-lines-retrieved-date-does-not-match-frontmatter"}
    unfired = declared - _FIRED
    if unfired:
        fails.append(f"FAIL every-declared-rule-was-watched-firing: {sorted(unfired)} "
                     f"never fired in any case")

    for f in fails:
        print(f)
    if fails:
        print(f"{len(fails)} rule(s) did not hold")
        return 1
    print(f"{len(declared)} rule(s) declared, every one watched firing against a mutated "
          f"copy of a committed document; 2 guard(s) that must not fire held")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return cmd_selftest()
    return cmd_check()


if __name__ == "__main__":
    sys.exit(main())
