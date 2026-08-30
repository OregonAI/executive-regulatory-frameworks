#!/usr/bin/env python3
"""Oregon Constitution ingestion — one article at a time (ADR 0005, #194).

  python3 src/ingest_constitution.py --catalog            # the whole document, from the page
  python3 src/ingest_constitution.py --ingest             # publish every article
  python3 src/ingest_constitution.py --ingest "VII (Amended)"   # or just one
  python3 src/ingest_constitution.py --check              # catalog against constitution/
  python3 src/ingest_constitution.py --drift PAGE         # WHICH sections moved on PAGE
  python3 src/ingest_constitution.py --selftest           # every skip rule, failing

THE SOURCE IS ONE PAGE. The Constitution is published at oregonlegislature.gov as a
SINGLE HTML page carrying all 18 articles, so this is one source entry, one URL, one
sha256 and one snapshot (`oregon-constitution`) — against ors.yml's 545 chapter sources.
Everything else is slicing, and the slicing is `repo_lib.snapshot_slice`: the same
function `corpus-verify-provenance` calls through the `snapshot_slice_module` plugin, so
what was ingested and what is verified cannot diverge.

ONE PAGE MEANS ONE HASH, and that is what `--drift` is for (#197). The group's upstream
signal is a single sha256 over the whole document, so an amendment anywhere moves it and the
signal says that SOMETHING changed and never what. `--drift` is the diff that does that work:
it names the sections whose text moved, stays silent about the ones that did not, and refuses
to call a section it could not slice a section that was deleted.

Shaped after src/ingest_ors.py, which does the same thing per ORS chapter."""
import argparse
import re
import sys
from collections import Counter, namedtuple
from datetime import date
from pathlib import Path

import yaml

from html_to_text import html_to_text
from ingest_lib import fetch, flow_to_lines, output_dir_for
from repo_lib import (CONST_SECTION_MIN_BODY_CHARS, ORCONST_ID_RE,
                      ORCONST_SECTION_TOKEN, REPO_ROOT, SNAPSHOT_DIR,
                      Checks, constitution_article_headings, constitution_article_region,
                      constitution_section_anchor, constitution_section_body_chars,
                      constitution_section_prints, constitution_section_prints_in,
                      constitution_section_slice, hash_snapshot, normalize_ws,
                      operative_print,
                      orconst_article_designation, orconst_article_slug, orconst_id,
                      normalized_text_hash,
                      snapshot_slice, ws_only)

URL = "https://www.oregonlegislature.gov/bills_laws/Pages/OrConst.aspx"
SNAP_ID = "oregon-constitution"
CATALOG = REPO_ROOT / "_meta/catalog/constitution.yml"
GROUP = REPO_ROOT / "_meta/sources/constitution.yml"
DOC_TYPE = "constitutional_provision"
# Not a hand-typed path: `output_dir_for` derives it from repo_lib.DIR_DOC_TYPE, the same
# table validate-frontmatter's directory-routing check reads (AGENTS.md, "Directory routing
# (CI-enforced)"), so this pipeline is correct by construction rather than by being caught.
OUT = output_dir_for(DOC_TYPE)
TODAY = date.today().isoformat()

# The zero-width spaces the page carries (U+200B, ~50 of them) survive `ws_only`, which
# collapses `\s` runs and deliberately leaves punctuation alone because the SLICE it produces
# has to be the source's bytes. A TITLE is not the slice — it is the leadline Legislative
# Counsel supplies, written into frontmatter and into a heading — so an invisible character
# there is a defect in a metadata field rather than fidelity to the text. Stripped here, and
# nowhere near the text.
_ZERO_WIDTH = "\u200b\ufeff"


def _title_text(raw: str) -> str:
    return raw.translate({ord(c): None for c in _ZERO_WIDTH}).strip()


def contents_list(region: str) -> dict:
    """{number: title} from the article's own contents list — the `Sec. 1. …` block the
    page prints under each article heading, before the first section body.

    It is NOT the section list (see discover_sections): repealed sections are dropped
    from it, and its wording drifts from the body's own leadline — Article VI's section 9
    is listed as "Vacancies OF county…" and printed as "Vacancies IN county…". Both facts
    are why it is used for titles and never for membership.

    THE LIST ENDS AT `Note:` WHERE THERE IS ONE, and this is not a tidy-up. The page puts a
    Legislative Counsel note between the contents list and the first section in four
    articles — "Note: Article XI-M was designated as 'Article XI-L' by S.J.R. 21, 2001, and
    adopted by the people Nov. 5, 2002." Without the cut, the note ran onto the LAST
    entry's title and its trailing year was parsed as a section number: XI-M's section 5
    would have been published under the title "Relationship to conflicting provisions of
    Constitution Note: Article XI-M was designated as …", which is not a title the source
    gives it. Article VI has no such note, which is why #194 did not meet this."""
    body = re.search(rf"Section {ORCONST_SECTION_TOKEN}\. ", region)
    chunk = region[:body.start()] if body else region
    note = re.search(r"\bNote: ", chunk)
    if note:
        chunk = chunk[:note.start()]
    sec = re.search(r"\bSec\.\s+", chunk)
    if not sec:
        return {}
    return {m.group(1): _title_text(m.group(2))
            for m in re.finditer(rf"({ORCONST_SECTION_TOKEN})\.\s+"
                                 rf"(.*?)(?=\s+{ORCONST_SECTION_TOKEN}\.\s|\s*$)",
                                 chunk[sec.end():])}


def leadline(slice_text: str, number: str) -> str:
    """A section's own leadline, read off the front of its text: everything between
    `Section 9a. ` and the punctuation that closes it.

    Both terminators are real in Article VI — section 6 reads "County Officers:" where
    every other section ends its leadline with a period. Legislative Counsel supplies the
    leadlines ("Unless otherwise specifically noted, the leadlines for the sections have
    been supplied by Legislative Counsel"), which is why the contents list is preferred
    where it has one: neither is the constitutional text itself."""
    m = re.match(constitution_section_anchor(number).replace(r"\. ", r"\.\s+")
                 + r"(.*?)[.:](?:\s|$)", slice_text)
    return _title_text(m.group(1)) if m else ""


# ------------------------------------------------------------------- what the page prints
#
# TWO DENOMINATORS, BOTH READ OFF THE SOURCE. `discover_articles` takes every ARTICLE
# heading the page prints and `discover_sections` takes every `Section N.` heading inside
# one of them — never the article's own contents list, and never the set of articles the
# corpus happens to cite. ADR 0005 counted 43 cited targets in the `Article X, section Y`
# form; building the catalog from those would mirror only what was already noticed, and
# leave a section nobody looked at indistinguishable from one Oregon does not have.


def discover_sections(region: str) -> list:
    """Every section ONE ARTICLE'S BODY PRINTS, by number, in the order it prints them.

    The body is the denominator, not the contents list: Article VI's section 9a is
    repealed, so the list omits it while the page still prints its leadline and the
    measures that created and repealed it. A catalog built from the list would make a
    section nobody has looked at look like a section the source does not carry, which is
    the one thing this repo's catalogs may not do.

    ONE ENTRY PER NUMBER, not per print. Nine numbers across seven articles are printed more
    than once on the 2024 edition, always as the section in force beside a superseded print
    of it, and a citation names the number — so `prints` records the doubling on the one
    entry rather than making a consumer reconcile two rows for one citable section."""
    listed = contents_list(region)
    out, seen = [], {}
    for m in re.finditer(rf"Section ({ORCONST_SECTION_TOKEN})\. ", region):
        number = m.group(1)
        if number in seen:
            seen[number]["prints"] = seen[number].get("prints", 1) + 1
            continue
        title = listed.get(number)
        seen[number] = {"number": number,
                        "title": title or _printed_title(region, number),
                        "title_source": "contents-list" if title else "leadline"}
        out.append(seen[number])
    return out


def _printed_title(region: str, number: str) -> str:
    """The leadline of the print a citation to this number names — for the numbers the
    article's contents list does not carry, which is where the body's own leadline is the
    only title there is.

    THE PRINT THAT WILL BE SLICED, not the first one printed, and `repo_lib.operative_print`
    is what decides — the same function the slicer reaches from a doc id. Article I prints
    section 36 twice with different leadlines ("Liquor prohibition" and "Capital punishment
    abolished"), so taking the first print's leadline beside whichever print carries text
    makes `anchored()` compare two different sections and refuse a slice as unidentifiable:
    a document reported as one this ingest could not place, on a page that places it fine."""
    return leadline(operative_print(constitution_section_prints_in(region, number), number),
                    number)


# ONE ARTICLE THIS INGEST WILL NOT MIRROR, in the same shape as a skipped section: which
# rule refused it, and the sentence written into the catalog beside it.
_ARTICLE_SKIP_REASONS = {
    "no-sections": "the page prints no 'Section N.' heading between this article's heading "
                   "and the next — what it prints is the heading, the article's title and a "
                   "legislative-history bracket, which is the shape of a repealed article — "
                   "so there is no text to mirror and nothing is ingested",
}


def discover_articles(norm_text: str) -> list:
    """Every ARTICLE heading the page prints, with the sections under it.

    THE PARENTHETICAL IS PART OF THE ARTICLE'S IDENTITY: `VII (Amended)` and `VII
    (Original)` are two entries, two ids and two documents, because Oregon cites them that
    way and both are operative.

    A DESIGNATION PRINTED TWICE IS TWO ENTRIES AND ONE IDENTITY. `ARTICLE XI-A` is printed
    as the 1916 RURAL CREDITS article, repealed in 1942 and kept on the page as its heading
    and its repeal bracket, and again as the article in force. Both are catalogued;
    `occurrence` says which print each entry is; the repealed one is SKIPPED WITH ITS REASON
    rather than dropped, so that a reader who looks for it finds the finding instead of a
    gap. (`XI-B` and `XI-C` are the same shape without the doubling — repealed articles the
    page still prints, and the only articles of the 39 with no living designation at all.)"""
    heads = constitution_article_headings(norm_text)
    printings = Counter(h.designation for h in heads)
    out = []
    for h in heads:
        entry = {"article": h.designation}
        if printings[h.designation] > 1:
            entry["occurrence"] = h.occurrence
        entry["title"] = article_title(h.text, h.designation)
        entry["sections"] = discover_sections(h.text)
        if not entry["sections"]:
            entry["status"] = "not_mirrored"
            entry["rule"] = "no-sections"
            note = _ARTICLE_SKIP_REASONS["no-sections"]
            if printings[h.designation] > 1:
                note += (f". The page prints ARTICLE {h.designation} "
                         f"{_times(printings[h.designation])}; this is print "
                         f"{h.occurrence + 1}, and a citation to Art. {h.designation} "
                         f"resolves against the print that carries sections")
            entry["note"] = note
        out.append(entry)
    return out


def _times(n: int) -> str:
    """`2` -> "twice" — the word the page's own shape deserves in a reason a human reads."""
    return {1: "once", 2: "twice", 3: "three times"}.get(n, f"{n} times")


# ONE SECTION THIS INGEST WILL NOT PUBLISH: which section, which rule refused it, and the
# sentence written into the catalog. A type rather than a formatted string, so the proofs
# below assert on the RULE that fired instead of pattern-matching prose (check_updates.py's
# Failure, catalog_agencies.py's, same reason).
Skip = namedtuple("Skip", "number rule reason")

# WHERE THE TEXT CAME FROM AND WHEN — the four facts every document's provenance block
# repeats, which travelled as four positional arguments through two functions before this
# type existed. They are one fact about one fetch of one page, and they are written into
# `source_url`, `source_sha256`, `source_version` and `retrieved` together or not at all.
Provenance = namedtuple("Provenance", "url sha256 source_version retrieved")

