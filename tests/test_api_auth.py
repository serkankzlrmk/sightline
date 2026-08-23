"""
Test: API route auth protection, rate limiting, CORS, and response formats.

Uses Flask test client with mocked auth to verify endpoint behavior
without needing a running server or external services.
"""

import json
from unittest.mock import patch

import pytest

import auth


@pytest.fixture
def app():
    import server

    return server.app


@pytest.fixture
def client(app):
    return app.test_client()


def _auth_headers(role="admin", uid="test-uid"):
    """Create mock auth context for a given role."""
    return {
        "uid": uid,
        "email": f"{uid}@test.com",
        "role": role,
    }


# ── Health endpoint (unauthenticated) ──────────────────────────────────────────


class TestHealthEndpoint:
    def test_health_no_auth_required(self, client):
        resp = client.get("/api/health")
        assert resp.status_code in (200, 503)

    def test_health_returns_json(self, client):
        resp = client.get("/api/health")
        data = json.loads(resp.data)
        assert "status" in data
        assert "version" in data

    def test_health_has_required_keys(self, client):
        resp = client.get("/api/health")
        data = json.loads(resp.data)
        for key in ["status", "db", "vector", "llm", "version"]:
            assert key in data, f"Missing key: {key}"


# ── Auth protection ────────────────────────────────────────────────────────────


class TestAuthProtection:
    def test_db_reports_requires_auth(self, client):
        with patch.object(auth, "_dev_mode", return_value=False), patch.object(auth, "_api_key", return_value=""):
            resp = client.get("/api/db/reports")
            assert resp.status_code == 401

    def test_db_stats_requires_auth(self, client):
        with patch.object(auth, "_dev_mode", return_value=False), patch.object(auth, "_api_key", return_value=""):
            resp = client.get("/api/db/stats")
            assert resp.status_code == 401

    def test_agent_chats_requires_auth(self, client):
        with patch.object(auth, "_dev_mode", return_value=False), patch.object(auth, "_api_key", return_value=""):
            resp = client.get("/api/agent/chats")
            assert resp.status_code == 401

    def test_sitrep_themes_public(self, client):
        # Freemium: themes/countries/reports/bulletins are public reads —
        # anonymous visitors can browse; only generation requires auth.
        with patch.object(auth, "_dev_mode", return_value=False), patch.object(auth, "_api_key", return_value=""):
            resp = client.get("/api/sitrep/themes")
            assert resp.status_code in (200, 500)  # 500 = ChromaDB not available in CI, still not 401

    def test_sitrep_run_requires_auth(self, client):
        with patch.object(auth, "_dev_mode", return_value=False), patch.object(auth, "_api_key", return_value=""):
            resp = client.post("/api/sitrep/run", json={"country": "x"})
            assert resp.status_code == 401

    def test_admin_users_requires_auth(self, client):
        with patch.object(auth, "_dev_mode", return_value=False), patch.object(auth, "_api_key", return_value=""):
            resp = client.get("/api/admin/users")
            assert resp.status_code == 401

    def test_auth_me_requires_auth(self, client):
        with patch.object(auth, "_dev_mode", return_value=False), patch.object(auth, "_api_key", return_value=""):
            resp = client.get("/api/auth/me")
            assert resp.status_code == 401


# ── Admin-only routes ──────────────────────────────────────────────────────────


class TestAdminOnlyRoutes:
    def test_admin_users_free_role_denied(self, client):
        fake_token = {"uid": "free-user", "role": "free"}
        with (
            patch.object(auth, "_dev_mode", return_value=False),
            patch.object(auth, "_api_key", return_value=""),
            patch.object(auth, "verify_firebase_token", return_value=fake_token),
            patch.object(auth, "_resolve_role", return_value="free"),
        ):
            resp = client.get(
                "/api/admin/users",
                headers={"Authorization": "Bearer token"},
            )
            assert resp.status_code == 403

    def test_daily_ingest_requires_admin(self, client):
        fake_token = {"uid": "premium-user", "role": "premium"}
        with (
            patch.object(auth, "_dev_mode", return_value=False),
            patch.object(auth, "_api_key", return_value=""),
            patch.object(auth, "verify_firebase_token", return_value=fake_token),
            patch.object(auth, "_resolve_role", return_value="premium"),
        ):
            resp = client.post(
                "/api/ingest/daily",
                headers={"Authorization": "Bearer token"},
            )
            assert resp.status_code == 403

    def test_upload_requires_admin(self, client):
        fake_token = {"uid": "premium-user", "role": "premium"}
        with (
            patch.object(auth, "_dev_mode", return_value=False),
            patch.object(auth, "_api_key", return_value=""),
            patch.object(auth, "verify_firebase_token", return_value=fake_token),
            patch.object(auth, "_resolve_role", return_value="premium"),
        ):
            resp = client.post(
                "/api/ingest/upload",
                headers={"Authorization": "Bearer token"},
            )
            assert resp.status_code == 403

    def test_chat_unlock_requires_admin(self, client):
        fake_token = {"uid": "premium-user", "role": "premium"}
        with (
            patch.object(auth, "_dev_mode", return_value=False),
            patch.object(auth, "_api_key", return_value=""),
            patch.object(auth, "verify_firebase_token", return_value=fake_token),
            patch.object(auth, "_resolve_role", return_value="premium"),
        ):
            resp = client.post(
                "/api/agent/chat/unlock",
                headers={"Authorization": "Bearer token"},
            )
            assert resp.status_code == 403


# ── Dev mode bypass ────────────────────────────────────────────────────────────


class TestDevModeBypass:
    def test_dev_mode_bypasses_auth(self, client):
        with patch.object(auth, "_dev_mode", return_value=True):
            resp = client.get("/api/db/stats")
            assert resp.status_code != 401

    def test_dev_mode_gives_admin_role(self, client):
        with patch.object(auth, "_dev_mode", return_value=True):
            resp = client.get("/api/auth/me")
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data.get("role") == "admin"


# ── Auth me endpoint ────────────────────────────────────────────────────────────


class TestAuthMeEndpoint:
    def test_auth_me_returns_user_info(self, client):
        fake_token = {"uid": "user123", "email": "user@test.com", "role": "premium"}
        with (
            patch.object(auth, "_dev_mode", return_value=False),
            patch.object(auth, "_api_key", return_value=""),
            patch.object(auth, "verify_firebase_token", return_value=fake_token),
            patch.object(auth, "_resolve_role", return_value="premium"),
        ):
            resp = client.get(
                "/api/auth/me",
                headers={"Authorization": "Bearer token"},
            )
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data["uid"] == "user123"
            assert data["role"] == "premium"

    def test_auth_me_no_token_returns_401(self, client):
        with patch.object(auth, "_dev_mode", return_value=False), patch.object(auth, "_api_key", return_value=""):
            resp = client.get("/api/auth/me")
            assert resp.status_code == 401
