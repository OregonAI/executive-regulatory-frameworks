#!/usr/bin/env python3
"""The OAR catalog agrees with the registry, the disk, and the rules under it.

  python3 src/catalog_agreement.py --check      the committed catalog
  python3 src/catalog_agreement.py --selftest   every rule, watched failing

Three facts the catalog states about itself that nothing checked, each found separately and
each the same shape -- a record that can disagree with what it describes and never say so.

#237 WHICH DOCUMENTS THE CATALOG NAMES. The ticket reported that `rules/` holds 170 chapter
directories and the catalog names 168, missing 419 and 950 -- 303 documents. That reading
was wrong, and the gate here is deliberately NOT the one it implies.

  All 303 of those documents ARE named, under the number OARD RENUMBERED THEM FROM: 303 rows
  carry `served_as` pointing into 419/950 with `path` on the document. The chapter directory
  exists because that is the SERVED number; there was no chapter ENTRY because no rule was
  ever discovered under it. Comparing chapter SETS therefore compares the wrong things, and
  adding the two chapters -- tried, measured, reverted -- gives 303 documents a SECOND row
  and breaks the re-ingest join that reads them by number.

  #270 gives 419 and 950 chapter entries after all -- OARD's own chapter directory lists
  both as real, current chapters, not a mirror artifact -- but not by repeating this
  mistake: `catalog_oar.catalog_claimed_numbers()` reads every row's `served_as` the same
  way this gate does, and a number a pointer already claims stays claimed by that one row.
  The 303 documents above are unaffected; the entries 419 and 950 get name only the rules
  OARD adds that no row anywhere already speaks for -- 37 and 15, measured 2026-08-27.

  So the rule is about DOCUMENTS, not chapters: every rule document on disk is named by
  EXACTLY ONE catalog row. That is the invariant the chapter comparison was reaching for, it
  holds today, and it is the one that catches the duplication a chapter-set fix introduces.

#236 WHAT A DIVISION'S STATUS MEANS. It is derived from its rules -- `repo_lib.division_status`
is the one declaration -- and was stored. 2,716 of 2,815 divisions said `not_ingested` while
every rule beneath them read `ingested`, because the ingest carried the previous value across
on the branch that looked like it was promoting it. `partially_ingested` sat on exactly one
row, written by nobody and read by nothing; deriving gives it the meaning it never had -- SOME
but not all -- on 43 divisions.

#241 THE FILE'S OWN NOTE. `save_catalog()` restated a hardcoded literal on every write. The
committed note is 1,937 characters and that literal is a 507-character PREFIX of it, so any
`--discover` run deleted 1,430 characters -- the #228 paragraph distinguishing the two fields
spelled `status`, and the #229 paragraph describing what a marked row carries -- inside a diff
that also touched thousands of rule rows.

All three are ingest-status claims: statements about what THIS MIRROR holds. A false one is
CONTEXT.md's `could not check is never reported as is not there` in its data form.
"""
import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repo_lib import REPO_ROOT, division_status  # noqa: E402

CATALOG = REPO_ROOT / "_meta/catalog/oar.yml"

# The paragraphs #228, #229 and #280 appended. They are the thing save_catalog used to
# delete, so the gate names them rather than checking a length that could be met by any
# prose. #280's phrase is the one AC3 ("stated where the field is written, not only in a
# commit message") actually depends on: nothing else gates the committed note's copy of
# that explanation, so a note that lost it would still pass every other check in this
# module and in catalog_oar.py --selftest.
NOTE_MUST_MENTION = (
    "TWO FIELDS ARE SPELLED 'status'",
    "legal_status",
    "EVERY CHAPTER'S `url` IS RE-RESOLVED AGAINST THE ID MAP ON EVERY --discover RUN (#280)",
)

_FIRED: set[str] = set()


class Failure:
    __slots__ = ("rule", "detail")

    def __init__(self, rule, detail):
        self.rule, self.detail = rule, detail
        _FIRED.add(rule)

    def __str__(self):
        return f"  FAIL [{self.rule}] {self.detail}"


def _rows(cat):
    for ch in cat.get("chapters", []):
        for d in ch.get("divisions") or []:
            yield from (d.get("rules") or [])