# WHAT A REASON MAY NOT SAY. Every sentence here is about the SLICE or about what the page
# PRINTS — never about whether the section exists. A section this ingest could not slice is
# not a section Oregon does not have, and a catalog that blurs the two answers a question
# nobody asked it (CONTEXT.md).
_SKIP_REASONS = {
    "no-body": "the page prints no 'Section {number}.' heading inside this article; not "
               "ingested",
    "too-short": "the page prints {length} character(s) of this section's own text — "
                 "outside its leadline, its legislative-history brackets and the notes "
                 "printed after it — under the {min} this ingest will publish, so the slice "
                 "is not known to be the section's text; not ingested",
    "mis-anchored": "the slice does not begin with 'Section {number}.' or shares no "
                    "wording with the title the page lists for it, so it is not known to "
                    "be this section's text; not ingested",
    "history-only": "the page prints this section's leadline and its legislative history "
                    "bracket and no text between them (the shape of a repealed section); "
                    "there is no text to mirror, so it is not ingested",
    "ambiguous-print": "the page prints this section number {prints} times inside this "
                       "article and {prints_with_text} of those prints carry text, so "
                       "nothing in the citation says which one it names; not ingested",
}


def anchored(slice_text: str, number: str, title: str) -> bool:
    """Is this slice known to be section `number`'s text?

    Two independent readings must agree: the LEADLINE the section prints at its own head,
    and the title the article's contents list prints for that number. Half of the title's
    first six long words, ROUNDED UP, is the tolerance — enough for section 9, which the
    contents list calls "Vacancies OF county…" and the body prints as "Vacancies IN
    county…", and not enough for a slice that merely mentions a word the title also uses.

    BOTH HALVES WERE MEASURED AGAINST A FAILING CASE, and ingest_ors.py's version passes
    it: comparing the first 200 characters (rather than the leadline) at half rounded DOWN
    admits a slice about the Governor nominating judges under the title "Duties of
    Secretary of State", because a three-word title needs one hit and "state" appears in
    almost every sentence of this document. Filed against the ORS ingest as #201, with that
    measurement in it; not fixed here."""
    if not slice_text.startswith(f"Section {number}."):
        return False
    head = normalize_ws(leadline(slice_text, number)).lower()
    words = re.findall(r"[a-z]{4,}", title.lower())[:6]
    if not words:
        return True
    return sum(1 for w in words if w in head) >= max(1, (len(words) + 1) // 2)


def why_not_publishable(slice_text: str, number: str, title: str,
                        prints: int = 1, prints_with_text: int = 1):
    """The rule that refuses to publish this slice, or None if every rule passed.

    AN ALLOWLIST. A section is published because its slice satisfied all five rules, not
    because it failed none of a list of known-bad shapes.

    `prints`/`prints_with_text` are what the ARTICLE says about this number — how many
    times it is printed and how many of those prints carry text — because the slice alone
    cannot see that it has a twin. They default to the ordinary case of one."""
    def skip(rule, **fmt):
        return Skip(number, rule, _SKIP_REASONS[rule].format(number=number, **fmt))

    # BEFORE the empty-slice rule, because the slicer answers an ambiguous number with ""
    # and `no-body` would report that as a section the page does not print — the exact
    # substitution of "could not check" for "is not there" CONTEXT.md forbids.
    if prints_with_text > 1:
        return skip("ambiguous-print", prints=_times(prints),
                    prints_with_text=prints_with_text)
    if not slice_text:
        return skip("no-body")
    if not anchored(slice_text, number, title):
        return skip("mis-anchored")
    # What is left of the slice once its OWN PRINTED leadline and every bracketed
    # legislative-history note are removed — a repealed section is printed as exactly those
    # two things. The measurement is `repo_lib.constitution_section_body_chars`, which is
    # also what the SLICER uses to decide which print of a doubled section number a citation
    # names: were the two written apart, this ingest could publish a print the slicer would
    # not return, and provenance would be verified against the other one.
    body = constitution_section_body_chars(slice_text, number)
    if body == 0:
        return skip("history-only")
    if body < CONST_SECTION_MIN_BODY_CHARS:
        return skip("too-short", length=body, min=CONST_SECTION_MIN_BODY_CHARS)
    return None


def edition(norm_text: str) -> str:
    """The page's own statement of WHICH constitution this is, verbatim from the sentence
    it prints above Article I: "The Constitution is here published as it is in effect
    following the approval of amendments and revisions on November 5, 2024."

    Read from the snapshot rather than typed here, because it is the field that dates the
    text and it moves on its own schedule — the general election. Absent, the ingest
    refuses: a mirror that cannot say which edition it copied is a mirror whose provenance
    is incomplete."""
    m = re.search(r"The Constitution is here published as it is (in effect following the "
                  r"approval of[^.]*)\.", norm_text)
    return m.group(1) if m else ""


# LEGAL STATUS - NOT-A-RULE: a section of the Oregon Constitution (ADR 0005). Its repeal is
# printed by the page itself as a leadline and a repeal bracket, and the Oregon Bulletin --
# ADR 0006's writer of a RULE's legal status -- does not publish constitutional amendments.
def doc_body(article, art_title, sec, prov, slice_text):
    url, sha, source_version, today = prov
    doc_id = orconst_id(article, sec["number"])
    citation = f"Or. Const. Art. {article}, sec. {sec['number']}"
    title = sec["title"]
    printed = leadline(slice_text, sec["number"])
    if sec["title_source"] != "contents-list":
        leadline_note = ("The section title above is the leadline printed at the head of "
                         "the section itself; the article's contents list does not list "
                         "this section")
    elif normalize_ws(printed).lower() != normalize_ws(title).lower():
        # The page says two different things and this document repeats both rather than
        # choosing: section 9 is listed as "Vacancies OF county…" and printed as
        # "Vacancies IN county…", and a reader who spots the difference should find it
        # already noticed rather than wonder which one this mirror mistyped.
        leadline_note = ("The section title above is the leadline the page's own contents "
                         f"list prints for this section. The section itself is headed "
                         f"\"{printed}\" — the source prints the two differently, and both "
                         "are reproduced here as it prints them")
    else:
        leadline_note = ("The section title above is the leadline the page's own contents "
                         "list prints for this section")
    return f"""---
schema_version: 1
corpus: "executive-regulatory-frameworks"
jurisdiction: "oregon"
id: {doc_id}
title: "{title.replace(chr(34), chr(39))}"
doc_type: {DOC_TYPE}
citation: "{citation}"
authority_level: constitution
issuing_body: "People of the State of Oregon; published by the Legislative Counsel Committee"
agency: statewide
legal_authority: []
source_url: "{url}"
source_format: html
retrieved: "{today}"
source_sha256: "{sha}"
snapshot_id: {SNAP_ID}
effective_date: null
last_reviewed: null
source_version: "{source_version}"
status: current
supersedes: null
content_mode: verbatim
conversion_notes: "sliced the section's text out of the shared constitution snapshot (one page carries all 18 articles); line breaks inserted at subsection markers (whitespace-only)"
last_verified: ""
verified_by: ""
maintainer: "@morficflux"
relationships:
  implements: []
  implemented_by: []
  references_external: []
  related: []
  supersedes: []
tags: ["constitution", "article-{orconst_article_slug(article)}"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** The official text of the Oregon
> Constitution is the one published by the Legislative Counsel Committee. Verify against
> the official source: <{url}> (retrieved {today}, {source_version}).

# {title} ({citation})

## At a glance

{citation} — {title}. Article {article} ({art_title}), Oregon Constitution, {source_version}.

## Full text

{flow_to_lines(slice_text)}

## Curator notes

{leadline_note}. The page states that "[u]nless otherwise specifically noted, the leadlines
for the sections have been supplied by Legislative Counsel" — a leadline is not part of the
constitutional text unless the section's own note says the measure carried it.

## Provenance & change history

- Source: <{url}> · retrieved {today} · sha256 `{sha}`
  (shared page snapshot `_meta/snapshots/{SNAP_ID}.html`, all 18 articles)
- See [CHANGELOG](./CHANGELOG.md).
"""


def ingest_article(entry, raw_text, prov, out_dir):
    """Publish every section of one catalog article whose slice passes every rule; report
    the rest.

    Mutates each catalog section in place with the status it ended in — `ingested` and a
    path, or `not_sliceable` and the reason it was not. Returns (published ids, skips)."""
    article = entry["article"]
    art_title = entry["title"]
    published, skipped = [], []
    for sec in entry["sections"]:
        number = sec["number"]
        doc_id = orconst_id(article, number)
        # THE SAME ENTRY POINT verify_provenance reaches through the snapshot_slice_module
        # plugin, called with the same arguments. Ingesting through a private helper would
        # let the text this publishes and the text CI checks it against drift apart.
        slice_text = snapshot_slice(doc_id, SNAP_ID, raw_text)
        prints = constitution_section_prints(raw_text, article, number)
        with_text = sum(1 for t in prints
                        if constitution_section_body_chars(t, number)
                        >= CONST_SECTION_MIN_BODY_CHARS)
        skip = why_not_publishable(slice_text, number, sec["title"],
                                   prints=len(prints), prints_with_text=with_text)
        if skip is not None:
            sec["status"] = "not_sliceable"
            sec["note"] = skip.reason
            sec.pop("path", None)
            skipped.append(skip)
            # A DOCUMENT PUBLISHED BY AN EARLIER RUN IS NOT DELETED HERE, and that is
            # reported rather than left to be discovered: this ingest publishes and
            # refuses, it does not withdraw mirrored law on its own. The stale file is
            # not silent either way — its '## Full text' no longer matches the snapshot,
            # so corpus-verify-provenance fails on it.
            stale = out_dir / f"{doc_id}.md"
            if stale.exists():
                print(f"  NOTE {stale.name} was published by an earlier run and is still "
                      f"on disk; the catalog no longer claims it. Verify or remove it by "
                      f"hand.")
            continue
        (out_dir / f"{doc_id}.md").write_text(
            doc_body(article, art_title, sec, prov, slice_text))
        sec["status"] = "ingested"
        sec["path"] = f"constitution/{doc_id}.md"
        sec.pop("note", None)
        published.append(doc_id)
    return published, skipped


def article_title(region: str, article: str) -> str:
    """An article's own name — "ADMINISTRATIVE DEPARTMENT" — from the line under its
    heading, in the page's own capitalization.

    Three terminators, because three shapes are real on the page: an article with a contents
    list ends its title at `Sec.`, one without a contents list ends it at its first
    `Section N.`, and a REPEALED article — which has neither — ends it at the `[` of the
    repeal bracket. Reading only the first two returned "" for the repealed articles, whose
    names are the only thing the page still says about them."""
    m = re.match(rf"ARTICLE {re.escape(article)}\s+(.*?)\s*"
                 rf"(?=Sec\.\s|Section \d|\[|Note: )", region)
    return _title_text(m.group(1)) if m else ""


def snapshot():
    """(snapshot text, sha256, whether this call fetched it).

    FETCHED ONCE: the page is re-served with a fresh ASP.NET view state on every request,
    so re-fetching would rewrite the committed .html with different bytes for identical
    content. `content_hash`/`hash_snapshot` both hash
    the extracted TEXT, which is stable across fetches — that is the drift signal, and the
    raw bytes are kept only as the copy the text was extracted from."""
    html_path = SNAPSHOT_DIR / f"{SNAP_ID}.html"
    txt_path = SNAPSHOT_DIR / f"{SNAP_ID}.txt"
    fetched = not html_path.exists()
    if fetched:
        raw = fetch(URL)
        html_path.write_bytes(raw)
        txt_path.write_text(html_to_text(raw), encoding="utf-8")
    return (txt_path.read_text(encoding="utf-8", errors="replace"),
            hash_snapshot(SNAP_ID, "html"), fetched)


def retrieved_date(cat, fetched: bool) -> str:
    """THE DATE THE DOCUMENTS CARRY: the day the page was fetched, not the day this script
    last ran. Re-running the ingest re-renders every document from the SAME committed
    snapshot — nothing was retrieved and nothing was re-verified, so stamping today would be
    a provenance claim with no fetch behind it, and it would make a re-run produce different
    files every day."""
    return TODAY if fetched or not cat.get("retrieved") else cat["retrieved"]


def load_catalog():
    if CATALOG.exists():
        return yaml.safe_load(CATALOG.read_text())
    return {"document": "Oregon Constitution", "url": URL, "snapshot_id": SNAP_ID,
            "source_version": "", "articles": []}


# The catalog's key order, so a re-run cannot reorder the file it just wrote.
_CATALOG_KEYS = ["document", "url", "snapshot_id", "retrieved", "source_version", "articles"]


def write_catalog(cat):
    ordered = {k: cat[k] for k in _CATALOG_KEYS if k in cat}
    ordered.update({k: v for k, v in cat.items() if k not in ordered})
    CATALOG.write_text(yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True,
                                      width=100))


