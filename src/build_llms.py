#!/usr/bin/env python3
"""Generate llms.txt — the machine-readable master index — mechanically.

  python3 src/build_llms.py           # regenerate llms.txt
  python3 src/build_llms.py --check   # exit 1 if committed llms.txt is stale (CI)

llms.txt used to be hand-maintained, which cost model tokens on every ingest and
rotted (it shipped broken links through two agency renames). Now it is GENERATED,
same pattern as REVIEW.md / graph.json / _index.md:

  - Counts, chapter/coverage enumerations, and section structure are DERIVED fresh
    each run from the corpus and the discovery catalogs (_meta/catalog/*.yml) — a
    thousand-section ORS ingest updates llms.txt with one script run, zero curation.
  - The judgment content (section titles, "when to consult" prose, highlighted
    documents) lives in _meta/llms-curated.yml, edited only when curation actually
    changes. A highlight whose path no longer exists is a hard error, so curation
    rot fails CI instead of shipping a broken link.

Knowledge bodies are auto-discovered from the corpus, so a new agency/body appears
here (with a generated default heading) before anyone curates it."""
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from repo_lib import REPO_ROOT, content_files, parse_frontmatter

CURATED = REPO_ROOT / "_meta/llms-curated.yml"
OUT = REPO_ROOT / "llms.txt"
CATALOG_DIR = REPO_ROOT / "_meta/catalog"

# canonical body order: jurisdiction-wide tiers by authority rank, then agencies
BODY_ORDER = ["statutes", "rules", "executive-orders"]
TAIL_ORDER = ["external-references"]


def _cat(name):
    p = CATALOG_DIR / f"{name}.yml"
    return yaml.safe_load(p.read_text()) if p.exists() else None


def body_key(rel_parts):
    if rel_parts[0] == "agencies":
        return "/".join(rel_parts[:3])
    return rel_parts[0]


def scan_bodies():
    """body key -> {count, docs_by_type} from the corpus itself."""
    bodies = defaultdict(lambda: {"count": 0, "full_text": 0})
    for p in content_files():
        rel = p.relative_to(REPO_ROOT)
        key = body_key(rel.parts)
        fm, _ = parse_frontmatter(p)
        bodies[key]["count"] += 1
        if fm.get("content_mode") == "verbatim":
            bodies[key]["full_text"] += 1
    return dict(bodies)


def chapters_line(cat, kind):
    """'complete chapters 183 (Administrative Procedures Act), 184 (…), …' from a
    catalog with chapters[].title. Only chapters that actually have ingested content."""
    parts = []
    for c in cat["chapters"]:
        n = 0
        if kind == "ors":
            n = sum(1 for s in c["sections"] if s.get("status") == "ingested")
        else:
            for d in c["divisions"]:
                rules = d.get("rules")
                if isinstance(rules, list):
                    n += sum(1 for r in rules if r.get("status") == "ingested")
        if n:
            title = c.get("title") or f"Chapter {c['chapter']}"
            title = title if title != f"Chapter {c['chapter']}" else None
            parts.append(f"{c['chapter']}" + (f" ({title})" if title else ""))
    return ", ".join(parts)


def summary_line(key, stats):
    """The generated (derived) summary sentence for one knowledge body."""
    n = stats["count"]
    if key == "statutes":
        cat = _cat("ors")
        return (f"{n} ORS sections, full text each — complete chapters "
                f"{chapters_line(cat, 'ors')}.")
    if key == "rules":
        cat = _cat("oar")
        return (f"{n} OAR rules, full text each — chapters "
                f"{chapters_line(cat, 'oar')}.")
    if key == "executive-orders":
        cat = _cat("eo")
        years = sorted({o["id"][3:5] for o in cat["orders"]
                        if o.get("status") == "ingested"})
        ft = stats["full_text"]
        return (f"{n} executive orders, 20{years[0]}–20{years[-1]}, from the "
                f"Governor's listing of record; {ft} carry verbatim full text, the "
                f"rest are image-only scans (metadata + official source link).")
    if key == "external-references":
        return f"{n} third-party reference(s)."
    # agency bodies
    ft = stats["full_text"]
    ft_note = "" if ft == n else f" ({ft} with verbatim full text)"
    return f"{n} documents{ft_note}."


def default_title(key):
    if "/" in key:
        _, slug, body = key.split("/")
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            import catalog_agencies
            names = {o["slug"]: o["name"] for o in
                     catalog_agencies.load()["organizations"]}
            agency = names.get(slug, slug)
        except Exception:
            agency = slug
        return f"{agency} — {body.replace('-', ' ').title()}"
    return key.replace("-", " ").title()


def index_link(key):
    p = f"{key}/_index.md"
    return p if (REPO_ROOT / p).is_file() else None


def build():
    cur = yaml.safe_load(CURATED.read_text())
    curated_by_key = {s["key"]: s for s in cur["sections"]}
    bodies = scan_bodies()

    # order: curated order first (it encodes authority-tier ordering), then any
    # uncurated bodies discovered on disk (new agencies) before the tail
    ordered = [s["key"] for s in cur["sections"] if s["key"] in bodies]
    extra = sorted(k for k in bodies if k not in ordered)
    ordered += [k for k in extra if k not in ordered]

    L = [f"# {cur['title']}", ""]
    for hline in cur["header"].split("\n"):
        L.append(f"> {hline}".rstrip())
    L.append("")

    errors = []
    for key in ordered:
        stats = bodies[key]
        c = curated_by_key.get(key, {})
        L.append(f"## {c.get('title') or default_title(key)}")
        L.append("")
        idx = index_link(key)
        summary = summary_line(key, stats)
        consult = c.get("consult", "").strip()
        head = (f"- [Index]({idx}): " if idx else "- ") + summary
        if consult:
            head += " " + consult
        L.append(head)
        for h in c.get("highlights") or []:
            if not (REPO_ROOT / h["path"]).is_file():
                errors.append(f"curated highlight path does not exist: {h['path']}")
                continue
            note = " ".join(h["note"].split())
            L.append(f"- [{h['label']}]({h['path']}): {note}")
        L.append("")
    if errors:
        for e in errors:
            print(f"ERROR   {e}", file=sys.stderr)
        sys.exit(1)
    return "\n".join(L)


def main():
    text = build()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            print("llms.txt is stale — run: python3 src/build_llms.py")
            sys.exit(1)
        print("llms.txt is current.")
        return
    OUT.write_text(text)
    n_sections = text.count("\n## ")
    print(f"llms.txt regenerated: {n_sections} sections, {len(text.splitlines())} lines")


if __name__ == "__main__":
    main()
