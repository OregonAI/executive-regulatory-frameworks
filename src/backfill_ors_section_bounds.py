#!/usr/bin/env python3
"""One-off backfill for the two snapshot_slice() boundaries fixed in repo_lib.py: a repealed or
renumbered section's bracket stub ('171.020 [Repealed by ...]') ends the section before it
(#446), and the chapter page's closing rule of underscores is not section text (#449).

Re-slices only the statutes that `check_ors_section_bounds.py` flags, with the fixed
snapshot_slice(), and replaces only the '## Full text' block, and only where the new text is
a STRICT PREFIX of the old one (the overrun trimmed, nothing else). A flagged document whose
new slice is not a prefix of its old text is printed and left alone; it needs a human look.
Title, frontmatter, ids and provenance are untouched. Reads cached
_meta/snapshots/ors-chapter-*.txt only: no network.

  python3 src/backfill_ors_section_bounds.py            # apply
  python3 src/backfill_ors_section_bounds.py --check    # report only; exit 1 if any would change
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from check_ors_section_bounds import FT_RE, findings  # noqa: E402
from ingest_lib import flow_to_lines  # noqa: E402
from repo_lib import REPO_ROOT, snapshot_slice  # noqa: E402

FT_BLOCK_RE = re.compile(r"(## Full text\n\n)(.*?)(\n\n## Provenance)", re.S)


NOTE_RE = re.compile(r"Note(?: \d)?: ")


def lost_notes(removed: str, others: dict) -> list:
    """Legislative Counsel 'Note:' texts inside `removed` that appear in no other document
    (`others` maps a name to its flattened text). Trimming a section whose overrun carries
    such a note would delete verbatim session-law text from the corpus, so the backfill
    refuses it. A note is identified by its first 70 characters."""
    flat = re.sub(r"\s+", " ", removed)
    out = []
    for m in NOTE_RE.finditer(flat):
        frag = flat[m.end():m.end() + 70]
        if not any(frag in t for t in others.values()):
            out.append(frag)
    return out


def _selftest():
    from repo_lib import Checks
    ck = Checks()
    others = {"ors-9.200": "9.200 Other. Note: Section 5, chapter 7, Oregon Laws 2020, provides: Keep this sentence in the corpus, it is long enough."}
    tail = ("9.150 [Repealed by 1991 c.2] Note: Section 5, chapter 7, Oregon Laws 2020, provides: "
            "Keep this sentence in the corpus, it is long enough. 9.160 [Repealed by 1991 c.3]")
    ck("a note found in another document may be trimmed", lost_notes(tail, others) == [])
    tail2 = "9.150 [Repealed by 1991 c.2] Note: Section 9, chapter 8, Oregon Laws 2021, provides: Lose."
    ck("a note found nowhere else is reported lost", len(lost_notes(tail2, others)) == 1)
    ck("a tail with no note loses nothing", lost_notes("9.150 [Repealed by 1991 c.2] ____", others) == [])
    ck("'Note 2:' is a note too", len(lost_notes("9.150 [x] Note 2: Section 9 unique words here.", {})) == 1)
    return ck.report("backfill-ors-section-bounds selftest")


def main():
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    check = "--check" in sys.argv
    paths = sorted((REPO_ROOT / "statutes").glob("ors-*.md"))
    ids = {p.stem[4:].upper() for p in paths}
    cache, changed, unsafe, unreadable, held = {}, 0, [], [], []
    flat_texts = {}
    for p in paths:
        text = p.read_text(encoding="utf-8")
        m = FT_BLOCK_RE.search(text)
        snap = re.search(r"snapshot_id: (ors-chapter-\S+)", text)
        if not m or not snap:
            unreadable.append(p.name)
            continue
        if not findings(p.stem, m.group(2), ids):
            continue
        sid = snap.group(1)
        if sid not in cache:
            f = REPO_ROOT / "_meta/snapshots" / f"{sid}.txt"
            cache[sid] = f.read_text(encoding="utf-8", errors="replace") if f.exists() else None
        if cache[sid] is None:
            unreadable.append(p.name)
            continue
        new_ft = flow_to_lines(snapshot_slice(p.stem, sid, cache[sid]))
        old_ft = m.group(2)
        if not new_ft or new_ft == old_ft or not old_ft.startswith(new_ft.rstrip()):
            unsafe.append(p.name)
            continue
        removed = old_ft[len(new_ft.rstrip()):]
        if NOTE_RE.search(removed):
            if not flat_texts:
                for q in paths:
                    mm = FT_BLOCK_RE.search(q.read_text(encoding="utf-8"))
                    if mm:
                        flat_texts[q.name] = re.sub(r"\s+", " ", mm.group(2))
            others = {k: v for k, v in flat_texts.items() if k != p.name}
            if lost_notes(removed, others):
                held.append(p.name)
                continue
        changed += 1
        if not check:
            p.write_text(text[:m.start(2)] + new_ft + text[m.end(2):], encoding="utf-8")
    for n in unsafe[:25]:
        print(f"SKIP  statutes/{n}: the new slice is not a strict prefix of the old text "
              "-- needs a human look")
    for n in held:
        print(f"HELD  statutes/{n}: the overrun carries a Legislative Counsel note found in no "
              "other document; trimming would delete it. Not changed.")
    for n in unreadable[:25]:
        print(f"UNREADABLE statutes/{n}: could not be re-sliced; not changed")
    print(("would change" if check else "patched") + f": {changed}; unsafe: {len(unsafe)}; "
          f"unreadable: {len(unreadable)}; held for notes: {len(held)}")
    if check and (changed or unsafe or unreadable or held):
        sys.exit(1)


if __name__ == "__main__":
    main()
