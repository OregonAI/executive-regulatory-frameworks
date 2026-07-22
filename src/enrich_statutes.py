#!/usr/bin/env python3
"""Enrich ORS statute frontmatter with the legislative-history years printed inside the
section's own verbatim text — pure mechanical parsing of already-committed content, no new
fetches, no fabrication (anything without a parseable history year is left null, not guessed).

  python3 src/enrich_statutes.py            # enrich every statutes/ors-*.md in place
  python3 src/enrich_statutes.py --check     # CI: fail if any statute's years drift
  python3 src/enrich_statutes.py ors-496.146 # one section (testing)

What gets filled, and from where (the section's verbatim text, before '## Provenance'):
  last_amended  <- MAX 4-digit year across the section's legislative-history notes, i.e. the
                   bracketed "[1967 c.624 §1; 2017 c.538 §5]" chapter-law citations and any
                   "Amended by YYYY" / "repealed by YYYY" prose. The most recent legislative
                   action on the section.
  enacted       <- MIN such year (original enactment / first codification).
Both are left null when the section carries no dated history (e.g. "[Formerly 91.505]" only,
or reserved/definitional sections). These are derived metadata, annotated as such — never a
substitute for the official history.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT, content_files, parse_frontmatter

YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")
BRACKET = re.compile(r"\[[^\]]*\]")
# a bracket group counts as legislative history if it names a chapter law or an action verb
HIST_MARK = re.compile(r"c\.\s*\d|Amended|Formerly|repealed|enacted|renumbered", re.I)
AMENDED_PROSE = re.compile(r"(?:Amended|Repealed|Added) by (?:.*?)(1[89]\d\d|20\d\d)")


def derive_years(body: str):
    """(enacted, last_amended) year ints from a section's history notes, or (None, None)."""
    text = body.split("## Provenance")[0]
    years = set()
    for br in BRACKET.findall(text):
        if HIST_MARK.search(br):
            years.update(int(y) for y in YEAR.findall(br))
    for m in AMENDED_PROSE.finditer(text):
        years.add(int(m.group(1)))
    if not years:
        return None, None
    return min(years), max(years)


def _fmt(v):
    return str(v) if v is not None else "null"


def apply(path: Path, enacted, last_amended) -> bool:
    """Insert/update `enacted` and `last_amended` in the frontmatter, anchored after
    `source_version:` (preserving all other formatting). Returns True if changed."""
    text = orig = path.read_text()
    for key, val in (("enacted", enacted), ("last_amended", last_amended)):
        line = f"{key}: {_fmt(val)}"
        if re.search(rf"^{key}:.*$", text, flags=re.M):
            text = re.sub(rf"^{key}:.*$", line, text, count=1, flags=re.M)
        else:
            text = re.sub(r"^(source_version:.*$)", r"\1\n" + line, text, count=1, flags=re.M)
    if text != orig:
        path.write_text(text)
        return True
    return False


def _cur(fm, key):
    v = fm.get(key)
    return int(v) if isinstance(v, int) else None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check = "--check" in sys.argv
    targets = [p for p in content_files()
               if p.stem.startswith("ors-") and (not args or p.stem in args)]

    changed = drift = 0
    for p in targets:
        fm, body = parse_frontmatter(p)
        enacted, last_amended = derive_years(body)
        if check:
            if _cur(fm, "enacted") != enacted or _cur(fm, "last_amended") != last_amended:
                print(f"DRIFT  {p.relative_to(REPO_ROOT)}: "
                      f"enacted {fm.get('enacted')}->{enacted} "
                      f"last_amended {fm.get('last_amended')}->{last_amended}")
                drift += 1
        elif apply(p, enacted, last_amended):
            changed += 1
    if check:
        if drift:
            print(f"FAILED: {drift} statute(s) drift from their own history notes — "
                  "run: python3 src/enrich_statutes.py")
            sys.exit(1)
        print(f"OK: {len(targets)} statute(s) match their own history notes.")
    else:
        dated = sum(1 for p in targets
                    if derive_years(parse_frontmatter(p)[1])[1] is not None)
        print(f"enriched {changed} of {len(targets)} statute file(s); "
              f"{dated:,} have a derivable last-amended year "
              f"({dated * 100 // max(len(targets), 1)}%)")


if __name__ == "__main__":
    main()
