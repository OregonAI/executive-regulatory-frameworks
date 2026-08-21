#!/usr/bin/env python3
"""Land `relations` beside `parent_slug` on every row of the agency registry.

  python3 src/expand_relations.py

THE EXPAND HALF OF ADR 0004's SPLIT. ADR 0004 replaces `parent_slug` with a relation that
names the parent, its kind and the authority establishing it, and the pointer says none of
that: "the Commodity Commissions are under the Department of Agriculture" and "the Highway
Division is under the Department of Transportation" are both true and are not the same
statement. So the relation lands in its own field FIRST, while `parent_slug` still holds
what it always held — nothing is removed and no consumer changes (#174 retires the
pointer). This script does the "first" part, once, over data that already exists.

WHAT THE RELATION SAYS TODAY, AND WHAT IT DOES NOT. Every entry this writes records the OAR
index's placement — the same fact `parent_slug` holds, because the index tree is where that
pointer came from — with `source: oar-index` and `kind: undetermined`. THE KIND IS NOT
GUESSED. Deciding between ADR 0004's two kinds turns on whether the body carries its own
admitting evidence, which is `enabling_authority`, which no row carries yet: 25 of the 81
children have their own statutory authority and 56 do not, and #173 is where that evidence
becomes kinds. Writing `part_of` on all 81 today would be 25 false statements about Oregon
law, and leaving the key off would let every consumer read the absence as whichever kind it
preferred. `undetermined` is the one true thing to say, and `catalog_agencies.py --check`
reports how many rows are in that state on every run rather than letting it go quiet.

NOR DOES IT INVENT A SECOND SOURCE. A body may hold more than one relation, because DAS,
the OAR index and statute may place it under different parents and ADR 0003 keeps that
disagreement rather than reconciling it. This script has read exactly one of those sources,
so it writes exactly one entry per child. The seven Health Licensing Office boards are the
worked example: the OAR index files them directly under the Oregon Health Authority, while
their names say `Oregon Health Authority, Health Licensing Office, Board of Cosmetology` and
ADR 0004 reads that as two hops between three bodies. The Health Licensing Office IS in the
registry, so recording the second hop needs only evidence and no new machinery — a relation
whose target is itself a body holding a relation is an ordinary relation, and three-level
nesting stopped being a special case the moment the field existed. Until that evidence is
read, this file says what the index says and says whose reading it is.

WHY A SCRIPT AND NOT A --refresh. `catalog_agencies.py --refresh` writes these entries from
now on (`set_index_relations`), but a refresh re-fetches all 189 chapter pages from
oregon.public.law and rewrites every row from what that mirror serves TODAY. Adding a field
to committed data is not a reason to re-open what every other field says, and the diff of
"one new key per row" is one a human can read.

RE-RUNNABLE AND IDEMPOTENT. A row that already carries `relations` is left exactly as it is
— the list is not re-derived from `parent_slug`, because it is the one field on the row that
holds curation the scrape never produced, and re-deriving it would delete a statute-sourced
entry the way #178's `note` deletes a hand-written note. So a second run writes the same
bytes as the first, and re-running it is how you check that it landed. It carries no
`--check` of its own: that every row has `relations`, that every relation resolves, and that
the OAR-index entry agrees with `parent_slug` are all rules of the registry's contract,
gated on every PR by `catalog_agencies.py --check` — and a fact stated by two gates is a
fact that can be true in one and false in the other.
"""
import sys

import yaml

from catalog_agencies import CATALOG, RELATION_KEY, relations_from_parent

# The key the new one lands after, so `relations` is printed beside the pointer it stands
# next to rather than at the end of the row — and so this file is byte-identical to the one
# a later --refresh writes, whose `scraped_entry()` puts it in exactly that place. A row
# that does not carry this key is BLOCKED rather than given the new one at the end (see
# `classify`): the placement would be right and the file would no longer be the one a
# refresh writes, which is a difference no reader sees and every comparison does.
AFTER_KEY = "parent_chapter"


