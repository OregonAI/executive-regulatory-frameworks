#!/usr/bin/env python3
"""Build the semantic-search vector index for the MCP server (optional workstream).

An offline, run-once-after-ingest step (like link_graph.py): embed every content
document with a LOCAL model (one vector per document — title + At-a-glance + head of
full text) and write an int8-quantized vector artifact under _meta/embeddings/ that the
MCP query engine (src/mcp_lib.py) loads for hybrid BM25+vector search.

  python3 src/build_embeddings.py                 # build/refresh the index
  python3 src/build_embeddings.py --check         # exit 1 if artifact is stale (CI)
  python3 src/build_embeddings.py --limit 500     # embed a subset (dev/smoke)
  python3 src/build_embeddings.py --backend sentence-transformers

Backends (auto: model2vec -> sentence-transformers -> hashing; override with --backend):
  - model2vec              PRODUCTION DEFAULT. Static embeddings (default
                           minishlab/potion-retrieval-32M) — token-vector lookup, no
                           transformer forward pass, so ~10k texts/sec on CPU. The right
                           choice for a CPU-only host; a transformer manages ~1-2/sec at
                           this text length (a ~13h build over this corpus).
  - sentence-transformers  Higher quality but ~1-2 texts/sec on CPU — practical only with
                           a GPU or a small corpus (default BAAI/bge-small-en-v1.5).
  - hashing                ZERO-DEPENDENCY fallback: hashed char-ngram bag-of-words. NO
                           semantic quality — only for wiring the pipeline / CI tests.

Artifact (under _meta/embeddings/, committed to git):
  vectors.i8.npy   int8 [n_docs, dim]  — each row an L2-normalized embedding × 127
  chunks.jsonl     one JSON object per row (one per doc): {doc_id, heading, ordinal, preview}
  meta.json        {backend, model, dim, granularity, n_chunks, fingerprint, repr_chars}

Dependency policy: this BUILD tool requires numpy (+ a model backend). The SERVE
side (mcp_lib) lazily imports numpy and falls back to pure FTS keyword search when
the artifact or numpy is absent — so the base install stays stdlib-only and the CI
`mcp_lib --selftest` runs without extra deps.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from repo_lib import REPO_ROOT, content_files, extract_fulltext, parse_frontmatter

EMB_DIR = REPO_ROOT / "_meta/embeddings"
VECTORS = EMB_DIR / "vectors.i8.npy"
CHUNKS = EMB_DIR / "chunks.jsonl"
META = EMB_DIR / "meta.json"

DEFAULT_M2V = "minishlab/potion-retrieval-32M"      # static, CPU-fast (default backend)
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"             # transformer (--backend sentence-transformers)
CHUNK_CHARS = 1600     # ~400 tokens
OVERLAP = 200


# ---------- searchable text + chunking ----------

def _section(body: str, heading: str):
    m = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", body, re.M | re.S)
    return m.group(1).strip() if m else None


def doc_units(path: Path):
    """(doc_id, [(heading, text), ...]) — the glance and full text of one document."""
    fm, body = parse_frontmatter(path)
    units = []
    glance = _section(body, "At a glance")
    if glance:
        units.append(("At a glance", glance))
    ft = extract_fulltext(body) or _section(body, "Key provisions")
    if ft:
        units.append(("Full text", ft))
    return fm["id"], fm.get("title", ""), units


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP):
    """Split on paragraph boundaries into <= size-char chunks with light overlap."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks, i = [], 0
    while i < len(text):
        end = min(i + size, len(text))
        # prefer to break at a paragraph/sentence boundary near the window end
        if end < len(text):
            brk = text.rfind("\n\n", i + size // 2, end)
            if brk == -1:
                brk = text.rfind(". ", i + size // 2, end)
            if brk != -1:
                end = brk + 1
        chunks.append(text[i:end].strip())
        if end >= len(text):
            break
        i = max(end - overlap, i + 1)
    return [c for c in chunks if c]


def iter_chunks(paths):
    """Yield (doc_id, heading, ordinal, title, chunk_text) across the corpus."""
    for p in paths:
        doc_id, title, units = doc_units(p)
        ordinal = 0
        for heading, text in units:
            for ch in chunk_text(text):
                yield doc_id, heading, ordinal, title, ch
                ordinal += 1


# ---------- corpus fingerprint (freshness key) ----------

def corpus_fingerprint(paths) -> str:
    """Hash of (doc_id + searchable text) across the corpus — changes only when the
    embeddable content changes, NOT on unrelated commits (unlike the fts.db git-state
    key). Lets --check detect staleness without re-embedding, and lets mcp_lib tell
    whether committed vectors still match the corpus."""
    h = hashlib.sha256()
    for p in sorted(paths):
        doc_id, _title, units = doc_units(p)
        h.update(doc_id.encode())
        for heading, text in units:
            h.update(heading.encode())
            h.update(re.sub(r"\s+", " ", text).strip().encode())
    return h.hexdigest()


# ---------- embedders ----------

class HashingEmbedder:
    """Deterministic stdlib+numpy fallback. Hashes 3–5-char n-grams into `dim` buckets
    with sub-linear tf weighting, then L2-normalizes. Reproducible and dependency-light,
    but NOT semantic — production uses SentenceTransformerEmbedder."""
    name = "hashing"

    def __init__(self, dim=384, model="hashing-ngram-v1"):
        self.dim = dim
        self.model = model or "hashing-ngram-v1"

    def encode(self, texts):
        import math
        import numpy as np
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for r, t in enumerate(texts):
            t = re.sub(r"\s+", " ", t.lower())
            for n in (3, 4, 5):
                for i in range(len(t) - n + 1):
                    g = t[i:i + n]
                    b = int.from_bytes(hashlib.blake2b(g.encode(), digest_size=4).digest(), "little") % self.dim
                    out[r, b] += 1.0
            row = out[r]
            nz = row > 0
            row[nz] = 1.0 + np.log(row[nz])          # sub-linear tf
            norm = float(np.linalg.norm(row)) or 1.0
            out[r] = row / norm
        return out


class Model2VecEmbedder:
    """Static (model2vec) embeddings — token-vector lookup + pooling, NO transformer
    forward pass, so it runs ~10,000 texts/sec on CPU (vs ~1-2/sec for a transformer at
    this text length). Default production backend on CPU-only hosts; retrieval quality is
    lower than a transformer but clearly separates related from unrelated concepts, which
    is what the vector arm of the hybrid (BM25+vector) search needs."""
    name = "model2vec"

    def __init__(self, model=DEFAULT_M2V):
        import numpy as np
        from model2vec import StaticModel
        self.model = model or DEFAULT_M2V
        self._m = StaticModel.from_pretrained(self.model)
        self.dim = int(self._m.encode(["probe"]).shape[1])
        self._np = np

    def encode(self, texts):
        np = self._np
        v = self._m.encode(list(texts)).astype("float32")
        n = np.linalg.norm(v, axis=1, keepdims=True)
        n[n == 0] = 1.0
        return v / n


class SentenceTransformerEmbedder:
    """Transformer backend — higher quality than model2vec but ~1-2 texts/sec on CPU, so
    only practical with a GPU or for a small corpus. Rebuild with --backend
    sentence-transformers where compute allows."""
    name = "sentence-transformers"

    def __init__(self, model=DEFAULT_MODEL):
        from sentence_transformers import SentenceTransformer
        self.model = model or DEFAULT_MODEL
        self._m = SentenceTransformer(self.model)
        self.dim = self._m.get_sentence_embedding_dimension()

    def encode(self, texts):
        return self._m.encode(texts, normalize_embeddings=True,
                              batch_size=64, show_progress_bar=False).astype("float32")


def make_embedder(backend, dim, model=None):
    """Build the embedder for a given backend. `model` is honored so the SERVE side
    (mcp_lib) reconstructs the SAME model the committed index was built with — using a
    different query model against those vectors would return silent garbage."""
    if backend == "hashing":
        return HashingEmbedder(dim=dim, model=model or "hashing-ngram-v1")
    if backend == "model2vec":
        return Model2VecEmbedder(model)
    if backend == "sentence-transformers":
        return SentenceTransformerEmbedder(model)
    # auto: static model2vec (CPU-appropriate) -> transformer -> hashing fallback
    for ctor in (lambda: Model2VecEmbedder(model), lambda: SentenceTransformerEmbedder(model)):
        try:
            return ctor()
        except Exception:
            continue
    print("note: no embedding model available; using the hashing fallback backend "
          "(no semantic quality).", file=sys.stderr)
    return HashingEmbedder(dim=dim, model=model)


# ---------- build ----------

def quantize_int8(vecs):
    import numpy as np
    return np.clip(np.rint(vecs * 127.0), -127, 127).astype(np.int8)


REPR_CHARS = 1400   # ~350 tokens: title + At-a-glance + head of full text
BATCH = 256         # encode/report granularity


def doc_repr(path):
    """One representative text per document for a single embedding: title +
    At-a-glance + the head of the full text. Doc-level (one vector per doc) is the
    right granularity for a CPU-only build over a ~68k-doc corpus — search returns
    documents, and BM25 covers full-text keyword recall in the hybrid path. (Per-chunk
    embedding is 5-10x the cost for marginal ranking gain here.)"""
    fm, body = parse_frontmatter(path)
    parts = [fm.get("title", "")]
    glance = _section(body, "At a glance")
    if glance:
        parts.append(glance)
    ft = extract_fulltext(body) or _section(body, "Key provisions")
    if ft:
        parts.append(ft)
    text = re.sub(r"[ \t]+", " ", "\n".join(p for p in parts if p)).strip()
    return fm["id"], text[:REPR_CHARS]


def build(backend="auto", limit=None, dim=384):
    import time

    import numpy as np
    paths = list(content_files())
    if limit:
        paths = paths[:limit]
    emb = make_embedder(backend, dim)

    ids, texts, previews = [], [], []
    for p in paths:
        did, text = doc_repr(p)
        if not text:
            continue
        ids.append(did); texts.append(text); previews.append(text[:160])
    n = len(texts)
    if not n:
        print("no documents to embed")
        return

    print(f"embedding {n} documents ({emb.name}, doc-level) …", flush=True)
    out = np.empty((n, emb.dim), dtype=np.int8)
    t0 = time.time()
    for start in range(0, n, BATCH):
        batch = texts[start:start + BATCH]
        out[start:start + len(batch)] = quantize_int8(emb.encode(batch))
        done = start + len(batch)
        if done % (BATCH * 4) == 0 or done == n:
            rate = done / max(time.time() - t0, 1e-6)
            eta = (n - done) / max(rate, 1e-6)
            print(f"  {done}/{n} ({done*100//n}%) · {rate:.1f} docs/s · "
                  f"ETA {eta/60:.0f} min", flush=True)

    EMB_DIR.mkdir(parents=True, exist_ok=True)
    np.save(VECTORS, out)
    with CHUNKS.open("w", encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({"doc_id": ids[i], "heading": "doc", "ordinal": 0,
                                "preview": previews[i]}, ensure_ascii=False) + "\n")
    META.write_text(json.dumps({
        "backend": emb.name, "model": getattr(emb, "model", ""), "dim": int(emb.dim),
        "granularity": "document", "n_chunks": n,
        "fingerprint": corpus_fingerprint(paths), "repr_chars": REPR_CHARS,
        "note": ("one int8 vector per document (title + At-a-glance + head of full text), "
                 "L2-normalized*127; cosine ≈ int32 dot / 127^2. Rebuild with "
                 "src/build_embeddings.py after any ingest."),
    }, indent=1) + "\n")
    print(f"embedded {n} documents ({emb.name}, dim={emb.dim}) -> "
          f"{VECTORS.relative_to(REPO_ROOT)}", flush=True)


def check():
    # Semantic search is optional: no committed artifact => soft-pass (the MCP server
    # falls back to keyword search). Only a COMMITTED-but-stale artifact fails CI, so a
    # rebuild is forced whenever the embedded content drifts from what's committed.
    if not META.is_file():
        print("no embeddings artifact — semantic search disabled (keyword-only); OK.")
        return
    meta = json.loads(META.read_text())
    fp = corpus_fingerprint(list(content_files()))
    if meta.get("fingerprint") != fp:
        print("_meta/embeddings is stale — run: python3 src/build_embeddings.py")
        sys.exit(1)
    print(f"_meta/embeddings current ({meta['n_chunks']} chunks, {meta['backend']}).")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 if the artifact is stale")
    ap.add_argument("--backend", choices=["auto", "model2vec", "sentence-transformers", "hashing"],
                    default="auto")
    ap.add_argument("--limit", type=int, help="embed only the first N content files")
    ap.add_argument("--dim", type=int, default=384, help="dim for the hashing backend")
    args = ap.parse_args()
    if args.check:
        check()
    else:
        build(args.backend, args.limit, args.dim)


if __name__ == "__main__":
    main()
