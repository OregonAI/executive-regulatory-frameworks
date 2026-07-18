#!/usr/bin/env python3
"""Validate content-file frontmatter against the JSON schema, check id/filename
agreement, the non-authoritative disclaimer, the relationships graph, and the
source manifest. See AGENTS.md."""
import json
import re

import jsonschema
import yaml

from repo_lib import (
    CONTENT_DIRS, MANIFEST_PATH, REPO_ROOT, SCHEMA_DIR,
    Reporter, content_files, parse_frontmatter,
)

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$")


def main():
    r = Reporter()
    doc_schema = json.loads((SCHEMA_DIR / "document.frontmatter.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(doc_schema)

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

    # Source manifest
    manifest_schema = json.loads((SCHEMA_DIR / "source-manifest.schema.json").read_text())
    try:
        manifest = yaml.safe_load(MANIFEST_PATH.read_text())
        for err in sorted(jsonschema.Draft202012Validator(manifest_schema).iter_errors(manifest), key=str):
            r.error(MANIFEST_PATH.relative_to(REPO_ROOT), f"schema: {err.message}")
    except Exception as e:
        r.error(MANIFEST_PATH.relative_to(REPO_ROOT), f"unreadable: {e}")

    n = len(list(content_files()))
    r.finish(f"OK: {n} content file(s) validated across {', '.join(CONTENT_DIRS)}.")


if __name__ == "__main__":
    main()
