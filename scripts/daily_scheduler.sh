#!/bin/sh
set -eu

# Run daily_ingest + daily visual enrichment once at 06:00 UTC.
# A mkdir lock prevents overlap.
while :; do
  now=$(date -u +%s)
  next=$(date -u -d 'tomorrow 06:00' +%s 2>/dev/null || true)
  [ -n "$next" ] || next=$((now + 86400))
  sleep_seconds=$((next - now))
  [ "$sleep_seconds" -gt 0 ] || sleep_seconds=60
  sleep "$sleep_seconds"
  if mkdir /tmp/sightline-daily-ingest.lock 2>/dev/null; then
    yesterday=$(date -u -d 'yesterday' +%F 2>/dev/null || date -u -v-1d +%F 2>/dev/null || true)
    if [ -z "$yesterday" ]; then
      yesterday=$(date -u +%F)
    fi
    echo "[daily] ingesting text for $yesterday"
    python scripts/daily_ingest.py --date "$yesterday" --no-purge || true
    echo "[daily] visual enrichment for $yesterday"
    python scripts/daily_visual_pipeline.py --date "$yesterday" --r2-required || true
    rmdir /tmp/sightline-daily-ingest.lock 2>/dev/null || true
  fi
done
