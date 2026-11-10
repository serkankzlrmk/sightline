"""Tests for admin audit logging."""

import pytest


@pytest.fixture()
def audit_env(tmp_path, monkeypatch):
    import blueprints.helpers as helpers
    import config
    from observability import error_tracking

    chats_path = tmp_path / "chats.db"
    monkeypatch.setattr(config, "CHATS_DB_PATH", chats_path, raising=False)
    monkeypatch.setattr(helpers, "CHATS_DB_PATH", chats_path, raising=False)
    monkeypatch.setattr(helpers, "_chats_schema_ready", False, raising=False)
    error_tracking.reset_for_tests()
    yield
    error_tracking.reset_for_tests()


def test_log_audit_emits_audit_event(monkeypatch):
    import blueprints.helpers as helpers

    calls = []
    monkeypatch.setattr(
        helpers, "log_event", lambda uid, event, props=None, session="": calls.append((uid, event, props))
    )
    helpers.log_audit("admin-1", "role_changed", "user-1", {"new_role": "premium"})
    assert calls[0][0] == "admin-1"
    assert calls[0][1] == "audit:role_changed"
    assert calls[0][2] == {"target": "user-1", "new_role": "premium"}


def test_admin_audit_endpoint(audit_env):
    import server
    from blueprints.helpers import log_audit

    log_audit("dev-local", "config_updated", "env", {"keys": ["ACTIVE_MODEL"]})
    client = server.app.test_client()
    resp = client.get("/api/admin/audit?days=30")
    assert resp.status_code == 200
    events = resp.get_json()["events"]
    assert any(e["action"] == "config_updated" for e in events)
