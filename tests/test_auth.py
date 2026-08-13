"""
Test: Authentication and role management.

Covers ROLE_HIERARCHY, _resolve_role, _role_rank, _dev_mode,
require_auth, require_admin, require_role, current_uid, current_role,
verify_firebase_token (mocked), set_user_role / get_user_role (mocked).
"""

import os
from unittest.mock import MagicMock, patch

import pytest

import auth

# ── Role hierarchy ─────────────────────────────────────────────────────────────


class TestRoleHierarchy:
    def test_hierarchy_order(self):
        assert auth.ROLE_HIERARCHY == ["free", "premium", "admin"]

    def test_role_rank_known_roles(self):
        assert auth._role_rank("free") == 0
        assert auth._role_rank("premium") == 1
        assert auth._role_rank("admin") == 2

    def test_role_rank_unknown_defaults_to_free(self):
        assert auth._role_rank("superuser") == 0
        assert auth._role_rank("") == 0


# ── _resolve_role ──────────────────────────────────────────────────────────────


class TestResolveRole:
    def test_custom_claim_admin(self):
        token = {"uid": "abc123", "role": "admin"}
        assert auth._resolve_role(token) == "admin"

    def test_custom_claim_premium(self):
        token = {"uid": "abc123", "role": "premium"}
        assert auth._resolve_role(token) == "premium"

    def test_custom_claim_free(self):
        token = {"uid": "abc123", "role": "free"}
        assert auth._resolve_role(token) == "free"

    def test_no_custom_claim_admin_uids_fallback(self):
        with patch.object(auth, "_admins", return_value={"admin_uid_1"}):
            token = {"uid": "admin_uid_1"}
            assert auth._resolve_role(token) == "admin"

    def test_no_custom_claim_no_match_defaults_free(self):
        with patch.object(auth, "_admins", return_value=set()):
            token = {"uid": "unknown_uid"}
            assert auth._resolve_role(token) == "free"

    def test_invalid_custom_claim_falls_back(self):
        with patch.object(auth, "_admins", return_value=set()):
            token = {"uid": "abc123", "role": "superuser"}
            assert auth._resolve_role(token) == "free"

    def test_admin_uid_allowlist_overrides_lower_privilege_claim(self):
        with patch.object(auth, "_admins", return_value={"abc123"}):
            token = {"uid": "abc123", "role": "premium"}
            assert auth._resolve_role(token) == "admin"


# ── _dev_mode ──────────────────────────────────────────────────────────────────


class TestDevMode:
    def test_dev_auth_bypass_true(self):
        # Dev bypass requires loopback SERVER_HOST (safety: no auth bypass on 0.0.0.0)
        with patch.dict(os.environ, {"DEV_AUTH_BYPASS": "true", "SERVER_HOST": "127.0.0.1"}):
            assert auth._dev_mode() is True

    def test_dev_auth_bypass_false(self):
        env = {"DEV_AUTH_BYPASS": "false", "SERVER_DEBUG": "false"}
        with patch.dict(os.environ, env, clear=False):
            assert auth._dev_mode() is False

    def test_dev_auth_bypass_non_loopback_blocked(self):
        # Dev bypass must NOT work on 0.0.0.0 (public-facing)
        with patch.dict(os.environ, {"DEV_AUTH_BYPASS": "true", "SERVER_HOST": "0.0.0.0"}):
            assert auth._dev_mode() is False

    def test_dev_mode_server_debug_no_firebase_no_apikey(self):
        env = {"SERVER_DEBUG": "true", "DEV_AUTH_BYPASS": "", "SERVER_HOST": "127.0.0.1"}
        with patch.dict(os.environ, env, clear=False):
            with (
                patch.object(auth, "_api_key", return_value=""),
                patch.object(auth, "_firebase_app", return_value=None),
            ):
                assert auth._dev_mode() is True

    def test_dev_mode_server_debug_with_apikey(self):
        env = {"SERVER_DEBUG": "true", "DEV_AUTH_BYPASS": "", "SERVER_HOST": "127.0.0.1"}
        with patch.dict(os.environ, env, clear=False):
            with patch.object(auth, "_api_key", return_value="some-key"):
                assert auth._dev_mode() is False

    def test_dev_mode_server_debug_with_firebase(self):
        env = {"SERVER_DEBUG": "true", "DEV_AUTH_BYPASS": "", "SERVER_HOST": "127.0.0.1"}
        with patch.dict(os.environ, env, clear=False):
            with (
                patch.object(auth, "_api_key", return_value=""),
                patch.object(auth, "_firebase_app", return_value=MagicMock()),
            ):
                assert auth._dev_mode() is False


# ── _admins ────────────────────────────────────────────────────────────────────


