#!/usr/bin/env python3
"""Second-engine corroboration for executive orders already recovered by OCR.

WHAT THIS DOES AND, MORE IMPORTANTLY, WHAT IT DOES NOT. 479 orders carry text recovered by
a SINGLE engine (ocrmypdf/tesseract) and say so in `conversion_notes`. A single engine's
output is unverifiable -- there is nothing to check it against -- and the two-engine rule in
AGENTS.md was written after those orders were ingested. This script supplies the missing
evidence: it reads the ORIGINAL scan with a second, independent engine and measures how far
the two agree.

IT NEVER REWRITES `## Full text`. AGENTS.md rule 1 is explicit that OCR may add text where a
stub has none and may never replace or "improve" text already committed, and that rule is
backed by measurement in this repo -- a 26-order bake-off found alternative engines worse
than the incumbent wherever the incumbent produced output (0 of 18 improved, mean dictionary
ratio 87.6% -> 75.3%). So this run changes provenance, not content: `conversion_notes` gains
the second engine and the agreement rates, and `source_sha256` is deliberately left alone
because it hashes the committed text, which does not change.

Corroboration is therefore evidence about text that is already published, gathered after the
fact. A document scoring below the bar is NOT edited and NOT withdrawn -- it is reported, so
a human can look at it. Silently rewriting 479 documents on the strength of an unreviewed
second reading would be the exact failure the two-engine rule exists to prevent.

THE PAIR IS tesseract + PaddleOCR, INHERITED FROM oregon-kpm's measured bake-off (word
agreement 0.816-0.929 across six scans, docTR lower on every one and therefore the tiebreaker
rather than the default). The committed `_meta/snapshots/<id>.txt` IS the tesseract reading --
`cmd_ocr` in ingest_eo.py writes exactly that file from `ocrmypdf | pdftotext` -- so tesseract
does not need re-running. Paddle reads the original scan, which is what keeps the two engines
independent: corroborating against a copy of the first engine's output would be an echo, not
evidence.

ORIENTATION HANDLING IS NOT OPTIONAL. Measured in oregon-kpm: with Paddle's
`use_doc_orientation_classify=False` a rotated scan scored 0.050 against tesseract, and 0.929
with it on. Same page, same engines. A corroboration check with orientation off is an
orientation check wearing a corroboration check's clothes, and it fails documents that are
fine.

Two passes on purpose:

    --measure   read every cached PDF with Paddle, write results to a JSON report.
    --apply     update `conversion_notes` from that report.

Splitting them means 500 documents are not mutated by the same command that computes the
numbers, so the numbers can be reviewed first.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

import yaml

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "_meta" / "catalog" / "eo.yml"
SNAPSHOTS = ROOT / "_meta" / "snapshots"
CACHE = ROOT / "_meta" / ".cache" / "eo-pdfs"
REPORT = ROOT / "_meta" / ".cache" / "eo-corroboration.json"
EO_DIR = ROOT / "executive-orders"

# Same bars as ingest_eo.py and the two-engine rule. Imported by value rather than from
# ingest_eo so this script does not drag in that module's network-facing imports.
MIN_AGREEMENT = 0.80
MIN_DICT_RATIO = 0.80
MIN_WORDS = 100

PRIMARY = "ocrmypdf/tesseract"
CROSS = "paddleocr PP-OCRv6"

# The host's wordlist, then the cache copy. `wamerican` is the intended source and is what
# ingest_eo.py's DICT_PATHS expects; the cache path exists because this host has no system
# dictionary installed and the gate cannot run without one.
DICT_PATHS = ["/usr/share/dict/words", "/usr/share/dict/american-english",
              str(ROOT / "_meta" / ".cache" / "wordlist" / "american-english")]

WORD = re.compile(r"[a-z]{2,}")
# Dates, section numbers, and the occasional dollar figure. Executive orders are prose, so
# this is reported for disclosure rather than gated on -- but ORS citations and effective
# dates are exactly the tokens a reader relies on, and they are where two engines diverge.
FIGURE = re.compile(r"\$?-?\d[\d,]*(?:\.\d+)?%?")


def load_dictionary() -> set[str] | None:
    for p in DICT_PATHS:
        if Path(p).is_file():
            return {w.strip().lower() for w in Path(p).read_text().splitlines()
                    if w.strip().isalpha()}
    return None


def paddle_text(pdf: Path, workdir: Path) -> str | None:
    """PaddleOCR over the ORIGINAL scan. None when the page render or the engine fails."""
    try:
        from paddleocr import PaddleOCR
    except ImportError:
        return None
    workdir.mkdir(parents=True, exist_ok=True)
    for old in workdir.glob("*.png"):
        old.unlink()
    try:
        subprocess.run(["pdftoppm", "-r", "200", "-png", str(pdf), str(workdir / "p")],
                       check=True, capture_output=True, timeout=1800)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    global _OCR
    if _OCR is None:
        from paddleocr import PaddleOCR as _P
        # Orientation classification ON -- see the module docstring. use_doc_unwarping is
        # off because these are flatbed scans of paper, not photographs of curved pages.
        _OCR = _P(lang="en", use_doc_orientation_classify=True,
                  use_doc_unwarping=False, use_textline_orientation=True)
    out: list[str] = []
    for img in sorted(workdir.glob("p-*.png")):
        try:
            for d in _OCR.predict(str(img)):
                out.extend(d.get("rec_texts") or [])
        except Exception:                                  # noqa: BLE001 — one bad page
            continue
    return "\n".join(out)


_OCR = None


def score(primary: str, cross_check: str, vocab: set[str]) -> dict:
    """Quality of the COMMITTED text, and how far the second engine agrees with it."""
    wa = WORD.findall(primary.lower())
    wb = WORD.findall(cross_check.lower())
    ratio = sum(1 for w in wa if w in vocab) / len(wa) if wa else 0.0
    agreement = (difflib.SequenceMatcher(None, wa, wb, autojunk=False).ratio()
                 if wa and wb else 0.0)
    glued = len(re.findall(r"\b[A-Za-z]{18,}\b", primary))
    fa = FIGURE.findall(primary.lower())
    fb = FIGURE.findall(cross_check.lower())
    fig = (difflib.SequenceMatcher(None, fa, fb, autojunk=False).ratio()
           if fa and fb else 0.0)
    return {"words": len(wa), "cross_words": len(wb), "dict_ratio": round(ratio, 4),
            "agreement": round(agreement, 4), "glued": glued, "figures": len(fa),
            "figure_agreement": round(fig, 4),
            "gate_ok": len(wa) >= MIN_WORDS and ratio >= MIN_DICT_RATIO,
            "agree_ok": agreement >= MIN_AGREEMENT}


def notes_for(s: dict) -> str:
    """`conversion_notes` for a document whose text was NOT changed by this run.

    The wording has to carry three facts a reader needs and none it cannot support: which
    engines read the page, how far they agreed, and that the committed text is the ORIGINAL
    single-engine extraction rather than anything this run produced.
    """
    glued_note = (f"; {s['glued']} heading/letterhead token(s) lost their word spacing in "
                  f"extraction and are left as-is rather than reconstructed"
                  if s["glued"] else "")
    fig_note = (f" and {s['figure_agreement']:.0%} of the {s['figures']} figures"
                if s["figures"] else "")
    return (f"text recovered via OCR ({PRIMARY}); corroborated after the fact by a second "
            f"independent engine ({CROSS}) reading the original scan, agreeing on "
            f"{s['agreement']:.0%} of the word sequence{fig_note}, "
            f"{s['dict_ratio']:.0%} dictionary-recognizable{glued_note}; committed text is "
            f"the original single-engine extraction and was not altered by corroboration; "
            f"NOT human-verified")


def in_scope(cat: dict, states: list[str]) -> list[dict]:
    return [o for o in cat["orders"]
            if any(str(o.get("text_layer", "")).startswith(s) for s in states)]


def cmd_measure(args) -> int:
    vocab = load_dictionary()
    if vocab is None:
        sys.exit("no wordlist found (looked in: " + ", ".join(DICT_PATHS) + ")")
    cat = yaml.safe_load(CATALOG.read_text())
    orders = in_scope(cat, args.states)
    if args.only:
        orders = [o for o in orders if o["id"] in set(args.only)]

    results = json.loads(REPORT.read_text()) if REPORT.is_file() and not args.restart else {}
    todo = [o for o in orders if o["id"] not in results][:args.limit or None]
    print(f"{len(orders)} in scope, {len(results)} already measured, {len(todo)} to do",
          file=sys.stderr)

    with tempfile.TemporaryDirectory() as td:
        wd = Path(td) / "pages"
        for i, o in enumerate(todo, 1):
            oid = o["id"]
            pdf = CACHE / f"{oid}.pdf"
            snap = SNAPSHOTS / f"{oid}.txt"
            if not pdf.is_file():
                results[oid] = {"status": "no-cached-pdf"}
            elif not snap.is_file():
                results[oid] = {"status": "no-committed-text"}
            else:
                cross = paddle_text(pdf, wd)
                if not cross:
                    results[oid] = {"status": "cross-engine-produced-nothing"}
                else:
                    s = score(snap.read_text(encoding="utf-8", errors="replace"),
                              cross, vocab)
                    s["status"] = "measured"
                    results[oid] = s
            if i % 10 == 0 or i == len(todo):
                REPORT.write_text(json.dumps(results, indent=2, sort_keys=True))
                done = [r for r in results.values() if r.get("status") == "measured"]
                print(f"  [{i}/{len(todo)}] measured={len(done)} "
                      f"below_bar={sum(1 for r in done if not r['agree_ok'])}",
                      file=sys.stderr)
    REPORT.write_text(json.dumps(results, indent=2, sort_keys=True))
    return 0


def cmd_apply(args) -> int:
    """Rewrite `conversion_notes` only. Never touches the body or `source_sha256`."""
    if not REPORT.is_file():
        sys.exit("no report; run --measure first")
    results = json.loads(REPORT.read_text())
    changed = skipped = below = 0
    for oid, s in sorted(results.items()):
        if s.get("status") != "measured":
            skipped += 1
            continue
        if not s["agree_ok"]:
            # Reported, not edited. A document the second engine does not corroborate keeps
            # its original single-engine note; claiming corroboration it does not have would
            # be worse than claiming none.
            below += 1
            continue
        md = EO_DIR / f"{oid}.md"
        if not md.is_file():
            skipped += 1
            continue
        text = md.read_text(encoding="utf-8")
        new = notes_for(s)
        out, n = re.subn(r'^conversion_notes: ".*?"$',
                         'conversion_notes: "' + new.replace('"', "'") + '"',
                         text, count=1, flags=re.M | re.S)
        if n and out != text:
            if not args.dry_run:
                md.write_text(out, encoding="utf-8")
            changed += 1
        else:
            skipped += 1
    print(f"conversion_notes updated: {changed}  below-bar (left as-is): {below}  "
          f"skipped: {skipped}" + ("  [DRY RUN]" if args.dry_run else ""), file=sys.stderr)
    return 0


def cmd_report(args) -> int:
    if not REPORT.is_file():
        sys.exit("no report; run --measure first")
    results = json.loads(REPORT.read_text())
    ok = [r for r in results.values() if r.get("status") == "measured"]
    bad = {k: v.get("status") for k, v in results.items() if v.get("status") != "measured"}
    if not ok:
        print("nothing measured yet")
        return 0
    ag = sorted(r["agreement"] for r in ok)
    fg = sorted(r["figure_agreement"] for r in ok if r["figures"])
    def pct(xs, q): return xs[int(q * (len(xs) - 1))]
    print(f"measured           {len(ok)}")
    print(f"word agreement     min {ag[0]:.3f}  p10 {pct(ag,.10):.3f}  "
          f"median {pct(ag,.5):.3f}  max {ag[-1]:.3f}")
    if fg:
        print(f"figure agreement   min {fg[0]:.3f}  p10 {pct(fg,.10):.3f}  "
              f"median {pct(fg,.5):.3f}  max {fg[-1]:.3f}")
    print(f"below {MIN_AGREEMENT} agreement  {sum(1 for r in ok if not r['agree_ok'])}")
    print(f"below {MIN_DICT_RATIO} dictionary {sum(1 for r in ok if not r['gate_ok'])}")
    if bad:
        import collections
        for st, n in collections.Counter(bad.values()).items():
            print(f"not measured       {n}  ({st})")
    worst = sorted(ok, key=lambda r: r["agreement"])[:15]
    ids = {id(v): k for k, v in results.items()}
    print("\nlowest agreement:")
    for r in worst:
        print(f"  {ids[id(r)]:24s} agree {r['agreement']:.3f}  "
              f"fig {r['figure_agreement']:.3f}  dict {r['dict_ratio']:.3f}  "
              f"words {r['words']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--restart", action="store_true", help="discard the existing report")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--states", nargs="*", default=["ocr-recovered", "fallback-ocr"])
    args = ap.parse_args()
    if args.measure:
        return cmd_measure(args)
    if args.apply:
        return cmd_apply(args)
    if args.report:
        return cmd_report(args)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
