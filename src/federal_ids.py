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

# `42 U.S.C. 1396`, `20 USC 1232g`, `29 USC § 3101`, `42 USC 1320d-2` (the `-2` suffix names a
# DIFFERENT section from `1320d` and must never be dropped -- ADR-0006's first landed section
# makes this scheme resolve for the first time, so a missing suffix group here would silently
# substitute one section of the U.S. Code for another, the exact failure this platform exists
# to refuse. The trailing subsection tail (`(b)(1)(A)`) is matched and ignored: a subsection is
# inside the section, never a different document.
#
# The letter run is UNBOUNDED and followed by a hard right boundary
# `(?![0-9A-Za-z])`, on purpose: capping it at two letters (or the digit run at five)
# let a longer real section TRUNCATE into a different, real, wrong one --
# `42 USC 1395ddd` (Medicare Integrity Program) silently became `1395dd` (EMTALA), and
# `21 USC 360bbb-3` (an EUA provision) became `360bb` (orphan drugs), dropping the `-3`
# too. That is the exact substitution this comment already warned the suffix group
# exists to prevent, just one letter later. Refusing to match at all is the honest
# outcome; a shorter real section id from a citation that named a different, real
# section is not.
#
# RANGE vs SUFFIX (federal-reference#99). `(?:-[0-9a-z]{1,4})?` above was one group doing
# two jobs: it correctly captures a genuine suffix (`1320d-2`, `360bbb-3`) and it ALSO
# matched the second number of a section RANGE (`38 USC 4301-4335`), deriving
# `38-usc-4301-4335` -- an id no document can ever have, because no section is named
# `4301-4335`. Fixing that needs a signal that tells the two apart, and only one of the
# three candidates on offer turned out to be reliable:
#
#   - §§ (double section mark) vs § was tried first and REJECTED: `38 USC 4301-4335`
#     (USERRA) carries no section mark at all, so requiring §§ would still swallow it.
#   - second-number-larger-than-first is a real signal but not sufficient alone: a
#     genuine suffix's tail number is usually smaller than the base section (`1320d-2`),
#     so magnitude alone would misclassify wide real ranges and let narrow ones slip
#     through by accident.
#   - LETTER IMMEDIATELY BEFORE THE HYPHEN is the reliable one, and it is reliable
#     because it already had to be true for every real suffix in this file's own hazard
#     list: `1320d-2`, `360bbb-3`, `717b-1`, `290dd-2` all have a letter run (`d`, `bbb`,
#     `b`, `dd`) directly before the hyphen. `4301-4335`, `101-336` and `1501-1508` do
#     not -- the base is pure digits in every real range found in this corpus. No U.S.C.
#     section suffix in the wild is hyphenated straight off a bare digit run.
#
# So `sec` is now two alternatives: digits-then-letters-then-optional-suffix (the suffix
# case, unchanged in what it matches) OR digits alone. A pure-digit `sec` leaves any
# following `-NNNNN` unconsumed, and a second, entirely optional clause picks that up as
# a candidate range endpoint (`hi`) ONLY when it is a plain hyphen/en-dash/em-dash
# directly followed by digits -- no `through`/`to`/`thru` wording, because no real USC
# range in this corpus is written that way, and guessing at unevidenced wording is the
# thing AGENTS.md's overriding rule refuses to do. A citation whose second number reads
# lower than or equal to the first (`10 USC 50-10`) is left ambiguous on purpose: the
# base section alone is still returned, but no range is guessed from it.
#
# EXPAND, don't refuse and don't stop at the first section -- following the CFR branch's
# own precedent below (`RANGE`/`MAX_RANGE`) for the same reason it gives there: returning
# an id is not a claim the document exists, so a range expands to every section it names
# and a gap in numbering simply misses at the index lookup, the honest place for that
# question to be answered. `MAX_RANGE` (shared with the CFR branch) also does the same
# job here it does there: `3 U.S.C. §§ 101-336` spans 235 sections, which is not a real
# range of consecutive U.S.C. sections -- it is `3 U.S.C.` mis-citing `Pub. L. 101-336`
# (a pre-existing data problem, out of scope here) -- and MAX_RANGE keeps this function
# from turning that mis-citation into 236 fabricated ids. The base section (`3-usc-101`)
# is still returned even when the range is too wide to expand, exactly as the CFR branch
# keeps its own first-matched section when a list/range entry falls outside MAX_RANGE.
USC = re.compile(r"\b(?P<title>\d{1,2})\s*U\.?\s?S\.?\s?C\.?\s*(?:§{1,2}\s*)?"
                 r"(?P<sec>\d{1,5}[a-z]+(?:-[0-9a-z]{1,4})?|\d{1,5})"
                 r"(?:\s*[-–—]\s*(?P<hi>\d{1,5})(?![0-9A-Za-z]))?"
                 r"(?![0-9A-Za-z])(?:\([^)]*\))*", re.I)

