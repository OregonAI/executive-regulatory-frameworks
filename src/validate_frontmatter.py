#!/usr/bin/env python3
"""Validate content-file frontmatter against the JSON schema, check id/filename
agreement, the non-authoritative disclaimer, the relationships graph, and the
source manifest. See AGENTS.md."""
import json
import re

import jsonschema
import yaml

from repo_lib import (
    CONTENT_DIRS, DIR_DOC_TYPE, REPO_ROOT, SCHEMA_DIR,
    Reporter, content_files, parse_frontmatter, source_groups,
)

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$")

# The 'agency:' field is grounded in the state's own organization directory (see
# src/catalog_agencies.py) rather than free-typed -- a hard error here is what makes
# that grounding real instead of a suggestion. 'statewide' covers jurisdiction-wide
# bodies (ORS/OAR/EO); 'external' covers third-party references.
AGENCY_SPECIAL = {"statewide", "external"}


def _agency_registry():
    cat = yaml.safe_load((REPO_ROOT / "_meta/catalog/agencies.yml").read_text())
    return {o["slug"] for o in cat["organizations"]}

# DIR_DOC_TYPE (imported above) maps directory name -> the one doc_type allowed to
# live there. Enforced here as a hard error (not a warning) so a document can never
# be merged into the wrong knowledge body, regardless of which script or human
# created it. See src/ingest_lib.py output_dir_for() for the single place new
# ingestion code should derive the target directory from.


def main():
    r = Reporter()
    doc_schema = json.loads((SCHEMA_DIR / "document.frontmatter.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(doc_schema)
    agency_registry = _agency_registry()

    docs = {}
    for path in content_files():
        rel = path.relative_to(REPO_ROOT)
        try:
            fm, body = parse_frontmatter(path)
        except ValueError as e:
            r.error(rel, str(e))
            continue
        for err in sorted(validator.iter_errors(fm), key=str):
            where = "/".join(str(x) for x in err.path) or "(root)"
            r.error(rel, f"schema: {where}: {err.message}")
        if fm.get("id") != path.stem:
            r.error(rel, f"id '{fm.get('id')}' != filename stem '{path.stem}'")
        if "NON-AUTHORITATIVE" not in body:
            r.error(rel, "missing NON-AUTHORITATIVE disclaimer block in body")

        agency = fm.get("agency")
        if agency not in AGENCY_SPECIAL and agency not in agency_registry:
            r.error(rel, f"agency '{agency}' is not 'statewide'/'external' and not in "
                        "the agency registry (_meta/catalog/agencies.yml — refresh with "
                        "src/catalog_agencies.py if the state added/renamed this org)")

        # Directory <-> doc_type: a document may only live in the one knowledge-body
        # directory designated for its doc_type (see DIR_DOC_TYPE above). The
        # knowledge-body directory is the top-level one (statutes/, rules/, ...) or,
        # for agency-scoped docs, the directory right after agencies/<agency>/ — rules
        # and standards nest further (rules/<ch>/<div>/, standards/<family>/), so we
        # can't just check path.parent.
        parts = rel.parts
        body_dir = parts[2] if parts[0] == "agencies" and len(parts) > 2 else parts[0]
        doc_type = fm.get("doc_type")
        expected_dir = next((d for d, dt in DIR_DOC_TYPE.items() if dt == doc_type), None)
        if body_dir in DIR_DOC_TYPE:
            if DIR_DOC_TYPE[body_dir] != doc_type:
                r.error(rel, f"doc_type '{doc_type}' does not belong in '{body_dir}/' "
                            f"(expected doc_type '{DIR_DOC_TYPE[body_dir]}')")
        elif expected_dir is not None:
            r.error(rel, f"doc_type '{doc_type}' belongs under a '{expected_dir}/' "
                        f"directory, not '{body_dir}/'")

        # Procedures are named *_pr; policies must not be (the exact mislabel class
        # this check was added for: a procedure filed with doc_type: policy).
        is_pr_name = path.stem.endswith("_pr")
        if doc_type == "procedure" and not is_pr_name:
            r.error(rel, "doc_type: procedure but filename does not end in '_pr'")
        if doc_type == "policy" and is_pr_name:
            r.error(rel, "filename ends in '_pr' but doc_type is 'policy' (should be 'procedure')")

        docs[fm.get("id")] = rel

    # Relationships graph: slug-shaped targets must resolve to an in-repo document;
    # citation-shaped targets (e.g. "ORS 276A.300") are allowed as forward references.
    for path in content_files():
        rel = path.relative_to(REPO_ROOT)
        try:
            fm, _ = parse_frontmatter(path)
        except ValueError:
            continue
        for edge, targets in (fm.get("relationships") or {}).items():
            for t in targets or []:
                if t in docs:
                    continue
                if SLUG_RE.match(t):
                    r.error(rel, f"relationships.{edge}: '{t}' does not resolve to any document")
                else:
                    r.warn(rel, f"relationships.{edge}: '{t}' is a citation, not yet ingested")

    # Source groups
    group_schema = json.loads((SCHEMA_DIR / "source-group.schema.json").read_text())
    gvalidator = jsonschema.Draft202012Validator(group_schema)
    try:
        for gpath, gdata in source_groups():
            grel = gpath.relative_to(REPO_ROOT)
            for err in sorted(gvalidator.iter_errors(gdata), key=str):
                r.error(grel, f"schema: {err.message}")
            if gdata.get("group") != gpath.stem:
                r.error(grel, f"group '{gdata.get('group')}' != filename stem '{gpath.stem}'")
            if gdata.get("kind") == "sp-listing" and not gdata.get("listing_snapshot"):
                r.error(grel, "sp-listing group requires listing_snapshot")
    except Exception as e:
        r.error("_meta/sources", f"unreadable: {e}")

    n = len(list(content_files()))
    r.finish(f"OK: {n} content file(s) validated across {', '.join(CONTENT_DIRS)}.")


if __name__ == "__main__":
    main()
