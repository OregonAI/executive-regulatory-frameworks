"""semantic_search_module (corpus.yml: plugins.semantic_search_module) — vector
search over the offline-built embeddings artifact (src/build_embeddings.py).
Ported from the old src/mcp_lib.py's semantic layer (_semantic_index/
_semantic_doc_order); best-effort like before: if numpy, the artifact, or the
model backend is missing, `available()` returns False and the toolkit's
search_corpus silently falls back to keyword-only."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_SEM = "unset"  # "unset" -> not tried; None -> unavailable; tuple -> loaded


def _semantic_index():
    global _SEM
    if _SEM != "unset":
        return _SEM
    try:
        # The model backends (model2vec/sentence-transformers) hit huggingface.co to
        # check the model revision on every load unless told not to; the serve side
        # only ever queries a model already cached locally by build_embeddings.py.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        import numpy as np
        from build_embeddings import CHUNKS, META, VECTORS, make_embedder
        meta = json.loads(META.read_text())
        vecs = np.load(VECTORS)
        doc_ids = [json.loads(line)["doc_id"]
                   for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line]
        if vecs.shape[0] != len(doc_ids):
            raise ValueError("vectors/chunks length mismatch")
        # The artifact records the model by HUB ID ("BAAI/bge-m3"), which
        # sentence-transformers resolves against the HF cache. In a container the weights
        # are volume-mounted at a path instead, with no cache and no network, so the hub id
        # would fail to resolve. CORPUS_SEMANTIC_MODEL_PATH overrides it with a local
        # directory.
        #
        # This is a SUBSTITUTION OF LOCATION ONLY, never of model: query vectors must come
        # from the same model as the artifact or the scores are meaningless rather than
        # merely worse. The override is therefore only honoured for the transformer
        # backend, and the loaded dim is checked against the artifact's below.
        model_ref = meta.get("model")
        local = os.environ.get("CORPUS_SEMANTIC_MODEL_PATH")
        if local and meta["backend"] == "sentence-transformers" and Path(local).is_dir():
            model_ref = local
        embedder = make_embedder(meta["backend"], meta["dim"], model_ref)

        # A dim mismatch means the query encoder and the vectors disagree, which produces
        # confident nonsense rather than an error. Fail closed to keyword-only instead.
        probe = embedder.encode(["dimension probe"])[0]
        if len(probe) != meta["dim"]:
            raise ValueError(
                f"query encoder produces dim {len(probe)} but the artifact is dim "
                f"{meta['dim']} -- refusing to serve semantic search on mismatched "
                "vectors")

        # CONVERT ONCE, NOT PER QUERY (#76). The artifact is int8 on disk -- 206 MiB for
        # 211,102 x 1024 -- and rank() used to do `vecs.astype(np.float32) @ q`, which
        # rebuilt an 825 MiB float32 copy on EVERY call. Measured on this shape:
        #
        #   astype(f32) @ q per query   277-301 ms
        #   f32 resident @ q              9.2 ms      <- 30x, +825 MiB RSS
        #   f16 resident @ q            443.2 ms      SLOWER than doing nothing
        #   int16 dot                   209.4 ms
        #
        # float16 is not a memory/speed tradeoff, it is a loss: numpy has no float16
        # GEMM so it upcasts internally, paying the conversion anyway on a layout BLAS
        # likes less. It is recorded here because it is the obvious next idea and it is
        # wrong. Blocked matmul was measured too and does not help (291-300 ms at three
        # block sizes) -- the cost is memory bandwidth over 216M values, not allocation.
        #
        # The 825 MiB is the real price and it is paid PER PROCESS. Set
        # CORPUS_SEMANTIC_LOW_MEMORY=1 to keep int8 resident and convert per query
        # instead, for hosts where RSS matters more than latency.
        vecs = prepare_vectors(np, vecs)
        _SEM = (np, vecs, doc_ids, embedder, meta)
    except Exception:
        _SEM = None
    return _SEM


def prepare_vectors(np, vecs):
    """int8 artifact -> the resident form rank() will multiply against.

    Extracted from _semantic_index() so it is reachable from selftest(). Inline in the
    loader it could not be tested at all -- _semantic_index() needs the embeddings
    artifact, which is gitignored and absent from every fresh clone and from CI. A
    selftest that asserts the maths but cannot see whether the loader still does the
    conversion is a guard that passes with the optimisation deleted; that happened on
    the first draft of this one.
    """
    if os.environ.get("CORPUS_SEMANTIC_LOW_MEMORY") == "1":
        print("semantic: low-memory mode, ~280 ms/query", file=sys.stderr)
        return vecs
    return np.ascontiguousarray(vecs, dtype=np.float32)


def available() -> bool:
    return _semantic_index() is not None


def rank(query: str, want: int) -> list:
    """Doc ids ranked by best-chunk cosine similarity to the query (empty if the
    semantic index is unavailable). Multiple chunks per doc_id — first hit in
    similarity order is that document's best chunk."""
    idx = _semantic_index()
    if not idx:
        return []
    np, vecs, doc_ids, embedder, _meta = idx
    q = embedder.encode([query])[0].astype(np.float32)
    # `vecs` is already float32 unless low-memory mode kept it int8, in which case the
    # astype here is the deliberate cost. Both paths are cosine: rows are L2-normalized
    # and the int8 form is scaled by 127, which cancels in the ranking.
    scores = (vecs @ q) if vecs.dtype == np.float32 else (vecs.astype(np.float32) @ q)
    best: dict[str, float] = {}
    for i in np.argsort(-scores):
        d = doc_ids[i]
        if d not in best:
            best[d] = float(scores[i])
            if len(best) >= want:
                break
    return sorted(best, key=lambda d: -best[d])


