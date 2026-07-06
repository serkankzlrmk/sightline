# =============================================================================
# Sightline — Dockerfile (ARM64 production + local dev)
# Multi-stage build: keeps final image small (~700 MB vs 5.7 GB venv)
# =============================================================================
# Build: docker build -t sightline:latest .
# Run:   docker compose up -d

# ── Stage 1: Builder ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies (needed for compiling C extensions like hdbscan)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Install Python deps to /root/.local (user-space, no torch/nvidia)
# sentence-transformers pulls torch — we install CPU-only torch first to avoid
# the 4.5 GB nvidia CUDA packages
RUN pip install --user --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu || true
RUN pip install --user --no-cache-dir -r requirements.txt

# ── Stage 2: Runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim

# Install system packages: Node.js (MCP servers), uv (uvx for arxiv MCP), sqlite3, curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl sqlite3 \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install uv (for uvx — arxiv MCP server)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    ln -sf /root/.local/bin/uvx /usr/local/bin/uvx && \
    ln -sf /root/.local/bin/uv /usr/local/bin/uv

# Copy Python packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Set working directory
WORKDIR /app

# Copy application code
COPY . .

# Pre-install MCP server packages (avoids 30-60s cold start on first use)
# arxiv MCP (via uvx)
RUN uvx --no-cache arxiv-mcp-server --help 2>/dev/null || true
# sequential-thinking MCP (via npx)
RUN npx -y @modelcontextprotocol/server-sequential-thinking --help 2>/dev/null || true
# brave-search MCP (via npx — will download but won't run without API key)
RUN npx -y @brave/brave-search-mcp-server --help 2>/dev/null || true

# Environment defaults (overridden by docker-compose env_file)
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    ORT_LOGGING_LEVEL=3 \
    TF_CPP_MIN_LOG_LEVEL=3 \
    ORT_TENSORRT_ENGINE_CACHE_ENABLE=0 \
    UV_CACHE_DIR=/tmp/uv-cache \
    npm_config_cache=/tmp/npm-cache \
    HOME=/tmp

# Expose Flask port
EXPOSE 5001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=30s \
    CMD curl -sf http://localhost:5001/api/health || exit 1

# Run with gunicorn (same config as production)
CMD ["gunicorn", "-c", "deploy/gunicorn.conf.py", "server:app"]