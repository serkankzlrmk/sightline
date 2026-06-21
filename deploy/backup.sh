#!/bin/bash
# ============================================================
# backup.sh — Daily SQLite backup for Sightline
# Add to crontab: 0 3 * * * /opt/sightline/deploy/backup.sh
# ============================================================

set -euo pipefail
umask 077  # Restrictive permissions for backup files (contain user PII)

APP_DIR="/opt/sightline"
BACKUP_DIR="/opt/sightline/backups"
DATE=$(date +%Y%m%d_%H%M)
MAX_BACKUPS=14  # Keep 2 weeks of backups

mkdir -p "$BACKUP_DIR"

# SQLite backup (safe — uses .backup command)
echo "[$DATE] Backing up SQLite databases..."
sqlite3 "$APP_DIR/data/reliefweb.db" ".backup $BACKUP_DIR/reliefweb_$DATE.db" 2>/dev/null || \
    cp "$APP_DIR/data/reliefweb.db" "$BACKUP_DIR/reliefweb_$DATE.db"
sqlite3 "$APP_DIR/data/chats.db" ".backup $BACKUP_DIR/chats_$DATE.db" 2>/dev/null || \
    cp "$APP_DIR/data/chats.db" "$BACKUP_DIR/chats_$DATE.db"

# ChromaDB backup (directory copy)
echo "[$DATE] Backing up ChromaDB..."
cp -r "$APP_DIR/data/reliefweb_chroma" "$BACKUP_DIR/reliefweb_chroma_$DATE"

# Compress old backups
echo "[$DATE] Compressing backups..."
find "$BACKUP_DIR" -name "*.db" -mtime +1 -exec gzip -f {} \;
find "$BACKUP_DIR" -name "reliefweb_chroma_*" -type d -mtime +1 -exec tar -czf {}.tar.gz -C {} . \; -exec rm -rf {} \;

# Restrict permissions on backup files (contain user chat history + PII)
chmod 600 "$BACKUP_DIR"/* 2>/dev/null || true
# TODO: Encrypt backup with gpg --symmetric --cipher-algo AES256 before offsite transfer
# TODO: Push offsite via rclone/rsync to S3/B2 with lifecycle policy

# Clean up old backups
echo "[$DATE] Cleaning up old backups..."
find "$BACKUP_DIR" -name "*.gz" -mtime +$MAX_BACKUPS -delete

echo "[$DATE] Backup complete!"
echo "  Files: $(ls -1 $BACKUP_DIR | wc -l)"
echo "  Size:  $(du -sh $BACKUP_DIR | cut -f1)"