def expanded(org: dict) -> dict:
    """One row with `relations` beside `parent_slug`, or unchanged if it already has some.

    Rebuilt key by key rather than assigned into, for the placement above. WHAT the relation
    says is `relations_from_parent()`'s answer and not this script's: the source of a
    placement depends on who is in a position to state it — the OAR index for a row the
    scrape produces, this registry itself for a `manual` row the index does not carry — and
    a second copy of that rule here is a second copy that can disagree with what --refresh
    writes. A row whose parent is null gets an EMPTY LIST: `[]` says this registry places
    the body under no other, which is what `parent_slug: null` says beside it, while an
    absent key would say nobody asked (CONTEXT.md)."""
    if RELATION_KEY in org:
        return org
    out = {}
    for key, value in org.items():
        out[key] = value
        if key == AFTER_KEY:
            out[RELATION_KEY] = relations_from_parent(org)
    return out


def classify(orgs: list):
    """(carries, children, unattached, blocked) — every row in exactly one of four states.

    `children` and `unattached` are separated because they are different claims and a human
    reading the report acts on them differently: 81 rows gain a relation naming a parent, and
    the rest gain an empty list saying this registry places them under nothing.

    `blocked` is the state that matters, and it is why this is a classification rather than
    a filter for rows lacking the key. A row with no `parent_slug` KEY has nothing to derive
    a relation from, and writing `[]` for it would publish "this body is under nothing" on
    the strength of a key nobody wrote — "could not check" reported as "is not there", which
    is the one substitution this repository never permits. A row with no `parent_chapter` is
    blocked for a smaller reason honestly stated: there is nowhere to put the new key that
    matches what --refresh writes, and appending it elsewhere would quietly break the one
    claim this script makes about the file it produces. Both are REPORTED under their own
    reason and neither is counted among the rows that came out clean, and NOTHING is written
    while one exists: a half-migrated registry is one where the population a consumer sees
    depends on which rows happened to be readable.
    """
    carries, children, unattached, blocked = [], [], [], []
    for i, org in enumerate(orgs):
        if not isinstance(org, dict):
            blocked.append((f"organizations[{i}]", "row is not a mapping"))
            continue
        row = org.get("slug") or f"organizations[{i}]"
        if RELATION_KEY in org:
            carries.append(row)
        elif "parent_slug" not in org:
            blocked.append((row, "no `parent_slug` to derive the relation from — an absent "
                                 "key is not a body placed under nothing"))
        elif AFTER_KEY not in org:
            blocked.append((row, f"no `{AFTER_KEY}` for the new key to land after, so the "
                                 "row this would write is not the row a --refresh writes"))
        elif org["parent_slug"] is None:
            unattached.append(row)
        elif isinstance(org["parent_slug"], str) and org["parent_slug"].strip():
            children.append(row)
        else:
            blocked.append((row, f"parent_slug is {org['parent_slug']!r}, which is neither "
                                 "a registry slug nor null"))
    return carries, children, unattached, blocked


def main() -> int:
    cat = yaml.safe_load(CATALOG.read_text())
    orgs = cat.get("organizations") or []
    carries, children, unattached, blocked = classify(orgs)

    for row, why in blocked:
        print(f"  FAIL {row}: {why}", file=sys.stderr)
    if blocked:
        print(f"\n{len(blocked)} row(s) cannot be migrated; nothing written",
              file=sys.stderr)
        return 1

    cat["organizations"] = [expanded(o) for o in orgs]
    # Same dump settings as catalog_agencies.py and expand_oar_name.py, so the file this
    # writes is byte-identical to the one a later --refresh would write, minus the values.
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    print(f"wrote relations onto {len(children) + len(unattached)} of {len(orgs)} "
          f"organizations: {len(children)} naming the parent their pointer already gives "
          f"them, every kind undetermined, and {len(unattached)} placed under nothing "
          f"({len(carries)} already carried relations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
