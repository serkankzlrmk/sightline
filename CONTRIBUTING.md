# Contributing to Sightline

First off, thank you for considering contributing to Sightline! This document
describes how to set up your development environment and how to submit
contributions.

---

## 1. Project Context

Sightline is a humanitarian intelligence platform: a 46-native-tool data agent
(60 tools active with MCP), a 10-stage SITREP pipeline, an embedded Proposal
Studio, country intelligence cards, and LLM evaluation/observability.

**License:** AGPL v3 (open core) + Commercial dual-license. All contributors
must sign the CLA (Section 5 below).

**Governance:** BDFL (Benevolent Dictator For Life) — the maintainer
(Serkan Kizilirmak) makes final decisions. See [`GOVERNANCE.md`](./GOVERNANCE.md).

---

## 2. Quick Start

### Prerequisites

- Python 3.12+
- Node.js 20+ and npm (for MCP servers — optional, see below)
- `uv` or `uvx` (for arxiv MCP server — optional)
- Docker

```bash
git clone https://github.com/serkankzlrmk/sightline.git
cd sightline
cp .env.example .env
# Edit .env — fill in your API keys (see .env.example for all ~75 variables)
python -m venv .venv
.venv/bin/pip install -r requirements.txt
SERVER_HOST=127.0.0.1 DESKTOP_MODE=true .venv/bin/python server.py
# → http://127.0.0.1:5001/app

# Production is CI-driven (push main → GitHub Actions → docker run).
# docker-compose.yml is legacy and not runnable; see docs/SYSTEM_DESIGN.md.
```

### Running Tests

```bash
pytest tests/ -v   # 436 passed, 6 skipped (current suite)
```

### Linting

```bash
ruff check .
ruff format --check .
npm run lint && npm run build
```

---

## 3. MCP Servers (optional)

The agent integrates three MCP (Model Context Protocol) servers:

- **arxiv** (uvx) — academic paper search (10-19 tools depending on version)
- **sequential-thinking** (npx) — structured reasoning
- **brave-search** (optional, `MCP_BRAVE_ENABLED=true` + `BRAVE_API_KEY`)
- **brave-search** (npx) — web/news/image search

To enable them locally:

```bash
# Install uv (for arxiv)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Node.js 20+ (for sequential-thinking + brave-search)
# (https://nodejs.org/ or via nvm)

# Pre-warm MCP packages (avoids 30-60s cold start)
uvx arxiv-mcp-server --help
npx -y @modelcontextprotocol/server-sequential-thinking --help
npx -y @brave/brave-search-mcp-server --help
```

If you skip MCP servers, the agent still works with its 35 native tools.

---

## 4. How to Contribute

### 4.1 Find or Open an Issue

