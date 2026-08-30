#!/usr/bin/env python3
"""Whole-chapter ORS ingestion pipeline (full-text-first, HC-1 safe).

  python3 src/ingest_ors.py 183 [184 ...]

Per chapter: fetch the chapter HTML -> snapshot ors-chapter-<ch>.html/.txt ->
for every section in _meta/catalog/ors.yml: slice its text via
repo_lib.snapshot_slice (the same function verify_provenance uses) and emit a
full-text document. Sections whose slice is missing/tiny or fails a
title-anchoring sanity check are SKIPPED and marked not_sliceable in the
catalog (renumbered/repealed/TOC-noise entries) — nothing is ever fabricated.
Also updates the catalog, the ors source group, statutes/_index.md, and prints
a terse per-chapter summary."""
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

import yaml

from html_to_text import html_to_text
from ingest_lib import fetch, flow_to_lines
from repo_lib import (REPO_ROOT, SNAPSHOT_DIR, content_hash, hash_snapshot,
                      normalize_ws, snapshot_slice, snapshot_text)

CATALOG = REPO_ROOT / "_meta/catalog/ors.yml"
GROUP = REPO_ROOT / "_meta/sources/ors.yml"
OUT = REPO_ROOT / "statutes"
TODAY = date.today().isoformat()
EDITION = "2025 Edition"

CHAPTER_TITLES = {}  # filled from catalog


# ORS itself delimits a section's catchline: every section is printed as
# "NUMBER CATCHLINE. body...", the catchline running from right after the number to the
# period that ends it (a closing quote may sit between the period and the following
# whitespace, e.g. `indorsement "not a true bill." (1) When...`).
_CATCHLINE_END_RE = re.compile(r"\.[”’\"']*(?:\s|$)")


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z]+", s.lower())


# Measured, not guessed: searching every currently-ingested section (37,534) for
# _CATCHLINE_END_RE's ending period past the section number, the longest real ORS
# catchline is 372 characters (656.245) and every single section finds its period within
# that -- none needed the search widened past 3000 characters to find one at all. 600 is
# that measured ceiling (372) plus a bit better than 1.6x headroom, not an arbitrary round
# number. If some future section's catchline still runs past this window,
# _CATCHLINE_END_RE finds no period inside it and _catchline_words silently falls back to
# treating the whole 600-character window as the catchline -- comparing the catalog title
# against catchline words plus a slice of body prose, which can only make anchor_ok MORE
# likely to refuse a genuine match (never less: extra body words can only break the
# position-by-position comparison, not manufacture a false agreement), so the failure
# mode this window's exhaustion produces is a false refusal caught by
# _proof_real_anchors_still_pass's spread of real rows, not a false admission.
_CATCHLINE_WINDOW = 600


def _catchline_words(slice_text: str, sec: str) -> list[str]:
    body = slice_text[len(sec):len(sec) + _CATCHLINE_WINDOW]
    m = _CATCHLINE_END_RE.search(body)
    return _words(body[:m.start()] if m else body)


