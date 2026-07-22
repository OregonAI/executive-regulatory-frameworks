#!/usr/bin/env python3
"""Compute the 2-D UMAP projection of the document embeddings and cache it.

Run-once-after-embeddings step (like build_embeddings.py). UMAP over 68k int8 vectors is
minutes of compute and stochastic, so we do it once with a fixed seed and commit the small
projected result; build_topic_map.py (the HTML generator) just reads this cache. The cache
carries the embeddings fingerprint so it can be detected as stale after a re-embed.

  .venv/bin/python src/build_topic_projection.py          # compute + write cache
  .venv/bin/python src/build_topic_projection.py --check  # exit 1 if missing/stale
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT

EMB = REPO_ROOT / "_meta/embeddings"
META = EMB / "meta.json"
VECS = EMB / "vectors.i8.npy"
CHUNKS = EMB / "chunks.jsonl"
GRAPH = REPO_ROOT / "_meta/graph.json"
OUT = EMB / "projection.2d.json"
SEED = 42
N_TOPICS = 28  # semantic clusters over the 512-D embeddings (full coverage, no noise)
# boilerplate that appears across most Oregon docs and makes for useless topic labels
DOMAIN_STOP = ("oregon rule rules chapter division department departments board commission "
               "definitions definition purpose scope general policy program requirements "
               "applicability ors oar section standard standards act procedure procedures "
               "provisions provision authority effective date administration enforcement "
               "application administrative fees fee report reports title notice model "
               "quorum chairperson chairman compensation expenses meeting meetings member "
               "members returned results incomplete formal knowledge dedication").split()


def _fingerprint() -> str:
    return json.loads(META.read_text())["fingerprint"]


def _topic_labels(docs, k):
    """Top distinctive terms per cluster (TF-IDF across clusters), de-duplicated."""
    from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
    vec = TfidfVectorizer(stop_words=list(ENGLISH_STOP_WORDS) + DOMAIN_STOP,
                          ngram_range=(1, 2), max_df=0.4, min_df=2,
                          token_pattern=r"[A-Za-z][A-Za-z]+")
    X = vec.fit_transform(docs)
    feats = vec.get_feature_names_out()
    labels = []
    for c in range(k):
        row = X[c].toarray().ravel()
        picked = []
        for j in row.argsort()[::-1]:
            if row[j] <= 0:
                break
            term = feats[j]
            words = term.split()
            if len(words) == 2 and words[0] == words[1]:      # drop "waiver waiver"
                continue
            # skip a term already implied by / implying a chosen one (substring overlap)
            if any(term in p or p in term for p in picked):
                continue
            picked.append(term)
            if len(picked) == 3:
                break
        labels.append(" · ".join(picked) if picked else f"cluster {c}")
    return labels


def compute() -> dict:
    import numpy as np

    fp = _fingerprint()
    ids = [json.loads(l)["doc_id"] for l in CHUNKS.read_text().splitlines()]
    vecs = np.load(VECS).astype(np.float32)               # (N, 512), already L2*127
    assert len(ids) == vecs.shape[0], f"{len(ids)} ids vs {vecs.shape[0]} vectors"

    # UMAP is the slow part and deterministic (fixed seed) — reuse the cached coordinates
    # when the embeddings are unchanged, so re-clustering doesn't pay for a re-projection.
    cache = json.loads(OUT.read_text()) if OUT.exists() else {}
    if cache.get("fingerprint") == fp and cache.get("ids") == ids and "x" in cache:
        q = np.column_stack([cache["x"], cache["y"]]).astype(int)
    else:
        import umap
        reducer = umap.UMAP(n_neighbors=25, min_dist=0.12, metric="cosine",
                            random_state=SEED, n_components=2, verbose=True)
        xy = np.asarray(reducer.fit_transform(vecs), dtype=np.float32)
        # Quantise to a 0..4095 integer grid per axis — plenty for a scatter, tiny to inline.
        lo, hi = xy.min(0), xy.max(0)
        span = np.where(hi - lo > 0, hi - lo, 1.0)
        q = np.round((xy - lo) / span * 4095).astype(int)

    # Cluster in the 512-D EMBEDDING space (not on the flattened 2-D map). The 2-D UMAP
    # squashes the administrative core into visual homogeneity, but those docs separate by
    # topic in the full space — so clustering here follows real semantic structure and gives
    # meaningful, full-coverage labels instead of one 77% "core" blob. Cosine ≈ Euclidean on
    # these L2-normalised vectors, so KMeans is appropriate; it's fast where HDBSCAN over 68k
    # 512-D points is not. Each label is placed at its cluster's 2-D centroid on the map.
    from sklearn.cluster import MiniBatchKMeans
    cl = MiniBatchKMeans(n_clusters=N_TOPICS, random_state=SEED, n_init=5,
                         batch_size=2048).fit_predict(vecs)
    k = N_TOPICS
    title = {n["id"]: n.get("title", "") for n in json.loads(GRAPH.read_text())["nodes"]}
    docs = [""] * k
    for i, c in zip(ids, cl):
        docs[c] += " " + title.get(i, "")
    labels = _topic_labels(docs, k)
    clusters = []
    for c in range(k):
        m = cl == c
        clusters.append({"t": labels[c], "x": int(round(q[m, 0].mean())),
                         "y": int(round(q[m, 1].mean())), "n": int(m.sum())})
    return {"fingerprint": fp, "grid": 4095, "ids": ids,
            "x": q[:, 0].tolist(), "y": q[:, 1].tolist(),
            "cl": cl.astype(int).tolist(), "clusters": clusters,
            "noise": int((cl == k).sum())}


def main():
    if "--check" in sys.argv:
        if not OUT.exists():
            print("projection.2d.json missing — run: .venv/bin/python src/build_topic_projection.py")
            sys.exit(1)
        cached = json.loads(OUT.read_text()).get("fingerprint")
        if cached != _fingerprint():
            print("projection.2d.json is stale (embeddings changed) — rebuild it")
            sys.exit(1)
        print("projection.2d.json is current.")
        return
    data = compute()
    OUT.write_text(json.dumps(data, separators=(",", ":")))
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {len(data['ids']):,} points")


if __name__ == "__main__":
    main()
