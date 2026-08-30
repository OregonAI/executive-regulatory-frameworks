#!/usr/bin/env python3
"""What the OAR hash watch covers is stated, and ADR 0006 is held to the manifest.

  python3 src/oar_watch_coverage.py --check      the manifest, the corpus, the worklist
  python3 src/oar_watch_coverage.py --selftest   every rule, watched failing

WHY THIS EXISTS (#247). ADR 0006 said `corpus-detect-changes` hashes "the 484 OAR CHAPTER
sources" standing for "36,955 rule documents". Neither half was true. `_meta/sources/oar.yml`
holds 484 INDIVIDUAL RULE PAGES in four chapters -- 125 (420), 122 (33), 128 (22), 105 (9) --
and `--check` prints the coverage that gives against the corpus and the mirrored chapters,
live, on every run (the "OAR hash watch: ..." line below).

The consequence is worse than the arithmetic. The August 2026 worklist names 534 rules across
35 chapters and NONE of them is 105, 122, 125 or 128, so the intersection of "rules the
Bulletin named" and "rules hashing watches" is ZERO. Two of ADR 0006's four cases -- *filed
but not yet served* and *agreement* -- require a rule in both sets, and there is none. The
table cannot produce them.

And it failed silently: a drift run prints `oar 484/484` and an operator concludes the OAR
mirror is under upstream-change surveillance. It is under surveillance at 1.3%. That is the
substitution CONTEXT.md forbids -- could not check reported as is not there -- reached by
arithmetic rather than by a missing file.

THIS IS THE NINTH INSTANCE of one fact declared twice with nothing gating agreement: the ADR
describing the manifest, and the manifest. Every previous one was invisible until something
moved; this one was invisible because nothing ever moved in the four chapters nobody files
against.

WHAT THIS GATE DOES. It states the coverage on every run so the number is never implied, and
it fails when the ADR's prose and the manifest stop agreeing -- so correcting the ADR once
cannot quietly rot again the next time the manifest is reseeded.
"""
import argparse
import collections
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repo_lib import REPO_ROOT  # noqa: E402

MANIFEST = REPO_ROOT / "_meta/sources/oar.yml"
WORKLIST = REPO_ROOT / "_meta/bulletin-worklist.yml"
ADR = REPO_ROOT / "docs/adr/0006-the-bulletin-is-notice-hashing-is-observation.md"

_FIRED: set[str] = set()


class Failure:
    __slots__ = ("rule", "detail")

    def __init__(self, rule, detail):
        self.rule, self.detail = rule, detail
        _FIRED.add(rule)

    def __str__(self):
        return f"  FAIL [{self.rule}] {self.detail}"


def measure(manifest: dict, worklist: dict, mirrored_chapters: set) -> dict:
    """Everything this gate decides from, taken once."""
    watched = {s["id"][4:] for s in manifest["sources"]}
    by_chapter = collections.Counter(n.split("-")[0] for n in watched)
    named = {r["number"] for r in worklist.get("rules", [])}
    return {
        "watched": len(watched),
        "watched_chapters": set(by_chapter),
        "by_chapter": dict(by_chapter),
        "named": len(named),
        "named_chapters": {n.split("-")[0] for n in named},
        "overlap": len(watched & named),
        "mirrored_chapters": len(mirrored_chapters),
        "mirrored_rules": len(list((REPO_ROOT / "rules").rglob("oar-*.md")))
        if (REPO_ROOT / "rules").is_dir() else 0,
    }


def findings(m: dict, adr_text: str) -> list:
    """The ADR must say what the manifest holds, in numbers a reader can check."""
    out = []

    # ADR 0006 must not call these chapter sources -- they are individual rule pages, and
    # that error is what made "484 stand for 36,955" look like arithmetic instead of a gap.
    if re.search(r"\b484 OAR chapter sources\b|\b484 chapter sources\b", adr_text):
        out.append(Failure(
            "the-adr-does-not-call-the-manifest-chapter-sources",
            "ADR 0006 still calls the manifest '484 chapter sources'. They are 484 "
            "individual rule pages; the phrasing is what hid a 1.3% coverage figure "
            "behind what looked like chapter-granularity coverage of the whole mirror"))

    # The coverage figure must appear, so a reader is never left to infer it from 484.
    pct = 100.0 * m["watched"] / max(m["mirrored_rules"], 1)
    if f"{pct:.1f}%" not in adr_text:
        out.append(Failure(
            "the-adr-states-the-coverage-it-actually-has",
            f"ADR 0006 does not state the coverage the manifest gives: {m['watched']} of "
            f"{m['mirrored_rules']} rule documents is {pct:.1f}%, and a number left to be "
            f"inferred is one nobody infers"))

    # And the disjointness, while it holds, must be stated rather than discovered again.
    if m["overlap"] == 0 and "intersection is zero" not in adr_text:
        out.append(Failure(
            "the-adr-states-that-the-two-signals-are-disjoint",
            f"{m['watched']} watched rules and {m['named']} named by the Bulletin share "
            f"NONE, so two of the ADR's four cases cannot occur — the table reads as if "
            f"all four were live and nothing says otherwise"))

    return out