def anchor_ok(slice_text: str, sec: str, title: str) -> bool:
    """Anchoring evidence: the slice must start with the section number, and the
    catalog title must agree, WORD FOR WORD IN ORDER FROM THE FRONT, with the text ORS
    itself prints as this section's own catchline -- not merely share a word with it
    (#201). A slice that begins with the wrong sentence is refused even when that
    sentence later happens to use one of the title's words, because this checks
    POSITION -- the one thing ORS's own convention (number, catchline, period, body)
    gives us to check against -- rather than vocabulary. A bag-of-words check has no
    such anchor: for a short catchline ("Purpose", "Definitions", "Scope") almost any
    single shared word clears it, which is the defect this replaces.

    A per-word mismatch is tolerated as a one-sided prefix at ANY position
    (`inspection` vs. `inspections`), not only the last -- a plural, or a truncated
    word, means the same thing wherever it falls in the catchline, and gating the
    tolerance to the final word only (an earlier version of this function did) refused
    correctly-anchored sections over nothing but that position, which is exactly the
    "silent gap" #201 itself warned a stricter rule must not trade a wrong answer for.
    Comparison then runs only through the SHORTER of the two word lists, because
    `catalog_ors.py`'s TOC parser truncates a title at 160 characters (sometimes
    mid-word), and a title cut short there must not be refused for lacking words the
    cut removed.

    Neither tolerance is a proof that every divergence beyond it is harmless --
    measured against every currently-ingested section (37,534, against the committed
    chapter snapshots), 21 titles diverged from their own printed catchline in ways
    this function still correctly refuses, catalogued in full at
    OregonAI/executive-regulatory-frameworks#286: a word missing from the catalog
    title that the printed catchline carries, words reordered, a catalog title itself
    shorter than the real catchline it truncated nothing from, and two `catalog_ors.py`
    parser bugs (a bare TOC heading fragment captured in place of the real catchline;
    an in-catchline "ORS N.NNN to N.NNN" cross-reference mistaken for a TOC-entry
    boundary, truncating the entry that names it). 18 of the 21 are now corrected by
    hand in `_meta/catalog/ors.yml` (`src/backfill_ors_286_titles.py`, run once) --
    verified against the section's own printed catchline exactly as this function
    checks it, not tuned away here. THREE are left AS-IS, all for the same reason: the
    catalog title is already correct and the printed SOURCE carries the defect --
    341.305's catalog title reads "tax levy" against the chapter-341 snapshot's own
    typo ("tex levy"); 315.123 and 470.540 read "recordkeeping"/"timetable" against a
    mid-word hyphen the source's own line-wrapped PDF-to-text extraction introduced
    ("record- keeping"/"time- table") where that same chapter's TOC prints the word
    cleanly. A fact about the source, never laundered into the catalog to make this
    check pass (CONTEXT.md's Access-failure/Upstream-drift split). A missing word, a
    reorder, or a genuinely different word at a shared position is never a one-sided
    prefix of the other, so none of these were ever let through by the tolerance
    above -- only inflection and truncation are.
    """
    if not slice_text.startswith(sec):
        return False
    title_words = _words(title)
    if not title_words:
        return False
    catchline_words = _catchline_words(slice_text, sec)
    n = min(len(title_words), len(catchline_words))
    if n == 0:
        return False
    for i in range(n):
        a, b = title_words[i], catchline_words[i]
        if a == b:
            continue
        if a and b and (a.startswith(b) or b.startswith(a)):
            continue
        return False
    return True


# LEGAL STATUS - NOT-A-RULE: an ORS section, not an OAR rule. ADR 0006 gives a RULE's legal
# status one writer, the Oregon Bulletin, which does not publish statutes -- a section's
# repeal is recorded in `_meta/catalog/ors-disposition.yml` from the chapter's own brackets.
# The `status: current` in the template below is this pipeline's, not that one's.
def doc_body(sec, title, ch, ch_title, snap_id, sha, url, slice_text):
    ft = flow_to_lines(slice_text)
    # The three platform fields must lead the frontmatter and match every other document in
    # the corpus; they were added by the multi-corpus work after this template was written,
    # so docs generated here silently lacked them.
    return f"""---
schema_version: 1
corpus: "executive-regulatory-frameworks"
jurisdiction: "oregon"
id: ors-{sec.lower()}
title: "{title.replace(chr(34), chr(39))}"
doc_type: statute
citation: "ORS {sec}"
authority_level: statute
issuing_body: "Oregon Legislative Assembly; published by the Legislative Counsel Committee"
agency: statewide
legal_authority: []
source_url: "{url}"
source_format: html
retrieved: "{TODAY}"
source_sha256: "{sha}"
snapshot_id: {snap_id}
effective_date: null
last_reviewed: null
source_version: "{EDITION}"
status: current
supersedes: null
content_mode: verbatim
conversion_notes: "sliced the section's text out of the shared chapter snapshot; line breaks inserted at subsection markers (whitespace-only)"
last_verified: ""
verified_by: ""
maintainer: "@morficflux"
relationships:
  implements: []
  implemented_by: []
  references_external: []
  related: []
  supersedes: []
tags: ["ors", "chapter-{ch.lower()}"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** The official ORS text is the printed
> published copy of the Oregon Revised Statutes. Verify against the official source:
> <{url}> (retrieved {TODAY}, {EDITION}).

# {title} (ORS {sec})

## At a glance

ORS {sec} — {title}. Chapter {ch} ({ch_title}), {EDITION}.

## Full text

{ft}

## Provenance & change history

- Source: <{url}> · retrieved {TODAY} · sha256 `{sha}`
  (chapter snapshot `_meta/snapshots/{snap_id}.html`)
- See [CHANGELOG](./CHANGELOG.md).
"""


