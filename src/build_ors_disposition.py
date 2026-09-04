#!/usr/bin/env python3
"""Mine ORS dispositions — repealed AND renumbered — from already-cached chapter snapshots.
Pure mechanical parsing of already-committed content, no new fetches, no fabrication.

Why: OAR rules routinely cite ORS sections that no longer exist because they were
genuinely repealed (this is legally normal — an Oregon rule stays valid citing a repealed
section until the agency files a housekeeping correction). A repealed section was never
going to get a document (there's no text to ingest), but the *disposition* — "repealed in
YYYY" vs. "we just haven't looked at this citation yet" — is exactly the distinction this
repo's anti-fabrication rules require before treating a dangling citation as noteworthy.

The disposition is already sitting in the raw chapter snapshot text as a repeal stub, e.g.:
  "184.616 [1979 c.186 §§2,3; 2003 c.14 §87; repealed by 2017 c.750 §140]"
catalog_ors.py's parse_toc() already recognizes and discards these (a real catchline is
always capitalized; a stub like this has no catchline at all). This script mines the same
pattern instead of discarding it.

  python3 src/build_ors_disposition.py            # scan + write cache
  python3 src/build_ors_disposition.py --check     # exit 1 if stale (CI)
"""
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT, content_files, ws_only
# The toolkit's render-and-compare: missing, unreadable, stale and current kept apart,
# and never raising (corpus-toolkit repo.check_generated). Replaces a hand-rolled compare
# that 22 scripts each carried (card 3 of the 2026-09-02 review).
from corpus_toolkit.repo import check_generated as _tk_check_generated  # noqa: E402

SNAP = REPO_ROOT / "_meta/snapshots"
OUT = REPO_ROOT / "_meta/catalog/ors-disposition.yml"

# A bare repeal stub: a section number immediately followed by a legislative-history
# bracket whose text says it was repealed. Requires the number to NOT already have a real
# ingested document — a currently-live section's own history bracket can legitimately
# mention "repealed" in reference to an unrelated earlier subsection/session law, so we
# only trust this pattern when there's no actual document to contradict it.
REPEAL_RE = re.compile(r"\b(\d{2,3}[A-Z]?\.\d{3})\s*\[([^\]]*)\]")
REPEALED_BY_RE = re.compile(r"repealed\s+by\s+.*?\b(1[89]\d\d|20\d\d)\b", re.I)

# ---------------------------------------------------------------- renumbering (issue #91)
#
# A RENUMBERED SECTION IS A DIFFERENT DISPOSITION FROM A REPEALED ONE. The text still exists;
# it moved. Until this was mined both looked identical to a caller — a citation resolving to
# nothing — and `resolve_citation` answered "holds no document with id ors-197.296" for a
# section whose text is right here under 197A.350. That is the same shape of message that
# produced two false coverage-gap issues against this corpus (#81, #90): true, and read as
# "the corpus is incomplete" when the corpus is not incomplete and the citation is historical.
#
# Measured from oregon-counties: 432 of 853 unresolved county citations — half the residual —
# are sections whose stub is sitting in a snapshot here unmined.
#
# THE PHRASE IS THE EVIDENCE. Ten distinct forms occur across 8,022 brackets and they do not
# all mean the same thing, so each is either parsed into an explicit shape or left out and
# counted. Nothing here infers a target from a number that happens to be nearby.
RENUM_TAIL_RE = re.compile(r"renumbered\s+([^;\]]*)", re.I)
SEC_RE = re.compile(r"\b\d{1,3}[A-Z]?\.\d{3}\b")
YEAR_RE = re.compile(r"\bin\s+((?:1[89]|20)\d\d)\b", re.I)


def parse_renumbering(bracket: str) -> dict | None:
    """One renumbering stub -> {targets, year, form, partial} or None if not safely parsable.

    The distinctions that matter, each observed in the snapshots:

      "renumbered 100.483 in 2019"                 one target                        (5,467)
      "renumbered 107.430"                         one target, no year               (2,384)
      "renumbered 21.115 and then 21.375"          a CHAIN — the text ended up at        (52)
                                                   the last hop, so that is the target
      "renumbered 197A.350 and 197A.355 in 2019"   SPLIT into two — both recorded and
                                                   neither chosen, because choosing
                                                   would be inventing the answer
      "renumbered 196.800 to 196.900 in 1989"      a RANGE: the section became a whole
                                                   series. NOT two targets, and left
                                                   unparsed rather than misrepresented       (9)
      "renumbered as part of 330.990"              only PART of the text moved; recorded
                                                   with partial: true so nobody reads it
                                                   as a clean redirect                       (7)
      "renumbered 181A.110 (3) in 2015"            landed in a subsection; the target is
                                                   still the section, subsection dropped
                                                   because this corpus ids sections
    """
    m = RENUM_TAIL_RE.search(bracket)
    if not m:
        return None
    tail = m.group(1).strip()

    # A range is not a list of targets. `X to Y` means the section became the whole series,
    # and recording X and Y as two destinations would assert something the source does not.
    if re.search(r"\b\d{1,3}[A-Z]?\.\d{3}\s+to\s+\d{1,3}[A-Z]?\.\d{3}\b", tail, re.I):
        return None

    secs = SEC_RE.findall(tail)
    if not secs:
        return None

    partial = bool(re.match(r"as\s+part\s+of\b", tail, re.I))
    # "A and then B": the section moved twice and lives at B. Intermediate hops are not
    # destinations — a caller sent to A would find nothing there either.
    if re.search(r"\band\s+then\b", tail, re.I):
        targets = [secs[-1]]
    else:
        targets = list(dict.fromkeys(secs))

    y = YEAR_RE.search(tail)
    return {"targets": [t.lower() for t in targets],
            "year": int(y.group(1)) if y else None,
            "form": ws_only(f"renumbered {tail}")[:120],
            "partial": partial}


