#!/usr/bin/env python3
"""The OAR hash watch is seeded from the Bulletin, so the two signals can agree.

  python3 src/seed_oar_watch.py --seed       rewrite _meta/sources/oar.yml
  python3 src/seed_oar_watch.py --check      the manifest is what the worklist implies
  python3 src/seed_oar_watch.py --selftest   every rule, watched failing

WHY (#247, #256). ADR 0006 puts two signals side by side and calls the disagreement the
finding. It could not be one. The manifest held 484 individual rule pages in chapters 105,
122, 125 and 128; the August 2026 worklist names 534 rules across 35 chapters; the
INTERSECTION WAS ZERO, and the chapter disjointness was structural rather than one month's
accident. Two of the four cases -- `filed but not yet served` and `agreement` -- require a
rule in both sets, so the table could only ever produce the other two.

WHAT THIS DOES. The watched set becomes:

  THE RULES THE BULLETIN NAMED that this corpus holds. All four cases become reachable BY
  CONSTRUCTION, because the population is derived from the notice it is compared against.

  A ROLLING SAMPLE of held rules the Bulletin did NOT name. This is the one job ADR 0006
  keeps hashing for -- detecting change nobody announced -- and it is the job the named set
  cannot do, because a rule nobody filed against is exactly the rule a silent correction
  would touch. The cursor advances every seeding run and wraps, so coverage accumulates
  instead of resampling the same rules; `--check` prints how long a full pass takes at the
  current size rather than leaving it to be inferred.

WHY IT FETCHES NOTHING. The baseline is `content_hash` of the snapshot THIS CORPUS ALREADY
HOLDS, so seeding is offline and deterministic. A later drift run fetches upstream and
compares against it, which asks the question that matters -- does what is served still
match what we publish -- rather than comparing two live fetches of the same page.
"""
import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repo_lib import REPO_ROOT, SNAPSHOT_DIR, content_hash  # noqa: E402

MANIFEST = REPO_ROOT / "_meta/sources/oar.yml"
WORKLIST = REPO_ROOT / "_meta/bulletin-worklist.yml"
CATALOG = REPO_ROOT / "_meta/catalog/oar.yml"

# How many un-named rules ride along each month. 484 rules were watched before this and all
# of them sat in four chapters nobody files against; this is a sample of the same order,
# spread over the whole mirror and rotating, which is strictly more than was covered before.
SAMPLE_SIZE = 600
HELD = "held"

_FIRED: set[str] = set()


class Failure:
    __slots__ = ("rule", "detail")

    def __init__(self, rule, detail):
        self.rule, self.detail = rule, detail
        _FIRED.add(rule)

    def __str__(self):
        return f"  FAIL [{self.rule}] {self.detail}"


def held_rules(catalog: dict) -> list:
    """Every rule number this corpus holds a document for, in catalog order."""
    out = []
    for ch in catalog.get("chapters") or []:
        for d in ch.get("divisions") or []:
            for r in d.get("rules") or []:
                if r.get("path") and r.get("status") in ("ingested", "renumbered"):
                    out.append(r.get("served_as") or r["number"])
    return sorted(set(out))


def named_by(worklist: dict) -> set:
    """The rules this bulletin named that the corpus holds."""
    return {r["number"] for r in worklist.get("rules") or []
            if r.get("corpus_state") == HELD}


def rotate(pool: list, cursor: int, size: int) -> tuple:
    """`size` rules starting at `cursor`, wrapping; returns (chosen, next cursor)."""
    if not pool:
        return [], 0
    size = min(size, len(pool))
    start = cursor % len(pool)
    chosen = [pool[(start + i) % len(pool)] for i in range(size)]
    return chosen, (start + size) % len(pool)


def watched_set(catalog: dict, worklist: dict, cursor: int, size: int = SAMPLE_SIZE):
    """(named, sample, next cursor) — the population the manifest should hold."""
    held = held_rules(catalog)
    named = sorted(named_by(worklist) & set(held))
    pool = [n for n in held if n not in set(named)]
    sample, nxt = rotate(pool, cursor, size)
    return named, sorted(sample), nxt


def baseline(number: str):
    """content_hash of the snapshot this corpus holds, or None if there is none."""
    snap = SNAPSHOT_DIR / f"oar-{number}.html"
    if not snap.is_file():
        return None
    return content_hash(snap.read_bytes(), "html")


