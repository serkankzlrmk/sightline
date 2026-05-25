#!/bin/bash
# ============================================================
# update.sh — Thin wrapper around deploy.sh
#
# Usage:
#   sudo bash deploy/update.sh [branch] [--skip-backup]
#
# This script calls deploy.sh which handles:
#   - Pre-flight checks
#   - Database backup
#   - Clone to timestamped release directory
#   - Install dependencies
#   - Atomic symlink switch
#   - Health check with automatic rollback on failure
#   - Cleanup of old releases
#
# For manual rollback: sudo bash deploy/rollback.sh
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Note: update.sh is a wrapper around deploy.sh"
echo "      For direct control, use: sudo bash deploy/deploy.sh [branch]"
echo ""

exec bash "$SCRIPT_DIR/deploy.sh" "$@"