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
from repo_lib import REPO_ROOT, orconst_id, yaml_load

from corpus_toolkit.mcp.framework import register_scheme

ORS_C = re.compile(r"(?:ORS\s*)?(\d{2,3}[A-Za-z]?\.\d{3})\s*$", re.I)
OAR_RULE_C = re.compile(r"(?:OAR\s*)?(\d{3}-\d{3}-\d{4})\s*$", re.I)
OAR_DIV_C = re.compile(r"(?:OAR\s*)?(\d{3}-\d{3})\s*$", re.I)
EO_C = re.compile(r"(?:EO|Executive\s+Order)\s*(?:No\.?\s*)?(?:20)?(\d{2})-(\d{1,2})\s*$", re.I)
NUMS_C = re.compile(r"(?:DAS|policy|statewide policy|OAM)?\s*([\d]{2,3}[.\-][\d]{3}[.\-][\d]{2,4})\s*$", re.I)

ORS_DISPOSITION_PATH = REPO_ROOT / "_meta/catalog/ors-disposition.yml"

_RENUM = None
_ORS_DISPOSITION = None


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
# THE CASE FLAG IS IN THE PATTERN STRING, NOT THE compile() CALL. register_scheme takes
# `OR_CONST_C.pattern` — the string — and compiles it itself, so a flag passed to
# re.compile here reaches this module's own uses and NOT the resolver the MCP server runs.
# Measured: with `re.I` passed as an argument, `Or. Const. Art. VI, sec. 1` matched here and
# came back from resolve_citation as "no citation scheme recognized this format". The same
# trap is set for ORS_C/OAR_*/EO_C/NUMS_C above, which all pass re.I the losing way;
# reported, not fixed here.
OR_CONST_C = re.compile(
    r"(?i)\b(?:Or|Ore|Oregon)\.?\s*Const(?:itution)?\.?,?\s*"
    r"Art(?:icle)?\.?\s*([IVXL]+(?:-[A-Z])?)\s*,?\s*"
    r"(?:§|Sec(?:tion|t|\.)?)\s*\.?\s*(\d+[a-z]?)\s*$")

CONSTITUTION_CATALOG_PATH = REPO_ROOT / "_meta/catalog/constitution.yml"


# The id shape lives in repo_lib beside the regex that parses it back into an article and
# a section number, because that parse is what the snapshot slicer runs on.
or_const_id = orconst_id

_CONSTITUTION = None


def _constitution_catalog():
    """{ARTICLE: catalog entry} — the sections the SOURCE PAGE prints for each article this
    corpus has mirrored, with the status each one ended in. It is what lets an unresolved
    constitutional citation say which of three things happened, instead of one blank."""
    global _CONSTITUTION
    if _CONSTITUTION is None:
        cat = {}
        if CONSTITUTION_CATALOG_PATH.exists():
            cat = yaml_load(CONSTITUTION_CATALOG_PATH.read_text()) or {}
        _CONSTITUTION = {a["article"].upper(): a for a in cat.get("articles", [])}
    return _CONSTITUTION


