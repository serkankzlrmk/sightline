"""Tests for observability/error_tracking.py (errors.db)."""

import sqlite3
import time

import pytest


@pytest.fixture()
def errors_db(tmp_path, monkeypatch):
    import config
    from observability import error_tracking

    monkeypatch.setattr(config, "ERRORS_DB_PATH", tmp_path / "errors.db", raising=False)
    monkeypatch.setattr(config, "ERRORS_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "ERRORS_SALT", "test-salt", raising=False)
    monkeypatch.setattr(config, "ERRORS_RETENTION_DAYS", 30, raising=False)
    error_tracking.reset_for_tests()
    yield error_tracking
    error_tracking.reset_for_tests()


def test_sanitize_removes_secrets():
    from observability.error_tracking import sanitize_text

    raw = "Bearer abc.def.ghi email a@b.com token=secret123 nonce=deadbeef key=ABC123"
    clean = sanitize_text(raw)
    assert "abc.def" not in clean
    assert "a@b.com" not in clean
    assert "secret123" not in clean
    assert "deadbeef" not in clean
    assert "[email]" in clean
    assert "[redacted]" in clean


def test_fingerprint_normalizes_dynamic_paths():
    from observability.error_tracking import fingerprint, normalize_route

    assert normalize_route("/api/sitrep/report/12345") == "/api/sitrep/report/:n"
    stack = 'File "app.py", line 10, in handler'
    a = fingerprint("backend", "/api/reports/123", "ValueError", stack, "boom")
    b = fingerprint("backend", "/api/reports/456", "ValueError", stack, "boom")
    c = fingerprint("backend", "/api/other/123", "ValueError", stack, "boom")
    assert a == b
    assert a != c


def test_record_summary_groups_resolve(errors_db):
    from observability.error_tracking import groups, recent, record_error, resolve, summary

    assert record_error(
        kind="backend",
        route="/api/x",
        method="GET",
        status=500,
        request_id="rid1",
        uid="u1",
        exc_type="ValueError",
        message="boom secret=abc",
        stack='File "x.py", line 1, in f',
    )
    s = summary(days=1)
    assert s["errors"] == 1
    assert s["by_kind"]["backend"] == 1
    assert s["unresolved"] == 1
    fp = groups(days=1)[0]["fingerprint"]
    assert groups(days=1)[0]["count"] == 1
    assert recent(days=1)[0]["message"].startswith("boom")
    assert resolve(fp) is True
    assert summary(days=1)["unresolved"] == 0


def test_request_stats_are_buffered_and_flushed(errors_db):
    from observability.error_tracking import record_request, summary, window_stats

    record_request("/api/a", 200, 100)
    record_request("/api/a", 500, 300)
    s = summary(days=1)
    assert s["requests"] == 2
    assert s["errors_5xx"] == 1
    assert s["error_rate"] == 0.5
    w = window_stats(minutes=15)
    assert w["requests"] == 2


def test_tool_error_classification():
    from observability.error_tracking import classify_tool_error

    assert classify_tool_error("Error: MCP tool timed out after 120s") == "timeout"
    assert classify_tool_error("Error: 401 Unauthorized") == "auth"
    assert classify_tool_error("Error: 429 rate limit") == "rate_limit"
    assert classify_tool_error("Error: upstream 503") == "upstream_5xx"
    assert classify_tool_error("Error: no results found") == "empty"
    assert classify_tool_error("Error: invalid arguments") == "invalid_args"
    assert classify_tool_error("Error: something odd") == "unknown"


def test_prune_removes_old_errors(errors_db, monkeypatch):
    import config

    errors_db.record_error(kind="backend", route="/api/x", message="old")
    db_path = config.ERRORS_DB_PATH
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE error_events SET ts = ?", (time.time() - 10 * 86400,))
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "ERRORS_RETENTION_DAYS", 5, raising=False)
    assert errors_db.prune() == 1


def test_alert_cooldown(errors_db):
    from observability.error_tracking import alert_allowed

    assert alert_allowed("test-key", cooldown_seconds=60) is True
    assert alert_allowed("test-key", cooldown_seconds=60) is False
    assert alert_allowed("test-key", cooldown_seconds=0) is True
