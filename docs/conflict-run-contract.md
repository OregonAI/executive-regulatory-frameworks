# The conflict-run contract

The standing rules for every future candidate-generation run, written down after the
2026-08-02 process review so they bind by document rather than by memory. The pipeline
(`analyze_conflicts.py`) and the review flow (`triage_conflicts.py`) enforce the
mechanical ones; the rest are operating discipline.

## 1. No run merges unevaluated (ENFORCED)

`merge_into_catalog` refuses any (model, prompt_version) pair with no entry in
`_meta/catalog/conflict-eval-ledger.yml`. Score the pair first
(`eval_conflicts.py … --record`), or bypass with `--unevaluated-ok` and wear the
warning. Origin: batch 2's ~3x recall collapse was discovered by accidental re-runs,
after the money was spent. The ledger's three seed entries are historical
reconstructions from the catalog's own notes, marked as such.

## 2. Coverage is a ledger, not a recollection (ENFORCED)

`_meta/catalog/conflict-coverage.yml` (generated, CI-gated) records per
shared-authority chapter the depth actually reached — `chapter`, `sections-partial`
(with the screened list), or `unscreened` — and orders the frontier by expected value:
agencies sharing the chapter × rule mass × audit corroboration × unscreened share.
**The next run reads from the top of this file.** The batch-3 rule (smallest chapters
first, to bound tokens) is retired; cost is bounded by taking fewer units, never by
preferring low-value ones. Current truth: 1,843 of 6,177 sections screened.

## 3. The run envelope is fixed (CONTRACT)

Every candidate a run emits carries: `summary`, `type` (one of the eight checks — run 4
omitted this and its candidates are permanently untyped; never again), `documents`
(each with `id`, `citation`, `quote`), `confidence` and `severity` (the model's own
graded low/medium/high, by the rubric in the prompt version — absent means NOT
RECORDED, never "low"), `run_id`, `model`, `prompt_version`. Prompt changes bump the
version; rubric meaning changes bump it twice as hard.

## 4. Weak quotes go to the front of the human queue (ENFORCED)

Machine grounding blesses exact quotes; it cannot bless **absence claims** ("the rule
omits X") or quotes it failed to locate. `triage_conflicts.py` orders those right after
the audit-corroborated set — the places a confident fabrication could survive are the
places a human looks first. For absence claims specifically, the next generation
session should add the cheap second pass: one model, one document, one question —
"does this document contain any provision addressing X?" — before the claim ever
reaches a human.

## 5. Verdicts feed the eval (ENFORCED, half-automatic)

`triage_conflicts.py --export-eval` writes `_meta/eval/triage-verdicts.yml`: confirmed
candidates are positives a model should find, dismissed are hard negatives it should
not. Run it after review sessions. This is the second ground-truth arm — human-authored,
so it never suffers the #65 circularity (a model credited for rediscovering its own
merged output).

## 6. Two tiers, and pacing (DISCIPLINE)

Section-scoped is the default sweep (cheaper, targeted, the unit `analyze_conflicts`
was built around); chapter-scoped is the escalation tier for chapters where sections
produced confirmed candidates. And generation is paced to review: with 1,398 candidates
unreviewed, another thousand deepens the backlog without adding knowledge. The coverage
ledger says what is left; the eval gate says a run will be worth reading; the triage
queue says when there is room for it.
