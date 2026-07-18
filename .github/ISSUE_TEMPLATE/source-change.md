---
name: Source change
about: An upstream source document has changed (usually auto-opened by detect-upstream-changes)
title: "Source changed: <id>"
labels: source-change
---

## Changed source

- **Document id**:
- **Source URL**:
- **Previous sha256**:
- **New sha256**:
- **Detected**: <!-- ISO date -->

## Triage

- [ ] Confirm the change is substantive (not just a served-bytes difference)
- [ ] Identify what changed (new effective date? new version? repealed/superseded?)
- [ ] Re-fetch and update the snapshot in `_meta/snapshots/`
- [ ] Update frontmatter (`retrieved`, `source_sha256`, `effective_date`, `source_version`,
      `status`, `last_verified`, `verified_by`)
- [ ] Re-verify every `[VERBATIM]` quote; update body content as needed
- [ ] Update `_meta/source-manifest.yml`
- [ ] Log `Source-Updated` (or `Superseded`/`Repealed`) in the knowledge body `CHANGELOG.md`
