#!/usr/bin/env python3
"""Scaffold a new agency into the repo — the mechanical first step of onboarding.

  python3 src/new_agency.py <slug> --title "Oregon Department of X" \\
      [--bodies policies,procedures] [--abbr ODX]

Creates (never overwrites; idempotent — re-run to add bodies later):
  agencies/<slug>/_index.md                 agency-level map
  agencies/<slug>/<body>/_index.md          per-body index stub
  agencies/<slug>/<body>/CHANGELOG.md       keep-a-changelog header
  _meta/sources/<slug>-policies.yml         update-group stub (kind/upstream TODO)

It does NOT ingest anything and does NOT create discovery catalogs — those come from
the agency's real listing of record (find the data-tables-web-part SharePoint config
behind its oregon.gov policy page; see AGENTS.md and _meta/skills/intake.md). The
printed next-steps checklist walks the rest of the onboarding flow."""
import argparse
import re
import sys
from datetime import date
from pathlib import Path

from repo_lib import DIR_DOC_TYPE, JURISDICTION_WIDE_DIRS, REPO_ROOT

TODAY = date.today().isoformat()
AGENCY_BODIES = sorted(d for d in DIR_DOC_TYPE if d not in JURISDICTION_WIDE_DIRS)


def body_index(slug, title, body):
    doc_type = DIR_DOC_TYPE[body]
    return f"""# {title} — {body.replace('-', ' ')} — index

{body.replace('-', ' ').capitalize()} (`doc_type: {doc_type}`) issued by {title}
(`agency: {slug}`). **Non-authoritative copies** — see [AGENTS.md](../../../AGENTS.md).

<!-- TODO: after the first ingest batch, describe the listing of record here and add
the document table (see agencies/das/policies/_index.md for the pattern). -->

| Citation | Title | Status | Path |
|---|---|---|---|
| _(none ingested yet)_ | | | |
"""


def body_changelog(title, body):
    return f"""# Changelog — {title} {body.replace('-', ' ')}

All notable changes to the curated copies in this directory. Format based on
[Keep a Changelog](https://keepachangelog.com/); change types: Added, Source-Updated,
Superseded, Repealed, Removed, Verified, Fixed, Security. This repo is non-authoritative;
dates below are repo-curation dates, not official effective dates (those live in each
file's frontmatter).

## [Unreleased]
"""


def agency_index(slug, title, bodies):
    lines = "\n".join(f"- [{b.replace('-', ' ').capitalize()}]({b}/_index.md)"
                      for b in bodies)
    return f"""# {title} (`{slug}`) — index

Knowledge bodies for {title}. **Non-authoritative copies.**

{lines}

<!-- TODO: one-paragraph orientation — what this agency does, which ORS chapters it
derives authority from, and how its policy stack is organized. -->
"""


def group_stub(slug, title):
    return f"""group: {slug}-policies
title: {title} policies
kind: content-hash
recheck: monthly
last_checked: '{TODAY}'
upstream_signal: 'TODO: find the listing of record for this agency''s policies (usually a
  data-tables-web-part SharePoint list behind its oregon.gov policy page — see AGENTS.md
  "Checking for / applying upstream changes"), switch kind to sp-listing, and add
  listing_snapshot. Until then this group only re-hashes its member sources.'
sources: []
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", help="agency slug (lowercase, e.g. 'odot', 'oha')")
    ap.add_argument("--title", required=True, help='full name, e.g. "Oregon Department of Transportation"')
    ap.add_argument("--bodies", default="policies,procedures",
                    help=f"comma-separated from: {','.join(AGENCY_BODIES)}")
    args = ap.parse_args()

    slug = args.slug
    if not re.fullmatch(r"[a-z][a-z0-9-]*", slug):
        sys.exit(f"slug must be lowercase [a-z0-9-], got {slug!r}")
    bodies = [b.strip() for b in args.bodies.split(",") if b.strip()]
    bad = [b for b in bodies if b not in AGENCY_BODIES]
    if bad:
        sys.exit(f"unknown bodies {bad}; valid: {AGENCY_BODIES}")

    agency_dir = REPO_ROOT / "agencies" / slug
    made = []

    def write(path: Path, content: str):
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        made.append(str(path.relative_to(REPO_ROOT)))

    for b in bodies:
        write(agency_dir / b / "_index.md", body_index(slug, args.title, b))
        write(agency_dir / b / "CHANGELOG.md", body_changelog(args.title, b))
    existing_bodies = sorted(d.name for d in agency_dir.iterdir() if d.is_dir())
    # agency index lists every body present on disk (re-runs pick up additions)
    idx = agency_dir / "_index.md"
    if not idx.exists():
        write(idx, agency_index(slug, args.title, existing_bodies))
    write(REPO_ROOT / "_meta/sources" / f"{slug}-policies.yml",
          group_stub(slug, args.title))

    for p in made:
        print(f"created {p}")
    if not made:
        print("nothing to create (all paths already exist)")
    print(f"""
Next steps (see _meta/skills/intake.md for the full gated flow):
 1. Find the agency's listing of record (its oregon.gov policy page; check for a
    data-tables-web-part SharePoint config) and build a discovery catalog under
    _meta/catalog/ — REVIEW GATE #1: a human approves the list before any ingestion.
 2. Update _meta/sources/{slug}-policies.yml: real upstream_signal, kind (sp-listing
    if there's a listing), listing_snapshot.
 3. Ingest via the established pipelines (ingest_lib helpers; output_dir_for routes
    files). New ORS/OAR chapters go through catalog_ors.py / ingest_oar.py unchanged.
 4. After the batch: link_graph.py, review_queue.py, both validators, update llms.txt
    and the agency _index.md files (fill the TODO markers).""")


if __name__ == "__main__":
    main()
