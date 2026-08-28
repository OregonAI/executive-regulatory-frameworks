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


def _words(s: str) -> list:
    return re.findall(r"[a-z]+", s.lower())


def _catchline_words(slice_text: str, sec: str) -> list:
    body = slice_text[len(sec):len(sec) + 600]
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

    Comparison runs only through the SHORTER of the two word lists, because the
    catalog title is not always the clean catchline: `catalog_ors.py`'s TOC parser
    truncates a title at 160 characters (sometimes mid-word) and, on a measured 27 of
    37,534 currently-ingested sections, carries a stray trailing heading fragment or a
    small transcription slip the printed catchline does not (OregonAI/
    executive-regulatory-frameworks#286) -- always EXTRA or DIVERGENT words beyond
    where the two agree, never a missing or reordered one for a genuinely-anchored
    slice, which is what makes truncating the comparison to the shorter list sound
    rather than merely permissive. The one place a mismatch is tolerated at all is the
    final word compared, and only as a one-sided prefix (`recor` vs. `records`) -- the
    shape a 160-character cut produces, not a stand-in for a different word.
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
        if i == n - 1 and a and b and (a.startswith(b) or b.startswith(a)):
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
last_verified: "{TODAY}"
verified_by: "@morficflux"
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
            s["status"] = "not_sliceable"
            s["note"] = ("no section body found in the chapter text (likely renumbered/"
                         "repealed or a TOC cross-reference artifact); not ingested")
            s.pop("path", None)
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
            s["status"] = "not_sliceable"
            s["note"] = ("catalog title does not match this section's own printed "
                         "catchline at the anchor point; not ingested (verify the "
                         "catalog title against the source before re-running)")
            s.pop("path", None)
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


def _proof_the_one_shared_word_defect_is_refused(ck):
    """CRITERION 1 OF #201: "A slice whose only catchline overlap is one common word is
    refused — watched failing, with a real ORS section as the fixture rather than a
    synthetic one."

    The number and title are real, current catalog rows (`ors.yml`'s chapter 12,
    section 12.420, "Purpose"), and the wrong body is real ORS text too — the opening of
    12.020's own printed body, lifted verbatim from the committed chapter-12 snapshot —
    just paired with 12.420's number and title instead of its own, so a slice that
    physically began at the wrong place would look exactly like this: the right number,
    a sentence that is not this section's catchline, and the word "purpose" sitting in
    it anyway (not at the front — mid-sentence, the way #201 describes). The pre-fix
    `anchor_ok` admitted this (a bag-of-words check with `hits >= max(1, len(words)//2)`
    against a 1-word title needs exactly one hit, and "purpose" is in the first 160
    characters); this proof is what watching that fail looked like, quoted in the commit
    that lands alongside it."""
    sec, title = "12.420", "Purpose"
    wrong_slice = (sec + " Except as provided in subsection (2) of this section, for the "
                   "purpose of determining whether an action has been commenced within "
                   "the time limited, an action shall be deemed commenced as to each "
                   "defendant, when the complaint is filed, and the summons served on "
                   "the defendant, or on a codefendant who is a joint contractor.")
    ck("pre-fix bag-of-words logic WOULD admit this (documented, not exercised): a title "
       "word appearing anywhere in the opening text is enough",
       "purpose" in normalize_ws(wrong_slice[:160]).lower())
    ck("the real anchor_ok refuses it: 'purpose' is not where this section's own "
       "catchline is printed", not anchor_ok(wrong_slice, sec, title))


def _proof_real_anchors_still_pass(ck):
    """CRITERION 2 OF #201: currently-ingested, correctly-anchored sections must still
    pass. Runs the real slicer against committed chapter snapshots (no network) for a
    spread of real catalog rows, including 12.420's OWN real slice (the section the
    refusal proof above impersonates) and 1.860, whose catalog title carries the
    trailing-heading noise `catalog_ors.py`'s `TRAILING_HEADING_RE` only partly strips
    ("...justice courts COURTS") -- proving the fix tolerates that known, separate
    catalog defect rather than refusing a section over it."""
    cases = [
        ("ors-chapter-1", "1.001", "State policy for courts"),
        ("ors-chapter-1", "1.194", "Definitions for ORS 1.194 to 1.200"),
        ("ors-chapter-1", "1.860", "Reports relating to municipal courts and justice courts COURTS"),
        ("ors-chapter-12", "12.420", "Purpose"),
    ]
    for snap_id, sec, title in cases:
        raw_txt = (SNAPSHOT_DIR / f"{snap_id}.txt").read_text(encoding="utf-8", errors="replace")
        sl = snapshot_slice(f"ors-{sec.lower()}", snap_id, raw_txt)
        ck(f"{sec}: real slice found in {snap_id}", len(sl) > 0)
        ck(f"{sec}: real slice anchors against its own catalog title", anchor_ok(sl, sec, title))


def _proof_a_measured_residual_is_named_not_absorbed(ck):
    """CRITERION 4 (rule rationale) and the ticket's "measure before you tighten"
    instruction: a tightened rule that happens to swallow every pre-existing catalog
    defect would be indistinguishable from one that checks nothing. Measured against
    the full currently-ingested corpus (37,534 sections, `_meta/catalog/ors.yml` +
    every committed `_meta/snapshots/ors-chapter-*.txt`): 37,507 pass (99.93%); 27 do
    not, because their catalog `title` diverges from the section's own printed
    catchline by more than a trailing word or heading fragment -- filed as
    OregonAI/executive-regulatory-frameworks#286 rather than silently patched here.
    Re-running that full scan on every selftest would cost the better part of a minute
    for no new information (the 27 are a fixed, filed list), so this proof instead
    pins one of them -- 452.300, catalogued "VECTOR" against a real printed catchline
    of "Oregon Health Authority vector control program" -- as a fast regression check
    that the refusal for a genuinely bad title still fires, without re-deriving the
    other 26."""
    raw_txt = (SNAPSHOT_DIR / "ors-chapter-452.txt").read_text(encoding="utf-8", errors="replace")
    sl = snapshot_slice("ors-452.300", "ors-chapter-452", raw_txt)
    ck("452.300: real slice found", len(sl) > 0)
    ck("452.300: refused — catalog title 'VECTOR' is not this section's printed "
       "catchline (#286), and the fix must not paper over that with a looser match",
       not anchor_ok(sl, "452.300", "VECTOR"))


def _selftest() -> int:
    from repo_lib import Checks
    ck = Checks()
    _proof_the_one_shared_word_defect_is_refused(ck)
    _proof_real_anchors_still_pass(ck)
    _proof_a_measured_residual_is_named_not_absorbed(ck)
    return ck.report("ingest-ors selftest")


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    main()
