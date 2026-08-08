#!/bin/sh
set -eu

# Run daily_ingest once at 06:00 UTC. A mkdir lock prevents overlap.
while :; do
  now=$(date -u +%s)
  next=$(date -u -d 'tomorrow 06:00' +%s 2>/dev/null || true)
  [ -n "$next" ] || next=$((now + 86400))
  sleep_seconds=$((next - now))
  [ "$sleep_seconds" -gt 0 ] || sleep_seconds=60
  sleep "$sleep_seconds"
  if mkdir /tmp/sightline-daily-ingest.lock 2>/dev/null; then
    python scripts/daily_ingest.py --no-purge || true
    rmdir /tmp/sightline-daily-ingest.lock 2>/dev/null || true
  fi
done