def find_renumberings(raw_text: str, existing_ids: set, repealed: set) -> dict:
    """{section_lower: parsed} for renumbering stubs, and a count of the ones left alone.

    Same two guards as the repeal miner, for the same reason: a section with a real ingested
    document has current text, so a "renumbered" mention in its history bracket refers to
    something else. Repeal wins where a bracket says both, so this cannot disturb any of the
    21,279 entries already recorded.
    """
    t = ws_only(raw_text)
    out, skipped = {}, 0
    for m in REPEAL_RE.finditer(t):
        sec, bracket = m.groups()
        if f"ors-{sec.lower()}" in existing_ids or sec.lower() in repealed:
            continue
        if "renumber" not in bracket.lower():
            continue
        parsed = parse_renumbering(bracket)
        if parsed is None:
            skipped += 1
            continue
        out[sec.lower()] = parsed
    out["__skipped__"] = skipped
    return out


def find_repeals(raw_text: str, existing_ids: set) -> dict:
    """{section_lower: repeal_year} for bare repeal stubs not already ingested as docs."""
    t = ws_only(raw_text)
    out = {}
    for m in REPEAL_RE.finditer(t):
        sec, bracket = m.groups()
        doc_id = f"ors-{sec.lower()}"
        if doc_id in existing_ids:
            continue  # has real current text; the "repealed" mention refers to something else
        rb = REPEALED_BY_RE.search(bracket)
        if rb:
            out[sec.lower()] = int(rb.group(1))
    return out


def compute() -> dict:
    existing_ids = {p.stem for p in content_files() if p.parent.name == "statutes"}
    entries, renum, skipped = {}, {}, 0
    for snap in sorted(SNAP.glob("ors-chapter-*.txt")):
        raw = snap.read_text(encoding="utf-8", errors="replace")
        entries.update(find_repeals(raw, existing_ids))
    # Second pass, after every repeal is known: repeal wins wherever a bracket says both, so
    # the 21,279 rows this file already carried are untouched by construction.
    for snap in sorted(SNAP.glob("ors-chapter-*.txt")):
        raw = snap.read_text(encoding="utf-8", errors="replace")
        found = find_renumberings(raw, existing_ids, set(entries))
        skipped += found.pop("__skipped__", 0)
        renum.update(found)

    # LEGAL STATUS - NOT-A-RULE: an ORS section's disposition, mined from the chapter page's
    # own repeal brackets. It is a claim about a STATUTE's force, and the Oregon Bulletin --
    # ADR 0006's writer of a RULE's legal status -- does not publish statutes.
    rows = [{"section": sec, "status": "repealed", "year": year}
            for sec, year in sorted(entries.items())]
    for sec, p in sorted(renum.items()):
        row = {"section": sec, "status": "renumbered", "year": p["year"],
               "targets": p["targets"], "source_phrase": p["form"]}
        if p["partial"]:
            row["partial"] = True
        rows.append(row)
    rows.sort(key=lambda r: (r["section"], r["status"]))

    return {
        "note": ("Mechanically mined from already-cached ORS chapter snapshot text (a "
                "section number immediately followed by a legislative-history bracket), for "
                "sections that are not already ingested documents. TWO DISPOSITIONS, and "
                "they mean different things: 'repealed' — the text is gone; 'renumbered' — "
                "the text still exists, at `targets`. A renumbered section reported as "
                "simply unresolved reads as a coverage gap in this corpus when it is a "
                "historical citation (issue #91). Every renumbering row carries the verbatim "
                "`source_phrase` it was read from, so any single row can be checked without "
                "re-running anything. Where a stub names two destinations both are recorded "
                "and neither is chosen; 'renumbered X and then Y' records Y, where the text "
                "actually ended up; 'renumbered X to Y' is a RANGE and is deliberately not "
                "recorded, because the section became a series rather than moving to two "
                "places. Repeal wins where a bracket says both. Not exhaustive — only "
                "chapters with a cached snapshot are scanned. Non-authoritative; verify "
                "against oregonlegislature.gov before relying on a disposition here."),
        "n_repealed": len(entries),
        "n_renumbered": len(renum),
        "n_renumbering_stubs_not_parsed": skipped,
        "sections": rows,
    }


def outputs():
    return {OUT: yaml.safe_dump(compute(), sort_keys=False, allow_unicode=True, width=100)}


def main():
    outs = outputs()
    if "--check" in sys.argv:
        stale = [p for p, t in outs.items() if not _tk_check_generated(p, t)[0]]
        if stale:
            print(f"{OUT.relative_to(REPO_ROOT)} is stale — run: "
                  "python3 src/build_ors_disposition.py")
            sys.exit(1)
        print("ors-disposition.yml is current.")
        return
    for p, t in outs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    d = compute()
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {d['n_repealed']} repealed, "
          f"{d['n_renumbered']} renumbered")
    # Named, not summarised away: these are stubs that DO record a disposition this file now
    # fails to carry. Reporting zero of them would read as full coverage.
    if d["n_renumbering_stubs_not_parsed"]:
        print(f"  {d['n_renumbering_stubs_not_parsed']} renumbering stub(s) left unparsed "
              f"(ranges — 'renumbered X to Y' means a series, not two destinations)")


if __name__ == "__main__":
    main()
