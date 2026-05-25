#!/bin/bash
# ============================================================
# rollback.sh — Roll back to a previous release
#
# Usage:
#   sudo bash deploy/rollback.sh              # roll back to previous release
#   sudo bash deploy/rollback.sh 20250614_120000  # roll back to specific release
#   sudo bash deploy/rollback.sh --list       # list available releases
# ============================================================

set -euo pipefail

APP_DIR="/opt/reliefagent"
RELEASES_DIR="$APP_DIR/releases"
CURRENT_LINK="$APP_DIR/current"
HEALTH_URL="http://localhost:5001/api/health"
HEALTH_RETRIES=10
HEALTH_INTERVAL=3
APP_USER="reliefagent"

# ── List mode ───────────────────────────────────────────────────
if [ "${1:-}" = "--list" ]; then
    echo "Available releases (newest first):"
    echo "─────────────────────────────────"
    for dir in $(ls -1d "$RELEASES_DIR"/*/ 2>/dev/null | sort -r); do
        REL_NAME=$(basename "$dir")
        INFO_FILE="$dir/RELEASE_INFO"
        if [ -f "$INFO_FILE" ]; then
            GIT_SHA=$(grep '^GIT_SHA=' "$INFO_FILE" | cut -d= -f2 | head -c8)
            BRANCH=$(grep '^BRANCH=' "$INFO_FILE" | cut -d= -f2)
            DEPLOY_DATE=$(grep '^DEPLOY_DATE=' "$INFO_FILE" | cut -d= -f2)
            echo "  $REL_NAME  branch=$BRANCH  sha=$GIT_SHA  deployed=$DEPLOY_DATE"
        else
            echo "  $REL_NAME  (no release info)"
        fi
    done

    # Show current
    if [ -L "$CURRENT_LINK" ]; then
        CURRENT_TARGET=$(basename "$(readlink -f "$CURRENT_LINK")")
        echo ""
        echo "Current: $CURRENT_TARGET ← active"
    fi
    exit 0
fi

# ── Determine target release ────────────────────────────────────
TARGET_RELEASE="${1:-}"

if [ -z "$TARGET_RELEASE" ]; then
    # Default: roll back to previous release
    if [ ! -L "$CURRENT_LINK" ]; then
        echo "✗ No current release symlink found"
        exit 1
    fi

    CURRENT_RELEASE=$(basename "$(readlink -f "$CURRENT_LINK")")

    # List releases sorted by date, find the one before current
    PREV_RELEASE=""
    for dir in $(ls -1d "$RELEASES_DIR"/*/ 2>/dev/null | sort -r); do
        REL_NAME=$(basename "$dir")
        if [ "$REL_NAME" = "$CURRENT_RELEASE" ]; then
            break
        fi
        PREV_RELEASE="$REL_NAME"
    done

    if [ -z "$PREV_RELEASE" ]; then
        echo "✗ No previous release to roll back to!"
        echo "  Current: $CURRENT_RELEASE"
        echo "  Use --list to see available releases"
        exit 1
    fi

    TARGET_RELEASE="$PREV_RELEASE"
fi

TARGET_DIR="$RELEASES_DIR/$TARGET_RELEASE"

if [ ! -d "$TARGET_DIR" ]; then
    echo "✗ Release $TARGET_RELEASE not found!"
    echo "  Use --list to see available releases"
    exit 1
fi

# ── Confirm rollback ────────────────────────────────────────────
CURRENT_RELEASE=$(basename "$(readlink -f "$CURRENT_LINK")")

echo "============================================================"
echo "  ReliefAgent — Rollback"
echo "============================================================"
echo "  Current:  $CURRENT_RELEASE"
echo "  Target:   $TARGET_RELEASE"
echo ""

# Show release info if available
if [ -f "$TARGET_DIR/RELEASE_INFO" ]; then
    echo "  Target release info:"
    cat "$TARGET_DIR/RELEASE_INFO" | sed 's/^/    /'
    echo ""
fi

read -p "  Proceed with rollback? [y/N] " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Rollback cancelled."
    exit 0
fi

# ── Execute rollback ────────────────────────────────────────────
echo ""
echo "Switching symlink..."
ln -sfn "$TARGET_DIR" "$CURRENT_LINK"
echo "  ✓ current → $TARGET_RELEASE"

echo "Restarting service..."
systemctl restart reliefagent
echo "  ✓ Service restarted"

# ── Health check ────────────────────────────────────────────────
echo "Health check (up to $((HEALTH_RETRIES * HEALTH_INTERVAL))s)..."

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

if [ "$HEALTH_OK" = false ]; then
    echo ""
    echo "✗ Health check failed after rollback!"
    echo "  The rolled-back version may also have issues."
    echo "  Check logs: journalctl -u reliefagent --no-pager -n 50"
    echo ""
    echo "  Available releases: sudo bash $APP_DIR/deploy/rollback.sh --list"
    exit 1
fi

echo ""
echo "============================================================"
echo "  ✓ Rollback Successful!"
echo "============================================================"
echo "  Now running: $TARGET_RELEASE"
echo "  Health:     $HEALTH_URL"
echo "  Logs:       journalctl -u reliefagent -f"
echo "============================================================"