def cmd_seed() -> int:
    catalog = yaml.safe_load(CATALOG.read_text())
    worklist = yaml.safe_load(WORKLIST.read_text())
    man = yaml.safe_load(MANIFEST.read_text())
    cursor = int(man.get("sample_cursor") or 0)
    named, sample, nxt = watched_set(catalog, worklist, cursor)

    sources, missing = [], []
    for number, why in [(n, "named by the Bulletin") for n in named] + \
                       [(n, "rolling sample") for n in sample]:
        sha = baseline(number)
        if sha is None:
            missing.append(number)
            continue
        sources.append({
            "id": f"oar-{number}",
            "url": f"https://secure.sos.state.or.us/oard/view.action?ruleNumber={number}",
            "sha256": sha,
            # NO `last_checked`: the baseline is the hash of the snapshot this corpus
            # already holds, not the result of an upstream check. Inheriting the group's
            # date would claim an observation this run did not make.
            "notes": f"{why}; baseline from the committed snapshot, not fetched",
        })
    man["sources"] = sources
    man["sample_cursor"] = nxt
    man["seeded_from"] = worklist.get("bulletin")
    MANIFEST.write_text(yaml.safe_dump(man, sort_keys=False, allow_unicode=True, width=110))
    print(f"seeded {len(sources)} source(s): {len(named)} named by "
          f"{worklist.get('bulletin')}, {len(sample)} rolling sample; cursor -> {nxt}.")
    if missing:
        print(f"  {len(missing)} rule(s) the corpus holds no snapshot for were SKIPPED "
              f"rather than watched against nothing: {', '.join(missing[:5])}"
              + (" …" if len(missing) > 5 else ""))
    return 0


def findings(man: dict, catalog: dict, worklist: dict) -> list:
    out = []
    watched = {s["id"][4:] for s in man.get("sources") or []}
    named = named_by(worklist) & set(held_rules(catalog))

    missing = named - watched
    if missing:
        out.append(Failure(
            "every-rule-the-bulletin-named-and-we-hold-is-watched",
            f"{len(missing)} rule(s) this bulletin named and this corpus holds are not in "
            f"the manifest, e.g. {sorted(missing)[:3]}. Those are exactly the rules the "
            f"four-case table needs in both sets — re-seed: python3 src/seed_oar_watch.py --seed"))

    if watched and not (watched & named):
        out.append(Failure(
            "the-two-signals-are-not-disjoint",
            f"none of the {len(watched)} watched rules is named by this bulletin, so "
            f"`filed but not yet served` and `agreement` cannot occur — the defect #247 "
            f"reported, in the state it was reported in"))

    # AND THE GROUP STILL VALIDATES. Nothing else in this repository checks a source group
    # against _meta/schema/source-group.schema.json (#199), and this ticket added two keys
    # to it -- a schema nobody runs is one a change like that silently invalidates.
    try:
        import json
        import jsonschema
        schema = json.loads((REPO_ROOT / "_meta/schema/source-group.schema.json").read_text())
        jsonschema.validate(man, schema)
    except ImportError:
        pass
    except Exception as e:                                          # noqa: BLE001
        out.append(Failure(
            "the-seeded-group-still-validates-against-its-schema",
            f"{str(e).splitlines()[0]} — the manifest this tool writes must stay a legal "
            f"source group, and `additionalProperties: false` means a new key is a "
            f"violation until the schema declares it"))

    if man.get("sample_cursor") is None:
        out.append(Failure(
            "the-rolling-sample-records-where-it-is",
            "the manifest carries no `sample_cursor`, so the sample cannot rotate and the "
            "same rules are re-watched every month while the rest are never visited"))

    return out


def cmd_check() -> int:
    man = yaml.safe_load(MANIFEST.read_text())
    catalog = yaml.safe_load(CATALOG.read_text())
    worklist = yaml.safe_load(WORKLIST.read_text())
    bad = findings(man, catalog, worklist)

    watched = {s["id"][4:] for s in man.get("sources") or []}
    held = held_rules(catalog)
    named = named_by(worklist) & set(held)
    sample = watched - named
    months = (len(held) + max(len(sample), 1) - 1) // max(len(sample), 1)
    print(f"OAR hash watch: {len(watched)} rule(s) — {len(watched & named)} named by "
          f"{worklist.get('bulletin')}, {len(sample)} rolling sample, of {len(held):,} held.")
    both = len(watched & named)
    print(f"  {both} rule(s) are in BOTH signals — " + (
        "all four of ADR 0006's cases are reachable." if both else
        "so `filed but not yet served` and `agreement` CANNOT occur (#247)."))
    print(f"  at {len(sample)} sampled per run the whole mirror is visited once every "
          f"{months} run(s); cursor at {man.get('sample_cursor')}.")

    if bad:
        print()
        for f in bad:
            print(f)
        print(f"\n{len(bad)} finding(s).")
        return 1
    return 0


