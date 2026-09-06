import sqlite3
from datetime import UTC, datetime

import pytest

from reliefweb_api.ingest_status import database_freshness, read_ingest_status, write_ingest_status


def _create_reports_db(path, report_date="2026-09-03"):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE reports (report_id INTEGER PRIMARY KEY, date TEXT, ingested_at TEXT)")
    conn.execute(
        "INSERT INTO reports VALUES (1, ?, '2026-09-04T06:00:00+00:00')",
        (report_date,),
    )
    conn.commit()
    conn.close()


def test_database_freshness_reports_current_snapshot(tmp_path):
    db_path = tmp_path / "reports.db"
    _create_reports_db(db_path)

    result = database_freshness(
        db_path=db_path,
        max_age_days=3,
        now=datetime(2026, 9, 5, tzinfo=UTC),
    )

    assert result["status"] == "fresh"
    assert result["is_fresh"] is True
    assert result["age_days"] == 2
    assert result["report_count"] == 1


def test_database_freshness_flags_stale_snapshot(tmp_path):
    db_path = tmp_path / "reports.db"
    _create_reports_db(db_path, report_date="2026-08-20")

    result = database_freshness(
        db_path=db_path,
        max_age_days=3,
        now=datetime(2026, 9, 5, tzinfo=UTC),
    )

    assert result["status"] == "stale"
    assert result["is_fresh"] is False
    assert result["age_days"] == 16


def test_ingest_status_round_trip(tmp_path):
    status_path = tmp_path / "ingest_status.json"
    payload = {"status": "completed", "target_date": "2026-09-04", "fetched": 12}

    write_ingest_status(payload, status_path)

    assert read_ingest_status(status_path) == payload


def test_missing_ingest_status_is_unknown(tmp_path):
    assert read_ingest_status(tmp_path / "missing.json") == {"status": "unknown"}


def test_reliefweb_listing_failure_is_not_treated_as_empty_day(monkeypatch):
    from reliefweb_api import reliefweb_utils
    from scripts.daily_ingest import fetch_report_ids_for_date

    def fail_request(*args, **kwargs):
        raise ConnectionError("offline")

    monkeypatch.setattr(reliefweb_utils, "retry_request", fail_request)

    with pytest.raises(RuntimeError, match="report listing failed"):
        fetch_report_ids_for_date("2026-09-04")