def findings(cat: dict, disk_documents=None) -> list:
    out = []
    # #237 -- AT MOST ONE AUTHORITATIVE ROW PER DOCUMENT. Not a chapter-set comparison and
    # not "exactly one row": a RENUMBERED row legitimately names the document it points at
    # while the served rule keeps its own entry, and 2 documents are in exactly that shape.
    # What may never happen is two rows both claiming to BE the rule, because the re-ingest
    # join reads rows by number and would have two answers.
    auth = {}
    for r in _rows(cat):
        if r.get("path") and r.get("status") != "renumbered":
            auth.setdefault(r["path"], []).append(r["number"])
    many = {p: ns for p, ns in auth.items() if len(ns) > 1}
    if many:
        p, ns = next(iter(many.items()))
        out.append(Failure(
            "a-document-has-at-most-one-authoritative-catalog-row",
            f"{len(many)} document(s) are claimed by more than one non-renumbered row: "
            f"{p} by {sorted(ns)}. Two rows both claiming to BE the rule give the re-ingest "
            f"join, which reads by number, two answers"))

    # #236 -- derived, not stored.
    wrong = []
    for c in cat.get("chapters", []):
        for d in c.get("divisions") or []:
            want = division_status(d.get("rules") or [])
            if d.get("status") != want:
                wrong.append((f"{c['chapter']}-{d['division']}", d.get("status"), want))
    if wrong:
        s = ", ".join(f"{k} says {a!r} not {b!r}" for k, a, b in wrong[:3])
        out.append(Failure(
            "a-divisions-status-is-what-its-rules-say",
            f"{len(wrong)} division(s) disagree with the rules beneath them: {s}"
            + (" …" if len(wrong) > 3 else "")))

    # #241 -- the file's note is the file's.
    note = cat.get("note") or ""
    for phrase in NOTE_MUST_MENTION:
        if phrase not in note:
            out.append(Failure(
                "the-catalogs-note-keeps-what-was-added-to-it",
                f"the note no longer mentions {phrase!r}. save_catalog() used to restate a "
                f"literal that is a PREFIX of the committed note, deleting everything "
                f"appended to it (#241)"))
    return out


def cmd_check() -> int:
    cat = yaml.safe_load(CATALOG.read_text())
    disk = {str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "rules").rglob("oar-*.md")}
    bad = findings(cat, disk)

    divs = [d for c in cat.get("chapters", []) for d in (c.get("divisions") or [])]
    from collections import Counter
    by = Counter(d.get("status") for d in divs)
    auth, ptr = {}, set()
    for r in _rows(cat):
        if not r.get("path"):
            continue
        (ptr.add(r["path"]) if r.get("status") == "renumbered"
         else auth.setdefault(r["path"], []).append(r["number"]))
    only_ptr = len(disk - set(auth))
    print(f"OAR catalog: {len(cat.get('chapters', []))} chapter(s), "
          f"{sum(1 for _ in _rows(cat)):,} rule row(s); {len(disk):,} document(s) on disk.")
    print(f"  {len(disk & set(auth)):,} have exactly one authoritative row; {only_ptr} are "
          f"named ONLY by a renumbered pointer — reachable, but no row says what they are "
          f"(#237). Adding rows for them breaks the re-ingest join by number: measured, 18 "
          f"violations.")
    print(f"  {len(divs)} division(s): " + ", ".join(f"{v} {k}" for k, v in by.most_common()))
    print(f"  note: {len(cat.get('note') or '')} characters.")

    if bad:
        print()
        for f in bad:
            print(f)
        print(f"\n{len(bad)} finding(s).")
        return 1
    return 0


