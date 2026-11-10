# Tests

Sightline has **436 collected tests** (437 test functions; parameterization accounts for the
difference), covering auth/RBAC, API, security, evaluation, error monitoring, resilience,
SITREP, SEO, ingest, and frontend deep links.

## Running Tests

```bash
# Run all tests
.venv/bin/python -m pytest tests/ -v

# Run a specific file
.venv/bin/python -m pytest tests/test_auth.py -v

# Run a specific test
.venv/bin/python -m pytest tests/test_auth.py::TestDevMode::test_dev_auth_bypass_true -v

# With coverage (if pytest-cov installed)
.venv/bin/python -m pytest tests/ --cov=. --cov-report=term-missing
```

CI runs `pytest tests/ -v --tb=short` with `SERVER_HOST=127.0.0.1`, `SERVER_DEBUG=true`,
`DEV_AUTH_BYPASS=true`, and a fake OpenRouter key. Tests must not require real network
access or Firebase credentials.

## Test Files (current)

| File | Tests | What it covers |
|---|---|---|
| `test_auth.py` | 46 | Firebase verification, RBAC, dev-mode bypass, admin UIDs |
| `test_api_auth.py` | 20 | API auth gates (401/403), `/api/auth/me`, dev bypass |
| `test_seo.py` | 64 | SSR pages, slugify, JSON-LD, sitemap/robots/llms, caching, SEO safety |
| `test_utils.py` | 41 | Country/ISO3/theme helpers, formatting, utilities |
| `test_daily_digest.py` | 36 | Digest JSON schema, sampling, SSR routes, deep dives, sitemap |
| `test_ingest.py` | 21 | ReliefWeb ingest, chunking, purge, ingest status |
| `test_sql_tools.py` | 21 | Read-only SQL tool, timeout, PII redaction |
| `test_observability.py` | 21 | Turn telemetry, feedback, eval scores, obs/error APIs |
| `test_sitrep.py` | 19 | Pipeline config, citation post-processing, report assembly |
| `test_eval_agent.py` | 16 | G-Eval parsing/sampling, dry-run/apply, evidence, upsert |
| `test_vector_store.py` | 13 | Chroma store add/search/purge/stats |
| `test_eval_retrieval.py` | 13 | Recall/nDCG/MRR math, pool-based production path, golden set |
| `test_agent_tools.py` | 11 | Agent tool registry, prompt source routing, tool modes |
| `test_config.py` | 11 | Config loading, env overrides, chat models |
| `test_imports.py` | 10 | All modules import without external services |
| `test_calibration.py` | 8 | QWK/Spearman/MAE, blind export, label persistence |
| `test_error_tracking.py` | 7 | Sanitization, fingerprinting, error stats, retention, taxonomy |
| `test_country_data_quality.py` | 6 | Country card fields and data quality |
| `test_dev_mode_safety.py` | 6 | Dev bypass only on loopback; blocked on public IP |
| `test_tool_resilience.py` | 6 | Retry, circuit breaker, JSON error envelopes |
| `test_alert_check.py` | 5 | Alert thresholds (5xx/tool/cost), cooldown, delivery |
| `test_ingest_status.py` | 5 | Ingest freshness/status writes |
| `test_path_traversal.py` | 5 | `Path.is_relative_to()` containment |
| `test_stream_nonce.py` | 5 | SITREP stream nonce: single-use, TTL, job binding |
| `test_error_api.py` | 4 | Request IDs, 404/500 handlers, client errors, admin error API |
| `test_backfill_turns.py` | 3 | Historical chats → obs turns (idempotent) |
| `test_frontend_deep_links.py` | 3 | SPA hash/deep-link tab routing |
| `test_health.py` | 3 | `/api/health` status and release field |
| `test_search_console.py` | 3 | GSC snapshot/dashboard (fake session) |
| `test_audit.py` | 2 | Audit event helper + `/api/admin/audit` |
| `test_canary.py` | 2 | Synthetic canary success/failure recording |
| `test_load_test.py` | 1 | Load-test percentile helper |

> Some tests skip when optional dependencies/data are absent (`6 skipped` locally);
> this is expected.

## Test Conventions

- `pytest` with `unittest.mock.patch` for dependency isolation.
- No real external API keys or network calls; LLM judges/clients are monkeypatched.
- No Firebase or running server required; Flask test client + dev auth bypass.
- `conftest.py` resets Flask-Limiter and per-IP counters per test; temp DBs use `tmp_path`.
- New features should ship with tests; evaluation/error/alert code must remain deterministic.
