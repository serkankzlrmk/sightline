"""
Pytest configuration — ensures test environment is properly set up.

Sets DEV_AUTH_BYPASS and SERVER_DEBUG so that auth module can be imported
without a real Firebase service account file.
"""

import os
import sys

# Ensure project root is on sys.path for `import auth`, `import server`, etc.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Dev-mode env defaults for testing (auth bypass on loopback)
os.environ.setdefault("SERVER_DEBUG", "true")
os.environ.setdefault("SERVER_HOST", "127.0.0.1")
os.environ.setdefault("DEV_AUTH_BYPASS", "true")

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Reset Flask-Limiter and in-memory rate-limit state before each test.

    Without this, the global limiter accumulates hits across tests and starts
    returning 429, which makes proposal/guided-proposal tests fail.
    """
    # 1. Reset Flask-Limiter storage (memory:// backend)
    try:
        import server

        limiter = server.limiter
        # Reset the storage backend's in-memory counters
        if hasattr(limiter, "storage") and hasattr(limiter.storage, "clear"):
            limiter.storage.clear()
        elif hasattr(limiter, "_storage") and hasattr(limiter._storage, "clear"):
            limiter._storage.clear()
    except Exception:
        pass

    # 2. Reset in-memory per-IP rate limit counters in helpers.py
    try:
        from blueprints.helpers import _api_rate_counts, _api_rate_lock

        with _api_rate_lock:
            _api_rate_counts.clear()
    except Exception:
        pass

    yield

    # Clean up after test too
    try:
        from blueprints.helpers import _api_rate_counts, _api_rate_lock

        with _api_rate_lock:
            _api_rate_counts.clear()
    except Exception:
        pass