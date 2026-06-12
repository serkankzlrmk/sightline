"""
Test: Health endpoint returns expected structure.

Uses Flask test client so no running server is needed.
"""

import json
import pytest


def test_health_endpoint_structure():
    """Health endpoint returns JSON with required keys."""
    from server import app

    client = app.test_client()
    resp = client.get("/api/health")
    data = json.loads(resp.data)

    required_keys = ["status", "db", "vector", "llm", "version"]
    for key in required_keys:
        assert key in data, f"Missing '{key}' key"

    assert data["status"] in ("ok", "degraded"), f"Unexpected status: {data['status']}"


def test_health_endpoint_status_code():
    """Health endpoint returns 200 (ok) or 503 (degraded)."""
    from server import app

    client = app.test_client()
    resp = client.get("/api/health")

    assert resp.status_code in (200, 503), f"Unexpected status code: {resp.status_code}"


def test_health_no_auth_required():
    """Health endpoint is accessible without authentication."""
    from server import app

    client = app.test_client()
    resp = client.get("/api/health")

    # Should NOT return 401
    assert resp.status_code != 401, "Health endpoint should not require auth"