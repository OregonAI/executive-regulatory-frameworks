# MCP server for the Oregon policy corpus (HTTP transport).
#   docker build -t oregon-policy-mcp .
#   docker run -p 8000:8000 oregon-policy-mcp
# The corpus is baked in at build time; rebuild the image to pick up new commits.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /repo
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
# pre-build the FTS index so first request is instant
RUN python3 src/mcp_lib.py --rebuild
EXPOSE 8000
CMD ["python3", "src/mcp_server.py", "--http", "--host", "0.0.0.0", "--port", "8000"]