# The key order of one article entry, so a re-run cannot reorder the file it just wrote.
_ARTICLE_KEYS = ["article", "occurrence", "title", "discovered", "status", "rule", "note",
                 "sections"]


def _ordered_article(entry: dict) -> dict:
    ordered = {k: entry[k] for k in _ARTICLE_KEYS if k in entry}
    ordered.update({k: v for k, v in entry.items() if k not in ordered})
    return ordered


def _article_key(entry: dict):
    """What identifies one catalog entry. THE DESIGNATION AND WHICH PRINT OF IT — the
    designation alone is not an identity for `XI-A`, which the page prints twice."""
    return (entry["article"], entry.get("occurrence", 0))


def cmd_catalog(articles):
    """Discover the document's articles and their sections FROM THE SOURCE and record them,
    keeping the status of anything already ingested.

    ARTICLES ARE DISCOVERED FROM THE PAGE'S OWN HEADINGS, always over the whole document,
    because the list of articles is itself a finding: an article present on the page and
    absent from this catalog would be indistinguishable from one Oregon does not have. Named
    designations narrow which entries have their SECTIONS re-read, not which articles
    exist."""
    raw_text, _, fetched = snapshot()
    norm = ws_only(raw_text)
    cat = load_catalog()
    cat["retrieved"] = retrieved_date(cat, fetched)
    cat["source_version"] = edition(norm)
    if not cat["source_version"]:
        print(f"{SNAP_ID}: the page does not state which edition it publishes; "
              f"refusing to catalog an undated mirror", file=sys.stderr)
        return 1
    found = discover_articles(norm)
    if not found:
        print(f"{SNAP_ID}: the page prints no ARTICLE headings at all; refusing to write a "
              f"catalog that would say the document has no articles", file=sys.stderr)
        return 1
    wanted = {a["article"] for a in found} if not articles or articles == ["all"] \
        else set(articles)
    unknown = wanted - {a["article"] for a in found}
    if unknown:
        print(f"not printed on the page: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 1
    known = {_article_key(a): a for a in cat["articles"]}
    out = []
    for entry in found:
        prev = known.get(_article_key(entry), {})
        if entry["article"] not in wanted and prev:
            out.append(_ordered_article(prev))
            continue
        # The date of the PAGE this list was read off, not of the run that read it:
        # re-reading the same committed snapshot a year later discovers the same articles
        # from the same bytes, and a moving date here would say otherwise.
        entry["discovered"] = cat["retrieved"]
        prev_secs = {s["number"]: s for s in prev.get("sections", [])}
        for sec in entry["sections"]:
            sec.update({k: v for k, v in prev_secs.get(sec["number"], {}).items()
                        if k in ("status", "path", "note")})
        out.append(_ordered_article(entry))
    cat["articles"] = out
    write_catalog(cat)
    _report_catalog(constitution_article_headings(norm), out, wanted)
    return 0


def _report_catalog(heads, entries, wanted):
    """WHAT THE PAGE PRINTS, COUNTED, on every catalog run — the denominator the mirror is
    measured against, stated rather than left to be inferred from the file.

    ONE DENOMINATOR PER LINE, and it is the denominator of what this run looked at.
    `--catalog XI` reads one article, so the totals say ONE ARTICLE and name it; only a run
    over the whole document says "whole document". A summary that counted articles over the
    file and sections over the argument reported a whole-document total for a one-article
    run, which is the sentence a reader would trust and shouldn't.

    The article's own region comes from `heads`, which the caller already walked, rather
    than being looked up again by designation — for XI-A that lookup goes through the
    "which print" rule and answers about a different heading than the line being printed."""
    regions = {(h.designation, h.occurrence): h.text for h in heads}
    prints = numbers = mirrored = shown = 0
    for entry in entries:
        if entry["article"] not in wanted:
            continue
        shown += 1
        secs = entry["sections"]
        n = sum(s.get("prints", 1) for s in secs)
        prints += n
        numbers += len(secs)
        label = f"Article {entry['article']}"
        if "occurrence" in entry:
            label += f" [print {entry['occurrence'] + 1}]"
        if entry.get("status") == "not_mirrored":
            print(f"{label} ({entry['title']}): NOT MIRRORED [{entry['rule']}]")
            continue
        mirrored += 1
        region = regions.get((entry["article"], entry.get("occurrence", 0)), "")
        doubled = ("" if n == len(secs) else
                   f" ({n} section headings, {n - len(secs)} of them a superseded print of "
                   f"a number the article prints more than once)")
        print(f"{label} ({entry['title']}): {len(secs)} section number(s) on the page, "
              f"{len(contents_list(region))} listed in its contents list{doubled}")
    scope = ("whole document" if shown == len(entries)
             else f"{shown} of {len(entries)} article heading(s) "
                  f"({', '.join(sorted(wanted))})")
    print(f"{scope}: {shown} article heading(s) printed, {mirrored} carrying sections, "
          f"{numbers} distinct section number(s) across {prints} section heading(s)")


def cmd_ingest(articles):
    raw_text, sha, fetched = snapshot()
    norm = ws_only(raw_text)
    cat = load_catalog()
    cat["retrieved"] = retrieved_date(cat, fetched)
    if not GROUP.exists():
        print(f"{GROUP.relative_to(REPO_ROOT)} does not exist. The group's cadence and the "
              f"date its clock starts are decisions a human makes (ADR 0005); this ingest "
              f"maintains the sha256 in it and nothing else.", file=sys.stderr)
        return 1
    OUT.mkdir(exist_ok=True)
    prov = Provenance(URL, sha, cat["source_version"], cat["retrieved"])
    wanted = ({a["article"] for a in cat["articles"]} if not articles or articles == ["all"]
              else set(articles))
    unknown = wanted - {a["article"] for a in cat["articles"]}
    if unknown:
        print(f"not in {CATALOG.relative_to(REPO_ROOT)}: {', '.join(sorted(unknown))} — run "
              f"--catalog first", file=sys.stderr)
        return 1
    rc = 0
    totals = [0, 0, 0]      # published, section numbers, articles not mirrored
    by_rule = {}
    for entry in cat["articles"]:
        if entry["article"] not in wanted:
            continue
        label = f"Article {entry['article']}"
        if "occurrence" in entry:
            label += f" [print {entry['occurrence'] + 1}]"
        if entry.get("status") == "not_mirrored":
            totals[2] += 1
            print(f"{label}: NOT MIRRORED [{entry['rule']}]: {entry['note']}")
            continue
        published, skipped = ingest_article(entry, norm, prov, OUT)
        totals[0] += len(published)
        totals[1] += len(entry["sections"])
        for sk in skipped:
            by_rule[sk.rule] = by_rule.get(sk.rule, 0) + 1
        print(f"{label}: published {len(published)} of {len(entry['sections'])} section "
              f"number(s) the page prints")
        for sk in skipped:
            print(f"  SKIPPED sec. {sk.number} [{sk.rule}]: {sk.reason}")
    write_catalog(cat)

    group = yaml.safe_load(GROUP.read_text())
    for src in group["sources"]:
        if src["id"] == SNAP_ID:
            src["sha256"] = sha
            src["last_checked"] = cat["retrieved"]
    GROUP.write_text(yaml.safe_dump(group, sort_keys=False, allow_unicode=True, width=110))
    write_index(cat)
    # THE COUNT IS STATED, NOT IMPLIED. A run that published fewer sections than the page
    # prints has to say how many and under which rule, or "10 of 11" is the only trace a
    # skipped section leaves and nobody adds up the difference.
    skipped_total = totals[1] - totals[0]
    print(f"whole document: published {totals[0]} of {totals[1]} section number(s), "
          f"skipped {skipped_total}"
          + (" (" + ", ".join(f"{n} {rule}" for rule, n in sorted(by_rule.items())) + ")"
             if by_rule else "")
          + f"; {totals[2]} article heading(s) not mirrored")
    if skipped_total != sum(by_rule.values()):
        print("the skipped sections do not add up to the rules that refused them — one of "
              "the two counts is wrong", file=sys.stderr)
        rc = 1
    return rc


def check_article(entry, raw_text, prov, out_dir, unclaimed=False) -> list:
    """Every disagreement between one catalog article and what is on disk.

    THE RULE `cmd_check` RUNS AND THE SELFTEST WATCHES FAIL, in one place, so the gate that
    guards the mirror and the proof that the gate works cannot describe different rules.

    Four kinds, named apart because they are different kinds of wrong:

      * a section the catalog claims `ingested` whose file is not there — the mirror LOST a
        document, and every citation to it now answers the way a wrong citation does, which
        is the collapse ADR 0005 exists to prevent
      * a file whose bytes differ from what re-rendering it now produces — criterion 10: a
        re-run would rewrite it, so what is committed is not what the pipeline says
      * a `path` that does not name the id — the join between catalog, file and citation has
        come apart
      * (with `unclaimed`) a file in the directory nothing in the catalog claims — this
        ingest never withdraws mirrored law on its own, so this is how an earlier run's
        document is FOUND rather than left to be discovered"""
    problems = []
    for sec in entry["sections"]:
        doc_id = orconst_id(entry["article"], sec["number"])
        path = out_dir / f"{doc_id}.md"
        if sec.get("status") != "ingested":
            if path.exists():
                problems.append(
                    f"{path.name} is on disk and the catalog does not claim it — it records "
                    f"{sec.get('status', 'no status')} for Art. {entry['article']}, "
                    f"sec. {sec['number']}")
            continue
        if sec.get("path") != f"constitution/{doc_id}.md":
            problems.append(f"Art. {entry['article']}, sec. {sec['number']} records path "
                            f"{sec.get('path')!r}, which is not the path the id {doc_id} "
                            f"names")
        if document_is_missing(sec, doc_id, out_dir):
            problems.append(
                f"{path.name} is MISSING: the catalog claims Art. {entry['article']}, "
                f"sec. {sec['number']} is ingested and no document is there. A citation to "
                f"it now answers the way a wrong citation does.")
            continue
        expected = doc_body(entry["article"], entry["title"], sec, prov,
                            snapshot_slice(doc_id, SNAP_ID, raw_text))
        if path.read_text() != expected:
            problems.append(f"{path.name} differs from what re-rendering it from the "
                            f"committed snapshot produces — a re-run would rewrite it")
    if unclaimed:
        claimed = {f"{orconst_id(entry['article'], s['number'])}.md"
                   for s in entry["sections"]}
        problems += [f"{p.name} is in {out_dir.name}/ and NOTHING in the catalog claims it. "
                     f"This ingest never withdraws mirrored law on its own, so an earlier "
                     f"run's document ends up here."
                     for p in sorted(out_dir.glob("orconst-*.md")) if p.name not in claimed]
    return problems


def committed_snapshot():
    """(the committed snapshot's text, its sha256) — or (None, None) after saying why not.

    THE REFUSAL IS THE POINT, and it is shared because two copies of it could come to say
    different things: `snapshot()` FETCHES when nothing is committed, and a gate that then
    checked the corpus against a page it just downloaded would be verifying the mirror
    against tomorrow's Constitution while reporting on today's."""
    raw_text, sha, fetched = snapshot()
    if fetched:
        print(f"{SNAP_ID}: no committed snapshot to check against; this fetched one. "
              f"Commit it, then re-run.", file=sys.stderr)
        return None, None
    return raw_text, sha


def cmd_check():
    """WHAT THE CATALOG SAYS SHOULD EXIST, AGAINST WHAT IS ON DISK — criteria 7 and 10 of
    #195, as a gate rather than as an intention.

    THE CATALOG IS THE LIST OF WHAT SHOULD EXIST. Without something reading it back, a
    document deleted from `constitution/` is *merely absent*: a citation to it falls through
    to the framework's generic "unresolved", which is the same answer a wrong citation gets.
    Here it is DETECTED, and named. `check_article` above holds the four rules.

    Reads the COMMITTED snapshot and never the network."""
    raw_text, sha = committed_snapshot()
    if raw_text is None:
        return 1
    norm = ws_only(raw_text)
    cat = load_catalog()
    prov = Provenance(URL, sha, cat["source_version"], cat["retrieved"])
    problems, claimed, ingested = [], set(), 0
    for entry in cat["articles"]:
        problems += check_article(entry, norm, prov, OUT)
        for sec in entry["sections"]:
            claimed.add(f"{orconst_id(entry['article'], sec['number'])}.md")
            ingested += sec.get("status") == "ingested"
    # ACROSS ALL ARTICLES, not per article: a document belongs to the catalog as a whole, so
    # asking one article whether it claims a file would report every other article's
    # documents as unclaimed.
    problems += [f"{p.name} is in {OUT.name}/ and NOTHING in the catalog claims it. This "
                 f"ingest never withdraws mirrored law on its own, so an earlier run's "
                 f"document ends up here."
                 for p in sorted(OUT.glob("orconst-*.md")) if p.name not in claimed]
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    numbers = sum(len(a["sections"]) for a in cat["articles"])
    unmirrored = sum(1 for a in cat["articles"] if a.get("status") == "not_mirrored")
    print(f"catalog: {len(cat['articles'])} article heading(s), {unmirrored} carrying no "
          f"sections; {numbers} section number(s), {ingested} published, "
          f"{numbers - ingested} cataloged with the reason they were not")
    if problems:
        print(f"{len(problems)} disagreement(s) between the catalog and constitution/",
              file=sys.stderr)
        return 1
    print(f"all {ingested} published document(s) are on disk and byte-identical to what "
          f"re-rendering them from the committed snapshot produces")
    return 0


# --------------------------------------------------------- drift, section by section
# WHAT THIS REPORT EXISTS FOR (#197). The group's upstream signal is ONE sha256 over the
# whole document — the Legislature publishes all 18 articles on one page — so an amendment
# anywhere moves it and the signal says that SOMETHING changed and never what. That
# limitation is recorded once, in `_meta/sources/constitution.yml`'s `upstream_signal`, and
# this is the diff it says has to do the work.
#
# THE VALUE IS ENTIRELY IN THE DIFFERENCE. A report that named every section on any change
# would tell an operator exactly what the hash already told them, so a section whose text is
# unchanged is not reported at all.

# The three things this report can say about one section number, and they may never be
# collapsed into two. CONTEXT.md's overriding rule is the whole reason for the third: a
# section that cannot be sliced out of a changed page is NOT a section Oregon deleted.
CHANGED = "CHANGED"
UNCHANGED = "unchanged"
UNCHECKABLE = "COULD NOT CHECK"

# WHY a section could not be checked — named, so `--selftest` asserts on the reason that
# fired instead of pattern-matching prose (`SkippedSection.rule`, same reason). Two of them,
# and they are statements about different things: the candidate page's shape moved under the
# slicer, or the mirror's own catalog records a section the committed page does not print.
NO_SLICE = "no-slice-on-the-candidate-page"
NO_BASELINE = "no-slice-on-the-committed-snapshot"

DriftRow = namedtuple("DriftRow", "state reason article section doc_id detail")


def section_drift(articles, committed_norm, candidate_norm) -> list:
    """One row per catalog section number: did this section's text move between the
    committed snapshot and the candidate page?

    THE CATALOG IS THE ALLOWLIST. Every comparison is a section the catalog records — 371
    numbers on the 2024 edition, the 339 published and the 32 recorded with the reason they
    were not — rather than whatever `constitution/` happens to hold. A section the page
    stopped printing is then a row that could not be checked, and not a row that quietly
    stops existing.

    BOTH SIDES GO THROUGH `snapshot_slice`, the same function the ingest published through
    and `corpus-verify-provenance` verifies through, so a difference here is a difference in
    the section's text and never in how two callers cut it out."""
    rows = []
    for entry in articles:
        for sec in entry["sections"]:
            doc_id = orconst_id(entry["article"], sec["number"])
            before = snapshot_slice(doc_id, SNAP_ID, committed_norm)
            after = snapshot_slice(doc_id, SNAP_ID, candidate_norm)
            rows.append(_compare(entry, sec, doc_id, before, after))
    return rows


def _where(sec, doc_id) -> str:
    """Which document a row is about, so a CHANGED row says what to re-render — read from
    the CATALOG's claim and never off the filesystem, because a document that has gone
    missing must not be reported as a section this mirror never published. That a claimed
    document is absent is `missing_documents`'s to say, once, before any of this runs."""
    if sec.get("status") == "ingested":
        return f"constitution/{doc_id}.md"
    return (f"the catalog records this section {sec.get('status', 'with no status')} and "
            f"this mirror publishes no text for it")


def document_is_missing(sec, doc_id, out_dir) -> bool:
    """The catalog claims this section is published and `out_dir` does not carry it.

    ONE PREDICATE, TWO CALLERS, because two places deciding what a lost document is, is two
    places that can come to disagree about it. `cmd_check` reports it per section with what
    it costs — a citation that now answers the way a wrong citation does — and `cmd_drift`
    refuses the whole run over it."""
    return sec.get("status") == "ingested" and not (out_dir / f"{doc_id}.md").exists()


def missing_documents(articles, out_dir) -> list:
    """Every document the catalog claims and `out_dir` does not carry.

    THE PRECONDITION OF THE DRIFT REPORT, and the reason it reads the committed documents
    and not only the committed snapshot. Against a `constitution/` that is not there every
    section still compares equal — the two pages are still the two pages — so the report
    would be a clean bill of health for documents that do not exist. The catalog defines the
    population, never the filesystem: a mirror wiped to nothing would otherwise look like a
    mirror with nothing to check.

    NOT `unmirrored`, which this file already uses for an ARTICLE the page prints with no
    sections at all (`status: not_mirrored`). Those are different absences."""
    missing = []
    for entry in articles:
        for sec in entry["sections"]:
            doc_id = orconst_id(entry["article"], sec["number"])
            if document_is_missing(sec, doc_id, out_dir):
                missing.append(doc_id)
    return missing


def _compare(entry, sec, doc_id, before, after) -> DriftRow:
    """THE THREE ANSWERS, in the order the rule reads: no baseline, no candidate slice,
    then the comparison itself. The two refusals come first because a `""` compared against
    a `""` is equal, and equal would print as `unchanged` — an answer, given about a section
    nothing was read for."""
    def row(state, reason, detail):
        return DriftRow(state, reason, entry["article"], sec["number"], doc_id, detail)

    if not before:
        return row(UNCHECKABLE, NO_BASELINE,
                   "the committed snapshot prints no such section, so there is no baseline "
                   "to compare the candidate page against. The catalog and the page it was "
                   "built from disagree — a statement about this mirror, not about Oregon "
                   "law")
    if not after:
        return row(UNCHECKABLE, NO_SLICE,
                   f"the candidate page yields no slice for this section, so this run has "
                   f"nothing to compare. NOT that the section was deleted: a heading that "
                   f"stopped parsing and a section Oregon repealed look identical from "
                   f"here, and only the diff can tell them apart ({_where(sec, doc_id)})")
    if before != after:
        return row(CHANGED, "",
                   f"the text under this section's heading moved ({_where(sec, doc_id)})")
    return row(UNCHANGED, "", "")


def candidate_page(path=None):
    """(the page's text, where it came from) for the page this run compares the mirror
    against.

    A PATH IS THE DEFAULT WAY IN, and it is what makes the comparison network-free: the page
    an operator already has — the fetch a drift issue was opened from — is compared without
    asking the Legislature for it again. With no path this fetches, which is the only thing
    in this command that touches the network.

    HTML IS EXTRACTED THE WAY `snapshot()` EXTRACTED THE COMMITTED `.txt` — `html_to_text`
    over the raw bytes, with no `normalize_volatile` — because the two texts are compared
    against each other. Stripping volatile bytes on one side only would show up as a section
    that moved. (`content_hash` strips them and this page carries none, which is why the
    group's recorded sha256 and `hash_snapshot` agree today; that they COULD disagree is a
    property of `snapshot()` and not of this comparison.)"""
    if path is None:
        return html_to_text(fetch(URL)), URL
    path = Path(path)
    if path.suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace"), str(path)
    return html_to_text(path.read_bytes()), str(path)


def group_sha256():
    """The sha256 `_meta/sources/constitution.yml` records for the page — the ONE number the
    update-check cycle compares a fetch against, read from the group that defines the signal
    rather than recomputed here, so this report and `check_updates.py` cannot disagree about
    whether the page moved."""
    if not GROUP.exists():
        return None
    group = yaml.safe_load(GROUP.read_text())
    return next((s.get("sha256") for s in group["sources"] if s["id"] == SNAP_ID), None)


def cmd_drift(path=None):
    """WHICH SECTIONS MOVED — the report the group's one-hash signal cannot give (#197).

    Reads the COMMITTED snapshot and the COMMITTED documents; the only network in this
    command is fetching the candidate page, and passing a path removes even that.

    THE RUN SAYS SO RATHER THAN PASSING QUIETLY: a changed page exits non-zero, whether or
    not any sliced section accounts for the change. A page that moved with every section's
    text intact is a real and reportable outcome — the change is somewhere this mirror does
    not slice — and reporting it as `ok` would be the quiet pass this ticket exists to
    remove."""
    committed_text, committed_sha = committed_snapshot()
    if committed_text is None:
        return 1
    cat = load_catalog()
    missing = missing_documents(cat["articles"], OUT)
    if missing:
        print(f"REFUSING TO REPORT: the catalog claims {len(missing)} published document(s) "
              f"that {OUT.name}/ does not carry ({', '.join(missing[:3])}"
              f"{', …' if len(missing) > 3 else ''}). Every section would compare equal and "
              f"this run would be a clean bill of health for documents that are not there. "
              f"Run --check.", file=sys.stderr)
        return 1
    text, origin = candidate_page(path)
    page_sha = normalized_text_hash(text)
    if page_sha is None:
        print(f"{origin}: too little text to hash — this run cannot say whether the page "
              f"moved, which is not the claim that it did not.", file=sys.stderr)
        return 1
    rows = section_drift(cat["articles"], ws_only(committed_text), ws_only(text))
    findings = [r for r in rows if r.state != UNCHANGED]
    # THE BASELINE IS THE SNAPSHOT THE SECTIONS ARE SLICED FROM, never the group file's
    # copy of its hash. Read the other way round, this command run against the committed
    # snapshot ITSELF would report `page CHANGED` with no section to account for it — a
    # drift report sending an operator to diff a snapshot against itself. That the group
    # records a different number is a real disagreement and it is reported as its own
    # finding, because it means the update-check cycle is comparing fetches against a hash
    # that is not this mirror's.
    moved = page_sha != committed_sha
    recorded = group_sha256()
    print(f"{SNAP_ID}: page {'CHANGED' if moved else 'unchanged'} — "
          f"{committed_sha[:10]}…{f' -> {page_sha[:10]}…' if moved else ''}"
          f" ({origin} against the committed snapshot)")
    for r in findings:
        print(f"  {r.state} Art. {r.article}, sec. {r.section}"
              f"{f' [{r.reason}]' if r.reason else ''} — {r.detail}")
    counts = Counter(r.state for r in rows)
    print(f"{len(rows)} section number(s) compared: {counts[CHANGED]} changed, "
          f"{counts[UNCHECKABLE]} could not be checked, {counts[UNCHANGED]} unchanged")
    sys.stdout.flush()
    rc = 1 if (moved or findings) else 0
    if moved and not findings:
        print(f"the page moved and no section this mirror slices did: the change is in text "
              f"outside the {len(rows)} section number(s) the catalog records — a heading, "
              f"the edition sentence, or page furniture. Diff the snapshot.", file=sys.stderr)
    if recorded != committed_sha:
        print(f"{GROUP.relative_to(REPO_ROOT)} records sha256 {str(recorded)[:10]}… for "
              f"{SNAP_ID} and the committed snapshot hashes to {committed_sha[:10]}…. The "
              f"update-check cycle compares fetches against the group's number, so it is "
              f"reporting drift against a page this mirror does not hold. Re-run --ingest.",
              file=sys.stderr)
        rc = 1
    return rc


def write_index(cat):
    mirrored = [a for a in cat["articles"] if a.get("status") != "not_mirrored"]
    unmirrored = [a for a in cat["articles"] if a.get("status") == "not_mirrored"]
    lines = ["# Oregon Constitution — index", "",
             "Every section of the Oregon Constitution, full text per section, sliced from",
             "the single page the Legislature publishes the whole document on",
             f"({cat['source_version']}).",
             "**Non-authoritative copies** — the official text is the one published by the",
             "Legislative Counsel Committee.", "",
             "Articles are the page's own headings, parenthetical included: ARTICLE VII is",
             "printed twice, as `(Amended)` and `(Original)`, and both are operative and",
             "both are mirrored. `XI-F(1)` and `XI-F(2)` are two articles, not one printed",
             "twice.", "",
             "| Article | Title | Section numbers on the page | Published |",
             "|---|---|---|---|"]
    tot = [0, 0]
    for a in mirrored:
        n = len(a["sections"])
        i = sum(1 for s in a["sections"] if s.get("status") == "ingested")
        tot[0] += n
        tot[1] += i
        lines.append(f"| {a['article']} | {a['title']} | {n} | {i} |")
    lines += [f"| **all** | | **{tot[0]}** | **{tot[1]}** |", ""]
    if unmirrored:
        lines += [f"## Article headings the page prints and this corpus does not mirror "
                  f"({len(unmirrored)})", "",
                  "Not a gap — each is a repealed article the page still prints as its",
                  "heading, its title and the measure that repealed it, with no section",
                  "text under it. The reason is recorded beside each one in the catalog.",
                  "", "| Article | Title | Why |", "|---|---|---|"]
        for a in unmirrored:
            where = "" if "occurrence" not in a else f" (print {a['occurrence'] + 1})"
            lines.append(f"| {a['article']}{where} | {a['title']} | `{a['rule']}` |")
        lines.append("")
    lines += ["Per-section numbers/titles/paths:",
              "[`_meta/catalog/constitution.yml`](../_meta/catalog/constitution.yml).",
              "Sections marked `not_sliceable` there are sections the page prints that this",
              "ingest did not publish, each with the reason recorded beside it.", ""]
    (OUT / "_index.md").write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--catalog", nargs="*", metavar="ARTICLE")
    ap.add_argument("--ingest", nargs="*", metavar="ARTICLE")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--drift", nargs="?", const="", metavar="PAGE",
                    help="which sections moved between the committed snapshot and PAGE "
                         "(a .html or .txt copy of the source page); with no PAGE, fetches")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if args.check:
        sys.exit(cmd_check())
    if args.drift is not None:
        sys.exit(cmd_drift(args.drift or None))
    if args.catalog is not None:
        sys.exit(cmd_catalog(args.catalog))
    if args.ingest is not None:
        sys.exit(cmd_ingest(args.ingest))
    ap.print_help()
    sys.exit(2)


