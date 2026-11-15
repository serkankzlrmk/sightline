"""Tests for double opt-in newsletter flow (Brevo calls are mocked)."""

import pytest


@pytest.fixture()
def nl(tmp_path, monkeypatch):
    import growth.newsletter as newsletter

    monkeypatch.setattr(newsletter, "GSC_DB_PATH", tmp_path / "growth.db")
    monkeypatch.setattr(newsletter, "configured", lambda: True)
    monkeypatch.setattr(newsletter, "send_confirmation", lambda *a, **k: True)
    monkeypatch.setattr(newsletter, "add_brevo_contact", lambda *a, **k: True)
    monkeypatch.setattr(newsletter, "remove_brevo_contact", lambda *a, **k: True)
    return newsletter


def test_double_opt_in_flow(nl):
    result = nl.signup("Reader@Example.org", name="Reader", source="landing_footer")
    assert result["status"] == "pending"
    assert nl.counts()["pending"] == 1

    confirmed = nl.confirm(result["token"])
    assert confirmed and confirmed["email"] == "reader@example.org"
    assert nl.counts()["confirmed"] == 1

    unsub = nl.unsubscribe(result["token"])
    assert unsub and nl.counts()["unsubscribed"] == 1
    assert nl.list_confirmed() == []


def test_public_signup_and_confirm_page(nl, monkeypatch):
    import blueprints.public_bp as public_bp

    monkeypatch.setattr(public_bp, "_lead_allowed", lambda ip: True)
    import server

    client = server.app.test_client()
    r = client.post(
        "/api/newsletter/signup",
        json={"email": "public@example.org", "consent": True, "source": "landing_footer"},
    )
    assert r.status_code == 200
    assert r.get_json()["confirmation_required"] is True

    token = nl.signup("public@example.org")["token"]
    r = client.get(f"/newsletter/confirm/{token}")
    assert r.status_code == 200
    assert b"You are in" in r.data


def test_signup_requires_consent(nl, monkeypatch):
    import server
    import blueprints.public_bp as public_bp

    monkeypatch.setattr(public_bp, "_lead_allowed", lambda ip: True)

    client = server.app.test_client()
    r = client.post("/api/newsletter/signup", json={"email": "no@example.org", "consent": False})
    assert r.status_code == 400
