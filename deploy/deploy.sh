#!/bin/bash
# ============================================================
# deploy.sh — Safe deployment with automatic rollback
#
# Usage:
#   sudo bash deploy/deploy.sh [branch] [--skip-backup]
#
# Each deploy creates a timestamped release directory under
# /opt/reliefagent/releases/ and atomically switches the
# /opt/reliefagent/current symlink. If the health check fails,
# it automatically rolls back to the previous release.
#
# Directory structure:
#   /opt/reliefagent/
#   ├── current → releases/YYYYMMDD_HHMMSS   (symlink)
#   ├── releases/
#   │   ├── 20250615_143000/                   (active)
#   │   └── 20250614_120000/                   (previous — rollback target)
#   ├── data/                                  (shared persistent data)
#   │   ├── .env
#   │   ├── firebase-service-account.json
#   │   ├── reliefweb.db
#   │   ├── chats.db
#   │   ├── reliefweb_chroma/
#   │   ├── reliefweb_downloads/
#   │   └── output/
#   └── backups/
# ============================================================

set -euo pipefail

# ── Configuration ───────────────────────────────────────────────
APP_DIR="/opt/reliefagent"
DATA_DIR="$APP_DIR/data"
RELEASES_DIR="$APP_DIR/releases"
CURRENT_LINK="$APP_DIR/current"
BACKUP_SCRIPT="$APP_DIR/deploy/backup.sh"
HEALTH_URL="http://localhost:5001/api/health"
HEALTH_RETRIES=10
HEALTH_INTERVAL=3
KEEP_RELEASES=3
REPO_URL="https://github.com/serkankzlrmk/RedAgent.git"
APP_USER="reliefagent"
LOG_DIR="/var/log/reliefagent"

# ── Parse arguments ──────────────────────────────────────────────
BRANCH="${1:-main}"
SKIP_BACKUP=false

for arg in "$@"; do
    case "$arg" in
        --skip-backup) SKIP_BACKUP=true ;;
        --branch=*) BRANCH="${arg#--branch=}" ;;
    esac
done

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RELEASE_DIR="$RELEASES_DIR/$TIMESTAMP"

echo "============================================================"
echo "  ReliefAgent — Safe Deploy"
echo "  Branch:  $BRANCH"
echo "  Release: $TIMESTAMP"
echo "============================================================"
echo ""

# ── Pre-flight checks ───────────────────────────────────────────
echo "[1/8] Pre-flight checks..."

# Check running as root
if [ "$(id -u)" -ne 0 ]; then
    echo "✗ Must run as root (sudo)"
    exit 1
fi

# Check disk space (need at least 1GB free)
AVAILABLE_GB=$(df -BG "$APP_DIR" | awk 'NR==2 {print $4}' | tr -d 'G')
if [ "$AVAILABLE_GB" -lt 1 ]; then
    echo "✗ Insufficient disk space: ${AVAILABLE_GB}GB free (need ≥1GB)"
    exit 1
fi

# Check git connectivity
if ! git ls-remote --heads "$REPO_URL" "$BRANCH" 2>/dev/null | grep -q "$BRANCH"; then
    echo "✗ Branch '$BRANCH' not found in remote repository"
    exit 1
fi
echo "  ✓ Branch '$BRANCH' exists in remote"

# Check data directory exists (must have been set up by setup.sh)
if [ ! -d "$DATA_DIR" ]; then
    echo "✗ Data directory $DATA_DIR not found. Run deploy/setup.sh first."
    exit 1
fi

# Check .env exists in data dir
if [ ! -f "$DATA_DIR/.env" ]; then
    echo "✗ .env not found in $DATA_DIR/. Run deploy/setup.sh first."
    exit 1
fi
echo "  ✓ Data directory and .env found"

# ── Backup ──────────────────────────────────────────────────────
if [ "$SKIP_BACKUP" = true ]; then
    echo "[2/8] Skipping backup (--skip-backup flag)"
else
    echo "[2/8] Backing up databases..."
    if [ -f "$BACKUP_SCRIPT" ]; then
        bash "$BACKUP_SCRIPT"
        echo "  ✓ Backup complete"
    else
        echo "  ⚠ Backup script not found, skipping backup"
    fi
fi

# ── Clone to new release directory ──────────────────────────────
echo "[3/8] Cloning branch '$BRANCH' to $RELEASE_DIR..."
mkdir -p "$RELEASES_DIR"
git clone --depth 1 -b "$BRANCH" "$REPO_URL" "$RELEASE_DIR"
echo "  ✓ Clone complete"

# Record release info
GIT_SHA=$(cd "$RELEASE_DIR" && git rev-parse HEAD)
cat > "$RELEASE_DIR/RELEASE_INFO" <<EOF
TIMESTAMP=$TIMESTAMP
GIT_SHA=$GIT_SHA
BRANCH=$BRANCH
DEPLOYER=$(whoami)
DEPLOY_DATE=$(date -Iseconds)
EOF
echo "  ✓ Release info written (SHA: ${GIT_SHA:0:8})"

# ── Install dependencies ────────────────────────────────────────
echo "[4/8] Installing Python dependencies..."
cd "$RELEASE_DIR"
python3 -m venv venv
venv/bin/pip install --upgrade pip setuptools wheel -q
venv/bin/pip install -r requirements.txt -q
venv/bin/pip install gunicorn -q

