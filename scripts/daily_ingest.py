#!/usr/bin/env python3
"""
daily_ingest.py — Automated daily ingestion + purge for Sightline.

Runs every morning at 06:00 UTC via cron:
  1. Fetches ALL reports from the previous day (no country/theme filter)
  2. Ingests new reports into SQLite + ChromaDB (in-memory, no disk files)
  3. Purges reports older than 90 days from both SQLite and ChromaDB

Usage:
  python scripts/daily_ingest.py              # ingest yesterday + purge
  python scripts/daily_ingest.py --date 2026-05-27   # ingest specific date
  python scripts/daily_ingest.py --no-purge    # skip purge step
  python scripts/daily_ingest.py --dry-run     # preview only, no writes
"""

import argparse
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Suppress ONNX/TensorRT noise
os.environ.setdefault("ORT_LOGGING_LEVEL", "3")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("ORT_TENSORRT_ENGINE_CACHE_ENABLE", "0")

# Import ReliefWeb config directly (avoid __init__.py which imports heavy deps)
import importlib.util

from config import config

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
# Ensure log directory exists (cron redirects to /var/log/sightline/)
_LOG_DIR = Path("/var/log/sightline")
try:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass  # May not have permissions — that's OK, cron will handle or skip

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("daily_ingest")

# ── Config ──────────────────────────────────────────────────────────────────
DB_PATH = str(config.DB_PATH)
CHROMA_DIR = str(config.CHROMA_DIR)
APPNAME = RELIEFWEB_APPNAME
PURGE_DAYS = 30
RELIEFWEB_API_URL = RELIEFWEB_REPORTS_API
PAGE_SIZE = 100  # max per request (ReliefWeb API limit)


def fetch_report_ids_for_date(target_date: str) -> list:
    """Fetch all report IDs from ReliefWeb API for a given date (YYYY-MM-DD).

    Returns a list of report IDs.
    """
    from reliefweb_api.reliefweb_utils import retry_request

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

        # Build URL with appname query param
        url = RELIEFWEB_API_URL
        if APPNAME:
            url = f"{RELIEFWEB_API_URL}?appname={APPNAME}"

        try:
            resp = retry_request(
                "post",
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
    from reliefweb_api.ingest_pipeline import ingest_from_api, is_ingested, is_ingested_with_pdf

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

    # Get old report IDs before purging (for ChromaDB cleanup)
    old_ids = db.get_old_report_ids(days=days)

    if not old_ids:
        log.info("No reports older than %d days to purge", days)
        return {"reports_purged": 0, "chunks_purged_chroma": 0}

    log.info("Found %d reports older than %d days to purge", len(old_ids), days)

    if dry_run:
        log.info("Dry run: would purge %d reports", len(old_ids))
        return {"reports_purged": len(old_ids), "chunks_purged_chroma": 0}

    # Purge from SQLite first (authoritative source)
    sqlite_purged = db.purge_old_reports(days=days)
    log.info("Purged %d reports from SQLite", sqlite_purged)

    # Then purge from ChromaDB (derived index)
    vs = VectorStore(CHROMA_DIR)
    chroma_removed = vs.purge_by_report_ids(old_ids)
    log.info("Purged %d chunks from ChromaDB", chroma_removed)

    return {
        "reports_purged": sqlite_purged,
        "chunks_purged_chroma": chroma_removed,
    }


def main():
    parser = argparse.ArgumentParser(description="Daily ReliefWeb report ingestion + purge")
    parser.add_argument("--date", help="Specific date to ingest (YYYY-MM-DD), default: yesterday")
    parser.add_argument("--no-purge", action="store_true", help="Skip the purge step")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    parser.add_argument("--purge-days", type=int, default=PURGE_DAYS, help="Purge threshold in days (default: 90)")
    args = parser.parse_args()

    # Determine target date
    if args.date:
        target_date = args.date
    else:
        yesterday = datetime.now(UTC) - timedelta(days=1)
        target_date = yesterday.strftime("%Y-%m-%d")

    log.info("=" * 60)
    log.info("Daily Ingest — %s", target_date)
    if args.dry_run:
        log.info("DRY RUN — no writes will be made")
    log.info("=" * 60)

    ingest_result = {"ingested": 0, "skipped": 0, "errors": 0}

    # Step 1: Fetch report IDs
    log.info("Fetching report IDs for %s...", target_date)
    report_ids = fetch_report_ids_for_date(target_date)
    log.info("Found %d reports for %s", len(report_ids), target_date)

    if not report_ids:
        log.info("No reports found. Nothing to ingest.")
    else:
        # Step 2: Ingest
        log.info("Ingesting %d reports...", len(report_ids))
        ingest_result = ingest_reports(report_ids, dry_run=args.dry_run)
        log.info(
            "Ingest complete: %d ingested, %d skipped, %d errors",
            ingest_result["ingested"],
            ingest_result["skipped"],
            ingest_result["errors"],
        )

    # Step 3: Purge old data
    purge_result = {"reports_purged": 0, "chunks_purged_chroma": 0}
    if not args.no_purge:
        log.info("Purging data older than %d days...", args.purge_days)
        purge_result = purge_old_data(days=args.purge_days, dry_run=args.dry_run)
        log.info(
            "Purge complete: %d reports removed from SQLite, %d chunks from ChromaDB",
            purge_result["reports_purged"],
            purge_result["chunks_purged_chroma"],
        )

    # Summary
    log.info("=" * 60)
    log.info("SUMMARY")
    log.info("  Date:          %s", target_date)
    log.info("  Fetched:       %d", len(report_ids))
    log.info("  Ingested:      %d", ingest_result.get("ingested", 0))
    log.info("  Skipped:       %d", ingest_result.get("skipped", 0))
    log.info("  Errors:        %d", ingest_result.get("errors", 0))
    log.info("  Purged (SQL):  %d", purge_result["reports_purged"])
    log.info("  Purged (Vec):  %d", purge_result["chunks_purged_chroma"])
    log.info("=" * 60)

    # Exit with error code if there were ingest errors
    if ingest_result.get("errors", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
