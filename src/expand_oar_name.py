#!/usr/bin/env python3
"""Land `oar_name` beside `name` on every row of the agency registry.

  python3 src/expand_oar_name.py

THE EXPAND HALF OF ADR 0003's RENAME. ADR 0003 moves the OAR chapter title out of `name`
and makes `name` the statutory name, and the cost it names falls on the consumers:
`oregon-kpm`, `oregon-audits` and `oregon-budget` all resolve against `name` today, and a
crosswalk that keeps matching a string which quietly changed meaning is exactly the failure
those crosswalks exist to prevent. So the OAR name lands in its own field FIRST, while
`name` still holds it too — consumers move onto `oar_name` and are verified there before
anything about `name` changes. This script does the "first" part, once, over data that
already exists.

WHY A SCRIPT AND NOT A --refresh. `catalog_agencies.py --refresh` writes `oar_name` from
now on (it is a SCRAPED field), but a refresh re-fetches all 189 chapter pages from
oregon.public.law and rewrites every row from what that mirror serves TODAY. Adding a field
to committed data is not a reason to re-open what every other field says, and the diff of
"one new key per row" is one a human can read. This script therefore reads and writes only
`oar_name`, from the `name` already committed for that row.

RE-RUNNABLE AND IDEMPOTENT. A row that already carries `oar_name` is left exactly as it is
— the value is not re-derived from `name`, because after ADR 0003's later step the two stop
being the same string and re-deriving would overwrite the real OAR name with a statutory
one. So a second run writes the same bytes as the first, and re-running it is how you check
that it landed. It carries no `--check` of its own: whether every row has an `oar_name` is
already a rule of the registry's contract, gated on every PR by `catalog_agencies.py
--check`, and a fact stated by two gates is a fact that can be true in one and false in the
other.

WHY EVERY ROW, INCLUDING THE MANUAL ONES. Seventeen rows are `manual` — bodies the chapter
scrape cannot see, most of them holding no OAR chapter at all. They still get an `oar_name`,
because the point of the field is that consumers can join on it: those slugs include ones
oregon-kpm's agency crosswalk resolves into today (see preserve_manual in
catalog_agencies.py), and leaving them empty would mean the crosswalk loses them the moment
it moves off `name`. What the value asserts is what `name` asserted before it — this is the
string this registry publishes for that body — and copying it claims nothing about what the
rules index prints.
"""
import sys

import yaml

from repo_lib import REPO_ROOT

CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"


def expanded(org: dict) -> dict:
    """One row with `oar_name` beside `name`, or unchanged if it already has one.

    Rebuilt key by key rather than assigned into, so the new key lands NEXT TO `name` in
    the written file instead of at the end of the row. The registry is read by humans in
    review — a field whose whole purpose is to sit beside another one should be printed
    beside it.
    """
    if "oar_name" in org:
        return org
    out = {}
    for key, value in org.items():
        out[key] = value
        if key == "name":
            out["oar_name"] = value
    return out


def classify(orgs: list):
    """(carries, to_migrate, blocked) — every row in exactly one of three states.

    `blocked` is the one that matters, and it is why this is a classification rather than a
    filter for rows lacking the key. A row with no `name` has nothing to copy, and giving it
    an empty string would publish a name no source states; a row that is not a mapping
    cannot be read at all. Both are REPORTED under their own reason and neither is counted
    among the rows that came out clean, because a row we could not migrate is never a row
    that did not need migrating — the registry's rule that being absent means no evidence
    was found, "never that none was sought" (CONTEXT.md, *Agency registry*).

    `blocked` and `to_migrate` are separate for the same reason: "nothing can give this row
    an OAR name" and "nobody has yet" are different states, and a human acts on them
    differently.
    """
    carries, to_migrate, blocked = [], [], []
    for i, org in enumerate(orgs):
        if not isinstance(org, dict):
            blocked.append((f"organizations[{i}]", "row is not a mapping"))
        elif "oar_name" in org:
            carries.append(org)
        else:
            row = org.get("slug") or f"organizations[{i}]"
            if isinstance(org.get("name"), str):
                to_migrate.append(row)
            else:
                blocked.append((row, "no `name` to take an OAR name from"))
    return carries, to_migrate, blocked


def main() -> int:
    cat = yaml.safe_load(CATALOG.read_text())
    orgs = cat.get("organizations") or []
    carries, to_migrate, blocked = classify(orgs)

    for row, why in blocked:
        print(f"  FAIL {row}: {why}", file=sys.stderr)
    if blocked:
        print(f"\n{len(blocked)} row(s) cannot be migrated; nothing written",
              file=sys.stderr)
        return 1

    cat["organizations"] = [expanded(o) for o in orgs]
    # Same dump settings as catalog_agencies.py and link_budget_codes.py, so the file this
    # writes is byte-identical to the one a later --refresh would write, minus the values.
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    print(f"wrote oar_name onto {len(to_migrate)} of {len(orgs)} organizations "
          f"({len(carries)} already had one)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
