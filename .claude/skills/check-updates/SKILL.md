---
name: check-updates
description: Check Oregon upstream sources for changes and refresh affected documents, scoped per update group (policies, OAM, rules, statutes, standards — each has its own cadence). Use when asked to check for policy updates, refresh a knowledge body, or see what's due.
---

# Check upstream updates (Stage 3, on demand — no cron)

Update groups are **data**, not code: every `_meta/sources/<group>.yml` describes one
knowledge body (its sources, its check kind, its cadence, its upstream signal). This
skill is generic — when new bodies or agencies are added as group files, nothing here
changes.

## Token-efficiency rules (hard)

- Drive the scripts; read ONLY their output. They are silent on unchanged sources by
  design.
- Never open snapshots or document bodies during a check. After a refresh, run the two
  validators and read only their final lines (plus any ERROR lines).
- Check only the group(s) that are due or that the user named — never `--all` unless
  asked.

## Workflow

1. **What's due?** (no network, instant)

       python3 src/check_updates.py --due

   Each group prints its cadence and staleness. Cadences reflect real upstream rhythms:
   OAR moves with the monthly Oregon Bulletin; the DAS-policies and OAM SharePoint
   listings can change any time (monthly checks); ORS changes biennially (odd-year
   sessions); standards move on their printed review dates.

2. **Check a due group** (network, scoped):

       python3 src/check_updates.py --group <name>

   No changes → one line per group; done. Report that to the user and stop.

3. **Something changed** → re-run with `--refresh`:

       python3 src/check_updates.py --group <name> --refresh

   - Changed documents are re-fetched, re-snapshotted, and their `## Full text`
     regenerated mechanically. Effective/version dates are NOT auto-updated — the
     script inserts `TODO: human verification required` markers; surface every one of
     these to the user (a human must transcribe dates from the new source; HC-1).
   - Changed **listings** are reported (ADDED / REMOVED / DATE CHANGED rows) but never
     auto-ingested: intake gate #1 requires the user to vet the list first. Present the
     ADDED rows and, on approval, ingest them with the established listing-driven
     pattern (fetch each row's FileRef verbatim, magic-byte check, snapshot + `.txt`,
     full-text-first body via `src/ingest_lib.py` helpers), then rebuild the listing
     snapshot, catalog, group file, `_index.md`, and `llms.txt`.

4. **Validate and land**:

       python3 src/validate_frontmatter.py && python3 src/verify_provenance.py
       python3 src/review_queue.py   # refresh REVIEW.md (CI checks it is current)
       python3 src/link_graph.py     # refresh relationship edges + _meta/graph.json

   Then write a `Source-Updated` entry in the affected body's `CHANGELOG.md`
   (what changed, old→new hash prefixes, any TODO markers left for human review),
   commit with the standard trailers, push, and confirm CI.

## Notes

- `chapter-html` groups (e.g. `ors`): one shared snapshot covers several section
  documents; a refresh regenerates every dependent file automatically.
- The old all-sources sweep still exists as `src/detect_changes.py` behind the
  `detect-upstream-changes` workflow's manual `workflow_dispatch` (cron removed).
- Adding a new group: copy an existing `_meta/sources/*.yml`, fill `kind`/`recheck`/
  `upstream_signal`/`sources`; it appears in `--due` immediately.
