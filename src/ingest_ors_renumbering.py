#!/usr/bin/env python3
"""Ingest Oregon Legislative Counsel's official ORS renumbering table across every edition
we can find, and record confidently-resolvable old->current section mappings, so an OAR
rule citing a since-renumbered ORS section can still resolve to the current text — even if
it was renumbered more than once across editions.

  python3 src/ingest_ors_renumbering.py            # fetch + parse + write catalog
  python3 src/ingest_ors_renumbering.py --check    # exit 1 if catalog is stale vs. snapshots

Oregon Legislative Counsel overwrites the SAME table URL in place every biennium (no
historical archive, no year-stamped filenames — confirmed by hand this session), so past
editions are only reachable via the Wayback Machine's captures of that one URL. EDITIONS
below is a fixed, hand-verified list (each URL's own PDF title was checked against its
listed year) — not something this script discovers on its own; extend the list by hand when
a new edition is found (the 2025 URL will itself become a future Wayback capture once
Legislative Counsel replaces it with the next edition).

The table is a two-column "Formerly | Renumbered" list (parser validated row-by-row against
the real 2025 document this session). Only single-section-to-single-section rows
("308.440" -> "308.429") are treated as confident enough to auto-apply. Multi-section list
rows and range rows ("79.0101 to 79.0628" -> a scattered set of 79A.* ranges) are recorded
for human reference but NEVER auto-expanded or positionally paired — the table gives no
guarantee the Nth item on one side corresponds to the Nth item on the other (HC-1: no
fabrication).

Chaining: a section can be renumbered more than once across editions (e.g. renumbered in
2019, then renumbered AGAIN in 2021) — simple mappings from every edition are merged into
one graph and each starting number is walked to a fixed point (capped at 10 hops to guard
against a cyclic/bad entry). For a chain that lands on an ingested statute, every historical
number in the chain is added to that document's relationships.supersedes (mirrors
enrich_oar.py's "OAR <old>" convention exactly, just potentially more than one entry)."""
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from ingest_lib import fetch
from repo_lib import REPO_ROOT, content_files, content_hash

# (edition label, source URL) - hand-verified this session: each PDF's own printed title
# ("OREGON REVISED STATUTES <year> Renumbering") was checked to match the label. 2017 is the
# earliest capture the Wayback Machine has of this URL; Legislative Counsel's own site has
# no further historical archive of this specific document.
EDITIONS = [
    ("2017", "http://web.archive.org/web/20190428122324id_/"
             "https://www.oregonlegislature.gov/bills_laws/BillsLawsEDL/ORS_Renum.pdf"),
    ("2019", "http://web.archive.org/web/20210719113022id_/"
             "https://www.oregonlegislature.gov/bills_laws/BillsLawsEDL/ORS_Renum.pdf"),
    ("2021", "http://web.archive.org/web/20231007143028id_/"
             "https://www.oregonlegislature.gov/bills_laws/BillsLawsEDL/ORS_Renum.pdf"),
    ("2025", "https://www.oregonlegislature.gov/bills_laws/BillsLawsEDL/ORS_Renum.pdf"),
]
SNAPSHOT_DIR = REPO_ROOT / "_meta/snapshots"
OUT = REPO_ROOT / "_meta/catalog/ors-renumbering.yml"

SECTION_RE = re.compile(r"^\d")
CONTINUATION_RE = re.compile(r"^\s*(to|and)\b", re.I)
BOILERPLATE_RE = re.compile(r"^\d+$")
SINGLE_SECTION_RE = re.compile(r"^\d{1,3}[A-Za-z]?\.\d{3,4}$")
MAX_HOPS = 10


def snap_id(edition: str) -> str:
    return f"ors-renum-{edition}"


