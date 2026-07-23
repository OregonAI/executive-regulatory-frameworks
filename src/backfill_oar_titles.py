#!/usr/bin/env python3
"""One-off backfill for the OAR title-truncation bug fixed in ingest_oar.py: the old title
extraction guessed a prose boundary in the flattened rule text and stopped at the first
capitalized word — which, since OARD titles are Title Case, was almost always the SECOND
word of the title ("Approval and Execution of Financing Agreements" -> "Approval and").
Affected an estimated 89% of ingested OAR rules.

Re-derives every already-ingested rule's title from its own already-cached snapshot HTML
(_meta/snapshots/oar-*.html — reads OARD's own <strong>NUM</strong><br><strong>TITLE
</strong> markup via repo_lib.rule_title_from_html(), no network calls) and, where it
differs from the committed title, patches the `title:` frontmatter, the `# {title} (OAR
{rule})` heading, and the "At a glance" line in place. Everything else in each file (full
text, citations, dates, verified_by, etc.) is left untouched. A rule whose snapshot doesn't
match the expected markup (a small number of OARD disambiguation pages) is left alone rather
than guessed.

Frontmatter escapes a literal '"' in a title as "'" (see ingest_oar.py's doc_body), so the
frontmatter's title and the heading/"At a glance" lines' title text can literally differ
(e.g. title: "'Applicant' and 'Licensee' Defined" vs heading '# "Applicant" and "Licensee"
Defined'). Each of the three spots is read and patched independently by its own anchored
regex rather than assuming one shared string, so this stays correct either way.

  python3 src/backfill_oar_titles.py            # apply
  python3 src/backfill_oar_titles.py --check    # report only, no writes; exit 1 if any diff
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT, content_files, rule_title_from_html

FM_RE = re.compile(r'^title: "(.*)"\s*$', re.M)


def head_re(rule):
    return re.compile(r'^# (.*) \(OAR ' + re.escape(rule) + r'\)\s*$', re.M)


def glance_re(rule):
    return re.compile(r'^OAR ' + re.escape(rule) + r' — (.*)\. Chapter\b', re.M)


def patch_rule_file(path: Path, rule: str, new_title: str) -> int:
    """new_title is the raw (unescaped) title from rule_title_from_html; each of the 3
    spots is matched and replaced independently, escaping only for the frontmatter line."""
    text = path.read_text(encoding="utf-8")
    new_title_fm = new_title.replace('"', "'")
    n = 0
    m = FM_RE.search(text)
    if m and m.group(1) != new_title_fm:
        text = text[:m.start(1)] + new_title_fm + text[m.end(1):]
        n += 1
    hre = head_re(rule)
    m = hre.search(text)
    if m and m.group(1) != new_title:
        text = text[:m.start(1)] + new_title + text[m.end(1):]
        n += 1
    gre = glance_re(rule)
    m = gre.search(text)
    if m and m.group(1) != new_title:
        text = text[:m.start(1)] + new_title + text[m.end(1):]
        n += 1
    if n:
        path.write_text(text, encoding="utf-8")
    return n


def main():
    check = "--check" in sys.argv
    files = [p for p in content_files() if "rules" in p.parts and p.stem.startswith("oar-")]

    n_diff = n_patched = n_incomplete = n_no_snapshot = 0
    for p in files:
        rule = p.stem.replace("oar-", "")
        html_path = REPO_ROOT / "_meta/snapshots" / f"{p.stem}.html"
        if not html_path.exists():
            n_no_snapshot += 1
            continue
        raw = html_path.read_text(encoding="utf-8", errors="replace")
        new_title = rule_title_from_html(raw, rule)
        if not new_title:
            continue  # unrecognized page shape (e.g. a disambiguation page) — leave as-is
        text = p.read_text(encoding="utf-8")
        m = FM_RE.search(text)
        hm = head_re(rule).search(text)
        gm = glance_re(rule).search(text)
        new_title_fm = new_title.replace('"', "'")
        if ((not m or m.group(1) == new_title_fm)
                and (not hm or hm.group(1) == new_title)
                and (not gm or gm.group(1) == new_title)):
            continue
        n_diff += 1
        if check:
            print(f"DIFF  {p.relative_to(REPO_ROOT)}: {(m and m.group(1))!r} -> {new_title_fm!r}")
            continue
        n = patch_rule_file(p, rule, new_title)
        expected = sum([bool(m) and m.group(1) != new_title_fm,
                        bool(hm) and hm.group(1) != new_title,
                        bool(gm) and gm.group(1) != new_title])
        if n == expected:
            n_patched += 1
        else:
            n_incomplete += 1
            print(f"WARN  {p.relative_to(REPO_ROOT)}: only {n}/{expected} title spot(s) "
                  f"matched — left partially patched, check by hand")

    if check:
        if n_diff:
            print(f"FAILED: {n_diff} rule(s) would get a corrected title "
                  f"({n_no_snapshot} rule(s) have no cached snapshot to check) — run: "
                  "python3 src/backfill_oar_titles.py")
            sys.exit(1)
        print(f"OK: no title corrections pending ({n_no_snapshot} rule(s) had no snapshot).")
        return
    print(f"backfilled {n_patched} of {n_diff} rule title(s)"
          + (f" ({n_incomplete} incomplete, see WARN lines above)" if n_incomplete else "")
          + f"; {n_no_snapshot} rule(s) had no cached snapshot to check")


if __name__ == "__main__":
    main()
