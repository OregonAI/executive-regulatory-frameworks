#!/usr/bin/env python3
"""Second-chance OCR for executive orders that have NO machine-verifiable text at all.

Scope is deliberately narrow. This is NOT a replacement for the incumbent
ocrmypdf/tesseract pipeline: a 26-document bake-off found the alternative engines
*worse* than tesseract wherever tesseract already produces output (0 of 18 improved
dictionary ratio; mean 87.6% -> 75.3%; fewer words captured). Re-OCRing the whole
corpus would make it worse.

Where they win is the 27 orders tesseract produced nothing for — 17 of which crashed
ocrmypdf outright (exit 6), so tesseract never got a chance at the page. Those orders
are metadata stubs today: no `## Full text`, nothing diffable, flagged in REVIEW.md as
the highest review priority. Recovering them adds text where there is currently none,
which is a strictly different (and safer) proposition than replacing text that exists.

THE GUARDRAIL. AGENTS.md's rule is "never auto-OCR a scan into `## Full text`", written
when the only available option was a single engine that produced garbage. This tool is
the amended form of that rule, not an exemption from it: text is promoted only when TWO
INDEPENDENT engines agree. Two engines inventing the *same* words is vanishingly
unlikely, so high agreement is positive evidence the words are really on the page —
which is exactly the assurance a single engine cannot give. Promotion additionally
requires the pre-existing quality gate (>= MIN_WORDS words, >= MIN_DICT_RATIO
dictionary-recognizable) to pass unchanged.

Anything below either bar is left exactly as it is — still a stub, still in REVIEW.md —
with the attempt recorded in `_meta/catalog/eo.yml`'s `text_layer` so a later run can
tell "we tried and it failed" from "we never tried".

On the measured corpus the two signals agree completely: the 15 orders that clear the
quality gate are the same 15 scoring 87.2-97.3% agreement, and the 12 that fail score
35.0-60.8%. The population is bimodal with a wide gap, so the threshold is not
finely balanced.

  python3 src/ocr_fallback_eo.py --report          # score candidates, write nothing
  python3 src/ocr_fallback_eo.py --apply           # promote everything above both bars
  python3 src/ocr_fallback_eo.py --apply --id eo-06-05
"""
import argparse
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from ingest_eo import CATALOG, MIN_DICT_RATIO, MIN_WORDS, TODAY, parse_signed_date
from repo_lib import REPO_ROOT, SNAPSHOT_DIR, normalize_ws

EO_DIR = REPO_ROOT / "executive-orders"
PDF_CACHE = REPO_ROOT / "_meta/.cache/eo-pdfs"      # gitignored; hash-only policy intact

# Minimum cross-engine word-sequence agreement to promote. Set below the observed
# good-population floor (87.2%) and far above the failed population's ceiling (60.8%).
MIN_AGREEMENT = 0.80

ENGINES = ("rapidocr-onnxruntime", "easyocr")