# ------------------------------------------------------------------------ selftest
# Synthetic fixtures: no network, no committed snapshot. Every rule that can SKIP a
# section is demonstrated firing, because a guard nobody has watched fail is not known
# to work — and the consequence of a silent one here is a published document that is not
# the source's text.
FIXTURE = ws_only("""
ARTICLE V
EXECUTIVE BRANCH
Sec. 1. Governor
2. Term of office
Section 1. Governor. The chief executive power of the State shall be vested in a
Governor, who shall hold his office for the term of four years.
Section 2. Term of office. The Governor shall be elected at the times and places of
choosing members of the Legislative Assembly.
ARTICLE VI
ADMINISTRATIVE DEPARTMENT
Sec. 1. Election of Secretary and Treasurer of state
2. Duties of Secretary of State
Section 1. Election of Secretary and Treasurer of state. There shall be elected by the
qualified electors of the State, at the times and places of choosing Members of the
Legislative Assembly, a Secretary, and Treasurer of State.
Section 2. Duties of Secretary of State. The Secretary of State shall keep a fair record
of the official acts of the Legislative Assembly, and Executive Branch.
Section 2a. County manager form of government. [Created through H.J.R. 3, 1943, and
adopted by the people Nov. 7, 1944; Repeal proposed by H.J.R. 22, 1957, and adopted by
the people Nov. 4, 1958]
ARTICLE VII (Amended)
JUDICIAL BRANCH
Section 1. Courts. The judicial power of the state shall be vested in one supreme court and
in such other courts as may from time to time be created by law.
ARTICLE VII (Original)
THE JUDICIAL BRANCH
Section 1. Courts. The judicial power of the State shall be vested in a Suprume Court,
Circuits Courts, and County Courts, which shall be courts of record.
ARTICLE XI
CORPORATIONS AND INTERNAL IMPROVEMENTS
Sec. 11. Property tax limitations on assessed value and rate of tax
11e. Severability of sections 11b, 11c and 11d
11L. Limitation on applicability of sections 11 and 11b on bonded indebtedness
Section 11. Property tax limitations on assessed value and rate of tax. For the tax year
beginning July 1, 1997, each unit of property in this state shall have a maximum assessed
value for ad valorem property tax purposes.
Section 11e. Severability of sections 11b, 11c and 11d. If any portion of sections 11b, 11c
or 11d of this Article is held invalid, the remaining portions shall not be affected.
Section 11L. Limitation on applicability of sections 11 and 11b on bonded indebtedness.
Sections 11 and 11b of this Article do not apply to bonded indebtedness incurred to finance
capital costs, if the question of the issuance is approved by the electors.
ARTICLE XI-A
RURAL CREDITS
[Created through initiative petition filed July 6, 1916, and adopted by the people Nov. 7,
1916; Repeal proposed by S.J.R. 1, 1941, and adopted by the people Nov. 3, 1942]
ARTICLE XI-A
FARM AND HOME LOANS TO VETERANS
Sec. 1. State empowered to make farm and home loans to veterans
Section 1. State empowered to make farm and home loans to veterans. The credit of the State
of Oregon may be loaned and indebtedness incurred for the purpose of creating a fund to be
known as the "Oregon War Veterans' Fund".
ARTICLE XI-F(1)
HIGHER EDUCATION BUILDING PROJECTS
Sec. 1. State empowered to lend credit
Section 1. State empowered to lend credit. The credit of the State of Oregon may be loaned
and indebtedness incurred for the purpose of providing buildings for higher education.
ARTICLE XIV
SEAT OF GOVERNMENT
Sec. 2. Erection of state house prior to 1865
Section 1. Removal of seat of government. [Constitution of 1859; Repeal proposed by S.J.R.
41, 1957, and adopted by the people Nov. 4, 1958]
Section 1. Seat of government. The permanent seat of government for the state shall be
Marion County. [Created through S.J.R. 41, 1957, and adopted by the people Nov. 4, 1958]
Section 2. Erection of state house prior to 1865. No tax shall be levied, or money of the
State expended, or debt contracted for the erection of a State House prior to the year
eighteen hundred and sixty five.
Section 3. Limitation on removal of seat of government. [Constitution of 1859; Repeal
proposed by S.J.R. 41, 1957, and adopted by the people Nov. 4, 1958]
Section 3. Location and use of state institutions. [Created through S.J.R. 41, 1957, and
adopted by the people Nov. 4, 1958; Repeal proposed by S.J.R. 9, 1971, and adopted by the
people Nov. 7, 1972]
""")


