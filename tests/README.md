# Tests

Sightline has 197+ tests covering auth, API, security, and core functionality.

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_auth.py -v

# Run a specific test
pytest tests/test_auth.py::TestDevMode::test_dev_auth_bypass_true -v

# Run with coverage (if pytest-cov installed)
pytest tests/ --cov=. --cov-report=term-missing
```

## Test Files

| File | Tests | What it covers |
|---|---|---|
| `test_auth.py` | 25+ | Firebase token verification, RBAC roles, dev mode bypass, DESKTOP_MODE, admin UIDs |
| `test_api_auth.py` | 15+ | API endpoint auth — 401/403 responses, dev mode bypass, `/api/auth/me` |
| `test_health.py` | 5+ | `/api/health` endpoint — status checks, degraded mode |
| `test_config.py` | 10+ | Config loading, env var overrides, model selection |
| `test_dev_mode_safety.py` | 10+ | Dev bypass safety — loopback-only, blocked on 0.0.0.0, API key prevents bypass |
| `test_path_traversal.py` | 10+ | Path traversal protection — `Path.is_relative_to()` containment |
| `test_stream_nonce.py` | 10+ | SITREP stream nonce auth — single-use, TTL, job_id binding |
| `test_imports.py` | 5+ | All modules import without error |
| `test_ingest.py` | 5+ | ReliefWeb ingest pipeline — report parsing, chunk creation |
| `test_vector_store.py` | 10+ | ChromaDB vector store — add, search, purge, stats |
| `test_utils.py` | 15+ | Utility functions — country codes, ISO3 mapping, themes parsing |
| `test_guided_proposal.py` | 30+ | Guided Proposal V2 — donor manifests, validation, E2E flow |
| `test_migration.py` | 5+ | V1 → V2 proposal migration script |

## Test Conventions

- Tests use `pytest` with `unittest.mock.patch` for dependency isolation.
- Tests do **not** require external API keys or network access.
- Tests do **not** require Firebase or a running server.
- The test database is in-memory or temporary (no persistent state).
- `conftest.py` sets up the Flask test client and common fixtures.

## Writing New Tests

1. Create `test_<feature>.py` in `tests/`.
2. Import fixtures from `conftest.py` (Flask app, test client).
3. Use `unittest.mock.patch` for external dependencies (API clients, LLM, Firebase).
4. Follow the existing naming convention: `TestClassName::test_descriptive_name`.
5. Run `pytest tests/ -v` to verify.

```python
"""Test my new feature."""
from unittest.mock import patch


def test_my_feature_works(client):
    """My feature should return the expected result."""
    resp = client.get("/api/my-feature")
    assert resp.status_code == 200
    assert resp.json["status"] == "ok"
```

## Security Tests

Security tests are critical and should **never** be skipped:

- `test_path_traversal.py` — validates all file-serving endpoints reject `../` and absolute paths.
- `test_stream_nonce.py` — validates SITREP stream nonces are single-use and TTL-enforced.
- `test_dev_mode_safety.py` — validates dev bypass only works on loopback, never on public IPs.

## CI

Tests run automatically on every PR via GitHub Actions (`.github/workflows/ci.yml`).
