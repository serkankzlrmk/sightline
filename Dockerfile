# =============================================================================
# Sightline — Dockerfile (ARM64 production + local dev)
# Single-stage build for simplicity and reliability
# =============================================================================
# Build: docker build -t sightline:latest .
# Run:   docker compose up -d

FROM python:3.12-slim

# Install system packages: Node.js 20 (MCP servers), uv (uvx for arxiv MCP), sqlite3, curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl sqlite3 build-essential gcc g++ \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install uv (for uvx — arxiv MCP server)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    ln -sf /root/.local/bin/uvx /usr/local/bin/uvx && \
    ln -sf /root/.local/bin/uv /usr/local/bin/uv

# Install Python dependencies (system-wide)
COPY requirements.txt .
# Install CPU-only torch first to avoid 4.5 GB nvidia CUDA packages
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu || true
RUN pip install --no-cache-dir -r requirements.txt

# Set working directory
WORKDIR /app

# Copy application code
COPY . .

# Pre-install MCP server packages (avoids 30-60s cold start on first use)
RUN uvx --no-cache arxiv-mcp-server --help 2>/dev/null || true
RUN npx -y @modelcontextprotocol/server-sequential-thinking --help 2>/dev/null || true
RUN npx -y @brave/brave-search-mcp-server --help 2>/dev/null || true

# Clean up build deps
RUN apt-get purge -y build-essential gcc g++ 2>/dev/null || true && apt-get autoremove -y 2>/dev/null || true

# Environment defaults (overridden by docker-compose env_file)
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    ORT_LOGGING_LEVEL=3 \
    TF_CPP_MIN_LOG_LEVEL=3 \
    ORT_TENSORRT_ENGINE_CACHE_ENABLE=0 \
    UV_CACHE_DIR=/tmp/uv-cache \
    npm_config_cache=/tmp/npm-cache \
    HOME=/tmp \
    CONTAINER_MODE=true

# Expose Flask port
EXPOSE 5001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=30s \
    CMD curl -sf http://localhost:5001/api/health || exit 1

# Run with gunicorn (python -m for reliable module resolution)
CMD ["python", "-m", "gunicorn", "-c", "deploy/gunicorn.conf.py", "server:app"]