#!/bin/bash
# ============================================================
# update.sh — Quick update & restart for ReliefAgent
# Usage: sudo bash deploy/update.sh
# ============================================================

set -euo pipefail

APP_DIR="/opt/reliefagent"
BRANCH="${1:-main}"

echo "=== Updating ReliefAgent (branch: $BRANCH) ==="

cd "$APP_DIR"

# Pull latest changes
echo "[1/4] Pulling latest code..."
sudo -u reliefagent git fetch origin
sudo -u reliefagent git reset --hard "origin/$BRANCH"

# Update dependencies
echo "[2/4] Updating Python dependencies..."
sudo -u reliefagent venv/bin/pip install -q -r requirements.txt

# Restart service
echo "[3/4] Restarting service..."
systemctl restart reliefagent

# Wait and check status
echo "[4/4] Checking status..."
sleep 3
if systemctl is-active --quiet reliefagent; then
    echo "✓ ReliefAgent is running!"
    echo "  Health check:"
    curl -s http://localhost:5000/api/health | python3 -m json.tool 2>/dev/null || echo "  (health endpoint not responding yet — may need a few seconds)"
else
    echo "✗ ReliefAgent failed to start!"
    echo "  Check logs: journalctl -u reliefagent --no-pager -n 50"
    exit 1
fi

echo ""
echo "Current git version:"
sudo -u reliefagent git log --oneline -1
echo ""