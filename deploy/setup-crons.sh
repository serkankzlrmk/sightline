#!/bin/bash
# ============================================================
# setup-crons.sh — Install cron jobs for Sightline
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

APP_DIR="/opt/sightline"
LOG_DIR="/var/log/sightline"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# ── 1. Daily Ingest Cron ────────────────────────────────────────
echo "[1/3] Installing daily ingest cron (06:00 UTC)..."
cat > /etc/cron.d/sightline-daily-ingest << 'EOF'
# Sightline — Daily Ingest
# Fetches yesterday's ReliefWeb reports + purges data older than 90 days
# Runs at 06:00 UTC every day

SHELL=/bin/bash
PATH=/opt/sightline/current/venv/bin:/usr/local/bin:/usr/bin:/bin

0 6 * * * root cd /opt/sightline/current && /opt/sightline/current/venv/bin/python /opt/sightline/current/scripts/daily_ingest.py >> /var/log/sightline/daily-ingest.log 2>&1
EOF
chmod 644 /etc/cron.d/sightline-daily-ingest
echo "  ✓ Installed /etc/cron.d/sightline-daily-ingest"

# ── 2. Weekly Bulletin Cron ────────────────────────────────────
echo "[2/3] Installing weekly bulletin cron (Monday 06:30 UTC)..."
cat > /etc/cron.d/sightline-bulletin << 'EOF'
# Sightline — Weekly Bulletin Generation
# Runs every Monday at 06:30 UTC (30 minutes after daily_ingest at 06:00)
# Generates bulletin for the previous week (Mon-Sun)

SHELL=/bin/bash
PATH=/opt/sightline/current/venv/bin:/usr/local/bin:/usr/bin:/bin

30 6 * * 1 root cd /opt/sightline/current && /opt/sightline/current/venv/bin/python /opt/sightline/current/scripts/generate_bulletin.py --last-week >> /var/log/sightline/bulletin.log 2>&1
EOF
chmod 644 /etc/cron.d/sightline-bulletin
echo "  ✓ Installed /etc/cron.d/sightline-bulletin"

# ── 3. Daily Backup Cron ────────────────────────────────────────
echo "[3/3] Installing daily backup cron (03:00 UTC)..."
cat > /etc/cron.d/sightline-backup << 'EOF'
# Sightline — Daily Backup
# Backs up SQLite + ChromaDB data
# Runs at 03:00 UTC every day

SHELL=/bin/bash
PATH=/opt/sightline/current/venv/bin:/usr/local/bin:/usr/bin:/bin

0 3 * * * root /opt/sightline/current/deploy/backup.sh >> /var/log/sightline/backup.log 2>&1
EOF
chmod 644 /etc/cron.d/sightline-backup
echo "  ✓ Installed /etc/cron.d/sightline-backup"

# ── Summary ─────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  ✓ All cron jobs installed!"
echo "============================================================"
echo ""
echo "  Daily ingest:  06:00 UTC → /var/log/sightline/daily-ingest.log"
echo "  Weekly bulletin: Mon 06:30 UTC → /var/log/sightline/bulletin.log"
echo "  Daily backup:  03:00 UTC → /var/log/sightline/backup.log"
echo ""
echo "  Verify:  crontab -l | grep sightline"
echo "  Test:    sudo /opt/sightline/current/venv/bin/python /opt/sightline/current/scripts/daily_ingest.py --dry-run"
echo "============================================================"