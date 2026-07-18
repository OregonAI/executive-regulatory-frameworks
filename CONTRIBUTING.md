# Contributing

All changes land through pull requests. There are two human review gates, and CI enforces
provenance mechanically. AI agents are welcome contributors under the rules in
[AGENTS.md](AGENTS.md).

## Workflow

1. **Propose** — open an *intake request* issue (for new documents) or work an auto-opened
   *source change* issue (for upstream updates). New sources must first be added to
   the matching update group in `_meta/sources/` and approved by a maintainer **before any content is
   ingested** (review gate #1).
2. **Ingest** — follow `_meta/skills/intake.md`: fetch the pinned URL, snapshot it under
   `_meta/snapshots/`, record `retrieved` + `source_sha256`, fill the matching template
   from `_meta/templates/`, label every statement `[VERBATIM]` or `[SUMMARY]`.
3. **Verify & merge** — CI runs frontmatter validation, provenance/quote verification, and
   link checks; a CODEOWNER reviews against the PR checklist and merges (review gate #2).

## Definition of done (any content PR)

- [ ] Frontmatter complete and schema-valid (`python3 src/validate_frontmatter.py`)
- [ ] Source snapshot committed; `source_sha256` matches; every `[VERBATIM]` quote passes
      `python3 src/verify_provenance.py`
- [ ] Effective/reviewed/version dates transcribed from the source itself, not assumed
- [ ] Non-authoritative disclaimer block present at top of the document body
- [ ] `relationships` targets resolve; new document added to `llms.txt` and the directory
      `_index.md`
- [ ] Knowledge body `CHANGELOG.md` updated (Keep a Changelog format; change types:
      Added / Source-Updated / Superseded / Repealed / Removed / Verified / Fixed / Security)
- [ ] Agent-assisted commits carry an `Assisted-by:` trailer

## Branch protection (repository settings)

Maintainers should enable on `main`:

- Require a pull request before merging, with **at least 1 approving review**
- Require review from Code Owners
- Require status checks: `validate-frontmatter`, `verify-provenance`, `check-links`
- No force pushes

## Local setup

```bash
pip install pyyaml jsonschema
python3 src/validate_frontmatter.py
python3 src/verify_provenance.py
```
