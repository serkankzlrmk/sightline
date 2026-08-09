# Sightline — Development Guide

> For local development, testing, and contributing.

## Quick Start

```bash
# 1. Clone
git clone https://github.com/serkankzlrmk/RedAgent.git
cd RedAgent

# 2. Create .env (copy from .env.example, fill in API keys)
cp .env.example .env
# Edit .env — set OPENROUTER_API_KEY, RELIEFWEB_APPNAME, etc.

# 3. Add firebase-service-account.json (for auth — optional in dev mode)

# 4. Start with Docker (recommended — same as production)
docker compose up -d --build

# 5. Open http://localhost:5001 (or http://localhost via Caddy)
```

## Dev Mode (no auth required)

For local development without Firebase auth:
```bash
# .env:
SERVER_DEBUG=true
SERVER_HOST=127.0.0.1
DEV_AUTH_BYPASS=true

# This bypasses auth with a mock admin user (uid=dev-local, role=admin)
# Only works on loopback (127.0.0.1) — never on 0.0.0.0
```

---

## Development Workflows

### Docker-based (recommended — same as production)

```bash
# Start
docker compose up -d

# Make code changes in your editor...

# Restart app (picks up code changes — 30s with cached layers)
docker compose restart app

# View logs
docker compose logs -f app

# Run tests
docker compose exec app pytest tests/ -v

# Stop
docker compose down
```

### Non-Docker (faster iteration, less consistent)

```bash
# Install deps
pip install -r requirements.txt

# Run server directly
SERVER_HOST=127.0.0.1 DEV_AUTH_BYPASS=true python server.py

# Run tests
pytest tests/ -v
```

---

## Testing

```bash
# Run all tests
docker compose exec app pytest tests/ -v
# or without Docker:
pytest tests/ -v

# Run specific test
pytest tests/test_auth.py -v

# Run with coverage
pytest tests/ --cov=server --cov=auth

# Test count: 171 tests (security, auth, API, imports, config, utils, vector store)
```

### Test files
| File | Tests | What |
|------|-------|------|
| `test_auth.py` | 44 | RBAC, dev mode, role management, decorators |
| `test_api_auth.py` | 17 | API route auth protection, admin-only routes |
| `test_ingest.py` | 21 | DatabaseManager CRUD, chunk_text, purge |
| `test_utils.py` | 41 | Country codes, normalize, validate, truncate |
| `test_vector_store.py` | 13 | VectorStore add/search/purge |
| `test_config.py` | 6 | Config values, chunk_text |
| `test_path_traversal.py` | 5 | Path containment (is_relative_to) |
| `test_dev_mode_safety.py` | 6 | Dev bypass blocked on public hosts |
| `test_stream_nonce.py` | 5 | SITREP stream nonce lifecycle |
| `test_health.py` | 3 | Health endpoint structure |
| `test_imports.py` | 10 | Module import smoke tests |

### Pre-deploy test gate
GitHub Actions runs `pytest tests/ -v` before building the Docker image.
If tests fail, deploy is aborted. (Requires GitHub Actions billing active.)

---

## Project Structure

```
RedAgent/
├── server.py                 # Flask app — all API routes (2,500+ lines)
├── config.py                 # All env vars + config (~370 lines)
├── auth.py                   # Firebase auth + RBAC + @require_auth/@optional_auth
├── mcp_integration.py        # MCP server integration (arxiv + sequential + brave)
├── Dockerfile                # Single-stage ARM64 build
├── docker-compose.yml        # app + caddy services
├── Caddyfile                 # Reverse proxy + auto-TLS
├── requirements.txt          # Python dependencies
├── requirements-dev.txt      # Dev deps (bandit, safety, pip-audit, ruff)
│
├── agent/
│   ├── relief_agent.py       # LangGraph agent + system prompt + tool binding
│   └── model.py              # LLM model initialization (OpenRouter/Ollama)
│
├── reliefweb_api/
│   ├── reliefweb.py          # 17 ReliefWeb tools (@tool functions)
│   ├── hdx_tools.py          # 7 HDX tools
│   ├── news_tools.py         # 4 News tools (NewsAPI)
│   ├── gdacs_tools.py        # 3 GDACS tools (disaster alerts)
│   ├── weather_tools.py      # 4 Weather tools (Open-Meteo)
│   ├── worldbank_tools.py    # 3 World Bank tools
│   ├── sql_tools.py          # 2 SQL query tools (read-only)
│   ├── gdacs_client.py       # GDACS RSS client
│   ├── weather_client.py     # Open-Meteo client
│   ├── worldbank_client.py   # World Bank API client
│   ├── hdx_client.py         # HDX HAPI client
│   ├── news_client.py        # NewsAPI client
│   ├── db_manager.py         # SQLite DB manager
│   ├── vector_store.py       # ChromaDB vector store
│   ├── pgvector_store.py     # pgvector store (Supabase — optional)
│   ├── ingest_pipeline.py    # Report ingest pipeline
│   └── country_codes.py      # ISO code conversions
│
├── sitrep/
│   ├── pipeline.py           # SITREP 10-stage pipeline
│   ├── weekly_bulletin.py    # Weekly bulletin generator
│   ├── country_summary.py    # Per-country intelligence summaries
│   ├── chroma_adapter.py     # ChromaDB adapter
│   ├── clustering.py         # HDBSCAN clustering
│   ├── question_generation.py
│   ├── question_filtering.py
│   ├── rag_answers.py        # RAG answer generation
│   ├── citation_postprocess.py
│   ├── cluster_summary.py
│   ├── executive_summary.py
│   ├── narrative_report.py
│   ├── report_assembly.py
│   ├── llm_client.py         # LLM HTTP client
│   └── hdx_enrichment.py     # HDX data enrichment
│
├── scripts/
│   ├── daily_ingest.py       # Cron: daily ReliefWeb ingest
│   ├── generate_bulletin.py  # Cron: weekly bulletin
│   ├── generate_country_summaries.py  # Cron: weekly country summaries
│   └── backfill_ingest.py    # Bulk backfill
│
├── templates/
│   └── index.html            # SPA frontend (all tabs)
│
├── static/
│   ├── app.js                # Main frontend JS (3,000+ lines)
│   ├── auth.js               # Firebase auth JS
│   └── style.css             # All styles (3,900+ lines)
│
├── tests/                    # 171 tests
├── deploy/                   # Deployment configs
├── .github/workflows/        # CI/CD (deploy.yml)
├── docs/                     # All documentation (deploy, dev, roadmap, codemap, etc.)
├── AGENTS.md                 # Agent instructions (local only, not in repo)
├── Dockerfile                # Single-stage ARM64 build
├── docker-compose.yml        # app + caddy services
├── Caddyfile                 # Reverse proxy + auto-TLS
└── requirements.txt          # Python dependencies
```

