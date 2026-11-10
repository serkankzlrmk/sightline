"""Tests for request IDs, global error handlers, client errors and admin API."""

import pytest

# Register the throwaway 500 route before Flask handles its first request.
import server as _server


def _boom_route():
    raise RuntimeError("kaboom-test")


_server.app.add_url_rule("/api/__boom_test", "boom_test", _boom_route)


@pytest.fixture()
def error_env(tmp_path, monkeypatch):
    import config
    from observability import error_tracking

    monkeypatch.setattr(config, "ERRORS_DB_PATH", tmp_path / "errors.db", raising=False)
    monkeypatch.setattr(config, "ERRORS_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "ERRORS_SALT", "test-salt", raising=False)
    error_tracking.reset_for_tests()
    yield error_tracking
    error_tracking.reset_for_tests()


def test_404_api_returns_request_id(error_env):
    import server

    client = server.app.test_client()
    resp = client.get("/api/definitely-missing")
    assert resp.status_code == 404
    assert resp.headers.get("X-Request-ID")
    body = resp.get_json()
    assert body["request_id"] == resp.headers["X-Request-ID"]
    assert body["code"].startswith("ERR-")


def test_uncaught_500_is_recorded(error_env):
    import server

    client = server.app.test_client()
    resp = client.get("/api/__boom_test")
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["request_id"]
    groups = error_env.groups(days=1)
    assert groups
    assert groups[0]["kind"] == "backend"
    assert "kaboom-test" in groups[0]["sample_message"]


def test_client_error_ingestion(error_env):
    import server

    client = server.app.test_client()
    resp = client.post(
        "/api/client-errors",
        json={
            "message": "TypeError: cannot read x",
            "stack": "at App (app.js:10:2)",
            "source": "/static/dist/app.js",
            "lineno": 10,
            "kind": "frontend",
        },
    )
    assert resp.status_code == 202
    groups = error_env.groups(days=1, kind="frontend")
    assert groups
    assert groups[0]["kind"] == "frontend"


def test_admin_error_api_and_resolve(error_env):
    import server

    client = server.app.test_client()
    error_env.record_error(kind="backend", route="/api/x", status=500, message="admin-visible")

    summary = client.get("/api/admin/errors/summary?days=7")
    assert summary.status_code == 200
    assert summary.get_json()["errors"] >= 1

    groups = client.get("/api/admin/errors/groups?days=7").get_json()["groups"]
    assert groups
    fp = groups[0]["fingerprint"]

    detail = client.get(f"/api/admin/errors/{fp}")
    assert detail.status_code == 200
    assert detail.get_json()["events"]

    resolved = client.post(f"/api/admin/errors/{fp}/resolve", json={"resolved": True})
    assert resolved.status_code == 200
    assert resolved.get_json()["ok"] is True

    test = client.post("/api/admin/errors/test")
    assert test.status_code == 200