# `IRS Pub 1075`, `IRS Publication 1075 (Rev. 11-2021)`, `IRS Pub 1075 Revision 9/2016`
IRSPUB = re.compile(r"\bIRS\s+Pub(?:lication)?\.?\s*(?P<num>\d{3,4})\b", re.I)
# The revision, read from anywhere in the citation rather than from a group that had to sit
# immediately after the number. Case-insensitive and notation-tolerant on purpose.
IRS_REV = re.compile(r"\b(?:rev(?:ision)?\.?\s*)?(\d{1,2})\s*[-/]\s*(\d{4})\b", re.I)
# `CJIS Security Policy 6.1`, `CJIS SP v5.9.4`
CJIS = re.compile(r"\bCJIS(?:\s+Security)?(?:\s+Policy|\s+SP)?\.?\s*"
                  r"(?:v(?:ersion)?\.?\s*)?(?P<ver>\d+(?:\.\d+){0,2})?", re.I)

# `ARC-AMPE`, `ARC-AMPE Vol. I`, `ARC AMPE Volume 1`. CMS's control set for state entities
# running Exchanges, Medicaid, CHIP and BHP.
#
# VOLUME IS NOT VERSION, so it is NOT in the id. CJIS above puts the version in the id
# because CJIS 5.9.4 and 6.1 state different requirements and a citation to one must never
# resolve to the other. ARC-AMPE's volumes are PARTS OF ONE EDITION published together --
# Vol. I is the control catalogue, the others are companions. A citation naming a volume is
# naming a section of the same instrument, the same way `(b)(1)(A)` names a subsection of a
# U.S.C. section and is deliberately ignored there. Splitting on volume would mint ids no
# Oregon rule cites and leave `ARC-AMPE` alone deriving nothing.
#
# Supersedes MARS-E: ARC-AMPE Vol. I fn. 6 states it "supersedes and replaces MARS-E and the
# NEE GRC Framework effective upon publication." MARS-E citations are NOT mapped here -- a
# superseded instrument and its replacement are different documents, the same rule that keeps
# a U.S.C. section off its public law.
ARC_AMPE = re.compile(r"\bARC[\s-]?AMPE\b(?:\s*Vol(?:ume|\.)?\s*[IV\d]+)?", re.I)

# `CISA CPGs`, `CISA CPG v1.0.1`, `Cross-Sector Cybersecurity Performance Goals`.
#
# VERSION IS IN THE ID, unlike ARC-AMPE and for CJIS's reason: CISA revises the CPGs and the
# goals change between revisions. An unversioned citation derives nothing rather than
# guessing -- federal-reference's own resolver can read frontmatter and answer it; a sibling
# cannot, and picking whichever revision happens to be held is the substitution this file
# exists to refuse.
CISA_CPG = re.compile(r"\bCISA\s+CPGs?\b(?:\s*v(?:ersion)?\.?\s*(?P<ver>\d+(?:\.\d+){0,2}))?"
                      r"|\bCross[\s-]Sector\s+Cybersecurity\s+Performance\s+Goals\b", re.I)

# `NIST SP 800-53 Rev. 5`, `NIST Special Publication 800-53, Revision 5 AC-2(1)`, `SP 800-53r5`,
# `NIST 800-53 Rev 5, AC-1, AT-1`. The publication is NIST SP 800-53 ITSELF -- 800-53A (the
# assessment procedures) and 800-53B (the control baselines) are different publications with
# different content, so a trailing letter makes this NOT a match (`sfx`), never a near-match.
#
# VERSION IS IN THE ID, for CJIS's reason: Rev. 4 and Rev. 5 state different controls
# (Rev. 5 withdrew controls, added whole families, and folded the privacy controls in), so a
# citation to Rev. 4 derives `nist-sp-800-53-r4`, which is simply absent from the index -- a
# correct miss with no version knowledge needed on the citing side. An unversioned citation
# derives nothing: a sibling cannot tell which revision its author meant, and picking
# whichever is held is the substitution this file exists to refuse.
#
# A RELEASE NUMBER IS NOT A REVISION. NIST publishes minor releases of Rev. 5 (5.1.1 in
# 2023, 5.2.0 on 2025-08-27) that change control text; the held document is the Rev. 5 PDF
# of record (September 2020, updates as of 2020-12-10), so `Rev. 5.2.0` derives nothing
# rather than being answered with text that predates it. federal-reference's own resolver
# says why.
NIST_800_53 = re.compile(
    r"(?:NIST\s*(?:Special\s+Publication\s*|SP\s*)?|Special\s+Publication\s*|\bSP\s*)?"
    r"(?<![0-9A-Za-z-])800[-\u2011]53(?P<sfx>[A-Za-z](?![A-Za-z]))?(?![0-9])", re.I)
