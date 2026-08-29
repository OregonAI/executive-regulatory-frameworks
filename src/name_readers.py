#!/usr/bin/env python3
"""Census of every in-repo read of a registry row's `name`, and the gate that each one is
classified where it lives — plus the gate that nobody takes the compound name apart to
derive a hierarchy from it.

  python3 src/name_readers.py             # the census, by classification and by file
  python3 src/name_readers.py --check     # CI: every read carries a classification
  python3 src/name_readers.py --selftest  # CI: every rule --check enforces fires

WHY THIS EXISTS. ADR 0003 changes what `name` MEANS: it becomes the body's statutory name,
and the OAR chapter title it held moved to `oar_name`. Almost nothing about that change is
visible in the data — the two fields still hold identical bytes on 187 of the 190 rows
(#279, re-measured for #281), and differ on the three whose established statutory name is
not the rules index's title (#168) — so a consumer that should
have moved and did not keeps matching a string that quietly changed meaning, which is the
failure the sibling crosswalks exist to prevent (ADR 0003, "the risky half").

The audit that finds those consumers is a one-time reading of every site. This is what keeps
it: a read of `name` in a module that handles registry rows must say, where it sits, which
kind of reader it is. #187 read all 38 sites on `main` and classified the 33 that still
read `name` once its two joins had moved; the next one arrives in a PR nobody remembers
this ticket in.

THE THREE CLASSIFICATIONS, and what each one commits its site to:

  JOIN       the name is matched against a string some other source wrote, to decide which
             body is meant. A join must say which NAME it matches — the OAR index spells a
             body one way (`oar_name`) and its enabling statute another (`name`) — because
             after ADR 0003 those are different strings and only one of them is the one the
             other source printed.
  DISPLAY    the name is shown to a reader (or written into a generated view for one). The
             statutory name is the right thing to show, and moving these is not the point of
             the audit; saying so at the site is, because a display site and a join site are
             indistinguishable from the code alone.
  MACHINERY  the code operates on the FIELD, not on the body's identity — the refresh's
             constructor, the survival simulation, the expand script that copies `name` into
             `oar_name`. It reads whatever `name` holds and is unaffected by what that is.

ALLOWLIST, NOT BLOCKLIST (CONTEXT.md's overriding rule). A read with no marker FAILS rather
than being passed over: an unclassified read is one nobody has looked at, and "could not
check" is never reported as "is not there". The same applies to the population — a module is
scanned because it handles registry rows, and the two ways it can (loading the file, or
importing something that serves them) are both detected here rather than listed by hand.

THE COMPOUND NAME IS NOT A PATH, and that is the second gate (#174). `Department of
Agriculture, Oregon Albacore Commission` is not the body's name — ORS 576.062 calls it the
Oregon Albacore Commission — it is a PATH the OAR index built, which used to duplicate
`parent_slug` inside a string (ADR 0004). #174 retired that pointer and put the hierarchy in
`relations`, where a placement says whose reading it is, which of ADR 0004's two kinds it is
and on what authority. The compound name says none of that and is not applied consistently
(`Oregon Health Authority Equity and Inclusion Division` has a parent and no comma, alone
among the 81), so a consumer that split it back apart would be re-deriving a hierarchy the
registry deliberately stopped stating that way — silently, and from a string.

So a site in a registry module that takes a string apart on a COMMA must say what it is
doing there, from an allowlist of two words:

  NAME                 the site derives a NAME from the compound and no placement — the
                       refresh naming a chapterless parent group from the common prefix of
                       its children's chapter-page titles is the one such site.
  NOT-A-REGISTRY-NAME  the string is not a registry name at all: a comma-separated command
                       line argument, a citation list. The marker records that somebody
                       looked, which is the only thing that distinguishes it from a split
                       nobody has read.

WHAT NEITHER GATE CLAIMS. That a site's classification is CORRECT is a human judgment this
cannot check: a join wrongly marked DISPLAY reads the same to a scanner, and a hierarchy
derivation marked NAME reads the same as a name derivation. What they enforce is that every
site has been read and its reading recorded next to it, which is the state #168 needs the
repository in before it can move `name`. The compound scan is also LITERAL-ONLY: it finds a
comma in the separator the call is written with, so a split on a separator held in a variable
passes it. It is deliberately over-inclusive in the other direction — every comma-split in a
registry module, whatever it is splitting — because the cost of that is a marker on a site
that turns out to be someone else's string, and the cost of the other direction is a
hierarchy nobody knows is being derived."""
import ast
import re
import sys
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from repo_lib import REPO_ROOT

