#!/usr/bin/env python3
"""AST-of-own-source machinery for "does this module's PRODUCTION code actually assign this
dict key" -- read off a writer module's syntax tree rather than trusted, the shape
`ingest_status.ingest_vocabulary()` established for one field (`status`) and `catalog_oar.py`
(#339) widens to every field a row-shaped dict can carry. Its own module, not a fourth writer
module's private helpers: `check_rule_ledger.py`'s docstring names the failure mode this
extraction avoids -- shared scaffolding copied by hand drifts, one copy at a time, and this
scan is general-purpose Python source analysis with nothing OAR-specific about it.

  python3 src/write_site_scan.py             # print what this module owns
  python3 src/write_site_scan.py --selftest  # CI: every shape this scan recognizes, proven

THE FIVE WRITE SHAPES A CALLER'S DECLARED KEYS ARE GATED AGAINST:

  1. a literal-key subscript assignment      r["path"] = ...
  2. a dict literal                          {"number": num, "status": "not_ingested"}
  3. a `for key, value in zip(KEYS, ...): row[key] = value` loop, where KEYS is a
     module-level tuple of key-constants -- the shape a multi-key group is often written
     through in one place
  4. `r.setdefault("path", ...)`
  5. `r.update(path=..., status=...)` (keyword form) or `r.update({"path": ...})` (a
     positional dict-literal argument -- reaches the scan through shape 2, since every
     `ast.Dict` anywhere in production code is walked, call arguments included)

NARROW ON PURPOSE, the same way `ingest_status.ingest_vocabulary()` names the shapes it does
not chase rather than pretending to be a general Python analyzer: only module-level constants
are resolved, and only a 2-tuple `for key, value in zip(...)` loop is unrolled. A write shape
outside these five is invisible to this scan the same way an unparseable module is -- a
caller's gate must report that as "declared writer nothing was observed", never as "declared
writer confirmed absent", because a scan that cannot see a write must not conclude the write
does not happen (AGENTS.md's overriding rule).

WHAT ELSE THIS SCAN NARROWS, NAMED RATHER THAN LEFT IMPLICIT (#339 review response):

  - IT ONLY EVER READS THE SOURCE FILES A CALLER HANDS IT. A field written by some module
    this scan was never pointed at is invisible to it -- not reported as "writer confirmed
    absent" (this scan makes no claim about a file it never read), but a caller who only ever
    hands it a fixed list of writer modules gets no signal AT ALL the day a new module starts
    writing the same key. `catalog_oar.WRITER_MODULE_PATHS` names this narrowing explicitly
    where it applies the fixed list; widening the set of files scanned is that caller's
    decision, not this module's.
  - ANY DICT LITERAL OR SUBSCRIPT ASSIGNMENT IN PRODUCTION CODE IS READ AS A KEY WRITE, not
    only ones that plausibly hold a ROW. A dict built for some unrelated purpose --
    `{"User-Agent": ..., "sha256": ...}`, a log line, an HTTP-request kwarg dict -- that
    happens to use one of a caller's declared field NAMES as a key ({"note": "..."} for a
    reason with nothing to do with a catalog row) is indistinguishable from a real row write
    to this scan. THIS IS A KNOWN, LIVE FALSE-POSITIVE MODE, not a hypothetical: measured
    against the real four OAR writer modules at #339's own review, this scan's unconstrained
    predecessor found 51 keys, 39 of which are not `catalog_oar.FIELDS` row fields at all
    ('User-Agent', 'sha256', 'total', 'retrieved', 'sources', ...). Today it agrees with
    `FIELDS` only because none of the twelve declared field names happens to be reused as an
    unrelated dict key in the four files this is pointed at; a caller with a sparser
    vocabulary, or a fifth file added to the scan, could see this fire on an unrelated dict.
    A stricter version was tried -- attribute a write only through an object already proven
    to carry a row-identifying key (`number`) -- and reverted: `ingest_oar.py`,
    `reingest_oar.py` and `legal_status.py` all mutate a row `number` is set in ELSEWHERE
    (discovery, once, never rewritten -- `catalog_oar.FIELDS`'s own comment on `number`), so
    that constraint made every one of their real writes as invisible as the false positive it
    was meant to catch. Left unconstrained on purpose, then: a caller whose declared
    vocabulary a write site's key happens to collide with is the diagnosis for a spurious
    `writer-observed-not-declared`, not a scan bug -- this paragraph is that diagnosis,
    written down so the next such failure is found here first.
"""
import argparse
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from repo_lib import REPO_ROOT, Checks