class TestAdmins:
    def test_empty_env(self):
        with patch.dict(os.environ, {"ADMIN_UIDS": ""}, clear=False):
            result = auth._admins()
            assert result == set()

    def test_single_uid(self):
        with patch.dict(os.environ, {"ADMIN_UIDS": "uid123"}, clear=False):
            assert auth._admins() == {"uid123"}

    def test_multiple_uids(self):
        with patch.dict(os.environ, {"ADMIN_UIDS": "uid1,uid2,uid3"}, clear=False):
            assert auth._admins() == {"uid1", "uid2", "uid3"}

    def test_whitespace_handling(self):
        with patch.dict(os.environ, {"ADMIN_UIDS": " uid1 , uid2 "}, clear=False):
            assert auth._admins() == {"uid1", "uid2"}


# ── current_uid / current_role ─────────────────────────────────────────────────


class TestHelpers:
    def test_current_uid_with_user(self):
        from flask import Flask, g

        app = Flask(__name__)
        with app.app_context():
            g.current_user = {"uid": "test-uid", "role": "admin"}
            assert auth.current_uid() == "test-uid"

    def test_current_uid_no_user(self):
        from flask import Flask

        app = Flask(__name__)
        with app.app_context():
            assert auth.current_uid() == ""

    def test_current_role_with_user(self):
        from flask import Flask, g

        app = Flask(__name__)
        with app.app_context():
            g.current_user = {"uid": "test-uid", "role": "premium"}
            assert auth.current_role() == "premium"

    def test_current_role_no_user(self):
        from flask import Flask

        app = Flask(__name__)
        with app.app_context():
            assert auth.current_role() == "free"


# ── Decorators with Flask test client ───────────────────────────────────────────


class TestRequireAuth:
    @pytest.fixture(autouse=True)
    def setup_app(self):
        self.app = __import__("server").app
        self.client = self.app.test_client()

    def test_no_token_returns_401(self):
        with patch.object(auth, "_dev_mode", return_value=False), patch.object(auth, "_api_key", return_value=""):
            resp = self.client.get("/api/agent/chats")
            assert resp.status_code == 401

    def test_empty_bearer_returns_401(self):
        with patch.object(auth, "_dev_mode", return_value=False), patch.object(auth, "_api_key", return_value=""):
            resp = self.client.get(
                "/api/agent/chats",
                headers={"Authorization": "Bearer "},
            )
            assert resp.status_code == 401

    def test_invalid_token_returns_401(self):
        with (
            patch.object(auth, "_dev_mode", return_value=False),
            patch.object(auth, "_api_key", return_value=""),
            patch.object(auth, "verify_firebase_token", side_effect=ValueError("Invalid token")),
        ):
            resp = self.client.get(
                "/api/agent/chats",
                headers={"Authorization": "Bearer invalid-token"},
            )
            assert resp.status_code == 401

    def test_valid_token_passes_auth(self):
        fake_token = {
            "uid": "user123",
            "email": "user@test.com",
            "role": "free",
        }
        with (
            patch.object(auth, "_dev_mode", return_value=False),
            patch.object(auth, "_api_key", return_value=""),
            patch.object(auth, "verify_firebase_token", return_value=fake_token),
            patch.object(auth, "_resolve_role", return_value="free"),
        ):
            resp = self.client.get(
                "/api/agent/chats",
                headers={"Authorization": "Bearer valid-token"},
            )
            assert resp.status_code != 401

    def test_api_key_valid(self):
        with (
            patch.object(auth, "_dev_mode", return_value=False),
            patch.object(auth, "_api_key", return_value="test-secret"),
        ):
            resp = self.client.get(
                "/api/agent/chats",
                headers={"X-API-Key": "test-secret"},
            )
            assert resp.status_code != 401
            assert resp.status_code != 403

    def test_api_key_invalid(self):
        with (
            patch.object(auth, "_dev_mode", return_value=False),
            patch.object(auth, "_api_key", return_value="test-secret"),
        ):
            resp = self.client.get(
                "/api/agent/chats",
                headers={"X-API-Key": "wrong-secret"},
            )
            assert resp.status_code == 403

    def test_dev_mode_bypass(self):
        with patch.object(auth, "_dev_mode", return_value=True):
            resp = self.client.get("/api/agent/chats")
            assert resp.status_code != 401


class TestRequireAdmin:
    @pytest.fixture(autouse=True)
    def setup_app(self):
        self.app = __import__("server").app
        self.client = self.app.test_client()

    def test_free_role_denied_admin_route(self):
        fake_token = {"uid": "free-user", "role": "free"}
        with (
            patch.object(auth, "_dev_mode", return_value=False),
            patch.object(auth, "_api_key", return_value=""),
            patch.object(auth, "verify_firebase_token", return_value=fake_token),
            patch.object(auth, "_resolve_role", return_value="free"),
        ):
            resp = self.client.get(
                "/api/admin/users",
                headers={"Authorization": "Bearer token"},
            )
            assert resp.status_code == 403

    def test_premium_role_denied_admin_route(self):
        fake_token = {"uid": "premium-user", "role": "premium"}
        with (
            patch.object(auth, "_dev_mode", return_value=False),
            patch.object(auth, "_api_key", return_value=""),
            patch.object(auth, "verify_firebase_token", return_value=fake_token),
            patch.object(auth, "_resolve_role", return_value="premium"),
        ):
            resp = self.client.get(
                "/api/admin/users",
                headers={"Authorization": "Bearer token"},
            )
            assert resp.status_code == 403

    def test_admin_role_allowed(self):
        fake_token = {"uid": "admin-user", "role": "admin"}
        with (
            patch.object(auth, "_dev_mode", return_value=False),
            patch.object(auth, "_api_key", return_value=""),
            patch.object(auth, "verify_firebase_token", return_value=fake_token),
            patch.object(auth, "_resolve_role", return_value="admin"),
            patch.object(auth, "_firebase_app", return_value=MagicMock()),
        ):
            with patch("firebase_admin.auth.list_users") as mock_list:
                mock_page = MagicMock()
                mock_page.users = []
                mock_list.return_value = mock_page
                resp = self.client.get(
                    "/api/admin/users",
                    headers={"Authorization": "Bearer token"},
                )
                assert resp.status_code == 200


