#!/usr/bin/env python3
"""Promote an image-only-scan document from summary to verbatim via OCR.

  python3 src/ocr_promote.py <doc-id> [<doc-id> ...]
  python3 src/ocr_promote.py --dry-run <doc-id>   # OCR + gate only, write nothing

Requires `ocrmypdf` and `pdftotext` on PATH. For each doc:

  1. Sanity-check the doc is actually a candidate: content_mode: summary,
     content_exception mentioning an image-only/no-text-layer scan, source_format: pdf,
     and its committed `_meta/snapshots/<id>.pdf` exists.
  2. Run `ocrmypdf --deskew --clean --optimize 1` on the committed PDF into a TEMP file
     (the original raw PDF snapshot is NEVER modified in place — it stays the exact
     bytes fetched from source_url, so provenance to the official source is untouched;
     OCR is purely a local text-recovery step, not a source refresh).
  3. Extract raw text via `pdftotext -layout` from the OCR'd temp copy.
  4. Quality gate — same threshold and same dictionary-ratio check as
     src/ingest_eo.py's scanned-executive-order gate (>=100 words, >=80% of alphabetic
     words in the system dictionary). FAILS -> leave the document untouched entirely,
     print why, and move on. Never force a bad OCR pass into the repo.
  5. On pass: overwrite `_meta/snapshots/<id>.txt` with the RAW pdftotext output
     (uncleaned — matches the existing convention where every other snapshot's .txt is
     raw pdftotext and src/ingest_lib.py's clean_pdf_text() strips furniture at
     doc-generation time, not at snapshot time).
  6. Rewrite the .md file:
     - content_mode: summary -> verbatim; content_exception line removed (dropping it
       is what the schema uses to require verbatim — see document.frontmatter.schema.json).
     - conversion_notes set from clean_pdf_text(), prefixed with an OCR disclosure so
       the fact that this text came from OCR (not the source's own text layer) is
       never hidden.
     - source_sha256 recomputed as sha256 of the whitespace-normalized new .txt —
       exactly what repo_lib.hash_snapshot() will independently compute at
       verify_provenance time, so this MUST match or CI fails.
     - last_verified bumped to today (a human is meant to review the OCR output before
       this lands — see the printed reminder).
     - Disclaimer blockquote swapped from the "curated summary / image-only scan"
       wording to the standard verbatim wording.
     - The body between '## At a glance' and '## Provenance & change history' (i.e.
       whatever summary content was there — a 'Key provisions' section, or nothing)
       is replaced with '## Full text' (the OCR'd, cleaned text) followed by a
       '## Curator notes' disclosing the OCR step (an explicitly allowed heading for
       curator-authored context, per AGENTS.md's content policy).
     - Nothing else (title, citation, legal_authority, relationships, tags, effective
       dates) is touched — those were already transcribed correctly by the original
       visual-reading summary.

This does NOT touch REVIEW.md, link_graph.py's edges, or llms.txt — run the normal
close-out chain (link_graph.py, review_queue.py, build_llms.py, both validators) after
promoting a batch, same as any other ingest."""
import argparse
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ingest_lib import clean_pdf_text
from repo_lib import REPO_ROOT, SNAPSHOT_DIR, content_files, normalize_ws, parse_frontmatter

TODAY = date.today().isoformat()
MIN_WORDS, MIN_DICT_RATIO = 100, 0.80
DICT_PATHS = ["/usr/share/dict/words", "/usr/share/dict/american-english"]


def load_dictionary():
    for p in DICT_PATHS:
        if Path(p).is_file():
            return {w.strip().lower() for w in Path(p).read_text().splitlines()
                    if w.strip().isalpha()}
    return None


def text_quality(text: str, dictionary):
    """(word_count, dict_ratio) — identical gate to src/ingest_eo.py's."""
    words = [w for w in re.findall(r"[A-Za-z]+", text) if len(w) > 1]
    if not words or dictionary is None:
        return len(words), 0.0
    hits = sum(1 for w in words if w.lower() in dictionary)
    return len(words), hits / len(words)


def find_doc(doc_id: str) -> Path | None:
    for p in content_files():
        if p.stem == doc_id:
            return p
    return None


def ocr_and_extract(pdf_path: Path) -> str:
    with tempfile.TemporaryDirectory() as td:
        ocr_pdf = Path(td) / "ocr.pdf"
        subprocess.run(
            ["ocrmypdf", "--deskew", "--clean", "--optimize", "1",
             "--quiet", str(pdf_path), str(ocr_pdf)],
            check=True, capture_output=True)
        return subprocess.run(
            ["pdftotext", "-layout", str(ocr_pdf), "-"],
            capture_output=True, text=True, check=True).stdout