def _proof_a_slice_is_this_article_s_section_and_nothing_else(ck):
    """The slicing rule, at the seam provenance verification reads it through.

    THREE WAYS TO GET THIS WRONG, all of which publish text the citation does not name:
    take the whole page, take Article V's section 1 (every article has one), or start at
    the article's own contents list, where the section number also appears."""
    sl = snapshot_slice("orconst-art-vi-sec-1", SNAP_ID, FIXTURE)
    ck("slice starts at Article VI's section 1",
       sl.startswith("Section 1. Election of Secretary and Treasurer of state."))
    ck("slice stops before the next section", "Section 2." not in sl)
    ck("slice does not reach the next article", "ARTICLE VII" not in sl)
    ck("slice is not the whole page", "Governor" not in sl)
    ck("the article's contents list is not sliced", "Sec. 1." not in sl)


def _proof_an_article_is_found_by_its_whole_designation(ck):
    """WHICH ARTICLE VII. The page prints ARTICLE VII twice — `(Amended)` and `(Original)`,
    both operative — so the roman numeral alone names two regions and cannot select one.

    And the OTHER shape, which is not the same fact: `ARTICLE XI-A` is printed twice under
    ONE designation, the repealed RURAL CREDITS article of 1916 and the article in force.
    Every heading the page prints is catalogued, so the repealed one is a stated finding;
    the SLICER, which reaches an article from a doc id alone and so has no occurrence to be
    told, takes the one that prints section bodies."""
    heads = constitution_article_headings(FIXTURE)
    ck("every heading the page prints is found, in the order it prints them",
       [(h.designation, h.occurrence) for h in heads]
       == [("V", 0), ("VI", 0), ("VII (Amended)", 0), ("VII (Original)", 0),
           ("XI", 0), ("XI-A", 0), ("XI-A", 1), ("XI-F(1)", 0), ("XIV", 0)])
    amended = constitution_article_region(FIXTURE, "VII (Amended)")
    original = constitution_article_region(FIXTURE, "VII (Original)")
    ck("Article VII (Amended) is its own region",
       "vested in one supreme court" in amended and "Suprume Court" not in amended)
    ck("Article VII (Original) is a different one",
       "Suprume Court" in original and "vested in one supreme court" not in original)
    ck("neither reaches the next article", "ARTICLE XI-A" not in original)
    ck("a lettered-and-numbered designation is not read as its parent",
       "HIGHER EDUCATION" in constitution_article_region(FIXTURE, "XI-F(1)"))
    live = constitution_article_region(FIXTURE, "XI-A")
    ck("the slicer's XI-A is the occurrence that prints sections",
       "Oregon War Veterans" in live and "RURAL CREDITS" not in live)
    ck("...and the repealed print is still there to be catalogued",
       "RURAL CREDITS" in heads[5].text and "Section " not in heads[5].text)