class TestRequireRole:
    @pytest.fixture(autouse=True)
    def setup_app(self):
        self.app = __import__("server").app
        self.client = self.app.test_client()

    def test_free_role_denied_premium_route(self):
        fake_token = {"uid": "free-user", "role": "free"}
        with (
            patch.object(auth, "_dev_mode", return_value=False),
            patch.object(auth, "_api_key", return_value=""),
            patch.object(auth, "verify_firebase_token", return_value=fake_token),
            patch.object(auth, "_resolve_role", return_value="free"),
        ):
            resp = self.client.get(
                "/api/hdx/availability/TUR",
                headers={"Authorization": "Bearer token"},
            )
            assert resp.status_code == 403

    def test_premium_role_allowed_premium_route(self):
        fake_token = {"uid": "premium-user", "role": "premium"}
        with (
            patch.object(auth, "_dev_mode", return_value=False),
            patch.object(auth, "_api_key", return_value=""),
            patch.object(auth, "verify_firebase_token", return_value=fake_token),
            patch.object(auth, "_resolve_role", return_value="premium"),
        ):
            with patch("reliefweb_api.hdx_tools.get_hdx_client", return_value=None):
                resp = self.client.get(
                    "/api/hdx/availability/TUR",
                    headers={"Authorization": "Bearer token"},
                )
                assert resp.status_code in (200, 503)

    def test_admin_role_allowed_premium_route(self):
        fake_token = {"uid": "admin-user", "role": "admin"}
        with (
            patch.object(auth, "_dev_mode", return_value=False),
            patch.object(auth, "_api_key", return_value=""),
            patch.object(auth, "verify_firebase_token", return_value=fake_token),
            patch.object(auth, "_resolve_role", return_value="admin"),
        ):
            with patch("reliefweb_api.hdx_tools.get_hdx_client", return_value=None):
                resp = self.client.get(
                    "/api/hdx/availability/TUR",
                    headers={"Authorization": "Bearer token"},
                )
                assert resp.status_code in (200, 503)


# ── set_user_role / get_user_role ───────────────────────────────────────────────


class TestUserRoleManagement:
    def test_set_user_role_invalid_role(self):
        assert auth.set_user_role("uid123", "superadmin") is False

    def test_set_user_role_no_firebase(self):
        with patch.object(auth, "_firebase_app", return_value=None):
            assert auth.set_user_role("uid123", "admin") is False

    def test_set_user_role_success(self):
        mock_fb = MagicMock()
        with (
            patch.object(auth, "_firebase_app", return_value=mock_fb),
            patch("firebase_admin.auth.set_custom_user_claims") as mock_set,
        ):
            result = auth.set_user_role("uid123", "admin")
            assert result is True
            mock_set.assert_called_once_with("uid123", {"role": "admin"})

    def test_get_user_role_no_firebase_admin_uid(self):
        with (
            patch.object(auth, "_firebase_app", return_value=None),
            patch.object(auth, "_admins", return_value={"uid123"}),
        ):
            assert auth.get_user_role("uid123") == "admin"

    def test_get_user_role_no_firebase_not_admin(self):
        with patch.object(auth, "_firebase_app", return_value=None), patch.object(auth, "_admins", return_value=set()):
            assert auth.get_user_role("uid123") == "free"

    def test_get_user_role_with_firebase(self):
        mock_fb = MagicMock()
        mock_user = MagicMock()
        mock_user.custom_claims = {"role": "premium"}
        with (
            patch.object(auth, "_firebase_app", return_value=mock_fb),
            patch("firebase_admin.auth.get_user", return_value=mock_user),
        ):
            assert auth.get_user_role("uid123") == "premium"

    def test_get_user_role_with_firebase_no_claims(self):
        mock_fb = MagicMock()
        mock_user = MagicMock()
        mock_user.custom_claims = None
        with (
            patch.object(auth, "_firebase_app", return_value=mock_fb),
            patch("firebase_admin.auth.get_user", return_value=mock_user),
            patch.object(auth, "_admins", return_value=set()),
        ):
            assert auth.get_user_role("uid123") == "free"
