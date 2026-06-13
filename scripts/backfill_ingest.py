#!/usr/bin/env python3
"""
backfill_ingest.py — One-time backfill ingestion for NovaSphere.

Fetches ALL reports from ReliefWeb API for the last N days (default 30),
ingests them into SQLite + ChromaDB, then purges data older than 90 days.

This is intended to be run ONCE to populate the database with historical data
before switching to the daily auto-ingest cron (daily_ingest.py).

Usage:
  python scripts/backfill_ingest.py                    # last 30 days + purge
  python scripts/backfill_ingest.py --days 60           # last 60 days
  python scripts/backfill_ingest.py --dry-run           # preview only
  python scripts/backfill_ingest.py --no-purge          # skip purge step
  python scripts/backfill_ingest.py --from 2026-04-01 --to 2026-05-28  # custom range
"""

import sys
import os
import logging
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Suppress ONNX/TensorRT noise
os.environ.setdefault("ORT_LOGGING_LEVEL", "3")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("ORT_TENSORRT_ENGINE_CACHE_ENABLE", "0")

from config import config

# Import ReliefWeb config directly (avoid __init__.py which imports heavy deps)
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "reliefweb_config",
    str(PROJECT_ROOT / "reliefweb_api" / "reliefweb_config.py"),
)
_rw_cfg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rw_cfg)
RELIEFWEB_REPORTS_API = _rw_cfg.RELIEFWEB_REPORTS_API
RELIEFWEB_APPNAME = _rw_cfg.RELIEFWEB_APPNAME
_ssl_verify = _rw_cfg._ssl_verify

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("backfill_ingest")

# ── Config ──────────────────────────────────────────────────────────────────
DB_PATH = str(config.DB_PATH)
CHROMA_DIR = str(config.CHROMA_DIR)
APPNAME = RELIEFWEB_APPNAME
PURGE_DAYS = 90
RELIEFWEB_API_URL = RELIEFWEB_REPORTS_API
PAGE_SIZE = 100  # max per request (ReliefWeb API limit)


def fetch_report_ids_for_date(target_date: str) -> list:
    """Fetch all report IDs from ReliefWeb API for a given date (YYYY-MM-DD).

    Returns a list of report IDs.
    """
    import requests

    all_ids = []
    offset = 0

    while True:
        payload = {
            "preset": "latest",
            "limit": PAGE_SIZE,
            "offset": offset,
            "fields": {"include": ["id", "title"]},
            "filter": {
                "operator": "AND",
                "conditions": [
                    {
                        "field": "date.original",
                        "value": {
                            "from": f"{target_date}T00:00:00+00:00",
                            "to": f"{target_date}T23:59:59+00:00",
                        },
                    }
                ],
            },
        }

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        url = RELIEFWEB_API_URL
        if APPNAME:
            url = f"{RELIEFWEB_API_URL}?appname={APPNAME}"

        try:
            resp = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=30,
                verify=_ssl_verify(),
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.error("ReliefWeb API request failed (offset=%d): %s", offset, e)
            break

        results = data.get("data", [])
        if not results:
            break

        for r in results:
            rid = r.get("id") or r.get("fields", {}).get("id")
            if rid:
                all_ids.append(int(rid))

        total_count = data.get("totalCount", 0)
        offset += PAGE_SIZE

        if offset >= total_count:
            break

    return all_ids


def ingest_reports(report_ids: list, dry_run: bool = False) -> dict:
    """Ingest a list of report IDs into SQLite + ChromaDB.

    Returns: {ingested: int, skipped: int, errors: int, error_details: list}
    """
    from reliefweb_api.ingest_pipeline import is_ingested, is_ingested_with_pdf, ingest_from_api

    ingested = 0
    skipped = 0
    errors = 0
    error_details = []

    for i, rid in enumerate(report_ids):
        if is_ingested(rid, DB_PATH) and is_ingested_with_pdf(rid, DB_PATH):
            skipped += 1
            log.debug("[%d/%d] Skipped %d (already in DB)", i + 1, len(report_ids), rid)
            continue

        if dry_run:
            log.info("[%d/%d] Would ingest %d (dry run)", i + 1, len(report_ids), rid)
            ingested += 1
            continue

        try:
            result = ingest_from_api(rid, DB_PATH, CHROMA_DIR)
            if result.get("success"):
                ingested += 1
                chunks = result.get("chunks_added", 0)
                log.info("[%d/%d] Ingested %d → %d chunks", i + 1, len(report_ids), rid, chunks)
            else:
                errors += 1
                err = result.get("error", "unknown")
                error_details.append({"report_id": rid, "error": err})
                log.warning("[%d/%d] Failed %d: %s", i + 1, len(report_ids), rid, err)
        except Exception as e:
            errors += 1
            error_details.append({"report_id": rid, "error": str(e)})
            log.warning("[%d/%d] Error %d: %s", i + 1, len(report_ids), rid, e)

    return {
        "ingested": ingested,
        "skipped": skipped,
        "errors": errors,
        "error_details": error_details,
    }


