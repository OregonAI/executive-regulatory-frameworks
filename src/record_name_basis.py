#!/usr/bin/env python3
"""Land `name_basis` beside `name` on every row of the agency registry.

  python3 src/record_name_basis.py

THE PROMOTION HALF OF ADR 0003's RENAME, AND THE HONESTY IT COSTS. `expand_oar_name.py` did
the first half: the OAR chapter title landed in `oar_name` while `name` still held it too,
so consumers could move off `name` before it changed meaning. #187 moved the last two
OAR-derived joins. This is what is left — `name` is the STATUTORY name now (ADR 0003), and
189 rows are carrying a rules-index title under a field that says otherwise.

WHAT THIS SCRIPT DOES NOT DO IS INVENT ONE. Establishing a body's statutory name means
reading the authority that created it, and that is human work recorded in
`link_enabling_authority.py`'s reviewed table, one body at a time. What this does is make the
gap SAYABLE: every row it touches records `name_basis: unverified-oar-title`, which states
that nobody has established a statutory name for this body and that `name` still holds the
title the rules index prints.

WHY THAT IS THE WHOLE POINT. A row that quietly keeps its OAR title while the field's
documented meaning becomes "statutory name" is a false statement about Oregon law published
under provenance — and it is invisible, because the string does not change. "Established" and
"not yet established" must not be the same state, which is the rule this repository already
keeps for an unmapped DAS number (`link_budget_codes.py`), for an absent enabling authority
(CONTEXT.md: absence is never the claim that a body has none) and for a relation nobody has
decided the kind of (`undetermined`). This field is that rule applied to the name.

WHY A SCRIPT AND NOT A --refresh, for the reason `expand_oar_name.py` gives: a refresh
re-fetches all 170 chapter pages and rewrites every row from what the mirror serves today
— 170, not this registry's 189 total rows, for the same reason and checked the same way
`expand_oar_name.py`'s docstring is (#279) — and adding a key to committed data is not a
reason to re-open what every other field says. `catalog_agencies.py --refresh` writes this
key from now on, because `scraped_entry()` does.

RE-RUNNABLE AND IDEMPOTENT. A row that already carries `name_basis` is left exactly as it is,
whatever it says — a second run writes the same bytes as the first, and it can never
downgrade a statutory name that has since been established back to an unverified title. It
carries no `--check` of its own: whether every row states a basis, and whether the basis it
states is one the row can support, are rules of the registry's contract, gated on every PR by
`catalog_agencies.py --check`. A fact stated by two gates is a fact that can be true in one
and false in the other.

WHY EVERY ROW, INCLUDING THE MANUAL ONES, and including the 107 that carry a reviewed
enabling authority. Carrying an authority is not the same as having read a name off it: the
authority answers "what created this body", and the name answers "what does that authority
call it". 107 rows can now be reviewed for the second question; none of them has been by this
script, and recording them as anything but unverified would credit a review nobody did.
"""
import sys

import yaml

from catalog_agencies import NAME_BASIS_KEY, UNVERIFIED_OAR_TITLE
from repo_lib import REPO_ROOT

CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"


def recorded(org: dict) -> dict:
    """One row with `name_basis` beside `name`, or unchanged if it already states one.

    Rebuilt key by key rather than assigned into, so the new key lands NEXT TO `name` in the
    written file instead of at the end of the row — the same reason `expand_oar_name.py`
    rebuilds: a field whose whole purpose is to say what the field beside it holds should be
    printed beside it, because the registry is read by humans in review.
    """
    if NAME_BASIS_KEY in org:
        return org
    out = {}
    for key, value in org.items():
        out[key] = value
        if key == "name":
            out[NAME_BASIS_KEY] = UNVERIFIED_OAR_TITLE
    return out


def classify(orgs: list):
    """(states, to_migrate, blocked) — every row in exactly one of three states.

    `blocked` is the one that matters. A row with no `name` has nothing to state a basis
    ABOUT, and a row that is not a mapping cannot be read at all; writing
    `unverified-oar-title` onto either would record that somebody looked at a name that is
    not there. Both are REPORTED under their own reason and neither is counted among the rows
    that came out clean, because a row we could not migrate is never a row that did not need
    migrating (CONTEXT.md: "could not check" is never reported as "is not there").

    `blocked` and `to_migrate` are separate for the same reason `expand_oar_name.py` keeps
    them apart: "nothing can give this row a basis" and "nobody has yet" are different
    states, and a human acts on them differently.
    """
    states, to_migrate, blocked = [], [], []
    for i, org in enumerate(orgs):
        if not isinstance(org, dict):
            blocked.append((f"organizations[{i}]", "row is not a mapping"))
        elif NAME_BASIS_KEY in org:
            states.append(org)
        else:
            row = org.get("slug") or f"organizations[{i}]"
            # NAME READER — MACHINERY: this script asks whether the row HAS a name, so that
            # it can record where that name came from. It never reads what the name says, and
            # it is unaffected by ADR 0003 changing what the field means — which is the point
            # of the key it writes.
            if isinstance(org.get("name"), str):
                to_migrate.append(row)
            else:
                blocked.append((row, "no `name` to record a basis for"))
    return states, to_migrate, blocked


def main() -> int:
    cat = yaml.safe_load(CATALOG.read_text())
    orgs = cat.get("organizations") or []
    states, to_migrate, blocked = classify(orgs)

    for row, why in blocked:
        print(f"  FAIL {row}: {why}", file=sys.stderr)
    if blocked:
        print(f"\n{len(blocked)} row(s) cannot be migrated; nothing written",
              file=sys.stderr)
        return 1

    cat["organizations"] = [recorded(o) for o in orgs]
    # Same dump settings as catalog_agencies.py, link_budget_codes.py and
    # expand_oar_name.py, so the file this writes is byte-identical to the one a later
    # --refresh would write, minus the values.
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    print(f"recorded {NAME_BASIS_KEY} onto {len(to_migrate)} of {len(orgs)} organizations "
          f"({len(states)} already stated one)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