def _proof_a_section_number_printed_twice_resolves_to_the_one_in_force(ck):
    """A SECTION NUMBER IS NOT ALWAYS ONE SECTION, and neither the first print nor the last
    is the answer. Measured on the 2024 edition: 9 numbers across 7 articles are printed
    more than once, 19 prints in all, and the operative print is FIRST in Article IV
    (sections 1 and 6 were amended in place, the superseded print following) and LAST in
    Article XIV, Article XV and Article XI (section 11, printed three times).

    Every superseded print is the shape of a repealed section — a leadline and a
    legislative-history bracket and nothing between them — so what distinguishes the print a
    citation means is the one carrying TEXT. That is the rule here, and it is applied in the
    SLICER rather than in this ingest: `snapshot_slice` is reached from a doc id alone, so a
    rule that lived here would publish one print and verify provenance against another.

    Article XIV section 3, whose two prints are BOTH repealed, is the case that must not be
    guessed at: there is no text, so nothing is published and the reason says so."""
    live = constitution_section_slice(FIXTURE, "XIV", "1")
    ck("the print carrying text is the one sliced, though it is printed second",
       "Marion County" in live)
    ck("...and the superseded print is not glued to it",
       live.count("Section 1.") == 1)
    ck("...and the slice stops before the next section", "Erection" not in live)
    ck("both prints are still visible to the catalog",
       [constitution_section_body_chars(t, "1") > 0
        for t in constitution_section_prints(FIXTURE, "XIV", "1")] == [False, True])
    ck("a number whose every print is repealed yields a history-only slice, not silence",
       why_not_publishable(constitution_section_slice(FIXTURE, "XIV", "3"), "3",
                           "Limitation on removal of seat of government").rule
       == "history-only")
    ck("a number printed once is unaffected",
       "eighteen hundred and sixty five" in constitution_section_slice(FIXTURE, "XIV", "2"))


def _proof_two_prints_both_carrying_text_are_refused(ck):
    """THE CASE WITH NO INSTANCE IN THE 2024 EDITION, refused rather than guessed.

    If an article ever prints one section number twice with text under both, nothing in the
    citation says which one it names — so the slicer returns nothing and this ingest reports
    it, instead of taking whichever came first and publishing text under a citation that
    does not name it. Watched failing here because it cannot be watched failing on the
    document: a guard nobody has seen fire is not known to work."""
    doubled = FIXTURE.replace(
        "Section 1. Removal of seat of government. [Constitution of 1859; Repeal proposed by "
        "S.J.R. 41, 1957, and adopted by the people Nov. 4, 1958]",
        "Section 1. Removal of seat of government. The seat of government shall not be "
        "removed from Salem without the consent of the electors of the state.")
    ck("the fixture really has two prints with text", doubled != FIXTURE)
    ck("neither print is sliced", constitution_section_slice(doubled, "XIV", "1") == "")
    skip = why_not_publishable(constitution_section_slice(doubled, "XIV", "1"), "1",
                               "Seat of government", prints=2, prints_with_text=2)
    ck("and the reason names the ambiguity rather than reporting an absence",
       skip is not None and skip.rule == "ambiguous-print"
       and "twice" in skip.reason and "does not exist" not in skip.reason)


def _proof_the_id_shape_round_trips(ck):
    """The id is the join between three things — the file the ingest writes, the candidate
    the citation scheme resolves to, and the coordinates the SLICER parses back out of it.
    A shape that cannot be parsed back would publish documents whose provenance could not
    be verified, since verify_provenance reaches the slice through the id alone.

    THE ARTICLE'S IDENTITY CARRIES ITS PARENTHETICAL, because that is part of how Oregon
    cites the article: the page prints ARTICLE VII twice — `(Amended)` and `(Original)` —
    and both are operative and both are cited. `XI-F(1)` and `XI-F(2)` are two designations
    and not one article printed twice."""
    for article, section in (("VI", "1"), ("VI", "9a"), ("XI-A", "3"), ("XVIII", "10"),
                             ("VII (Amended)", "1"), ("VII (Original)", "1"),
                             ("XI-F(1)", "1"), ("XI-I(2)", "4"), ("X-A", "2")):
        doc_id = orconst_id(article, section)
        m = ORCONST_ID_RE.match(doc_id)
        ck(f"{doc_id} parses back to Article {article}, section {section}",
           bool(m) and orconst_article_designation(m.group(1)) == article
           and m.group(2) == section)
    # CRITERION 12, as a proof rather than as an intention: Article VI's ten documents are
    # live on main, and every citation that resolves today resolves to one of those ids.
    # An identity change that re-keyed them would break all of it silently.
    ck("Article VI's published ids are untouched by the parenthetical",
       [orconst_id("VI", n) for n in ("1", "10")]
       == ["orconst-art-vi-sec-1", "orconst-art-vi-sec-10"])
    ck("VII (Amended) and VII (Original) are different documents",
       orconst_id("VII (Amended)", "1") != orconst_id("VII (Original)", "1"))


def _proof_the_catalog_is_discovered_from_the_source(ck):
    """WHAT THE DENOMINATOR IS. The section list comes from the article's own BODY —
    every `Section N.` heading it prints — and not from the contents list above it, which
    omits repealed sections (Article VI's section 9a is in the body and not in the list).
    A catalog built from the contents list would leave a section this corpus never looked
    at indistinguishable from one the source does not carry.

    The title still comes from the contents list where there is one, because that makes
    the anchoring check in `anchored()` a cross-check between two independently printed
    parts of the page rather than a comparison of the body with itself."""
    secs = discover_sections(constitution_article_region(FIXTURE, "VI"))
    ck("every section the body prints is cataloged",
       [s["number"] for s in secs] == ["1", "2", "2a"])
    ck("a section absent from the contents list is still cataloged",
       secs[2]["title_source"] == "leadline")
    ck("its title is read from its own leadline",
       secs[2]["title"] == "County manager form of government")
    ck("a listed section takes the contents list's title",
       secs[1] == {"number": "2", "title": "Duties of Secretary of State",
                   "title_source": "contents-list"})
    ck("another article's sections are not cataloged here",
       all(s["title"] != "Governor" for s in secs))


def _proof_the_article_catalog_is_the_pages_own_headings(ck):
    """WHAT THE ARTICLE-LEVEL DENOMINATOR IS: every ARTICLE heading the page prints, in the
    order it prints them — not a list of eighteen roman numerals, and not the articles this
    corpus happened to notice being cited.

    Two things it must not collapse. ARTICLE VII (Amended) and ARTICLE VII (Original) are
    TWO ARTICLES sharing a numeral, and both are catalogued and both are mirrored. ARTICLE
    XI-A is ONE DESIGNATION PRINTED TWICE — the 1916 RURAL CREDITS article, repealed in 1942
    and kept on the page as a heading and a repeal bracket, and the article in force. The
    repealed print is CATALOGUED AND SKIPPED WITH ITS REASON, the way Article VI's section 9a
    is, so that its absence from the mirror is a finding this repository states rather than a
    gap a reader has to notice."""
    arts = discover_articles(FIXTURE)
    ck("every heading is an entry, both prints of XI-A included",
       [(a["article"], a.get("occurrence")) for a in arts]
       == [("V", None), ("VI", None), ("VII (Amended)", None), ("VII (Original)", None),
           ("XI", None), ("XI-A", 0), ("XI-A", 1), ("XI-F(1)", None), ("XIV", None)])
    ck("an occurrence is recorded only where the page prints the designation twice",
       [a for a in arts if "occurrence" in a] == [a for a in arts if a["article"] == "XI-A"])
    repealed = arts[5]
    ck("the repealed print is the one with no sections", repealed["sections"] == [])
    ck("...and it is catalogued with the rule that refused it",
       repealed["status"] == "not_mirrored" and repealed["rule"] == "no-sections")
    ck("...and the reason says what the page prints, never that the article does not exist",
       "no 'Section" in repealed["note"] and "does not exist" not in repealed["note"])
    ck("...and it says the designation is printed twice, which is why it is not a gap",
       "twice" in repealed["note"])
    ck("the article in force keeps its sections and its title",
       arts[6]["title"] == "FARM AND HOME LOANS TO VETERANS"
       and [s["number"] for s in arts[6]["sections"]] == ["1"])
    ck("both editions of Article VII are mirrored, separately",
       [a["title"] for a in arts if a["article"].startswith("VII")]
       == ["JUDICIAL BRANCH", "THE JUDICIAL BRANCH"])


def _proof_a_section_number_may_carry_an_uppercase_letter(ck):
    """ARTICLE XI, SECTION 11L, and it is the only one in the document.

    Measured on the 2024 edition: the page prints 381 `Section N.` headings and exactly one
    of them carries an UPPERCASE suffix. Read with a lowercase-only suffix — as every part
    of this pipeline was until #195 — section 11L is not a section that failed a rule and
    was reported; it is a section the tooling could not see at all, which is the one outcome
    a catalog derived from the source may not produce. It sits between 11k and 12 in the
    article's own contents list, so nothing about the count would have looked wrong.

    THE ID IS STILL LOWERCASE (`orconst-art-xi-sec-11l`), as every id in this repo is, and
    the slicer matches the suffix case-insensitively to reach back to the printed
    heading — safe because no article prints both `Section 11l.` and `Section 11L.`."""
    secs = discover_sections(constitution_article_region(FIXTURE, "XI"))
    ck("the uppercase-suffixed section is discovered",
       [s["number"] for s in secs] == ["11", "11e", "11L"])
    ck("...and its title comes from the article's contents list",
       secs[2]["title_source"] == "contents-list"
       and secs[2]["title"].startswith("Limitation on applicability"))
    ck("...and it does not swallow its neighbours' titles",
       secs[1]["title"] == "Severability of sections 11b, 11c and 11d")
    ck("the id is lowercase like every other", orconst_id("XI", "11L")
       == "orconst-art-xi-sec-11l")
    ck("...and the slicer reaches the printed heading from it",
       snapshot_slice("orconst-art-xi-sec-11l", SNAP_ID, FIXTURE)
       .startswith("Section 11L."))
    ck("...and stops there rather than running to the end of the article",
       "ARTICLE XIV" not in snapshot_slice("orconst-art-xi-sec-11l", SNAP_ID, FIXTURE))
    ck("section 11 is not read as the front of section 11L",
       "bonded indebtedness" not in constitution_section_slice(FIXTURE, "XI", "11"))
    ck("the citation resolves to it",
       why_not_publishable(constitution_section_slice(FIXTURE, "XI", "11L"), "11L",
                           secs[2]["title"]) is None)


def _proof_a_section_number_the_page_prints_twice_is_one_catalog_entry(ck):
    """ONE ENTRY PER SECTION NUMBER, because a citation names a number and there is one
    section in force under it. How many times the page PRINTS that number is recorded on the
    entry, so the doubling is a stated fact rather than two rows a consumer has to reconcile
    — and rather than a silent choice between them."""
    secs = discover_sections(constitution_article_region(FIXTURE, "XIV"))
    ck("the doubled number appears once", [s["number"] for s in secs] == ["1", "2", "3"])
    ck("...and the entry records how many times the page prints it",
       [s.get("prints") for s in secs] == [2, None, 2])
    ck("a number printed once records no count to explain",
       "prints" not in secs[1])


