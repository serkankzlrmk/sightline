# Sightline — System Design (current)

> **Status:** current implementation (2026-11-10). This document replaces the older
> `ARCHITECTURE.md`/`docs/CODEMAP.md` claims where they disagree.
>
> Quick links: [README](../README.md) · [Tools](TOOLS.md) · [Evaluation](EVALUATION.md) ·
> [Error monitoring](ERROR_MONITORING.md) · [SRE runbook](SRE_RUNBOOK.md)

---

## 1. Product surfaces

| Surface | Route | Auth | What it is |
|---|---|---|---|
| Landing | `/` | public | Marketing page + 3D globe |
| SPA | `/app` (`noindex`) | public; chat/db/admin gated | Crisis map, database, chat agent, SITREP, bulletin, admin |
| SSR publications | `/crisis`, `/countries`, `/sitreps`, `/bulletins`, `/digest`, `/deep-dive`, `/solutions/*` | public | SEO/crawler surface, JSON-LD, sitemap/robots/llms.txt |
| Proposal Studio | `/proposal` | Firebase session | Separate repo embedded through `proposal_bridge.py` |
| JSON API | `/api/*` | role-dependent | ~120 routes across 14 blueprint modules |

---

## 2. Runtime topology

```
Browser / crawler
        │
     Caddy (TLS, SSE flush, static cache)
        │  reverse_proxy
     gunicorn: 1 worker, 4 threads (gthread), 120s timeout
        │
     Flask app (server.py)
        ├── blueprints/*        HTTP routes
        ├── helpers.py          shared DB, rate limits, nonces, jobs
        ├── auth.py             Firebase token verification + RBAC
        ├── agent/              LangGraph agent + tools + memory + resilience
        ├── sitrep/             pipeline, bulletin, country cards, digests
        ├── reliefweb_api/      external clients (13+ sources)
        ├── observability/      obs.db, eval, error tracking
        └── proposal_bridge.py  Proposal Studio blueprints (separate repo)

External: OpenRouter (LLM), Firebase Auth, ReliefWeb/HDX/ACLED/FTS/UNHCR/GDACS/
NASA FIRMS/FAO GIEWS/Overpass/NewsAPI/World Bank, MCP servers (arXiv, sequential).
```

Why one worker? SQLite (multi-DB) and Chroma are single-process-friendly; in-memory
jobs/nonces/rate counters and `max_requests=1000` assume a single worker. Scaling to
multiple workers requires Redis/Postgres first (roadmap).

---

## 3. Boot sequence

1. Environment setup: ONNX/TensorRT noise suppression env.
2. `config.py` import:
   - `load_dotenv(override=True)`; `.env` model-name migration;
   - creates output folders; validates production `SECRET_KEY`/`SSL_VERIFY`;
   - defines chat models, budgets, paths, observability/error/alert config.
3. Flask app: template/static folders, 50 MB upload limit.
4. Request middleware:
   - `before_request`: request id (`g.request_id`) + start time;
   - global `HTTPException` / `Exception` handlers → sanitized JSON/HTML + `errors.db`;
   - security headers/CSP; per-IP daily API limit; `/api/admin/*` and
     `/api/client-errors` exempt from the daily IP budget (still auth/own limits).
5. Blueprints registered: admin, obs, errors, sitrep, agent, public, hdx, news, db,
   ingest, main, auth, seo, proposal bridge.
6. External clients initialized at import (HDX, News, GDACS, Weather, World Bank,
   ACLED, FTS, Overpass, GIEWS-gated, UNHCR/FIRMS key-gated); MCP loads in a daemon
   thread and registers tools when ready.
7. Gunicorn serves `server:app`.

---

## 4. Request path (important endpoints)

### 4.1 Chat agent (`POST /api/agent/chat`, SSE)

- `@require_auth`; role/model validation; global `CHAT_MAX_CONCURRENT` semaphore (503 +
  `Retry-After` when saturated); per-user busy lock; daily message limit (admin bypass).
- History from `chat_messages`; optional cross-chat memory (`agent/memory.py`).
- Per-request agent (`build_agent`) or singleton; system prompt with source-routing rules.
- Streaming events: `llm`, `token`, `llm_done`, `tool_start`, `tool_done`,
  `done` (turn id, tools, usage, cost, latency, citations), `error` (code/request id).
- Tool calls go through `agent/tool_resilience.invoke_tool`: transient retry
  (timeout/429/5xx), per-tool circuit breaker, JSON error-envelope detection.
- Turn telemetry persisted to `obs.db` in `finally` (ok/error/empty/cancelled),
  including tool previews for later evaluation.

### 4.2 SITREP (`POST /api/sitrep/run` + SSE stream)

- Premium; spawns `sitrep/pipeline.py` subprocess; job id + single-use nonce.
- Progress streamed as plain SSE lines; `__PING__` heartbeat, `__DONE__` sentinel.
- Pipeline: chunks → HDX enrichment → clustering → questions → filter → RRF retrieval →
  answers → citations → summaries → narrative → assembly.
