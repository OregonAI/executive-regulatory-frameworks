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
     snapshot, catalog, group file, `_index.md`, and `python3 src/build_llms.py` (llms.txt is generated).

4. **Validate and land**:

       corpus-validate-frontmatter --config _meta/corpus.yml
       corpus-verify-provenance --config _meta/corpus.yml
       python3 src/link_graph.py     # relationship edges + _meta/graph.json — run FIRST,
                                      # most generators below read the graph

       # CI gates ~20 generated artifacts, not three. Regenerating only link_graph and
       # review_queue produces a PR that fails on a dozen staleness checks, so run the
       # rest too. Order matters only in that link_graph comes first.
       python3 src/build_ors_disposition.py      # repeal dispositions (feeds resolve_citation)
       python3 src/enrich_statutes.py
       python3 src/enrich_oar.py
       python3 src/review_queue.py               # REVIEW.md
       python3 src/build_llms.py                 # llms.txt
       python3 src/build_agency_index.py
       python3 src/build_agency_graph.py
       python3 src/build_policy_gap.py
       python3 src/build_statute_fan.py
       python3 src/build_authority_explorer.py
       python3 src/build_freshness_data.py && python3 src/build_freshness.py
       python3 src/build_policy_age_data.py && python3 src/build_policy_age.py
       python3 src/build_governor_priorities_data.py && python3 src/build_governor_priorities.py
       python3 src/build_conflict_candidates_data.py && python3 src/build_conflict_candidates.py
       python3 src/build_topic_map.py            # reads the committed UMAP projection

       # NOT run here: src/build_embeddings.py. It needs a GPU and a 2.3 GB model, its
       # artifact is gitignored, and its CI gate soft-passes when absent — so semantic
       # search silently keeps serving the previous index until someone rebuilds it.

   Then write a `Source-Updated` entry in the affected body's `CHANGELOG.md`
   (what changed, old→new hash prefixes, any TODO markers left for human review),
   commit with the standard trailers, push, and confirm CI.

## Notes

- `chapter-html` groups (e.g. `ors`): one shared snapshot covers several section
  documents; a refresh regenerates every dependent file automatically.
- `constitution` is ONE source and ONE sha256 for the whole document (ADR 0005), so a
  `CHANGED` line there says only that something moved. Name the sections before refreshing
  anything:

      python3 src/ingest_constitution.py --drift _meta/snapshots/oregon-constitution.txt
      python3 src/ingest_constitution.py --drift path/to/the-page-you-fetched.html
      python3 src/ingest_constitution.py --drift            # no path: fetches the page

  It prints the sections whose text moved and says nothing about the ones that did not; a
  section it cannot slice out of the new page is `COULD NOT CHECK` and never a section that
  was deleted. It exits non-zero whenever the page moved — including when NO sliced section
  accounts for it, which means the change is outside the text this mirror publishes (a
  heading, the edition sentence, page furniture) and the snapshot itself needs diffing.
  Given a path it touches no network, and it refuses to report at all if `constitution/`
  does not carry what the catalog claims.
- The old all-sources sweep is now `corpus-detect-changes` (from corpus-toolkit)
  behind the `detect-upstream-changes` workflow's manual `workflow_dispatch`
  (cron removed).
- Adding a new group: copy an existing `_meta/sources/*.yml`, fill `kind`/`recheck`/
  `upstream_signal`/`sources`; it appears in `--due` immediately. `recheck` must be one of
  the cadences declared in `src/check_updates.py`'s `CADENCES` table — the schema's enum is
  generated from it and prints what each one means in days — and a value nothing declares is
  reported (`--due` says `UNKNOWN CADENCE`, `--check` fails against the group) rather than
  raising. A cadence tied to an EVENT rather than an elapsed period
  (`even_year_general_election`, `biennial`) only lands on that event if the group's first
  `last_checked` sits after one: the interval cannot set its own phase (#198).
