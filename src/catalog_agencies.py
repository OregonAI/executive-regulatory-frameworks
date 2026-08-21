#!/usr/bin/env python3
"""Populate _meta/catalog/agencies.yml — the canonical registry of Oregon agencies and
their sub-units, grounded in the OAR chapter assignment scheme as presented by
https://oregon.public.law/rules.

  python3 src/catalog_agencies.py --refresh
  python3 src/catalog_agencies.py --check           # CI: the registry keeps its contract
  python3 src/catalog_agencies.py --selftest        # CI: every rule --check enforces fires
  python3 src/catalog_agencies.py "<search term>"   # look up a slug

WHY --check EXISTS. This registry is the identity three sibling corpora crosswalk into, and
--refresh rebuilds all 189 rows from the scrape every time it runs, so the ways it breaks are
quiet ones: a curated field nothing preserves, a manual row nothing carries over, a slug two
bodies claim. Every one of those leaves a file that still parses and slugs that still resolve,
and surfaces months later as a cross-corpus join that quietly stopped matching (it has already
happened twice — see preserve_manual and preserve_curated). --check reads committed data only,
runs a --refresh in simulation against it, and states what would be lost. It asserts nothing
about upstream: what oregon.public.law currently serves is not something a PR here can break.

Why this source (user decision 2026-07-19, third source after two rejects):
data.oregon.gov's org dataset and the SoS Blue Book directory were both reviewed and
rejected. OAR chapter numbers are the state's own operational agency-assignment scheme
(every chapter belongs to exactly one agency/board/commission), and oregon.public.law's
index additionally models HIERARCHY: sub-units nest under their parent agency (e.g.
chapter 125 Dept. of Administrative Services, with 122 Chief Financial Office, 105
Chief Human Resources Office, 128 Office of the State CIO as sub-units). Caveat,
recorded in the catalog note: oregon.public.law is an unofficial (well-maintained)
mirror; official chapter assignment lives with the SoS Administrative Rules Unit.

Mechanics: the /rules index provides the tree (nested "quasi-sub-chapter" cards) but
abbreviates names ("Dept.", "Comm'n"); each chapter page's <title> carries the proper
full name ("OAR Chapter 125 - Department of Administrative Services"), so --refresh
fetches every chapter page (politeness delay) and uses that. Slugs are mechanical
(lowercase, non-alnum runs -> one hyphen). A slug collision between two chapters is a
hard error needing a human decision, never silent dedup.

validate_frontmatter.py requires every content file's agency: field to be 'statewide',
'external', or a slug from this registry. Sub-unit slugs are valid agency: values like
any other; whether a sub-unit gets its own agencies/<slug>/ tree or files under its
parent is an onboarding-time decision."""
import re
import sys
import time
import urllib.request
from collections import namedtuple
from datetime import date
from html import unescape

import yaml

from repo_lib import REPO_ROOT

BASE = "https://oregon.public.law"
INDEX_URL = f"{BASE}/rules"
CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"

# ------------------------------------------------------------------- the registry's fields
#
# THE ONE PLACE A REGISTRY FIELD IS DECLARED. `CURATED_KEYS` is DERIVED from this table
# rather than restated, because the two used to be the same fact written twice: this set was
# hand-maintained beside a comment asking whoever adds a curated field to remember to add it
# here too, and forgetting means --refresh destroys the curation with no error and no diff
# anyone reads. A field that is not scraped is curated by the same statement that says it
# exists, so the two cannot disagree.
#
# ORIGIN is the load-bearing column, and it answers one question: what happens to this field
# when --refresh rebuilds every row from oregon.public.law?
#
#   SCRAPED     the refresh writes it. `scraped_entry()` below is the only thing that may
#               produce one, and --check verifies this column against that constructor, so
#               calling a field scraped is a claim the code has to back up.
#   CURATED     nothing upstream produces it; it survives only because CURATED_KEYS carries
#               it across a refresh. Hand-reviewed data, and the reason this table exists.
#   MANUAL_FLAG `manual: true`, which is preserved by a different mechanism — it keeps the
#               WHOLE row (a body the chapter scrape can never see). Deliberately NOT
#               curated: copying the flag onto a row the scrape now produces would re-assert
#               a claim that a human is supposed to retire by hand after comparing names.
SCRAPED, CURATED, MANUAL_FLAG = "scraped", "curated", "manual-flag"

Field = namedtuple("Field", "origin required")

# One contract violation: which rule, which row, and what is wrong with it. A type rather
# than a formatted string so --selftest asserts on the RULE that fired instead of pattern-
# matching prose, which is how a test starts passing for the wrong reason.
Failure = namedtuple("Failure", "rule row detail")