SRC = REPO_ROOT / "src"

# HOW A MODULE COMES TO HOLD REGISTRY ROWS. It reads the registry file, or it imports
# something that already does — and the second one is TRANSITIVE, which is not a refinement:
# `build_conflict_candidates_data.py` reads a body's name off a row it got from
# `enrich_oar.load_registry_by_chapter`, two hops from the file, and a population seeded
# with a hand-kept list of "the modules that read the registry" leaves it out silently. So
# the population is a fixed point over the imports, computed here, rather than a list.
REGISTRY_PATH = "_meta/catalog/agencies.yml"

# THE MARKER. One spelling, checked against an allowlist of three words — a marker whose
# word is not one of them is a site classified as something this repository does not have a
# meaning for, which is not a classification.
MARKER_RE = re.compile(r"NAME READER\s+[-–—]+\s+([A-Z][A-Z_-]*)")
CLASSIFICATIONS = ("JOIN", "DISPLAY", "MACHINERY")

# THE SECOND MARKER, spelled its own way so the two censuses cannot borrow each other's
# classifications: DISPLAY says nothing about whether a string is being taken apart, and
# NAME says nothing about who a name is shown to.
COMPOUND_MARKER_RE = re.compile(r"COMPOUND NAME\s+[-–—]+\s+([A-Z][A-Z_-]*)")
COMPOUND_PURPOSES = ("NAME", "NOT-A-REGISTRY-NAME")

# The str methods whose argument NAMES A SEPARATOR OR AN AFFIX — the ones a comma in the
# call means something by. Not all of them take the string apart (`startswith` only tests
# it), and that is deliberate: a test for the `Parent, ` prefix is a body reading the
# compound as a path just as much as a split is. An ALLOWLIST of methods rather than a
# search for the comma anywhere, because `"a, b"` in a message string is a comma nobody is
# reading, and demanding a marker on every f-string would make the gate noise instead of a
# gate.
NAMES_A_SEPARATOR = ("split", "rsplit", "partition", "rpartition", "removeprefix",
                     "removesuffix", "startswith", "endswith", "index", "find")

# Not a classification: what a site is marked with when this scan could not read its module
# at all. It fails like an unclassified read, under its own rule, because the two are
# different states — nobody classified it, versus nobody could look.
UNREADABLE = "UNREADABLE"

# How far above a read its marker may sit. The comment blocks in this codebase are long and
# one marker legitimately covers the several reads of one function; a marker further away
# than this is not "where the code is" any more, and the read is reported as unclassified —
# which is the safe direction to be wrong in.
MARKER_WINDOW = 30

# Proof code is not a consumer. A fixture that deletes `name` from a synthetic row, or
# asserts what a derived value is NOT, states something about a gate rather than about the
# registry — and requiring a classification marker on it would put the word JOIN next to
# code that joins nothing.
PROOF_FUNCTIONS = re.compile(r"^(selftest|_case_|_proof_)|fixture")

# `what` is which census the site belongs to — the two are scanned together because the
# population, the marker window and the proof-code exclusion are the same question for both,
# and answered twice they would drift.
NAME_READ = "registry-name"
COMPOUND_SPLIT = "compound-name"

Site = namedtuple("Site", "path line text function classification what")
Failure = namedtuple("Failure", "rule site detail")


