#!/usr/bin/env python3
"""Mark every OAR rule with an honest `upstream_tracking` frontmatter field (#78).

The exposure this field closes: hand-ingested OAR rules have per-rule entries in
`_meta/sources/oar.yml`, so upstream drift detection re-hashes them on schedule —
but the mass-imported chapters were ingested with `--skip-group` and get NO
freshness checking at all. Both kinds of document otherwise look identical: same
frontmatter, same retrieval date, same confident `## Full text`. A reader (human
or agent) could not tell whether the rule they were holding was freshness-tracked
or could have been superseded upstream with nothing noticing. Issue #78's
constraint: "the corpus should be able to say so per document rather than
presenting mass-imported and freshness-tracked rules identically."

The field, on every `rules/**/oar-*.md`:

  upstream_tracking: manifest   the rule's id has a per-source entry in
                                _meta/sources/oar.yml — content-hash re-checked by
                                the scheduled drift jobs (.github/workflows/
                                scheduled.yml).
  upstream_tracking: none       no manifest entry — NOTHING re-checks this rule's
                                text against upstream. Its retrieval date is a
                                statement about the past, not about freshness.

Ground truth is _meta/sources/oar.yml, nothing else; re-running after a manifest
change moves exactly the affected rules. Idempotent by construction (targeted
line edit, same style as enrich_oar.py; writes only when the value differs).

  python3 src/mark_upstream_tracking.py           # set/repair the field everywhere
  python3 src/mark_upstream_tracking.py --check   # CI: fail if any rule lacks the
                                                  # field or carries the wrong value

The field is exposed to agents via `mcp.extra_document_fields` in _meta/corpus.yml.
The frontmatter schema allows extra keys, so validate-frontmatter stays green.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml

from repo_lib import REPO_ROOT, content_files

FIELD_RE = re.compile(r"^upstream_tracking: (\S+)$", re.M)
# Insert into the provenance cluster, right after the hash the manifest tracks —
# every OAR rule carries source_sha256 (ingest writes it unconditionally).
ANCHOR_RE = re.compile(r'^(source_sha256: .*)$', re.M)


def tracked_ids() -> set:
    manifest = REPO_ROOT / "_meta" / "sources" / "oar.yml"
    data = yaml.safe_load(manifest.read_text())
    return {s["id"] for s in data.get("sources") or []}


def desired(path: Path, tracked: set) -> str:
    return "manifest" if path.stem in tracked else "none"


def current(text: str):
    m = FIELD_RE.search(text)
    return m.group(1) if m else None


def apply(path: Path, want: str) -> bool:
    text = path.read_text()
    have = current(text)
    if have == want:
        return False
    if have is not None:
        new = FIELD_RE.sub(f"upstream_tracking: {want}", text, count=1)
    else:
        new, n = ANCHOR_RE.subn(rf"\1\nupstream_tracking: {want}", text, count=1)
        if not n:
            raise SystemExit(f"ERROR {path}: no source_sha256 line to anchor "
                             "upstream_tracking after — fix the file, don't guess")
    path.write_text(new)
    return True


def main():
    check = "--check" in sys.argv
    tracked = tracked_ids()
    n = {"manifest": 0, "none": 0}
    changed, drifted, missing_docs = 0, [], set(tracked)
    for p in content_files():
        rel = p.relative_to(REPO_ROOT)
        if not (p.stem.startswith("oar-") and rel.parts[0] == "rules"):
            continue
        want = desired(p, tracked)
        n[want] += 1
        missing_docs.discard(p.stem)
        if check:
            if current(p.read_text()) != want:
                drifted.append(p.relative_to(REPO_ROOT))
        else:
            if apply(p, want):
                changed += 1

    total = n["manifest"] + n["none"]
    if missing_docs:
        # A manifest id with no rule document is a manifest bug worth surfacing,
        # not silently absorbing into the counts.
        print(f"NOTE: {len(missing_docs)} _meta/sources/oar.yml id(s) have no "
              f"rules/**/ document: {', '.join(sorted(missing_docs)[:10])}"
              + ("…" if len(missing_docs) > 10 else ""))
    if check:
        if drifted:
            for p in drifted[:20]:
                print(f"DRIFT  {p}")
            print(f"FAILED: {len(drifted)} of {total} rule(s) missing the "
                  "upstream_tracking field or carrying a value that contradicts "
                  "_meta/sources/oar.yml — run: python3 src/mark_upstream_tracking.py")
            sys.exit(1)
        print(f"OK: {total} rules honest about upstream tracking "
              f"({n['manifest']} manifest-tracked, {n['none']} untracked).")
    else:
        print(f"marked {changed} of {total} rule file(s) "
              f"({n['manifest']} manifest-tracked, {n['none']} untracked)")


if __name__ == "__main__":
    main()