SRC = REPO_ROOT / "src"


def module_key_constants(tree: ast.Module) -> tuple:
    """(name -> str, name -> tuple-of-str) for every simple MODULE-LEVEL assignment a write
    site's key might resolve through -- `ACTION_KEY = "reingest_action"`, then
    `REINGEST_KEYS = (ACTION_KEY, NOTICE_KEY)` built from names already resolved earlier in
    the same file (source order, matching how these modules actually declare them). A
    constant assigned inside a function is outside this scan's declared narrowing above."""
    strings: dict = {}
    tuples: dict = {}

    def resolve_str(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return strings.get(node.id)
        return None

    for stmt in tree.body:
        if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)):
            continue
        name = stmt.targets[0].id
        s = resolve_str(stmt.value)
        if s is not None:
            strings[name] = s
            continue
        if isinstance(stmt.value, (ast.Tuple, ast.List)):
            elts = [resolve_str(e) for e in stmt.value.elts]
            if elts and all(e is not None for e in elts):
                tuples[name] = tuple(elts)
    return strings, tuples


def externally_referenced_names(module_stem: str, other_sources: dict, trees: dict = None) -> set:
    """Every top-level name of the module named `module_stem` that some OTHER source in
    `other_sources` (label/path -> text, any OTHER module -- not `module_stem`'s own tree)
    imports by name (`from module_stem import name`) or reaches as an attribute after a bare
    `import module_stem` (`module_stem.name(...)`, or `import module_stem as m` then
    `m.name(...)`).

    THE GAP THIS CLOSES (#339 review): a top-level function's own call graph, walked from
    `selftest`/`cmd_selftest` alone, cannot tell a real production function apart from a test
    fixture when the function's ONLY named caller inside its own module happens to be
    `selftest` -- true of a function every OTHER module imports and calls, same as a function
    truly reachable only from a test. `legal_status.resolve` (imported by `ingest_oar.py`,
    `enrich_oar.py`) and `catalog_oar.display_note` (imported by `review_queue.py`) are both
    this shape on the real committed tree. A name returned here must never be excluded from
    a production scan as test-only, no matter how it looks from inside its own module --
    some OTHER writer may call it in production, and that is enough.

    `trees`, when given, maps the same keys as `other_sources` to already-parsed ASTs -- an
    optional cache so a caller calling this once PER TARGET module over the same
    `other_sources` does not re-`ast.parse` each source once per call. A key `trees` does not
    carry falls back to parsing `other_sources`' text for that key, so a partial cache is
    safe. A caller doing that for EVERY module in a corpus (module count N -> N calls here,
    each walking N-1 trees: O(N^2) `ast.walk()`, which is the greater part of this
    function's cost -- #394 review measured `ast.parse` at 0.2s of a 15-16s run,
    `ast.walk` at the rest) should call `all_externally_referenced_names()` below instead,
    which walks each tree exactly once."""
    referenced = set()
    for key, text in other_sources.items():
        tree = trees.get(key) if trees is not None else None
        if tree is None:
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
        referenced |= _file_import_references(tree).get(module_stem, set())
    return referenced


def _file_import_references(tree: ast.Module) -> dict:
    """One pass over `tree`: {imported module_stem: names referenced from it in this file}
    -- every `from module_stem import name` and every `module_stem.name(...)` /
    `import module_stem as m; m.name(...)` reachable in `tree`, for every `module_stem` at
    once. The per-file half of `externally_referenced_names`'s cross-module lookup, split
    out so a caller aggregating over every file in a corpus walks each tree once (see
    `all_externally_referenced_names`) instead of once per (target module, file) pair."""
    referenced: dict = {}
    bound_aliases: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            referenced.setdefault(node.module, set()).update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            for a in node.names:
                bound_aliases[a.asname or a.name] = a.name
    if bound_aliases:
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id in bound_aliases):
                referenced.setdefault(bound_aliases[node.value.id], set()).add(node.attr)
    return referenced


