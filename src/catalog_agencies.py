#!/usr/bin/env python3
"""Populate _meta/catalog/agencies.yml — the canonical registry of Oregon executive-
branch agencies/boards/commissions, grounded in the Secretary of State's own Blue Book
directory (not a repo-invented list).

  python3 src/catalog_agencies.py --refresh

Source: https://sos.oregon.gov/blue-book/government/pages/state-agencies.aspx — same
data-tables-web-part SharePoint pattern as the OAM/DAS-policies/executive-order
listings (list /blue-book/government/Lists/Agencies, "Public" view), fetched via
RenderListDataAsStream, never scraped from the JS-rendered page.

An earlier registry sourced from a data.oregon.gov dataset was dropped 2026-07-18 as
unreliable ("unexpectedly garbage" per review) in favor of this one.

Name reconstruction: the Blue Book's own Title field inverts many names around a
comma for its own sort order (e.g. "Administrative Services, Department of"). This is
purely mechanical, not judgment: split on the FIRST comma and swap the two halves
("X, Y" -> "Y X"). ~14 rows are a division/program within a larger department and
carry a trailing " - PARENTABBR" (e.g. "Archives Division - SOS") -- that suffix is
stripped into a separate parent_abbr field before the comma-swap, not reordered into
the name. raw_title (the Title exactly as printed) and blue_book_url (the row's own
page) are kept alongside for transparency.

validate_frontmatter.py requires every content file's agency: field to be 'statewide',
'external', or a slug from this registry -- this is what makes agency values
CI-enforced rather than free-typed. Idempotent; rerun to pick up the state's own
additions/renames."""
import json
import re
import sys
import urllib.request
from datetime import date

import yaml

from repo_lib import REPO_ROOT

WEB = "/blue-book/government"
LIST = "/blue-book/government/Lists/Agencies"
PUBLIC_VIEW = "4b549acc-20aa-4f50-9034-9ac376b4b812"
SOURCE_URL = "https://sos.oregon.gov/blue-book/government/pages/state-agencies.aspx"
CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"

PARENT_SUFFIX_RE = re.compile(r"\s*[-–]\s*([A-Z]{2,8})$")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def clean_ws(s: str) -> str:
    s = s.replace("﻿", "").replace("​", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def reconstruct(raw_title: str):
    """(name, parent_abbr) from the Blue Book's raw Title."""
    t = clean_ws(raw_title)
    parent = None
    m = PARENT_SUFFIX_RE.search(t)
    if m:
        parent = m.group(1)
        t = t[: m.start()].strip()
    if "," in t:
        a, b = t.split(",", 1)
        t = f"{b.strip()} {a.strip()}".strip()
    return t, parent


def fetch_rows():
    url = f"https://sos.oregon.gov{WEB}/_api/web/GetList('{LIST}')/RenderListDataAsStream?View={PUBLIC_VIEW}"
    body = b'{"parameters":{"__metadata":{"type":"SP.RenderListDataParameters"},"RenderOptions":2}}'
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": "oregon-policy-repo (+https://github.com/morficflux/oregon-policy-repo)",
        "Accept": "application/json;odata=verbose",
        "Content-Type": "application/json;odata=verbose"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["Row"]


def cmd_refresh():
    rows = fetch_rows()
    by_slug = {}
    dupes = []
    for r in rows:
        raw_title = r["Title"]
        name, parent = reconstruct(raw_title)
        slug = slugify(name)
        entry = {"slug": slug, "name": name, "parent_abbr": parent,
                 "raw_title": raw_title,
                 "blue_book_url": f"https://sos.oregon.gov{r['link']}"}
        if slug in by_slug:
            dupes.append((slug, by_slug[slug]["name"], name))
            continue
        by_slug[slug] = entry

    cat = {
        "note": ("Canonical registry of Oregon executive-branch agencies/boards/"
                 "commissions/divisions, grounded in the Secretary of State's Blue "
                 "Book directory (an earlier data.oregon.gov-sourced registry was "
                 "dropped 2026-07-18 as unreliable). Names are mechanically "
                 "reconstructed from the Blue Book's comma-inverted Title field "
                 "(first-comma split-and-swap; a trailing ' - PARENTABBR' on ~14 "
                 "division/program rows is captured as parent_abbr, not reordered "
                 "into the name). validate_frontmatter.py requires every content "
                 "file's agency: field to resolve to 'statewide', 'external', or a "
                 "slug here."),
        "source_url": SOURCE_URL,
        "retrieved": date.today().isoformat(),
        "organizations": [by_slug[s] for s in sorted(by_slug)],
    }
    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    print(f"catalog: {len(by_slug)} organizations from {len(rows)} rows "
          f"({len(dupes)} name variants collapsed to an existing slug)")
    for slug, kept, dropped in dupes:
        print(f"  {slug}: kept {kept!r}, also matched {dropped!r}")


def load():
    return yaml.safe_load(CATALOG.read_text())


def find(query: str, limit: int = 5):
    """Substring search over the reconstructed name, for a human picking a slug."""
    q = query.lower()
    cat = load()
    return [o for o in cat["organizations"] if q in o["name"].lower()][:limit]


def main():
    if "--refresh" in sys.argv:
        cmd_refresh()
    elif len(sys.argv) > 1:
        for o in find(" ".join(a for a in sys.argv[1:] if not a.startswith("--"))):
            print(f"{o['slug']:50} {o['name']}"
                  + (f"  [{o['parent_abbr']}]" if o.get("parent_abbr") else ""))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