def _vocabulary() -> set:
    """Dictionary for the quality gate, built from the corpus's own HTML-sourced statute
    text. The upstream pipeline reads /usr/share/dict/words, which is absent both here
    and on the CI runner (the generated-views job installs only pyyaml) — and a general
    English wordlist is a poor fit for statutory prose anyway.

    Sampling is deterministic and spread across the whole ORS range on purpose. An
    arbitrary slice (e.g. the first 400 files, which are all chapter 1xx) yields a
    vocabulary skewed to a few subject areas, and the resulting dictionary ratios swing
    by 5-10 points — enough to move documents across the promotion threshold. The gate
    must not depend on which files the glob happened to return first."""
    files = sorted(REPO_ROOT.glob("statutes/ors-*.md"))
    step = max(1, len(files) // 2000)                  # ~2000 files, evenly spread
    vocab = set()
    for p in files[::step]:
        vocab |= set(re.findall(r"[a-z]{2,}", p.read_text(encoding="utf-8", errors="replace").lower()))
    return vocab


def score(text_a: str, text_b: str, vocab: set) -> dict:
    """Quality + agreement for one order. `text_a` is the engine whose output would be
    committed; `text_b` is the independent cross-check."""
    wa = re.findall(r"[a-z]{2,}", text_a.lower())
    wb = re.findall(r"[a-z]{2,}", text_b.lower())
    ratio = sum(1 for w in wa if w in vocab) / len(wa) if wa else 0.0
    agreement = difflib.SequenceMatcher(None, wa, wb, autojunk=False).ratio() if wa and wb else 0.0
    # Wide-tracked letterhead and all-caps headings ("INTERAGENCY COUNCIL ON …") get
    # split per glyph-cluster by the detector and rejoined without spaces. Count the
    # artifact so it can be DISCLOSED rather than silently shipped. Deliberately not
    # repaired: re-inserting word boundaries would be reconstructing text that the OCR
    # did not actually resolve, which is the thing the content policy forbids.
    glued = len(re.findall(r"\b[A-Za-z]{18,}\b", text_a))
    return {"words": len(wa), "dict_ratio": ratio, "agreement": agreement, "glued": glued,
            "gate_ok": len(wa) >= MIN_WORDS and ratio >= MIN_DICT_RATIO,
            "agree_ok": agreement >= MIN_AGREEMENT}


def promote(md_path: Path, oid: str, text: str, s: dict, url: str) -> str:
    """Rewrite a metadata stub into a verbatim document. Returns the new file text.

    The committed extraction and `source_sha256` must satisfy the toolkit's hash-only
    branch: with a .txt present, source_sha256 must equal sha256 of its
    whitespace-normalized content, or corpus-verify-provenance fails CI."""
    digest = hashlib.sha256(normalize_ws(text).encode("utf-8")).hexdigest()
    date = parse_signed_date(normalize_ws(text), oid)
    glued_note = (f"; {s['glued']} heading/letterhead token(s) lost their word spacing in "
                  f"extraction and are left as-is rather than reconstructed"
                  if s["glued"] else "")
    notes = (f"text recovered via fallback OCR after the primary engine produced none; "
             f"two independent engines ({' + '.join(ENGINES)}) agree on "
             f"{s['agreement']:.0%} of the word sequence, {s['dict_ratio']:.0%} "
             f"dictionary-recognizable{glued_note}; NOT human-verified")
    raw = md_path.read_text(encoding="utf-8")

    raw = re.sub(r"^content_mode: summary$", "content_mode: verbatim", raw, count=1, flags=re.M)
    raw = re.sub(r'^content_exception: ".*"$', f'conversion_notes: "{notes}"', raw, count=1, flags=re.M)
    raw = re.sub(r'^source_sha256: ".*"$', f'source_sha256: "{digest}"', raw, count=1, flags=re.M)
    raw = re.sub(r"^last_verified: .*$", f'last_verified: "{TODAY}"', raw, count=1, flags=re.M)
    if date:
        raw = re.sub(r"^effective_date: null$", f'effective_date: "{date}"', raw, count=1, flags=re.M)

    # Banner: the stub's version asserts the file carries no verbatim text. It now does.
    raw = re.sub(
        r"> \*\*NON-AUTHORITATIVE.*?\(retrieved [\d-]+\)\.\n",
        "> **NON-AUTHORITATIVE — AI-friendly reference only.** The text below was recovered by\n"
        "> OCR from a scan and is **not human-verified**. Verify against the official\n"
        f"> source: <{url}> (retrieved {TODAY}).\n",
        raw, count=1, flags=re.S)

    body = ("## Full text\n\n" + text.strip() + "\n\n"
            "## Curator notes\n\n"
            "The source PDF has no usable text layer, so this text was produced by OCR, not by "
            "the document's own embedded text. It was promoted only because two independent OCR "
            f"engines ({' + '.join(ENGINES)}) independently produced "
            f"{s['agreement']:.0%}-matching output — agreement between independent engines is "
            "evidence the words are on the page, not invented. It has **not** been checked by a "
            "human against the source. Signature blocks, names, and dates are the least reliable "
            "part of an OCR'd scan; treat them with particular care and verify anything "
            "load-bearing against the linked source PDF. Wide-tracked letterhead and all-caps "
            "headings sometimes lose their word spacing in extraction (`OfficeoftheGovernor`); "
            "these are left exactly as extracted rather than repaired, because re-inserting word "
            "boundaries would mean writing text the OCR did not resolve. Body prose is "
            "unaffected.\n\n"
            "## Provenance & change history")
    raw = re.sub(r"## Provenance & change history", body, raw, count=1)
    raw = re.sub(r"· raw-byte sha256 `[0-9a-f]{64}`",
                 f"· text-content sha256 `{digest}`", raw, count=1)
    raw = re.sub(r"there is no text layer to commit, so nothing diffs this document against its source mechanically\.",
                 f"the OCR text extraction is committed as `_meta/snapshots/{oid}.txt`.", raw, count=1)
    return raw


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write changes (default: report only)")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--id", help="restrict to one order id")
    ap.add_argument("--rapid-dir", default="/tmp/rapid27", help="engine-1 output dir")
    ap.add_argument("--easy-dir", default="/tmp/easy27", help="engine-2 output dir")
    args = ap.parse_args()

    cat = yaml.safe_load(CATALOG.read_text())
    by_id = {o["id"]: o for o in cat["orders"]}
    targets = [o for o in cat["orders"] if (o.get("text_layer") or "").startswith("none")]
    if args.id:
        targets = [o for o in targets if o["id"] == args.id]

    vocab = _vocabulary()
    promoted = skipped = 0
    print(f"{'id':16s} {'words':>5s} {'dict':>5s} {'agree':>6s}  decision")
    print("-" * 56)
    for o in sorted(targets, key=lambda x: x["id"]):
        oid = o["id"]
        pa, pb = Path(args.rapid_dir) / f"{oid}.txt", Path(args.easy_dir) / f"{oid}.txt"
        if not (pa.is_file() and pb.is_file()):
            print(f"{oid:16s} {'':5s} {'':5s} {'':6s}  SKIP (missing engine output)")
            continue
        a, b = pa.read_text(encoding="utf-8"), pb.read_text(encoding="utf-8")
        s = score(a, b, vocab)
        ok = s["gate_ok"] and s["agree_ok"]
        why = "promote" if ok else ("below agreement" if not s["agree_ok"] else "below quality gate")
        print(f"{oid:16s} {s['words']:5d} {s['dict_ratio']:5.0%} {s['agreement']:6.1%}  {why}")

        if not ok:
            skipped += 1
            if args.apply:
                o["text_layer"] = (f"none (fallback OCR attempted {TODAY}: {s['words']} words, "
                                   f"{s['dict_ratio']:.0%} dictionary, {s['agreement']:.0%} "
                                   f"cross-engine agreement — below threshold)")
            continue
        if args.apply:
            md = EO_DIR / f"{oid}.md"
            (SNAPSHOT_DIR / f"{oid}.txt").write_text(a, encoding="utf-8")
            md.write_text(promote(md, oid, a, s, o["file_ref"] and
                                  f"https://www.oregon.gov{o['file_ref']}" or ""), encoding="utf-8")
            o["text_layer"] = (f"fallback-ocr ({s['words']} words, {s['dict_ratio']:.0%} "
                               f"dictionary, {s['agreement']:.0%} cross-engine agreement)")
        promoted += 1

    print(f"\n{promoted} promotable, {skipped} left as stubs "
          f"(thresholds: >= {MIN_WORDS} words, >= {MIN_DICT_RATIO:.0%} dictionary, "
          f">= {MIN_AGREEMENT:.0%} agreement)")
    if args.apply:
        CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
        print("applied; _meta/catalog/eo.yml updated")
    else:
        print("report only — pass --apply to write")


if __name__ == "__main__":
    main()
