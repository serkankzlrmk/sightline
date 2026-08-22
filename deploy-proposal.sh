#!/usr/bin/env bash
# =============================================================================
# deploy-proposal.sh — Deploy Proposal Studio alongside Sightline on production
# =============================================================================
# Usage:
#   ./deploy-proposal.sh              # Full deploy (clone + build + up)
#   ./deploy-proposal.sh --rebuild    # Force rebuild images
#   ./deploy-proposal.sh --proposal-only  # Only rebuild/update proposal service
#   ./deploy-proposal.sh --check      # Health check only
#
# Prerequisites:
#   - SSH alias: sightline-production (root@178.105.242.180)
#   - Docker Compose v2+ on production server
#   - /opt/sightline/ as compose project directory
# =============================================================================

set -euo pipefail

COMPOSE_DIR="/opt/sightline"
PRODUCTION="sightline-production"
REBUILD_FLAG=""
PROPOSAL_ONLY=false
CHECK_ONLY=false

for arg in "$@"; do
  case "$arg" in
    --rebuild) REBUILD_FLAG="--build" ;;
    --proposal-only) PROPOSAL_ONLY=true ;;
    --check) CHECK_ONLY=true ;;
    *) echo "Unknown arg: $arg"; exit 1 ;;
  esac
done

# ── Health check only ──────────────────────────────────────────────────────
if $CHECK_ONLY; then
  echo "🔍 Checking production health..."
  ssh "$PRODUCTION" "cd $COMPOSE_DIR && \\
    echo 'Sightline:' && curl -sf http://localhost:5001/api/health && echo '' && \\
    echo 'Proposal:' && curl -sf http://localhost:5002/health && echo '' && \\
    echo 'Caddy /proposal:' && curl -sf http://localhost/proposal/health && echo '' && \\
    echo 'Caddy /:' && curl -sf http://localhost/api/health && echo ''"
  exit 0
fi

# ── Ensure proposal repo is cloned ─────────────────────────────────────────
echo "📦 Ensuring proposal repo is cloned on production..."
ssh "$PRODUCTION" "cd $COMPOSE_DIR && \\
  if [ ! -d proposal ]; then \\
    git clone https://github.com/serkankzlrmk/proposal.git proposal; \\
  else \\
    cd proposal && git pull; \\
  fi"

# ── Ensure proposal volumes exist ──────────────────────────────────────────
echo "💾 Creating Docker volumes if missing..."
ssh "$PRODUCTION" "docker volume create proposal_db 2>/dev/null || true && \\
  docker volume create proposal_output 2>/dev/null || true"

# ── Deploy ──────────────────────────────────────────────────────────────────
if $PROPOSAL_ONLY; then
  echo "🚀 Deploying Proposal Studio only..."
  ssh "$PRODUCTION" "cd $COMPOSE_DIR && \\
    docker compose build proposal && \\
    docker compose up -d proposal && \\
    echo '⏳ Waiting for proposal health...' && \\
    sleep 5 && \\
    curl -sf http://localhost:5002/health && echo ''"
else
  echo "🚀 Deploying full stack..."
  ssh "$PRODUCTION" "cd $COMPOSE_DIR && \\
    cd sightline && git pull && \\
    cd ../proposal && git pull && \\
    cd .. && \\
    docker compose build $REBUILD_FLAG && \\
    docker compose up -d $REBUILD_FLAG && \\
    echo '⏳ Waiting for services...' && \\
    sleep 10 && \\
    echo '=== Health checks ===' && \\
    echo 'Sightline:' && curl -sf http://localhost:5001/api/health && echo '' && \\
    echo 'Proposal:' && curl -sf http://localhost:5002/health && echo '' && \\
    echo 'Caddy /proposal:' && curl -sf http://localhost/proposal/health && echo ''"
fi

echo ""
echo "✅ Deployment complete!"
echo "   Sightline: https://sightlinehumanitarian.com"
echo "   Proposal:  https://sightlinehumanitarian.com/proposal"