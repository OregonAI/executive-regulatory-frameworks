#!/usr/bin/env python3
"""Populate _meta/catalog/agencies.yml — the canonical registry of Oregon agencies and
their sub-units, grounded in the OAR chapter assignment scheme as presented by
https://oregon.public.law/rules.

  python3 src/catalog_agencies.py --refresh
  python3 src/catalog_agencies.py "<search term>"   # look up a slug

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
from datetime import date
from html import unescape

import yaml

from repo_lib import REPO_ROOT

BASE = "https://oregon.public.law"
INDEX_URL = f"{BASE}/rules"
CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"
UA = "oregon-policy-repo (+https://github.com/morficflux/oregon-policy-repo)"

ENTRY_RE = re.compile(
    r'<dt class="col-sm-2">[^<]*</dt>\s*'
    r'<dd class="col-sm-10">(?:<a href="/rules/oar_chapter_(\d+[a-z]?)">(.*?)</a>'
    r'|([^<]+?)(?=<div class="card))', re.S)
CARD_RE = re.compile(r'<div class="card[^"]*quasi-sub-chapter"')
TITLE_RE = re.compile(r"<title>OAR Chapter \d+[a-zA-Z]? \W (.*?)</title>", re.S)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


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
        orgs[i] = {"slug": slugify(name), "name": name, "oar_chapter": ch,
                   "raw_index_name": index_name, "source_url": url}
        if note:
            orgs[i]["note"] = note
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
        orgs[i] = {"slug": slugify(name), "name": name, "oar_chapter": None,
                   "raw_index_name": index_name, "source_url": INDEX_URL}
        if note:
            orgs[i]["note"] = note

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
        else:
            orgs[i]["parent_slug"] = None
            orgs[i]["parent_chapter"] = None

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
                 "slug here."),
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


def main():
    if "--refresh" in sys.argv:
        cmd_refresh()
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


if __name__ == "__main__":
    main()
