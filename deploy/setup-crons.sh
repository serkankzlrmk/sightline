#!/bin/bash
# ============================================================
# setup-crons.sh — Install cron jobs for ReliefAgent
#
# Installs:
#   1. Daily ingest (06:00 UTC) — fetches yesterday's reports
#   2. Weekly bulletin (Monday 06:30 UTC) — generates last week's bulletin
#   3. Daily backup (03:00 UTC) — SQLite + ChromaDB backup
#
# Usage:
#   sudo bash deploy/setup-crons.sh
#
# Safe to run multiple times — overwrites existing crons.
# ============================================================

set -euo pipefail

APP_DIR="/opt/reliefagent"
LOG_DIR="/var/log/reliefagent"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# ── 1. Daily Ingest Cron ────────────────────────────────────────
echo "[1/3] Installing daily ingest cron (06:00 UTC)..."
cat > /etc/cron.d/reliefagent-daily-ingest << 'EOF'
# ReliefAgent — Daily Ingest
# Fetches yesterday's ReliefWeb reports + purges data older than 90 days
# Runs at 06:00 UTC every day

SHELL=/bin/bash
PATH=/opt/reliefagent/current/venv/bin:/usr/local/bin:/usr/bin:/bin

0 6 * * * root cd /opt/reliefagent/current && /opt/reliefagent/current/venv/bin/python /opt/reliefagent/current/scripts/daily_ingest.py >> /var/log/reliefagent/daily-ingest.log 2>&1
EOF
chmod 644 /etc/cron.d/reliefagent-daily-ingest
echo "  ✓ Installed /etc/cron.d/reliefagent-daily-ingest"

# ── 2. Weekly Bulletin Cron ────────────────────────────────────
echo "[2/3] Installing weekly bulletin cron (Monday 06:30 UTC)..."
cat > /etc/cron.d/reliefagent-bulletin << 'EOF'
# ReliefAgent — Weekly Bulletin Generation
# Runs every Monday at 06:30 UTC (30 minutes after daily_ingest at 06:00)
# Generates bulletin for the previous week (Mon-Sun)

SHELL=/bin/bash
PATH=/opt/reliefagent/current/venv/bin:/usr/local/bin:/usr/bin:/bin

30 6 * * 1 root cd /opt/reliefagent/current && /opt/reliefagent/current/venv/bin/python /opt/reliefagent/current/scripts/generate_bulletin.py --last-week >> /var/log/reliefagent/bulletin.log 2>&1
EOF
chmod 644 /etc/cron.d/reliefagent-bulletin
echo "  ✓ Installed /etc/cron.d/reliefagent-bulletin"

# ── 3. Daily Backup Cron ────────────────────────────────────────
echo "[3/3] Installing daily backup cron (03:00 UTC)..."
cat > /etc/cron.d/reliefagent-backup << 'EOF'
# ReliefAgent — Daily Backup
# Backs up SQLite + ChromaDB data
# Runs at 03:00 UTC every day

SHELL=/bin/bash
PATH=/opt/reliefagent/current/venv/bin:/usr/local/bin:/usr/bin:/bin

0 3 * * * root /opt/reliefagent/current/deploy/backup.sh >> /var/log/reliefagent/backup.log 2>&1
EOF
chmod 644 /etc/cron.d/reliefagent-backup
echo "  ✓ Installed /etc/cron.d/reliefagent-backup"

# ── Summary ─────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  ✓ All cron jobs installed!"
echo "============================================================"
echo ""
echo "  Daily ingest:  06:00 UTC → /var/log/reliefagent/daily-ingest.log"
echo "  Weekly bulletin: Mon 06:30 UTC → /var/log/reliefagent/bulletin.log"
echo "  Daily backup:  03:00 UTC → /var/log/reliefagent/backup.log"
echo ""
echo "  Verify:  crontab -l | grep reliefagent"
echo "  Test:    sudo /opt/reliefagent/current/venv/bin/python /opt/reliefagent/current/scripts/daily_ingest.py --dry-run"
echo "============================================================"