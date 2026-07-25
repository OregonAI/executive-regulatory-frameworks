# MCP server for the Oregon executive-regulatory-frameworks corpus (HTTP transport).
#   docker build -t executive-regulatory-frameworks-mcp .
#   docker run -p 8000:8000 executive-regulatory-frameworks-mcp
# The corpus is baked in at build time; rebuild the image to pick up new commits.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /repo
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
# pre-build the FTS index so first request is instant (~70s at this corpus's size)
RUN python3 -c "\
from corpus_toolkit import config as config_mod; \
from corpus_toolkit.mcp.framework import CorpusFramework; \
CorpusFramework(config_mod.load('_meta/corpus.yml')).ensure_index()"
EXPOSE 8000
CMD ["corpus-mcp-serve", "--config", "_meta/corpus.yml", "--http", "--host", "0.0.0.0", "--port", "8000"]