def fetch_and_snapshot(edition: str, url: str) -> str:
    """Fetch one edition's PDF, snapshot it, extract text via pdftotext -layout."""
    raw = fetch(url)
    if raw[:5] != b"%PDF-":
        raise SystemExit(f"{edition}: fetched content is not a PDF")
    sid = snap_id(edition)
    pdf_path = SNAPSHOT_DIR / f"{sid}.pdf"
    pdf_path.write_bytes(raw)
    txt_path = SNAPSHOT_DIR / f"{sid}.txt"
    subprocess.run(["pdftotext", "-layout", str(pdf_path), str(txt_path)], check=True)
    return txt_path.read_text(encoding="utf-8")


def parse_table(text: str) -> list:
    """[{"formerly": str, "renumbered": str}, ...] — one dict per logical table row,
    reconstructed from pdftotext -layout's fixed-column output (column position varies by
    page, so split on runs of 2+ spaces rather than an absolute offset; a row continues
    across lines when the left column is blank, or when it starts with a bare list item
    while the row-in-progress ends mid-list ('...,'))."""
    lines = text.split("\n")
    hdr = next((i for i, l in enumerate(lines) if l.strip().startswith("Formerly")), None)
    if hdr is None:
        return []
    rows, cur = [], None

    def incomplete(c):
        if c is None:
            return False
        return c["formerly"].rstrip().endswith(",") or c["renumbered"].rstrip().endswith(",")

    for line in lines[hdr + 1:]:
        s = line.strip()
        if not s or BOILERPLATE_RE.match(s) or ("Formerly" in s and "Renumbered" in s):
            continue
        leading = len(line) - len(line.lstrip())
        parts = [p for p in re.split(r"\s{2,}", line.rstrip()) if p]
        if leading >= 20:
            left, right = "", (parts[0] if parts else "")
        elif len(parts) >= 2:
            left, right = parts[0], " ".join(parts[1:])
        else:
            left, right = (parts[0] if parts else ""), ""
        looks_new = bool(SECTION_RE.match(left)) and not CONTINUATION_RE.match(right)
        if looks_new and not incomplete(cur):
            if cur:
                rows.append(cur)
            cur = {"formerly": left.strip(), "renumbered": right.strip()}
        elif cur is not None:
            if left.strip():
                cur["formerly"] += " " + left.strip()
            if right.strip():
                cur["renumbered"] += " " + right.strip()
    if cur:
        rows.append(cur)
    return rows


def classify(rows: list) -> tuple:
    """(simple, advisory) — simple = single-section-to-single-section rows only."""
    simple, advisory = [], []
    for r in rows:
        f, n = r["formerly"], r["renumbered"]
        if SINGLE_SECTION_RE.match(f) and SINGLE_SECTION_RE.match(n):
            simple.append({"formerly": f.lower(), "renumbered": n.lower()})
        else:
            advisory.append({"formerly": f, "renumbered": n})
    return simple, advisory


def resolve_chains(all_simple: list) -> dict:
    """{starting_old_section: [chain of every historical number, ending with the final
    resolved section]} for every distinct starting section across all editions' simple
    mappings, walked to a fixed point (capped at MAX_HOPS to guard against a bad/cyclic
    entry rather than looping forever)."""
    step = {}
    for row in all_simple:
        step.setdefault(row["formerly"], row["renumbered"])  # first edition to mention it wins
    chains = {}
    for start in step:
        chain, cur, seen = [start], start, {start}
        for _ in range(MAX_HOPS):
            nxt = step.get(cur)
            if not nxt or nxt in seen:
                break
            chain.append(nxt)
            seen.add(nxt)
            cur = nxt
        chains[start] = chain
    return chains


