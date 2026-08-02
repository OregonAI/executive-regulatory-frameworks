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


def tesseract_text(pdf: Path, workdir: Path) -> str | None:
    """ocrmypdf/tesseract over a COPY, then pdftotext. None when ocrmypdf refuses the file.

    `--rotate-pages` is present and was NOT in `ingest_eo.ocr_and_extract`'s flag set. That
    omission is why orientation has to be re-verified here rather than assumed: tesseract at
    default OSD confidence will happily leave a page upside down and emit confident garbage
    that passes every length check. Where a document still reads short, the caller retries
    with `--rotate-pages-threshold 0`.

    Returning None is an expected outcome, not an error. ocrmypdf exits 6 on some of these
    scans -- 17 of the original 27 stubs, per ocr_fallback_eo.py's docstring -- so tesseract
    never gets a look at the page at all, and the pair has to become Paddle + docTR.
    """
    out = workdir / "ocr.pdf"
    src = workdir / "src.pdf"
    workdir.mkdir(parents=True, exist_ok=True)
    src.write_bytes(pdf.read_bytes())
    for extra in ([], ["--rotate-pages-threshold", "0"]):
        out.unlink(missing_ok=True)
        try:
            subprocess.run(["ocrmypdf", "-l", "eng", "--optimize", "0",
                            "--output-type", "pdf", "--rotate-pages", "--deskew",
                            "--clean", "--quiet", *extra, str(src), str(out)],
                           check=True, capture_output=True, timeout=1800)
        except (FileNotFoundError, subprocess.CalledProcessError,
                subprocess.TimeoutExpired):
            continue
        try:
            text = subprocess.run(["pdftotext", "-layout", str(out), "-"],
                                  capture_output=True, text=True, check=True).stdout
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
        if len(WORD.findall(text.lower())) >= MIN_WORDS:
            return text
        last = text
    return locals().get("last") or None


def doctr_text(pdf: Path) -> str | None:
    """docTR (DBNet + CRNN) — the TIEBREAKER, not a default.

    It agrees with tesseract less than Paddle does on every document measured (0.747-0.862),
    so promoting it to default would lower every score. It earns its place on the documents
    where the primary pair cannot run: it straightens pages itself, and in oregon-kpm it was
    the only engine that read a 180-degree-rotated scan correctly with no per-document retry.
    """
    try:
        from doctr.io import DocumentFile
        from doctr.models import ocr_predictor
    except ImportError:
        return None
    global _DOCTR
    try:
        if _DOCTR is None:
            _DOCTR = ocr_predictor(pretrained=True)
        res = _DOCTR(DocumentFile.from_pdf(str(pdf)))
    except Exception:                                      # noqa: BLE001
        return None
    lines = []
    for page in res.pages:
        for block in page.blocks:
            for line in block.lines:
                lines.append(" ".join(w.value for w in line.words))
    return "\n".join(lines)


_DOCTR = None


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


