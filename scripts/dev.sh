#!/usr/bin/env bash
# =============================================================================
# Sightline — Dev script (hot reload, debug logging, auth bypassed)
# =============================================================================
# Starts Sightline in development mode with:
#   - Hot reload (auto-restart on file changes)
#   - Debug logging
#   - DESKTOP_MODE (no Firebase auth needed)
#   - Loopback only (127.0.0.1)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# ── Check .env exists ────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo "⚠ No .env file found. Copying from .env.example..."
    cp .env.example .env
    echo "  Edit .env with your API keys, then re-run this script."
    exit 1
fi

# ── Check venv ───────────────────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python -m venv .venv
    .venv/bin/pip install -r requirements.txt
    .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
fi

# ── Start dev server ─────────────────────────────────────────────────────────
export SERVER_HOST="127.0.0.1"
export SERVER_PORT="${SERVER_PORT:-5001}"
export SERVER_DEBUG="true"
export DESKTOP_MODE="true"

echo "▶ Starting Sightline in DEV mode..."
echo "  URL: http://127.0.0.1:${SERVER_PORT}"
echo "  Auth: DESKTOP_MODE (bypassed, admin access)"
echo "  Hot reload: enabled"
echo "  Logs: verbose (DEBUG level)"
echo ""

.venv/bin/python server.py
