FROM python:3.13.11-slim-trixie
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 MCP_BRASIL_DATASET_CACHE_DIR=/cache
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --disable-pip-version-check "mcp-brasil==0.14.0" "fastmcp==3.4.7" \
    && useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin mcp
WORKDIR /app
COPY --chown=mcp:mcp upstream/mcp-brasil-container/serve.py ./serve.py
RUN install -d -o mcp -g mcp -m 0750 /cache
USER mcp
EXPOSE 8000
CMD ["python", "/app/serve.py"]
