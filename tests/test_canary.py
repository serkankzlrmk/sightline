"""Tests for scripts/canary.py."""

import pytest


@pytest.fixture()
def errors_env(tmp_path, monkeypatch):
    import config
    from observability import error_tracking

    monkeypatch.setattr(config, "ERRORS_DB_PATH", tmp_path / "errors.db", raising=False)
    monkeypatch.setattr(config, "ERRORS_ENABLED", True, raising=False)
    error_tracking.reset_for_tests()
    yield error_tracking
    error_tracking.reset_for_tests()


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_canary_success(errors_env, monkeypatch):
    import scripts.canary as canary

    def fake_get(url, timeout=0):
        if url.endswith("/api/health"):
            return FakeResponse(200, {"status": "ok", "release": "abc"})
        return FakeResponse(200)

    monkeypatch.setattr(canary.requests, "get", fake_get)
    report = canary.run("http://example.test", alert=False)
    assert report["ok"] is True
    assert report["failures"] == 0
    assert errors_env.summary(days=1)["errors"] == 0


def test_canary_failure_is_recorded(errors_env, monkeypatch):
    import scripts.canary as canary

    def fake_get(url, timeout=0):
        if url.endswith("/api/health"):
            return FakeResponse(503, {"status": "degraded"})
        return FakeResponse(200)

    monkeypatch.setattr(canary.requests, "get", fake_get)
    report = canary.run("http://example.test", alert=False)
    assert report["ok"] is False
    groups = errors_env.groups(days=1, kind="canary")
    assert groups and groups[0]["kind"] == "canary"
