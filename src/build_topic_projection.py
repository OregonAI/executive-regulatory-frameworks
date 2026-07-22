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
OUT = EMB / "projection.2d.json"
SEED = 42


def _fingerprint() -> str:
    return json.loads(META.read_text())["fingerprint"]


def compute() -> dict:
    import numpy as np
    import umap

    fp = _fingerprint()
    vecs = np.load(VECS).astype(np.float32)               # (N, 512), already L2*127
    ids = [json.loads(l)["doc_id"] for l in CHUNKS.read_text().splitlines()]
    assert len(ids) == vecs.shape[0], f"{len(ids)} ids vs {vecs.shape[0]} vectors"

    reducer = umap.UMAP(n_neighbors=25, min_dist=0.12, metric="cosine",
                        random_state=SEED, n_components=2, verbose=True)
    xy = reducer.fit_transform(vecs)                      # (N, 2) float

    # Quantise to a 0..4095 integer grid (per axis) — plenty for a scatter, tiny to inline.
    xy = np.asarray(xy, dtype=np.float32)
    lo, hi = xy.min(0), xy.max(0)
    span = np.where(hi - lo > 0, hi - lo, 1.0)
    q = np.round((xy - lo) / span * 4095).astype(int)
    return {"fingerprint": fp, "grid": 4095,
            "ids": ids, "x": q[:, 0].tolist(), "y": q[:, 1].tolist()}


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
