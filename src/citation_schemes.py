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
from repo_lib import REPO_ROOT, yaml_load

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
                    "agency files a housekeeping correction). Mechanically mined from "
                    "the chapter's own legislative-history bracket, not an authoritative "
                    "disposition table — verify against oregonlegislature.gov.")
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
register_scheme("ors", ORS_C.pattern, resolver=_resolve_ors)
register_scheme("oar-rule", OAR_RULE_C.pattern, resolver=_resolve_oar_rule)
register_scheme("eo", EO_C.pattern, resolver=_resolve_eo)
register_scheme("oar-division", OAR_DIV_C.pattern, resolver=_resolve_oar_div)
register_scheme("das-oam-number", NUMS_C.pattern, resolver=_resolve_nums)
