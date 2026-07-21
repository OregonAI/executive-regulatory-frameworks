#!/usr/bin/env python3
"""Build the semantic-search vector index for the MCP server (optional workstream).

An offline, run-once-after-ingest step (like link_graph.py): chunk every content
document's searchable text, embed each chunk with a LOCAL model, and write an
int8-quantized vector artifact under _meta/embeddings/ that the MCP query engine
(src/mcp_lib.py) loads for hybrid BM25+vector search.

  python3 src/build_embeddings.py                 # build/refresh the index
  python3 src/build_embeddings.py --check         # exit 1 if artifact is stale (CI)
  python3 src/build_embeddings.py --limit 500     # embed a subset (dev/smoke)
  python3 src/build_embeddings.py --backend hashing

Backends (auto-detected; override with --backend):
  - sentence-transformers  PRODUCTION. A small local model (default
                           BAAI/bge-small-en-v1.5, 384-dim). No network at serve
                           time once vectors + model are committed/cached.
  - hashing                ZERO-DEPENDENCY fallback: deterministic hashed char-ngram
                           bag-of-words. NO semantic quality — only for wiring the
                           pipeline and CI tests when no model is installed.

Artifact (under _meta/embeddings/, committed to git):
  vectors.i8.npy   int8 [n_chunks, dim]  — each row an L2-normalized embedding × 127
  chunks.jsonl     one JSON object per row: {doc_id, heading, ordinal, preview}
  meta.json        {backend, model, dim, n_chunks, fingerprint, chunk_chars, overlap}

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

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
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


class SentenceTransformerEmbedder:
    """Production backend — a small local model, L2-normalized output."""
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
    if backend == "sentence-transformers":
        return SentenceTransformerEmbedder(model)
    # auto: prefer the real model, fall back to hashing
    try:
        return SentenceTransformerEmbedder(model)
    except Exception as e:
        print(f"note: sentence-transformers unavailable ({e.__class__.__name__}); "
              "using the hashing fallback backend (no semantic quality).", file=sys.stderr)
        return HashingEmbedder(dim=dim, model=model)


# ---------- build ----------

def quantize_int8(vecs):
    import numpy as np
    return np.clip(np.rint(vecs * 127.0), -127, 127).astype(np.int8)


def build(backend="auto", limit=None, dim=384):
    import numpy as np
    paths = list(content_files())
    if limit:
        paths = paths[:limit]
    emb = make_embedder(backend, dim)

    ids, headings, ordinals, previews, texts = [], [], [], [], []
    for doc_id, heading, ordinal, _title, ch in iter_chunks(paths):
        ids.append(doc_id); headings.append(heading); ordinals.append(ordinal)
        previews.append(ch[:160]); texts.append(ch)
    if not texts:
        print("no chunks to embed")
        return

    vecs = emb.encode(texts)
    q = quantize_int8(vecs)

    EMB_DIR.mkdir(parents=True, exist_ok=True)
    np.save(VECTORS, q)
    with CHUNKS.open("w", encoding="utf-8") as f:
        for i in range(len(ids)):
            f.write(json.dumps({"doc_id": ids[i], "heading": headings[i],
                                "ordinal": ordinals[i], "preview": previews[i]},
                               ensure_ascii=False) + "\n")
    META.write_text(json.dumps({
        "backend": emb.name, "model": getattr(emb, "model", ""), "dim": int(vecs.shape[1]),
        "n_chunks": len(ids), "fingerprint": corpus_fingerprint(paths),
        "chunk_chars": CHUNK_CHARS, "overlap": OVERLAP,
        "note": ("int8 vectors, L2-normalized*127; cosine ≈ int32 dot / 127^2. Rebuild "
                 "with src/build_embeddings.py after any ingest."),
    }, indent=1) + "\n")
    print(f"embedded {len(ids)} chunks from {len(paths)} docs "
          f"({emb.name}, dim={vecs.shape[1]}) -> {VECTORS.relative_to(REPO_ROOT)}")


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
    ap.add_argument("--backend", choices=["auto", "sentence-transformers", "hashing"],
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
