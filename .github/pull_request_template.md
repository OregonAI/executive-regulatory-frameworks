## What

<!-- Which documents are added/updated and why (link the intake or source-change issue). -->

## Verification checklist (content PRs)

- [ ] Source URL reachable and pinned; snapshot committed under `_meta/snapshots/`
- [ ] `retrieved` date and `source_sha256` recorded and match the snapshot
- [ ] Effective / reviewed / version dates transcribed exactly as printed in the source
- [ ] Every `[VERBATIM]` quote verified against the snapshot (CI: verify-provenance)
- [ ] Every `[SUMMARY]` sits under a heading tied to a cited section; no unsourced statements
- [ ] Frontmatter schema-valid; `relationships` targets resolve (CI: validate-frontmatter)
- [ ] Non-authoritative disclaimer block present at the top of each document
- [ ] Knowledge body `CHANGELOG.md` updated; new docs added to `llms.txt` and `_index.md`
- [ ] Agent-assisted commits carry an `Assisted-by:` trailer