def all_externally_referenced_names(trees: dict) -> dict:
    """{key: externally-referenced names for the module at `key`} for EVERY key in `trees`
    (a `pathlib.Path` whose `.stem` is that module's name -> its already-parsed AST),
    computed by walking each tree in `trees` exactly once and aggregating by imported
    module stem -- the batch form of calling
    `externally_referenced_names(key.stem, {other keys' sources}, trees=trees)` once per
    key, which walks every OTHER tree again for each key (O(N^2) `ast.walk()` calls over a
    corpus of N files; this is O(N)). A caller keying by a plain label string rather than a
    `Path` (a synthetic fixture, most callers' `sources=...` path) has no `.stem` to
    aggregate by and should call `externally_referenced_names` directly instead."""
    contrib = {key: _file_import_references(tree) for key, tree in trees.items()}
    agg: dict = {}
    for referenced in contrib.values():
        for stem, names in referenced.items():
            agg.setdefault(stem, set()).update(names)
    return {key: set(agg.get(key.stem, set())) - contrib[key].get(key.stem, set())
            for key in trees}


def test_only_function_names(tree: ast.Module, externally_referenced: frozenset = frozenset()) -> set:
    """Every TOP-LEVEL function this module defines that exists only to test it -- computed
    from the module's own call graph rather than guessed from a naming convention. A naming
    guess (`_proof_*`/`_fixture*`) was tried first and missed real cases: a fixture helper
    with neither prefix can build a dict literal AST-identical to a real row write.

    `selftest`/`cmd_selftest` (the entry point every writer module exposes) seeds the set; a
    function is added once EVERY place it is called (by name, anywhere in the module) is
    already in the set -- to a fixed point, since a fixture builder often calls another
    fixture builder. A name in `externally_referenced` is NEVER added, however this module's
    OWN call graph would classify it -- see `externally_referenced_names()`'s docstring for
    why a module-local reachability walk alone misses exactly this case.

    A function this misses in some OTHER way (called only indirectly, e.g. through a list of
    function references rather than by name or import) is simply not excluded, which biases
    this scan toward over-reporting a field as written, never toward silently excusing a real
    write -- could not check is never reported as is not there."""
    defs = {n.name: n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    entry = ({"selftest", "cmd_selftest"} & set(defs)) - set(externally_referenced)
    if not entry:
        return set()
    calls = {name: {c.func.id for c in ast.walk(node)
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
             for name, node in defs.items()}
    test_only = set(entry)
    changed = True
    while changed:
        changed = False
        for name in defs:
            if name in test_only or name in externally_referenced:
                continue
            callers = [c for c, callees in calls.items() if name in callees]
            if callers and all(c in test_only for c in callers):
                test_only.add(name)
                changed = True
    return test_only


def walk_production(tree: ast.Module, exclude_names: frozenset = frozenset(),
                    externally_referenced: frozenset = frozenset()):
    """`ast.walk(tree)`, except it never descends into a top-level function
    `test_only_function_names` finds, and never descends into a top-level assignment whose
    target name is in `exclude_names` -- a caller's OWN schema declaration
    (`catalog_oar.FIELDS` is the one example on the real tree: a dict literal whose keys are
    exactly the row keys this scan looks for, structurally identical to a real
    row-construction dict, and the one write site every field's declared writers would
    otherwise be attributed to no matter what actually writes it). Excluding the WHOLE
    subtree for a test-only function (not just the def itself) is what keeps a nested
    fixture -- a helper defined INSIDE `selftest()` -- from being reached at all."""
    test_only = test_only_function_names(tree, externally_referenced)
    stack = list(tree.body)
    while stack:
        node = stack.pop()
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in test_only):
            continue
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in exclude_names):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def assigned_keys(tree: ast.Module, exclude_names: frozenset = frozenset(),
                  externally_referenced: frozenset = frozenset()) -> set:
    """Every dict key this module's syntax tree assigns, IN ITS OWN PRODUCTION CODE -- the
    five shapes named in this module's docstring, resolved through `module_key_constants`'s
    maps, walked via `walk_production` so a test fixture is never read as a write. See this
    module's docstring for the known false-positive mode this does NOT guard against (an
    unrelated dict reusing a declared field's name as a key)."""
    strings, tuples = module_key_constants(tree)

    def resolve_str(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return strings.get(node.id)
        return None

    def resolve_tuple(node):
        if isinstance(node, ast.Name):
            return tuples.get(node.id)
        if isinstance(node, (ast.Tuple, ast.List)):
            elts = [resolve_str(e) for e in node.elts]
            if elts and all(e is not None for e in elts):
                return tuple(elts)
        return None

    out = set()
    for node in walk_production(tree, exclude_names, externally_referenced):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Subscript):
                    key = resolve_str(t.slice)
                    if key is not None:
                        out.add(key)
        elif isinstance(node, ast.Dict):
            for k in node.keys:
                key = resolve_str(k) if k is not None else None
                if key is not None:
                    out.add(key)
        elif isinstance(node, ast.For):
            target = node.target
            if not (isinstance(target, ast.Tuple) and len(target.elts) == 2
                    and all(isinstance(e, ast.Name) for e in target.elts)
                    and isinstance(node.iter, ast.Call)
                    and isinstance(node.iter.func, ast.Name)
                    and node.iter.func.id == "zip" and node.iter.args):
                continue
            keys_tuple = resolve_tuple(node.iter.args[0])
            key_var = target.elts[0].id
            if keys_tuple and any(
                    isinstance(inner, ast.Assign)
                    and any(isinstance(tg, ast.Subscript)
                           and isinstance(tg.slice, ast.Name) and tg.slice.id == key_var
                           for tg in inner.targets)
                    for inner in ast.walk(node)):
                out.update(keys_tuple)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr == "setdefault" and node.args):
            key = resolve_str(node.args[0])
            if key is not None:
                out.add(key)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr == "update" and node.keywords):
            out.update(kw.arg for kw in node.keywords if kw.arg is not None)
            # A positional `.update({"key": val})` dict-literal argument needs no separate
            # case here: that literal is itself an `ast.Dict` node, a child of this Call,
            # already reached and read by the generic dict-literal branch above.
    return out