---

## Agent Tools (54 total)

### Native Python tools (35)
| Group | Count | Source | API Key |
|-------|-------|--------|---------|
| ReliefWeb | 17 | `reliefweb.py` | RELIEFWEB_APPNAME (free) |
| HDX | 7 | `hdx_tools.py` | HDX_APP_IDENTIFIER (free) |
| News | 4 | `news_tools.py` | NEWS_API_KEY (free tier) |
| GDACS | 3 | `gdacs_tools.py` | None (keyless) |
| Weather | 4 | `weather_tools.py` | None (keyless) |
| World Bank | 3 | `worldbank_tools.py` | None (keyless) |
| SQL query | 2 | `sql_tools.py` | None (local SQLite) |

### MCP tools (19 — loaded via mcp_integration.py)
| Server | Count | Command | API Key |
|--------|-------|---------|---------|
| arxiv | 10 | `uvx --no-cache arxiv-mcp-server` | None (keyless) |
| sequential-thinking | 1 | `npx -y @modelcontextprotocol/server-sequential-thinking` | None |
| brave-search | 8 | `npx -y @brave/brave-search-mcp-server` | BRAVE_API_KEY (30/day limit) |

### Adding a new tool
1. Create `reliefweb_api/<name>_client.py` — HTTP client (singleton, httpx, SimpleCache, rate limit)
2. Create `reliefweb_api/<name>_tools.py` — `@tool` functions + `init_<name>_tools()` + `TOOLS` list
3. Add config to `config.py` (URL, timeout, cache TTL, API key env var)
4. Register in `agent/relief_agent.py` — import, init, add to `all_tools`
5. Add system prompt documentation in `_build_system_prompt()`
6. If MCP: add to `mcp_integration.py` `_configure_servers()`

---

## Chat Models

| Key | Name | Model | Premium | Sequential |
|-----|------|-------|---------|------------|
| `flash` | Flash | google/gemini-2.5-flash | No | No |
| `thinking` | Thinking | google/gemma-4-31b-it | No | No |
| `ultra` | Ultra | google/gemini-2.5-pro | Yes | No |
| `deep_think` | Deep Think | google/gemini-2.5-pro | Yes | Yes |

Deep Think mode: uses gemini-2.5-pro + sequential_thinking tool for complex multi-step analysis.

---

## Freemium Preview

Anonymous visitors can:
- See dashboard (map with all country markers, global overview, crisis headlines)
- View country summaries (headline, severity, report count, themes)
- Search countries on map
- See SITREP report list (filenames only)

Anonymous visitors cannot (login panel appears on click):
- Chat with agent
- View full SITREP reports
- View full bulletins (crisis sources)
- Browse database
- Access admin panel

Public endpoints (no auth): `/api/health`, `/api/public/stats`, `/api/public/bulletins`, `/api/public/bulletin/<filename>`, `/api/public/sitrep/reports`, `/api/country/summaries`, `/api/public/countries`

---

## Code Style

- Python: ruff (E, F, W, I, S, B, UP rules) — `pyproject.toml`
- No comments unless absolutely necessary
- Bilingual codebase (EN/TR docstrings)
- `logger` in every module: `logger = logging.getLogger(__name__)`
- Thread-safe: all global mutable state protected with `threading.Lock`

---

## Useful Commands

```bash
# SSH to production
ssh root@<your-server-ip>

# Check production health
curl -sfk https://YOUR_PROJECT_ID.com/api/health

# Check production logs
ssh root@<your-server-ip> "docker logs sightline --tail 50"

# Run tests locally
pytest tests/ -v

# Lint
ruff check .
ruff format .

# Security scan
bandit -r . -ll
pip-audit
```