#!/usr/bin/env python3
"""Census of every in-repo read of a registry row's `name`, and the gate that each one is
classified where it lives.

  python3 src/name_readers.py             # the census, by classification and by file
  python3 src/name_readers.py --check     # CI: every read carries a classification
  python3 src/name_readers.py --selftest  # CI: every rule --check enforces fires

WHY THIS EXISTS. ADR 0003 changes what `name` MEANS: it becomes the body's statutory name,
and the OAR chapter title it holds today moves to `oar_name`. Nothing about that change is
visible in the data — the two fields hold identical bytes on all 189 rows — so a consumer
that should have moved and did not keeps matching a string that quietly changed meaning,
which is the failure the sibling crosswalks exist to prevent (ADR 0003, "the risky half").

The audit that finds those consumers is a one-time reading of every site. This is what keeps
it: a read of `name` in a module that handles registry rows must say, where it sits, which
kind of reader it is. #187 classified 33 of them; the next one arrives in a PR nobody
remembers this ticket in.

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

WHAT IT DOES NOT CLAIM. That a site's classification is CORRECT is a human judgment this
cannot check: a join wrongly marked DISPLAY reads the same to a scanner. What it enforces is
that every site has been read and its reading recorded next to it, which is the state #168
needs the repository in before it can move `name`."""
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

Site = namedtuple("Site", "path line text function classification")
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
    imports = {m: _imported_modules(ast.parse(src)) for m, src in sources.items()}
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


def _enclosing_functions(tree: ast.AST) -> dict:
    """{line: innermost function name} for every line inside a function body."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                out[line] = node.name
    return out


def scan_source(path: str, source: str, population=("catalog_agencies", "agency_profile")) -> list:
    """Every registry-name read in one module, with the classification marking it (or None).

    Returns [] for a module that does not handle registry rows — `area["name"]` in a script
    that never sees the registry is not a site this audit is about."""
    tree = ast.parse(source)
    if not reads_registry(tree, source, population):
        return []
    lines = source.splitlines()
    functions = _enclosing_functions(tree)
    markers = {}
    for i, line in enumerate(lines, 1):
        m = MARKER_RE.search(line)
        if m:
            markers[i] = m.group(1)

    sites = []
    for line in sorted(set(_name_reads(tree))):
        function = functions.get(line)
        if function and PROOF_FUNCTIONS.search(function):
            continue
        near = [n for n in markers if line - MARKER_WINDOW <= n <= line]
        sites.append(Site(path, line, lines[line - 1].strip(), function,
                          markers[max(near)] if near else None))
    return sites


def _label(path) -> str:
    """How a site names its file. Repository-relative where it can be — `paths` is a
    parameter so a census can be run over a tree that is not this checkout, which is how
    the before/after of a migration like #187 gets measured."""
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
        if s.classification is None:
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
        print(f"\n{len(failures)} unclassified registry-name read(s) across "
              f"{len(sites)} site(s)", file=sys.stderr)
        return 1
    print(f"{len(sites)} registry-name read(s) across "
          f"{len({s.path for s in sites})} module(s), every one classified: "
          + ", ".join(f"{c.lower()} {sum(1 for s in sites if s.classification == c)}"
                      for c in CLASSIFICATIONS))
    return 0


def cmd_census() -> int:
    sites = census()
    for path in sorted({s.path for s in sites}):
        print(path)
        for s in (x for x in sites if x.path == path):
            print(f"  {s.line:>5}  {str(s.classification or 'UNCLASSIFIED'):<12} {s.text[:80]}")
    print(f"\n{len(sites)} site(s) across {len({s.path for s in sites})} module(s)")
    for c in CLASSIFICATIONS + (None,):
        n = sum(1 for s in sites if s.classification == c)
        print(f"  {str(c or 'UNCLASSIFIED').lower():<13} {n}")
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

_PROOF_CODE = '''
CATALOG = REPO_ROOT / "_meta/catalog/agencies.yml"


def _case_missing_name(cat):
    del cat["organizations"][0]["name"]
'''

# (name, source, the rule it must break — or None for a source that must come out clean)
_CASES = [
    ("clean-module", _CLEAN, None),
    ("unclassified-read", _UNCLASSIFIED, "registry-name-classified"),
    ("unclassified-get-form", _UNCLASSIFIED_GET_FORM, "registry-name-classified"),
    ("invented-classification", _INVENTED_CLASSIFICATION, "known-classification"),
    ("marker-too-far-away", _MARKER_TOO_FAR_AWAY, "registry-name-classified"),
    ("read-through-an-imported-registry-module", _IMPORTS_THE_REGISTRY_MODULE,
     "registry-name-classified"),
    ("module-that-never-sees-the-registry", _NOT_A_REGISTRY_MODULE, None),
    ("writing-a-name-key-reads-nothing", _WRITES_A_NAME_KEY, None),
    ("proof-code-is-not-a-consumer", _PROOF_CODE, None),
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
    for name, source, rule in _CASES:
        failures = check_sites(scan_source(f"<{name}>", source))
        if rule is None:
            if failures:
                print(f"FAIL {name}: expected no failure, got {failures}", file=sys.stderr)
                bad += 1
        elif not any(f.rule == rule for f in failures):
            print(f"FAIL {name}: expected a [{rule}] failure, got {failures}",
                  file=sys.stderr)
            bad += 1
    print(f"{sum(1 for _, _, r in _CASES if r)} violation(s) demonstrated failing, "
          f"{sum(1 for _, _, r in _CASES if not r)} clean module(s) left alone, "
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