def _imported_modules(tree: ast.AST) -> set:
    """Top-level module names this module imports, wherever the import sits — several of
    these modules import inside a function to keep a script's startup cheap."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
    return out


def registry_modules(sources: dict) -> set:
    """{module name} of every module that handles registry rows, transitively.

    Seeded with the modules that read the registry file and closed over imports: a module
    that imports one of them can be holding its rows. The closure OVER-includes — importing
    `catalog_agencies` for `normalize_name()` puts a module in the population without any
    row ever reaching it — and that is the direction to be wrong in: the cost is a marker on
    a `name` read that turns out to be someone else's `name`, and the cost of the other
    direction is a registry consumer nobody classified."""
    population = {m for m, src in sources.items() if REGISTRY_PATH in src}
    # A module that does not parse contributes no imports here and is reported by the scan
    # itself, under `readable-module`. Raising instead would take the whole census down over
    # one broken file and report nothing about the fifteen that are fine.
    imports = {}
    for module, src in sources.items():
        try:
            imports[module] = _imported_modules(ast.parse(src))
        except SyntaxError:
            imports[module] = set()
    changed = True
    while changed:
        changed = False
        for module, imported in imports.items():
            if module not in population and imported & population:
                population.add(module)
                changed = True
    return population


def reads_registry(tree: ast.AST, source: str, population=()) -> bool:
    """Whether this module handles registry rows."""
    return REGISTRY_PATH in source or bool(_imported_modules(tree) & set(population))


def _name_reads(tree: ast.AST):
    """Line numbers of every read of a `name` key, in either spelling.

    `row["name"]` and `row.get("name")` are the two forms this codebase writes, and both are
    found through the syntax tree rather than by matching text: `"name":` in a dict literal
    is a WRITE and reads nothing, and a regex that caught it would demand a classification
    on every dict this repository builds."""
    for node in ast.walk(tree):
        if (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
                and node.slice.value == "name"):
            yield node.lineno
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "name"):
            yield node.lineno


def _compound_splits(tree: ast.AST):
    """Line numbers of every call that takes a string apart at a separator containing a
    comma — `name.split(", ")`, `name.partition(",")`, `name.startswith("Parent,")`.

    Found through the syntax tree and not by matching text, for the reason `_name_reads` is:
    a comma inside a message string is not a split, and a gate that demanded a marker on
    every one of those would be ignored within a week."""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in NAMES_A_SEPARATOR):
            continue
        if any(isinstance(a, ast.Constant) and isinstance(a.value, str) and "," in a.value
               for a in node.args):
            yield node.lineno


def _enclosing_functions(tree: ast.AST) -> dict:
    """{line: innermost function name} for every line inside a function body."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                out[line] = node.name
    return out


