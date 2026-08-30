#!/usr/bin/env python3
"""A snapshot's identity is derived once, and the two spellings are made to agree.

  python3 src/snapshot_identity.py --check      every committed snapshot, both spellings
  python3 src/snapshot_identity.py --selftest   every rule, watched failing

WHY THIS EXISTS. Two functions answer "the bytes of this snapshot" and they are not the
same function (corpus-toolkit#207):

  hash_snapshot(id, fmt, dir)   sha256 of the whitespace-normalised text ALREADY COMMITTED
                                in <id>.txt. Never re-derived. Volatile patterns are not
                                applied, because it never sees the raw source.
  content_hash(raw, fmt, pats)  sha256 of the normalised text extracted from raw, with the
                                corpus's volatile patterns STRIPPED FIRST.

`source_sha256` is written with the second and verified with the first. They agree only
while no volatile pattern matches anything that survives into the `.txt` -- and nothing
enforced that or reported it if it stopped being true.

THIS IS THE FIFTH INSTANCE of one fact declared twice with nothing gating agreement:
CURATED_KEYS (#165), the recheck enum against CADENCES (#193), the citation scheme against
AUTHORITY_FORMS (#195), snapshot() against content_hash (this), and legal status against
ingest status (#228). Every one was invisible until something moved.

WHAT MAKES IT URGENT NOW. corpus-toolkit#244: the OARD application's version string sits in
every rule page's footer, moved v2.1.7 -> v2.1.8, and is VISIBLE TEXT -- so it survives
html_to_text into the `.txt`. Adding it to the volatile patterns makes `content_hash` skip
it while `hash_snapshot` still sees it, and provenance fails for every OAR rule. That
was measured, not predicted: an attempt to fix #244 produced exactly that, and the cause
took three wrong diagnoses to find because nothing named the disagreement.

This gate names it. Add a pattern that touches visible text and `--check` goes red the same
day, saying which snapshots and why -- instead of a provenance error per rule pointing at
the wrong thing.
"""
import argparse
import re
import sys
from pathlib import Path

from corpus_toolkit.repo import content_hash, hash_snapshot

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repo_lib import REPO_ROOT, SNAPSHOT_DIR, VOLATILE_PATTERNS  # noqa: E402

# THE ONE DECLARATION #207 ASKED FOR. Both spellings are taken from here, so a future
# change to how a snapshot's bytes are derived moves both or neither.
COMPILED_PATTERNS = tuple(re.compile(p) for p in VOLATILE_PATTERNS)


def spellings(snap_id: str, fmt: str, snapshot_dir: Path, patterns=None) -> tuple[str, str]:
    """The two hashes of one snapshot, in the order (committed-text, extracted-from-raw).

    `patterns` defaults to the corpus's declared set. It is a parameter ONLY so the selftest
    can watch this rule fail: the three patterns declared today all match HTML attributes
    that `html_to_text` removes anyway, so none of them can produce a disagreement, and a
    proof that cannot fail is not a proof. The case that matters -- a pattern touching
    VISIBLE text -- is exactly what corpus-toolkit#244 will add."""
    pats = COMPILED_PATTERNS if patterns is None else patterns
    stored = hash_snapshot(snap_id, fmt, snapshot_dir)
    raw = (snapshot_dir / f"{snap_id}.{fmt}").read_bytes()
    derived = content_hash(raw, fmt, pats)
    return stored, derived


def disagreements(snapshot_dir: Path, limit: int | None = None, patterns=None):
    """Every committed snapshot whose two spellings differ, with both hashes."""
    out = []
    n = 0
    for raw_path in sorted(snapshot_dir.glob("*.html")):
        snap_id = raw_path.name[:-5]
        if not (snapshot_dir / f"{snap_id}.txt").is_file():
            # No committed .txt: hash_snapshot falls back to raw bytes and the two are
            # different questions by construction. Not a disagreement -- reported by count
            # so the population this gate actually covers is never implied.
            continue
        stored, derived = spellings(snap_id, "html", snapshot_dir, patterns)
        n += 1
        if stored != derived:
            out.append((snap_id, stored, derived))
            if limit and len(out) >= limit:
                break
    return out, n


def cmd_check() -> int:
    bad, checked = disagreements(SNAPSHOT_DIR)
    pat_count = len(COMPILED_PATTERNS)
    if bad:
        for snap_id, stored, derived in bad[:20]:
            print(f"  FAIL [snapshot-identity] {snap_id}: the committed .txt hashes to "
                  f"{stored[:16]}… and the raw source with volatile patterns stripped "
                  f"hashes to {derived[:16]}… — `source_sha256` is written with the second "
                  f"and verified with the first, so one of them is now wrong. A volatile "
                  f"pattern matches text that survives into the .txt: regenerate the "
                  f"snapshots, or the pattern is stripping content.")
        if len(bad) > 20:
            print(f"  … and {len(bad) - 20} more")
        print(f"{len(bad)} snapshot(s) whose two spellings disagree, of {checked} checked "
              f"against {pat_count} volatile pattern(s).")
        return 1
    print(f"snapshot identity: {checked} snapshot(s) checked against {pat_count} volatile "
          f"pattern(s); both spellings agree on every one.")
    return 0


# ---------------------------------------------------------------- selftest