def ingest_chapter(ch, cat_chapter):
    ch_l = ch.lower()
    snap_id = f"ors-chapter-{ch_l}"
    url = cat_chapter["url"]
    html_path = SNAPSHOT_DIR / f"{snap_id}.html"
    if not html_path.exists():
        raw = fetch(url)
        html_path.write_bytes(raw)
        (SNAPSHOT_DIR / f"{snap_id}.txt").write_text(snapshot_text(raw), encoding="utf-8")
    sha = hash_snapshot(snap_id, "html")
    raw_txt = (SNAPSHOT_DIR / f"{snap_id}.txt").read_text(encoding="utf-8", errors="replace")
    ch_title = cat_chapter["title"]

    def refuse(s, note):
        """The one shape a section takes when it is withheld rather than published:
        marked `not_sliceable`, its stale `path` dropped, and a note a human auditing
        the catalog can read. Both refusal sites below share this shape and must keep
        sharing it -- the reason the second exists at all is that its note stay
        distinguishable from the first's (#201)."""
        s["status"] = "not_sliceable"
        s["note"] = note
        s.pop("path", None)

    made = skipped = kept = 0
    for s in cat_chapter["sections"]:
        sec, title = s["number"], s["title"]
        doc_id = f"ors-{sec.lower()}"
        out = OUT / f"{doc_id}.md"
        if s.get("status") == "ingested" and out.exists():
            kept += 1
            continue
        sl = snapshot_slice(doc_id, snap_id, raw_txt)
        if len(sl) < 120:
            refuse(s, "no section body found in the chapter text (likely renumbered/"
                      "repealed or a TOC cross-reference artifact); not ingested")
            skipped += 1
            continue
        if not anchor_ok(sl, sec, title):
            # A body-length slice was found at the section number, but it does not
            # start with this section's own catchline (#201) -- distinct from the
            # "nothing there at all" case above, and reported as such rather than
            # folded into the same note, so a human auditing not_sliceable rows can
            # tell a renumbered/repealed section from a title that needs re-checking
            # against the source (see OregonAI/executive-regulatory-frameworks#286
            # for a catalog of the latter already found and not yet corrected).
            refuse(s, "catalog title does not match this section's own printed "
                      "catchline at the anchor point; not ingested (verify the "
                      "catalog title against the source before re-running)")
            skipped += 1
            continue
        out.write_text(doc_body(sec, title, ch, ch_title, snap_id, sha, url, sl))
        s["status"] = "ingested"
        s["path"] = f"statutes/{doc_id}.md"
        s.pop("note", None)
        made += 1
    return made, skipped, kept, sha, url


def main():
    chapters = sys.argv[1:]
    if not chapters:
        print("usage: ingest_ors.py <chapter> [<chapter> ...]")
        sys.exit(2)
    cat = yaml.safe_load(CATALOG.read_text())
    by_num = {c["chapter"]: c for c in cat["chapters"]}
    group = yaml.safe_load(GROUP.read_text())
    gsrc = {s["id"]: s for s in group["sources"]}

    for ch in chapters:
        if ch not in by_num:
            print(f"{ch}: not in catalog")
            continue
        made, skipped, kept, sha, url = ingest_chapter(ch, by_num[ch])
        print(f"chapter {ch}: made {made}, skipped(not_sliceable) {skipped}, kept {kept}")
        snap_id = f"ors-chapter-{ch.lower()}"
        gsrc[snap_id] = {"id": snap_id, "url": url, "sha256": sha,
                         "last_checked": TODAY,
                         "notes": f"ORS chapter {ch} ({by_num[ch]['title']}), {EDITION}"}

    group["sources"] = sorted(gsrc.values(), key=lambda s: s["id"])
    GROUP.write_text(yaml.safe_dump(group, sort_keys=False, allow_unicode=True, width=110))
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))

    # regenerate statutes/_index.md from the catalog
    lines = ["# Statutes (ORS) — index", "",
             "Oregon Revised Statutes for DAS/executive-branch administration, full text per",
             f"section, sliced from the Legislature's chapter HTML ({EDITION}).",
             "**Non-authoritative copies** — the official text is the printed published ORS.", "",
             "| Chapter | Title | Sections listed | Ingested |", "|---|---|---|---|"]
    tot = [0, 0]
    for c in cat["chapters"]:
        n = len(c["sections"])
        i = sum(1 for s in c["sections"] if s.get("status") == "ingested")
        tot[0] += n; tot[1] += i
        lines.append(f"| {c['chapter']} | {c['title']} | {n} | {i} |")
    lines += [f"| **all** | | **{tot[0]}** | **{tot[1]}** |", "",
              "Per-section numbers/titles/paths: [`_meta/catalog/ors.yml`](../_meta/catalog/ors.yml).",
              "Sections marked `not_sliceable` there have no body text in the chapter HTML",
              "(renumbered/repealed or catalog noise) and are intentionally not ingested.", ""]
    (OUT / "_index.md").write_text("\n".join(lines))