def notes_for(s: dict, existing: str) -> str:
    """Append corroboration to the EXISTING note. Never compose a replacement from scratch.

    The first version of this function built a fresh note out of what corroboration measured,
    and it was wrong twice over -- both failures invisible in a one-line diff:

      * It deleted "no page furniture detected", which 499 orders carry. That is a real
        observation from the original extraction about headers and footers, and nothing in
        this run can re-derive it, because corroboration never looks at the committed text's
        layout.
      * It asserted every document had been recovered by ocrmypdf/tesseract. For the 15
        `fallback-ocr` orders that is FALSE -- their committed text is rapidocr+easyocr's
        reading, which is precisely why they needed a fallback -- and it would have thrown
        away the agreement rate those two engines were measured at.

    So the existing note is authoritative about how the text was produced, and this run has
    exactly one thing to add: that a further independent engine read the same scan and how
    far it agreed. Append, re-terminate, change nothing else.
    """
    fig_note = (f" and {s['figure_agreement']:.0%} of the {s['figures']} figures"
                if s["figures"] else "")
    base = existing.strip().rstrip(".")
    # Re-terminated below, so that the disclaimer stays LAST rather than being buried
    # mid-sentence by the clause we are adding.
    for tail in ("; NOT human-verified", "; not human-verified"):
        if base.endswith(tail):
            base = base[: -len(tail)]
            break
    return (f"{base}; corroborated after the fact by a further independent engine ({CROSS}) "
            f"reading the original scan, agreeing on {s['agreement']:.0%} of the committed "
            f"word sequence{fig_note}, {s['dict_ratio']:.0%} dictionary-recognizable; "
            f"the committed text is the original extraction and was not altered by "
            f"corroboration; NOT human-verified")


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
                # NOT recorded. A missing PDF means the fetch has not reached this order
                # yet, which is a transient state -- writing it into the report would make
                # the resume logic skip the order permanently once the fetch caught up.
                continue
            if not snap.is_file():
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
        m = re.search(r'^conversion_notes: "(.*?)"$', text, re.M | re.S)
        if not m:
            skipped += 1
            continue
        if CROSS in m.group(1):
            # Already corroborated by a previous run. Appending again would stack a second
            # identical clause onto the note every time this is re-run.
            skipped += 1
            continue
        new = notes_for(s, m.group(1))
        # Function replacement, not a string: `new` is built from the note already in the
        # file, so a stray backslash in it would be parsed as an escape sequence and raise
        # `re.error` mid-run. Same bug that aborted ocr_fallback_eo.py's promotion loop on a
        # scan containing "\Z".
        repl = 'conversion_notes: "' + new.replace('"', "'") + '"'
        out, n = re.subn(r'^conversion_notes: ".*?"$', lambda _m: repl,
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


def quality(text: str, vocab: set[str]) -> dict:
    """Absolute quality of ONE reading, so two readings can be compared like for like.

    `score()` deliberately measures only the committed text plus an agreement ratio, which
    is all corroboration needs -- and that turned out to be the wrong thing to store. It
    answers "do the engines agree" and cannot answer "which engine read the page better",
    so 494 documents were measured without ever scoring the second reading. This is the
    missing half.

    Dictionary ratio penalises proper nouns and legal vocabulary in BOTH readings equally,
    so it is a poor absolute score and a fair relative one -- which is exactly the use here.
    """
    w = WORD.findall(text.lower())
    return {"words": len(w),
            "dict_ratio": round(sum(1 for x in w if x in vocab) / len(w), 4) if w else 0.0,
            "glued": len(re.findall(r"\b[A-Za-z]{18,}\b", text))}


def cmd_ab(args) -> int:
    """Score the committed reading against Paddle's, head to head, on a sample.

    WHY THIS EXISTS. AGENTS.md rule 1 forbids replacing committed OCR text and cites a
    26-order bake-off as evidence -- but that bake-off tested rapidocr and easyocr. Paddle
    was never in it. So the rule was applied to an engine its own supporting measurement is
    silent about. This produces the Paddle-specific evidence, and nothing here changes a
    document: it writes numbers and the second reading, and that is all.

    THE PADDLE TEXT IS SAVED THIS TIME. The corroboration pass discarded it after computing
    a ratio, which cost ~90 minutes of GPU time to regenerate for exactly this question.
    """
    vocab = load_dictionary()
    if vocab is None:
        sys.exit("no wordlist found (looked in: " + ", ".join(DICT_PATHS) + ")")
    cat = yaml.safe_load(CATALOG.read_text())
    orders = [o for o in in_scope(cat, args.states) if (CACHE / f"{o['id']}.pdf").is_file()]
    orders.sort(key=lambda o: o["id"])
    if args.only:
        orders = [o for o in orders if o["id"] in set(args.only)]
    elif args.sample:
        # Evenly spaced through the id-sorted list rather than random: ids sort by year, so
        # this spreads the sample across two decades of scan quality instead of clustering
        # in whichever years a seed happened to pick.
        step = max(1, len(orders) // args.sample)
        orders = orders[::step][:args.sample]

    cdir = ROOT / "_meta" / ".cache" / "ocr-cross"
    cdir.mkdir(parents=True, exist_ok=True)
    out_path = ROOT / "_meta" / ".cache" / "eo-ab.json"
    rows = json.loads(out_path.read_text()) if out_path.is_file() and not args.restart else {}

    print(f"{'id':14s} {'tess_w':>7s} {'pad_w':>7s} {'tess_d':>7s} {'pad_d':>7s} "
          f"{'tess_g':>6s} {'pad_g':>6s}  better")
    print("-" * 74)
    with tempfile.TemporaryDirectory() as td:
        wd = Path(td) / "pages"
        for o in orders:
            oid = o["id"]
            if oid in rows:
                continue
            snap = SNAPSHOTS / f"{oid}.txt"
            if not snap.is_file():
                continue
            cached = cdir / f"{oid}.txt"
            cross = (cached.read_text(encoding="utf-8") if cached.is_file()
                     else paddle_text(CACHE / f"{oid}.pdf", wd))
            if not cross:
                continue
            cached.write_text(cross, encoding="utf-8")     # never regenerate this again
            t = quality(snap.read_text(encoding="utf-8", errors="replace"), vocab)
            p = quality(cross, vocab)
            rows[oid] = {"tess": t, "paddle": p}
            better = ("paddle" if p["dict_ratio"] > t["dict_ratio"] + 0.005 else
                      "tesseract" if t["dict_ratio"] > p["dict_ratio"] + 0.005 else "tie")
            print(f"{oid:14s} {t['words']:7d} {p['words']:7d} {t['dict_ratio']:7.3f} "
                  f"{p['dict_ratio']:7.3f} {t['glued']:6d} {p['glued']:6d}  {better}")
            out_path.write_text(json.dumps(rows, indent=2, sort_keys=True))
    out_path.write_text(json.dumps(rows, indent=2, sort_keys=True))

    import statistics as st
    n = len(rows)
    if not n:
        print("nothing compared")
        return 0
    td_ = [v["tess"]["dict_ratio"] for v in rows.values()]
    pd_ = [v["paddle"]["dict_ratio"] for v in rows.values()]
    wins = sum(1 for v in rows.values()
               if v["paddle"]["dict_ratio"] > v["tess"]["dict_ratio"] + 0.005)
    loss = sum(1 for v in rows.values()
               if v["tess"]["dict_ratio"] > v["paddle"]["dict_ratio"] + 0.005)
    print(f"\ncompared {n} orders")
    print(f"  dictionary ratio   tesseract mean {st.mean(td_):.3f} median {st.median(td_):.3f}")
    print(f"                     paddle    mean {st.mean(pd_):.3f} median {st.median(pd_):.3f}")
    print(f"  per-document       paddle better {wins}   tesseract better {loss}   "
          f"tie {n - wins - loss}")
    print(f"  glued tokens       tesseract {sum(v['tess']['glued'] for v in rows.values())}   "
          f"paddle {sum(v['paddle']['glued'] for v in rows.values())}")
    print(f"  total words        tesseract {sum(v['tess']['words'] for v in rows.values()):,}   "
          f"paddle {sum(v['paddle']['words'] for v in rows.values()):,}")
    return 0


def cmd_recover(args) -> int:
    """Read the stubs with BOTH engines and stage the output for ocr_fallback_eo.py.

    Only stubs. AGENTS.md rule 1 lets OCR add text where a document has none, and forbids it
    everywhere else, so this mode cannot touch a recovered order even by accident -- the
    target list is `text_layer: none` and nothing else.

    Staging rather than promoting: `ocr_fallback_eo.py` already owns promotion (the banner
    rewrite, the snapshot, the `source_sha256` recomputation the toolkit's hash-only branch
    re-derives, the catalog update). Duplicating that here would be two implementations of
    the one step where a mistake is not visible in review.
    """
    vocab = load_dictionary()
    if vocab is None:
        sys.exit("no wordlist found (looked in: " + ", ".join(DICT_PATHS) + ")")
    cat = yaml.safe_load(CATALOG.read_text())
    targets = in_scope(cat, ["none"])
    if args.only:
        targets = [o for o in targets if o["id"] in set(args.only)]
    pdir = ROOT / "_meta" / ".cache" / "ocr-primary"
    cdir = ROOT / "_meta" / ".cache" / "ocr-cross"
    pdir.mkdir(parents=True, exist_ok=True)
    cdir.mkdir(parents=True, exist_ok=True)
    pairs_path = ROOT / "_meta" / ".cache" / "eo-recover-pairs.json"
    pairs = json.loads(pairs_path.read_text()) if pairs_path.is_file() else {}

    print(f"{'id':16s} {'primary':>8s} {'cross':>8s} {'agree':>7s} {'dict':>6s}  pair")
    print("-" * 74)
    with tempfile.TemporaryDirectory() as td:
        wd = Path(td)
        for o in sorted(targets, key=lambda x: x["id"]):
            oid = o["id"]
            pdf = CACHE / f"{oid}.pdf"
            if not pdf.is_file():
                print(f"{oid:16s} {'—':>8s} {'—':>8s} {'—':>7s} {'—':>6s}  no cached PDF")
                continue
            primary = tesseract_text(pdf, wd / "tess")
            cross = paddle_text(pdf, wd / "pages")
            pair = (PRIMARY, CROSS)
            if not primary:
                # tesseract could not open the page at all. Paddle becomes the primary and
                # docTR the corroborator -- the tiebreaker earning its keep.
                primary, cross = cross, doctr_text(pdf)
                pair = (CROSS, "docTR (DBNet + CRNN)")
            if not primary or not cross:
                print(f"{oid:16s} {'—':>8s} {'—':>8s} {'—':>7s} {'—':>6s}  "
                      f"no usable output from both engines")
                continue
            s = score(primary, cross, vocab)
            (pdir / f"{oid}.txt").write_text(primary, encoding="utf-8")
            (cdir / f"{oid}.txt").write_text(cross, encoding="utf-8")
            pairs[oid] = {"engines": list(pair), **s}
            print(f"{oid:16s} {s['words']:8d} {s['cross_words']:8d} "
                  f"{s['agreement']:7.1%} {s['dict_ratio']:6.0%}  {' + '.join(pair)}")
    pairs_path.write_text(json.dumps(pairs, indent=2, sort_keys=True))
    good = [k for k, v in pairs.items() if v["gate_ok"] and v["agree_ok"]]
    print(f"\n{len(good)} of {len(targets)} clear both bars "
          f"(>= {MIN_WORDS} words, >= {MIN_DICT_RATIO:.0%} dictionary, "
          f">= {MIN_AGREEMENT:.0%} agreement)")
    print(f"staged in {pdir} and {cdir}; promote with:\n"
          f"  python3 src/ocr_fallback_eo.py --apply")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--ab", action="store_true",
                    help="head-to-head quality of the committed reading vs Paddle")
    ap.add_argument("--sample", type=int, default=0,
                    help="--ab: compare N orders spread evenly across the corpus")
    ap.add_argument("--recover", action="store_true",
                    help="read the text_layer:none stubs with both engines and stage them")
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
    if args.ab:
        return cmd_ab(args)
    if args.recover:
        return cmd_recover(args)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
