# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-09-17

### Added — Daily Content Enrichment Engine
- **Daily ACAPS-style digests** — `scripts/daily_content_enrichment.py` runs after the 06:00 UTC ingest: top 10 crisis countries, last-7-days chunks from SQLite (ARM64-safe, never ChromaDB `collection.query()`), first-chunk-per-report sampling, HDX figures in the prompt, explicit `google/gemini-2.5-flash` with `max_tokens=800` + fence stripping, per-country failure omission, atomic tmp+rename writes, status file (`output/daily_digests/status.json`). ~$0.70-1.50/month LLM cost.
- **`sitrep/daily_digest.py`** — single digest store/loader: schema validation (strings-only, D1), atomic writes (D11), 5-minute in-process index cache (D7), backward date walk ≤3 days (D5). Shared by the cron script and SSR so the schema lives in one place.
- **Crisis-page "Latest developments" section** — `/crisis/<slug>` SSR renders the newest valid digest (all LLM-derived fields pass `_sanitize_html`; D1). Sitemap `lastmod` for crisis pages now also considers the digest date (D12).
- **Daily digest routes** — `/digest` (archive index), `/digest/<date>` (day index, 404 on empty days), `/digest/<date>/<country>` (single-country page; "Data pending" fallback on malformed files). All digest pages enter the sitemap: single-country pages only when a live `/crisis/<slug>` exists, day indexes when they have content.
- **`/api/health` digest freshness** — `digest_fresh` + `digest_date` from the enrichment status file (non-critical observability; D12).
- **Weekly deep dives (Tier C)** — `scripts/generate_deep_dives.py` (Monday 06:45 UTC cron, after the 06:30 bulletin): top 3-5 crises of the coverage week, 300-500 words each ({headline, what_changed, why_it_matters, what_to_watch, information_gaps}) in `output/deep_dives/{coverage-week}/`. Bulletin pages render a "Weekly deep dives" section reading the files directly (no bulletin JSON field — ordering deadlock); new `/deep-dive/<week>/<slug>` SSR pages + sitemap entries.
- **Scheduler wiring** — enrichment step inside the `daily_scheduler.sh` lock block after the visual pipeline, wrapped `|| true` so it never fails the scheduler (D2/D8; ingest success is the only real gate). Weekly deep-dive cron added to `deploy/setup-crons-docker.sh` (Mon 06:45).
- **36 new tests** — loader schema/roundtrip/atomicity, backward walk, chunk-sampling dedupe, fence stripping, LLM field rejection, crisis-page section render/omit/sanitize/stale, digest routes E2E, deep-dive selection/routes/sitemap, bulletin deep-dive section, health freshness. Full suite: 342 passed, 6 skipped.
- **Design doc** — `docs/designs/daily-content-enrichment.md` (APPROVED; office-hours + adversarial spec review ×2 + eng review D1-D12 + outside-voice scope challenge resolved: founder chose to INCLUDE weekly deep dives and `/digest/<date>` sitemap entries (D10 reversal, 2026-09-17); kill criteria retained at the week-8 GSC review).

## [0.1.0] - Unreleased

### Added — Open-Source Foundation
- **AGPL v3 license** with Sightline copyright header (`LICENSE`)
- **Commercial dual-license** for enterprise use (`LICENSES/Commercial-LICENSE.md`)
  - 5 tiers: Individual, Team, Enterprise, Enterprise+, White-Label
- **Contributor License Agreement** (CLA) — individual + corporate (`CLA.md`)
- **Contributing guidelines** with Docker/local setup, MCP, PR workflow (`CONTRIBUTING.md`)
- **Contributor Covenant 2.1 Code of Conduct** (`CODE_OF_CONDUCT.md`)
- **Security policy** with responsible disclosure process (`SECURITY.md`)
- **BDFL governance model** document (`GOVERNANCE.md`)
- **Open-source roadmap** — 4-phase plan (removed — see README for roadmap overview)
- `DESKTOP_MODE` env flag — bypass Firebase auth for local/desktop use (loopback only)
- `FIREBASE_SERVICE_ACCOUNT_PATH` env var — env-driven Firebase SA path (no more hardcoded paths)
- `static/firebase-config.example.js` — template for Firebase web SDK config
- `.env.example` expanded with MCP, Brave, DESKTOP_MODE, FIREBASE_SERVICE_ACCOUNT_PATH sections
- `VERSION` file for SemVer tracking
- `CHANGELOG.md` (this file)

### Changed
- `static/auth.js` — hardcoded Firebase config removed; now loads from `window.FIREBASE_CONFIG`
  (via `firebase-config.js`). Falls back to DESKTOP_MODE if absent.
- `templates/index.html` — `firebase-config.js` script tag added before `auth.js`
- `auth.py` — `_dev_mode()` now checks `DESKTOP_MODE` in addition to `DEV_AUTH_BYPASS`
  (both require loopback `SERVER_HOST` for safety)
- `docker-compose.yml` — `DESKTOP_MODE`, `FIREBASE_SERVICE_ACCOUNT_PATH` env vars +
  `firebase-config.js` volume mount added
- `AGENTS.md` — open-source roadmap added to Documentation Index

### Security
- Git history scrubbed: personal `RELIEFWEB_APPNAME` values removed from all commits
- `static/firebase-config.js` added to `.gitignore` (user-specific, not tracked)
- `firebase-service-account.json` confirmed in `.gitignore` (was already there)

### Tests
- `tests/test_auth.py` — 2 new tests for `DESKTOP_MODE`:
  - `test_desktop_mode_true` — bypass works on loopback
  - `test_desktop_mode_non_loopback_blocked` — bypass blocked on 0.0.0.0

---

## Pre-0.1.0 History

Sightline was developed as a private project (under the internal name "RedAgent")
before being prepared for open-source release. The following major milestones
were achieved during private development:

- **Core platform:** Flask + LangGraph agent with 54 tools, ChromaDB vector store (24,955 chunks),
  SQLite database, Firebase Auth + RBAC
- **Tool groups (35 native):** ReliefWeb (17), HDX (7), News (4), GDACS (3), Weather (4),
  WorldBank (3), SQL (2)
- **MCP integration (19 tools):** arxiv (10), sequential-thinking (1), brave-search (8)
- **SITREP pipeline:** 10.5-stage clustering (UMAP + HDBSCAN), RRF retrieval, LLM synthesis
- **Weekly bulletin generator** + **country intelligence cards** (30 countries)
- **Guided Proposal V2:** manifest-driven donor compliance (6 donors: OCHA CBPF, USAID BHA,
  EuropeAID PRAG, ECHO, UNFPA, generic) with tool-calling generator + blind verifier +
  M&E reviewer + cross-section validation
- **Security hardening:** CSP, HSTS, XSS sanitization, path traversal protection, rate limiting,
  stream nonce auth, dev bypass loopback-only, 171+ tests
- **Docker deployment:** ARM64 single-stage build, Caddy auto-TLS, GitHub Actions CI/CD
- **Freemium preview:** dashboard, country cards, SITREP list for anonymous visitors

_Detailed commit history is available in the git log._
