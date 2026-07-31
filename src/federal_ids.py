"""Citation -> federal-reference document id. THE CROSS-CORPUS CONTRACT.

A sibling corpus resolves into federal-reference by EXACT ID LOOKUP against its published
`corpus-index.json`, whose rows are `[title, doc_type, path]` — no version, no status, no
search. So a sibling can only reach a document whose id it can derive from the citation
string alone, knowing nothing about what federal-reference holds.

That makes this file a contract rather than a convenience. It is PURE: no filesystem, no
corpus contents, no network. Copy it verbatim into any corpus that cites federal
instruments; both sides then compute the same ids by construction instead of by agreement.

WHY IT EXISTS. The public laws originally shipped as `pl-113-128-wioa`. Nothing in
federal-reference noticed, because its own scheme built its lookup table FROM the held ids
and so was circular — it could always find them. But no sibling can guess `-wioa` from
"Pub. L. 113-128", so those documents were unreachable from every other corpus on the
platform, silently. This function is the non-circular definition that makes that a test
failure instead of a discovery.

VERSIONS RIDE IN THE ID ON PURPOSE. `cjis-sp-6-1` encodes 6.1, so a citation to 5.9.4
derives `cjis-sp-5-9-4`, which is simply absent from the index — a correct miss with no
version knowledge needed on the citing side, and one that starts resolving by itself if
5.9.4 is ever ingested. The alternative, mapping every CJIS citation onto whatever version
is held, is the substitution this platform exists to refuse.
"""
from __future__ import annotations

import re

# `2 CFR 200`, `2 C.F.R. § 200.303`, `2 CFR Part 200.303`
CFR = re.compile(r"\b(?P<title>\d{1,2})\s*C\.?\s?F\.?\s?R\.?\s*(?:Part\s+)?§{0,2}\s*"
                 r"(?P<part>\d{1,4})(?:\.(?P<sec>\d{1,4}))?\b", re.I)
# `Pub. L. 113-128`, `Public Law No. 115-224`, `PL 113-128`
PUBLAW = re.compile(r"\bP(?:ub(?:lic)?)?\.?\s*L(?:aw)?\.?\s*(?:No\.?\s*)?"
                    r"(?P<cong>\d{2,3})\s*[-–]\s*(?P<num>\d{1,4})\b", re.I)
# `200.331-200.333`, `200.510 through 200.512`, en/em dashes included.
RANGE = re.compile(r"200\.(\d{1,4})\s*(?:-|–|—|to|through|thru)\s*(?:200\.)?(\d{1,4})\b", re.I)
# A citation spanning more of the part than this is a drafting artefact, not a real range;
# expanding it would flood the caller with ids rather than answer the question.
MAX_RANGE = 60
# A section continuing a list: the `, 200.303` in "2 CFR 200.302, 200.303". Requires a list
# separator immediately before it, so `2 CFR 200.303 and ORS 200.055` does NOT pull the ORS
# section in -- the intervening "ORS" breaks the match, which a bare `200\.\d+` would not.
LIST_SEC = re.compile(r"(?:,|;|\band\b|&)\s*§{0,2}\s*200\.(\d{1,4})\b", re.I)

# `IRS Pub 1075`, `IRS Publication 1075 (Rev. 11-2021)`, `IRS Pub 1075 Revision 9/2016`
IRSPUB = re.compile(r"\bIRS\s+Pub(?:lication)?\.?\s*(?P<num>\d{3,4})\b", re.I)
# The revision, read from anywhere in the citation rather than from a group that had to sit
# immediately after the number. Case-insensitive and notation-tolerant on purpose.
IRS_REV = re.compile(r"\b(?:rev(?:ision)?\.?\s*)?(\d{1,2})\s*[-/]\s*(\d{4})\b", re.I)
# `CJIS Security Policy 6.1`, `CJIS SP v5.9.4`
CJIS = re.compile(r"\bCJIS(?:\s+Security)?(?:\s+Policy|\s+SP)?\.?\s*"
                  r"(?:v(?:ersion)?\.?\s*)?(?P<ver>\d+(?:\.\d+){0,2})?", re.I)


def candidates(citation: str) -> list[str]:
    """Document ids a citation could name, most specific first. Never empty-guesses.

    Returns [] when the string names nothing this scheme understands. Returning an id is
    NOT a claim the document exists — that is the index lookup's job, and keeping the two
    separate is what lets an unheld instrument come back as an honest miss.
    """
    c = (citation or "").strip()
    if not c:
        return []

    hits = list(CFR.finditer(c))
    if hits:
        base = f"{hits[0].group('title')}-cfr-{hits[0].group('part')}"
        secs: list[str] = []
        for m in hits:
            if m.group("sec"):
                secs.append(m.group("sec"))
        if not secs:
            return [base]

        # RANGES AND LISTS. `2 CFR 200.331-200.333` used to resolve to .331 alone, silently
        # dropping two sections this corpus holds; `200.510 through 200.512` and
        # `200.302, 200.303` behaved the same way. finditer collects every section NAMED, and
        # a range expands to every section BETWEEN its endpoints -- safe to do here because
        # returning an id is explicitly not a claim that the document exists. The index
        # lookup is the existence test, so a gap in CFR numbering simply misses.
        secs.extend(LIST_SEC.findall(c))
        for a, b in RANGE.findall(c):
            lo, hi = int(a), int(b)
            if 0 < hi - lo <= MAX_RANGE:
                secs.extend(str(n) for n in range(lo, hi + 1))

        # NO BARE-PART FALLBACK. Offering the part after the section looks helpful and is the
        # one place this file can hand back a plausible wrong answer: a sibling cannot tell
        # "section exists but was not split out" from "section was REMOVED in 2021" or "no
        # such section", because the index carries no status -- so `2 CFR 200.56` and
        # `2 CFR 200.9999` both resolved to the CURRENT part text. federal-reference's own
        # resolver keeps the fallback, because it reads frontmatter and CAN tell the cases
        # apart; a sibling gets an honest miss instead.
        seen, out = set(), []
        for sec in secs:
            i = f"{base}.{sec}"
            if i not in seen:
                seen.add(i)
                out.append(i)
        return out

    m = PUBLAW.search(c)
    if m:
        return [f"pl-{m.group('cong')}-{m.group('num')}"]

    m = IRSPUB.search(c)
    if m:
        rev = IRS_REV.search(c)
        # SAME RULE AS CJIS BELOW, and it was missing here. The id is the only place a
        # sibling can see a version: index rows are [title, doc_type, path]. Without the
        # revision in the id, `IRS Pub 1075 (Rev. 09-2016)` derived `irs-pub-1075` and hit
        # the 11-2021 document exactly -- federal-reference refused that citation while both
        # citing corpora answered it.
        if rev:
            return [f"irs-pub-{m.group('num')}-{rev.group(1).zfill(2)}-{rev.group(2)}"]
        # No revision named -> no candidate, rather than a guess at whichever revision
        # happens to be held. federal-reference's own resolver still answers these; it can
        # read the frontmatter, and a sibling cannot.
        return []

    m = CJIS.search(c)
    if m:
        ver = m.group("ver")
        # No version named -> no candidate. Guessing a version here would hand back whatever
        # happens to be held, which is exactly the wrong answer this corpus refuses. An
        # unversioned CJIS reference is answered by federal-reference's own resolver, not by
        # a sibling silently picking one.
        return [f"cjis-sp-{ver.replace('.', '-')}"] if ver else []

    return []