def scan_source(path: str, source: str, population=()) -> list:
    """Every registry-name read AND every compound-name split in one module, with the
    classification marking it (or None).

    Returns [] for a module that does not handle registry rows — `area["name"]` in a script
    that never sees the registry is not a site this audit is about.

    `population` is the set of module names already known to serve registry rows, which is
    `registry_modules()`'s answer over the whole of src/. It defaults to EMPTY rather than to
    a seed list of "the modules that read the registry": a default naming
    `catalog_agencies` here would be exactly the hand-kept list this module refuses to keep,
    living where nobody would look for it. With no population passed, a module qualifies
    only by reading the registry file itself.

    A module that does not PARSE is reported as one unreadable site rather than skipped or
    crashed on. It is a module this audit could not read, and "could not check" is never
    reported as "is not there" (CONTEXT.md)."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [Site(path, e.lineno or 0, f"module does not parse: {e.msg}", None,
                     UNREADABLE, NAME_READ)]
    if not reads_registry(tree, source, population):
        return []
    lines = source.splitlines()
    functions = _enclosing_functions(tree)

    def markers_of(pattern):
        found = {}
        for i, line in enumerate(lines, 1):
            m = pattern.search(line)
            if m:
                found[i] = m.group(1)
        return found

    sites = []
    for what, found, markers in ((NAME_READ, _name_reads(tree), markers_of(MARKER_RE)),
                                 (COMPOUND_SPLIT, _compound_splits(tree),
                                  markers_of(COMPOUND_MARKER_RE))):
        for line in sorted(set(found)):
            function = functions.get(line)
            if function and PROOF_FUNCTIONS.search(function):
                continue
            near = [n for n in markers if line - MARKER_WINDOW <= n <= line]
            sites.append(Site(path, line, lines[line - 1].strip(), function,
                              markers[max(near)] if near else None, what))
    return sites


def _label(path) -> str:
    """How a site names its file: repository-relative where it can be, absolute where it
    cannot — `census()` takes the paths as a parameter so a census can be run over a tree
    that is not this checkout, which is how the before/after of a migration like #187 gets
    measured."""
    try:
        return str(Path(path).relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def census(paths=None) -> list:
    """Every registry-name read in src/, in file and line order."""
    paths = sorted(paths if paths is not None else SRC.glob("*.py"))
    sources = {Path(p).stem: Path(p).read_text() for p in paths}
    population = registry_modules(sources)
    sites = []
    for p in paths:
        sites += scan_source(_label(p), sources[Path(p).stem], population)
    return sites


def check_sites(sites) -> list:
    """Every way the census violates the classification contract, as Failures."""
    failures = []
    for s in sites:
        if s.classification == UNREADABLE:
            failures.append(Failure(
                "readable-module", f"{s.path}:{s.line}",
                f"{s.text} — no registry-name read or compound-name split in it could be "
                "evaluated, which is not the same as its having none"))
        elif s.what == COMPOUND_SPLIT:
            if s.classification not in COMPOUND_PURPOSES:
                failures.append(Failure(
                    "compound-name-is-not-a-path", f"{s.path}:{s.line}",
                    f"takes a string apart on a comma with "
                    + ("no `COMPOUND NAME` marker" if s.classification is None
                       else f"purpose {s.classification!r}, which is not one of "
                            f"{', '.join(COMPOUND_PURPOSES)}")
                    + f" within {MARKER_WINDOW} lines above it: {s.text[:70]!r}. "
                    "`Parent, Child` is a path the OAR index built, and hierarchy lives in "
                    "`relations` since #174 — mark it "
                    f"`COMPOUND NAME — {'|'.join(COMPOUND_PURPOSES)}` and say why it is not "
                    "a placement being derived from a string"))
        elif s.classification is None:
            failures.append(Failure(
                "registry-name-classified", f"{s.path}:{s.line}",
                f"reads a registry `name` with no classification within {MARKER_WINDOW} "
                f"lines above it: {s.text[:70]!r}. Mark it "
                f"`NAME READER — {'|'.join(CLASSIFICATIONS)}` and say why"))
        elif s.classification not in CLASSIFICATIONS:
            failures.append(Failure(
                "known-classification", f"{s.path}:{s.line}",
                f"classified {s.classification!r}, which is not one of "
                f"{', '.join(CLASSIFICATIONS)}"))
    return failures


def cmd_check() -> int:
    sites = census()
    failures = check_sites(sites)
    for f in failures:
        print(f"  FAIL [{f.rule}] {f.site}: {f.detail}", file=sys.stderr)
    if failures:
        print(f"\n{len(failures)} unclassified site(s) out of {len(sites)}",
              file=sys.stderr)
        return 1
    reads = [s for s in sites if s.what == NAME_READ]
    splits = [s for s in sites if s.what == COMPOUND_SPLIT]
    print(f"{len(reads)} registry-name read(s) across "
          f"{len({s.path for s in reads})} module(s), every one classified: "
          + ", ".join(f"{c.lower()} {sum(1 for s in reads if s.classification == c)}"
                      for c in CLASSIFICATIONS))
    print(f"{len(splits)} compound-name split(s), every one classified: "
          + ", ".join(f"{c.lower()} {sum(1 for s in splits if s.classification == c)}"
                      for c in COMPOUND_PURPOSES)
          + " — nothing derives hierarchy from the `Parent, Child` name")
    return 0


def cmd_census() -> int:
    sites = census()
    for path in sorted({s.path for s in sites}):
        print(path)
        for s in sorted((x for x in sites if x.path == path), key=lambda x: x.line):
            print(f"  {s.line:>5}  {s.what:<14} "
                  f"{str(s.classification or 'UNCLASSIFIED'):<20} {s.text[:60]}")
    print(f"\n{len(sites)} site(s) across {len({s.path for s in sites})} module(s)")
    # TALLIED PER CENSUS, because the two have different allowlists and an unclassified read
    # is not the same finding as an unclassified split — one total covering both would name
    # neither.
    for what, allowed in ((NAME_READ, CLASSIFICATIONS), (COMPOUND_SPLIT, COMPOUND_PURPOSES)):
        of_this_kind = [s for s in sites if s.what == what]
        print(f"  {what} ({len(of_this_kind)})")
        for c in allowed + (None,):
            n = sum(1 for s in of_this_kind if s.classification == c)
            print(f"    {str(c or 'UNCLASSIFIED').lower():<22} {n}")
    return 0


# ------------------------------------------------------------------------------ selftest
#
# THE PROOF THAT THE GATE ABOVE CAN FAIL, on synthetic modules written to break exactly one
# rule each. A guard nobody has watched fire is not known to fire, and this one guards
# against an absence — the site that nobody classified — which is the kind that looks
# identical to a clean run.

_CLEAN = '''
CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"


def titles(orgs):
    # NAME READER - DISPLAY: shown to a reader beside the slug.
    return {o["slug"]: o["name"] for o in orgs}
'''

_UNCLASSIFIED = '''
CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"


def titles(orgs):
    return {o["slug"]: o["name"] for o in orgs}
'''

_UNCLASSIFIED_GET_FORM = '''
CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"


def titles(orgs):
    return {o["slug"]: o.get("name", o["slug"]) for o in orgs}
'''

_INVENTED_CLASSIFICATION = '''
CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"


def titles(orgs):
    # NAME READER - PROBABLY_FINE
    return {o["slug"]: o["name"] for o in orgs}
'''

_MARKER_TOO_FAR_AWAY = '''
CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"

# NAME READER - DISPLAY
''' + "\n" * (MARKER_WINDOW + 2) + '''

def titles(orgs):
    return {o["slug"]: o["name"] for o in orgs}
'''

_IMPORTS_THE_REGISTRY_MODULE = '''
import catalog_agencies


def titles():
    return {o["slug"]: o["name"] for o in catalog_agencies.load()["organizations"]}
'''

_NOT_A_REGISTRY_MODULE = '''
def areas(priorities):
    return {a["id"]: a["name"] for a in priorities}
'''

_WRITES_A_NAME_KEY = '''
CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"


def row(slug, title):
    return {"slug": slug, "name": title}
'''

_DOES_NOT_PARSE = '''
CATALOG = ROOT / "_meta/catalog/agencies.yml"

def titles(orgs)
    return {o["slug"]: o["name"] for o in orgs}
'''

_DERIVES_HIERARCHY_FROM_THE_COMPOUND_NAME = '''
CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"


def parent_of(org):
    # NAME READER - MACHINERY: reads the field, not the body's identity.
    return slugify(org["name"].split(", ")[0])
'''

_COMPOUND_SPLIT_WITH_AN_INVENTED_PURPOSE = '''
CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"


def parent_of(org):
    # COMPOUND NAME - PROBABLY_FINE
    return slugify(org["name"].split(", ")[0])
'''

_COMPOUND_SPLIT_CLASSIFIED = '''
CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"


def own_name(org):
    # NAME READER - DISPLAY: shown to a reader beside the slug.
    # COMPOUND NAME - NAME: the tail segment is the body's own name; no placement is
    # derived here.
    return org["name"].rsplit(", ", 1)[-1]
'''

_A_COMMA_IN_A_MESSAGE_IS_NOT_A_SPLIT = '''
CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"


def report(rows):
    return f"{len(rows)} rows, every one checked"
'''

_NAME_MARKER_IS_NOT_A_COMPOUND_MARKER = '''
CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"


def parent_of(org):
    # NAME READER - DISPLAY: shown to a reader beside the slug.
    return org["name"].split(", ")[0]
'''

_PROOF_CODE = '''
CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"


def _case_missing_name(cat):
    del cat["organizations"][0]["name"]
'''

# (name, source, the rule it must break — or None for a source that must come out clean —
# and, where the module qualifies only through an import, the population it is scanned
# against; `registry_modules()` computes that set for real, and its own proof is below)
_CASES = [
    ("clean-module", _CLEAN, None),
    ("unclassified-read", _UNCLASSIFIED, "registry-name-classified"),
    ("unclassified-get-form", _UNCLASSIFIED_GET_FORM, "registry-name-classified"),
    ("invented-classification", _INVENTED_CLASSIFICATION, "known-classification"),
    ("marker-too-far-away", _MARKER_TOO_FAR_AWAY, "registry-name-classified"),
    ("read-through-an-imported-registry-module", _IMPORTS_THE_REGISTRY_MODULE,
     "registry-name-classified", {"catalog_agencies"}),
    ("module-that-never-sees-the-registry", _NOT_A_REGISTRY_MODULE, None),
    ("writing-a-name-key-reads-nothing", _WRITES_A_NAME_KEY, None),
    ("proof-code-is-not-a-consumer", _PROOF_CODE, None),
    ("module-that-does-not-parse", _DOES_NOT_PARSE, "readable-module"),
    # THE COMPOUND NAME IS NOT A PATH (#174). The first case is the failure itself — a
    # module deriving a body's parent by splitting `Parent, Child` — and it is the one this
    # gate exists for: it passes every other rule here, because the read IS classified and
    # the classification is a true statement about the read.
    ("derives-hierarchy-from-the-compound-name",
     _DERIVES_HIERARCHY_FROM_THE_COMPOUND_NAME, "compound-name-is-not-a-path"),
    ("compound-split-with-an-invented-purpose",
     _COMPOUND_SPLIT_WITH_AN_INVENTED_PURPOSE, "compound-name-is-not-a-path"),
    # AND THE TWO MARKERS ARE NOT INTERCHANGEABLE: a site marked only as a name READER has
    # said who the name is shown to and nothing about taking it apart.
    ("a-name-marker-does-not-classify-a-compound-split",
     _NAME_MARKER_IS_NOT_A_COMPOUND_MARKER, "compound-name-is-not-a-path"),
    ("compound-split-classified", _COMPOUND_SPLIT_CLASSIFIED, None),
    ("a-comma-in-a-message-is-not-a-split", _A_COMMA_IN_A_MESSAGE_IS_NOT_A_SPLIT, None),
]


def _proof_the_population_is_transitive() -> int:
    """A module two hops from the registry is still a registry consumer. This is the real
    shape of `build_conflict_candidates_data` -> `enrich_oar` -> the file, and it is the
    case a seeded list of registry modules gets wrong."""
    sources = {
        "reads_the_file": f'CATALOG = ROOT / "{REGISTRY_PATH}"',
        "one_hop": "import reads_the_file",
        "two_hops": "from one_hop import rows",
        "unrelated": "import json",
    }
    got = registry_modules(sources)
    if got != {"reads_the_file", "one_hop", "two_hops"}:
        print(f"FAIL population-is-transitive: {sorted(got)}", file=sys.stderr)
        return 1
    return 0


def selftest() -> int:
    bad = _proof_the_population_is_transitive()
    for name, source, rule, *population in _CASES:
        failures = check_sites(scan_source(f"<{name}>", source, *population))
        if rule is None:
            if failures:
                print(f"FAIL {name}: expected no failure, got {failures}", file=sys.stderr)
                bad += 1
        elif not any(f.rule == rule for f in failures):
            print(f"FAIL {name}: expected a [{rule}] failure, got {failures}",
                  file=sys.stderr)
            bad += 1
    print(f"{sum(1 for c in _CASES if c[2])} violation(s) demonstrated failing across "
          f"{len({c[2] for c in _CASES if c[2]})} rule(s), "
          f"{sum(1 for c in _CASES if not c[2])} clean module(s) left alone, "
          "population closed over imports"
          if not bad else f"{bad} case(s) did not behave")
    return 1 if bad else 0


def main() -> int:
    if "--check" in sys.argv:
        return cmd_check()
    if "--selftest" in sys.argv:
        return selftest()
    return cmd_census()


if __name__ == "__main__":
    raise SystemExit(main())
