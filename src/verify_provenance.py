#!/usr/bin/env python3
"""Verify provenance under the full-text-first content policy.

For every content file: the source snapshot must exist and match the recorded
content hash (hash_snapshot — deterministic, no re-extraction).

content_mode: verbatim (required for state-authored docs):
  - a '## Full text' section must exist;
  - every non-empty line of it, whitespace-normalized, must appear in the
    snapshot text IN ORDER — mechanically prevents fabrication (HC-1);
  - coverage (normalized full-text length / normalized snapshot-slice length,
    slice per repo_lib.snapshot_slice) must be >= 0.70, warn under 0.90 —
    catches silent omission.

State-authored docs that are not verbatim fail, unless frontmatter carries
content_exception or migration_pending (warn instead). external_reference must
be summary. Legacy [VERBATIM] quote blocks are still checked wherever present.

Scope/scale:
  (default)          verify every content file (push-to-main / nightly)
  --changed [ref]    verify only files changed vs ref (merge-base origin/main
                     if omitted) — for PR CI, keeps runtime flat as the corpus grows
  -j N / --jobs N    parallelize across N processes (default: all CPUs)
"""
import argparse
import multiprocessing as mp
import os

from repo_lib import (
    REPO_ROOT, SNAPSHOT_DIR,
    Reporter, changed_content_files, content_files, extract_fulltext,
    extract_verbatim_quotes, hash_snapshot, normalize_ws, parse_frontmatter,
    snapshot_slice,
)

STATE_AUTHORED = {"statute", "rule", "executive_order", "policy", "procedure",
                  "standard", "manual"}
COVER_FAIL, COVER_WARN = 0.70, 0.90


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


def check_file(path):
    """Verify one content file. Returns (rel, findings, checked, fulltexts, quotes)
    where findings is a list of ('error'|'warn', message). Pure/self-contained so it
    can run in a worker process."""
    rel = path.relative_to(REPO_ROOT)
    findings = []
    checked = fulltexts = quotes = 0
    try:
        fm, body = parse_frontmatter(path)
    except ValueError as e:
        return rel, [("error", str(e))], 0, 0, 0
    doc_id = fm.get("id")
    snap_id = fm.get("snapshot_id") or doc_id
    fmt = fm.get("source_format", "html")
    raw = SNAPSHOT_DIR / f"{snap_id}.{fmt}"
    txt = SNAPSHOT_DIR / f"{snap_id}.txt"
    hash_only = fm.get("snapshot_policy") == "hash-only"
    if hash_only:
        # Raw source deliberately not committed (e.g. executive orders: ~700 MB of
        # image scans). If a .txt extraction is committed, the recorded hash is the
        # normalized-text sha256 and full-text checks run against it as usual; with
        # no .txt (image-only scans) the recorded raw-byte hash of the uncommitted
        # PDF cannot be re-verified here — those docs carry content_exception and
        # are already surfaced in REVIEW.md.
        if txt.is_file():
            import hashlib
            digest = hashlib.sha256(
                normalize_ws(txt.read_text(encoding="utf-8", errors="replace"))
                .encode("utf-8")).hexdigest()
            if digest != fm.get("source_sha256"):
                findings.append(("error", f"source_sha256 mismatch: frontmatter {fm.get('source_sha256')} != committed .txt {digest}"))
            source_text = normalize_ws(txt.read_text(encoding="utf-8", errors="replace"))
        elif fm.get("content_mode") == "verbatim":
            findings.append(("error", "snapshot_policy: hash-only verbatim doc has no committed .txt to verify against"))
            return rel, findings, checked, fulltexts, quotes
        else:
            source_text = ""
    else:
        if not raw.is_file():
            findings.append(("error", f"missing source snapshot {raw.relative_to(REPO_ROOT)}"))
            return rel, findings, checked, fulltexts, quotes
        digest = hash_snapshot(snap_id, fmt)
        if digest != fm.get("source_sha256"):
            findings.append(("error", f"source_sha256 mismatch: frontmatter {fm.get('source_sha256')} != snapshot {digest}"))
        source_text = normalize_ws(
            txt.read_text(encoding="utf-8") if txt.is_file()
            else raw.read_text(encoding="utf-8", errors="replace")
        )
    checked = 1

    mode = fm.get("content_mode")
    state_authored = fm.get("doc_type") in STATE_AUTHORED
    excused = bool(fm.get("content_exception") or fm.get("migration_pending"))

    if state_authored and mode != "verbatim":
        msg = f"state-authored doc with content_mode: {mode}"
        if excused:
            findings.append(("warn", msg + " (excused: content_exception/migration_pending)"))
        else:
            findings.append(("error", msg + " — full text required, or add content_exception"))

    if mode == "verbatim":
        ft = extract_fulltext(body)
        if ft is None:
            findings.append(("error", "content_mode: verbatim but no '## Full text' section"))
        else:
            fulltexts = 1
            pos, bad = 0, None
            for line in ft.splitlines():
                nl = normalize_ws(line)
                if not nl:
                    continue
                i = source_text.find(nl, pos)
                if i == -1:
                    bad = nl
                    break
                pos = i + len(nl)
            if bad is not None:
                findings.append(("error", f"full-text line not found in snapshot (in order): \"{bad[:90]}\""))
            raw_txt = (txt.read_text(encoding="utf-8", errors="replace")
                       if txt.is_file() else raw.read_text(encoding="utf-8", errors="replace"))
            denom = len(normalize_ws(snapshot_slice(doc_id, snap_id, raw_txt))) or 1
            cover = len(normalize_ws(ft)) / denom
            if cover < COVER_FAIL:
                findings.append(("error", f"full-text coverage {cover:.0%} of source slice (< {COVER_FAIL:.0%})"))
            elif cover < COVER_WARN:
                findings.append(("warn", f"full-text coverage {cover:.0%} of source slice"))

    for q in extract_verbatim_quotes(body):
        quotes += 1
        if not quote_in_text(q, source_text):
            findings.append(("error", f"[VERBATIM] quote not found in snapshot: \"{normalize_ws(q)[:80]}…\""))

    return rel, findings, checked, fulltexts, quotes


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--changed", nargs="?", const="", metavar="REF",
                    help="verify only files changed vs REF (default: merge-base with origin/main)")
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1,
                    help="worker processes (default: all CPUs)")
    args = ap.parse_args()

    if args.changed is not None:
        paths = changed_content_files(args.changed or None)
        if not paths:
            print("No changed content files to verify.")
            return
        print(f"Verifying {len(paths)} changed file(s).")
    else:
        paths = list(content_files())

    r = Reporter()
    checked = quotes = fulltexts = 0
    jobs = max(1, args.jobs)
    if jobs == 1 or len(paths) < 50:
        results = (check_file(p) for p in paths)
    else:
        # fork inherits the loaded corpus/modules — no re-import or per-task pickling
        # (Python 3.14 defaults to forkserver; CI's 3.12 defaults to fork).
        ctx = mp.get_context("fork")
        pool = ctx.Pool(jobs)
        results = pool.imap_unordered(check_file, paths, chunksize=64)
    for rel, findings, c, f, q in results:
        for level, msg in findings:
            (r.error if level == "error" else r.warn)(rel, msg)
        checked += c; fulltexts += f; quotes += q
    if jobs != 1 and len(paths) >= 50:
        pool.close(); pool.join()

    r.finish(f"OK: {checked} file(s); {fulltexts} full-text section(s) and "
             f"{quotes} legacy quote(s) verified against snapshots.")


if __name__ == "__main__":
    main()
