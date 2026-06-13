#!/bin/bash
# auto-deploy.sh — Cron-based auto-deploy for NovaSphere
#
# Runs every 2 minutes via /etc/cron.d/novasphere-autodeploy
# Checks for new commits on main branch, deploys with health check + auto-rollback
#
# Setup:
#   1. Copy this script to /opt/novasphere/auto-deploy.sh
#   2. Generate SSH deploy key: ssh-keygen -t ed25519 -f /root/.ssh/id_ed25519 -N ""
#   3. Add public key to GitHub repo as deploy key (with write access for cleanup)
#   4. Add cron: echo '*/2 * * * * root /opt/novasphere/auto-deploy.sh >> /var/log/novasphere/auto-deploy.log 2>&1' > /etc/cron.d/novasphere-autodeploy
#
set -euo pipefail

APP_DIR="/opt/novasphere"
DATA_DIR="$APP_DIR/data"
RELEASES_DIR="$APP_DIR/releases"
CURRENT_LINK="$APP_DIR/current"
HEALTH_URL="http://localhost:5001/api/health"
REPO_DIR="$APP_DIR/repo"
BRANCH="main"
LOG_TAG="auto-deploy"

log() { logger -t "$LOG_TAG" "$1"; echo "[$(date -Iseconds)] $1"; }

# -- Check for new commits --
if [ ! -d "$REPO_DIR" ]; then
    log "INIT: Cloning repo for tracking..."
    git clone --bare git@github.com:serkankzlrmk/RedAgent.git "$REPO_DIR" 2>&1 | tail -3
fi

cd "$REPO_DIR"

# Fetch and update local refs so git clone -b main works correctly
git fetch origin "+refs/heads/$BRANCH:refs/heads/$BRANCH" 2>&1 | tail -3 || { log "WARN: git fetch failed"; exit 0; }

NEW_SHA=$(git rev-parse "refs/heads/$BRANCH" 2>/dev/null || echo "")
if [ -z "$NEW_SHA" ]; then
    log "ERROR: Could not resolve refs/heads/$BRANCH"
    exit 1
fi

CURRENT_SHA=""
if [ -f "$APP_DIR/.last-deploy-sha" ]; then
    CURRENT_SHA=$(cat "$APP_DIR/.last-deploy-sha")
fi

if [ "$NEW_SHA" = "$CURRENT_SHA" ]; then
    exit 0
fi

log "NEW COMMIT: ${CURRENT_SHA:0:8} -> ${NEW_SHA:0:8}"

# -- Create new release --
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
NEW_RELEASE="$RELEASES_DIR/$TIMESTAMP"

log "Creating release: $TIMESTAMP"
git clone --depth 1 -b "$BRANCH" "$REPO_DIR" "$NEW_RELEASE" 2>&1 | tail -3

# -- Create fresh venv (pip cache makes this fast) --
log "Creating venv..."
cd "$NEW_RELEASE"
python3 -m venv venv
venv/bin/pip install --upgrade pip setuptools wheel -q 2>&1 | tail -1
venv/bin/pip install -r requirements.txt -q 2>&1 | tail -3
venv/bin/pip install gunicorn -q 2>&1 | tail -1

# -- Remove GPU packages (not needed on ARM64, saves ~4.5GB) --
log "Removing GPU packages..."
venv/bin/pip uninstall -y torch nvidia-cublas-cu12 nvidia-cuda-cupti-cu12 nvidia-cuda-nvrtc-cu12 \
  nvidia-cuda-runtime-cu12 nvidia-cudnn-cu12 nvidia-cufft-cu12 nvidia-cufile-cu12 \
  nvidia-curand-cu12 nvidia-cusolver-cu12 nvidia-cusparse-cu12 nvidia-nccl-cu12 \
  nvidia-nvjitlink-cu12 nvidia-nvtx-cu12 nvidia-cusparselt-cu12 nvidia-nvshmem-cu12 \
  triton kubernetes 2>/dev/null | tail -1 || true
rm -rf venv/lib/python3.*/site-packages/nvidia/ venv/lib/python3.*/site-packages/torch/ venv/lib/python3.*/site-packages/triton/

# -- Clean pip cache to save disk --
pip cache purge 2>/dev/null || true

# -- Link shared data --
ln -sf "$DATA_DIR/.env" "$NEW_RELEASE/.env"
[ -f "$DATA_DIR/firebase-service-account.json" ] && ln -sf "$DATA_DIR/firebase-service-account.json" "$NEW_RELEASE/firebase-service-account.json"
ln -sf "$DATA_DIR/reliefweb.db" "$NEW_RELEASE/reliefweb.db"
ln -sf "$DATA_DIR/chats.db" "$NEW_RELEASE/chats.db"
ln -sfn "$DATA_DIR/reliefweb_chroma" "$NEW_RELEASE/reliefweb_chroma"
ln -sfn "$DATA_DIR/output" "$NEW_RELEASE/output"

# -- Release info --
cat > "$NEW_RELEASE/RELEASE_INFO" << EOF
TIMESTAMP=$TIMESTAMP
GIT_SHA=$NEW_SHA
BRANCH=$BRANCH
DEPLOYER=auto-deploy
DEPLOY_DATE=$(date -Iseconds)
EOF

chown -R novasphere:novasphere "$NEW_RELEASE"

# -- Atomic switch --
PREV_RELEASE=$(readlink -f "$CURRENT_LINK")
ln -sfn "$NEW_RELEASE" "$CURRENT_LINK"
systemctl restart novasphere
log "Symlink switched, service restarted"

# -- Health check --
HEALTH_OK=false
for i in $(seq 1 10); do
    if curl -sf "$HEALTH_URL" 2>/dev/null | grep -q '"ok"'; then
        HEALTH_OK=true
        log "Health OK (attempt $i)"
        break
    fi
    sleep 3
done

if [ "$HEALTH_OK" = false ]; then
    log "FAILED - rolling back"
    ln -sfn "$PREV_RELEASE" "$CURRENT_LINK"
    systemctl restart novasphere
    exit 1
fi

# -- Save SHA --
echo "$NEW_SHA" > "$APP_DIR/.last-deploy-sha"

# -- Cleanup: keep only current + 1 previous --
RELEASE_COUNT=$(ls -1d "$RELEASES_DIR"/*/ 2>/dev/null | wc -l | tr -d ' ')
if [ "$RELEASE_COUNT" -gt 2 ]; then
    ls -1d "$RELEASES_DIR"/*/ | sort | head -n -2 | xargs rm -rf
    log "Cleaned old releases"
fi

log "DEPLOY OK: $TIMESTAMP ($NEW_SHA)"