- Checkpoints under `output/`; job timeout 1800s; report JSON/Markdown stored in `output/reports`.

### 4.3 Public/SEO

- `seo_bp` renders SSR pages from `output/` artifacts and in-process map data.
- Canonical URLs from `SITE_URL`; sitemap/robots/llms.txt generated from the same sources.
- Map endpoint is disk-cached (`output/map_countries_cache.json`), single-flight refresh,
  stale-while-revalidate; cold build is expensive.

---

## 5. Data stores

| Store | Content | Notes |
|---|---|---|
| `reliefweb.db` | `reports`, `chunks`, pages/visual units | chunk id = `{report_id}_{index}`; 800-char chunks/150 overlap; retrieval source |
| `chats.db` | chats, chat_messages, users, rate_limits, events | WAL; role source of truth; audit events `audit:*` |
| `obs.db` | turns, tool_calls, feedback, eval_scores, eval_retrieval, eval tables | separate DB; retention 90d |
| `errors.db` | error_events, error_stats_minute, alert_state, calibration tables | separate DB; works when `OBS_ENABLED=false` |
| `Chroma` | 384-dim embeddings + agent memory collections | ChromaDB queries disabled on ARM64; pool retrieval uses numpy over SQLite chunks |
| `output/` | reports, bulletins, country summaries, digests, deep dives, caches | filesystem artifacts consumed by SSR/public APIs |
| `proposal.db` | Proposal Studio data | separate DB; never reuse reliefweb.db |

**Retrieval reality:** the SITREP pipeline reads candidate chunks from SQLite
(`get_chunks_by_country`) and computes similarity in-process with RRF; Chroma is used for
embeddings/memory, not live chunk search. This avoids ARM64 Chroma segfaults.

---

## 6. Auth & RBAC

- Firebase ID token (`Authorization: Bearer`) verified with `firebase_admin`;
  optional `SERVER_API_KEY` legacy mode (admin-level, disables Firebase verification).
- Role resolution: `ADMIN_UIDS` → `chats.db users.role` → Firebase custom claim → `free`.
- Decorators: `require_auth`, `require_admin`, `require_role(minimum)`, `optional_auth`.
- Dev bypass (`DESKTOP_MODE`/`DEV_AUTH_BYPASS`) only on loopback; returns mock admin.
- Content gating: agent chat/database/admin tabs gated in UI; SITREP/bulletin lists public;
  SITREP generation premium; admin routes admin-only.
- Rate limits: Flask-Limiter per IP (120/min; agent 30/min; admin 60), custom 100/day
  per-IP for `/api/*` (exemptions), per-user daily message quota in SQLite.

---

## 7. Agent and tools

- LangGraph `MessagesState`, nodes `llm_call` → `tool_node`; recursion limit 25.
- Models: `flash` (gemini-3.8-flash), `deep_think` (gemini-3.1-pro-preview, sequential),
  `vision` (gemini-3.8-flash), 7 premium custom models; SITREP default gemma-4-31b-it.
- System prompt (~26 KB): identity/security, source-routing matrix, per-source tool docs,
  citation rules, behavior rules. Source routing explicitly prefers quantitative tools
  (HDX/ACLED/FTS/UNHCR/World Bank) for numbers over ReliefWeb prose.
- **46 native tools potential**, 20 MCP tools (arXiv 19 + sequential 1); 60 active in the
  default local deployment. See [TOOLS.md](TOOLS.md) for key-gated tools.
- Tool health: JSON error envelopes (`error_type`, `error:true`) count as errors and are
  stored in `tool_calls.error_class`; per-tool retry/circuit breaker in
  `agent/tool_resilience.py`.
- Memory: Chroma collections `agent_memory`/`agent_facts`; gated recall and periodic
  consolidation.

---

## 8. Content generation

| Pipeline | Trigger | Output |
|---|---|---|
| SITREP | Premium UI / API | `output/reports/*.json|.md` |
| Weekly bulletin | Mon cron + admin UI | `output/bulletins/*.json` |
| Country cards | daily cron | `output/country_summaries/*.json` |
| Daily digest | daily enrichment script | `output/daily_digests/{date}/*.json` |
| Deep dives | weekly script | `output/deep_dives/{week}/*.json` |

Cron entries live in `deploy/setup-crons-docker.sh`/host crontab; see SRE docs.

---

## 9. Evaluation, feedback, observability

- **Turn telemetry** (`obs.db.turns`, `tool_calls`): model, usage/cost, latency, tools,
  citations/no-answer, tool previews.
- **Chat evaluation** (`scripts/eval_agent.py`): G-Eval rubric, cross-family judge,
  multi-sample averaging, evidence-aware prompt; scores stored in `eval_scores`.