_FIRED: set[str] = set()


def _case(name: str, rule: str, build) -> str:
    """Build a synthetic snapshot pair, run the gate over it, and require `rule` to fire."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        dirp = Path(d)
        build(dirp)
        bad, _ = disagreements(dirp, patterns=(re.compile(rb'(?<=class="colophon">)\s*v\d+\.\d+\.\d+'),))
        if not bad:
            return (f"FAIL {name}: expected a [{rule}] disagreement, got none — the gate "
                    f"cannot see the case it exists for")
    _FIRED.add(rule)
    return ""


def _write(dirp: Path, snap_id: str, html: bytes, txt: str) -> None:
    (dirp / f"{snap_id}.html").write_bytes(html)
    (dirp / f"{snap_id}.txt").write_text(txt, encoding="utf-8")


_BODY = ("This is a mirrored administrative rule with enough prose in it to clear the "
         "two-hundred-character floor that both hash functions apply before they fall back "
         "to raw bytes, which they must not do here because the whole point of this gate is "
         "to compare the text spellings rather than the byte ones. " * 2)


def cmd_selftest() -> int:
    fails = []

    # THE CASE #244 WILL PRODUCE. A pattern strips bytes from raw that are still present in
    # the committed .txt, because they were visible text when the .txt was written.
    def volatile_in_txt(dirp: Path):
        html = (f'<html><body><p>{_BODY}</p>'
                f'<div class="colophon">   v2.1.8   </div></body></html>').encode()
        _write(dirp, "case-volatile-in-txt", html, _BODY + " v2.1.8")
    problem = _case("a-pattern-that-strips-text-the-committed-txt-still-carries",
                    "snapshot-identity", volatile_in_txt)
    if problem:
        fails.append(problem)

    # THE FACT #244 ASSERTS, watched both ways: an OARD release must not move the hash
    # of a rule whose text did not change. Proved against the REAL declared pattern set,
    # and watched failing with the colophon pattern removed -- without that mutation this
    # would pass on a corpus where the pattern was never added.
    def _page(version: str) -> bytes:
        return (f'<html><body><p>{_BODY}</p>'
                f'<div class="colophon">\n    {version}\n</div></body></html>').encode()

    a, b = _page("v2.1.7"), _page("v2.1.8")
    if content_hash(a, "html", COMPILED_PATTERNS) != content_hash(b, "html", COMPILED_PATTERNS):
        fails.append("FAIL an-oard-release-does-not-move-a-rules-hash: the same rule text "
                     "hashed differently across v2.1.7 and v2.1.8, which is #244 unfixed")
    without = tuple(c for c in COMPILED_PATTERNS if "colophon" not in c.pattern.decode())
    if len(without) != len(COMPILED_PATTERNS) - 1:
        fails.append(f"FAIL the-colophon-pattern-is-declared: removed "
                     f"{len(COMPILED_PATTERNS) - len(without)} patterns, wanted exactly 1 -- "
                     f"the mutation below proves nothing if it removed nothing")
    elif content_hash(a, "html", without) == content_hash(b, "html", without):
        fails.append("FAIL the-colophon-pattern-is-what-does-it: dropping it still gave "
                     "equal hashes, so this proof passes whether or not #244 is fixed")

    # THE GUARD THAT MUST NOT FIRE. Identical derivation on both sides.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        dirp = Path(d)
        _write(dirp, "case-clean", f"<html><body><p>{_BODY}</p></body></html>".encode(), _BODY)
        bad, checked = disagreements(dirp)
        if bad:
            fails.append("FAIL a-snapshot-whose-spellings-agree-produces-no-finding: "
                         f"got {bad[0][0]}")
        if checked != 1:
            fails.append(f"FAIL the-clean-case-is-actually-checked: checked {checked}, not 1")

    # A SNAPSHOT WITH NO COMMITTED .txt IS NOT A DISAGREEMENT, and is not silently counted
    # as checked either -- that would let the population this gate covers drift downwards
    # without anything saying so.
    with tempfile.TemporaryDirectory() as d:
        dirp = Path(d)
        (dirp / "case-no-txt.html").write_bytes(b"<html><body>short</body></html>")
        bad, checked = disagreements(dirp)
        if bad or checked:
            fails.append(f"FAIL a-snapshot-with-no-committed-txt-is-neither-checked-nor-a-"
                         f"finding: bad={len(bad)} checked={checked}")

    # EVERY RULE THIS MODULE DECLARES MUST HAVE BEEN WATCHED FIRING, not merely listed.
    declared = {"snapshot-identity"}
    unfired = declared - _FIRED
    if unfired:
        fails.append(f"FAIL every-declared-rule-was-watched-firing: {sorted(unfired)} "
                     f"never fired in any case")

    for f in fails:
        print(f)
    if fails:
        print(f"{len(fails)} rule(s) did not fire")
        return 1
    print(f"{len(_FIRED)} violation(s) demonstrated failing, 2 guard(s) that must not fire held")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true",
                   help="every committed snapshot: both spellings must agree (no network)")
    g.add_argument("--selftest", action="store_true",
                   help="every rule, watched failing against synthetic snapshots")
    a = ap.parse_args()
    return cmd_check() if a.check else cmd_selftest()


if __name__ == "__main__":
    raise SystemExit(main())
