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
import re
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


_MIRRORED_CACHE: dict = {}


def mirrored_oar_chapters(cat=None):
    """THE CHAPTERS THIS CORPUS MIRRORS, read from `rules/` -- with titles, sorted.

    NOT from the catalog's chapter list (#237). `_meta/catalog/oar.yml` is a DISCOVERY MAP
    -- its own note says so -- and it lists what discovery walked. Chapters 419 and 950 were
    never walked: oregon.public.law does not carry them, and their 303 documents arrived
    under rules RENUMBERED INTO those chapters, whose catalog rows keep the number OARD
    renumbered them FROM. Both readings are correct about their own question, and llms.txt
    was asking the wrong one: it printed `36953 OAR rules ... chapters 101, 104, ...` --
    a count taken from the corpus and a list taken from the map, disagreeing inside one
    sentence, with 303 mirrored documents named nowhere.

    Titles come from the catalog where it has one and the agency registry otherwise, which
    is where the catalog's own titles come from.
    """
    # MEMOISED because this walks every rule document, and `--selftest` asks five times.
    # Unmemoised it was the slowest gate in the whole sweep at 207s of a 30-minute budget
    # -- five rglobs over 36,953 files to answer one question that cannot change mid-run.
    if "v" in _MIRRORED_CACHE and cat is None:
        return _MIRRORED_CACHE["v"]
    cat = cat if cat is not None else _cat("oar")
    titles = {str(c["chapter"]): c.get("title") for c in cat.get("chapters") or []}
    reg = yaml.safe_load((REPO_ROOT / "_meta/catalog/agencies.yml").read_text())
    orgs = reg["organizations"] if isinstance(reg, dict) else reg
    for o in orgs:
        ch = o.get("oar_chapter")
        if ch and not titles.get(str(ch)):
            # NAME READER — JOIN (OAR-derived): pairing a CHAPTER NUMBER with a name is an
            # OAR-keyed join by construction -- the chapter is the OAR index's key, and the
            # name printed beside it is the one that index uses for the body, `oar_name`
            # (CONTEXT.md, *OAR name*). Same read as catalog_oar.registry_chapters, which
            # is where the catalog's own titles come from; this only fills the two chapters
            # the catalog never walked. `name` is the fallback for a row with no oar_name --
            # 19 registry rows carry no oar_chapter at all and never reach here, but a row
            # admitted on enabling authority alone may legitimately have no OAR name, and
            # printing the statutory one beats printing a bare number.
            titles[str(ch)] = o.get("oar_name") or o.get("name")
    out = []
    for d in sorted((REPO_ROOT / "rules").iterdir(), key=lambda p: (len(p.name), p.name)):
        if not (d.is_dir() and d.name.isdigit()):
            continue
        n = sum(1 for _ in d.rglob("oar-*.md"))
        if n:
            out.append((d.name, titles.get(d.name), n))
    _MIRRORED_CACHE["v"] = out
    return out


def chapters_line(cat, kind):
    """'complete chapters 183 (Administrative Procedures Act), 184 (…), …'.

    ORS reads the catalog, whose sections carry their own ingest status. OAR reads the
    MIRROR, for the reason in `mirrored_oar_chapters`."""
    parts = []
    if kind == "oar":
        for ch, title, _n in mirrored_oar_chapters(cat):
            parts.append(f"{ch}" + (f" ({title})" if title else ""))
        return ", ".join(parts)
    for c in cat["chapters"]:
        n = sum(1 for s in c["sections"] if s.get("status") == "ingested")
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
            # NAME READER — DISPLAY: the agency title in llms.txt, read by a person or a
            # model deciding what this corpus holds. Stays on `name` — the statutory name
            # after ADR 0003 — because the entry names the BODY, not its rule chapter.
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


def missing_chapters(text):
    """Mirrored OAR chapters the published text does not name."""
    line = next((ln for ln in text.splitlines() if "OAR rules, full text each" in ln), "")
    named = set(re.findall(r"(?<![\d-])(\d{3})(?= \()", line))
    return [(ch, t, n) for ch, t, n in mirrored_oar_chapters() if ch not in named]


def selftest() -> int:
    fails = []
    have = mirrored_oar_chapters()
    if not have:
        fails.append("FAIL there-are-mirrored-chapters-to-check: none found, so every "
                     "rule below is about nothing")

    good = build()
    if missing_chapters(good):
        fails.append(f"FAIL the-generated-text-names-every-mirrored-chapter: "
                     f"{[c for c, _, _ in missing_chapters(good)]}")

    # WATCHED FAILING against the shape #237 found: the chapter list taken from the
    # discovery map while the count is taken from the corpus.
    cat = _cat("oar")
    from_map = ", ".join(f"{c['chapter']} ({c.get('title')})"
                         for c in cat.get("chapters") or [])
    stale = f"- [Index](rules/_index.md): 36953 OAR rules, full text each — chapters {from_map}."
    caught = missing_chapters(stale)
    if not caught:
        fails.append("FAIL a-chapter-list-taken-from-the-discovery-map-is-caught: the "
                     "catalog names every mirrored chapter, so this proof cannot fail and "
                     "is not a proof — it held only while 419 and 950 were missing")
    elif {c for c, _, _ in caught} != {"419", "950"}:
        fails.append(f"FAIL ...and it names exactly which: {sorted(c for c, _, _ in caught)}")

    # AND A GUARD THAT MUST NOT FIRE: a line naming every chapter is clean, so the rule
    # cannot be satisfied by matching nothing.
    allch = ", ".join(f"{c} ({t or 'x'})" for c, t, _ in have)
    if missing_chapters(f"- [Index](rules/_index.md): 1 OAR rules, full text each — "
                        f"chapters {allch}."):
        fails.append("FAIL a-line-naming-every-chapter-produces-no-finding")

    for f in fails:
        print(f)
    if fails:
        print(f"{len(fails)} rule(s) did not hold")
        return 1
    print(f"1 violation demonstrated failing over {len(have)} mirrored chapter(s); "
          f"2 guard(s) that must not fire held")
    return 0


def main():
    text = build()
    if "--selftest" in sys.argv:
        sys.exit(selftest())

    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            print("llms.txt is stale — run: python3 src/build_llms.py")
            sys.exit(1)
        # STALENESS IS NOT ENOUGH (#237). llms.txt was current and WRONG: the OAR count
        # came from the corpus and the chapter list from the discovery map, so 303 mirrored
        # documents in chapters 419 and 950 were named nowhere while the sentence around
        # them said 36,953. A regenerated file reproduces that faithfully.
        missing = missing_chapters(text)
        if missing:
            for ch, title, n in missing[:10]:
                print(f"  FAIL [what-we-publish-names-every-chapter-we-mirror] {ch}: "
                      f"rules/{ch} holds {n} document(s)"
                      + (f" ({title})" if title else "")
                      + " and llms.txt does not name the chapter")
            print(f"\n{len(missing)} mirrored chapter(s) missing from llms.txt.")
            sys.exit(1)
        print(f"llms.txt is current, and names all "
              f"{len(mirrored_oar_chapters())} mirrored OAR chapter(s).")
        return
    OUT.write_text(text)
    n_sections = text.count("\n## ")
    print(f"llms.txt regenerated: {n_sections} sections, {len(text.splitlines())} lines")


if __name__ == "__main__":
    main()
