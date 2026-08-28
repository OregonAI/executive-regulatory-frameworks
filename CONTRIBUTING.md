# Contributing

All changes land through pull requests. There are two human review gates, and CI enforces
provenance mechanically. AI agents are welcome contributors under the rules in
[AGENTS.md](AGENTS.md).

## Workflow

1. **Propose** — open an *intake request* issue (for new documents) or work a source-change issue (opened when someone runs `detect-upstream-changes`; it no
   longer runs on a cron) or an
   *source change* issue (for upstream updates). New sources must first be added to
   the matching update group in `_meta/sources/` and approved by a maintainer **before any content is
   ingested** (review gate #1).
2. **Ingest** — follow `_meta/skills/intake.md`: fetch the pinned URL, snapshot it under
   `_meta/snapshots/`, record `retrieved` + `source_sha256`, fill the matching template
   from `_meta/templates/`, label every statement `[VERBATIM]` or `[SUMMARY]`.
3. **Verify & merge** — CI runs frontmatter validation (including relationship-graph
   integrity) and provenance/quote verification. Link checking runs weekly and on demand,
   not on PRs. a CODEOWNER reviews against the PR checklist and merges (review gate #2).

## Definition of done (any content PR)

- [ ] Frontmatter complete and schema-valid (`corpus-validate-frontmatter --config
      _meta/corpus.yml`)
- [ ] Source snapshot committed; `source_sha256` matches; every `[VERBATIM]` quote passes
      `corpus-verify-provenance --config _meta/corpus.yml`
- [ ] Effective/reviewed/version dates transcribed from the source itself, not assumed
- [ ] Non-authoritative disclaimer block present at top of the document body
- [ ] `relationships` targets resolve; new document added to `llms.txt` and the directory
      `_index.md`
- [ ] Knowledge body `CHANGELOG.md` updated (Keep a Changelog format; change types:
      Added / Source-Updated / Superseded / Repealed / Removed / Verified / Fixed / Security)
- [ ] Agent-assisted commits carry `Co-Authored-By:`/`Claude-Session:` trailers (see
      AGENTS.md, Commit conventions)

## Branch protection (repository settings)

Maintainers should enable on `main`:

- Require a pull request before merging, with **at least 1 approving review**
- Require review from Code Owners
- Require status checks: `validate-frontmatter`, `verify-provenance`
  (do NOT add `check-links` — it has no `pull_request` trigger, so requiring it leaves
  every PR pending forever with no error to explain why. Relationship-graph integrity is
  covered anyway: `corpus-validate-frontmatter` runs it on every PR.)
- No force pushes

## Local setup

```bash
pip install -r requirements.txt
corpus-validate-frontmatter --config _meta/corpus.yml
corpus-verify-provenance --config _meta/corpus.yml
```