def _proof_every_rule_that_can_skip_a_section_fires(ck):
    """THE FIVE WAYS A SECTION IS NOT PUBLISHED, each watched failing — and the count is
    the point: an ALLOWLIST is only an allowlist if every rule in it is here. A section is
    published because its slice passed all five, never because it failed no known-bad one.

    None of these says the section does not exist. CONTEXT.md's overriding rule is that
    "could not check" is never reported as "is not there", and a slice this ingest could
    not take is a statement about the slice."""
    title = "Duties of Secretary of State"
    good = ("Section 2. Duties of Secretary of State. The Secretary of State shall keep a "
            "fair record of the official acts of the Legislative Assembly, and Executive "
            "Branch; and shall when required lay the same before either chamber.")

    def rule_for(text, number="2", sec_title=title):
        skip = why_not_publishable(text, number, sec_title)
        return skip.rule if skip else "(published)"

    ck("a good slice is published", rule_for(good) == "(published)")
    ck("[no-body] a section the page prints no body for",
       rule_for("") == "no-body")
    ck("[too-short] a slice with text under its leadline, but not enough to be the section",
       rule_for("Section 2. Duties of Secretary of State. Ibid. [Constitution of 1859]")
       == "too-short")
    ck("[mis-anchored] a slice that starts in another section",
       rule_for(good.replace("Section 2.", "Section 3.")) == "mis-anchored")
    ck("[mis-anchored] a slice whose heading is right and whose text is not",
       rule_for("Section 2. The Governor shall nominate judges and commissioners of "
                "every court in this state, subject to confirmation by the Senate, and "
                "shall commission all officers of this state. " * 2) == "mis-anchored")
    ck("[history-only] a repealed section, printed as leadline and history only",
       rule_for("Section 2a. County manager form of government. [Created through H.J.R. "
                "3, 1943, and adopted by the people Nov. 7, 1944; Repeal proposed by "
                "H.J.R. 22, 1957, and adopted by the people Nov. 4, 1958]", "2a",
                "County manager form of government") == "history-only")


def _proof_a_one_sentence_section_is_published(ck):
    """THE FLOOR IS MEASURED IN THE SECTION'S OWN TEXT, NOT IN THE LENGTH OF THE SLICE, and
    that is #195's correction to a threshold copied out of `ingest_ors.py`.

    An ORS section is never 100 characters long. A constitutional one is: "All elections
    shall be free and equal." is the whole of Article II section 1, and Article I sections 17
    and 30 and Article V section 10 are the same shape. Refusing a slice under 120 characters
    refused FOUR real sections of the Oregon Constitution — three of them in the Bill of
    Rights — with a reason that said the slice was too small to be the section's text when it
    was the entire section.

    MEASURED ACROSS THE DOCUMENT rather than argued: of the 381 section headings the page
    prints, 40 have NO letters outside their leadline, their history brackets and the
    Legislative Counsel notes that follow them, and every one of those 40 is a repealed or
    superseded print. The next smallest carries 31. The floor sits in that gap."""
    free = ("Section 1. Elections free. All elections shall be free and equal.\u2014")
    ck("a one-sentence section is published",
       why_not_publishable(free, "1", "Elections free") is None)
    ck("...and the whole of it is 66 characters",
       len(free) < 120 and constitution_section_body_chars(free, "1") >= 8)
    ck("a slice with a letter or two under its leadline is still refused",
       why_not_publishable("Section 1. Elections free. Ibid. [Constitution of 1859]", "1",
                           "Elections free").rule == "too-short")


def _proof_a_repealed_section_whose_only_text_is_a_counsel_note_is_refused(ck):
    """THE NOTE IS NOT THE SECTION'S TEXT. The page prints Legislative Counsel notes between
    sections — 57 of them — and a slice runs from one section heading to the next, so a note
    lands inside the preceding section's slice.

    For a live section that is the page's own adjacent text and it is mirrored as printed.
    For a REPEALED one it is the only thing between the history bracket and the next heading,
    and counting it as body text publishes a section that was repealed as though it had a
    body: `Or. Const. Art. I, sec. 36` would have carried the 1914 capital-punishment
    section's leadline, its repeal bracket, and an editorial note about there having been two
    section 36s — under a heading saying it was the section's full text. Four sections
    measured in that state (Art. I sec. 36, Art. IV sec. 1a, Art. VIII sec. 6, Art. XI sec.
    11f); all four are repealed."""
    repealed = ("Section 6. Qualifications of electors at school elections. [Created through "
                "initiative petition filed June 25, 1948, and adopted by the people Nov. 2, "
                "1948; Repeal proposed by H.J.R. 4, 2007, and adopted by the people Nov. 4, "
                "2008] Note: The leadline to section 6 was a part of the measure proposed by "
                "initiative petition filed June 25, 1948.")
    ck("the note is not counted as the section's body",
       constitution_section_body_chars(repealed, "6") == 0)
    ck("...so the section is refused, and for being repealed rather than for being short",
       why_not_publishable(repealed, "6",
                           "Qualifications of electors at school elections").rule
       == "history-only")
    live = ("Section 46. Prohibition on denial or abridgment of rights on account of sex. "
            "Equality of rights under the law shall not be denied or abridged by the State "
            "of Oregon or by any political subdivision on account of sex. Note: See notes "
            "under section 42 of this Article.")
    ck("a live section followed by a note is still published",
       why_not_publishable(live, "46", "Prohibition on denial or abridgment of rights on "
                                       "account of sex") is None)


def _proof_a_bare_redesignation_entry_is_refused(ck):
    """ARTICLE V SECTION 15, which is a heading and a bracket and NO LEADLINE AT ALL —
    "Section 15. [This section of the Constitution of 1859 was redesignated as section 15b
    …]". The leadline cut has to stop at the bracket: reading through it consumed
    "[This section … proposed by S.J.R. " and left the rest of the bracket standing as
    twenty-four letters of apparent body text, which is a repealed entry published as a
    section."""
    bare = ("Section 15. [This section of the Constitution of 1859 was redesignated as "
            "section 15b by the amendment proposed by S.J.R. 12, 1915, and adopted by the "
            "people Nov. 7, 1916]")
    ck("nothing survives the bracket", constitution_section_body_chars(bare, "15") == 0)
    ck("...so it is refused as printed history, not published as a section",
       why_not_publishable(bare, "15", "").rule == "history-only")


def _proof_a_doubled_number_takes_the_title_of_the_print_that_is_sliced(ck):
    """THE TITLE AND THE TEXT MUST COME FROM THE SAME PRINT, for the numbers no contents
    list carries. Reading the FIRST print's leadline beside whichever print holds text makes
    `anchored()` cross-check two different sections against each other, and the document
    would carry a heading naming one section over the text of another.

    SYNTHETIC, AND SAID TO BE. The 2024 edition has no instance of this: eight of its nine
    doubled section numbers are in their article's contents list, which supplies the title
    and never reaches `_printed_title`, and the ninth — Article I section 36, whose two
    prints really are headed "Liquor prohibition" and "Capital punishment abolished" — has
    two REPEALED prints, so the operative print is the first one and both readings agree.
    The rule is right by coincidence on the document as it stands, which is the kind of rule
    that goes wrong without anybody noticing, so it is watched failing here instead."""
    region = constitution_article_region(FIXTURE, "XIV")
    secs = discover_sections(region)
    one = next(s for s in secs if s["number"] == "1")
    ck("the two prints really are headed differently",
       leadline(region[region.index("Section 1."):], "1")
       == "Removal of seat of government")
    ck("the title is read off the print that carries text",
       (one["title"], one["title_source"]) == ("Seat of government", "leadline"))
    slice_text = constitution_section_slice(FIXTURE, "XIV", "1")
    ck("...which is the print the slicer returns",
       leadline(slice_text, "1") == one["title"])
    ck("...so the section is published rather than reported unidentifiable",
       why_not_publishable(slice_text, "1", one["title"], prints=2,
                           prints_with_text=1) is None)


def _proof_the_history_only_rule_reads_the_printed_leadline(ck):
    """THE TWO TITLES ARE DIFFERENT STRINGS, and the history-only rule must not assume they
    are the same length. It measures what is left after the leadline and the history bracket
    are removed; cutting `len(title)` characters instead of matching the leadline shifted
    that window by the difference, in both directions:

      * a contents-list title LONGER than the printed leadline ate real text, and a live
        section came out looking like a repealed one — skipped, with a note saying the page
        prints no text for a section whose text is right there;
      * a title SHORTER left leadline words in the remainder, which is how a repealed
        section with a long leadline gets published as if it had a body.

    MEASURED, because only one of those two is demonstrably reachable: the false-PUBLISH
    fixture below fails under the arithmetic and passes under the match (watched, by running
    both). The false-SKIP one passes either way and is kept as a regression guard rather than
    dressed up as a proof — `anchored()` gets there first in most of that direction, since a
    title much longer than the leadline carries more words than the leadline can match."""
    live = ("Section 6. County Officers: There shall be elected in each county by the "
            "qualified electors thereof at the time of holding general elections, a county "
            "clerk, treasurer and sheriff who shall severally hold their offices for the "
            "term of four years. [Constitution of 1859]")
    ck("a live section survives a contents-list title longer than its leadline",
       why_not_publishable(live, "6", "County officers' qualifications; location of offices "
                                      "of county and city officers") is None)
    repealed = ("Section 2a. County manager form of government for counties of more than "
                "one hundred thousand inhabitants as determined by the last federal census. "
                "[Created through H.J.R. 3, 1943, and adopted by the people Nov. 7, 1944; "
                "Repeal proposed by H.J.R. 22, 1957, and adopted Nov. 4, 1958]")
    skip = why_not_publishable(repealed, "2a", "County manager")
    ck("a repealed section is still refused when its leadline is longer than its title",
       skip is not None and skip.rule == "history-only")