# ------------------------------------------------------------------------------ selftest


def _proof_key_constants_resolve_chained_names(check) -> None:
    src = ('A_KEY = "field_a"\nB_KEY = "field_b"\nGROUP = (A_KEY, B_KEY)\n')
    strings, tuples = module_key_constants(ast.parse(src))
    check("a module-level string constant resolves", strings.get("A_KEY") == "field_a")
    check("a module-level tuple built from earlier constants resolves",
          tuples.get("GROUP") == ("field_a", "field_b"))


def _proof_test_only_exclusion(check) -> None:
    src = ('def _oddly_named_helper(number):\n'
          '    r = {"number": number}\n'
          '    return r\n'
          'def selftest():\n'
          '    _oddly_named_helper("1")\n')
    tree = ast.parse(src)
    check("a fixture helper reachable only from selftest is excluded however it is named",
          "number" not in assigned_keys(tree))
    real_and_test = ('def build(number):\n'
                     '    return {"number": number, "status": "ok"}\n'
                     'def cmd_run():\n'
                     '    return build("1")\n'
                     'def selftest():\n'
                     '    build("1")\n')
    check("...but the SAME helper is scanned when a real command path also reaches it",
          assigned_keys(ast.parse(real_and_test)) == {"number", "status"})


def _proof_externally_referenced_names_close_the_module_local_blind_spot(check) -> None:
    """THE CONCRETE FINDING (#339 review): a helper reachable, inside its OWN module, only
    from `selftest` -- but imported and called by some OTHER module under src/ -- is real
    production code, and a module-local call-graph walk alone cannot tell it apart from a
    true fixture. Reproduced end to end: the same source, scanned in isolation versus scanned
    with an importing module in view, must disagree."""
    writer_src = ('def _oddly_named_helper(number):\n'
                 '    r = {"number": number}\n'
                 '    r["served_as"] = number\n'
                 '    return r\n'
                 'def selftest():\n'
                 '    _oddly_named_helper("1")\n')
    tree = ast.parse(writer_src)
    check("RED: in isolation (no other module in view), the helper is excluded and its "
          "write is invisible -- the defect this proof exists to catch",
          assigned_keys(tree) == set())
    importer_src = 'from a_writer_module import _oddly_named_helper\n'
    ext_ref = externally_referenced_names(
        "a_writer_module", {"importer": importer_src})
    check("externally_referenced_names sees the import by name",
          ext_ref == {"_oddly_named_helper"})
    check("GREEN: told about the importing module, the same source's write is scanned",
          assigned_keys(tree, externally_referenced=ext_ref) == {"number", "served_as"})
    attr_importer_src = ('import a_writer_module\n'
                        'def use():\n'
                        '    return a_writer_module._oddly_named_helper("1")\n')
    check("...and the same holds for a bare `import module` + attribute-access call, not "
          "only `from module import name`",
          externally_referenced_names("a_writer_module", {"importer": attr_importer_src})
          == {"_oddly_named_helper"})


