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

A STRICTLY OLDER prose date is the bug: it means a later refresh updated frontmatter and
left prose behind. That is what `--check` fails on.

A STRICTLY NEWER banner date is NOT this bug, and `--check` does not fail on it. 25
`executive-orders/*.md` documents carry a banner date ahead of frontmatter (and of the
provenance line, which still agrees with frontmatter) — all from one commit
(e1723c7f46, "Corroborate every OCR'd executive order with a second engine"), which
re-fetched each order's PDF and ran a second OCR engine over the ALREADY-COMMITTED text
to corroborate it, without replacing that text (`source_sha256` is unchanged, by design —
the hash commits to the committed reading, not to whichever engine's output happens to
agree with it this week). The banner's date was hand-advanced to record that
re-verification; the frontmatter and provenance-line dates correctly still name the
retrieval that produced the current sha. This is a real distinction this corpus's data
model does not have a field for yet (a "last verified unchanged" date beside "last
changed"), not a failure to re-stamp — rewriting those 25 banners back to the earlier
date would make the corpus LESS accurate, not more. `--check` reports the count so it
stays visible rather than silently excluded.

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
FM_RE = re.compile(r'^retrieved: "(\d{4}-\d{2}-\d{2})"$', re.M)
BANNER_RE = re.compile(r'\(retrieved (\d{4}-\d{2}-\d{2})\)')
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

    # THE #424 BUG: a prose date left behind a frontmatter date that moved past it.
    # A date AHEAD of frontmatter is a different, deliberately-not-failed case -- see
    # the module docstring -- so both comparisons below are strict less-than, never !=.
    if banner and banner < fm:
        out.append(Failure(
            "the-banners-retrieved-date-is-not-behind-frontmatter", site,
            f"frontmatter publishes retrieved \"{fm}\" but the non-authoritative banner "
            f"still reads (retrieved {banner}) — a reader following the banner sees a "
            f"stale retrieval date while frontmatter has already moved on"))

    if prose and prose < fm:
        out.append(Failure(
            "the-provenance-lines-retrieved-date-is-not-behind-frontmatter", site,
            f"frontmatter publishes retrieved \"{fm}\" but the provenance line still "
            f"reads retrieved {prose} — the same staleness, on the line "
            f"provenance_spelling.py's docstring calls \"the one a reader actually "
            f"follows\""))

    return out


def survey():
    """(findings, checked, banner_ahead, prose_ahead) over every content document."""
    out, checked, banner_ahead, prose_ahead = [], 0, 0, 0
    for p in content_files():
        rel = p.relative_to(REPO_ROOT)
        text = p.read_text(encoding="utf-8", errors="replace")
        fm, banner, prose = dates(text)
        if fm is None:
            continue
        checked += 1
        if banner and banner > fm:
            banner_ahead += 1
        if prose and prose > fm:
            prose_ahead += 1
        out.extend(findings(str(rel), text))
    return out, checked, banner_ahead, prose_ahead


def cmd_check() -> int:
    bad, checked, banner_ahead, prose_ahead = survey()
    if bad:
        for f in bad[:20]:
            print(f)
        if len(bad) > 20:
            print(f"  … and {len(bad) - 20} more")
        print(f"\n{len(bad)} finding(s) over {checked} content document(s) carrying a "
              f"frontmatter retrieved date.")
        return 1
    print(f"provenance dates: {checked} content document(s) carry a frontmatter "
          f"retrieved date; no prose copy is behind it. {banner_ahead} carry a banner "
          f"date AHEAD of frontmatter (verified-without-content-change events — see this "
          f"module's docstring; not a finding) and {prose_ahead} carry a provenance-line "
          f"date ahead (none at this writing — the provenance line has never been "
          f"observed ahead of frontmatter in this corpus, only behind or equal).")
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
          "the-banners-retrieved-date-is-not-behind-frontmatter", site, banner_stale)

    prose_stale = PROSE_RE.sub(f"· retrieved {older} ·", text, count=1)
    _case(fails, "a-provenance-line-date-left-behind-frontmatter-is-caught",
          "the-provenance-lines-retrieved-date-is-not-behind-frontmatter", site, prose_stale)

    # BOTH AT ONCE must fire both rules, not just the first one found.
    both_stale = PROSE_RE.sub(f"· retrieved {older} ·", banner_stale, count=1)
    got_both = {f.rule for f in findings(site, both_stale)}
    expected_both = {"the-banners-retrieved-date-is-not-behind-frontmatter",
                     "the-provenance-lines-retrieved-date-is-not-behind-frontmatter"}
    if got_both != expected_both:
        fails.append(f"FAIL both-prose-dates-stale-fires-both-rules: "
                     f"expected {sorted(expected_both)}, got {sorted(got_both)}")

    # THE DELIBERATE NON-FINDING: a banner date AHEAD of frontmatter (the 25
    # executive-orders shape) must not fail the gate. Proving this is proving the
    # design decision, not an oversight -- see the module docstring.
    newer = "2099-01-01"
    banner_ahead = BANNER_RE.sub(f"(retrieved {newer})", text, count=1)
    _case_clean(fails, "a-banner-date-ahead-of-frontmatter-is-not-a-finding",
                site, banner_ahead)

    # NOTHING IN THIS PROOF WROTE TO THE WORKING TREE (#252).
    if (REPO_ROOT / site).read_text() != text:
        fails.append("FAIL nothing-in-this-proof-wrote-to-the-working-tree: "
                     f"{site} changed while the selftest ran")

    declared = {"the-banners-retrieved-date-is-not-behind-frontmatter",
                "the-provenance-lines-retrieved-date-is-not-behind-frontmatter"}
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