FIELDS = {
    "slug": Field(SCRAPED, required=True),
    "name": Field(SCRAPED, required=True),
    # THE OAR NAME (CONTEXT.md): the name the administrative rules index gives a body, and
    # the string OAR-derived joins must match (ADR 0003). It lands BESIDE `name` rather than
    # replacing it, so consumers can move off `name` while `name` still means what it always
    # did — ADR 0003 changes what `name` holds, and a crosswalk that keeps matching a string
    # that quietly changed meaning is the failure those crosswalks exist to prevent.
    #
    # SCRAPED, NOT CURATED, and that is the whole point of the field. The chapter page's own
    # title is where this value comes from — `scraped_entry()` already reads it — so
    # declaring it CURATED would mean --refresh preserves the old file's copy and never
    # updates it: an upstream chapter retitle would move `name` and leave `oar_name` frozen
    # at a title the rules index no longer prints. A field that cannot track an upstream
    # retitle cannot be the string OAR-derived joins match on.
    "oar_name": Field(SCRAPED, required=True),
    # Null on 19 rows and that is not a gap: a body is in the registry because it EXISTS,
    # not because it issues rules (ADR 0003). Required means the KEY is present.
    "oar_chapter": Field(SCRAPED, required=True),
    "raw_index_name": Field(SCRAPED, required=True),
    "source_url": Field(SCRAPED, required=True),
    "parent_slug": Field(SCRAPED, required=True),
    "parent_chapter": Field(SCRAPED, required=True),
    # Written by the refresh when a chapter page's title would not parse or its fetch
    # failed. NOT curated even though the two rows carrying one today were hand-written:
    # both are `manual` rows, preserved whole, so they need nothing from CURATED_KEYS —
    # while making `note` curated would resurrect a stale "title not parseable" note onto a
    # row whose title parsed fine on the next refresh, which is a false claim about the
    # scrape rather than preserved curation.
    "note": Field(SCRAPED, required=False),
    "manual": Field(MANUAL_FLAG, required=False),
    # Hand-reviewed map to the DAS agency numbers oregon-budget reports spending against;
    # see src/link_budget_codes.py. ADR 0003 renames this field to `das_agency_number` —
    # the number identifies a body in the state's financial administration and says nothing
    # about whether it spends money. The rename is a separate change to the registry's data;
    # this table declares the field the committed rows carry TODAY.
    "budget_agency_code": Field(CURATED, required=False),
    # Other names the same body is known by, including former names after a rename. An
    # ASSERTION of identity, reviewed once, rather than a similarity score computed at
    # query time.
    "aliases": Field(CURATED, required=False),
}

CURATED_KEYS = frozenset(k for k, f in FIELDS.items() if f.origin == CURATED)
SCRAPED_KEYS = frozenset(k for k, f in FIELDS.items() if f.origin == SCRAPED)
UA = "executive-regulatory-frameworks (+https://github.com/OregonAI/executive-regulatory-frameworks)"

ENTRY_RE = re.compile(
    r'<dt class="col-sm-2">[^<]*</dt>\s*'
    r'<dd class="col-sm-10">(?:<a href="/rules/oar_chapter_(\d+[a-z]?)">(.*?)</a>'
    r'|([^<]+?)(?=<div class="card))', re.S)
CARD_RE = re.compile(r'<div class="card[^"]*quasi-sub-chapter"')
TITLE_RE = re.compile(r"<title>OAR Chapter \d+[a-zA-Z]? \W (.*?)</title>", re.S)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def scraped_entry(*, name, oar_chapter, raw_index_name, source_url, note=None):
    """One registry row as --refresh builds it from oregon.public.law.

    THE ONLY PLACE THE SCRAPE'S OWN FIELDS ARE WRITTEN, which is what lets --check
    simulate a refresh honestly: the simulation calls this constructor instead of copying
    the committed row's keys, so it cannot credit the scrape with producing a field the
    scrape never writes. Crediting it wrongly is the exact failure the simulation exists to
    catch — a curated field mislabelled `SCRAPED` would then look preserved while a real
    --refresh silently dropped it.

    ONE STRING, TWO FIELDS, ON PURPOSE. The chapter page title is the only name the scrape
    can see, and it is the OAR NAME (CONTEXT.md) — what the rules index calls this body. It
    is written to `oar_name`, where OAR-derived joins can rely on it, and to `name`, which
    still holds exactly what it held before. Writing it twice is what makes this the EXPAND
    half of ADR 0003's rename: consumers move onto `oar_name` while `name` is unchanged,
    rather than being re-verified after `name` has already changed meaning underneath them.

    parent_slug/parent_chapter are written null here and filled by the caller once the
    index tree is known; they are keys of a scraped row either way."""
    entry = {"slug": slugify(name), "name": name, "oar_name": name,
             "oar_chapter": oar_chapter,
             "raw_index_name": raw_index_name, "source_url": source_url}
    if note:
        entry["note"] = note
    entry["parent_slug"] = None
    entry["parent_chapter"] = None
    return entry


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_index(raw: str):
    """[(chapter|None, index_name, parent_top_index|None)] from the /rules tree, plus
    the list of top entries. Sub-unit entries live inside a parent's <dd> in a
    quasi-sub-chapter card, whose single <dl> ends at the first </dl> after the card
    opens. Four parents (e.g. Dept. of Consumer & Business Services, Secretary of
    State) have NO chapter of their own — they appear as a bare-text <dd> (empty
    <dt>, no link) that exists only to carry a card; those become chapterless
    name-only groups."""
    card_spans = []
    for m in CARD_RE.finditer(raw):
        end = raw.index("</dl>", m.start())
        card_spans.append((m.start(), end))

    entries = []   # [chapter|None, index_name, parent_top_index|None]
    tops = []      # (pos, entry_index) of top-level entries
    for m in ENTRY_RE.finditer(raw):
        pos = m.start()
        ch = m.group(1)  # None for a chapterless bare-text group
        name = re.sub(r"\s+", " ", unescape(m.group(2) or m.group(3) or "")).strip()
        if not name:
            continue
        span = next(((s, e) for s, e in card_spans if s <= pos <= e), None)
        if span is None:
            tops.append((pos, len(entries)))
            entries.append([ch, name, None])
        else:
            parent_idx = next((ei for p, ei in reversed(tops) if p < span[0]), None)
            entries.append([ch, name, parent_idx])
    return entries


def assert_scrape_declared(orgs):
    """Stop a refresh that produced a field FIELDS does not declare SCRAPED.

    THE DECLARATION IS BINDING ON THE SCRAPE, and this is the half --check cannot reach: it
    reads committed data and never runs a scrape, so it can only ask whether the rows it can
    see would survive. A field added to the scrape without being declared would make that
    simulation wrong in the direction that hides losses — the field would be compared as if
    curated and fail, or worse, be assumed rewritten — so the refresh that would introduce it
    stops here instead, before anything is written."""
    undeclared = {k for o in orgs for k in o} - SCRAPED_KEYS
    if undeclared:
        sys.exit(f"the scrape produced undeclared field(s) {sorted(undeclared)} — add them "
                 "to FIELDS (origin SCRAPED) before writing the registry")


