"""Operational status helpers for the daily ReliefWeb ingestion pipeline."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def database_freshness(
    db_path: Path | str | None = None,
    max_age_days: int | None = None,
    now: datetime | None = None,
) -> dict:
    from config import DATA_FRESHNESS_MAX_AGE_DAYS, DB_PATH

    path = Path(db_path or DB_PATH)
    freshness_limit = max_age_days if max_age_days is not None else DATA_FRESHNESS_MAX_AGE_DAYS
    result = {
        "status": "unknown",
        "is_fresh": False,
        "latest_report_date": "",
        "latest_ingested_at": "",
        "age_days": None,
        "report_count": 0,
    }
    try:
        conn = sqlite3.connect(str(path))
        try:
            row = conn.execute(
                "SELECT MAX(SUBSTR(date, 1, 10)), MAX(ingested_at), COUNT(*) FROM reports"
            ).fetchone()
        finally:
            conn.close()
    except (OSError, sqlite3.Error):
        return result

    latest_date = str(row[0] or "") if row else ""
    result["latest_report_date"] = latest_date
    result["latest_ingested_at"] = str(row[1] or "") if row else ""
    result["report_count"] = int(row[2] or 0) if row else 0
    if not latest_date:
        return result
    try:
        latest = datetime.fromisoformat(latest_date).date()
        current = (now or datetime.now(UTC)).date()
        age_days = max(0, (current - latest).days)
    except ValueError:
        return result

    result["age_days"] = age_days
    result["is_fresh"] = age_days <= freshness_limit
    result["status"] = "fresh" if result["is_fresh"] else "stale"
    return result


def write_ingest_status(payload: dict, path: Path | str | None = None) -> None:
    from config import INGEST_STATUS_PATH

    target = Path(path or INGEST_STATUS_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)


def read_ingest_status(path: Path | str | None = None) -> dict:
    from config import INGEST_STATUS_PATH

    target = Path(path or INGEST_STATUS_PATH)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "unknown"}
    return data if isinstance(data, dict) else {"status": "unknown"}