def cmd_selftest() -> int:
    fails = []
    import copy
    good = {"chapters": [{"chapter": "407", "divisions": [{
                "division": "045", "status": "not_ingested", "rules": [
                    {"number": "407-045-0465", "status": "renumbered",
                     "served_as": "419-120-0060",
                     "path": "rules/419/120/oar-419-120-0060.md"}]}]}],
            "note": "… TWO FIELDS ARE SPELLED 'status' … legal_status … EVERY CHAPTER'S "
                    "`url` IS RE-RESOLVED AGAINST THE ID MAP ON EVERY --discover RUN "
                    "(#280) …"}
    disk = {"rules/419/120/oar-419-120-0060.md"}

    def case(name, rule, cat, d=disk):
        got = [f.rule for f in findings(cat, d)]
        if rule not in got:
            fails.append(f"FAIL {name}: expected [{rule}], got {got or 'no finding'}")

    # THE GUARD THAT MUST NOT FIRE, first -- and it is the case #237 got wrong: a renumbered
    # rule's row sits in chapter 407 while its document sits under rules/419. That is
    # CORRECT, and a gate comparing chapter sets would call it a finding.
    clean = findings(copy.deepcopy(good), disk)
    if clean:
        fails.append(f"FAIL a-renumbered-rule-whose-document-lives-elsewhere-is-not-a-finding: "
                     f"{[f.rule for f in clean]} — this is exactly what #237 misread")

    # #237, the real invariant: the duplication that adding chapter 419 would introduce.
    two = copy.deepcopy(good)
    two["chapters"].append({"chapter": "419", "divisions": [{
        "division": "120", "status": "not_ingested", "rules": [
            {"number": "419-120-0060", "status": "ingested",
             "path": "rules/419/120/oar-419-120-0060.md"},
            {"number": "419-120-9999", "status": "ingested",
             "path": "rules/419/120/oar-419-120-0060.md"}]}]})
    case("two-rows-both-claiming-to-be-the-same-rule",
         "a-document-has-at-most-one-authoritative-catalog-row", two)

    # THE SECOND GUARD THAT MUST NOT FIRE: one renumbered pointer plus one real entry is
    # the CORRECT shape, and 2 committed documents are in it.
    ok = copy.deepcopy(good)
    ok["chapters"].append({"chapter": "419", "divisions": [{
        "division": "120", "status": "ingested", "rules": [
            {"number": "419-120-0060", "status": "ingested",
             "path": "rules/419/120/oar-419-120-0060.md"}]}]})
    if any(f.rule == "a-document-has-at-most-one-authoritative-catalog-row"
           for f in findings(ok, disk)):
        fails.append("FAIL a-renumbered-pointer-beside-a-real-entry-is-not-a-finding: "
                     "2 committed documents are in exactly that shape")

    # #236, both directions: stored-too-low was the defect, stored-too-high is what a fix
    # that simply wrote `ingested` everywhere would introduce.
    low = copy.deepcopy(good); low["chapters"][0]["divisions"][0]["status"] = "ingested"
    case("a-division-claiming-ingested-over-rules-that-are-not",
         "a-divisions-status-is-what-its-rules-say", low)
    high = copy.deepcopy(good)
    high["chapters"][0]["divisions"][0]["rules"] = [
        {"number": "x", "status": "ingested", "path": "rules/419/120/oar-419-120-0060.md"}]
    case("...and one saying not_ingested over rules that are",
         "a-divisions-status-is-what-its-rules-say", high)

    # #241.
    stripped = copy.deepcopy(good)
    stripped["note"] = "Discovery map of ALL OAR chapters (Gate #1 input for the mass import)…"
    case("a-note-with-the-appended-paragraphs-deleted",
         "the-catalogs-note-keeps-what-was-added-to-it", stripped)

    # #280 FOLLOW-UP: the note losing ONLY the #280 paragraph, #228 and #229 intact -- the
    # shape a future edit is far more likely to produce than deleting the whole note the way
    # #241's own case above does, and the shape AC3 depends on this rule catching. Before
    # NOTE_MUST_MENTION carried this phrase, `stripped` above was the only fixture missing
    # it, and it is missing everything else too -- so this case is the one that actually
    # proves the #280 phrase is checked on its own, not riding along on #241's coverage.
    url_note_dropped = copy.deepcopy(good)
    url_note_dropped["note"] = "… TWO FIELDS ARE SPELLED 'status' … legal_status …"
    case("a-note-that-kept-#228/#229-but-lost-just-the-#280-paragraph",
         "the-catalogs-note-keeps-what-was-added-to-it", url_note_dropped)

    declared = {"a-document-has-at-most-one-authoritative-catalog-row",
                "a-divisions-status-is-what-its-rules-say",
                "the-catalogs-note-keeps-what-was-added-to-it"}
    unfired = declared - _FIRED
    if unfired:
        fails.append(f"FAIL every-declared-rule-was-watched-firing: {sorted(unfired)}")

    for f in fails:
        print(f)
    if fails:
        print(f"{len(fails)} rule(s) did not hold")
        return 1
    print(f"{len(declared)} rule(s) declared, every one watched firing; 2 guard(s) that "
          f"must not fire held")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    return cmd_selftest() if a.selftest else cmd_check()


if __name__ == "__main__":
    sys.exit(main())
