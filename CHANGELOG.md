# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
- **Open-source roadmap** — 4-phase plan (`docs/OPEN_SOURCE_ROADMAP.md`)
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
