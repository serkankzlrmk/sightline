"""Tests for the anonymous guest chat preview."""

import pytest


@pytest.fixture()
def guest_env(tmp_path, monkeypatch):
    import blueprints.helpers as helpers
    import config
    from blueprints import guest

    chats = tmp_path / "chats.db"
    monkeypatch.setattr(config, "CHATS_DB_PATH", chats, raising=False)
    monkeypatch.setattr(helpers, "CHATS_DB_PATH", chats, raising=False)
    monkeypatch.setattr(helpers, "_chats_schema_ready", False, raising=False)
    return guest


def _ctx():
    from flask import Flask

    app = Flask(__name__)
    return app.test_request_context(environ_base={"REMOTE_ADDR": "203.0.113.9"})


def test_guest_cookie_and_quota(guest_env):
    guest = guest_env
    with _ctx():
        gid, is_new = guest.get_guest_id()
        assert is_new and len(gid) >= 24
        assert guest.status(gid)["remaining"] == 3
        for expected in (2, 1, 0):
            result = guest.consume(gid)
            assert result["allowed"] is True
            assert result["remaining"] == expected
        blocked = guest.consume(gid)
        assert blocked["allowed"] is False
        assert blocked["login_required"] is True


def test_guest_ip_daily_limit(guest_env, monkeypatch):
    guest = guest_env
    monkeypatch.setattr(guest, "GUEST_IP_DAILY_LIMIT", 2)
    with _ctx():
        first, _ = guest.get_guest_id()
        assert guest.consume(first)["allowed"] is True
        assert guest.consume(first)["allowed"] is True
        assert guest.consume(first)["allowed"] is False


def test_guest_status_endpoint(guest_env, monkeypatch):
    import auth
    import server

    monkeypatch.setattr(auth, "_dev_mode", lambda: False)
    client = server.app.test_client()
    resp = client.get("/api/agent/guest")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["guest"] is True
    assert data["limit"] == 3
    assert data["remaining"] == 3
    assert resp.headers.get("Set-Cookie", "").startswith("sightline_guest=")


def test_guest_chat_rejects_after_three(guest_env, monkeypatch):
    import auth
    import server

    monkeypatch.setattr(auth, "_dev_mode", lambda: False)
    gid = "a" * 32
    with _ctx():
        for _ in range(3):
            assert guest_env.consume(gid)["allowed"] is True
    client = server.app.test_client()
    client.set_cookie("sightline_guest", gid)
    resp = client.post("/api/agent/chat", json={"message": "hello"})
    assert resp.status_code == 401
    assert resp.get_json()["login_required"] is True