1. Check [existing issues](https://github.com/serkankzlrmk/sightline/issues)
   for something you'd like to work on.

2. If you have a new feature or bug in mind, **open an issue first** to discuss
   it with the maintainer before starting work. This avoids wasted effort if
   the change is out of scope or has a different approach in mind.

### 4.2 Development Workflow

```bash
# 1. Fork the repo on GitHub
# 2. Clone your fork
git clone https://github.com/YOUR_USERNAME/sightline.git
cd sightline

# 3. Add upstream remote
git remote add upstream https://github.com/serkankzlrmk/sightline.git

# 4. Create a feature branch (from main, up to date)
git checkout main
git pull upstream main
git checkout -b feat/your-feature-name
# or: git checkout -b fix/your-bug-fix-name

# 5. Make your changes. Commit with clear messages (see below).

# 6. Run tests + lint
pytest tests/ -v
ruff check .

# 7. Push to your fork
git push origin feat/your-feature-name

# 8. Open a pull request against `main`
```

### 4.3 Commit Message Convention

We use a simplified conventional-commits format:

```
<type>: <short description>

<optional longer description>
```

Types:

- `feat`: new feature (e.g., `feat: add JICA donor manifest`)
- `fix`: bug fix (e.g., `fix: proposal PDF export crashing on empty budget`)
- `docs`: documentation (e.g., `docs: update README architecture diagram`)
- `refactor`: code restructuring (e.g., `refactor: extract donor validation utils`)
- `test`: test additions (e.g., `test: add ECHO PRAG manifest unit tests`)
- `chore`: tooling, deps, CI (e.g., `chore: bump chromadb to 0.5.20`)
- `security`: security fix (e.g., `security: sanitize ReliefWeb report input`)

Please keep the first line under 72 characters.

### 4.4 Pull Request Checklist

Before opening a PR:

- [ ] Tests pass: `pytest tests/ -v`
- [ ] Lint passes: `ruff check .`
- [ ] Commit messages follow the convention above
- [ ] No secrets / API keys / `.env` files committed
- [ ] New features have tests (try to maintain or improve coverage)
- [ ] Documentation updated (README, docstrings) if relevant
- [ ] CLA signed (Section 5 below)

### 4.5 Pull Request Review

1. The maintainer will review your PR, usually within 1-2 weeks
   (this is a side project, so please be patient).
2. Address feedback by pushing more commits to the same branch
   (do not close and re-open the PR).
3. Once approved, the maintainer will squash-merge your PR into `main`.

---

## 5. CLA (Contributor License Agreement)

All contributors must sign the CLA before their PRs can be merged.

The CLA grants the maintainer the right to include your Contribution in both
the AGPL v3 open-source release and the Commercial License release of the
Project, without seeking additional permission.

- For individuals: sign electronically via the [CLA Assistant](https://cla-assistant.io/)
  GitHub App when you open your first PR.
- For corporate contributors: a CLA signed by an authorized representative of
  your employer is required. Contact the maintainer to arrange this.

The full CLA text is in [`CLA.md`](./CLA.md). Signing is a one-time action —
once you sign, all future PRs are covered.

---

## 6. Code Style

- **Python:** `ruff` is the source of truth. Configuration lives in
  `pyproject.toml` or `ruff.toml` at the repo root.
- **JavaScript:** No enforced linter yet, but please follow the style of
  existing files in `static/`.
- **Type hints:** New or changed public API surface (server.py, blueprints/*,
  agent/relief_agent.py, reliefweb_api/*_tools.py) must have type hints.
- **Comments:** Code should be self-documenting. Comments should explain
  "why", not "what". Avoid big blocks of commented-out dead code.
- **Docstrings:** All public functions and classes must have docstrings
  (Google or Sphinx style, your preference, just be consistent).

---

## 7. Project Structure (quick reference)

See the directory structure in `CONTRIBUTING.md` for an overview.

```
server.py                  — Flask app init, request IDs, error handlers, middleware
config.py                  — Environment-driven configuration (~159 env reads)
auth.py                    — Firebase token verification, RBAC decorators
agent/                     — LangGraph agent, prompt, memory, tool resilience
reliefweb_api/             — External clients/tools (ReliefWeb, HDX, ACLED, FTS, ...)
blueprints/                — 14 route modules + shared helpers (~121 routes)
  helpers.py               — DB, rate limits, chat CRUD, events/audit, jobs
  agent_bp.py              — Chat agent + SSE + feedback
  sitrep.py                — SITREP pipeline + bulletin
  public_bp.py             — Map/dashboard/country data
  seo_bp.py                — SSR publication pages + sitemap/robots
  admin_bp.py              — Admin panel & user management
  obs_bp.py                — Observability/eval/calibration API
  error_bp.py              — Client errors + admin Errors API
  ...                      — main, auth, db, hdx, news, ingest
observability/             — obs.db, error tracking, calibration metrics
templates/                 — SPA + SSR templates
static/                    — SPA modules (esbuild bundle in static/dist)
proposal/                  — Proposal Studio (separate repo, embedded)
tests/                     — Pytest suite (436 collected)
scripts/                   — Ingest, bulletin, eval, alerts, canary, load test
```

---

## 8. Documentation and release policy

Public documentation is limited to the files tracked in git: `README.md`,
`docs/SYSTEM_DESIGN.md`, `docs/TOOLS.md`, `docs/EVALUATION.md`,
`docs/CALIBRATION.md`, `docs/ERROR_MONITORING.md`, `docs/LOAD_TESTING.md`,
`docs/SRE_RUNBOOK.md`, `tests/README.md`, and this file. Internal notes
(`AGENTS.md`, `docs/CODEMAP.md`, `docs/DEVELOPMENT.md`, `docs/DEPLOYMENT.md`,
`docs/ROADMAP.md`, design notes and research scratchpads) are kept locally and ignored by
git; they are not part of the public repository.

Documentation changes are committed separately from code changes. The deploy workflow
ignores documentation-only pushes (`**.md`, `docs/**`, `LICENSES/**`), so documentation can
be published through CI checks without rebuilding the production image.

## 9. Reporting Security Issues

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, see [`SECURITY.md`](./SECURITY.md) for the responsible disclosure
process.

---

## 9. Code of Conduct

Participation in this project is governed by the [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md).
By participating, you are expected to uphold this code.

---

_Thank you for contributing to Sightline! — Serkan Kizilirmak_
