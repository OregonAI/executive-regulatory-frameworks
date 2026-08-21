# Changelog — Oregon Constitution

All notable changes to the curated copies in this directory. Format based on
[Keep a Changelog](https://keepachangelog.com/); change types: Added, Source-Updated,
Superseded, Repealed, Removed, Verified, Fixed, Security. This repo is non-authoritative;
dates below are repo-curation dates, not official effective dates (those live in each
file's frontmatter).

## [Unreleased]

### Added

- **The whole document (#195).** Every article the source page prints, **339 of the 371
  distinct section numbers** it carries, full text per section. The catalog is derived from
  the page's own headings — 40 article headings under 39 distinct designations — and is the
  list of what SHOULD exist, so a section missing from this directory is detectable against
  it rather than merely absent. Verified-by @morficflux (machine verification; human review
  pending).
- **An article's identity carries its parenthetical.** The page prints ARTICLE VII twice,
  as `(Amended)` and `(Original)`; both are operative, both are cited by Oregon courts, and
  they are now two documents — `orconst-art-vii-amended-sec-1` and
  `orconst-art-vii-original-sec-1`. `Or. Const. Art. VII, sec. 1` resolves to NEITHER and
  says which two it could have meant. `XI-F(1)`/`XI-F(2)` and `XI-I(1)`/`XI-I(2)` are
  distinct designations (`xi-f-1`, `xi-i-2`), not duplicates. **Article VI's ten documents
  are unchanged** — an article with no parenthetical keeps the slug it already had.

### Fixed

Five defects that Article VI alone could not show, each found by measuring the whole page:

- **Article XI section 11L was invisible.** It is the only section in the document whose
  number carries an uppercase letter, and every regex in the pipeline read `\d+[a-z]?`. It
  was not a section that failed a rule and was reported — it was a section nothing could
  see.
- **A section number is not always one section.** Nine numbers across seven articles are
  printed more than once (19 prints), the operative print FIRST in Article IV and LAST in
  Articles XI, XIV and XV. The slicer now takes the print carrying text, and refuses when
  more than one does. Article XIV section 1 — the seat of government — was the case that
  showed it.
- **A 120-character floor copied from the ORS ingest refused four real sections**, three of
  them in the Bill of Rights: Article II section 1 ("All elections shall be free and
  equal."), Article I sections 17 and 30, Article V section 10. The floor is now measured in
  the section's own text, in a gap the document itself supplies: 40 prints carry zero, the
  next carries 31.
- **A Legislative Counsel note is not a section's text.** Counted as body text it published
  four repealed sections (Art. I sec. 36, Art. IV sec. 1a, Art. VIII sec. 6, Art. XI sec.
  11f) whose "full text" was a leadline, a repeal bracket and an editorial note.
- **Two parsing traps put page furniture into metadata**: Article V section 15 is a heading
  and a bracket with no leadline, and four articles print a `Note:` between the contents
  list and the first section, which ran onto the last listed section's title.

### Not published, with the reason recorded

- **32 sections** the page prints carry no text to mirror: it prints them as a leadline and
  a legislative-history bracket and nothing between them. Each is in
  [`_meta/catalog/constitution.yml`](../_meta/catalog/constitution.yml) with that reason
  beside it, and a citation to one of them resolves to nothing **and says why**.
- **3 article headings**: the repealed ARTICLE XI-A (RURAL CREDITS, 1916, repealed 1942 —
  the page prints the designation twice and this is the print with no sections), ARTICLE
  XI-B and ARTICLE XI-C. Catalogued and skipped with their reason, as Article VI section 9a
  was, so their absence is a stated finding rather than a gap.

## [2026-08-21]

### Added

- **Article VI (Administrative Department), 10 of the 11 sections the source page prints**,
  full text per section, via the new `src/ingest_constitution.py` — the first article
  mirrored under ADR 0005 (#194). Section 9a is cataloged and NOT published: the page
  prints its leadline and its legislative-history bracket and no text between them (it was
  repealed in 1958), so there is no text to mirror. The reason is recorded beside it in
  [`_meta/catalog/constitution.yml`](../_meta/catalog/constitution.yml).
  Verified-by @morficflux (machine verification; human review pending).
- The other 17 articles are **not** mirrored (#195). A citation into one of them resolves
  to nothing and says it is not mirrored — which is not a statement that the section does
  not exist.
