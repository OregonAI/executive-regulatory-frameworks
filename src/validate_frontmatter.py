#!/usr/bin/env python3
"""Validate content-file frontmatter against the JSON schema, check id/filename
agreement, the non-authoritative disclaimer, the relationships graph, and the
source manifest. See AGENTS.md.

Scope/scale:
  (default)          validate every content file (push-to-main / nightly)
  --changed [ref]    validate only files changed vs ref (merge-base origin/main
                     if omitted). The relationship-resolution universe is taken from
                     _meta/graph.json's nodes (fast) rather than re-parsing the whole
                     corpus, so a PR check stays flat as the corpus grows. The global
                     "every content-agency has a profile" cross-check needs a full
                     scan and is deferred to full runs.
  -j N / --jobs N    parallelize the per-file checks across N processes (default: CPUs)
"""
import argparse
import json
import multiprocessing as mp
import os
import re

import jsonschema
import yaml

from repo_lib import (
    CONTENT_DIRS, DIR_DOC_TYPE, REPO_ROOT, SCHEMA_DIR,
    Reporter, changed_content_files, content_files, parse_frontmatter, source_groups,
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

# Per-worker globals, populated by _init_worker so the schema validator/registry are
# built once per process instead of pickled per task.
_VALIDATOR = None
_AGENCY_REGISTRY = None


def _init_worker(schema_dict, agency_registry):
    global _VALIDATOR, _AGENCY_REGISTRY
    _VALIDATOR = jsonschema.Draft202012Validator(schema_dict)
    _AGENCY_REGISTRY = agency_registry


def check_file(path):
    """Per-file frontmatter checks. Returns (rel, findings, doc_id, agency) where
    findings is a list of ('error'|'warn', message). Relationship-target resolution is
    NOT done here (needs the corpus-wide id set); handled by the caller."""
    rel = path.relative_to(REPO_ROOT)
    findings = []
    try:
        fm, body = parse_frontmatter(path)
    except ValueError as e:
        return rel, [("error", str(e))], None, None

    for err in sorted(_VALIDATOR.iter_errors(fm), key=str):
        where = "/".join(str(x) for x in err.path) or "(root)"
        findings.append(("error", f"schema: {where}: {err.message}"))
    if fm.get("id") != path.stem:
        findings.append(("error", f"id '{fm.get('id')}' != filename stem '{path.stem}'"))
    if "NON-AUTHORITATIVE" not in body:
        findings.append(("error", "missing NON-AUTHORITATIVE disclaimer block in body"))

    agency = fm.get("agency")
    if agency not in AGENCY_SPECIAL and agency not in _AGENCY_REGISTRY:
        findings.append(("error", f"agency '{agency}' is not 'statewide'/'external' and not in "
                        "the agency registry (_meta/catalog/agencies.yml — refresh with "
                        "src/catalog_agencies.py if the state added/renamed this org)"))

    # Directory <-> doc_type: a document may only live in the one knowledge-body
    # directory designated for its doc_type (see DIR_DOC_TYPE above). The knowledge-body
    # directory is the top-level one (statutes/, rules/, ...) or, for agency-scoped docs,
    # the directory right after agencies/<agency>/ — rules and standards nest further
    # (rules/<ch>/<div>/, standards/<family>/), so we can't just check path.parent.
    parts = rel.parts
    body_dir = parts[2] if parts[0] == "agencies" and len(parts) > 2 else parts[0]
    doc_type = fm.get("doc_type")
    expected_dir = next((d for d, dt in DIR_DOC_TYPE.items() if dt == doc_type), None)
    if body_dir in DIR_DOC_TYPE:
        if DIR_DOC_TYPE[body_dir] != doc_type:
            findings.append(("error", f"doc_type '{doc_type}' does not belong in '{body_dir}/' "
                            f"(expected doc_type '{DIR_DOC_TYPE[body_dir]}')"))
    elif expected_dir is not None:
        findings.append(("error", f"doc_type '{doc_type}' belongs under a '{expected_dir}/' "
                        f"directory, not '{body_dir}/'"))

    # Procedures are named *_pr; policies must not be (the exact mislabel class this
    # check was added for: a procedure filed with doc_type: policy).
    is_pr_name = path.stem.endswith("_pr")
    if doc_type == "procedure" and not is_pr_name:
        findings.append(("error", "doc_type: procedure but filename does not end in '_pr'"))
    if doc_type == "policy" and is_pr_name:
        findings.append(("error", "filename ends in '_pr' but doc_type is 'policy' (should be 'procedure')"))

    return rel, findings, fm.get("id"), agency


def _relationship_findings(paths, universe):
    """Slug-shaped relationship targets must resolve to an in-repo document id;
    citation-shaped targets (e.g. 'ORS 276A.300') are allowed as forward references."""
    out = []
    for path in paths:
        rel = path.relative_to(REPO_ROOT)
        try:
            fm, _ = parse_frontmatter(path)
        except ValueError:
            continue
        for edge, targets in (fm.get("relationships") or {}).items():
            for t in targets or []:
                if t in universe:
                    continue
                if SLUG_RE.match(t):
                    out.append((rel, "error", f"relationships.{edge}: '{t}' does not resolve to any document"))
                else:
                    out.append((rel, "warn", f"relationships.{edge}: '{t}' is a citation, not yet ingested"))
    return out


def _graph_node_ids():
    """All document ids known to the (CI-fresh) authority graph — a fast corpus-wide
    universe for relationship resolution without re-parsing every frontmatter."""
    gpath = REPO_ROOT / "_meta/graph.json"
    if not gpath.is_file():
        return set()
    return {n["id"] for n in json.loads(gpath.read_text()).get("nodes", [])}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--changed", nargs="?", const="", metavar="REF",
                    help="validate only files changed vs REF (default: merge-base with origin/main)")
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1,
                    help="worker processes (default: all CPUs)")
    args = ap.parse_args()

    scoped = args.changed is not None
    if scoped:
        paths = changed_content_files(args.changed or None)
        if not paths:
            print("No changed content files to validate.")
            # still run the cheap global manifest/profile-schema checks below
    else:
        paths = list(content_files())

    r = Reporter()
    doc_schema = json.loads((SCHEMA_DIR / "document.frontmatter.schema.json").read_text())
    agency_registry = _agency_registry()

    # Per-file checks (parallel).
    docs = {}          # id -> rel, for scanned files
    content_agencies = set()
    jobs = max(1, args.jobs)
    if jobs == 1 or len(paths) < 50:
        _init_worker(doc_schema, agency_registry)
        results = [check_file(p) for p in paths]
    else:
        # fork so workers inherit loaded modules; CI (3.12) forks by default, 3.14 forkservers.
        ctx = mp.get_context("fork")
        with ctx.Pool(jobs, initializer=_init_worker,
                      initargs=(doc_schema, agency_registry)) as pool:
            results = list(pool.imap_unordered(check_file, paths, chunksize=64))
    for rel, findings, doc_id, agency in results:
        for level, msg in findings:
            (r.error if level == "error" else r.warn)(rel, msg)
        if doc_id is not None:
            docs[doc_id] = rel
        if agency in agency_registry:
            content_agencies.add(agency)

    # Relationships graph resolution. Universe = graph nodes (corpus-wide, fast) plus
    # whatever we just scanned; in full mode the scanned ids are a superset, so behavior
    # is unchanged, while in --changed mode we still resolve targets against the whole corpus.
    universe = _graph_node_ids() | set(docs)
    for rel, level, msg in _relationship_findings(paths, universe):
        (r.error if level == "error" else r.warn)(rel, msg)

    # Agency profiles: schema-valid; every key must be a registry slug (no orphans);
    # every agency that actually has in-repo content must have a profile entry — profiles
    # are the context layer for the data, so they may not silently lag onboarding. (Stub
    # entries with governance: unclassified satisfy this; the review queue surfaces them
    # as curation debt.) The content-agency coverage cross-check needs a full corpus scan,
    # so under --changed it is deferred to full runs.
    try:
        prof_schema = json.loads((SCHEMA_DIR / "agency-profile.schema.json").read_text())
        prof_data = yaml.safe_load((REPO_ROOT / "_meta/agency-profiles.yml").read_text())
        for err in sorted(jsonschema.Draft202012Validator(prof_schema).iter_errors(prof_data), key=str):
            r.error("_meta/agency-profiles.yml", f"schema: {err.message[:160]}")
        prof_keys = set((prof_data.get("profiles") or {}).keys())
        for k in sorted(prof_keys - agency_registry):
            r.error("_meta/agency-profiles.yml", f"profile key '{k}' is not a registry slug")
        if not scoped:
            for a in sorted(content_agencies - prof_keys):
                r.error("_meta/agency-profiles.yml",
                        f"agency '{a}' has in-repo content but no profile entry")
    except FileNotFoundError as e:
        r.error("_meta/agency-profiles.yml", f"missing: {e}")

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

    scope = f"{len(paths)} changed" if scoped else f"{len(paths)}"
    r.finish(f"OK: {scope} content file(s) validated across {', '.join(CONTENT_DIRS)}.")


if __name__ == "__main__":
    main()
