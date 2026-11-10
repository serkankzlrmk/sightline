<div align="center">

<img src="static/logo-signal-horizon.webp" alt="Sightline — Humanitarian Intelligence Platform" width="120">

# Sightline

**Humanitarian intelligence platform for crisis response teams.**

Real-time data aggregation · 10-stage SITREP pipeline · LLM evaluation and observability · donor-compliant proposal generator.

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Commercial License](https://img.shields.io/badge/Commercial-Dual_License-green.svg)](LICENSES/Commercial-LICENSE.md)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ed.svg)](https://www.docker.com/)
[![Tests](https://img.shields.io/badge/tests-436-brightgreen.svg)](tests/)
[![Version](https://img.shields.io/badge/version-0.2.0-orange.svg)](VERSION)

[Quick Start](#quick-start) · [Features](#features) · [Architecture](#architecture) · [Observability](#observability--evaluation) · [Docs](#documentation) · [Contributing](CONTRIBUTING.md)

</div>

---

## Why Sightline?

Humanitarian professionals spend a large share of their time collecting, synthesizing, and
formatting information from scattered sources — ReliefWeb, HDX, GDACS, ACLED, FTS, UNHCR,
news feeds, field reports. Sightline automates this workflow with direct API integrations,
a 60-tool LangGraph agent, automated SITREP/bulletin/country intelligence generation, and a
donor-compliance-aware Proposal Studio.

| What | How |
|---|---|
| **60-tool data agent** | 46 native tools (ReliefWeb, HDX, ACLED, FTS, UNHCR, FIRMS, GIEWS, OSM, GDACS, weather, World Bank, SQL) + 20 MCP tools (arXiv, sequential-thinking). Quantitative questions route to HDX/ACLED/FTS instead of defaulting to report search. |
| **10-stage SITREP pipeline** | UMAP + HDBSCAN clustering → question generation → filtering → pool-based RRF retrieval → citation post-processing → synthesis. Produces structured situation reports from the report corpus. |
| **Donor-compliant Proposal Studio** | Separate repository embedded in the same Flask process: 5-step pipeline, 6 donor manifests, deterministic scoring, Typst PDF export. |
| **Evaluation & observability** | G-Eval chat evaluation, human calibration (QWK), 👍/👎 user feedback, per-turn telemetry, error monitoring, audit log, alerts and synthetic canary. |

---

## Quick Start

```bash
git clone https://github.com/serkankzlrmk/sightline.git
cd sightline
cp .env.example .env
# Fill in at least OPENROUTER_API_KEY and RELIEFWEB_APPNAME
```

### Local development (no Firebase)

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
SERVER_HOST=127.0.0.1 DESKTOP_MODE=true SERVER_DEBUG=true .venv/bin/python server.py
# → http://127.0.0.1:5001/app
```

`DESKTOP_MODE`/`DEV_AUTH_BYPASS` only work on loopback; all requests get a mock admin user.

### Docker (production-like)

The production image is built by CI and run with `docker run` (see
[docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md) and `deploy/gunicorn.conf.py`).
The repository's historical `docker-compose.yml` targets an old monorepo layout and is
**not** the current deployment path.

> **No API keys?** The app starts without them; `/api/health` reports `degraded`.
> GDACS, Open-Meteo, FTS, Overpass, and World Bank are keyless. Add keys for ReliefWeb,
> HDX, News, ACLED, UNHCR, FIRMS, Brave, and the LLM as needed.
> See [docs/TOOLS.md](docs/TOOLS.md) for the full tool/key matrix.

---

## Features

### Data agent (46 native + 20 MCP tools)

The agent uses a source-routing prompt: ReliefWeb for qualitative reports, HDX/UNHCR for
displacement and refugee statistics, ACLED for conflict events, FTS for funding plans,
World Bank for macro indicators, GDACS for rapid-onset alerts, FIRMS for fires, OSM for
nearby infrastructure, News/Brave for media, arXiv for literature, and SQL for local
database analytics.

Availability depends on keys; see [docs/TOOLS.md](docs/TOOLS.md). ACLED auth failures and
GIEWS schema-pending errors are surfaced as tool errors (not silently counted as success).

### SITREP pipeline

`POST /api/sitrep/run` (premium) runs `sitrep/pipeline.py` in a subprocess and streams
progress over a nonce-authenticated SSE endpoint:

1. Load chunks from SQLite (country/theme/date filter)
2. HDX enrichment (non-fatal)
3. UMAP + HDBSCAN clustering (adaptive hyperparameter search)
4. Question generation
5. Question filtering + dedup
6. Pool-based retrieval with reciprocal rank fusion over sub-queries
7. RAG answers with citations
8. Citation post-processing
9. Cluster summaries + executive summary + narrative HTML
10. JSON + Markdown report assembly

Outputs live under `output/` (reports, clusters, questions, answers, summaries, bulletins,
country summaries, daily digests, deep dives).

### Weekly bulletin, country cards, digests

- Weekly bulletin: top countries, severity, key figures, global overview.
- Country intelligence cards: ReliefWeb + HDX + GDACS + World Bank, deterministic narrative,
  map data for all countries, weekly freshness checks.
- Daily digest + weekly deep-dives: SSR publication pages with structured JSON.

### Public / SEO surface

Server-rendered pages for crisis/country/SITREP/bulletin/digest/deep-dive content, plus
sitemap/robots/llms.txt/IndexNow. Public SSR pages are cache-friendly; the SPA at `/app` is
`noindex`.

### Proposal Studio

A separate repository (`proposal/` symlink in development, mounted read-only in production)
registered into the same Flask process by `proposal_bridge.py`. It owns the donor-call
ingestion, 5-step proposal pipeline, deterministic verification, and Typst PDF export.
API routes remain root-relative (`/api/proposals`, `/api/calls`, `/api/proposal-v2/...`).

---

## Architecture

```
Browser
 ├── /               landing page (marketing)
 ├── /app            SPA (map, chat, database, SITREP, bulletin, admin)
 ├── /crisis ...     SSR publication pages (SEO)
 └── /proposal       Proposal Studio SPA (separate repo, same process)

Flask — server.py (~600 lines: app init, request IDs, error handlers, middleware)
├── blueprints/     14 route modules + helpers.py (~120 routes)
├── auth.py         Firebase + RBAC (role source of truth: users table)
├── agent/          LangGraph agent, models, memory, tool resilience
├── reliefweb_api/  13+ external data clients + tools
├── sitrep/         10-stage pipeline, bulletin, country summaries, digests
├── observability/  turn telemetry, eval scores, error tracking
└── proposal/       embedded Proposal Studio (separate repo)

Storage
├── reliefweb.db    reports + chunks (SQLite; chunk store is the retrieval source)
├── chats.db        chats, messages, users, rate limits, events
├── obs.db          turns, tool calls, feedback, eval scores, retrieval eval
├── errors.db       error events, request stats, alert state
├── chroma/         embeddings (384-dim) + agent memory collections
└── output/         generated reports, bulletins, summaries, digests, caches
```

**Runtime:** gunicorn 1 worker / 4 threads (SQLite + Chroma single-process constraint),
Caddy for TLS and SSE, OpenRouter for LLM, Firebase for auth, MCP subprocesses for
arXiv/sequential-thinking.

---

## Observability & evaluation

Sightline records every chat turn in `obs.db` and every error in `errors.db`:

- **Turn telemetry:** model, tokens, cost, latency/total, iterations, tool calls, citations,
  no-answer signal, tool evidence previews.
- **Chat evaluation:** G-Eval judge (cross-family default, multi-sample), evidence-aware
  rubric, low-score queue.
- **Human calibration:** blind admin queue, 1–5 rating, QWK/Spearman/MAE against the judge.
- **User feedback:** 👍/👎 under assistant answers (one vote per turn/user).
- **Error monitoring:** request IDs (`X-Request-ID`, `ERR-…`), backend/frontend/tool/LLM/SSE
  capture, grouped fingerprints, admin Errors panel, audit log.
- **Alerts & canary:** threshold checks (`scripts/alert_check.py`) and synthetic uptime checks
  (`scripts/canary.py`), webhook/Telegram delivery.
- **Load testing:** async HTTP load script with p50/p95/p99 reporting.

Details: [docs/EVALUATION.md](docs/EVALUATION.md), [docs/CALIBRATION.md](docs/CALIBRATION.md),
[docs/ERROR_MONITORING.md](docs/ERROR_MONITORING.md), [docs/LOAD_TESTING.md](docs/LOAD_TESTING.md),
[docs/SRE_RUNBOOK.md](docs/SRE_RUNBOOK.md), [docs/TOOLS.md](docs/TOOLS.md).

---

## Configuration

Configuration is environment-driven (`.env`); see [`.env.example`](.env.example) and
[docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md#configuration) for the current groups.

Key variables:

| Variable | Required | Description |
|---|---|---|
| `LLM_PROVIDER` | Optional | `openrouter` (default), `google` (Gemini API) or `ollama` |
| `OPENROUTER_API_KEY` | If OpenRouter | LLM access (chat + evaluation judge + SITREP) |
| `GOOGLE_API_KEY` | If Google | Gemini API key; server-side only, never exposed to the browser |
| `RELIEFWEB_APPNAME` | ✅ | ReliefWeb API identifier |
| `HDX_APP_IDENTIFIER` | Optional | HDX API (base64 app identifier) |
| `NEWS_API_KEY` | Optional | NewsAPI.org |
| `ACLED_EMAIL`/`ACLED_PASSWORD` or `ACLED_API_KEY` | Optional | ACLED conflict events |
| `UNHCR_API_KEY` | Optional | UNHCR refugee statistics |
| `FIRMS_MAP_KEY` | Optional | NASA FIRMS active fires |
| `GIEWS_ENABLED` | Optional | Enable FAO GIEWS once schema is verified (default false) |
| `BRAVE_API_KEY` + `MCP_BRAVE_ENABLED=true` | Optional | Brave search MCP |
| `DESKTOP_MODE`/`DEV_AUTH_BYPASS` | Optional | Local auth bypass (loopback only) |
| `OBS_DB_PATH`, `ERRORS_DB_PATH`, `ERRORS_SALT` | Optional | Telemetry/error stores |
| `ALERT_WEBHOOK_URL`, `ALERT_TELEGRAM_*` | Optional | Alert delivery |
| `CHAT_MAX_CONCURRENT` | Optional | Chat SSE concurrency guard |
| `RELEASE_SHA` | Optional | Release identifier in health/errors |

**Chat models** (current): `flash` → `google/gemini-3.8-flash` (free),
`deep_think` → `google/gemini-3.1-pro-preview` (premium, sequential reasoning),
`vision` → `google/gemini-3.8-flash` (premium), plus 7 premium custom models.
SITREP/bulletin default model is `google/gemma-4-31b-it` (configurable via `LLM_MODEL`).

---

## Auth & RBAC

| Role | Chat | SITREP | Bulletin | Database | Admin |
|---|---|---|---|---|---|
| free | 10/day | ✗ | read | last 3 days | ✗ |
| premium | 100/day | ✓ | read | full | ✗ |
| admin | unlimited | ✓ | generate | full | ✓ |

Role resolution order: `ADMIN_UIDS` → `chats.db users.role` (source of truth) → Firebase
custom claim → `free`. Decorators: `@require_auth`, `@require_admin`,
`@require_role("premium")`, `@optional_auth`.

Freemium gating (current code): gated tabs are **agent chat, database, admin**; SITREP and
bulletin lists are publicly browsable, while SITREP generation remains premium.

---

## Development

```bash
# Tests — 436 passed, 6 skipped (current suite)
.venv/bin/python -m pytest tests/ -q

# Lint/format (CI gate)
ruff check .
ruff format --check .

# Frontend bundle (required for /app after JS/CSS edits)
npm run lint
npm run build
node --check static/dist/app.js

# Dev server
SERVER_HOST=127.0.0.1 DESKTOP_MODE=true SERVER_DEBUG=true .venv/bin/python server.py
```

The SPA is plain script-tag JavaScript bundled by esbuild (`static/dist/app.js`,
`static/dist/style.css`). `static/dist/` is gitignored and built inside Docker.

---

## Deployment

Production: Hetzner ARM64 + Docker + Caddy, image `ghcr.io/serkankzlrmk/sightline`.
Pushing to `main` triggers GitHub Actions: test → ARM64 build → GHCR → SSH `docker run`
→ health check → automatic rollback on failure. `RELEASE_SHA` is exposed in
`/api/health` and error records.

The historical `docker-compose.yml` is not production; use the CI workflow or the
`docker run` command in `.github/workflows/deploy.yml`. See
[docs/SRE_RUNBOOK.md](docs/SRE_RUNBOOK.md) for operations.

---

## Documentation

| Doc | Purpose |
|---|---|
| [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md) | Current architecture, modules, data flows, storage, auth, deployment |
| [docs/EVALUATION.md](docs/EVALUATION.md) | Chat evaluation + retrieval evaluation process |
| [docs/EVALUATION_RESULTS.md](docs/EVALUATION_RESULTS.md) | Preliminary measured results and pending evaluations |
| [docs/CALIBRATION.md](docs/CALIBRATION.md) | Human calibration of the LLM judge (UI + CSV) |
| [docs/ERROR_MONITORING.md](docs/ERROR_MONITORING.md) | errors.db, request IDs, admin Errors, alerts, canary, audit |
| [docs/LOAD_TESTING.md](docs/LOAD_TESTING.md) | Load-test baseline and capacity guards |
| [docs/SRE_RUNBOOK.md](docs/SRE_RUNBOOK.md) | On-call checks, rollback, alerts |
| [docs/TOOLS.md](docs/TOOLS.md) | Tool inventory and enablement matrix |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution workflow, CLA |
| [SECURITY.md](SECURITY.md) | Vulnerability disclosure policy |

---

## License

Sightline is **dual-licensed**:

1. **AGPL v3** ([`LICENSE`](LICENSE)) — open-source use; network use requires sharing modifications.
2. **Commercial License** ([`LICENSES/Commercial-LICENSE.md`](LICENSES/Commercial-LICENSE.md)) — for proprietary/SaaS use.

All contributions require signing the [CLA](CLA.md).

---

## Security

See [`SECURITY.md`](SECURITY.md) for the vulnerability disclosure policy. Do not open public
issues for security vulnerabilities; use GitHub Security Advisories.

---

<div align="center">

Built by [Serkan Kizilirmak](https://github.com/serkankzlrmk)

**Sightline** — *Humanitarian intelligence for crisis response*

</div>