def cmd_check() -> int:
    manifest = yaml.safe_load(MANIFEST.read_text())
    worklist = yaml.safe_load(WORKLIST.read_text())
    mirrored = {p.name for p in (REPO_ROOT / "rules").iterdir() if p.is_dir()}
    m = measure(manifest, worklist, mirrored)
    bad = findings(m, ADR.read_text())

    # STATED ON EVERY RUN, pass or fail. The whole defect was a number nobody printed.
    pct = 100.0 * m["watched"] / max(m["mirrored_rules"], 1)
    print(f"OAR hash watch: {m['watched']} rule page(s) in {len(m['watched_chapters'])} "
          f"chapter(s) {sorted(m['watched_chapters'])} — {pct:.1f}% of {m['mirrored_rules']:,} "
          f"rule documents across {m['mirrored_chapters']} mirrored chapters.")
    print(f"  this month's Bulletin names {m['named']} rule(s) in "
          f"{len(m['named_chapters'])} chapter(s); {m['overlap']} of them are watched.")
    if m["overlap"] == 0:
        print("  the two signals are DISJOINT: ADR 0006's 'filed but not yet served' and "
              "'agreement' cases cannot occur on this manifest (#247).")

    if bad:
        print()
        for f in bad:
            print(f)
        print(f"\n{len(bad)} finding(s).")
        return 1
    return 0


def cmd_selftest() -> int:
    fails = []
    mani = {"sources": [{"id": f"oar-125-001-{i:04d}"} for i in range(3)]}
    work = {"rules": [{"number": "411-057-0100"}, {"number": "333-011-0310"}]}
    m = measure(mani, work, {"125", "411", "333"})
    if m["overlap"] != 0:
        fails.append(f"FAIL the-fixture-is-disjoint-as-the-real-data-is: {m['overlap']}")

    good = (f"484 individual rule pages … {100.0 * m['watched'] / max(m['mirrored_rules'],1):.1f}% "
            f"… the intersection is zero …")

    def case(name, rule, text):
        got = [f.rule for f in findings(m, text)]
        if rule not in got:
            fails.append(f"FAIL {name}: expected [{rule}], got {got or 'no finding'}")

    case("an-adr-calling-them-chapter-sources-is-caught",
         "the-adr-does-not-call-the-manifest-chapter-sources",
         good + " hashes the 484 chapter sources and reports what moved")
    case("an-adr-that-omits-the-coverage-figure-is-caught",
         "the-adr-states-the-coverage-it-actually-has",
         "484 individual rule pages … the intersection is zero …")
    case("an-adr-that-omits-the-disjointness-is-caught",
         "the-adr-states-that-the-two-signals-are-disjoint",
         f"484 individual rule pages … {100.0 * m['watched'] / max(m['mirrored_rules'],1):.1f}% …")

    # THE GUARD THAT MUST NOT FIRE: prose that says all three things is clean.
    left = findings(m, good)
    if left:
        fails.append(f"FAIL correct-prose-produces-no-finding: {[f.rule for f in left]}")

    # AND THE DISJOINTNESS RULE MUST NOT FIRE WHEN THE SIGNALS OVERLAP -- otherwise fixing
    # the manifest would leave a gate demanding the ADR keep saying they are disjoint.
    m2 = measure({"sources": [{"id": "oar-411-057-0100"}]}, work, {"411"})
    if any(f.rule == "the-adr-states-that-the-two-signals-are-disjoint"
           for f in findings(m2, f"{100.0 * m2['watched'] / max(m2['mirrored_rules'],1):.1f}%")):
        fails.append("FAIL the-disjointness-rule-is-silent-once-they-overlap: it would "
                     "outlive the defect and demand prose that had become false")

    declared = {"the-adr-does-not-call-the-manifest-chapter-sources",
                "the-adr-states-the-coverage-it-actually-has",
                "the-adr-states-that-the-two-signals-are-disjoint"}
    unfired = declared - _FIRED
    if unfired:
        fails.append(f"FAIL every-declared-rule-was-watched-firing: {sorted(unfired)}")

    for f in fails:
        print(f)
    if fails:
        print(f"{len(fails)} rule(s) did not hold")
        return 1
    print(f"{len(declared)} rule(s) declared, every one watched firing; "
          f"2 guard(s) that must not fire held")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    return cmd_selftest() if a.selftest else cmd_check()


if __name__ == "__main__":
    sys.exit(main())
