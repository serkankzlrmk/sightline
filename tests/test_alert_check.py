"""Tests for scripts/alert_check.py (thresholds, cooldown, delivery)."""

import pytest


@pytest.fixture()
def alert_env(tmp_path, monkeypatch):
    import config
    from observability import error_tracking

    monkeypatch.setattr(config, "ERRORS_DB_PATH", tmp_path / "errors.db", raising=False)
    monkeypatch.setattr(config, "ERRORS_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "ERRORS_SALT", "test-salt", raising=False)
    monkeypatch.setattr(config, "ALERT_WEBHOOK_URL", "https://example.test/hook", raising=False)
    monkeypatch.setattr(config, "ALERT_TELEGRAM_BOT_TOKEN", "", raising=False)
    monkeypatch.setattr(config, "ALERT_TELEGRAM_CHAT_ID", "", raising=False)
    monkeypatch.setattr(config, "ALERT_MIN_REQUESTS", 5, raising=False)
    monkeypatch.setattr(config, "ALERT_5XX_RATE", 0.02, raising=False)
    monkeypatch.setattr(config, "ALERT_TOOL_ERROR_RATE", 0.10, raising=False)
    monkeypatch.setattr(config, "ALERT_COOLDOWN_MIN", 30, raising=False)
    error_tracking.reset_for_tests()
    yield error_tracking
    error_tracking.reset_for_tests()


def test_evaluate_thresholds():
    from scripts.alert_check import evaluate

    alerts = evaluate(
        {"requests": 100, "error_rate": 0.05, "tool_calls": 100, "tool_error_rate": 0.2},
        {"checked": False},
        min_requests=20,
        error_rate=0.02,
        tool_rate=0.10,
    )
    assert {a["key"] for a in alerts} == {"5xx_rate", "tool_error_rate"}

    none = evaluate(
        {"requests": 100, "error_rate": 0.01, "tool_calls": 100, "tool_error_rate": 0.01},
        {"checked": False},
        min_requests=20,
        error_rate=0.02,
        tool_rate=0.10,
    )
    assert none == []


def test_cost_thresholds():
    from scripts.alert_check import evaluate

    alerts = evaluate(
        {
            "requests": 10,
            "error_rate": 0.0,
            "tool_calls": 0,
            "tool_error_rate": 0.0,
            "daily_cost": 30.0,
            "top_user_cost": 7.0,
            "top_user_uid": "u1",
        },
        {"checked": False},
        min_requests=100,
        error_rate=0.02,
        tool_rate=0.10,
        daily_cost_limit=25.0,
        user_cost_limit=5.0,
    )
    assert {a["key"] for a in alerts} == {"daily_cost", "user_daily_cost"}


def test_dry_run_does_not_send(alert_env, monkeypatch):
    import scripts.alert_check as ac

    monkeypatch.setattr(
        ac,
        "collect_metrics",
        lambda minutes=15: {
            "window_minutes": 15,
            "requests": 100,
            "errors": 10,
            "error_rate": 0.1,
            "tool_calls": 0,
            "tool_errors": 0,
            "tool_error_rate": 0.0,
        },
    )
    monkeypatch.setattr(ac, "check_health", lambda url: {"checked": False})
    report = ac.run(dry_run=True)
    assert report["alerts"]
    assert report["delivery"]["skipped"] is True


def test_webhook_and_cooldown(alert_env, monkeypatch):
    import scripts.alert_check as ac

    monkeypatch.setattr(
        ac,
        "collect_metrics",
        lambda minutes=15: {
            "window_minutes": 15,
            "requests": 100,
            "errors": 10,
            "error_rate": 0.1,
            "tool_calls": 0,
            "tool_errors": 0,
            "tool_error_rate": 0.0,
        },
    )
    monkeypatch.setattr(ac, "check_health", lambda url: {"checked": False})
    sent = []

    class FakeResponse:
        status_code = 200

    monkeypatch.setattr(ac.requests, "post", lambda url, **kw: sent.append((url, kw)) or FakeResponse())
    first = ac.run(dry_run=False)
    assert first["alerts"]
    assert sent and sent[0][0] == "https://example.test/hook"

    second = ac.run(dry_run=False)
    assert second["alerts"] == []
    assert second["suppressed"] >= 1


def test_test_message(alert_env, monkeypatch):
    import scripts.alert_check as ac

    sent = []

    class FakeResponse:
        status_code = 200

    monkeypatch.setattr(ac.requests, "post", lambda url, **kw: sent.append(url) or FakeResponse())
    report = ac.run(test=True)
    assert report["test"] is True
    assert sent
