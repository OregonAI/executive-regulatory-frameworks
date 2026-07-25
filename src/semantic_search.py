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
        embedder = make_embedder(meta["backend"], meta["dim"], meta.get("model"))
        _SEM = (np, vecs, doc_ids, embedder, meta)
    except Exception:
        _SEM = None
    return _SEM


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
    scores = vecs.astype(np.float32) @ q          # cosine (all rows L2-normalized)
    best: dict[str, float] = {}
    for i in np.argsort(-scores):
        d = doc_ids[i]
        if d not in best:
            best[d] = float(scores[i])
            if len(best) >= want:
                break
    return sorted(best, key=lambda d: -best[d])
