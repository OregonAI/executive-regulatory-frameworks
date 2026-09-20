# CLAUDE.md

Read [AGENTS.md](AGENTS.md) — it is the canonical agent guide for this repository.
All content rules there (especially the [VERBATIM]/[SUMMARY] anti-fabrication requirements) are mandatory.

## Before opening any PR that adds or changes corpus content

Run every staleness gate, **including the nightly tier** — PR CI skips those, so a green
PR does not mean the generated files are current (#426 left six red nightlies behind it):

    python3 -m pytest -n auto -m check

For each failure that prints `<file> is stale — run: <command>`, run that command, then
rerun the gates. Repeat until green (generators feed each other, e.g. graph.json →
agency-graph.json) and commit the regenerated files in the same PR. Never hand-edit a
generated file.
