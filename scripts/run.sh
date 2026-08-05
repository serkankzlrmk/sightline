#!/usr/bin/env bash
# =============================================================================
# Sightline — Run script (macOS / Linux)
# =============================================================================
# Starts Sightline in Docker mode (recommended).
#
# Usage:
#   ./scripts/run.sh              # Docker mode (production-like)
#   ./scripts/run.sh --build      # Rebuild Docker image
#   ./scripts/run.sh --local      # Local Python mode (no Docker)
#   ./scripts/run.sh --desktop    # Desktop mode (DESKTOP_MODE=true, no Firebase)
# =============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# ── Check .env exists ────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠ No .env file found. Copying from .env.example...${NC}"
    cp .env.example .env
    echo -e "${YELLOW}  Edit .env with your API keys, then re-run this script.${NC}"
    echo -e "${YELLOW}  Required: OPENROUTER_API_KEY, RELIEFWEB_APPNAME${NC}"
    exit 1
fi

# ── Mode selection ───────────────────────────────────────────────────────────
MODE="${1:-docker}"

case "$MODE" in
    --local|local)
        echo -e "${GREEN}▶ Starting Sightline in LOCAL mode (Python)...${NC}"
        if [ ! -d ".venv" ]; then
            echo -e "${YELLOW}  Creating virtual environment...${NC}"
            python -m venv .venv
            .venv/bin/pip install -r requirements.txt
            .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
        fi
        export SERVER_HOST="${SERVER_HOST:-127.0.0.1}"
        export SERVER_PORT="${SERVER_PORT:-5001}"
        .venv/bin/python server.py
        ;;

    --desktop|desktop)
        echo -e "${GREEN}▶ Starting Sightline in DESKTOP mode (local, no Firebase)...${NC}"
        export SERVER_HOST="127.0.0.1"
        export DESKTOP_MODE="true"
        export SERVER_DEBUG="true"
        if [ ! -d ".venv" ]; then
            echo -e "${YELLOW}  Creating virtual environment...${NC}"
            python -m venv .venv
            .venv/bin/pip install -r requirements.txt
            .venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
        fi
        .venv/bin/python server.py
        ;;

    --build|build)
        echo -e "${GREEN}▶ Building and starting Sightline in Docker...${NC}"
        docker compose up -d --build
        echo -e "${GREEN}✓ Sightline is running at http://localhost:5001${NC}"
        docker compose logs -f sightline
        ;;

    docker|--docker|*)
        echo -e "${GREEN}▶ Starting Sightline in Docker...${NC}"
        docker compose up -d
        echo -e "${GREEN}✓ Sightline is running at http://localhost:5001${NC}"
        echo -e "  Logs: docker compose logs -f sightline"
        echo -e "  Stop: docker compose down"
        ;;
esac