NIST_REV = re.compile(
    r"\A[\s,(:]*(?:Rev(?:ision|\.)?\s*(?P<rev>\d{1,2})|r(?P<rev2>\d{1,2}))(?P<rel>(?:\.\d+)+)?(?![0-9A-Za-z])",
    re.I)
# A control id with any enhancements: `AC-2`, `AC-2(1)`, `SC-7(3)(a)` is NOT a thing here --
# enhancements are `(N)`. The 20 two-letter families of Rev. 5; an unlisted prefix is not a
# control (CSF subcategories `PR.AC-3` and CJIS's own `IA-0` must not become ids).
NIST_FAMILIES = frozenset("AC AT AU CA CM CP IA IR MA MP PE PL PM PS RA SA SC SI SR PT".split())
NIST_CONTROL = re.compile(r"(?<![A-Za-z0-9.])(?P<fam>[A-Z]{2})-(?P<num>\d{1,2})"
                         r"(?P<enh>(?:\(\d{1,2}\))*)(?![0-9A-Za-z])")
# Where a control list ends: the next publication named.
_NIST_TAIL_STOP = re.compile(r"\b(?:FIPS|SP|NIST|ISO|CJIS|IRS|CFR|C\.F\.R\.|OMB|PUB)\b")


def nist_800_53(citation: str):
    """(revision or None, release_suffix, [control ids]) for the first SP 800-53 citation in the
    string, or None if it names no 800-53 at all (800-53A/B do not count). `revision` is None for
    an unversioned citation. Shared by candidates() and by
    federal-reference's own resolver, so the two cannot disagree about what was cited.
    """
    for m in NIST_800_53.finditer(citation):
        if m.group("sfx"):
            continue
        tail = citation[m.end():]
        r = NIST_REV.match(tail)
        rev = (r.group("rev") or r.group("rev2")) if r else None
        rest = tail[r.end():] if r else tail
        stop = _NIST_TAIL_STOP.search(rest)
        if stop:
            rest = rest[:stop.start()]
        ctrls = []
        for c in NIST_CONTROL.finditer(rest):
            if c.group("fam") in NIST_FAMILIES:
                cid = f"{c.group('fam').lower()}-{int(c.group('num'))}"
                # `-0` is never a control (CJIS's own `IA-0` heading is not one).
                if int(c.group("num")) and cid not in ctrls:
                    ctrls.append(cid)
        return rev, (r.group("rel") or "") if r else "", ctrls
    return None



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

    m = USC.search(c)
    if m:
        # NEVER mapped onto a public law -- ADR-0004's rule survives ADR-0006's supersession.
        # The codified section and the enacted text are different documents; this returns
        # the codified section's own id, never a `pl-` id, regardless of what this corpus
        # currently holds -- existence is the index lookup's job, not this pure function's.
        title, sec = m.group("title"), m.group("sec").lower()

        # RANGE EXPANSION (federal-reference#99). `hi` is only ever populated when `sec`
        # matched the pure-digit alternative above -- see USC's own comment for why a
        # letter-suffixed `sec` never leaves a trailing `-NNNNN` for this group to find --
        # so `int(sec)` below is always safe. `0 < hi - lo` refuses a reversed or degenerate
        # pair (`10 USC 50-10`) rather than guess at what it means; `<= MAX_RANGE` refuses a
        # span wide enough to be a mis-citation instead of a real range (see USC's comment on
        # `3 U.S.C. §§ 101-336`). Either way the base section is still returned -- exactly
        # the CFR branch's own behaviour when its own range falls outside MAX_RANGE.
        hi = m.group("hi")
        if hi:
            lo_n, hi_n = int(sec), int(hi)
            if 0 < hi_n - lo_n <= MAX_RANGE:
                return [f"{title}-usc-{n}" for n in range(lo_n, hi_n + 1)]
        return [f"{title}-usc-{sec}"]

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

    if ARC_AMPE.search(c):
        # One id regardless of volume -- see the pattern's comment.
        return ["arc-ampe"]

    m = CISA_CPG.search(c)
    if m:
        ver = m.groupdict().get("ver")
        # The held document is `cisa-cpg`, the v1.0.1 report. A citation naming a DIFFERENT
        # version derives that version's id, which is simply absent from the index -- a
        # correct miss, exactly as CJIS 5.9.4 is. An unversioned citation derives nothing.
        if not ver:
            return []
        return ["cisa-cpg"] if ver == "1.0.1" else [f"cisa-cpg-{ver.replace('.', '-')}"]

    nist = nist_800_53(c)
    if nist:
        rev, rel, ctrls = nist
        # Unversioned or release-numbered: nothing derivable (see NIST_800_53's comment).
        if rev is None or rel:
            return []
        pub = f"nist-sp-800-53-r{rev}"
        return [f"{pub}.{cid}" for cid in ctrls] or [pub]

    return []
