#!/bin/bash
# ============================================================
# setup-crons-docker.sh — Install cron jobs for Sightline (Docker)
#
# Cron jobs run on the host but execute inside the Docker container
# via `docker exec sightline`.
#
# Installs:
#   1. Daily ingest (06:00 UTC) — fetches yesterday's reports
#   2. Weekly bulletin (Monday 06:30 UTC) — generates last week's bulletin
#   3. Weekly country summaries (Monday 07:00 UTC) — generates country cards
#   4. Daily backup (03:00 UTC) — SQLite + ChromaDB backup
#
# Usage:
#   sudo bash deploy/setup-crons-docker.sh
# ============================================================

set -euo pipefail

LOG_DIR="/var/log/reliefagent"
mkdir -p "$LOG_DIR"

# ── 1. Daily Ingest Cron ────────────────────────────────────────
echo "[1/4] Installing daily ingest cron (06:00 UTC)..."
cat > /etc/cron.d/reliefagent-daily-ingest << 'EOF'
# Sightline — Daily Ingest (Docker)
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
0 6 * * * root docker exec sightline python /app/scripts/daily_ingest.py >> /var/log/reliefagent/daily-ingest.log 2>&1
EOF
chmod 644 /etc/cron.d/reliefagent-daily-ingest
echo "  ✓ Installed /etc/cron.d/reliefagent-daily-ingest"

# ── 2. Weekly Bulletin Cron ────────────────────────────────────
echo "[2/4] Installing weekly bulletin cron (Monday 06:30 UTC)..."
cat > /etc/cron.d/reliefagent-bulletin << 'EOF'
# Sightline — Weekly Bulletin Generation (Docker)
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
30 6 * * 1 root docker exec sightline python /app/scripts/generate_bulletin.py --last-week >> /var/log/reliefagent/bulletin.log 2>&1
EOF
chmod 644 /etc/cron.d/reliefagent-bulletin
echo "  ✓ Installed /etc/cron.d/reliefagent-bulletin"

# ── 3. Daily Country Summaries Cron ─────────────────────────────
echo "[3/4] Installing daily country summaries cron (06:15 UTC)..."
cat > /etc/cron.d/reliefagent-country-summaries << 'EOF'
# Sightline — Daily Country Intelligence Summaries (Docker)
# DB-derived fields refresh daily; HDX + World Bank respect a 30-day TTL.
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
15 6 * * * root docker exec sightline python /app/scripts/generate_country_summaries.py >> /var/log/reliefagent/country-summaries.log 2>&1
EOF
chmod 644 /etc/cron.d/reliefagent-country-summaries
echo "  ✓ Installed /etc/cron.d/reliefagent-country-summaries"

# ── 4. Daily Backup Cron ────────────────────────────────────────
echo "[4/4] Installing daily backup cron (03:00 UTC)..."
cat > /etc/cron.d/reliefagent-backup << 'EOF'
# Sightline — Daily Backup
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
0 3 * * * root /opt/reliefagent/current/deploy/backup.sh >> /var/log/reliefagent/backup.log 2>&1
EOF
chmod 644 /etc/cron.d/reliefagent-backup
echo "  ✓ Installed /etc/cron.d/reliefagent-backup"

# ── Summary ─────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  ✓ All cron jobs installed (Docker mode)!"
echo "============================================================"
echo ""
echo "  Daily ingest:        06:00 UTC → docker exec sightline"
echo "  Weekly bulletin:     Mon 06:30 UTC → docker exec sightline"
echo "  Country summaries:  daily 06:15 UTC → docker exec sightline"
echo "  Daily backup:       03:00 UTC → backup.sh"
echo ""
echo "  Logs: /var/log/reliefagent/"
echo "============================================================"