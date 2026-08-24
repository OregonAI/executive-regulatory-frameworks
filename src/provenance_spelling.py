#!/usr/bin/env python3
"""A document's source hash is written once, and its two spellings are made to agree.

  python3 src/provenance_spelling.py --check      every content document
  python3 src/provenance_spelling.py --selftest   every rule, watched failing

WHY THIS EXISTS (#253). Every content document publishes its source hash TWICE:

  frontmatter   source_sha256: "…"
  prose         - Source: <…> · retrieved … · sha256 `…`

`corpus-verify-provenance` reads ONLY the frontmatter one. The prose one -- the
human-readable line, the one a reader actually follows -- was read in exactly one place
in this repository: reingest_oar.py's byte-identical rule, over the 306 documents that
path has ever written. 306 of 76,313.

WHAT THAT COST. #244 re-stamped the frontmatter field on all 36,953 OAR rules and not the
prose line:

  prose sha disagreed with frontmatter : 36,952
  already agreed                       :      1

`corpus-verify-provenance` passed on all 36,953 in that state and said nothing. The
disagreement surfaced only because reingest_oar happened to cover 306 of them. Had #244
touched a body of documents that path has never written, the corpus would be publishing
36,952 provenance lines quoting a hash of nothing, with every gate green.

THIS IS THE EIGHTH INSTANCE of one fact declared twice with nothing gating agreement:
CURATED_KEYS (#165), the recheck enum against CADENCES (#193), the citation scheme against
AUTHORITY_FORMS (#195), legal status against ingest status (#228), snapshot() against
content_hash (#207), the link_graph drop predicate (#242), and this. Every one was
invisible until something moved.

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

# THE TWO SPELLINGS, declared here and nowhere else in this module.
FM_RE = re.compile(r'^source_sha256: "([0-9a-f]{64})"$', re.M)
PROSE_RE = re.compile(r'· ((?:raw-byte |text-content )?)sha256 `([0-9a-f]{64})`')

# The mirrored bodies of law. A document here is a reproduction of an official text, and
# must carry BOTH spellings: dropping either one is how a hash quietly stops being checked.
# `agencies/` is deliberately not in this set -- 107 documents there legitimately carry
# only one, and cmd_check reports them by count rather than passing over them in silence.
MIRRORED_BODIES = ("rules", "statutes", "executive-orders")

_FIRED: set[str] = set()


class Failure:
    __slots__ = ("rule", "site", "detail")

    def __init__(self, rule, site, detail):
        self.rule, self.site, self.detail = rule, site, detail
        _FIRED.add(rule)

    def __str__(self):
        return f"  FAIL [{self.rule}] {self.site}: {self.detail}"


def spellings(text: str):
    """(frontmatter sha, prose label, prose sha) for one document; None where absent."""
    m = FM_RE.search(text)
    hits = PROSE_RE.findall(text)
    label, prose = (hits[0][0].strip(), hits[0][1]) if hits else (None, None)
    return (m.group(1) if m else None), label, prose, len(hits)


def findings(site: str, body: str, text: str) -> list:
    """Every rule this module declares, decided from the document's text alone."""
    fm, label, prose, n_prose = spellings(text)
    out = []

    if fm and prose and fm != prose:
        out.append(Failure(
            "the-two-spellings-of-a-documents-source-hash-agree", site,
            f"frontmatter publishes {fm[:16]}… and the provenance line publishes "
            f"{prose[:16]}…. corpus-verify-provenance reads only the first, so the second "
            f"is a hash a reader can follow and nothing checks — re-stamp both or neither"))

    if body in MIRRORED_BODIES and (fm is None or prose is None):
        missing = "the frontmatter source_sha256" if fm is None else "the provenance line's sha256"
        out.append(Failure(
            "a-mirrored-law-document-declares-its-source-hash-in-both-places", site,
            f"is a reproduction of an official text but is missing {missing}. One spelling "
            f"is one nothing cross-checks, which is how #244 went unnoticed on 36,952 "
            f"documents at once"))

    if n_prose > 1:
        out.append(Failure(
            "a-document-declares-at-most-one-prose-source-hash", site,
            f"carries {n_prose} provenance sha256 lines. Which one a reader is meant to "
            f"follow is undecidable, and this module compares only the first"))

    return out


def survey():
    """(findings, checked, both, fm_only, prose_only) over every content document."""
    out, checked, both, fm_only, prose_only = [], 0, 0, 0, 0
    for p in content_files():
        rel = p.relative_to(REPO_ROOT)
        text = p.read_text(encoding="utf-8", errors="replace")
        fm, _, prose, _ = spellings(text)
        checked += 1
        if fm and prose:
            both += 1
        elif fm:
            fm_only += 1
        elif prose:
            prose_only += 1
        out.extend(findings(str(rel), rel.parts[0], text))
    return out, checked, both, fm_only, prose_only


