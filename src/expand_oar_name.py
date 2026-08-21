#!/usr/bin/env python3
"""Land `oar_name` beside `name` on every row of the agency registry.

  python3 src/expand_oar_name.py           # write oar_name into agencies.yml
  python3 src/expand_oar_name.py --check   # report rows that carry no oar_name

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
one. So a second run writes the same bytes as the first, and the check below is a
first-class mode rather than something to eyeball. The CI gate is
`catalog_agencies.py --check`, which requires `oar_name` on every row; `--check` here is
this script's own before/after statement, and the place a row it CANNOT migrate is named.

WHY EVERY ROW, INCLUDING THE MANUAL ONES. Seventeen rows are `manual` — bodies the chapter
scrape cannot see, most of them holding no OAR chapter at all. They still get an `oar_name`,
because the point of the field is that consumers can join on it: six of those slugs are ones
oregon-kpm's crosswalk resolves into today, and leaving them empty would mean the crosswalk
loses them the moment it moves off `name`. What the value asserts is what `name` asserted
before it — this is the string this registry has always published for that body — and no new
claim about the rules index is made by copying it.
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
    if "oar_name" in org or "name" not in org:
        return org
    out = {}
    for key, value in org.items():
        out[key] = value
        if key == "name":
            out["oar_name"] = value
    return out


def missing(orgs: list) -> list:
    """[(row id, why)] for every row this script cannot leave carrying an `oar_name`.

    A row with no `name` is REPORTED rather than skipped or given an empty string. There
    is nothing to copy and inventing one would publish a name no source states — and a row
    we could not migrate must never be counted among the ones that came out clean
    (CONTEXT.md: "could not check" is never reported as "is not there").
    """
    out = []
    for i, org in enumerate(orgs):
        if not isinstance(org, dict):
            out.append((f"organizations[{i}]", "not a mapping"))
        elif "oar_name" not in org and not isinstance(org.get("name"), str):
            out.append((org.get("slug") or f"organizations[{i}]",
                        "no `name` to take an OAR name from"))
    return out


def main() -> int:
    check = "--check" in sys.argv
    cat = yaml.safe_load(CATALOG.read_text())
    orgs = cat.get("organizations") or []

    problems = missing(orgs)
    for row, why in problems:
        print(f"  FAIL {row}: {why}", file=sys.stderr)

    if check:
        without = [o for o in orgs
                   if not isinstance(o, dict) or "oar_name" not in o]
        for o in without:
            row = o.get("slug", "?") if isinstance(o, dict) else o
            print(f"  FAIL {row}: no oar_name", file=sys.stderr)
        if without or problems:
            print(f"\n{len(without)} of {len(orgs)} row(s) carry no oar_name",
                  file=sys.stderr)
            return 1
        print(f"{len(orgs)} rows carry oar_name")
        return 0

    if problems:
        print(f"\n{len(problems)} row(s) cannot be migrated; nothing written",
              file=sys.stderr)
        return 1

    added = sum(1 for o in orgs if "oar_name" not in o)
    cat["organizations"] = [expanded(o) for o in orgs]
    # Same dump settings as catalog_agencies.py and link_budget_codes.py, so the file this
    # writes is byte-identical to the one a later --refresh would write, minus the values.
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    print(f"wrote oar_name onto {added} of {len(orgs)} organizations "
          f"({len(orgs) - added} already had one)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