# --------------------------------------------------------------------------- selftest

def selftest() -> int:
    """Prove the #76 optimisation is behaviour-preserving, on synthetic vectors.

    Runs without the embeddings artifact, which is gitignored and absent from a fresh
    clone -- so this is checkable in CI, where the real index will never exist.

    The property that matters is NOT that float32 is faster. It is that converting once
    at load cannot change what the corpus returns. int8*127 and its float32 copy differ
    by a positive scale factor, which cannot reorder a ranking -- but "cannot" is the
    kind of claim that is worth asserting, because if it were ever false every answer
    the semantic arm gives would change and nothing would report it.
    """
    import numpy as np
    fails = []
    rng = np.random.default_rng(11)
    N, D = 4000, 128
    v = rng.standard_normal((N, D), dtype=np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    vi8 = np.round(v * 127).astype(np.int8)
    f32 = np.ascontiguousarray(vi8, dtype=np.float32)

    # 1. Identical ranking, both paths, over several queries.
    for k in range(8):
        q = rng.standard_normal(D).astype(np.float32)
        q /= np.linalg.norm(q)
        old = np.argsort(-(vi8.astype(np.float32) @ q))[:100]
        new = np.argsort(-(f32 @ q))[:100]
        if not np.array_equal(old, new):
            fails.append(f"query {k}: converting at load reordered the top 100")

    # 2. rank() must work whichever dtype the index holds, because low-memory mode keeps
    #    int8. A dtype check that only ever saw float32 would let the fallback rot.
    global _SEM
    saved = _SEM
    try:
        class _E:
            def encode(self, xs):
                r = rng.standard_normal((len(xs), D)).astype(np.float32)
                return r / np.linalg.norm(r, axis=1, keepdims=True)
        ids = [f"doc-{i // 4}" for i in range(N)]          # 4 chunks per document
        for label, mat in (("float32 (default)", f32), ("int8 (low-memory)", vi8)):
            _SEM = (np, mat, ids, _E(), {"dim": D})
            got = rank("anything", 5)
            if len(got) != 5:
                fails.append(f"{label}: rank() returned {len(got)} docs, want 5")
            if len(set(got)) != len(got):
                fails.append(f"{label}: rank() returned a duplicate doc_id")
    finally:
        _SEM = saved

    # 3. THE LOADER MUST ACTUALLY CONVERT. Checks 1-2 assert the maths and the dtype
    #    fallback; neither notices if prepare_vectors() stops converting, which IS the
    #    #76 bug. The first draft of this selftest passed 12/12 with the optimisation
    #    reverted -- caught only by reverting it and looking.
    os.environ.pop("CORPUS_SEMANTIC_LOW_MEMORY", None)
    out = prepare_vectors(np, vi8)
    if out.dtype != np.float32:
        fails.append("prepare_vectors() left the matrix int8 by default -- every query "
                     "pays the ~280 ms conversion again (#76)")
    os.environ["CORPUS_SEMANTIC_LOW_MEMORY"] = "1"
    try:
        low = prepare_vectors(np, vi8)
        if low.dtype != np.int8:
            fails.append("CORPUS_SEMANTIC_LOW_MEMORY=1 still converted; the memory "
                         "opt-out does nothing and a small host pays 825 MiB anyway")
    finally:
        os.environ.pop("CORPUS_SEMANTIC_LOW_MEMORY", None)

    for f in fails:
        print(f"FAIL {f}")
    print(f"semantic_search selftest: {(8 + 4 + 2) - len(fails)}/14 passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(selftest())