def purge_old_data(days: int = PURGE_DAYS, dry_run: bool = False) -> dict:
    """Purge reports older than `days` from SQLite + ChromaDB.

    Returns: {reports_purged: int, chunks_purged_chroma: int}
    """
    from reliefweb_api.db_manager import DatabaseManager
    from reliefweb_api.vector_store import VectorStore

    db = DatabaseManager(DB_PATH)
    old_ids = db.get_old_report_ids(days=days)

    if not old_ids:
        log.info("No reports older than %d days to purge", days)
        return {"reports_purged": 0, "chunks_purged_chroma": 0}

    log.info("Found %d reports older than %d days to purge", len(old_ids), days)

    if dry_run:
        log.info("Dry run: would purge %d reports", len(old_ids))
        return {"reports_purged": len(old_ids), "chunks_purged_chroma": 0}

    vs = VectorStore(CHROMA_DIR)
    chroma_removed = vs.purge_by_report_ids(old_ids)
    log.info("Purged %d chunks from ChromaDB", chroma_removed)

    sqlite_purged = db.purge_old_reports(days=days)
    log.info("Purged %d reports from SQLite", sqlite_purged)

    return {
        "reports_purged": sqlite_purged,
        "chunks_purged_chroma": chroma_removed,
    }


def main():
    parser = argparse.ArgumentParser(description="Backfill ReliefWeb reports for the last N days")
    parser.add_argument("--days", type=int, default=30, help="Number of days to backfill (default: 30)")
    parser.add_argument("--from", dest="date_from", help="Start date YYYY-MM-DD (overrides --days)")
    parser.add_argument("--to", dest="date_to", help="End date YYYY-MM-DD (overrides --days)")
    parser.add_argument("--no-purge", action="store_true", help="Skip the purge step")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    parser.add_argument("--purge-days", type=int, default=PURGE_DAYS, help="Purge threshold in days (default: 90)")
    args = parser.parse_args()

    # Determine date range
    today = datetime.now(timezone.utc).date()
    if args.date_from and args.date_to:
        start_date = datetime.strptime(args.date_from, "%Y-%m-%d").date()
        end_date = datetime.strptime(args.date_to, "%Y-%m-%d").date()
    else:
        end_date = today - timedelta(days=1)  # yesterday (don't include today)
        start_date = end_date - timedelta(days=args.days - 1)

    # Generate list of dates
    date_list = []
    current = start_date
    while current <= end_date:
        date_list.append(current)
        current += timedelta(days=1)

    log.info("=" * 60)
    log.info("Backfill Ingest — %s to %s (%d days)", start_date, end_date, len(date_list))
    if args.dry_run:
        log.info("DRY RUN — no writes will be made")
    log.info("=" * 60)

    total_fetched = 0
    total_ingested = 0
    total_skipped = 0
    total_errors = 0
    all_error_details = []

    for day_idx, target_date in enumerate(date_list):
        date_str = target_date.strftime("%Y-%m-%d")
        log.info("")
        log.info("[%d/%d] Processing %s...", day_idx + 1, len(date_list), date_str)

        # Fetch report IDs for this date
        report_ids = fetch_report_ids_for_date(date_str)
        log.info("  Found %d reports for %s", len(report_ids), date_str)
        total_fetched += len(report_ids)

        if not report_ids:
            continue

        # Ingest
        result = ingest_reports(report_ids, dry_run=args.dry_run)
        total_ingested += result["ingested"]
        total_skipped += result["skipped"]
        total_errors += result["errors"]
        all_error_details.extend(result.get("error_details", []))

        log.info(
            "  %s: %d ingested, %d skipped, %d errors",
            date_str,
            result["ingested"],
            result["skipped"],
            result["errors"],
        )

    # Purge old data
    purge_result = {"reports_purged": 0, "chunks_purged_chroma": 0}
    if not args.no_purge:
        log.info("")
        log.info("Purging data older than %d days...", args.purge_days)
        purge_result = purge_old_data(days=args.purge_days, dry_run=args.dry_run)
        log.info(
            "Purge complete: %d reports removed from SQLite, %d chunks from ChromaDB",
            purge_result["reports_purged"],
            purge_result["chunks_purged_chroma"],
        )

    # Summary
    log.info("")
    log.info("=" * 60)
    log.info("SUMMARY")
    log.info("  Date range:    %s → %s", start_date, end_date)
    log.info("  Days processed: %d", len(date_list))
    log.info("  Fetched:       %d", total_fetched)
    log.info("  Ingested:      %d", total_ingested)
    log.info("  Skipped:       %d", total_skipped)
    log.info("  Errors:        %d", total_errors)
    log.info("  Purged (SQL):  %d", purge_result["reports_purged"])
    log.info("  Purged (Vec):  %d", purge_result["chunks_purged_chroma"])
    log.info("=" * 60)

    if all_error_details:
        log.info("")
        log.info("Error details (first 10):")
        for ed in all_error_details[:10]:
            log.info("  Report %s: %s", ed.get("report_id"), ed.get("error"))

    # Exit with error code if there were ingest errors
    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()