def _proof_the_catalog_detects_a_document_that_went_missing(ck):
    """CRITERIA 7 AND 10 OF #195, watched failing. The catalog is the list of what SHOULD
    exist, and that claim is only worth something if something reads it back: a document
    deleted from `constitution/` would otherwise be MERELY ABSENT — a citation to it falls
    through to the framework's generic "unresolved", which is the answer a WRONG citation
    gets, and those two must never be the same state (CONTEXT.md, ADR 0005).

    Four disagreements, each made on purpose against a temporary corpus rather than against
    the committed one, and each named apart because they are different kinds of wrong: a
    document gone, a document nothing claims, a document whose bytes a re-run would change,
    and a path that does not match its id."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        entry = next(a for a in discover_articles(FIXTURE) if a["article"] == "VI")
        prov = Provenance(URL, "0" * 64, "fixture", "2026-08-21")
        published, _ = ingest_article(entry, FIXTURE, prov, out)
        ck("the fixture corpus published something to check",
           published == ["orconst-art-vi-sec-1", "orconst-art-vi-sec-2"])
        ck("a sound corpus reports no disagreement",
           check_article(entry, FIXTURE, prov, out) == [])

        (out / "orconst-art-vi-sec-1.md").unlink()
        found = check_article(entry, FIXTURE, prov, out)
        ck("[missing] a deleted document is DETECTED, not merely absent",
           len(found) == 1 and "MISSING" in found[0]
           and "orconst-art-vi-sec-1" in found[0])
        ck("...and the reason says what it costs, in the words a citation would answer in",
           "wrong citation" in found[0])

        (out / "orconst-art-vi-sec-1.md").write_text("not the source's text")
        found = check_article(entry, FIXTURE, prov, out)
        ck("[re-run would rewrite it] bytes that are not what the pipeline produces",
           len(found) == 1 and "differs from what re-rendering" in found[0])

        (out / "orconst-art-vi-sec-99.md").write_text("published by nobody")
        found = check_article(entry, FIXTURE, prov, out, unclaimed=True)
        ck("[unclaimed] a document the catalog says nothing about is found",
           any("NOTHING in the catalog claims it" in f for f in found))

        entry["sections"][0]["path"] = "constitution/orconst-art-vi-sec-2.md"
        ck("[wrong path] a path that does not match the id is reported",
           any("is not the path the id" in f
               for f in check_article(entry, FIXTURE, prov, out)))


def _proof_a_broken_slice_is_reported_and_not_published(ck):
    """END TO END, on a snapshot whose Article VI section 2 has been broken on purpose:
    the ingest must report it and write NOTHING for it, while its neighbour publishes
    normally. A rule that merely returns a reason somewhere inside the loop is not the
    claim being made — the claim is that no document appears."""
    import tempfile
    broken = FIXTURE.replace(
        "Section 2. Duties of Secretary of State. The Secretary of State shall keep a "
        "fair record of the official acts of the Legislative Assembly, and Executive "
        "Branch.", "Section 2. Duties of Secretary of State. [Repealed]")
    ck("the fixture really is broken", broken != FIXTURE)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        entry = next(a for a in discover_articles(broken) if a["article"] == "VI")
        sections = entry["sections"]
        published, skipped = ingest_article(
            entry, broken, Provenance(URL, "0" * 64, "fixture", "2026-08-21"), out)
        ck("the sound section is published", published == ["orconst-art-vi-sec-1"])
        ck("the broken one is reported",
           [(s.number, s.rule) for s in skipped] == [("2", "history-only"),
                                                     ("2a", "history-only")])
        ck("and nothing was written for it",
           not (out / "orconst-art-vi-sec-2.md").exists())
        ck("the catalog records why, not that it is absent",
           all(s["status"] == "not_sliceable" and "not ingested" in s["note"]
               for s in sections if s["number"] in ("2", "2a")))


def _proof_a_changed_section_is_named_and_an_unchanged_one_is_not(ck):
    """CRITERIA 2 AND 3 OF #197, and they are one proof because either alone is worthless.
    The group's signal is ONE sha256 for the whole document, so it says that something moved
    and never what; the value of this report is entirely in the DIFFERENCE, and a report that
    named every section on any change would tell an operator exactly what the hash already
    told them."""
    import tempfile
    amended = FIXTURE.replace(
        "The Secretary of State shall keep a fair record",
        "The Secretary of State shall keep a full and fair record")
    ck("the candidate page really differs from the committed one", amended != FIXTURE)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        catalog = discover_articles(FIXTURE)
        prov = Provenance(URL, "0" * 64, "fixture", "2026-08-21")
        for entry in catalog:
            if entry["sections"]:
                ingest_article(entry, FIXTURE, prov, out)
        rows = section_drift(catalog, FIXTURE, amended)
        reported = [(r.state, r.article, r.section) for r in rows if r.state != UNCHANGED]
        ck("the section whose text moved is named", reported == [(CHANGED, "VI", "2")])
        ck("every other section number was compared and stayed silent",
           len(rows) == sum(len(a["sections"]) for a in catalog))


def _proof_a_section_that_cannot_be_sliced_is_not_a_section_that_was_deleted(ck):
    """CONTEXT.md's OVERRIDING RULE, on the population where breaking it is worst: "could
    not check" is never reported as "is not there". A section this report cannot slice out
    of the candidate page is a section it has nothing to say about — the page's shape moved
    under the slicer — and reporting it as CHANGED would tell an operator that Oregon
    amended a section when what actually happened is that a heading stopped parsing.

    THE NEIGHBOUR IS THE HONEST SECOND HALF. A slice runs heading to heading, so a heading
    that stops matching does not merely lose its own section: its text falls into the
    preceding slice, and THAT section really did change. Both are reported, and they are
    reported as different things."""
    import tempfile
    unparseable = FIXTURE.replace("Section 2. Term of office.", "Secton 2. Term of office.")
    ck("the candidate page really lost that heading", unparseable != FIXTURE)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        catalog = discover_articles(FIXTURE)
        prov = Provenance(URL, "0" * 64, "fixture", "2026-08-21")
        for entry in catalog:
            if entry["sections"]:
                ingest_article(entry, FIXTURE, prov, out)
        rows = {(r.article, r.section): r
                for r in section_drift(catalog, FIXTURE, unparseable)}
        gone = rows[("V", "2")]
        ck("[no slice] the section the candidate page will not yield is UNCHECKABLE",
           gone.state == UNCHECKABLE and gone.reason == NO_SLICE)
        ck("...and it is never reported as changed, which would claim an amendment",
           gone.state != CHANGED)
        ck("...and the reason says what it is not", "deleted" in gone.detail)
        ck("the neighbour whose slice swallowed it IS reported as changed",
           rows[("V", "1")].state == CHANGED)
        ck("and no other section number is reported",
           sorted(k for k, r in rows.items() if r.state != UNCHANGED)
           == [("V", "1"), ("V", "2")])


def _proof_a_section_with_no_baseline_is_reported_as_such(ck):
    """THE OTHER DIRECTION, and it is not the same finding. The committed snapshot is the
    baseline, so a catalog entry the committed page does not print has nothing to be
    compared against — the mirror's own record and the page it was built from disagree, and
    that is a statement about this corpus rather than about Oregon law. It must not read as
    `unchanged`, which is what comparing "" to "" would have said."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        catalog = discover_articles(FIXTURE)
        prov = Provenance(URL, "0" * 64, "fixture", "2026-08-21")
        for entry in catalog:
            if entry["sections"]:
                ingest_article(entry, FIXTURE, prov, out)
        vi = next(a for a in catalog if a["article"] == "VI")
        vi["sections"].append({"number": "99", "title": "Never printed",
                               "title_source": "leadline", "status": "not_sliceable"})
        rows = {(r.article, r.section): r
                for r in section_drift(catalog, FIXTURE, FIXTURE)}
        ck("[no baseline] a catalog entry the committed page does not print is UNCHECKABLE",
           rows[("VI", "99")].state == UNCHECKABLE
           and rows[("VI", "99")].reason == NO_BASELINE)
        ck("...and comparing nothing to nothing is not reported as unchanged",
           rows[("VI", "99")].state != UNCHANGED)


def _proof_a_mirror_that_is_not_there_refuses_to_report(ck):
    """THE HALF THAT IS NOT ABOUT THE PAGE, and the reason this report reads the committed
    DOCUMENTS as well as the committed snapshot. Run against a `constitution/` that is not
    there, every section compares equal — the two snapshots are still the two snapshots —
    and the report is a clean bill of health for documents that do not exist. That is the
    worse half of CONTEXT.md's rule, on the population where it costs most, and it is the
    same refusal `link_enabling_authority.py --check` makes for the same reason (ADR 0005).

    The catalog says WHICH documents should be there; the filesystem never gets to define
    the population, or a mirror wiped to nothing would look like a mirror with nothing to
    check."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        catalog = discover_articles(FIXTURE)
        prov = Provenance(URL, "0" * 64, "fixture", "2026-08-21")
        for entry in catalog:
            if entry["sections"]:
                ingest_article(entry, FIXTURE, prov, out)
        ck("a whole mirror has nothing to refuse over",
           missing_documents(catalog, out) == [])
        (out / "orconst-art-vi-sec-1.md").unlink()
        ck("a document the catalog claims and the mirror does not carry is found",
           missing_documents(catalog, out) == ["orconst-art-vi-sec-1"])
        for doc in out.glob("orconst-*.md"):
            doc.unlink()
        ck("an empty mirror is every claimed document, not an empty population",
           len(missing_documents(catalog, out))
           == sum(1 for a in catalog for s in a["sections"] if s["status"] == "ingested"))


def _proof_an_unchanged_page_reports_nothing(ck):
    """A DRIFT REPORT THAT ALWAYS FIRES IS NOT A DRIFT REPORT, and this is the half most
    easily "passed" by a check that cannot tell a changed section from an unchanged one.
    The proof above shows one section named; this one shows the same comparison silent on
    a page that did not move — over EVERY section number, not a sampled one, and against a
    mirror that carries every document the catalog claims.

    Watched failing: with `_compare` returning CHANGED unconditionally, this reports every
    one of the fixture's section numbers where it must report none."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        catalog = discover_articles(FIXTURE)
        prov = Provenance(URL, "0" * 64, "fixture", "2026-08-21")
        for entry in catalog:
            if entry["sections"]:
                ingest_article(entry, FIXTURE, prov, out)
        rows = section_drift(catalog, FIXTURE, FIXTURE)
        ck("the same page compared against itself reports NOTHING",
           [r for r in rows if r.state != UNCHANGED] == [])
        ck("...and it got there by comparing every section number, not by skipping them",
           len(rows) == sum(len(a["sections"]) for a in catalog) and len(rows) > 0)
        ck("...against a mirror that carries every document the catalog claims",
           missing_documents(catalog, out) == [])


def _proof_an_undated_page_is_refused(ck):
    """The FIFTH rule, and the only one that refuses a whole run rather than a section:
    the page states which constitution it is publishing ("…as it is in effect following
    the approval of amendments and revisions on November 5, 2024"), and that sentence is
    every document's `source_version`. Read from the snapshot rather than typed into this
    file, because it moves on its own schedule — the general election. If the sentence is
    not there, this ingest cannot say WHEN the text it copied was the text, and a mirror
    of law that cannot date itself is not one this repo publishes."""
    dated = ws_only("The Constitution is here published as it is in effect following the "
                    "approval of amendments and revisions on November 5, 2024. " + FIXTURE)
    ck("the edition is read verbatim from the page",
       edition(dated) == "in effect following the approval of amendments and revisions "
                         "on November 5, 2024")
    ck("a page that does not state its edition yields nothing to date the mirror with",
       edition(FIXTURE) == "")


_PROOFS = [_proof_an_article_is_found_by_its_whole_designation,
           _proof_a_section_number_printed_twice_resolves_to_the_one_in_force,
           _proof_two_prints_both_carrying_text_are_refused,
           _proof_the_id_shape_round_trips,
           _proof_a_one_sentence_section_is_published,
           _proof_a_repealed_section_whose_only_text_is_a_counsel_note_is_refused,
           _proof_a_bare_redesignation_entry_is_refused,
           _proof_a_doubled_number_takes_the_title_of_the_print_that_is_sliced,
           _proof_the_history_only_rule_reads_the_printed_leadline,
           _proof_an_undated_page_is_refused,
           _proof_a_slice_is_this_article_s_section_and_nothing_else,
           _proof_the_catalog_is_discovered_from_the_source,
           _proof_the_article_catalog_is_the_pages_own_headings,
           _proof_a_section_number_may_carry_an_uppercase_letter,
           _proof_a_section_number_the_page_prints_twice_is_one_catalog_entry,
           _proof_every_rule_that_can_skip_a_section_fires,
           _proof_a_broken_slice_is_reported_and_not_published,
           _proof_the_catalog_detects_a_document_that_went_missing,
           _proof_a_changed_section_is_named_and_an_unchanged_one_is_not,
           _proof_a_section_that_cannot_be_sliced_is_not_a_section_that_was_deleted,
           _proof_a_section_with_no_baseline_is_reported_as_such,
           _proof_a_mirror_that_is_not_there_refuses_to_report,
           _proof_an_unchanged_page_reports_nothing]


def selftest() -> int:
    # ONE tally, printed by Checks.report() rather than by a copy of it: "a selftest whose
    # scaffolding is copied is one where the copies drift" (repo_lib.Checks).
    ck = Checks()
    for proof in _PROOFS:
        proof(ck)
    return ck.report(f"constitution ingest selftest ({len(_PROOFS)} proofs)")


if __name__ == "__main__":
    main()
