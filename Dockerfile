# MCP server for the Oregon executive-regulatory-frameworks corpus (HTTP transport).
#
#   docker build -t executive-regulatory-frameworks-mcp .
#   docker run -p 8000:8000 executive-regulatory-frameworks-mcp
#
# The corpus is baked in at build time; rebuild the image to pick up new commits.
#
# BUILD FROM A SHALLOW CLONE, not your working tree. `.git` cannot be excluded — it is a
# RUNTIME dependency, because the FTS cache key is `git rev-parse HEAD` plus a hash of
# `git status --porcelain`, and corpus_overview() shells out to `git log -1`. In a full
# clone that directory is ~845 MB and dominates the image. A depth-1 clone keeps git
# working and the image small:
#
#   git clone --depth 1 --branch main https://github.com/OregonAI/executive-regulatory-frameworks build/
#   docker build -t executive-regulatory-frameworks-mcp build/
#
# SEMANTIC SEARCH IS ACTIVE, and none of its bulk is in this image. requirements.txt
# installs torch (CPU wheel) + sentence-transformers so a query can be encoded; the 253 MiB
# vector artifact and 2.2 GB of BAAI/bge-m3 weights are bind-mounted by
# platform-deploy/docker-compose.yml. Neither can be built here — the artifact needs a GPU
# — so mounting is not an optimisation, it is the only way this works.
#
# LAYER ORDER IS LOAD-BEARING. requirements.txt is copied and installed BEFORE the corpus,
# so a content-only change reuses the pip layer. With the two steps the other way round —
# which is how this file read until 2026-07-30 — every edited markdown file re-downloaded
# torch and sentence-transformers. That was the bulk of a 15-minute rebuild; the index step
# below is only ~70s of it.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /repo
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# pre-build the FTS index so first request is instant (~70s at this corpus's size)
RUN python3 -c "\
from corpus_toolkit import config as config_mod; \
from corpus_toolkit.mcp.framework import CorpusFramework; \
CorpusFramework(config_mod.load('_meta/corpus.yml')).ensure_index()"
EXPOSE 8000

# --path and --public-hostname both matter behind the tunnel and are easy to omit:
#   * A Cloudflare Tunnel matches on path but does NOT strip it. Routing
#     /executive-regulatory-frameworks here forwards the whole path, so the server must
#     mount at that same prefix or every request 404s.
#   * Without --public-hostname the SDK's DNS-rebinding guard rejects the forwarded Host
#     header with 421 Invalid Host header.
# Override either at `docker run` for a different hostname or a dedicated-host deployment
# (in which case pass --path /mcp).
CMD ["corpus-mcp-serve", "--config", "_meta/corpus.yml", "--http", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--path", "/executive-regulatory-frameworks/mcp", \
     "--public-hostname", "oregonai.morficflux.com"]