def _proof_all_externally_referenced_names_matches_the_per_module_form(check) -> None:
    """`all_externally_referenced_names` (#394 review: the O(N^2)-`ast.walk()` fix for a
    caller computing this for EVERY module in a corpus) batches what calling
    `externally_referenced_names` once per target module, over the same sources, computes --
    proven to agree with it here so the two can't silently drift apart. Also proves the
    `trees=` cache parameter agrees with parsing fresh."""
    a_src = 'from b_writer import _helper\n'
    b_src = ('def _helper(number):\n'
            '    r = {"number": number}\n'
            '    r["served_as"] = number\n'
            '    return r\n')
    c_src = 'x = 1\n'  # imports nothing -- contributes no references either way
    sources = {Path("a_writer.py"): a_src, Path("b_writer.py"): b_src, Path("c.py"): c_src}
    trees = {p: ast.parse(t) for p, t in sources.items()}
    batch = all_externally_referenced_names(trees)
    check("the batch form finds b_writer's helper referenced by a_writer",
          batch[Path("b_writer.py")] == {"_helper"})
    check("...and a module nothing imports has no external references",
          batch[Path("a_writer.py")] == set() and batch[Path("c.py")] == set())
    other = {p: t for p, t in sources.items() if p != Path("b_writer.py")}
    per_target = externally_referenced_names("b_writer", other)
    check("...agreeing with the per-target form given the same sources",
          batch[Path("b_writer.py")] == per_target)
    check("the trees= cache agrees with parsing fresh",
          externally_referenced_names("b_writer", other,
                                      trees={p: trees[p] for p in other}) == per_target)


def _proof_setdefault_and_update_shapes(check) -> None:
    src = ('def build(number):\n'
          '    r = {"number": number}\n'
          '    r.setdefault("path", "x")\n'
          '    r.update(status="ingested", note="n")\n'
          '    return r\n')
    check("`r.setdefault(key, ...)` is recognized",
          "path" in assigned_keys(ast.parse(src)))
    check("`r.update(key=value, ...)` (keyword form) is recognized",
          {"status", "note"} <= assigned_keys(ast.parse(src)))
    src_dict_arg = ('def build(number):\n'
                   '    r = {"number": number}\n'
                   '    r.update({"path": "x"})\n'
                   '    return r\n')
    check("`r.update({...})` (dict-literal argument) is recognized too, via the generic "
          "dict-literal branch -- no separate case needed",
          "path" in assigned_keys(ast.parse(src_dict_arg)))


def _proof_exclude_names_hides_a_schema_declaration(check) -> None:
    src = ('FIELDS = {"number": None, "status": None}\n'
          'def build(number):\n'
          '    return {"number": number}\n')
    check("a name in exclude_names (a caller's own schema dict) contributes no keys",
          assigned_keys(ast.parse(src), exclude_names={"FIELDS"}) == {"number"})
    check("...while the same source with nothing excluded reports both",
          assigned_keys(ast.parse(src)) == {"number", "status"})


def selftest() -> int:
    check = Checks()
    _proof_key_constants_resolve_chained_names(check)
    _proof_test_only_exclusion(check)
    _proof_externally_referenced_names_close_the_module_local_blind_spot(check)
    _proof_all_externally_referenced_names_matches_the_per_module_form(check)
    _proof_setdefault_and_update_shapes(check)
    _proof_exclude_names_hides_a_schema_declaration(check)
    return check.report()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