- **Human calibration** (`scripts/calibrate_judge.py` + Admin UI): blind queue, 1–5 rating,
  QWK/Spearman/MAE in `calibration_runs`.
- **User feedback** (`feedback`): 👍/👎 per turn/user (upsert).
- **Retrieval evaluation** (`scripts/eval_retrieval.py`): golden set, pool-based two-stage
  Recall/nDCG/MRR; persisted in `eval_retrieval`.
- **Error monitoring** (`errors.db`): request IDs, backend/frontend/tool/LLM/SSE errors,
  fingerprints, admin Errors panel, audit log, alert checks, synthetic canary.

---

## 10. Frontend

- `templates/index.html` + `static/` plain JS; esbuild concatenates modules into
  `static/dist/app.js` and CSS into `static/dist/style.css` (content-hash `version.json`).
- Auth: Firebase ESM (`static/auth.js`), `localStorage.id_token`, preview mode.
- Admin: Users / Analytics / Observability / Errors subtabs; calibration, eval, errors.
- Chat: SSE reader, tool indicators, observability panel, 👍/👎 feedback.
- Cache busting: `?v=<hash>` from `version.json`; landing bundle separate.

---

## 11. Proposal Studio embedding

- Separate repo (`proposal/`) with its own DB/outputs; bridge pins `auth` module and
  registers blueprints into the Sightline process.
- Route families: `/api/proposals*`, `/api/calls*`, `/api/proposal-v2/steps/3|4/*`.
- `/api/auth/me` stays owned by Sightline; frontend uses root-relative API URLs.
- Production mount is read-only; Python changes require an app restart.

---

## 12. Deployment

- CI/CD: push `main` → GitHub Actions test → ARM64 image → GHCR → SSH `docker run` →
  health check → automatic rollback on failure. `RELEASE_SHA` is passed to the container.
- Production: Hetzner ARM64, Caddy TLS, Docker volumes for DB/Chroma/output; 1 gunicorn
  worker/4 threads; MCP cache volumes.
- Historical `docker-compose.yml` is not the current deployment path.
- `/api/health` returns booleans + release; deploy uses it as liveness gate.

---

### LLM providers

The active provider is selected by `LLM_PROVIDER`:

| Provider | Endpoint | Key | Notes |
|---|---|---|---|
| `openrouter` (default) | OpenRouter API | `OPENROUTER_API_KEY` | Public default; serves all configured chat/custom models |
| `google` | Gemini API (native SDK for chat, OpenAI-compatible for text-only pipelines) | `GOOGLE_API_KEY` | Server-side only; native SDK preserves Gemini 3 `thought_signature`; non-Google custom models fall back to Flash |
| `ollama` | local OpenAI-compatible server | optional `OLLAMA_API_KEY` | Local development |

Internal model ids keep the OpenRouter-style `google/...` form; `provider_model_name()`
maps them to the provider-specific id. Switching providers is an environment change plus
restart; no code changes. The previous provider stays configured for rollback.

## 13. Configuration groups

`config.py` (~159 env reads) + `.env.example`:
- paths/databases (`DB_PATH`, `CHATS_DB_PATH`, `OBS_DB_PATH`, `ERRORS_DB_PATH`, `CHROMA_DIR`);
- external APIs (ReliefWeb, HDX, News, ACLED, FTS, UNHCR, FIRMS, GIEWS, Overpass, World Bank);
- LLM/OpenRouter + chat model registry + pipeline model/temperature;
- SITREP retrieval/clustering/question parameters;
- auth/Firebase/CORS/server;
- analytics/ads/SEO/IndexNow/GSC;
- observability, alerts, error monitoring, tool resilience, concurrency.

---

## 14. Tests and quality gates

- `pytest tests/` — **436 passed, 6 skipped** (local; 2026-11-10).
- CI: `ruff check .`, `ruff format --check .` (ruff pinned), tests; deploy workflow runs
  tests separately then builds/deploys.
- Frontend: `npm run lint`, `npm run build`, `node --check static/dist/app.js`.
- Tests cover auth/RBAC, path traversal, stream nonces, SITREP, SEO, evaluation,
  calibration, error tracking, alerts, resilience, ingest.

---

## 15. Known constraints / caveats

- Single gunicorn worker: long SSE streams hold threads; `CHAT_MAX_CONCURRENT` guards chat,
  but true horizontal scaling needs Redis + Postgres/pgvector.
- ChromaDB whole-collection queries are disabled on ARM64; pool retrieval is mandatory.
- Cold `/api/map/countries` build is expensive; disk cache + single-flight mitigates it.
- `max_requests=1000` recycles the worker; in-memory nonces/jobs/rate counters reset.
- ACLED requires valid credentials; GIEWS is disabled until its schema is verified;
  UNHCR/FIRMS/Brave require optional keys.
- `docs/` internal notes (AGENTS.md, CODEMAP, etc.) are gitignored by design; the tracked
  public docs are the ones linked from the README.