def preserve_manual(prev_orgs, orgs, by_slug):
    """Carry over manually-added entries (chapters OARD serves but the mirror's index
    omits, e.g. 419, 950 — discovered via renumbering redirects during the mass import).
    A refresh must never drop them; a collision with a newly-indexed chapter means the
    mirror caught up — then the manual flag should be removed by hand after comparing
    names. Mutates `orgs` and `by_slug`, which is what --refresh needs and what --check
    replays."""
    # THE SCRAPED CHAPTERS, COMPUTED ONCE. This set used to be rebuilt inside the loop
    # against `orgs`, which the loop is simultaneously appending to -- so the first
    # preserved entry with `oar_chapter: null` put None INTO the set that the next one
    # was tested against, and every null-chapter manual entry after it looked like a
    # collision with a chapter the mirror had caught up on.
    #
    # 13 of the 15 manual entries THEN IN THE REGISTRY carried a null chapter -- 17 carry
    # the flag today -- because that is what a body with no OAR chapter looks like: the
    # Governor's office, the Legislative Assembly, district attorneys. Simulated against
    # the registry as it stood, a --refresh kept 2
    # and dropped 13, among them office-of-the-governor, legislative-fiscal-officer and
    # district-attorneys-and-deputies. Six of those are slugs oregon-kpm's agency
    # crosswalk resolves into today.
    #
    # It would have failed the way preserve_curated() below warns about: silently. The
    # registry still parses, every remaining slug still resolves, and the loss only
    # surfaces as a cross-corpus join that quietly stopped matching. `--check` now replays
    # this function against the committed registry on every PR, so the next regression of
    # this class is a red build rather than a silent one.
    # A NULL CHAPTER CANNOT COLLIDE, and that is the second half of the bug. The guard
    # asks "has the mirror caught up on this chapter?", which is meaningless for an entry
    # that never had one -- and four SCRAPED bodies legitimately carry
    # `oar_chapter: null` (Secretary of State, DCBS, the Military Department, the Mental
    # Health Regulatory Agency, all parents whose rules live in their sub-units). So None
    # was always in this set, and every null-chapter manual entry was discarded no matter
    # what order they came in. Such an entry can only be superseded by SLUG, which the
    # first clause already handles.
    scraped_chapters = {x["oar_chapter"] for x in orgs if x.get("oar_chapter")}
    for o in prev_orgs:
        if o.get("manual") and o["slug"] not in by_slug \
                and (not o.get("oar_chapter")
                     or o["oar_chapter"] not in scraped_chapters):
            orgs.append(o)
            by_slug[o["slug"]] = o


def preserve_curated(prev_orgs, by_slug, curated_keys=None):
    """Copy CURATED_KEYS from the previous registry onto the rows the scrape rebuilt.

    Every field --refresh writes is derived fresh from oregon.public.law, so a key that
    is not scraped — and `budget_agency_code` is not; it is a hand-reviewed mapping to the
    DAS codes oregon-budget reports spending against — would be silently dropped on the
    next --refresh. Silently is the problem: the file would still parse, every slug would
    still resolve, and the loss would only surface as a cross-corpus join that quietly
    stopped matching anything."""
    curated_keys = CURATED_KEYS if curated_keys is None else curated_keys
    for o in prev_orgs:
        current = by_slug.get(o["slug"])
        if not current:
            continue
        for key in curated_keys:
            if key in o and key not in current:
                current[key] = o[key]