def _resolve_or_const(m):
    """THREE ANSWERS, WHICH MAY NEVER BE COLLAPSED INTO ONE (CONTEXT.md).

      * the section is mirrored          -> its id
      * the article is not mirrored yet  -> nothing, and says so (#195)
      * the article IS mirrored and the page prints no such section -> nothing, and says
        THAT, which is the only one of the three that is a claim about the Constitution
      * the page prints it and this corpus did not publish it -> nothing, and the reason
        the catalog recorded

    A partial mirror is exactly the state ADR 0005 warned makes "not found" ambiguous, so
    while it lasts the ambiguity is answered in words rather than left to be inferred."""
    article, section = m.group(1).upper(), m.group(2).lower()
    cid = orconst_id(article, section)
    catalog = _constitution_catalog()
    entry = catalog.get(article)
    if entry is None:
        held = ", ".join(f"Article {a}" for a in catalog) or "no article of it"
        return [], (f"Article {article} of the Oregon Constitution is not mirrored in "
                    f"this corpus yet — it mirrors {held} (ADR 0005; the rest is #195). "
                    f"That is a statement about this corpus's coverage, and it is not "
                    f"evidence about Or. Const. Art. {article}, sec. {section} either way.")
    sec = next((s for s in entry["sections"] if str(s["number"]).lower() == section), None)
    if sec is None:
        printed = ", ".join(str(s["number"]) for s in entry["sections"])
        return [], (f"Article {article} is mirrored from the source page section by "
                    f"section, and the page prints no section {section} in it — the "
                    f"sections it prints are {printed}. This citation matches none of "
                    f"them, and it is not read as a near miss for any of them.")
    if sec.get("status") != "ingested":
        why = str(sec.get("note", "no reason recorded")).rstrip(". ")
        return [], (f"Or. Const. Art. {article}, sec. {section} is printed by the source "
                    f"page and was not published by this corpus: {why}. It is in "
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

for _name, _rx in (("federal-cfr", _F_CFR), ("federal-public-law", _F_PL),
                   ("federal-irs-pub", _F_IRS), ("federal-cjis", _F_CJIS)):
    register_scheme(_name, _rx.pattern,
                    # m.string, NOT m.group(0). group(0) is only the substring the
                    # instrument pattern matched, so `IRS Pub 1075 (Rev. 09-2016)` arrived
                    # here as `IRS Pub 1075` -- the revision was stripped before the id
                    # function could see it, and the citation resolved to whichever revision
                    # federal-reference happens to hold. The whole citation must reach it.
                    resolver=lambda m: _federal_ids(m.string),
                    corpus="federal-reference")


register_scheme("ors", ORS_C.pattern, resolver=_resolve_ors)
# Before the ORS/OAR/EO schemes would not matter — no constitutional citation contains a
# NNN.NNN, a NNN-NNN-NNNN or an EO number — but registered beside them because it is the
# same kind of thing: this corpus's own legal-citation formats, in one place.
register_scheme("or-const", OR_CONST_C.pattern, resolver=_resolve_or_const)
register_scheme("oar-rule", OAR_RULE_C.pattern, resolver=_resolve_oar_rule)
register_scheme("eo", EO_C.pattern, resolver=_resolve_eo)
register_scheme("oar-division", OAR_DIV_C.pattern, resolver=_resolve_oar_div)
register_scheme("das-oam-number", NUMS_C.pattern, resolver=_resolve_nums)


# ------------------------------------------------------------------------ selftest
def _selftest() -> int:
    """The constitutional scheme's own proofs: what it matches, what id it builds, and —
    the half that matters most — what it says when it resolves to nothing."""
    from repo_lib import Checks
    ck = Checks()

    def resolve(citation):
        m = OR_CONST_C.search(citation.strip())
        if not m:
            return None, "no scheme matched"
        out = _resolve_or_const(m)
        return out if isinstance(out, tuple) else (out, None)

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
    # pattern that answered them would answer confidently and wrongly.
    for other in ("Article VI, section 1", "ORS 183.310", "OAR 125-800-0020",
                  "Art. VI, sec. 1", "U.S. Const. Art. VI, sec. 1"):
        ck(f"{other!r} is not this corpus's constitutional citation",
           resolve(other)[0] is None or other.startswith("U.S."))

    # THE REGRESSION GUARD for the flag trap above: register_scheme compiles the pattern
    # STRING, so this is the regex the MCP server actually runs. Tested here rather than
    # assumed, because the failure is silent — the citation comes back as a format no
    # scheme recognized, which reads as "this corpus does not do constitutional citations".
    ck("the pattern the framework compiles is the one this module tests",
       re.compile(OR_CONST_C.pattern).search("or. const. art. vi, sec. 1") is not None)

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

    ids, note = resolve("Or. Const. Art. IV, sec. 1")
    ck("an article nobody has mirrored yet resolves to nothing", ids == [])
    ck("...and says it is not mirrored, which is not the same as absent",
       note is not None and "not mirrored" in note and "#195" in note)
    return ck.report("citation-schemes selftest")


if __name__ == "__main__":
    import sys as _s
    if "--selftest" not in _s.argv[1:]:
        print("usage: python3 src/citation_schemes.py --selftest", file=_s.stderr)
        _s.exit(2)
    _s.exit(_selftest())