def promote(doc_id: str, dictionary, dry_run: bool) -> str:
    path = find_doc(doc_id)
    if path is None:
        return f"SKIP  {doc_id}: no such document"
    fm, body = parse_frontmatter(path)

    if fm.get("content_mode") != "summary":
        return f"SKIP  {doc_id}: content_mode is {fm.get('content_mode')!r}, not 'summary'"
    exc = fm.get("content_exception", "")
    if "image-only" not in exc and "no extractable text" not in exc and "no text layer" not in exc:
        return f"SKIP  {doc_id}: content_exception doesn't read as an image-only scan: {exc!r}"
    if fm.get("source_format") != "pdf":
        return f"SKIP  {doc_id}: source_format is {fm.get('source_format')!r}, not pdf"
    pdf_path = SNAPSHOT_DIR / f"{doc_id}.pdf"
    if not pdf_path.is_file():
        return f"SKIP  {doc_id}: no committed snapshot at {pdf_path}"

    try:
        raw_ocr_text = ocr_and_extract(pdf_path)
    except subprocess.CalledProcessError as e:
        return (f"FAIL  {doc_id}: ocrmypdf failed with exit code {e.returncode}; "
                f"left untouched")
    words, ratio = text_quality(raw_ocr_text, dictionary)
    if words < MIN_WORDS or ratio < MIN_DICT_RATIO:
        return (f"FAIL  {doc_id}: OCR quality gate failed "
                f"({words} words, {ratio:.0%} dictionary — need >={MIN_WORDS} words "
                f"and >={MIN_DICT_RATIO:.0%}); left untouched")

    if dry_run:
        return f"PASS  {doc_id}: {words} words, {ratio:.0%} dictionary (dry run, nothing written)"

    txt_path = SNAPSHOT_DIR / f"{doc_id}.txt"
    txt_path.write_text(raw_ocr_text, encoding="utf-8")

    full_text, conv_notes = clean_pdf_text(raw_ocr_text)
    conv_notes = ("text recovered via OCR (ocrmypdf/tesseract) from an image-only "
                  f"scan, not the source's own text layer; {conv_notes}")
    new_sha = __import__("hashlib").sha256(
        normalize_ws(txt_path.read_text(encoding="utf-8", errors="replace")).encode("utf-8")
    ).hexdigest()

    text = path.read_text()
    text = re.sub(r'^content_mode: summary$', 'content_mode: verbatim', text, count=1, flags=re.M)
    text = re.sub(r'^content_exception: .*(\n(?:  .*\n)*)?', '', text, count=1, flags=re.M)
    text = re.sub(r'^conversion_notes: .*$', f'conversion_notes: "{conv_notes}"',
                  text, count=1, flags=re.M)
    if "conversion_notes:" not in text:
        text = re.sub(r'^(content_mode: verbatim)$',
                      f'\\1\nconversion_notes: "{conv_notes}"', text, count=1, flags=re.M)
    text = text.replace(fm["source_sha256"], new_sha)
    text = re.sub(r'^last_verified: .*$', f'last_verified: "{TODAY}"', text, count=1, flags=re.M)

    text = re.sub(
        r'> \*\*NON-AUTHORITATIVE.*?\(retrieved [^)]+\)\.\n',
        f'> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated copy of the\n'
        f'> official text. Verify against the official source: <{fm["source_url"]}> '
        f'(retrieved {fm["retrieved"]}).\n',
        text, count=1, flags=re.S)
    text = re.sub(
        rf'- Snapshot: `_meta/snapshots/{re.escape(doc_id)}\.pdf`.*$',
        f'- Snapshot: `_meta/snapshots/{doc_id}.pdf` / `.txt`',
        text, count=1, flags=re.M)

    curator_note = (f"OCR'd via `ocrmypdf` (tesseract) on {TODAY} because the source PDF has "
                    f"no native text layer — verify against the source PDF for possible OCR "
                    f"misreads before treating any figure or proper noun as certain.")
    new_body_section = f"## Full text\n\n{full_text}\n\n## Curator notes\n\n{curator_note}\n\n"
    # Preserve the "At a glance" paragraph itself; replace only what follows it
    # (a "Key provisions" section, or nothing) up to "## Provenance".
    m = re.search(r'## At a glance\n\n(.*?)\n\n(?=## |\Z)', text, flags=re.S)
    if not m:
        raise ValueError(f"{doc_id}: could not locate '## At a glance' paragraph")
    glance_para = m.group(1)
    text = re.sub(r'## At a glance\n\n.*?(?=## Provenance)',
                  f'## At a glance\n\n{glance_para}\n\n{new_body_section}',
                  text, count=1, flags=re.S)

    path.write_text(text)
    return f"OK    {doc_id}: {words} words, {ratio:.0%} dictionary — promoted to verbatim"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("doc_ids", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dictionary = load_dictionary()
    if dictionary is None:
        sys.exit("no system dictionary found (needed for the OCR quality gate)")
    for doc_id in args.doc_ids:
        print(promote(doc_id, dictionary, args.dry_run))


if __name__ == "__main__":
    main()