def cmd_refresh():
    raw = get(INDEX_URL)
    entries = parse_index(raw)
    chapters = [e[0] for e in entries if e[0]]
    if len(set(chapters)) != len(chapters):
        dupes = {c for c in chapters if chapters.count(c) > 1}
        sys.exit(f"duplicate chapters in index parse: {dupes}")
    n_groups = sum(1 for e in entries if e[0] is None)
    print(f"index: {len(chapters)} chapters + {n_groups} chapterless parent groups "
          f"({sum(1 for e in entries if e[2] is not None)} sub-units); "
          f"fetching proper names from chapter pages...")

    # Fetch proper names for every chaptered entry
    orgs = [None] * len(entries)
    fallbacks = 0
    done = 0
    for i, (ch, index_name, parent_idx) in enumerate(entries):
        if ch is None:
            continue  # chapterless group — named after its children below
        url = f"{BASE}/rules/oar_chapter_{ch}"
        name, note = index_name, None
        try:
            m = TITLE_RE.search(get(url))
            if m:
                name = re.sub(r"\s+", " ", unescape(m.group(1))).strip()
            else:
                note = "chapter page title not parseable; name from index (abbreviated)"
                fallbacks += 1
        except Exception as e:
            note = f"chapter page fetch failed ({e}); name from index (abbreviated)"
            fallbacks += 1
        orgs[i] = scraped_entry(name=name, oar_chapter=ch, raw_index_name=index_name,
                                source_url=url, note=note)
        time.sleep(0.2)
        done += 1
        if done % 40 == 0:
            print(f"...{done}/{len(chapters)}")

    # Chapterless parent groups: derive the proper name mechanically from the common
    # "Parent Name, " prefix their children's chapter pages all print; fall back to
    # the (abbreviated) index name if the children don't agree on one.
    for i, (ch, index_name, _) in enumerate(entries):
        if ch is not None:
            continue
        child_names = [orgs[j]["name"] for j, e in enumerate(entries)
                       if e[2] == i and orgs[j]]
        prefixes = {n.split(", ")[0] for n in child_names if ", " in n}
        if len(prefixes) == 1:
            name = prefixes.pop()
            note = None
        else:
            name = index_name
            note = ("chapterless group; children's name prefixes don't agree "
                    f"({sorted(prefixes)}), name from index (abbreviated)")
        orgs[i] = scraped_entry(name=name, oar_chapter=None, raw_index_name=index_name,
                                source_url=INDEX_URL, note=note)

    by_slug = {}
    for o in orgs:
        if o["slug"] in by_slug:
            sys.exit(f"SLUG COLLISION: chapters {by_slug[o['slug']]['oar_chapter']} and "
                     f"{o['oar_chapter']} both slugify to {o['slug']!r} — needs a human "
                     "decision, not silent dedup")
        by_slug[o["slug"]] = o
    for i, (ch, _, parent_idx) in enumerate(entries):
        if parent_idx is not None:
            orgs[i]["parent_slug"] = orgs[parent_idx]["slug"]
            orgs[i]["parent_chapter"] = orgs[parent_idx]["oar_chapter"]

    assert_scrape_declared(orgs)

    if CATALOG.exists():
        prev_orgs = yaml.safe_load(CATALOG.read_text()).get("organizations", [])
        preserve_manual(prev_orgs, orgs, by_slug)
        preserve_curated(prev_orgs, by_slug)

    cat = {
        "note": ("Canonical registry of Oregon agencies and their sub-units, keyed on "
                 "the OAR chapter assignment scheme as presented by oregon.public.law/"
                 "rules (an unofficial but well-maintained mirror; official chapter "
                 "assignment lives with the SoS Administrative Rules Unit). Proper "
                 "names come from each chapter page's own title; the index tree "
                 "provides the parent/sub-unit hierarchy (parent_chapter/parent_slug). "
                 "Third registry source: a data.oregon.gov dataset and the SoS Blue "
                 "Book directory were both previously used and dropped after review "
                 "(2026-07-18/19). validate_frontmatter.py requires every content "
                 "file's agency: field to resolve to 'statewide', 'external', or a "
                 "slug here. oar_name is the OAR name — the chapter page's own title, "
                 "which is the string OAR-derived joins must match; it is scraped, so an "
                 "upstream chapter retitle moves it. raw_index_name is a different "
                 "string: the index's own abbreviated spelling. "
                 "budget_agency_code, where present, is the three-digit DAS "
                 "agency code the oregon-budget corpus reports spending against; it is "
                 "hand-reviewed (src/link_budget_codes.py), is NOT scraped from the "
                 "source above, and is preserved across --refresh. Its absence on an "
                 "entry means no counterpart was found, not that none was sought."),
        "source_url": INDEX_URL,
        "retrieved": date.today().isoformat(),
        "organizations": sorted(orgs, key=lambda o: o["slug"]),
    }
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    n_sub = sum(1 for o in orgs if o["parent_slug"])
    print(f"catalog: {len(orgs)} organizations ({len(orgs) - n_sub} top-level, "
          f"{n_sub} sub-units, {fallbacks} name fallbacks)")


def load():
    return yaml.safe_load(CATALOG.read_text())


def find(query: str, limit: int = 8):
    """Substring search over the proper name, for a human picking a slug."""
    q = query.lower()
    cat = load()
    return [o for o in cat["organizations"] if q in o["name"].lower()][:limit]


# ---------------------------------------------------------------- name -> slug resolution
#
# `find()` above is a substring match "for a human picking a slug" and cannot reach a name
# written in another house style. The Secretary of State Archives Division inverts them —
# "Agriculture, Dept. of", "ODOT - Highway Division", "Treasury, Oregon State" — and folding
# in its 76 retention schedules needed every one attributed to a registry slug.
#
# GENERATES CANDIDATE FORMS RATHER THAN REWRITING TO ONE. An earlier version de-inverted a
# trailing kind unconditionally, turned "Criminal Justice Commission" into "commission of
# criminal justice", and LOST two names that had already matched. A name may or may not be
# inverted; guessing costs matches either way, trying both costs nothing.
#
# Measured on those 76: 66 automatic (24 exact, 31 normalized, 10 token, 1 alias), 10 left
# for a human. Recorded in _meta/catalog/retention-schedule-agencies.yml with a basis and,
# for anything non-exact, a note.

# The trailing `\.?` deliberately carries no closing `\b`. `\bdept\.?\b` CANNOT match
# "dept." — after the optional period `\b` would sit between "." and " ", neither a word
# character, so it is not a boundary. That form silently matched "dept" alone, left
# "department. of", and cost 9 of 76 matches before it was found.
_ABBREV = [
    (r"\bdept\.?", "department"), (r"\bcomm'?n\.?", "commission"),
    (r"\bdiv\.?(?=\s|$)", "division"), (r"\bexam'?rs\.?", "examiners"),
    (r"\bbd\.?(?=\s|$)", "board"), (r"\bofc\.?", "office"), (r"&", "and"),
]
_KIND = r"(department|board|commission|office|bureau|division|authority|agency)"
_STOP = {"oregon", "state", "of", "the", "and"}


