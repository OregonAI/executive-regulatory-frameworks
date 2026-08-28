"""citation_module (corpus.yml: plugins.citation_module) — registers this
corpus's citation formats with the toolkit's resolve_citation dispatcher.
Ported from the old src/mcp_lib.py's ORS_C/OAR_RULE_C/OAR_DIV_C/EO_C/NUMS_C
regex + OAR renumbering-map lookup + ORS repealed-disposition annotation —
none of this generalizes to other corpora, so it lives here rather than in
the toolkit (see corpus_toolkit's MIGRATION.md)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from link_graph import build_renumber_map
from repo_lib import (ORCONST_ARTICLE_TOKEN, ORCONST_SECTION_TOKEN, REPO_ROOT,
                      orconst_article_designation, orconst_article_slug, orconst_id,
                      yaml_load)

from corpus_toolkit.mcp.framework import register_scheme

ORS_C = re.compile(r"(?:ORS\s*)?(\d{2,3}[A-Za-z]?\.\d{3})\s*$", re.I)
OAR_RULE_C = re.compile(r"(?:OAR\s*)?(\d{3}-\d{3}-\d{4})\s*$", re.I)
OAR_DIV_C = re.compile(r"(?:OAR\s*)?(\d{3}-\d{3})\s*$", re.I)
EO_C = re.compile(r"(?:EO|Executive\s+Order)\s*(?:No\.?\s*)?(?:20)?(\d{2})-(\d{1,2})\s*$", re.I)
NUMS_C = re.compile(r"(?:DAS|policy|statewide policy|OAM)?\s*([\d]{2,3}[.\-][\d]{3}[.\-][\d]{2,4})\s*$", re.I)

ORS_DISPOSITION_PATH = REPO_ROOT / "_meta/catalog/ors-disposition.yml"
ORS_SOURCES_PATH = REPO_ROOT / "_meta/sources/ors.yml"
ORS_CATALOG_PATH = REPO_ROOT / "_meta/catalog/ors.yml"

_RENUM = None
_ORS_DISPOSITION = None
_ORS_MIRRORED_CHAPTERS = None
_ORS_CATALOG_CHAPTERS = None

_ORS_CHAPTER_RE = re.compile(r"^(\d+[a-z]?)\.")


def _renumber(rule):
    global _RENUM
    if _RENUM is None:
        _RENUM = build_renumber_map()[0]
    return _RENUM.get(rule, rule)


def _ors_disposition(section):
    global _ORS_DISPOSITION
    if _ORS_DISPOSITION is None:
        _ORS_DISPOSITION = {}
        if ORS_DISPOSITION_PATH.exists():
            cat = yaml_load(ORS_DISPOSITION_PATH.read_text())
            _ORS_DISPOSITION = {s["section"]: s for s in cat.get("sections", [])}
    return _ORS_DISPOSITION.get(section)


def ors_mirrored_chapters():
    """Every chapter number this corpus has actually selected and ingested — the `ors`
    source group's own sources, which is the ground truth `ingest_ors.py` reads and writes
    (CONTEXT.md's Ingest status, one level up: a CHAPTER selected, not a document held).
    Lowercased, so '45A' and '45a' are the same key a citation's own lowercased chapter
    can look up."""
    global _ORS_MIRRORED_CHAPTERS
    if _ORS_MIRRORED_CHAPTERS is None:
        chapters = set()
        if ORS_SOURCES_PATH.exists():
            group = yaml_load(ORS_SOURCES_PATH.read_text()) or {}
            for s in group.get("sources", []):
                m = re.match(r"ors-chapter-(\w+)$", str(s.get("id", "")))
                if m:
                    chapters.add(m.group(1).lower())
        _ORS_MIRRORED_CHAPTERS = chapters
    return _ORS_MIRRORED_CHAPTERS


def ors_catalog_chapters():
    """{chapter number: title} for every chapter `_meta/catalog/ors.yml`'s discovery map
    knows about — a live scrape of oregonlegislature.gov's chapter pages, NOT a complete
    enumeration of Oregon's ORS numbering space (the catalog's own note: "relevant to
    DAS/executive-branch administration"). A chapter appearing here, mirrored or not, is
    POSITIVE evidence it is real — Oregon's own chapter page was fetched and titled. A
    chapter's absence here is never evidence it is NOT real; the catalog was never asked
    about most of the numbering space, so silence from it answers nothing."""
    global _ORS_CATALOG_CHAPTERS
    if _ORS_CATALOG_CHAPTERS is None:
        out = {}
        if ORS_CATALOG_PATH.exists():
            cat = yaml_load(ORS_CATALOG_PATH.read_text()) or {}
            for c in cat.get("chapters", []):
                out[str(c.get("chapter", "")).lower()] = c.get("title", "")
        _ORS_CATALOG_CHAPTERS = out
    return _ORS_CATALOG_CHAPTERS


def _ors_chapter_absence_note(chapter: str):
    """#210. TWO ANSWERS, and they must never collapse into one: a chapter this corpus
    chose not to ingest is a coverage gap and a claim about THIS MIRROR; a chapter number
    nothing here can corroborate is neither confirmed real nor confirmed bogus, and is
    reported as exactly that rather than guessed either way (AGENTS.md: "could not check"
    is never reported as "is not there"). `None` when the chapter IS mirrored — the
    citation names a real, wrong, or renumbered SECTION instead, which is a different
    question this function does not answer."""
    if chapter in ors_mirrored_chapters():
        return None
    title = ors_catalog_chapters().get(chapter)
    if title is not None:
        named = f" ({title})" if title else ""
        return (f"this corpus does not mirror ORS chapter {chapter}{named}. It is a real "
                f"chapter — recorded in _meta/catalog/ors.yml's discovery map, scraped "
                f"from oregonlegislature.gov — that was not selected for ingestion; this "
                f"is a coverage gap, not a citation to nothing.")
    return (f"this corpus does not mirror ORS chapter {chapter}, and cannot tell whether "
            f"it is a real, un-ingested chapter or not a chapter Oregon uses. "
            f"_meta/catalog/ors.yml's discovery map — the only source of positive "
            f"evidence this corpus keeps — is scoped to chapters relevant to "
            f"DAS/executive-branch administration and was never asked about this one, so "
            f"its silence proves nothing either way. Reported as unmirrored, not guessed.")


_MINED_CAVEAT = ("Mechanically mined from the chapter's own legislative-history "
                 "bracket, not an authoritative disposition table — verify against "
                 "oregonlegislature.gov.")


def _follow_renumbering(section, disp, hops_left=5):
    """Walk a renumbered section to where its text lives NOW. The disposition table
    records one hop per row (verbatim source_phrase each); a section renumbered twice
    chains. Cycle- and depth-guarded; multi-target rows return every target and choose
    none (the table's own rule)."""
    targets = disp.get("targets") or []
    if not targets or hops_left <= 0:
        return targets
    out = []
    for tgt in targets:
        nxt = _ors_disposition(str(tgt).lower())
        if nxt and nxt.get("status") == "renumbered" and str(tgt) != section:
            out.extend(x for x in _follow_renumbering(str(tgt).lower(), nxt, hops_left - 1)
                       if x not in out)
        elif tgt not in out:
            out.append(tgt)
    return out


def _resolve_ors(m, nodes):
    section = m.group(1).lower()
    cid = f"ors-{section}"
    if cid in nodes:
        return [cid]
    disp = _ors_disposition(section)
    if disp and disp.get("status") == "repealed":
        return [], (f"ORS {section} was repealed in {disp['year']} — no current text "
                    "exists. Citing rules/policies may not have been updated since "
                    "(this is legally normal in Oregon; a rule stays valid until the "
                    "agency files a housekeeping correction). " + _MINED_CAVEAT)
    if disp and disp.get("status") == "renumbered":
        # THE ISSUE #90 CASE: county code (and old state policy) cites the law as it
        # stood when adopted, and the state renumbers underneath it. A bare miss here
        # read as a coverage gap in this corpus when the text exists under a new number
        # — 7,936 mined renumberings sat unconsulted while this returned nothing.
        finals = _follow_renumbering(section, disp)
        held = [f"ors-{str(t).lower()}" for t in finals
                if f"ors-{str(t).lower()}" in nodes]
        where = " and ".join(f"ORS {t}" for t in finals) or "an unrecorded destination"
        note = (f"ORS {section} was renumbered in {disp.get('year', '?')} "
                f"(source: '{disp.get('source_phrase', '')}'); the current section is "
                f"{where}. " +
                ("Returning the current text. " if held else
                 "The destination is not held in this corpus. ") + _MINED_CAVEAT)
        return held, note
    # #210: neither repealed nor renumbered explains the miss, so before falling through
    # to "no such document exists" — the answer a genuinely WRONG citation earns — check
    # whether the miss is explained one level up, at the CHAPTER: a citation into a
    # chapter this corpus never selected for ingestion is a stated ABSENCE, never the
    # generic unresolved answer, and the two must not read alike (CONTEXT.md).
    m2 = _ORS_CHAPTER_RE.match(section)
    if m2:
        note = _ors_chapter_absence_note(m2.group(1))
        if note is not None:
            return [], note
    return [cid]


# ---------------------------------------------------------------- the Oregon Constitution
#
# `Or. Const. Art. VI, sec. 1` — the form Oregon courts, the ORS annotations and this
# corpus's own documents use (ADR 0005; 751 documents cite the Constitution). Registered
# because until now the layer at the top of the authority chain had no citation scheme at
# all: the string matched nothing, and resolve_citation answered "no citation scheme
# recognized this format" about the instrument every statute in this corpus hangs from.
#
# WHAT IT REFUSES IS THE POINT. The 'Or. Const.' token is REQUIRED — a bare
# "Article VI, section 1" is a citation to some article of something, and matching it would
# make this scheme answer for contracts, charters and other states' constitutions. `\b`
# before `Or` is what keeps `ColORado Const.` out.
#
# The id is the citation, token for token: Art. VI, sec. 9a -> orconst-art-vi-sec-9a. The
# article keeps its roman numeral and the section keeps its letter, because both are how
# the source prints them and how a reader would write them back.
#
# THE ARTICLE HALF IS `repo_lib.ORCONST_ARTICLE_TOKEN`, NOT A SECOND SPELLING OF IT. It
# carries the parenthetical, because Oregon's citation does: `Art. VII (Amended), sec. 1`
# and `Art. VII (Original), sec. 1` are two operative articles and two documents, and the
# page prints no bare ARTICLE VII at all. The same declaration builds
# `catalog_agencies.AUTHORITY_FORMS`' constitutional form — see
# `article_form_disagreements` below for what that fixes and what gates it.
#
# #202, FIXED FOR ALL SIX SCHEMES, NOT WORKED AROUND FOR THIS ONE. `register_scheme` used
# to be handed `OR_CONST_C.pattern` — the STRING — which the toolkit compiled itself with
# no flags, so `re.I` passed here reached this module's own uses and NOT the resolver the
# MCP server runs. Measured, before the fix: `Or. Const. Art. VI, sec. 1` matched here and
# came back from resolve_citation as "no citation scheme recognized this format". This
# scheme used to carry an inline `(?i)` in the pattern string as a one-off workaround —
# ORS_C/OAR_*/EO_C/NUMS_C above did not, and sat broken (most visibly `eo`, since its
# `EO`/`Executive Order` token is mandatory rather than optional).
#
# THE ACTUAL FIX IS IN THE REGISTRATION CALL, not the pattern: `register_scheme` accepts
# either a string (compiled fresh, no flags) or an already-compiled pattern used AS GIVEN,
# flags and all (corpus-toolkit#134, released in the v1.31.1 this corpus pins). Every
# `register_scheme(...)` call below now passes the compiled object — `OR_CONST_C`, not
# `OR_CONST_C.pattern` — so `re.I` on the object IS what the server runs, and a workaround
# baked into one pattern's source text cannot be the only thing standing between this and
# the same silent miss on whichever scheme is edited next.
# `_proof_flagged_schemes_survive_registration` gates it end-to-end, for every scheme that
# declares a flag, not just this one.
OR_CONST_C = re.compile(
    r"\b(?:Or|Ore|Oregon)\.?\s*Const(?:itution)?\.?,?\s*"
    rf"Art(?:icle)?\.?\s*({ORCONST_ARTICLE_TOKEN})\s*,?\s*"
    rf"(?:§|Sec(?:tion|t|\.)?)\s*\.?\s*({ORCONST_SECTION_TOKEN})\.?\s*$", re.I)

CONSTITUTION_CATALOG_PATH = REPO_ROOT / "_meta/catalog/constitution.yml"


_CONSTITUTION = None


def _constitution_catalog():
    """{article slug: catalog entry} — the sections the SOURCE PAGE prints for each article,
    with the status each one ended in. It is what lets an unresolved constitutional citation
    say which of several things happened instead of one blank.

    KEYED ON THE SLUG, which is the article's identity: `VII (Amended)` and `VII (Original)`
    are different keys because they are different articles, and the case a citation happens
    to be written in cannot reach this dictionary.

    A DESIGNATION THE PAGE PRINTS TWICE IS ONE KEY. `ARTICLE XI-A` is printed as the repealed
    1916 RURAL CREDITS article and as the article in force; the print carrying sections is
    the one a citation to `Art. XI-A` can mean, and it is the one kept here — the same rule
    `repo_lib.constitution_article_region` applies, so the resolver and the slicer cannot
    disagree about which article a citation names."""
    global _CONSTITUTION
    if _CONSTITUTION is None:
        cat = {}
        if CONSTITUTION_CATALOG_PATH.exists():
            cat = yaml_load(CONSTITUTION_CATALOG_PATH.read_text()) or {}
        out = {}
        for a in cat.get("articles", []):
            key = orconst_article_slug(a["article"])
            if key not in out or (a.get("sections") and not out[key].get("sections")):
                out[key] = a
        _CONSTITUTION = out
    return _CONSTITUTION


def _designations_sharing(slug: str) -> list:
    """Every article the catalog holds whose slug extends `slug` — what a citation that
    omits the parenthetical could have meant. `vii` -> VII (Amended), VII (Original)."""
    prefix = slug + "-"
    return [a["article"] for key, a in _constitution_catalog().items()
            if key.startswith(prefix)]


def _resolve_or_const(m):
    """FIVE ANSWERS, WHICH MAY NEVER BE COLLAPSED INTO ONE (CONTEXT.md).

      * the section is mirrored                    -> its id
      * the citation names an article by a numeral the page prints only WITH a parenthetical
        -> nothing, and says which two it could be, because choosing would be a guess
      * the page prints no such article             -> nothing, and says THAT
      * the article is on the page and carries no sections (a repealed article, printed as
        its heading and its repeal bracket) -> nothing, and says that
      * the page prints the section and this corpus did not publish it -> nothing, and the
        reason the catalog recorded

    Only the middle three are claims about the Constitution; the last is a claim about this
    corpus, and the two are never worded alike."""
    slug = orconst_article_slug(m.group(1))
    section = m.group(2).lower()
    cid = orconst_id(m.group(1), section)
    entry = _constitution_catalog().get(slug)
    if entry is None:
        # `Art. VII, sec. 1` — the numeral is real and names two articles, because the page
        # prints ARTICLE VII only as `(Amended)` and `(Original)`. Answering with either
        # would be a coin flip between two operative articles with different text.
        sharing = _designations_sharing(slug)
        if sharing:
            forms = " and ".join(f"Or. Const. Art. {d}, sec. {section}" for d in sharing)
            return [], (f"The Oregon Constitution has no Article {m.group(1)} on its own — "
                        f"the page prints that numeral {len(sharing)} times, as "
                        + ", ".join(f"Article {d}" for d in sharing) +
                        f", and every one of them is operative. This citation names none of "
                        f"them: write {forms}. Choosing one would be a guess between "
                        f"articles with different text.")
        held = len(_constitution_catalog())
        return [], (f"The source page prints no Article {m.group(1)} of the Oregon "
                    f"Constitution. This corpus mirrors the whole document — all {held} "
                    f"article designations the page carries (ADR 0005) — so this is a "
                    f"statement about the Constitution and not about the corpus's coverage.")
    if entry.get("status") == "not_mirrored":
        why = str(entry.get("note", "no reason recorded")).rstrip(". ")
        return [], (f"Article {entry['article']} ({entry['title']}) is printed on the source "
                    f"page and carries no sections: {why}. It is in "
                    f"_meta/catalog/constitution.yml with that reason beside it.")
    sec = next((s for s in entry["sections"] if str(s["number"]).lower() == section), None)
    if sec is None:
        printed = ", ".join(str(s["number"]) for s in entry["sections"])
        return [], (f"Article {entry['article']} is mirrored from the source page section by "
                    f"section, and the page prints no section {section} in it — the "
                    f"sections it prints are {printed}. This citation matches none of "
                    f"them, and it is not read as a near miss for any of them.")
    if sec.get("status") != "ingested":
        why = str(sec.get("note", "no reason recorded")).rstrip(". ")
        return [], (f"Or. Const. Art. {entry['article']}, sec. {sec['number']} is printed by "
                    f"the source page and was not published by this corpus: {why}. It is in "
                    f"_meta/catalog/constitution.yml with that reason beside it.")
    return [cid]


def _resolve_oar_rule(m, nodes):
    served = _renumber(m.group(1))
    cid = f"oar-{served}"
    if served != m.group(1):
        return [cid], f"OAR {m.group(1)} was renumbered; current rule is {served}"
    return [cid]


def _resolve_eo(m, nodes):
    return [f"eo-{m.group(1)}-{int(m.group(2)):02d}"]


def _resolve_oar_div(m, nodes):
    div = m.group(1)
    return sorted(i for i in nodes if i.startswith(f"oar-{div}-"))


def _resolve_nums(m, nodes):
    num = m.group(1).replace(".", "-")
    return sorted(i for i in nodes if i in (f"das-{num}", f"oam-{num}", f"das-{num}_pr"))


# Registration order mirrors the old if/elif priority: first pattern to MATCH wins
# (regardless of whether it then resolves to an existing document), NUMS_C tried
# only if none of the legal-citation patterns matched at all.
# ---------------------------------------------------------------- outbound: federal instruments
#
# MEASURED before declaring: of this corpus's 916 federal authority claims across 1,250
# distinct targets, exactly ONE target resolves -- 2 CFR 200, with 15 authority claims and 39
# mentions. 1.6% of claims, 0.08% of targets. That is small, and it is stated plainly rather
# than dressed up.
#
# It is still worth the edge, because of WHAT those 15 are: 14 Oregon administrative rules
# and one DAS manual declare 2 CFR 200 in `legal_authority` or `statutes_implemented`
# (oar-581-051-0500 and its neighbours, oar-461-135-1230, oam-75-30-02). Those are rules
# whose stated legal basis resolved to nothing at all. The authority chain now terminates in
# the actual requirement instead of stopping at the state border.
#
# The other 901 claims are overwhelmingly CFR titles and U.S. Code sections federal-reference
# does not hold (34 CFR 300 alone has 105). They begin resolving as intake grows, with no
# change here -- which is the point of deriving ids rather than tabulating them.
#
# REGISTERED FIRST, and this ordering is load-bearing -- it also fixes a PRE-EXISTING bug.
#
# ORS_C is `(?:ORS\s*)?(\d{2,3}[A-Za-z]?\.\d{3})\s*$`: the "ORS" is OPTIONAL, so the
# pattern matches any bare NNN.NNN at the end of a string. Registered ahead of these, it
# captured `2 CFR 200.332` and derived `ors-200.332`, and `45 CFR 75.352` -> `ors-75.352`.
# First pattern to MATCH wins whether or not it resolves, so the federal schemes never ran.
#
# That has been happening since before this change; it produced misses rather than wrong
# answers only because no such ORS documents exist. ORS chapter 200 is real, so ingesting
# ORS 200.332 would have turned a federal citation into a confidently wrong STATE statute.
#
# Safe in this order because every federal pattern requires a literal CFR / Pub. L. / IRS
# Pub / CJIS token, which no ORS, OAR or EO citation contains. Verified after the move:
# ORS, OAR and EO citations still resolve locally and unchanged.
import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from federal_ids import CFR as _F_CFR, CJIS as _F_CJIS, IRSPUB as _F_IRS, PUBLAW as _F_PL  # noqa: E402
from federal_ids import candidates as _federal_ids  # noqa: E402

# THE SAME #202 TRAP, measured live here too: all four of CFR/PUBLAW/IRSPUB/CJIS declare
# re.I on the compiled object, and `register_scheme(_name, _rx.pattern, ...)` handed the
# toolkit the pattern STRING, which it compiled itself with no flags -- `2 cfr 200.332`
# matched none of these schemes while `2 CFR 200.332` matched federal-cfr. Fixed the same
# way as the six schemes above: pass `_rx`, the compiled object, not `_rx.pattern`.
for _name, _rx in (("federal-cfr", _F_CFR), ("federal-public-law", _F_PL),
                   ("federal-irs-pub", _F_IRS), ("federal-cjis", _F_CJIS)):
    register_scheme(_name, _rx,
                    # m.string, NOT m.group(0). group(0) is only the substring the
                    # instrument pattern matched, so `IRS Pub 1075 (Rev. 09-2016)` arrived
                    # here as `IRS Pub 1075` -- the revision was stripped before the id
                    # function could see it, and the citation resolved to whichever revision
                    # federal-reference happens to hold. The whole citation must reach it.
                    resolver=lambda m: _federal_ids(m.string),
                    corpus="federal-reference")


register_scheme("ors", ORS_C, resolver=_resolve_ors)
# Before the ORS/OAR/EO schemes would not matter — no constitutional citation contains a
# NNN.NNN, a NNN-NNN-NNNN or an EO number — but registered beside them because it is the
# same kind of thing: this corpus's own legal-citation formats, in one place.
register_scheme("or-const", OR_CONST_C, resolver=_resolve_or_const)
register_scheme("oar-rule", OAR_RULE_C, resolver=_resolve_oar_rule)
register_scheme("eo", EO_C, resolver=_resolve_eo)
register_scheme("oar-division", OAR_DIV_C, resolver=_resolve_oar_div)
register_scheme("das-oam-number", NUMS_C, resolver=_resolve_nums)


# ---------------------------------------------- one declaration, and the gate on it (#195)
#
# TWO FORMS ANSWER "WHAT IS A CONSTITUTIONAL CITATION" IN THIS REPO: the `or-const` scheme
# above, which RESOLVES one, and `catalog_agencies.AUTHORITY_FORMS`, which decides whether a
# registry row may RECORD one as its enabling authority. Until #195 they were two
# hand-maintained answers, and they disagreed in both directions — measured, not feared:
#
#   Or. Const. Art. VII (Amended), sec. 1   scheme REFUSED   form accepted
#   Or. Const. Art. XI-A, sec. 1            scheme accepted  form REFUSED
#   Or. Const. Art. XI-F(1), sec. 1         both refused, and it is a real article
#
# Both now interpolate `repo_lib.ORCONST_ARTICLE_TOKEN`, so the article half is DERIVED and
# not written twice. THE DIRECTION IS FORCED: the token lives beside `orconst_article_slug`,
# because the scheme has to turn the token into a document id and the form only has to
# recognize it — a recognizer can be derived from a parser, and a parser cannot be derived
# from a recognizer. This is #193's fix to `CADENCES` versus the `recheck` enum, in the
# second place the repository stated one fact twice.
#
# The gate below is what makes that survive someone editing one of the two by hand.


def _gate_articles():
    """The article designations the gate runs through both forms.

    DERIVED FROM THE SOURCE DOCUMENT, via the catalog the ingest writes from the page's own
    headings — so an article Oregon adds arrives at this gate without anyone remembering to
    add it. The refusals are fixed, because they are shapes the page does not print and no
    catalog will ever supply."""
    # NO FALLBACK LIST. An empty catalog means the gate has nothing to compare, and a
    # hardcoded stand-in would let it report agreement about one designation as agreement
    # about the document. `article_form_disagreements` raises on it instead, because this
    # function is public and a silently narrowed gate is worse than a loud broken one.
    accept = sorted(a["article"] for a in _constitution_catalog().values())
    if not accept:
        raise RuntimeError(
            f"{CONSTITUTION_CATALOG_PATH.relative_to(REPO_ROOT)} holds no articles, so "
            f"there is nothing to run through both citation forms. That is a gate with no "
            f"subject, not two forms that agree.")
    # Not a designation the page prints, and not a spelling either form may quietly take: a
    # letter that is not a roman numeral, a parenthetical that is not one of the two
    # editions, the edition run onto the numeral without the space the citation prints, a
    # lettered article with its letter missing, an arabic numeral, and a two-digit index
    # where the page prints one.
    #
    # NOT IN THIS LIST: spacing and case. The scheme is deliberately tolerant of how a
    # document writes a citation (`Or Const Art VI sec 1`) and AUTHORITY_FORMS is
    # deliberately exact about what a registry row may hold, so `Art. VI , sec. 1` is a
    # DECISION the two differ on rather than a drift, and a gate that reported it would be
    # asking them to stop meaning different things.
    refuse = ["Q", "VII (Repealed)", "VII(Amended)", "XI-", "6", "XI-F(10)"]
    return [(d, True) for d in accept] + [(d, False) for d in refuse]


def article_form_disagreements(constitution_form=None) -> list:
    """Every article designation the citation scheme and the enabling-authority form answer
    differently — empty when they agree, which is the state CI requires.

    Compared on the CANONICAL citation only (`Or. Const. Art. <designation>, sec. 1`), not
    on case or spacing variants: the scheme is deliberately tolerant of how a document
    writes a citation and `AUTHORITY_FORMS` is deliberately exact about what a registry row
    may hold, and that difference is a decision rather than a drift.

    `constitution_form` overrides the pattern read from `AUTHORITY_FORMS`, so the gate can
    be watched failing against a form made to disagree."""
    from catalog_agencies import AUTHORITY_FORMS
    form = constitution_form or dict(AUTHORITY_FORMS)["constitution"]
    out = []
    for designation, expected in _gate_articles():
        citation = f"Or. Const. Art. {designation}, sec. 1"
        by_scheme = OR_CONST_C.search(citation) is not None
        by_form = form.fullmatch(citation) is not None
        if by_scheme != by_form:
            out.append(f"{citation!r}: the or-const scheme "
                       f"{'accepts' if by_scheme else 'refuses'} it and AUTHORITY_FORMS "
                       f"{'accepts' if by_form else 'refuses'} it")
        elif by_scheme != expected:
            out.append(f"{citation!r}: both forms "
                       f"{'accept' if by_scheme else 'refuse'} it, and the page "
                       f"{'prints' if expected else 'does not print'} that article")
    return out


# ------------------------------------------------------------------------ selftest
def resolve(citation):
    """(ids, note) for one constitutional citation, or (None, …) when the scheme refuses it.

    The seam every proof below reads through — the pattern AND the resolver, together, which
    is what an agent's `resolve_citation` call reaches. Module level rather than a closure so
    each proof can be read on its own."""
    m = OR_CONST_C.search(citation.strip())
    if not m:
        return None, "no scheme matched"
    out = _resolve_or_const(m)
    return out if isinstance(out, tuple) else (out, None)


def _selftest() -> int:
    """The constitutional scheme's own proofs: what it matches, what id it builds, and —
    the half that matters most — what it says when it resolves to nothing."""
    from repo_lib import Checks
    ck = Checks()

    ids, note = resolve("Or. Const. Art. VI, sec. 1")
    ck("the official citation form resolves to the section's id",
       ids == ["orconst-art-vi-sec-1"])
    for form in ("Or. Const. Art. VI, sec. 1", "Or Const Art VI sec 1",
                 "Oregon Constitution, Article VI, Section 1",
                 "Or. Const. Art. VI, § 1", "or. const. art. vi, sec. 1"):
        got, _ = resolve(form)
        ck(f"form {form!r}", got == ["orconst-art-vi-sec-1"])
    ck("a lettered section and a lettered article keep their letters",
       orconst_id(*OR_CONST_C.search("Or. Const. Art. XI-A, sec. 9a").groups())
       == "orconst-art-xi-a-sec-9a")

    # THE LOOSE-MATCH REFUSALS. Each of these is a citation to something else, and a
    # pattern that answered them would answer confidently and wrongly. `U.S. Const.` is the
    # sharpest: same article and section numbers, a different sovereign.
    for other in ("Article VI, section 1", "ORS 183.310", "OAR 125-800-0020",
                  "Art. VI, sec. 1", "U.S. Const. Art. VI, sec. 1",
                  "Colorado Const. Art. VI, sec. 1", "Or. Const. Art. VI"):
        ck(f"{other!r} is not this corpus's constitutional citation",
           resolve(other)[0] is None)

    ck("a citation ending a sentence still matches",
       resolve("Or. Const. Art. VI, sec. 1.")[0] == ["orconst-art-vi-sec-1"])

    ids, note = resolve("Or. Const. Art. VI, sec. 99")
    ck("a section the source does not print resolves to NOTHING", ids == [])
    ck("...and says the page prints no such section",
       note is not None and "no section 99" in note and "Article VI" in note)
    ck("...and does not fall back to a section that does exist",
       note is not None and "orconst-art-vi-sec-9" not in note)

    ids, note = resolve("Or. Const. Art. VI, sec. 9a")
    ck("a section the source prints and this corpus did not publish resolves to nothing",
       ids == [])
    ck("...and says WHY it is not held, not that it does not exist",
       note is not None and "not published" in note and "does not exist" not in note)

    _proof_the_two_editions_of_article_vii_are_two_documents(ck)
    _proof_an_article_the_page_does_not_print_says_so(ck)
    _proof_every_designation_round_trips_through_its_slug(ck)
    _proof_the_two_forms_accept_the_same_article(ck)
    _proof_the_gate_can_watch_the_two_forms_disagree(ck)
    _proof_a_lost_flag_actually_fails_a_gate(ck)
    fw = _load_framework()
    if fw is not None:
        _proof_registration_stores_the_flag(ck, fw)
        _proof_the_citation_resolves_end_to_end(ck, fw)
        _proof_flagged_schemes_survive_registration(ck, fw)
        _proof_federal_schemes_survive_registration(ck, fw)
        _proof_ors_unmirrored_chapter_states_absence(ck, fw)
    return ck.report("citation-schemes selftest")


def _proof_a_lost_flag_actually_fails_a_gate(ck):
    """CRITERION 3 OF #202: "a scheme whose flag is lost at registration fails a gate,
    watched failing." Everything else in this file asserts real schemes SURVIVE
    registration; none of it demonstrates what happens to one that does not — which is how
    `eo` sat broken while `or-const` alone was fixed, with nothing anywhere failing to say
    so.

    Reproduces the exact mistake this issue is about, through the SAME function every real
    scheme in this module calls — `register_scheme(name, pattern.pattern, ...)`, the
    STRING, not the compiled object — for a throwaway scheme nothing else in this corpus
    will ever match. Runs in `__main__`'s own top-level scope (this function is called
    directly by `_selftest`, before any `CorpusFramework` is built), so the call lands in
    `_SCHEMES`, the toolkit's module-level table, exactly where `register_scheme` puts an
    entry when nothing is collecting for a framework — and what is read back is that
    table's own entry, not a hand-rolled restatement of what registration does."""
    from corpus_toolkit.mcp.framework import _SCHEMES as _tk_schemes
    throwaway = re.compile(r"\bSELFTEST-THROWAWAY-(\d+)\b", re.I)
    register_scheme("citation-schemes-selftest-throwaway-lossy", throwaway.pattern,
                    resolver=lambda m: [f"throwaway-{m.group(1)}"])
    entry = next((s for s in _tk_schemes
                 if s[0] == "citation-schemes-selftest-throwaway-lossy"), None)
    ck("the throwaway scheme registered", entry is not None)
    if entry is None:
        return
    stored = entry[1]
    ck("registered the lossy .pattern way, it matches uppercase",
       stored.search("SELFTEST-THROWAWAY-1") is not None)
    ck("...and the SAME check the proofs below make — lower behaves like upper — is FALSE "
       "here: the gate can watch a lost flag fail, and this is that failure, caught",
       (stored.search("selftest-throwaway-1") is not None)
       != (stored.search("SELFTEST-THROWAWAY-1") is not None))


def _proof_the_two_editions_of_article_vii_are_two_documents(ck):
    """CRITERION 2 OF #195. The page prints ARTICLE VII twice, as `(Amended)` and
    `(Original)`, and Oregon courts cite both — amended Article VII holds the judicial power,
    and original Article VII's provisions on courts and jurisdiction survive with the status
    of a statute by the terms of amended section 2. They are different text under the same
    numeral, so they must be different documents, and the parenthetical is what tells them
    apart.

    THE BARE NUMERAL RESOLVES TO NEITHER. There is no ARTICLE VII on the page without a
    parenthetical, so `Or. Const. Art. VII, sec. 1` is a citation to one of two things and
    this scheme says which two rather than picking one."""
    amended, _ = resolve("Or. Const. Art. VII (Amended), sec. 1")
    original, _ = resolve("Or. Const. Art. VII (Original), sec. 1")
    ck("the amended article resolves to its own document",
       amended == ["orconst-art-vii-amended-sec-1"])
    ck("the original article resolves to its own document",
       original == ["orconst-art-vii-original-sec-1"])
    ck("they are not the same document", amended != original)
    ck("and they do not hold the same text",
       (REPO_ROOT / "constitution/orconst-art-vii-amended-sec-1.md").read_text()
       != (REPO_ROOT / "constitution/orconst-art-vii-original-sec-1.md").read_text())
    ids, note = resolve("Or. Const. Art. VII, sec. 1")
    ck("the bare numeral resolves to nothing", ids == [])
    ck("...and names both articles it could have meant",
       note is not None and "VII (Amended)" in note and "VII (Original)" in note)
    ck("...and does not report the section as absent",
       note is not None and "guess" in note and "no section" not in note)
    xi_a, _ = resolve("Or. Const. Art. XI-A, sec. 1")
    ck("a designation the page prints twice resolves against the print carrying sections",
       xi_a == ["orconst-art-xi-a-sec-1"])
    ids, note = resolve("Or. Const. Art. XI-B, sec. 1")
    ck("a repealed article the page still prints resolves to nothing", ids == [])
    ck("...and says the article carries no sections, not that it never existed",
       note is not None and "carries no sections" in note
       and "STATE PAYMENT OF IRRIGATION" in note)


def _proof_an_article_the_page_does_not_print_says_so(ck):
    """THE ANSWER THAT CHANGED WHEN THE MIRROR BECAME WHOLE. While one article of eighteen
    was mirrored, `Or. Const. Art. IV, sec. 1` resolved to nothing and had to say "not
    mirrored yet" — a statement about this corpus that carried no information about Oregon
    law. It now resolves, and a citation to an article the page does not print is a claim
    about the Constitution, which is the ambiguity ADR 0005 said a partial mirror creates."""
    ids, _ = resolve("Or. Const. Art. IV, sec. 1")
    ck("an article that used to be unmirrored now resolves",
       ids == ["orconst-art-iv-sec-1"])
    ids, note = resolve("Or. Const. Art. XX, sec. 1")
    ck("an article the page does not print resolves to nothing", ids == [])
    ck("...and says so about the Constitution, not about this corpus's coverage",
       note is not None and "prints no Article XX" in note
       and "not mirrored" not in note)


def _proof_every_designation_round_trips_through_its_slug(ck):
    """THE OTHER HALF OF ONE DECLARATION. The article shape is stated as a citation TOKEN and
    as an id SLUG, and `orconst_article_slug`/`orconst_article_designation` are the bridge —
    but nothing derives one spelling from the other, so the two could drift and only a
    hand-picked example would notice.

    Run over EVERY designation the catalog holds, which is the page's own list, so the claim
    is about the document rather than about nine examples someone chose. A slug that will not
    parse back is a document whose provenance cannot be verified, since `snapshot_slice`
    reaches the article through the slug alone."""
    designations = sorted(a["article"] for a in _constitution_catalog().values())
    bad = [d for d in designations
           if orconst_article_designation(orconst_article_slug(d)) != d]
    for d in bad:
        print(f"  {d!r} -> {orconst_article_slug(d)!r} -> "
              f"{orconst_article_designation(orconst_article_slug(d))!r}", file=sys.stderr)
    ck("every article designation the page prints round-trips through its slug", bad == [])
    ck("...and the citation token accepts every one of them",
       all(OR_CONST_C.search(f"Or. Const. Art. {d}, sec. 1") for d in designations))
    ck("...and no two designations fold to the same slug",
       len({orconst_article_slug(d) for d in designations}) == len(designations))
    ck("there is a document's worth of them", len(designations) >= 39)


def _proof_the_two_forms_accept_the_same_article(ck):
    """CRITERION 4 OF #195: the citation scheme and the enabling-authority form accept the
    same article token, because both are built from one declaration.

    Run over every designation the catalog holds — 39 on the 2024 edition, ARTICLE VII's two
    editions and the lettered articles included — so this is a claim about the document and
    not about four examples someone chose."""
    disagreements = article_form_disagreements()
    for d in disagreements:
        print("  " + d, file=sys.stderr)
    ck("the two constitutional citation forms agree on every article the page prints",
       disagreements == [])
    accepted = [d for d, ok in _gate_articles() if ok]
    ck("...and there is a document's worth of them to agree about", len(accepted) >= 18)
    ck("the parenthetical editions are among them",
       "VII (Amended)" in accepted and "VII (Original)" in accepted)


def _proof_the_gate_can_watch_the_two_forms_disagree(ck):
    """A GATE NOBODY HAS WATCHED FAIL IS NOT KNOWN TO WORK, and this one guards a fact that
    is invisible when it breaks: a registry row could record an authority no citation in
    this corpus can resolve, or a citation could resolve to a document the registry may not
    name as an authority, and nothing would say so.

    The disagreement is made IN PROCESS, by handing the gate the form as it stood before
    #195 — the article token without its parenthetical and without its lettered suffix,
    which is what `AUTHORITY_FORMS` actually held."""
    before = re.compile(r"Or\. Const\. Art\. [IVXL]+[A-Z]?"
                        r"(?: \((?:Amended|Original)\))?, sec\. \d+[a-z]?")
    caught = article_form_disagreements(constitution_form=before)
    ck("the gate reports a form that has lost the lettered articles", caught != [])
    ck("...and names the article it disagrees about",
       any("XI-A" in c for c in caught))
    ck("...and says which side accepts it",
       all("the or-const scheme" in c and "AUTHORITY_FORMS" in c for c in caught))
    lost_edition = re.compile(r"Or\. Const\. Art\. [IVXL]+(?:-[A-Z](?:\(\d\))?)?, "
                              r"sec\. \d+[a-z]?")
    ck("a form that has lost ARTICLE VII's editions is caught too",
       any("VII (Amended)" in c
           for c in article_form_disagreements(constitution_form=lost_edition)))


def _load_framework():
    """A `CorpusFramework` over this corpus as committed, or `None` with a LOUD skip
    printed to stderr. Shared by every proof below that needs the served path — the seam
    an agent actually calls, not this module's own regex — so the corpus is only loaded
    once per selftest run."""
    try:
        from corpus_toolkit import config as config_mod
        from corpus_toolkit.mcp.framework import CorpusFramework
        return CorpusFramework(config_mod.load(str(REPO_ROOT / "_meta/corpus.yml")))
    except Exception as e:                                     # noqa: BLE001
        print(f"SKIP registration-stores-the-flag, end-to-end resolution, flagged-scheme "
              f"registration and federal-scheme registration: the corpus could not be "
              f"loaded here ({type(e).__name__}: {e}) — NOT a pass, and #202's own gates "
              f"are silently absent from this run", file=sys.stderr)
        return None


def _proof_registration_stores_the_flag(ck, fw):
    """THE REGRESSION GUARD for the flag trap above (#202) — reading what
    `register_scheme("or-const", …)` actually STORED in THIS corpus's own served scheme
    table (`fw.schemes`, the exact list `resolve_citation` iterates), not what the toolkit's
    `_compiled` helper does when handed whatever pattern the test happens to already have.

    That is the guard this replaces. The old version called
    `corpus_toolkit.mcp.framework._compiled("or-const", OR_CONST_C)` directly — handing the
    toolkit the compiled object the test itself picked, rather than reading anything
    registration actually stored — so it could not see a broken registration even in
    principle. Measured on a build where all `register_scheme(...)` calls below were
    reverted to `.pattern` (the pre-fix, lossy form): that old guard's two checks still
    PASSED, in the same run where `resolve_citation("or. const. art. vi, sec. 1")` and four
    other lowercase citations FAILED to resolve. Reading `fw.schemes` instead closes that:
    if `or-const`'s entry there ever lost `re.I`, this fails, because it is reading the same
    table the server reads."""
    entry = next((s for s in fw.schemes if s[0] == "or-const"), None)
    ck("or-const is in the scheme table the framework actually collected",
       entry is not None)
    if entry is None:
        return
    stored = entry[1]
    ck("the stored pattern carries re.I", bool(stored.flags & re.I))
    ck("...so what the served table runs still matches lowercase",
       stored.search("or. const. art. vi, sec. 1") is not None)


def _proof_the_citation_resolves_end_to_end(ck, fw):
    """THE WHOLE WAY THROUGH, against this corpus as committed — the seam an agent actually
    calls, not this module's own regex.

    It belongs in a per-PR gate and not only in the nightly MCP smoke test: the pull request
    that changes a scheme is exactly the one that can break it, and everything above this
    line would still pass while `resolve_citation` answered "no citation scheme recognized
    this format". That is not a hypothetical — it is what a re.I passed to `re.compile`
    instead of written into the pattern did to this scheme while it was being built (#202)."""
    r = fw.resolve_citation("Or. Const. Art. VI, sec. 1")
    ck("resolve_citation returns the document",
       [m["id"] for m in r["matches"]] == ["orconst-art-vi-sec-1"])
    r = fw.resolve_citation("Or. Const. Art. VI, sec. 99")
    ck("resolve_citation returns nothing for a section the page does not print",
       bool(r.get("unresolved")) and not r["matches"])
    ck("...and the reason reaches the caller",
       "no section 99" in (r.get("note") or ""))


def _proof_flagged_schemes_survive_registration(ck, fw):
    """#202, THE WHOLE ISSUE — not just the `or-const` corner of it that #194 happened to
    hit. Every scheme below declares `re.I` on its own compiled pattern, and
    `register_scheme` used to be handed `X_C.pattern` — the STRING — which the toolkit
    compiled itself with no flags. The flag then governed this module's own uses and
    NOTHING the MCP server actually runs.

    Measured on the committed code before this proof existed: of the five affected
    schemes, only `eo` was live-broken, because `ORS_C`/`OAR_RULE_C`/`OAR_DIV_C`/`NUMS_C`
    all make their letter prefix OPTIONAL, so a lowercase prefix is simply skipped rather
    than refused — the digits still match unaided. `EO_C` makes `EO`/`Executive Order`
    MANDATORY, so losing the flag made it case-sensitive for real:
    `resolve_citation("executive order 20-03")` came back "no citation scheme recognized
    this format" while `"EO 20-03"` resolved.

    Every scheme with a flag is asserted here anyway, upper- and lower-case alike, through
    `fw.resolve_citation` — the served path — so a scheme that is unaffected today by luck
    of its pattern shape does not become tomorrow's silent miss the next time someone
    tightens a prefix from optional to required. `or-const` is here too — the one scheme
    whose flag MECHANISM this commit actually changed, from an inline `(?i)` in the pattern
    string to the same compiled-object `re.I` every other scheme carries — so the case this
    proof would most need to catch was, for a while, the one case it skipped.

    `oar-division` and `das-oam-number` expand to every rule id under a prefix, which pins
    this proof to how many rules `rules/101/080/` (or `das-107-004-180`'s procedure sibling)
    happens to hold today — a fact about corpus growth, not about the flag. `expected=None`
    on those two means "matched something", so the case-insensitivity assertion
    (`got_lower == got_upper`) stays the one doing the work; the pinned lists on the other
    four are safe because each resolves one citation to one document, not a division's
    membership."""
    cases = [
        ("ors",            "ORS 183.310",             "ors 183.310",             ["ors-183.310"]),
        ("oar-rule",       "OAR 101-080-0010",         "oar 101-080-0010",        ["oar-101-080-0010"]),
        ("oar-division",   "OAR 101-080",              "oar 101-080",             None),
        ("eo (EO form)",   "EO 20-03",                 "eo 20-03",                ["eo-20-03"]),
        ("eo (spelled)",   "Executive Order 20-03",    "executive order 20-03",   ["eo-20-03"]),
        ("das-oam-number", "DAS 107-004-180",          "das 107-004-180",         None),
        ("or-const",       "Or. Const. Art. VI, sec. 1", "or. const. art. vi, sec. 1",
         ["orconst-art-vi-sec-1"]),
    ]
    for label, upper, lower, expected in cases:
        r_upper = fw.resolve_citation(upper)
        got_upper = sorted(m["id"] for m in r_upper["matches"])
        if expected is None:
            ck(f"{label}: {upper!r} resolves to at least one document",
               got_upper != [])
        else:
            ck(f"{label}: {upper!r} resolves through resolve_citation",
               got_upper == sorted(expected))
        r_lower = fw.resolve_citation(lower)
        got_lower = sorted(m["id"] for m in r_lower["matches"])
        ck(f"{label}: {lower!r} resolves THE SAME WAY through resolve_citation "
           f"— the flag reached the served resolver",
           got_lower == got_upper)


def _proof_ors_unmirrored_chapter_states_absence(ck, fw):
    """#210. A citation to an ORS chapter this corpus never selected for ingestion must
    resolve to a stated ABSENCE ("this corpus does not mirror ORS chapter N") and never to
    the generic "no such document exists" a citation to a genuinely WRONG section — one
    inside a chapter this corpus DOES hold — gets. CONTEXT.md: those are two different
    facts, and before this fix `resolve_citation` answered both identically.

    THREE CASES, measured on the committed corpus rather than assumed:

      * ORS 79.010 -- chapter 79 (Secured Transactions, Former Provisions) is cited by
        this corpus and is not mirrored. It IS a real chapter: `_meta/catalog/ors.yml`'s
        discovery map lists it, scraped from oregonlegislature.gov, just never selected for
        ingestion. This is the coverage-gap case #210 was filed about, generalized past the
        one chapter (151) that happened to get noticed -- re-measured on this corpus, 13
        other chapters share this exact shape (cited, real per the catalog, not mirrored;
        `_meta/catalog/ors-citation-gap.yml`'s `chapters_known_real_not_ingested: 14`
        counts 79 among them).
      * ORS 935.035 -- chapter 935 is cited 62 times across 21 documents (935.035 x41,
        935.040 x21 -- an OAR rule's authority line, apparently a transcription of chapter
        835, is one of them, not the whole of it) and is absent from BOTH the mirrored set
        and the discovery catalog. Nothing here can tell a real, un-ingested chapter apart
        from a typo or a chapter Oregon does not use, and the note says so explicitly
        rather than guessing either way -- regardless of how often it is cited.
      * ORS 151.999 -- chapter 151 IS mirrored (18 sections, landed for this same issue).
        Section .999 does not exist in it. This is the WRONG-citation case, and it must
        keep the answer it already had -- unaffected by the fix above."""
    r = fw.resolve_citation("ORS 151.211")
    ck("ORS 151.211 resolves now that chapter 151 is mirrored",
       [m["id"] for m in r["matches"]] == ["ors-151.211"])

    r = fw.resolve_citation("ORS 79.010")
    ck("a citation to a real, un-mirrored chapter resolves to nothing",
       bool(r.get("unresolved")) and not r["matches"])
    note = r.get("note") or ""
    ck("...and states the absence explicitly, naming the chapter",
       "does not mirror ORS chapter 79" in note)
    ck("...and says it IS a real chapter, backed by the discovery catalog",
       "discovery" in note.lower() and "cannot tell" not in note.lower())
    ck("...and does not read like the generic wrong-citation answer",
       "no such document exists" not in note)

    r = fw.resolve_citation("ORS 935.035")
    ck("a citation to a chapter with no corroborating evidence resolves to nothing",
       bool(r.get("unresolved")) and not r["matches"])
    note = r.get("note") or ""
    ck("...and says explicitly it cannot tell a real un-mirrored chapter from a chapter "
       "number Oregon does not use",
       "does not mirror ORS chapter 935" in note and "cannot tell" in note.lower())
    ck("...and does not fabricate a claim the discovery catalog does not support",
       "discovery" in note.lower())

    r = fw.resolve_citation("ORS 151.999")
    ck("a wrong section inside a chapter this corpus DOES hold keeps the OLD generic "
       "answer, unaffected by the chapter-level fix",
       bool(r.get("unresolved")) and not r["matches"]
       and "no such document exists" in (r.get("note") or ""))


def _proof_federal_schemes_survive_registration(ck, fw):
    """THE SAME #202 TRAP, found by the same measurement one scope over: CFR/PUBLAW/
    IRSPUB/CJIS in the federal-instruments block below also declare `re.I` locally and
    were ALSO registered by `.pattern` — `2 cfr 200.332` matched no scheme while
    `2 CFR 200.332` matched `federal-cfr`. Fixed alongside the six above rather than
    filed separately, since it is the identical one-line cause in the identical file.

    Through `fw._match_schemes` — scheme matching and id derivation, the part the flag
    governs — and not through `resolve_citation` all the way to a match: these candidates
    live in the `federal-reference` sibling corpus, resolved over the network via
    `siblings:` in corpus.yml, which this gate does not have and should not depend on to
    stay green. `_match_schemes` is what `resolve_citation` calls before it ever reaches
    the network, so this still proves the served regex, not this module's own copy of it."""
    cases = [
        ("federal-cfr", "2 CFR 200.332", "2 cfr 200.332"),
        ("federal-public-law", "Pub. L. 111-5", "pub. l. 111-5"),
        # No bare `IRS Pub 1075` here: `federal_ids.candidates` deliberately returns no
        # candidate without a revision (a version this sibling would otherwise have to
        # guess), which would fail this case for a reason that has nothing to do with the
        # flag. The revision makes the id deterministic and the case pure.
        ("federal-irs-pub", "IRS Pub 1075 (Rev. 09-2016)", "irs pub 1075 (rev. 09-2016)"),
        ("federal-cjis", "CJIS Security Policy v5.9", "cjis security policy v5.9"),
    ]
    for scheme, upper, lower in cases:
        _, _, cands_upper, _ = fw._match_schemes(upper)
        ck(f"{scheme}: {upper!r} matches through the served scheme table",
           cands_upper != [])
        _, _, cands_lower, _ = fw._match_schemes(lower)
        ck(f"{scheme}: {lower!r} matches THE SAME WAY — the flag reached the served table",
           cands_lower == cands_upper)


if __name__ == "__main__":
    import sys as _s
    if "--selftest" not in _s.argv[1:]:
        print("usage: python3 src/citation_schemes.py --selftest", file=_s.stderr)
        _s.exit(2)
    _s.exit(_selftest())