def cmd_check() -> int:
    bad, checked, both, fm_only, prose_only = survey()
    if bad:
        for f in bad[:20]:
            print(f)
        if len(bad) > 20:
            print(f"  … and {len(bad) - 20} more")
        print(f"\n{len(bad)} finding(s) over {checked} content document(s).")
        return 1
    # STATE THE DENOMINATOR. A document declaring the hash once is not a finding outside
    # the mirrored bodies, but it is not covered by the agreement rule either, and a
    # population that shrinks in silence is a gate that quietly stops meaning anything.
    print(f"provenance spelling: {checked} content document(s); {both} declare the source "
          f"hash in both places and every pair agrees. {fm_only} carry frontmatter only "
          f"and {prose_only} carry the provenance line only — none in {'/'.join(MIRRORED_BODIES)}, "
          f"which are required to carry both.")
    return 0


# ---------------------------------------------------------------- selftest

def _committed() -> tuple:
    """A real committed rule, as (site, body, text). Proving these rules on a fixture would
    prove them about a document shape the corpus may not have."""
    for p in (REPO_ROOT / "rules").rglob("oar-*.md"):
        text = p.read_text()
        fm, _, prose, _ = spellings(text)
        if fm and prose:
            rel = p.relative_to(REPO_ROOT)
            return str(rel), rel.parts[0], text
    raise SystemExit("no committed rule carries both spellings — the corpus this gate "
                     "governs does not have the shape it assumes")


def _case(fails: list, name: str, rule: str, site: str, body: str, text: str) -> None:
    got = [f.rule for f in findings(site, body, text)]
    if rule not in got:
        fails.append(f"FAIL {name}: expected [{rule}], got {got or 'no finding'} — the "
                     f"gate cannot see the case it exists for")


def cmd_selftest() -> int:
    fails = []
    site, body, text = _committed()

    # THE GUARD THAT MUST NOT FIRE, first: the unmutated document is clean. Without this
    # every case below could be firing on a document that was already broken.
    clean = findings(site, body, text)
    if clean:
        fails.append(f"FAIL a-committed-document-produces-no-finding-unmutated: "
                     f"{[f.rule for f in clean]}")

    # THE CASE #244 PRODUCED, on 36,952 documents at once.
    drifted = PROSE_RE.sub(lambda m: f"· {m.group(1)}sha256 `{'a' * 64}`", text, count=1)
    _case(fails, "a-document-whose-two-spellings-disagree-is-caught",
          "the-two-spellings-of-a-documents-source-hash-agree", site, body, drifted)

    # ...AND FROM THE OTHER SIDE. Re-stamping the prose line and not the frontmatter is
    # the same defect and must not pass because the mutation ran the other way.
    other = FM_RE.sub(f'source_sha256: "{"b" * 64}"', text, count=1)
    _case(fails, "...and so is the same drift written the other way round",
          "the-two-spellings-of-a-documents-source-hash-agree", site, body, other)

    # A MIRRORED-LAW DOCUMENT THAT DROPS EITHER SPELLING. Dropping one is not a
    # disagreement -- there is nothing left to disagree with -- so the rule above cannot
    # see it, which is exactly how coverage shrinks without a gate noticing.
    _case(fails, "a-rule-that-drops-its-provenance-line-is-caught",
          "a-mirrored-law-document-declares-its-source-hash-in-both-places",
          site, body, PROSE_RE.sub("· sha256 `gone`", text, count=1))
    _case(fails, "...and one that drops its frontmatter field",
          "a-mirrored-law-document-declares-its-source-hash-in-both-places",
          site, body, FM_RE.sub("source_sha256: null", text, count=1))

    # TWO PROSE HASHES. This module compares the first; a second would be unchecked.
    doubled = text.replace("\n- See [CHANGELOG]",
                           f"\n- Source: <http://example.invalid> · sha256 `{'c' * 64}`\n"
                           f"- See [CHANGELOG]", 1)
    _case(fails, "a-document-carrying-two-provenance-hashes-is-caught",
          "a-document-declares-at-most-one-prose-source-hash", site, body, doubled)

    # AN AGENCY DOCUMENT MAY DECLARE IT ONCE. 107 legitimately do; a gate that failed on
    # them would have been switched off on its first run.
    if findings("agencies/x/policies/y.md", "agencies",
                FM_RE.sub("source_sha256: null", text, count=1)):
        fails.append("FAIL an-agency-document-declaring-the-hash-once-is-not-a-finding: "
                     "the 107 that legitimately do would fail this gate on arrival")

    # NOTHING IN THIS PROOF WROTE TO THE WORKING TREE (#252). Every rule above was decided
    # from a string; this asserts the file behind them is untouched.
    if (REPO_ROOT / site).read_text() != text:
        fails.append("FAIL nothing-in-this-proof-wrote-to-the-working-tree: "
                     f"{site} changed while the selftest ran")

    declared = {"the-two-spellings-of-a-documents-source-hash-agree",
                "a-mirrored-law-document-declares-its-source-hash-in-both-places",
                "a-document-declares-at-most-one-prose-source-hash"}
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