def compute() -> dict:
    editions_out = []
    all_simple = []
    for edition, url in EDITIONS:
        sid = snap_id(edition)
        txt_path = SNAPSHOT_DIR / f"{sid}.txt"
        text = txt_path.read_text(encoding="utf-8")
        simple, advisory = classify(parse_table(text))
        editions_out.append({
            "edition": edition, "source_url": url,
            "source_sha256": content_hash((SNAPSHOT_DIR / f"{sid}.pdf").read_bytes(), "pdf"),
            "simple": simple, "advisory": advisory,
        })
        all_simple.extend(simple)

    existing_ids = {p.stem for p in content_files() if p.parent.name == "statutes"}
    chains = resolve_chains(all_simple)
    resolved = []
    for start, chain in sorted(chains.items()):
        final = chain[-1]
        resolved.append({
            "formerly": start, "current": final, "hops": chain,
            "current_ingested": f"ors-{final}" in existing_ids,
        })

    return {
        "note": ("Oregon Legislative Counsel's official ORS renumbering table, one entry "
                "per edition found (Legislative Counsel overwrites the same URL in place "
                "each biennium and keeps no historical archive of it — past editions here "
                "were recovered via Wayback Machine captures of that URL, hand-verified "
                "against each PDF's own printed edition title; 2017 is the earliest capture "
                "available, not necessarily the earliest edition that ever existed). "
                "'resolved_chains' merges every edition's single-section-to-single-section "
                "mappings and walks each starting number to its final current section, "
                "which is what actually gets applied to relationships.supersedes. Advisory "
                "(multi-section list/range) rows are recorded per-edition below for human "
                "reference only — never auto-expanded or chained, since the table gives no "
                "positional correspondence to safely follow. Non-authoritative; verify "
                "against the source PDFs before relying on any entry here."),
        "resolved_chains": resolved,
        "editions": editions_out,
    }


def apply_supersedes(resolved_chains: list) -> int:
    """For each chain landing on an ingested statute, add every historical number in the
    chain ('ORS <old>') to that document's relationships.supersedes if not already present.
    Returns count of documents changed."""
    changed = 0
    for row in resolved_chains:
        if not row["current_ingested"]:
            continue
        path = REPO_ROOT / "statutes" / f"ors-{row['current']}.md"
        if not path.exists():
            continue
        text = orig = path.read_text(encoding="utf-8")
        for old in row["hops"][:-1]:  # every historical alias except the current section itself
            old_cite = f"ORS {old.upper()}"
            if f'"{old_cite}"' in text:
                continue
            new_text, n = re.subn(r"^(  supersedes: )\[\]$",
                                  rf'\1\n    - "{old_cite}"', text, count=1, flags=re.M)
            if not n:
                new_text, n = re.subn(r"^(  supersedes: ?\n(?:    - .*\n)*)",
                                      rf'\1    - "{old_cite}"\n', text, count=1, flags=re.M)
            if n:
                text = new_text
        if text != orig:
            path.write_text(text, encoding="utf-8")
            changed += 1
    return changed


def main():
    check = "--check" in sys.argv

    if check:
        # Never re-fetch over the network for a CI gate — re-parse the already-committed
        # snapshots (like every other --check in this repo) and compare to the committed
        # catalog. Run without --check at least once first to create the snapshots.
        missing = [e for e, _ in EDITIONS if not (SNAPSHOT_DIR / f"{snap_id(e)}.txt").exists()]
        if missing:
            print(f"missing snapshot(s) for edition(s) {missing} — run: "
                  "python3 src/ingest_ors_renumbering.py")
            sys.exit(1)
        data = compute()
        text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
        if not OUT.exists() or OUT.read_text() != text:
            print(f"{OUT.relative_to(REPO_ROOT)} is stale — run: "
                  "python3 src/ingest_ors_renumbering.py")
            sys.exit(1)
        print("ors-renumbering.yml is current.")
        return

    for edition, url in EDITIONS:
        fetch_and_snapshot(edition, url)
    data = compute()
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    changed = apply_supersedes(data["resolved_chains"])
    n_multi_hop = sum(1 for r in data["resolved_chains"] if len(r["hops"]) > 2)
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {len(EDITIONS)} editions, "
          f"{len(data['resolved_chains'])} resolved chain(s) ({n_multi_hop} multi-hop); "
          f"applied supersedes to {changed} statute document(s)")


if __name__ == "__main__":
    main()
