#!/usr/bin/env python3
"""Mine ORS repeal dispositions from already-cached chapter snapshots — pure mechanical
parsing of already-committed content, no new fetches, no fabrication.

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

SNAP = REPO_ROOT / "_meta/snapshots"
OUT = REPO_ROOT / "_meta/catalog/ors-disposition.yml"

# A bare repeal stub: a section number immediately followed by a legislative-history
# bracket whose text says it was repealed. Requires the number to NOT already have a real
# ingested document — a currently-live section's own history bracket can legitimately
# mention "repealed" in reference to an unrelated earlier subsection/session law, so we
# only trust this pattern when there's no actual document to contradict it.
REPEAL_RE = re.compile(r"\b(\d{2,3}[A-Z]?\.\d{3})\s*\[([^\]]*)\]")
REPEALED_BY_RE = re.compile(r"repealed\s+by\s+.*?\b(1[89]\d\d|20\d\d)\b", re.I)


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
    entries = {}
    for snap in sorted(SNAP.glob("ors-chapter-*.txt")):
        raw = snap.read_text(encoding="utf-8", errors="replace")
        entries.update(find_repeals(raw, existing_ids))
    rows = [{"section": sec, "status": "repealed", "year": year}
            for sec, year in sorted(entries.items())]
    return {
        "note": ("Mechanically mined from already-cached ORS chapter snapshot text "
                "(a section number immediately followed by a legislative-history bracket "
                "saying it was repealed, and not already an ingested document). Not "
                "exhaustive — only chapters with a cached snapshot are scanned, and a "
                "section repealed without an explicit 'repealed by YYYY' bracket phrase "
                "won't be caught. Non-authoritative; verify against "
                "oregonlegislature.gov before relying on a disposition here."),
        "n_repealed": len(rows),
        "sections": rows,
    }


def outputs():
    return {OUT: yaml.safe_dump(compute(), sort_keys=False, allow_unicode=True, width=100)}


def main():
    outs = outputs()
    if "--check" in sys.argv:
        stale = [p for p, t in outs.items() if not p.exists() or p.read_text() != t]
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
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {d['n_repealed']} repealed section(s) found")


if __name__ == "__main__":
    main()
