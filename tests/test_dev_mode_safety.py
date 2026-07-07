"""
Tests for dev mode bypass safety — ensures auth bypass cannot activate
in production configurations.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth


class TestDevModeSafety:
    def test_dev_mode_disabled_in_production(self):
        """SERVER_DEBUG=false → dev mode must be False."""
        env = {"SERVER_DEBUG": "false", "DEV_AUTH_BYPASS": "", "SERVER_HOST": "127.0.0.1"}
        with patch.dict(os.environ, env, clear=False):
            assert auth._dev_mode() is False

    def test_dev_bypass_blocked_on_public_host(self):
        """DEV_AUTH_BYPASS=true but SERVER_HOST=0.0.0.0 → must be False."""
        env = {"DEV_AUTH_BYPASS": "true", "SERVER_HOST": "0.0.0.0"}
        with patch.dict(os.environ, env, clear=False):
            assert auth._dev_mode() is False

    def test_dev_bypass_blocked_on_ip(self):
        """DEV_AUTH_BYPASS=true but SERVER_HOST=192.168.1.1 → must be False."""
        env = {"DEV_AUTH_BYPASS": "true", "SERVER_HOST": "192.168.1.1"}
        with patch.dict(os.environ, env, clear=False):
            assert auth._dev_mode() is False

    def test_dev_bypass_allowed_on_loopback(self):
        """DEV_AUTH_BYPASS=true + SERVER_HOST=127.0.0.1 → True (legitimate dev)."""
        env = {"DEV_AUTH_BYPASS": "true", "SERVER_HOST": "127.0.0.1"}
        with patch.dict(os.environ, env, clear=False):
            assert auth._dev_mode() is True

    def test_dev_bypass_allowed_on_localhost(self):
        """DEV_AUTH_BYPASS=true + SERVER_HOST=localhost → True."""
        env = {"DEV_AUTH_BYPASS": "true", "SERVER_HOST": "localhost"}
        with patch.dict(os.environ, env, clear=False):
            assert auth._dev_mode() is True

    def test_legacy_dev_mode_blocked_on_public_host(self):
        """SERVER_DEBUG=true but SERVER_HOST=0.0.0.0 + no Firebase → False."""
        env = {"SERVER_DEBUG": "true", "DEV_AUTH_BYPASS": "", "SERVER_HOST": "0.0.0.0"}
        with patch.dict(os.environ, env, clear=False):
            with patch.object(auth, "_api_key", return_value=""), \
                 patch.object(auth, "_firebase_app", return_value=None):
                assert auth._dev_mode() is False