def _catalog_titles() -> dict[str, str]:
    """{section: title}, read straight from `_meta/catalog/ors.yml` -- the file
    `ingest_chapter` itself reads. The proofs below look a title up here rather than
    hand-typing it, so each one asserts about the row the corpus actually contains: a
    hand-typed stand-in can drift from the catalog (1.194's title was typed here once as
    "Definitions for ORS 1.194 to 1.200"; the catalog has held "Definitions for ORS"
    since before this fix, found in review of this ticket's own commit) or freeze a
    known-bad row's title as a literal, which keeps a residual-defect check green forever
    even after the row is corrected -- see _proof_a_measured_residual_is_named_not_absorbed."""
    cat = yaml.safe_load(CATALOG.read_text())
    return {s["number"]: s["title"] for c in cat["chapters"] for s in c["sections"]}


def _pre_fix_anchor_ok(slice_text: str, sec: str, title: str) -> bool:
    """A kept, unmodified copy of `anchor_ok` as it stood before #201: a bag-of-words
    check requiring the slice to start with the section number and share ONE word (4+
    letters, up to six considered) with the catalog title, admitted at
    `hits >= max(1, len(words) // 2)`, searched anywhere in the slice's first 160
    characters. Never called by `ingest_chapter` -- kept only so
    `_proof_the_one_shared_word_defect_is_refused` exercises the actual defective logic
    the ticket describes, rather than a string-containment check on a literal that
    touches no function and cannot fail by construction (the defect this replaces,
    found in review of this ticket's own first attempt at this proof)."""
    if not slice_text.startswith(sec):
        return False
    head = normalize_ws(slice_text[:160]).lower()
    words = [w for w in re.findall(r"[a-z]{4,}", title.lower())][:6]
    if not words:
        return True
    hits = sum(1 for w in words if w in head)
    return hits >= max(1, len(words) // 2)


def _proof_the_one_shared_word_defect_is_refused(ck):
    """CRITERION 1 OF #201: "A slice whose only catchline overlap is one common word is
    refused — watched failing, with a real ORS section as the fixture rather than a
    synthetic one."

    The number and title are real, current catalog rows (`ors.yml`'s chapter 12,
    section 12.420, "Purpose", read via `_catalog_titles()`), and the wrong body is
    12.020's own real printed text, read at runtime from the committed chapter-12
    snapshot with `snapshot_slice` -- the same function the pipeline itself calls, not a
    hand-typed approximation of it -- with only its leading section number swapped for
    12.420's. That is the shape a genuine mis-anchor actually takes: the right number,
    followed by a different section's real catchline and body, which happens to use the
    word "purpose" too (12.020's own sentence: "...for the purpose of determining
    whether an action has been commenced..." -- not at the front, mid-sentence, the way
    #201 describes).

    The red half calls `_pre_fix_anchor_ok`, above -- a kept copy of the actual reverted
    logic -- against this fixture and asserts it WOULD admit it, so this half is
    demonstrated against real code that can fail (reverting `anchor_ok`'s body to
    `_pre_fix_anchor_ok`'s makes the SECOND check below fail for real; this was watched
    directly, not inferred). The green half asserts the real, current `anchor_ok`
    refuses it."""
    titles = _catalog_titles()
    sec, title = "12.420", titles["12.420"]
    raw_txt = (SNAPSHOT_DIR / "ors-chapter-12.txt").read_text(encoding="utf-8", errors="replace")
    real_12_020 = snapshot_slice("ors-12.020", "ors-chapter-12", raw_txt)
    wrong_slice = sec + real_12_020[len("12.020"):]
    ck("pre-fix anchor_ok (kept copy of the reverted logic) WOULD admit this: a title "
       "word appearing anywhere in the slice's opening 160 characters was enough",
       _pre_fix_anchor_ok(wrong_slice, sec, title))
    ck("the real anchor_ok refuses it: 'purpose' is not where this section's own "
       "catchline is printed", not anchor_ok(wrong_slice, sec, title))


def _proof_real_anchors_still_pass(ck):
    """CRITERION 2 OF #201: currently-ingested, correctly-anchored sections must still
    pass. Runs the real slicer against committed chapter snapshots (no network) for a
    spread of real catalog rows (titles read via `_catalog_titles()`, not hand-typed),
    including 12.420's OWN real slice (the section the refusal proof above impersonates)
    and 1.860, whose catalog title carries the trailing-heading noise
    `catalog_ors.py`'s `TRAILING_HEADING_RE` only partly strips ("...justice courts
    COURTS") -- proving the fix tolerates that known, separate catalog defect rather
    than refusing a section over it."""
    titles = _catalog_titles()
    cases = [
        ("ors-chapter-1", "1.001"),
        ("ors-chapter-1", "1.194"),
        ("ors-chapter-1", "1.860"),
        ("ors-chapter-12", "12.420"),
    ]
    for snap_id, sec in cases:
        title = titles[sec]
        raw_txt = (SNAPSHOT_DIR / f"{snap_id}.txt").read_text(encoding="utf-8", errors="replace")
        sl = snapshot_slice(f"ors-{sec.lower()}", snap_id, raw_txt)
        ck(f"{sec}: real slice found in {snap_id}", len(sl) > 0)
        ck(f"{sec}: real slice anchors against its own catalog title ({title!r})",
           anchor_ok(sl, sec, title))


def _proof_a_measured_residual_is_named_not_absorbed(ck):
    """CRITERION 4 (rule rationale) and the ticket's "measure before you tighten"
    instruction: a tightened rule that happens to swallow every pre-existing catalog
    defect would be indistinguishable from one that checks nothing. Measured against
    the full currently-ingested corpus (37,534 sections, `_meta/catalog/ors.yml` +
    every committed `_meta/snapshots/ors-chapter-*.txt`): 37,510 pass (99.94%); 3 have
    no section-length slice at all and never reach `anchor_ok`; 21 titles diverged from
    the section's own printed catchline by more than this function's inflection/
    truncation tolerance -- filed as OregonAI/executive-regulatory-frameworks#286
    rather than silently patched here (6 of #286's original 27 -- 137.593, 197A.302,
    249.850, 480.560, 673.370, 708A.475 -- turn out to be nothing but a plural or
    similar inflection at a non-final word, and now pass under this function's
    any-position prefix tolerance rather than sit in that list marked correctly-
    anchored-but-refused). 18 of the remaining 21 are now hand-corrected
    (`src/backfill_ors_286_titles.py`); THREE -- 341.305, 315.123, 470.540 -- are
    deliberately left diverging, all for the same reason: the catalog title is already
    right and the printed SOURCE carries the defect (341.305: a typo, "tex levy" for
    "tax levy"; 315.123/470.540: a mid-word hyphen from the source's own line-wrapped
    PDF-to-text extraction, "record- keeping"/"time- table" where the chapter's own TOC
    prints "recordkeeping"/"timetable" cleanly), so correcting the CATALOG to match
    would mean writing the source's own error into a curated field, the opposite of
    what this function exists to catch. An earlier version of the 315.123/470.540
    backfill got this backwards -- writing the hyphenated artifact INTO the catalog and
    the ingested files -- caught in code review and reverted before landing, on exactly
    the reasoning #286's own follow-up comment already applied to 341.305. Re-running
    that full scan on every selftest would cost the better part of a minute for no new
    information (the residual is now a fixed, permanent list of exactly these three
    rows), so this proof instead pins all three as a fast regression check that the
    refusal for a genuinely-diverging title still fires, for both of the two distinct
    reasons a printed source can diverge from a correct catalog.

    Every title is read from `_catalog_titles()`, not pinned as a string literal: this
    proof starts failing the moment either side of any comparison changes (a catalog
    title drifting, or oregonlegislature.gov correcting its own upstream defect), which
    is the signal a human should re-examine these pins rather than a silent stale
    pass."""
    titles = _catalog_titles()
    cases = [
        ("341", "341.305", "a typo -- 'tex levy' for 'tax levy'"),
        ("315", "315.123", "a line-wrap hyphenation artifact -- 'record- keeping' where "
                            "the chapter's own TOC prints 'recordkeeping'"),
        ("470", "470.540", "a line-wrap hyphenation artifact -- 'time- table' where the "
                            "chapter's own TOC prints 'timetable'"),
    ]
    for ch, sec, why in cases:
        raw_txt = (SNAPSHOT_DIR / f"ors-chapter-{ch}.txt").read_text(encoding="utf-8",
                                                                       errors="replace")
        sl = snapshot_slice(f"ors-{sec}", f"ors-chapter-{ch}", raw_txt)
        ck(f"{sec}: real slice found", len(sl) > 0)
        ck(f"{sec}: refused — catalog title {titles[sec]!r} does not word-for-word match "
           f"this section's own printed catchline (#286: the PRINTED SOURCE carries "
           f"{why} -- the catalog is right and must not be changed to match it)",
           not anchor_ok(sl, sec, titles[sec]))


def _proof_a_refusal_never_publishes_through_the_real_consumer(ck):
    """CRITERION 3 OF #201: "A refusal is recorded as unsliceable and reported, never
    published." The proofs above test `anchor_ok` directly; `ingest_chapter` is its
    only caller (`grep -rn anchor_ok src/` confirms), but a False verdict only means
    what #201 requires if the wiring around it actually withholds the document -- so
    this proof calls `ingest_chapter` itself, the real consumer, rather than trust that
    by reading the code alone.

    Real chapter (12, already-committed snapshot, no network) and a real section number
    (12.420) paired with a title ("VECTOR") anchor_ok is known to refuse, in a synthetic
    `cat_chapter` dict of one section so this doesn't attempt every real row in the
    chapter. `OUT` is monkeypatched to a throwaway temp directory for the call and
    restored after, so a refusal that (contrary to what this proof checks) DID write a
    file would land there and never touch the real `statutes/` tree."""
    tmpdir = Path(tempfile.mkdtemp(prefix="ingest-ors-selftest-"))
    orig_out = globals()["OUT"]
    globals()["OUT"] = tmpdir
    try:
        cat_chapter = {
            "url": "https://www.oregonlegislature.gov/bills_laws/ors/ors012.html",
            "title": "Limitations",
            "sections": [{"number": "12.420", "title": "VECTOR", "status": "not_ingested"}],
        }
        made, skipped, kept, sha, url = ingest_chapter("12", cat_chapter)
        s = cat_chapter["sections"][0]
        ck("ingest_chapter reports the refusal in its own tally (made=0, skipped=1)",
           made == 0 and skipped == 1)
        ck("the catalog row is marked not_sliceable, not left as-is or as ingested",
           s.get("status") == "not_sliceable")
        ck("the refusal note names the anchor mismatch, not the separate no-body-found "
           "reason", "catchline" in s.get("note", ""))
        ck("no path is recorded on the refused row", "path" not in s)
        ck("no document file was written for the refused section",
           not (tmpdir / "ors-12.420.md").exists() and not any(tmpdir.iterdir()))
    finally:
        globals()["OUT"] = orig_out


def _selftest() -> int:
    from repo_lib import Checks
    ck = Checks()
    _proof_the_one_shared_word_defect_is_refused(ck)
    _proof_real_anchors_still_pass(ck)
    _proof_a_measured_residual_is_named_not_absorbed(ck)
    _proof_a_refusal_never_publishes_through_the_real_consumer(ck)
    return ck.report("ingest-ors selftest")


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    main()