def normalize_name(s: str) -> str:
    """Lowercase, de-punctuate and expand a free-text agency name."""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).lower()
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = re.sub(r"\(.*?\)", " ", s)                       # "(ODOT)", "(formerly DHS)"
    s = re.sub(r"^\s*odot\s*[-\u2013]\s*", "department of transportation ", s)
    for pat, rep in _ABBREV:
        s = re.sub(pat, rep, s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _variants(name: str):
    base = normalize_name(name)
    if not base:
        return []
    out = [base]
    stripped = re.sub(r"^(oregon state|state of oregon|oregon|the)\s+", "", base).strip()
    if stripped != base:
        out.append(stripped)
    for v in list(out):
        for pat, fmt in ((rf"^(.*?),?\s*{_KIND}\s+of$", "{1} of {0}"),
                         (rf"^(.*?)\s+{_KIND}$", "{1} of {0}"),
                         (rf"^{_KIND}\s+of\s+(.*)$", "{1} {0}")):
            m = re.match(pat, v)
            if m:
                out.append(fmt.format(m.group(1), m.group(2)).strip())
        for k in ("department", "agency", "commission", "board", "office"):
            out += [f"{v} {k}", f"{k} of {v}"]
    seen, uniq = set(), []
    for v in out:
        v = re.sub(r"\s+", " ", v).strip()
        if v and v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def _tokens(s):
    return {t for t in normalize_name(s).split() if t not in _STOP}


def resolve(name, organizations=None):
    """Free-text agency name -> (slug, basis) or (None, "unmatched").

    basis is exact | normalized | alias | tokens, in descending confidence."""
    orgs = organizations if organizations is not None else load()["organizations"]
    raw = str(name or "").strip().lower()
    for o in orgs:
        if raw == o["name"].strip().lower():
            return o["slug"], "exact"
    vs = _variants(name)
    for o in orgs:
        if {normalize_name(o["name"]), normalize_name(o.get("raw_index_name") or "")} & set(vs):
            return o["slug"], "normalized"
    for o in orgs:
        if any(normalize_name(a) in vs for a in (o.get("aliases") or [])):
            return o["slug"], "alias"
    # Token containment, and ONLY when unambiguous. A tie is reported unmatched rather than
    # guessed: a wrong agency attribution is worse than a name on a review list.
    t = _tokens(name)
    if t:
        hits = [o["slug"] for o in orgs if t <= _tokens(o["name"])]
        if len(hits) == 1:
            return hits[0], "tokens"
    return None, "unmatched"


# --------------------------------------------------------------------------------- check
#
# WHAT --check IS FOR. The registry is the identity three sibling corpora crosswalk into, and
# every rule below states something the committed rows already satisfy — so a failure here
# means a change broke the registry's contract, not that the contract was aspirational. It
# reads the committed registry and nothing else: no scrape, no network, so CI can run it on
# every PR.
#
# ALLOWLIST, NOT BLOCKLIST. A row is checked against the fields FIELDS declares; anything
# else is a failure rather than something skipped. A key nobody declared cannot be evaluated
# for whether --refresh preserves it, and CONTEXT.md's overriding rule is that "could not
# check" is never reported as "is not there".


def simulate_refresh(prev_orgs, curated_keys=None):
    """{slug: row} for what --refresh would leave behind, run against committed data.

    NO NETWORK AND NO SCRAPE. The scrape is replayed rather than performed: every row the
    scrape would rebuild is reconstructed by `scraped_entry()` from the values already
    committed for it, and then the two real preservation steps run over the result. What
    that measures is SURVIVAL — which rows and which fields a refresh keeps — not whether
    the upstream index still says the same thing, which is a question only a fetch can
    answer and not one a PR can break.

    A `manual` row is not reconstructed, because the scrape cannot see it: that is what the
    flag means. It comes back through preserve_manual() or not at all, and "or not at all"
    is a bug that already happened once (see that function).

    `name` is passed as the scrape's one name string because that is where the committed
    rows hold it today — `oar_name` holds the same bytes on all 189 of them. When ADR 0003
    makes `name` the statutory name the two stop agreeing, and this call has to read
    `oar_name` instead; nothing here would notice, because a scraped field is skipped by the
    survival comparison, so that step belongs with the change that splits them.
    """
    orgs, by_slug = [], {}
    for o in prev_orgs:
        if o.get("manual"):
            continue
        row = scraped_entry(name=o.get("name"), oar_chapter=o.get("oar_chapter"),
                            raw_index_name=o.get("raw_index_name"),
                            source_url=o.get("source_url"), note=o.get("note"))
        row["parent_slug"] = o.get("parent_slug")
        row["parent_chapter"] = o.get("parent_chapter")
        orgs.append(row)
        # setdefault, not assignment: a slug claimed twice is unique-slug's failure to
        # report, and masking one of the two here would turn it into a survival failure
        # against the wrong row.
        by_slug.setdefault(row["slug"], row)
    preserve_manual(prev_orgs, orgs, by_slug)
    preserve_curated(prev_orgs, by_slug, curated_keys)
    return {o["slug"]: o for o in orgs}


def _row_id(o, i):
    """What to name a row in a failure. Falls back to its position, because a row missing
    the slug is exactly the row that most needs pointing at."""
    slug = o.get("slug") if isinstance(o, dict) else None
    return slug if isinstance(slug, str) and slug else f"organizations[{i}]"


def check_registry(cat, fields=None) -> list:
    """Every way the registry violates its contract, as Failures.

    `fields` is the declaration to check against, defaulting to the one this module ships.
    It is a PARAMETER so that --selftest can check a registry against a differently-declared
    table — the two ways a curated field goes missing from CURATED_KEYS are statements about
    the declaration, and no registry row can express either one."""
    fields = FIELDS if fields is None else fields
    curated = frozenset(k for k, f in fields.items() if f.origin == CURATED)
    scraped = frozenset(k for k, f in fields.items() if f.origin == SCRAPED)

    failures = []
    orgs = (cat or {}).get("organizations")
    if not isinstance(orgs, list):
        return [Failure("readable-registry", "agencies.yml",
                        "no `organizations` list to check")]
    # Every rule below is vacuously true of an empty list, so a registry that lost all its
    # rows would pass every one of them — the "check that passes without checking anything"
    # this repo treats as a defect in its own right. `validate_frontmatter` resolves every
    # content file's agency: against these rows, so zero of them is never a valid state.
    if not orgs:
        return [Failure("registry-populated", "agencies.yml",
                        "no bodies at all — every other rule is vacuously true of an "
                        "empty registry, so nothing was checked")]

    for i, o in enumerate(orgs):
        if not isinstance(o, dict):
            failures.append(Failure("readable-row", _row_id(o, i),
                                    "not a mapping, so no rule below could be evaluated "
                                    "against it"))
            continue
        for key in o:
            if key not in fields:
                failures.append(Failure(
                    "declared-field", _row_id(o, i),
                    f"field {key!r} is not declared in FIELDS — if it is curated, "
                    "--refresh will destroy it; declare it"))
        # An absent key and a null value are different claims: `parent_slug: null` says a
        # body has no parent, an absent parent_slug says nobody asked. Consumers read both
        # as "no parent", which is how the second silently becomes the first.
        for key, field in fields.items():
            if field.required and key not in o:
                failures.append(Failure("required-field", _row_id(o, i),
                                        f"required field {key!r} is absent (null is a "
                                        "value; absent is not)"))

    # Position is carried alongside, so a failure points at the row's place in the
    # committed file rather than its place among the rows that happened to be readable.
    rows = [(i, o) for i, o in enumerate(orgs) if isinstance(o, dict)]
    # IDENTITY. The slug is the only thing a sibling corpus joins on, and the chapter is
    # what put most rows here; either one claimed twice attributes one body's documents to
    # another. --refresh already calls a slug collision a human decision rather than silent
    # dedup, and this is the same rule applied to what is already committed.
    for key, rule in (("slug", "unique-slug"), ("oar_chapter", "unique-chapter")):
        seen = {}
        for i, o in rows:
            value = o.get(key)
            if value is None:   # 19 bodies hold no chapter, which is not a collision
                continue
            if value in seen:
                failures.append(Failure(rule, _row_id(o, i),
                                        f"{key} {value!r} is already claimed by "
                                        f"{seen[value]!r}"))
            else:
                seen[value] = _row_id(o, i)

    # THE PARENT RELATION. ADR 0004 splits `parent_slug` into *part of* and *administered
    # by*, and both readings agree on this much: the relation names a body this registry
    # carries. A pointer at a slug nobody has states a hierarchy no reader can check, and
    # parent_chapter is the same pointer written twice — when the two disagree, each
    # consumer resolves the parent differently depending on which half it read.
    by_slug = {o["slug"]: o for _, o in rows if isinstance(o.get("slug"), str)}
    for i, o in rows:
        parent_slug = o.get("parent_slug")
        if parent_slug is None:
            continue
        parent = by_slug.get(parent_slug)
        if parent is None:
            failures.append(Failure("parent-resolves", _row_id(o, i),
                                    f"parent_slug {parent_slug!r} is not a slug in this "
                                    "registry"))
            continue
        if o.get("parent_chapter") != parent.get("oar_chapter"):
            failures.append(Failure(
                "parent-agrees", _row_id(o, i),
                f"parent_chapter {o.get('parent_chapter')!r} but {parent_slug!r} holds "
                f"chapter {parent.get('oar_chapter')!r}"))

    # CALLING A FIELD SCRAPED IS A CLAIM ABOUT THE CODE, so it is checked against the code.
    # The survival comparison below skips scraped fields on the grounds that the refresh
    # rewrites them; a curated field wrongly declared SCRAPED would therefore be skipped
    # while a real --refresh dropped it — a false pass, which is the one outcome a gate must
    # not produce. `scraped_entry()` is the only thing that writes a scraped field, so its
    # own key set settles the question. The probe passes a TRUTHY note on purpose: the
    # constructor omits that key when a chapter page parsed fine, which is most of the time.
    written = set(scraped_entry(name="probe", oar_chapter=None, raw_index_name=None,
                                source_url=None, note="probe"))
    for key in sorted(scraped - written):
        failures.append(Failure("scraped-field", "FIELDS",
                                f"{key!r} is declared SCRAPED but scraped_entry() does "
                                "not write it — --refresh would drop it"))
    for key in sorted(written - scraped):
        failures.append(Failure("scraped-field", "FIELDS",
                                f"scraped_entry() writes {key!r}, which FIELDS does not "
                                "declare SCRAPED"))

    # WHAT A --refresh WOULD LEAVE BEHIND. Everything above reads the registry as it stands;
    # this reads it as it would stand after the command that rebuilds it, which is the only
    # place curation has ever been lost. Compared for every field that is NOT scraped,
    # allowlist-style: whatever the refresh does not write, it has to preserve.
    #
    # A row with no name or no slug is one the simulation cannot run on at all: the refresh
    # derives the slug from the name, so there is nothing to rebuild and nothing to compare.
    # Such a row is REPORTED as unevaluated rather than crashed on or quietly left out of
    # the comparison — "could not check" is never reported as "is not there" (CONTEXT.md).
    simulatable, unevaluable = [], []
    for i, o in rows:
        (simulatable if isinstance(o.get("name"), str) and isinstance(o.get("slug"), str)
         else unevaluable).append((i, o))
    for i, o in unevaluable:
        failures.append(Failure("survives-refresh", _row_id(o, i),
                                "no name or no slug, so a refresh cannot be simulated "
                                "against this row — it is unchecked, not clean"))
    survivors = simulate_refresh([o for _, o in simulatable], curated_keys=curated)
    for i, o in simulatable:
        got = survivors.get(o.get("slug"))
        if got is None:
            failures.append(Failure("survives-refresh", _row_id(o, i),
                                    "--refresh would not produce this row and nothing "
                                    "preserves it — the row, and every curated field on "
                                    "it, would be gone"))
            continue
        for key in o:
            if key in scraped:
                continue
            if key not in got:
                failures.append(Failure("survives-refresh", _row_id(o, i),
                                        f"--refresh would drop {key!r} — it is not "
                                        "scraped, so only CURATED_KEYS can carry it "
                                        "across"))
            elif got[key] != o[key]:
                failures.append(Failure("survives-refresh", _row_id(o, i),
                                        f"--refresh would change {key!r} from {o[key]!r} "
                                        f"to {got[key]!r}"))
    return failures


def cmd_check() -> int:
    """Report every contract violation in the committed registry. Exit 1 if any."""
    if not CATALOG.exists():
        print(f"FAIL [readable-registry] {CATALOG}: no registry to check", file=sys.stderr)
        return 1
    cat = load()
    failures = check_registry(cat)
    for f in failures:
        print(f"  FAIL [{f.rule}] {f.row}: {f.detail}", file=sys.stderr)
    orgs = cat.get("organizations") or []
    if failures:
        print(f"\n{len(failures)} contract violation(s) across {len(orgs)} row(s)",
              file=sys.stderr)
        return 1
    curated = sum(1 for o in orgs if isinstance(o, dict) for k in o if k in CURATED_KEYS)
    print(f"{len(orgs)} rows against {len(FIELDS)} declared fields; "
          f"{curated} curated value(s) and "
          f"{sum(1 for o in orgs if isinstance(o, dict) and o.get('manual'))} manual row(s) "
          "survive a simulated --refresh")
    return 0


# ------------------------------------------------------------------------------ selftest
#
# THE PROOF THAT THE GATE ABOVE CAN FAIL. Every rule --check enforces is exercised here
# against a synthetic registry built to violate exactly one of them, because a check nobody
# has watched fail is not known to work — it is only known to be quiet. Synthetic fixtures:
# no network, no read of the committed registry.


def _fixture():
    """A registry that passes every rule. Each case below breaks exactly one thing."""
    das = scraped_entry(name="Department of Administrative Services", oar_chapter="125",
                        raw_index_name="Dept. of Administrative Services",
                        source_url=f"{BASE}/rules/oar_chapter_125")
    das["budget_agency_code"] = "107"
    cfo = scraped_entry(name="Chief Financial Office", oar_chapter="122",
                        raw_index_name="Chief Financial Office",
                        source_url=f"{BASE}/rules/oar_chapter_122")
    cfo["parent_slug"], cfo["parent_chapter"] = das["slug"], das["oar_chapter"]
    gov = scraped_entry(name="Office of the Governor", oar_chapter=None,
                        raw_index_name=None, source_url=None)
    gov["manual"] = True
    gov["aliases"] = ["Governor's Office"]
    return {"organizations": [das, cfo, gov]}


def _case_undeclared_field(cat):
    """A field nobody declared. It may be curation --refresh is about to destroy, and a
    field we could not evaluate must never be reported as one that passed. The name is
    deliberately made up: `das_agency_number` is a field ADR 0003 says the registry is
    GOING to carry, and using it as the example of an illegitimate field would read as a
    verdict on a decision that has already been taken. `oar_name` was the other such
    example until the registry started carrying one, which is the second reason to make
    the name up — a declared field stops demonstrating anything here."""
    cat["organizations"][0]["headcount"] = 412


def _case_missing_required_field(cat):
    """A row that dropped a field every row carries. `parent_slug: null` and no
    parent_slug at all read the same to a consumer and are not the same claim."""
    del cat["organizations"][1]["parent_slug"]


def _case_missing_oar_name(cat):
    """A row that carries a `name` but no `oar_name`. The whole point of landing the OAR
    name in its own field is that consumers can join on it INSTEAD of `name`, so a row
    missing one is a row those joins silently lose — and it is invisible from the outside,
    because `name` still holds the same string today. It stops holding it (ADR 0003), and
    then the gap is a body no OAR-derived join resolves."""
    del cat["organizations"][1]["oar_name"]


def _case_row_is_not_a_mapping(cat):
    """A row no rule can be evaluated against. It must FAIL, not be skipped — a row we
    could not check is never a row that passed."""
    cat["organizations"][2] = "office-of-the-governor"


def _case_duplicate_slug(cat):
    """Two rows, one identity. The slug is the only thing another corpus joins on, so a
    collision silently attributes one body's documents to another — the case --refresh
    already treats as a human decision rather than silent dedup."""
    cat["organizations"][1]["slug"] = cat["organizations"][0]["slug"]


def _case_duplicate_chapter(cat):
    """One OAR chapter claimed by two bodies. Chapter assignment is one-chapter-one-body
    (ADR 0003); two claims means one of them is wrong and nothing says which."""
    cat["organizations"][1]["oar_chapter"] = cat["organizations"][0]["oar_chapter"]


def _case_parent_slug_resolves_to_nothing(cat):
    """A parent pointer aimed at no body. Whatever ADR 0004 splits `parent_slug` into,
    the relation names a body IN this registry; a dangling one states a hierarchy that
    cannot be checked and reads as a fact."""
    cat["organizations"][1]["parent_slug"] = "department-of-administrative-service"


def _case_parent_chapter_disagrees(cat):
    """The two halves of the same pointer disagreeing. Consumers use whichever half they
    happened to read, so the disagreement resolves differently per consumer."""
    cat["organizations"][1]["parent_chapter"] = "999"


def _case_slug_the_scrape_would_not_produce(cat):
    """A slug hand-edited away from the one slugify() derives from the name. --refresh
    rebuilds the row under the DERIVED slug, so the hand-edited row — and the curated
    fields riding on it — is not preserved onto anything; it just stops existing."""
    cat["organizations"][1]["budget_agency_code"] = "107"
    cat["organizations"][1]["slug"] = "cfo"


def _case_field_the_refresh_drops(cat):
    """A non-scraped field that nothing preserves. `manual: false` is not the flag that
    keeps a row whole, so the row is rebuilt from the scrape and the key disappears —
    the silent-loss failure mode CURATED_KEYS exists to prevent, in a field that is not
    in it."""
    cat["organizations"][1]["manual"] = False


def _case_row_the_simulation_cannot_run_on(cat):
    """A row with no name. The refresh derives a slug from the name, so there is nothing
    to simulate — and a row that could not be evaluated must be REPORTED as unevaluated,
    never left out of the report as though it had passed."""
    del cat["organizations"][0]["name"]


def _case_registry_emptied(cat):
    """Every row gone. A gate that reports a registry with no bodies in it as clean is a
    gate that passes without checking anything — and every rule below is vacuously true of
    an empty list, so this one has to be stated separately."""
    cat["organizations"] = []


_CASES = [
    ("undeclared-field", _case_undeclared_field, "declared-field"),
    ("registry-emptied", _case_registry_emptied, "registry-populated"),
    ("row-the-simulation-cannot-run-on", _case_row_the_simulation_cannot_run_on,
     "survives-refresh"),
    ("slug-the-scrape-would-not-produce", _case_slug_the_scrape_would_not_produce,
     "survives-refresh"),
    ("field-the-refresh-drops", _case_field_the_refresh_drops, "survives-refresh"),
    ("parent-slug-resolves-to-nothing", _case_parent_slug_resolves_to_nothing,
     "parent-resolves"),
    ("parent-chapter-disagrees", _case_parent_chapter_disagrees, "parent-agrees"),
    ("duplicate-slug", _case_duplicate_slug, "unique-slug"),
    ("duplicate-chapter", _case_duplicate_chapter, "unique-chapter"),
    ("missing-required-field", _case_missing_required_field, "required-field"),
    ("missing-oar-name", _case_missing_oar_name, "required-field"),
    # The SAME mutation as row-the-simulation-cannot-run-on above, asserted against the
    # other rule it has to trip. Deleting `name` breaks two things at once — nothing can be
    # simulated for the row, AND a required field is gone — and a case asserts one rule, so
    # covering both takes two entries. `name` and `oar_name` are the two names a consumer
    # can resolve a body by, and each is required on every row.
    ("missing-name", _case_row_the_simulation_cannot_run_on, "required-field"),
    ("row-is-not-a-mapping", _case_row_is_not_a_mapping, "readable-row"),
]


# THE TWO WAYS A CURATED FIELD GOES MISSING FROM CURATED_KEYS. Neither is expressible as a
# registry row, because both are a statement about the FIELDS table — so each is a whole
# alternative declaration, checked against a registry that is otherwise clean. This is
# acceptance criterion 5 of issue #165 kept permanently: deriving CURATED_KEYS from FIELDS
# is only worth doing if the derivation going wrong is caught.
#
#   not curated     the field is declared, but as something other than CURATED, so
#                   preserve_curated() never carries it forward and --refresh drops it.
#   called scraped  worse, because it looks preserved: the field is left out of the
#                   survival comparison as if the scrape rewrote it, while scraped_entry()
#                   — the only thing that writes a scraped field — never produces it.
_PROOFS = [
    ("curated-field-declared-manual-flag",
     dict(FIELDS, budget_agency_code=Field(MANUAL_FLAG, required=False)),
     "survives-refresh"),
    ("curated-field-declared-scraped",
     dict(FIELDS, budget_agency_code=Field(SCRAPED, required=False)),
     "scraped-field"),
]


def _proof_refresh_rejects_an_undeclared_scraped_field() -> int:
    """--refresh's own half of the declaration, which --check cannot reach: it reads
    committed data and never runs a scrape, so a field the SCRAPE started writing without
    declaring it can only be caught where the scrape runs. Demonstrated failing here
    because a guard nobody has watched fire is not known to fire.

    The probe field is MADE UP, and it has to be. This proof used to name `oar_name` — a
    field ADR 0003 said the registry was going to carry — and the day it started carrying
    one the proof stopped proving anything: the guard correctly said nothing, and the only
    reason that surfaced as a red build rather than a quiet pass is that the assertion is on
    the guard firing. Any real field is a field FIELDS may legitimately declare tomorrow."""
    try:
        assert_scrape_declared([{"slug": "a-body", "headcount": 412}])
    except SystemExit as e:
        return 0 if "headcount" in str(e) else 1
    print("FAIL refresh-rejects-undeclared-scraped-field: the scrape guard did not fire",
          file=sys.stderr)
    return 1


def selftest() -> int:
    bad = 0
    for name, declaration, rule in _PROOFS:
        failures = check_registry(_fixture(), fields=declaration)
        if not any(f.rule == rule for f in failures):
            print(f"FAIL {name}: expected a [{rule}] failure, got {failures}",
                  file=sys.stderr)
            bad += 1
    bad += _proof_refresh_rejects_an_undeclared_scraped_field()
    for name, mutate, rule in _CASES:
        cat = _fixture()
        assert not check_registry(cat), f"fixture does not pass cleanly ({name})"
        mutate(cat)
        failures = check_registry(cat)
        if not any(f.rule == rule for f in failures):
            print(f"FAIL {name}: expected a [{rule}] failure, got {failures}",
                  file=sys.stderr)
            bad += 1
    print(f"{len(_CASES) + len(_PROOFS) + 1} violation(s) demonstrated failing"
          if not bad else f"{bad} rule(s) did not fire")
    return 1 if bad else 0


def main():
    if "--refresh" in sys.argv:
        cmd_refresh()
    elif "--check" in sys.argv:
        return cmd_check()
    elif "--selftest" in sys.argv:
        return selftest()
    elif len(sys.argv) > 1:
        cat = load()
        by_ch = {o["oar_chapter"]: o for o in cat["organizations"]}
        for o in find(" ".join(a for a in sys.argv[1:] if not a.startswith("--"))):
            tag = f"[ch. {o['oar_chapter']}"
            if o.get("parent_chapter"):
                p = by_ch.get(o["parent_chapter"])
                tag += f", sub-unit of {o['parent_chapter']} {p['name'] if p else '?'}"
            tag += "]"
            print(f"{o['slug']:50} {o['name']}  {tag}")
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
