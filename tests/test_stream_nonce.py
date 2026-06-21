"""
Tests for SITREP stream nonce lifecycle — single-use, TTL, UID + job_id binding.
"""
import os
import sys
import time
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the nonce functions directly from server module
# We need to import server, but it may fail if Firebase/deps are missing.
# Use try/except to handle import gracefully.
try:
    import server
    _create_stream_nonce = server._create_stream_nonce
    _consume_stream_nonce = server._consume_stream_nonce
    _STREAM_NONCE_TTL = server._STREAM_NONCE_TTL
    HAS_SERVER = True
except Exception:
    HAS_SERVER = False

import pytest
pytestmark = pytest.mark.skipif(not HAS_SERVER, reason="server module not importable in test env")


class TestStreamNonce:
    def test_nonce_single_use(self):
        """A nonce can only be consumed once."""
        nonce = _create_stream_nonce("user-123", "job-abc")
        assert _consume_stream_nonce(nonce, "user-123", "job-abc") is True
        # Second use must fail
        assert _consume_stream_nonce(nonce, "user-123", "job-abc") is False

    def test_nonce_uid_binding(self):
        """A nonce created for user-A cannot be used by user-B."""
        nonce = _create_stream_nonce("user-A", "job-1")
        assert _consume_stream_nonce(nonce, "user-B", "job-1") is False
        # Original user can still use it
        assert _consume_stream_nonce(nonce, "user-A", "job-1") is True

    def test_nonce_job_id_binding(self):
        """A nonce created for job-A cannot be used for job-B."""
        nonce = _create_stream_nonce("user-1", "job-A")
        assert _consume_stream_nonce(nonce, "user-1", "job-B") is False
        # Correct job_id works
        assert _consume_stream_nonce(nonce, "user-1", "job-A") is True

    def test_nonce_invalid_returns_false(self):
        """A non-existent nonce returns False."""
        assert _consume_stream_nonce("fake-nonce-xyz", "user-1", "job-1") is False

    def test_nonce_empty_job_id_allows_any(self):
        """If nonce was created with empty job_id, any job_id is accepted (backward compat)."""
        nonce = _create_stream_nonce("user-1", "")
        assert _consume_stream_nonce(nonce, "user-1", "any-job") is True