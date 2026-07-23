#!/usr/bin/env python3
"""Ingest Oregon Legislative Counsel's official ORS renumbering table (published each
biennium at a stable URL — this fetches the current edition) and record confidently-
resolvable old->new section mappings, so an OAR rule citing a since-renumbered ORS section
can still resolve to the current text.

  python3 src/ingest_ors_renumbering.py            # fetch + parse + write catalog
  python3 src/ingest_ors_renumbering.py --check    # exit 1 if catalog is stale vs. snapshot

The table is a two-column "Formerly | Renumbered" list (fetched and hand-verified against
the real document this session — see _meta/catalog/ors-renumbering.yml's own note). It is
only the CURRENT biennium's incremental delta, not a master historical index; a citation
renumbered in an earlier edition needs that edition's own table (not yet located/ingested —
see BACKLOG.md).

Only single-section-to-single-section rows ("308.440" -> "308.429") are treated as
confident enough to auto-apply: for each, if the new section is already an ingested
statute, "ORS <old>" is added to its relationships.supersedes (mirrors enrich_oar.py's
"OAR <old>" convention exactly). Multi-section list rows and range rows ("79.0101 to
79.0628" -> a scattered set of 79A.* ranges) are recorded for human reference but NEVER
auto-expanded or positionally paired — the table gives no guarantee the Nth item on one
side corresponds to the Nth item on the other (HC-1: no fabrication).
"""
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from ingest_lib import fetch
from repo_lib import REPO_ROOT, content_files, content_hash

URL = "https://www.oregonlegislature.gov/bills_laws/BillsLawsEDL/ORS_Renum.pdf"
SNAP_ID = "ors-renum-2025"
SNAPSHOT_DIR = REPO_ROOT / "_meta/snapshots"
OUT = REPO_ROOT / "_meta/catalog/ors-renumbering.yml"

SECTION_RE = re.compile(r"^\d")
CONTINUATION_RE = re.compile(r"^\s*(to|and)\b", re.I)
BOILERPLATE_RE = re.compile(r"^\d+$")
SINGLE_SECTION_RE = re.compile(r"^\d{1,3}[A-Za-z]?\.\d{3,4}$")


def fetch_and_snapshot() -> str:
    """Fetch the PDF, snapshot it, extract text via pdftotext -layout. Returns the text."""
    raw = fetch(URL)
    if raw[:5] != b"%PDF-":
        raise SystemExit("fetched content is not a PDF")
    pdf_path = SNAPSHOT_DIR / f"{SNAP_ID}.pdf"
    pdf_path.write_bytes(raw)
    txt_path = SNAPSHOT_DIR / f"{SNAP_ID}.txt"
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


def compute(text: str) -> dict:
    rows = parse_table(text)
    existing_ids = {p.stem for p in content_files() if p.parent.name == "statutes"}

    simple, advisory = [], []
    for r in rows:
        f, n = r["formerly"], r["renumbered"]
        if SINGLE_SECTION_RE.match(f) and SINGLE_SECTION_RE.match(n):
            entry = {"formerly": f.lower(), "renumbered": n.lower()}
            new_id = f"ors-{n.lower()}"
            entry["new_section_ingested"] = new_id in existing_ids
            simple.append(entry)
        else:
            advisory.append({"formerly": f, "renumbered": n})

    return {
        "source_url": URL,
        "source_sha256": content_hash((SNAPSHOT_DIR / f"{SNAP_ID}.pdf").read_bytes(), "pdf"),
        "note": ("Oregon Legislative Counsel's official ORS renumbering table, current "
                "edition only (fetched from source_url above — republished each biennium, "
                "this is NOT a master historical index). 'simple' rows are single-section-"
                "to-single-section mappings, confident enough to auto-apply to "
                "relationships.supersedes. 'advisory' rows are multi-section lists or "
                "ranges the table gives no positional correspondence for — recorded for "
                "human reference only, never auto-expanded. Non-authoritative; verify "
                "against the source PDF before relying on any entry here."),
        "simple": simple,
        "advisory": advisory,
    }


def apply_supersedes(simple_rows) -> int:
    """For each simple row whose new section is ingested, add 'ORS <old>' to its
    relationships.supersedes if not already present. Returns count changed."""
    changed = 0
    for row in simple_rows:
        if not row["new_section_ingested"]:
            continue
        path = REPO_ROOT / "statutes" / f"ors-{row['renumbered']}.md"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        old_cite = f"ORS {row['formerly'].upper()}"
        if f'"{old_cite}"' in text:
            continue
        new_text, n = re.subn(r"^(  supersedes: )\[\]$",
                              rf'\1\n    - "{old_cite}"', text, count=1, flags=re.M)
        if n:
            path.write_text(new_text, encoding="utf-8")
            changed += 1
    return changed


def main():
    check = "--check" in sys.argv
    txt_path = SNAPSHOT_DIR / f"{SNAP_ID}.txt"

    if check:
        # Never re-fetch over the network for a CI gate — re-parse the already-committed
        # snapshot text (like every other --check in this repo) and compare to the
        # committed catalog. Run without --check at least once first to create the
        # snapshot.
        if not txt_path.exists():
            print(f"{txt_path.relative_to(REPO_ROOT)} doesn't exist — run: "
                  "python3 src/ingest_ors_renumbering.py")
            sys.exit(1)
        data = compute(txt_path.read_text(encoding="utf-8"))
        text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
        if not OUT.exists() or OUT.read_text() != text:
            print(f"{OUT.relative_to(REPO_ROOT)} is stale — run: "
                  "python3 src/ingest_ors_renumbering.py")
            sys.exit(1)
        print("ors-renumbering.yml is current.")
        return

    text_content = fetch_and_snapshot()
    data = compute(text_content)
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    changed = apply_supersedes(data["simple"])
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {len(data['simple'])} simple mapping(s), "
          f"{len(data['advisory'])} advisory (list/range) mapping(s); "
          f"applied supersedes to {changed} statute document(s)")


if __name__ == "__main__":
    main()
