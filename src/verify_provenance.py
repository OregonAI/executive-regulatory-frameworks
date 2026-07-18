#!/usr/bin/env python3
"""Verify provenance: each content file's source snapshot exists and matches its
recorded sha256, and every [VERBATIM] quote is a literal (whitespace-normalized)
substring of the snapshot text. '…' inside a quote marks an elision: each segment
must appear, in order. This mechanically prevents quote fabrication (AGENTS.md)."""
import hashlib

from repo_lib import (
    REPO_ROOT, SNAPSHOT_DIR,
    Reporter, content_files, extract_verbatim_quotes, normalize_ws, parse_frontmatter,
)


def quote_in_text(quote: str, text: str) -> bool:
    segments = [normalize_ws(s) for s in quote.split("…")]
    pos = 0
    for seg in segments:
        if not seg:
            continue
        i = text.find(seg, pos)
        if i == -1:
            return False
        pos = i + len(seg)
    return True


def main():
    r = Reporter()
    checked = quotes = 0
    for path in content_files():
        rel = path.relative_to(REPO_ROOT)
        try:
            fm, body = parse_frontmatter(path)
        except ValueError as e:
            r.error(rel, str(e))
            continue
        doc_id, fmt = fm.get("id"), fm.get("source_format", "html")
        raw = SNAPSHOT_DIR / f"{doc_id}.{fmt}"
        if not raw.is_file():
            r.error(rel, f"missing source snapshot {raw.relative_to(REPO_ROOT)}")
            continue
        digest = hashlib.sha256(raw.read_bytes()).hexdigest()
        if digest != fm.get("source_sha256"):
            r.error(rel, f"source_sha256 mismatch: frontmatter {fm.get('source_sha256')} != snapshot {digest}")
        txt = SNAPSHOT_DIR / f"{doc_id}.txt"
        source_text = normalize_ws(
            txt.read_text(encoding="utf-8") if txt.is_file()
            else raw.read_text(encoding="utf-8", errors="replace")
        )
        for q in extract_verbatim_quotes(body):
            quotes += 1
            if not quote_in_text(q, source_text):
                r.error(rel, f"[VERBATIM] quote not found in snapshot: \"{normalize_ws(q)[:80]}…\"")
        checked += 1
    r.finish(f"OK: {checked} file(s), {quotes} [VERBATIM] quote(s) verified against snapshots.")


if __name__ == "__main__":
    main()
