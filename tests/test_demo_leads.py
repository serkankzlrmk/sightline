"""Tests for the public /demo sample and consent-based lead capture."""

import pytest


@pytest.fixture()
def lead_env(tmp_path, monkeypatch):
    import growth.leads as leads

    monkeypatch.setattr(leads, "GSC_DB_PATH", tmp_path / "growth.db")
    return leads


def test_demo_page_is_public():
    import server

    client = server.app.test_client()
    r = client.get("/demo")
    assert r.status_code == 200
    assert b"Lead" in r.data or b"live" in r.data.lower()


def test_lead_capture_and_admin_list(lead_env):
    import server

    client = server.app.test_client()
    r = client.post(
        "/api/leads",
        json={"email": "Tester@Example.org", "consent": True, "source": "demo", "utm_source": "linkedin"},
    )
    assert r.status_code == 200
    assert lead_env.count_leads() == 1

    r = client.post("/api/leads", json={"email": "not-an-email", "consent": True})
    assert r.status_code == 400

    r = client.post("/api/leads", json={"email": "no-consent@example.org", "consent": False})
    assert r.status_code == 400

    r = client.get("/api/admin/growth/leads")
    assert r.status_code == 200
    data = r.get_json()
    assert data["count"] == 1
    assert data["leads"][0]["email"] == "tester@example.org"
    assert data["leads"][0]["source"] == "demo"


def test_lead_honeypot_is_silent(lead_env):
    import server

    client = server.app.test_client()
    r = client.post("/api/leads", json={"email": "bot@example.org", "consent": True, "website": "spam"})
    assert r.status_code == 200
    assert lead_env.count_leads() == 0


def test_growth_funnel_and_lead_csv(lead_env):
    import server

    client = server.app.test_client()
    client.post(
        "/api/leads",
        json={"email": "funnel@example.org", "consent": True, "source": "demo", "utm_source": "test"},
    )
    r = client.get("/api/admin/growth/funnel?days=30")
    assert r.status_code == 200
    data = r.get_json()
    assert data["leads"] == 1
    assert data["sources"][0]["source"] == "demo"
    assert "demo_views" in data and "guest_messages" in data

    r = client.get("/api/admin/growth/leads.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["Content-Type"]
    assert "funnel@example.org" in r.get_data(as_text=True)
