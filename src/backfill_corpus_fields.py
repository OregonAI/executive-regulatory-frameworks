#!/usr/bin/env python3
"""One-off backfill for the Phase 3 corpus-toolkit migration: every content file needs
three new frontmatter fields the generic toolkit schema requires that the old
Oregon-specific schema didn't (`schema_version`, `corpus`, `jurisdiction` — see
docs/provenance-schema-v1.md in corpus-toolkit). All three are constants for this
corpus, so this is a pure text insertion right after the opening `---`, never a full
YAML re-dump — every other line in each file (formatting, key order, quoting) is left
byte-for-byte untouched. Idempotent: skips any file that already has schema_version.

  python3 src/backfill_corpus_fields.py            # apply
  python3 src/backfill_corpus_fields.py --check    # report only, no writes; exit 1 if any file needs it
"""
import sys

from repo_lib import content_files

FIELDS = 'schema_version: 1\ncorpus: "executive-regulatory-frameworks"\njurisdiction: "oregon"\n'


def needs_backfill(text: str) -> bool:
    end = text.find("\n---", 4)
    return text.startswith("---\n") and end != -1 and "schema_version:" not in text[4:end]


def patch(text: str) -> str:
    return text[:4] + FIELDS + text[4:]


def main():
    check = "--check" in sys.argv
    todo = []
    for p in content_files():
        text = p.read_text(encoding="utf-8")
        if needs_backfill(text):
            todo.append(p)
            if not check:
                p.write_text(patch(text), encoding="utf-8")

    if check:
        if todo:
            print(f"{len(todo)} file(s) missing schema_version/corpus/jurisdiction:")
            for p in todo[:20]:
                print(f"  {p}")
            if len(todo) > 20:
                print(f"  … and {len(todo) - 20} more")
            sys.exit(1)
        print("all content files have schema_version/corpus/jurisdiction.")
        return

    print(f"backfilled {len(todo)} file(s).")


if __name__ == "__main__":
    main()