# Remove GPU packages (not needed on ARM64, saves ~4.5GB)
echo "  Removing GPU packages..."
venv/bin/pip uninstall -y torch nvidia-cublas-cu12 nvidia-cuda-cupti-cu12 nvidia-cuda-nvrtc-cu12 \
  nvidia-cuda-runtime-cu12 nvidia-cudnn-cu12 nvidia-cufft-cu12 nvidia-cufile-cu12 \
  nvidia-curand-cu12 nvidia-cusolver-cu12 nvidia-cusparse-cu12 nvidia-nccl-cu12 \
  nvidia-nvjitlink-cu12 nvidia-nvtx-cu12 nvidia-cusparselt-cu12 nvidia-nvshmem-cu12 \
  triton kubernetes 2>/dev/null | tail -1 || true
rm -rf venv/lib/python3.*/site-packages/nvidia/ venv/lib/python3.*/site-packages/torch/ venv/lib/python3.*/site-packages/triton/

# Clean pip cache
pip cache purge 2>/dev/null || true
echo "  ✓ Dependencies installed (GPU packages removed)"

# ── Link shared data ────────────────────────────────────────────
echo "[5/8] Linking shared data..."

# Symlink .env
ln -sf "$DATA_DIR/.env" "$RELEASE_DIR/.env"

# Symlink firebase service account
if [ -f "$DATA_DIR/firebase-service-account.json" ]; then
    ln -sf "$DATA_DIR/firebase-service-account.json" "$RELEASE_DIR/firebase-service-account.json"
fi

# Symlink databases
ln -sf "$DATA_DIR/reliefweb.db" "$RELEASE_DIR/reliefweb.db"
ln -sf "$DATA_DIR/chats.db" "$RELEASE_DIR/chats.db"

# Symlink data directories
ln -sfn "$DATA_DIR/reliefweb_chroma" "$RELEASE_DIR/reliefweb_chroma"
ln -sfn "$DATA_DIR/output" "$RELEASE_DIR/output"

echo "  ✓ Shared data linked"

# ── Set permissions ─────────────────────────────────────────────
chown -R "$APP_USER:$APP_USER" "$RELEASE_DIR"

# ── Atomic switch ───────────────────────────────────────────────
echo "[6/8] Switching to new release..."

# Find previous release for potential rollback
PREV_RELEASE=""
if [ -L "$CURRENT_LINK" ]; then
    PREV_RELEASE=$(readlink -f "$CURRENT_LINK")
fi

# Atomic symlink switch
ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"
echo "  ✓ Symlink switched: current → $TIMESTAMP"

# Restart service
systemctl restart reliefagent
echo "  ✓ Service restarted"

# ── Health check ────────────────────────────────────────────────
echo "[7/8] Health check (up to $((HEALTH_RETRIES * HEALTH_INTERVAL))s)..."

HEALTH_OK=false
for i in $(seq 1 "$HEALTH_RETRIES"); do
    if curl -sf "$HEALTH_URL" 2>/dev/null | grep -q '"ok"'; then
        HEALTH_OK=true
        echo "  ✓ Health check passed (attempt $i)"
        break
    fi
    echo "  ... attempt $i/$HEALTH_RETRIES failed, retrying in ${HEALTH_INTERVAL}s"
    sleep "$HEALTH_INTERVAL"
done

# ── Rollback on failure ─────────────────────────────────────────
if [ "$HEALTH_OK" = false ]; then
    echo ""
    echo "✗✗✗ HEALTH CHECK FAILED ✗✗✗"
    echo ""

    if [ -n "$PREV_RELEASE" ] && [ -d "$PREV_RELEASE" ]; then
        echo "Rolling back to previous release: $(basename "$PREV_RELEASE")"
        ln -sfn "$PREV_RELEASE" "$CURRENT_LINK"
        systemctl restart reliefagent

        # Wait for rollback to stabilize
        sleep 5
        if curl -sf "$HEALTH_URL" 2>/dev/null | grep -q '"ok"'; then
            echo "✓ Rollback successful — previous version is live"
        else
            echo "✗ Rollback also failed! Manual intervention required!"
            echo "  Check logs: journalctl -u reliefagent --no-pager -n 50"
        fi
    else
        echo "✗ No previous release to roll back to!"
        echo "  Check logs: journalctl -u reliefagent --no-pager -n 50"
    fi

    echo ""
    echo "Failed release preserved at: $RELEASE_DIR"
    echo "To inspect: cd $RELEASE_DIR && venv/bin/python -c 'import server'"
    exit 1
fi

# ── Cleanup old releases ────────────────────────────────────────
echo "[8/8] Cleaning old releases (keeping last $KEEP_RELEASES)..."
RELEASE_COUNT=$(ls -1d "$RELEASES_DIR"/*/ 2>/dev/null | wc -l | tr -d ' ')
if [ "$RELEASE_COUNT" -gt "$KEEP_RELEASES" ]; then
    ls -1d "$RELEASES_DIR"/*/ | sort | head -n -"$KEEP_RELEASES" | xargs rm -rf
    REMOVED=$((RELEASE_COUNT - KEEP_RELEASES))
    echo "  ✓ Removed $REMOVE old release(s)"
else
    echo "  ✓ Only $RELEASE_COUNT release(s), no cleanup needed"
fi

# ── Summary ─────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  ✓ Deploy Successful!"
echo "============================================================"
echo "  Release:  $TIMESTAMP"
echo "  Branch:   $BRANCH"
echo "  Git SHA:  ${GIT_SHA:0:8}"
echo "  Directory: $RELEASE_DIR"
echo ""
echo "  Health:   $HEALTH_URL"
echo "  Logs:     journalctl -u reliefagent -f"
echo ""
echo "  Rollback: sudo bash $APP_DIR/deploy/rollback.sh"
echo "============================================================"