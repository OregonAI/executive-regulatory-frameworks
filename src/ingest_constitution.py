#!/usr/bin/env python3
"""Oregon Constitution ingestion — one article at a time (ADR 0005, #194).

  python3 src/ingest_constitution.py --catalog VI      # discover VI's sections
  python3 src/ingest_constitution.py --ingest VI       # publish them
  python3 src/ingest_constitution.py --selftest        # every skip rule, failing

THE SOURCE IS ONE PAGE. The Constitution is published at oregonlegislature.gov as a
SINGLE HTML page carrying all 18 articles, so this is one source entry, one URL, one
sha256 and one snapshot (`oregon-constitution`) — against ors.yml's 545 chapter sources.
Everything else is slicing, and the slicing is `repo_lib.snapshot_slice`: the same
function `corpus-verify-provenance` calls through the `snapshot_slice_module` plugin, so
what was ingested and what is verified cannot diverge.

Shaped after src/ingest_ors.py, which does the same thing per ORS chapter."""
import argparse
import re
import sys
from collections import namedtuple
from datetime import date
from pathlib import Path

import yaml

from html_to_text import html_to_text
from ingest_lib import fetch, flow_to_lines, output_dir_for
from repo_lib import (ORCONST_ID_RE, REPO_ROOT, SNAPSHOT_DIR, Checks,
                      constitution_article_region, hash_snapshot, normalize_ws, orconst_id,
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

# The shortest slice this ingest will publish. Same threshold as ingest_ors.py: below it
# there is not enough text for the document to be the source's text rather than a stub.
MIN_SLICE = 120


def contents_list(region: str) -> dict:
    """{number: title} from the article's own contents list — the `Sec. 1. …` block the
    page prints under each article heading, before the first section body.

    It is NOT the section list (see discover_sections): repealed sections are dropped
    from it, and its wording drifts from the body's own leadline — Article VI's section 9
    is listed as "Vacancies OF county…" and printed as "Vacancies IN county…". Both facts
    are why it is used for titles and never for membership."""
    body = re.search(r"Section \d+[a-z]?\. ", region)
    chunk = region[:body.start()] if body else region
    sec = re.search(r"\bSec\.\s+", chunk)
    if not sec:
        return {}
    return {m.group(1): m.group(2).strip()
            for m in re.finditer(r"(\d+[a-z]?)\.\s+(.*?)(?=\s+\d+[a-z]?\.\s|\s*$)",
                                 chunk[sec.end():])}


def leadline(slice_text: str, number: str) -> str:
    """A section's own leadline, read off the front of its text: everything between
    `Section 9a. ` and the punctuation that closes it.

    Both terminators are real in Article VI — section 6 reads "County Officers:" where
    every other section ends its leadline with a period. Legislative Counsel supplies the
    leadlines ("Unless otherwise specifically noted, the leadlines for the sections have
    been supplied by Legislative Counsel"), which is why the contents list is preferred
    where it has one: neither is the constitutional text itself."""
    m = re.match(rf"Section {re.escape(number)}\.\s+(.*?)[.:](?:\s|$)", slice_text)
    return m.group(1).strip() if m else ""


def discover_sections(norm_text: str, article: str) -> list:
    """Every section ONE ARTICLE'S BODY PRINTS, in the order it prints them.

    The body is the denominator, not the contents list: Article VI's section 9a is
    repealed, so the list omits it while the page still prints its leadline and the
    measures that created and repealed it. A catalog built from the list would make a
    section nobody has looked at look like a section the source does not carry, which is
    the one thing this repo's catalogs may not do."""
    region = constitution_article_region(norm_text, article)
    listed = contents_list(region)
    out = []
    for m in re.finditer(r"Section (\d+[a-z]?)\. ", region):
        number = m.group(1)
        title = listed.get(number)
        out.append({"number": number,
                    "title": title or leadline(region[m.start():], number),
                    "title_source": "contents-list" if title else "leadline"})
    return out


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
    "too-short": "the slice is {length} characters, under the {min} this ingest will "
                 "publish — too little to be the section's text; not ingested",
    "mis-anchored": "the slice does not begin with 'Section {number}.' or shares no "
                    "wording with the title the page lists for it, so it is not known to "
                    "be this section's text; not ingested",
    "history-only": "the page prints this section's leadline and its legislative history "
                    "bracket and no text between them (the shape of a repealed section); "
                    "there is no text to mirror, so it is not ingested",
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


def why_not_publishable(slice_text: str, number: str, title: str):
    """The rule that refuses to publish this slice, or None if every rule passed.

    AN ALLOWLIST. A section is published because its slice satisfied all four rules, not
    because it failed none of a list of known-bad shapes."""
    def skip(rule, **fmt):
        return Skip(number, rule, _SKIP_REASONS[rule].format(number=number, **fmt))

    if not slice_text:
        return skip("no-body")
    if len(slice_text) < MIN_SLICE:
        return skip("too-short", length=len(slice_text), min=MIN_SLICE)
    if not anchored(slice_text, number, title):
        return skip("mis-anchored")
    # What is left of the slice once its OWN PRINTED leadline and every bracketed
    # legislative-history note are removed. A repealed section is printed as exactly those
    # two things.
    #
    # THE LEADLINE IS CUT BY MATCHING IT, not by counting `len(title)` characters off the
    # front: `title` is the CONTENTS LIST's wording, which this file documents as differing
    # from the printed one — "County Officers" against "County Officers:", "Vacancies OF"
    # against "Vacancies IN". Every character of difference shifted the window, so a title
    # longer than the leadline ate real text (a section wrongly skipped) and a shorter one
    # left leadline words in the remainder (a repealed section wrongly published). Article
    # VI's lengths happen to line up; #195's seventeen articles are where that runs out.
    rest = re.sub(rf"^Section {re.escape(number)}\.\s+.*?[.:](?:\s|$)", "", slice_text)
    rest = re.sub(r"\[[^\]]*\]", "", rest)
    if len(re.sub(r"[^A-Za-z]", "", rest)) < 40:
        return skip("history-only")
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
last_verified: "{today}"
verified_by: "@morficflux"
maintainer: "@morficflux"
relationships:
  implements: []
  implemented_by: []
  references_external: []
  related: []
  supersedes: []
tags: ["constitution", "article-{article.lower()}"]
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


def ingest_article(article, sections, raw_text, prov, out_dir):
    """Publish every section of `article` whose slice passes every rule; report the rest.

    Mutates each catalog section in place with the status it ended in — `ingested` and a
    path, or `not_sliceable` and the reason it was not. Returns (published ids, skips)."""
    art_title = article_title(raw_text, article)
    published, skipped = [], []
    for sec in sections:
        doc_id = orconst_id(article, sec["number"])
        # THE SAME ENTRY POINT verify_provenance reaches through the snapshot_slice_module
        # plugin, called with the same arguments. Ingesting through a private helper would
        # let the text this publishes and the text CI checks it against drift apart.
        slice_text = snapshot_slice(doc_id, SNAP_ID, raw_text)
        skip = why_not_publishable(slice_text, sec["number"], sec["title"])
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


def article_title(norm_text: str, article: str) -> str:
    """An article's own name — "ADMINISTRATIVE DEPARTMENT" — from the line under its
    heading, in the page's own capitalization."""
    region = constitution_article_region(norm_text, article)
    m = re.match(rf"ARTICLE {re.escape(article)}\s+(.*?)\s+(?:Sec\.|Section )", region)
    return m.group(1).strip() if m else ""


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


def cmd_catalog(articles):
    """Discover each article's sections FROM THE SOURCE and record them, keeping the
    status of any section already ingested."""
    raw_text, _, fetched = snapshot()
    norm = ws_only(raw_text)
    cat = load_catalog()
    cat["retrieved"] = retrieved_date(cat, fetched)
    cat["source_version"] = edition(norm)
    if not cat["source_version"]:
        print(f"{SNAP_ID}: the page does not state which edition it publishes; "
              f"refusing to catalog an undated mirror", file=sys.stderr)
        return 1
    by_article = {a["article"]: a for a in cat["articles"]}
    for article in articles:
        found = discover_sections(norm, article)
        if not found:
            print(f"Article {article}: no section bodies found on the page", file=sys.stderr)
            return 1
        known = {s["number"]: s for s in by_article.get(article, {}).get("sections", [])}
        for sec in found:
            sec.update({k: v for k, v in known.get(sec["number"], {}).items()
                        if k in ("status", "path", "note")})
        by_article[article] = {"article": article,
                               "title": article_title(norm, article),
                               # The date of the PAGE this list was read off, not of the
                               # run that read it: re-reading the same committed snapshot
                               # a year later discovers the same sections from the same
                               # bytes, and a moving date here would say otherwise.
                               "discovered": cat["retrieved"], "sections": found}
        listed = len(contents_list(constitution_article_region(norm, article)))
        print(f"Article {article} ({by_article[article]['title']}): {len(found)} section "
              f"bodies on the page, {listed} listed in its contents list")
    cat["articles"] = [by_article[a] for a in sorted(by_article, key=_article_sort_key)]
    write_catalog(cat)
    return 0


def _article_sort_key(article: str):
    """Articles in the order the page prints them, which is roman-numeral order with the
    lettered suffixes (XI-A … XI-Q) following their parent."""
    roman = {"I": 1, "V": 5, "X": 10, "L": 50}
    base, _, suffix = article.partition("-")
    total, prev = 0, 0
    for ch in reversed(base):
        v = roman.get(ch, 0)
        total += -v if v < prev else v
        prev = max(prev, v)
    return (total, suffix)


def cmd_ingest(articles):
    raw_text, sha, fetched = snapshot()
    cat = load_catalog()
    cat["retrieved"] = retrieved_date(cat, fetched)
    by_article = {a["article"]: a for a in cat["articles"]}
    if not GROUP.exists():
        print(f"{GROUP.relative_to(REPO_ROOT)} does not exist. The group's cadence and the "
              f"date its clock starts are decisions a human makes (ADR 0005); this ingest "
              f"maintains the sha256 in it and nothing else.", file=sys.stderr)
        return 1
    OUT.mkdir(exist_ok=True)
    prov = Provenance(URL, sha, cat["source_version"], cat["retrieved"])
    rc = 0
    for article in articles:
        if article not in by_article:
            print(f"Article {article}: not in {CATALOG.relative_to(REPO_ROOT)} — run "
                  f"--catalog {article} first", file=sys.stderr)
            rc = 1
            continue
        entry = by_article[article]
        published, skipped = ingest_article(article, entry["sections"], raw_text, prov, OUT)
        print(f"Article {article}: published {len(published)} of "
              f"{len(entry['sections'])} section(s) the page prints")
        for s in skipped:
            print(f"  SKIPPED sec. {s.number} [{s.rule}]: {s.reason}")
    write_catalog(cat)

    group = yaml.safe_load(GROUP.read_text())
    for src in group["sources"]:
        if src["id"] == SNAP_ID:
            src["sha256"] = sha
            src["last_checked"] = cat["retrieved"]
    GROUP.write_text(yaml.safe_dump(group, sort_keys=False, allow_unicode=True, width=110))
    write_index(cat)
    return rc


def write_index(cat):
    lines = ["# Oregon Constitution — index", "",
             "Sections of the Oregon Constitution, full text per section, sliced from the",
             "single page the Legislature publishes the whole document on",
             f"({cat['source_version']}).",
             "**Non-authoritative copies** — the official text is the one published by the",
             "Legislative Counsel Committee.", "",
             "| Article | Title | Sections on the page | Published |", "|---|---|---|---|"]
    tot = [0, 0]
    for a in cat["articles"]:
        n = len(a["sections"])
        i = sum(1 for s in a["sections"] if s.get("status") == "ingested")
        tot[0] += n
        tot[1] += i
        lines.append(f"| {a['article']} | {a['title']} | {n} | {i} |")
    lines += [f"| **all** | | **{tot[0]}** | **{tot[1]}** |", "",
              "Only the articles listed above are mirrored; the rest of the document is",
              "not yet ingested (#195), which is not a statement that those articles have",
              "no sections. Per-section numbers/titles/paths:",
              "[`_meta/catalog/constitution.yml`](../_meta/catalog/constitution.yml).",
              "Sections marked `not_sliceable` there are sections the page prints that this",
              "ingest did not publish, each with the reason recorded beside it.", ""]
    (OUT / "_index.md").write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--catalog", nargs="+", metavar="ARTICLE", default=[])
    ap.add_argument("--ingest", nargs="+", metavar="ARTICLE", default=[])
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if args.catalog:
        sys.exit(cmd_catalog(args.catalog))
    if args.ingest:
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
Section 1. Courts. The judicial power of the state shall be vested in one supreme court.
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


def _proof_the_id_shape_round_trips(ck):
    """The id is the join between three things — the file the ingest writes, the candidate
    the citation scheme resolves to, and the coordinates the SLICER parses back out of it.
    A shape that cannot be parsed back would publish documents whose provenance could not
    be verified, since verify_provenance reaches the slice through the id alone."""
    for article, section in (("VI", "1"), ("VI", "9a"), ("XI-A", "3"), ("XVIII", "10")):
        doc_id = orconst_id(article, section)
        m = ORCONST_ID_RE.match(doc_id)
        ck(f"{doc_id} parses back to Article {article}, section {section}",
           bool(m) and m.group(1).upper() == article and m.group(2) == section)


def _proof_the_catalog_is_discovered_from_the_source(ck):
    """WHAT THE DENOMINATOR IS. The section list comes from the article's own BODY —
    every `Section N.` heading it prints — and not from the contents list above it, which
    omits repealed sections (Article VI's section 9a is in the body and not in the list).
    A catalog built from the contents list would leave a section this corpus never looked
    at indistinguishable from one the source does not carry.

    The title still comes from the contents list where there is one, because that makes
    the anchoring check in `anchored()` a cross-check between two independently printed
    parts of the page rather than a comparison of the body with itself."""
    secs = discover_sections(FIXTURE, "VI")
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


def _proof_every_rule_that_can_skip_a_section_fires(ck):
    """THE FOUR WAYS A SECTION IS NOT PUBLISHED, each watched failing. An ALLOWLIST: a
    section is published because its slice passed every rule, never because it failed no
    known-bad one.

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
    ck("[too-short] a slice too small to be the section's text",
       rule_for("Section 2. Duties of Secretary of State. See below.") == "too-short")
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
        sections = discover_sections(broken, "VI")
        published, skipped = ingest_article(
            "VI", sections, broken, Provenance(URL, "0" * 64, "fixture", "2026-08-21"), out)
        ck("the sound section is published", published == ["orconst-art-vi-sec-1"])
        ck("the broken one is reported",
           [(s.number, s.rule) for s in skipped] == [("2", "too-short"),
                                                     ("2a", "history-only")])
        ck("and nothing was written for it",
           not (out / "orconst-art-vi-sec-2.md").exists())
        ck("the catalog records why, not that it is absent",
           all(s["status"] == "not_sliceable" and "not ingested" in s["note"]
               for s in sections if s["number"] in ("2", "2a")))


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


_PROOFS = [_proof_the_id_shape_round_trips,
           _proof_the_history_only_rule_reads_the_printed_leadline,
           _proof_an_undated_page_is_refused,
           _proof_a_slice_is_this_article_s_section_and_nothing_else,
           _proof_the_catalog_is_discovered_from_the_source,
           _proof_every_rule_that_can_skip_a_section_fires,
           _proof_a_broken_slice_is_reported_and_not_published]


def selftest() -> int:
    # ONE tally, printed by Checks.report() rather than by a copy of it: "a selftest whose
    # scaffolding is copied is one where the copies drift" (repo_lib.Checks).
    ck = Checks()
    for proof in _PROOFS:
        proof(ck)
    return ck.report(f"constitution ingest selftest ({len(_PROOFS)} proofs)")


if __name__ == "__main__":
    main()