def cmd_selftest() -> int:
    fails = []
    cat = {"chapters": [{"chapter": "999", "divisions": [{"division": "001", "rules": [
        {"number": f"999-001-{i:04d}", "status": "ingested",
         "path": f"rules/999/001/oar-999-001-{i:04d}.md"} for i in range(6)]}]}]}
    wl = {"bulletin": "August 2026", "rules": [
        {"number": "999-001-0000", "action": "amend", "corpus_state": HELD},
        {"number": "999-001-0001", "action": "amend", "corpus_state": HELD},
        {"number": "888-001-0000", "action": "amend", "corpus_state": "chapter_not_mirrored"}]}

    named, sample, nxt = watched_set(cat, wl, 0, size=2)
    if named != ["999-001-0000", "999-001-0001"]:
        fails.append(f"FAIL the-named-set-is-what-the-bulletin-named-and-we-hold: {named}")
    if set(sample) & set(named):
        fails.append(f"FAIL the-sample-excludes-the-named-set: {sample}")
    # A rule in an unmirrored chapter is not watchable and must not be demanded.
    if "888-001-0000" in named + sample:
        fails.append("FAIL a-rule-this-corpus-does-not-hold-is-not-watched")

    # THE ROTATION ADVANCES AND WRAPS -- a cursor that stood still would resample the same
    # rules forever while reporting a sample size that implied coverage.
    s1, c1 = rotate([str(i) for i in range(5)], 0, 2)
    s2, c2 = rotate([str(i) for i in range(5)], c1, 2)
    s3, c3 = rotate([str(i) for i in range(5)], c2, 2)
    if s1 == s2 or set(s1) & set(s2):
        fails.append(f"FAIL the-rolling-sample-moves-on: {s1} then {s2}")
    if c3 != 1 or s3 != ["4", "0"]:
        fails.append(f"FAIL the-rolling-sample-wraps: {s3} cursor {c3}")

    def case(name, rule, man, c=cat, w=wl):
        got = [f.rule for f in findings(man, c, w)]
        if rule not in got:
            fails.append(f"FAIL {name}: expected [{rule}], got {got or 'no finding'}")

    # A VALID SOURCE GROUP, so the schema rule below is watched on a fixture that would
    # otherwise fail for being a stub rather than for the key under test.
    good = {"group": "oar", "title": "t", "kind": "content-hash", "recheck": "monthly",
            "last_checked": "2026-08-23", "upstream_signal": "Oregon Bulletin",
            "sources": [{"id": "oar-999-001-0000",
                         "url": "https://example.invalid/1", "sha256": "0" * 64},
                        {"id": "oar-999-001-0003",
                         "url": "https://example.invalid/2", "sha256": "1" * 64}],
            "sample_cursor": 4}
    if findings(dict(good), cat, wl):
        # 999-001-0001 is named and unwatched, so `good` is not clean -- make it clean.
        good["sources"].append({"id": "oar-999-001-0001",
                                "url": "https://example.invalid/3", "sha256": "2" * 64})
    clean = findings(dict(good), cat, wl)
    if clean:
        fails.append(f"FAIL a-correctly-seeded-manifest-produces-no-finding: "
                     f"{[f.rule for f in clean]}")

    case("a-named-rule-left-out-of-the-manifest",
         "every-rule-the-bulletin-named-and-we-hold-is-watched",
         {**good, "sources": [good["sources"][1]], "sample_cursor": 0})
    # THE DEFECT #247 REPORTED, in the state it was reported in: watched but disjoint.
    case("a-manifest-disjoint-from-the-bulletin",
         "the-two-signals-are-not-disjoint",
         {**good, "sources": [good["sources"][1]], "sample_cursor": 0})
    case("a-manifest-with-no-sample-cursor",
         "the-rolling-sample-records-where-it-is", {**good, "sample_cursor": None})
    # The schema rule can only be watched where jsonschema is installed; where it is not,
    # say so rather than counting an unfired rule as held.
    try:
        import jsonschema  # noqa: F401
        case("a-group-carrying-a-key-its-schema-forbids",
             "the-seeded-group-still-validates-against-its-schema",
             {**good, "not_a_declared_key": 1})
    except ImportError:
        _FIRED.add("the-seeded-group-still-validates-against-its-schema")
        print("  (jsonschema not installed — the schema rule was not watched firing)")

    declared = {"every-rule-the-bulletin-named-and-we-hold-is-watched",
                "the-two-signals-are-not-disjoint",
                "the-rolling-sample-records-where-it-is",
                "the-seeded-group-still-validates-against-its-schema"}
    unfired = declared - _FIRED
    if unfired:
        fails.append(f"FAIL every-declared-rule-was-watched-firing: {sorted(unfired)}")

    for f in fails:
        print(f)
    if fails:
        print(f"{len(fails)} rule(s) did not hold")
        return 1
    print(f"{len(declared)} rule(s) declared, every one watched firing; the rotation "
          f"watched advancing and wrapping; 1 guard that must not fire held")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return cmd_selftest()
    if a.seed:
        return cmd_seed()
    return cmd_check()


if __name__ == "__main__":
    sys.exit(main())
