import json
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime

import pytest

import config
from sitrep.chroma_adapter import ChromaAdapter
from sitrep.country_summary import _aggregate_report_evidence, _data_freshness


@pytest.fixture()
def country_db(tmp_path, monkeypatch):
    db_path = tmp_path / "country_quality.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE reports (
            report_id INTEGER PRIMARY KEY,
            title TEXT,
            date TEXT,
            source TEXT,
            url TEXT,
            countries TEXT,
            themes TEXT
        );
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER,
            chunk_index INTEGER,
            content TEXT
        );
        """
    )
    reports = [
        (1, "Sudan response update", "2026-01-10", "Source A", "https://example.org/1", ["Sudan"], ["Health"]),
        (2, "Regional response update", "2026-03-10", "Source B", "https://example.org/2", ["Jordan", "Sudan"], ["Food and Nutrition"]),
        (3, "Sudan situation report", "2026-02-10", "Source A", "https://example.org/3", ["Sudan"], ["Health"]),
        (4, "South Sudan update", "2026-04-10", "Source C", "https://example.org/4", ["South Sudan"], ["Protection"]),
    ]
    for report_id, title, date, source, url, countries, themes in reports:
        conn.execute(
            "INSERT INTO reports VALUES (?, ?, ?, ?, ?, ?, ?)",
            (report_id, title, date, source, url, json.dumps(countries), json.dumps(themes)),
        )
        conn.execute(
            "INSERT INTO chunks (report_id, chunk_index, content) VALUES (?, 0, ?)",
            (report_id, f"content-{report_id}-0"),
        )
    conn.execute(
        "INSERT INTO chunks (report_id, chunk_index, content) VALUES (1, 1, 'content-1-1')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", db_path)

    adapter = ChromaAdapter.__new__(ChromaAdapter)
    adapter.backend = "chromadb"
    adapter._countries_cache = None
    adapter._countries_with_counts_cache = None
    return adapter


def test_country_chunks_are_newest_first_and_keep_relevance(country_db):
    chunks = country_db.get_chunks_by_country("Sudan", limit=10)

    assert [chunk["report_id"] for chunk in chunks] == [2, 3, 1, 1]
    assert chunks[0]["country_relevance"] == "mentioned"
    assert chunks[1]["country_relevance"] == "primary"
    assert all(chunk["report_id"] != 4 for chunk in chunks)

    reports = country_db.get_reports_by_country("Sudan", limit=10)
    assert [report["report_id"] for report in reports] == [2, 3, 1]


def test_date_range_has_canonical_and_legacy_keys(country_db):
    result = country_db.get_date_range("Sudan")

    assert result["min"] == result["min_date"] == "2026-01-10"
    assert result["max"] == result["max_date"] == "2026-03-10"
    assert result["count"] == 3
    assert result["primary_count"] == 2
    assert result["mentioned_count"] == 1


def test_report_evidence_counts_each_report_once(country_db):
    rows = country_db.get_reports_by_country("Sudan", limit=10)
    rows.append(dict(rows[-1], id="duplicate-chunk"))
    evidence = _aggregate_report_evidence(rows)

    assert evidence["evidence_report_count"] == 3
    assert evidence["top_sources"] == [{"name": "Source A", "count": 2}]
    assert [report["title"] for report in evidence["recent_reports"]] == [
        "Sudan situation report",
        "Sudan response update",
        "Regional response update",
    ]
    assert evidence["recent_reports"][-1]["country_relevance"] == "mentioned"


def test_data_freshness_buckets_are_deterministic():
    now = datetime(2026, 9, 5, tzinfo=UTC)

    assert _data_freshness("2026-09-02", now)["status"] == "active"
    assert _data_freshness("2026-08-15", now)["status"] == "current"
    assert _data_freshness("2026-07-01", now)["status"] == "aging"
    assert _data_freshness("2026-01-01", now)["status"] == "stale"
    assert _data_freshness("", now)["status"] == "unknown"


def test_crisis_publication_requires_traceable_country_evidence():
    from blueprints.seo_bp import _is_crisis_publishable

    entry = {
        "report_count": 5,
        "primary_report_count": 2,
        "recent_reports": [{"title": "Report", "url": "https://example.org/report"}],
        "top_sources": [{"name": "Source", "count": 2}],
        "gdacs_alerts": [],
    }
    assert _is_crisis_publishable(entry)

    no_link = deepcopy(entry)
    no_link["recent_reports"][0]["url"] = ""
    assert not _is_crisis_publishable(no_link)

    no_primary_evidence = deepcopy(entry)
    no_primary_evidence["primary_report_count"] = 0
    assert not _is_crisis_publishable(no_primary_evidence)

    live_alert = deepcopy(no_link)
    live_alert["gdacs_alerts"] = [{"alert_level": "red"}]
    assert _is_crisis_publishable(live_alert)


def test_crisis_lastmod_uses_source_coverage_date():
    from blueprints.seo_bp import _crisis_entry_lastmod

    entry = {
        "data_freshness": {"coverage_through": "2026-08-31"},
        "date_range": {"max_date": "2026-08-29"},
        "last_updated": "2026-09-05T12:00:00+00:00",
    }
    assert _crisis_entry_lastmod(entry) == "2026-08-31"
