#!/usr/bin/env python3
"""Populate _meta/catalog/agencies.yml — the canonical registry of Oregon executive-
branch agencies/boards/commissions, grounded in the state's own organization
directory (a public data.oregon.gov dataset, not a repo-invented list).

  python3 src/catalog_agencies.py --refresh

Source: https://data.oregon.gov/api/v3/views/wu8n-jqum/query.json (one field:
organization_name). Slugs are purely mechanical (lowercase; runs of non-alphanumeric
characters collapsed to one hyphen; trimmed) -- no reordering or prettification of the
state's inconsistent naming conventions ("X Department" vs "Department of X" vs
"X, Department of" all appear verbatim upstream). validate_frontmatter.py requires
every content file's agency: field to be 'statewide', 'external', or a slug from this
registry -- this is what makes agency values CI-enforced rather than free-typed.
Idempotent; rerun to pick up the state's own additions/renames."""
import json
import re
import sys
import urllib.request

import yaml

from repo_lib import REPO_ROOT

SOURCE_URL = "https://data.oregon.gov/api/v3/views/wu8n-jqum/query.json"
CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def cmd_refresh():
    req = urllib.request.Request(SOURCE_URL, headers={
        "User-Agent": "oregon-policy-repo (+https://github.com/morficflux/oregon-policy-repo)"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        rows = json.loads(resp.read())

    by_slug = {}
    dupes = []
    for r in rows:
        name = r["organization_name"].strip()
        slug = slugify(name)
        if slug in by_slug:
            dupes.append((slug, by_slug[slug], name))
            continue
        by_slug[slug] = name

    from datetime import date
    cat = {
        "note": ("Canonical registry of Oregon executive-branch agencies/boards/"
                 "commissions, grounded in the state's own organization directory "
                 "(not a repo-invented list). Slugs are mechanical (lowercased, "
                 "non-alnum runs -> one hyphen) -- no reordering of the source's "
                 "inconsistent name formats. validate_frontmatter.py requires every "
                 "content file's agency: field to resolve to 'statewide', 'external', "
                 "or a slug here."),
        "source_url": SOURCE_URL,
        "retrieved": date.today().isoformat(),
        "organizations": [{"slug": s, "name": by_slug[s]} for s in sorted(by_slug)],
    }
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    print(f"catalog: {len(by_slug)} organizations ({len(dupes)} name variants "
          f"collapsed to an existing slug)")
    for slug, kept, dropped in dupes:
        print(f"  {slug}: kept {kept!r}, also matched {dropped!r}")


def load():
    return yaml.safe_load(CATALOG.read_text())


def find(query: str, limit: int = 5):
    """Substring search over organization_name, for a human picking a slug."""
    q = query.lower()
    cat = load()
    return [o for o in cat["organizations"] if q in o["name"].lower()][:limit]


def main():
    if "--refresh" in sys.argv:
        cmd_refresh()
    elif len(sys.argv) > 1:
        for o in find(" ".join(a for a in sys.argv[1:] if not a.startswith("--"))):
            print(f"{o['slug']:55} {o['name']}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
