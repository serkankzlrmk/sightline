# Contributing to Sightline

First off, thank you for considering contributing to Sightline! This document
describes how to set up your development environment and how to submit
contributions.

---

## 1. Project Context

Sightline is a humanitarian intelligence platform: a 54-tool data agent,
a 10-stage SITREP pipeline, a donor-specific proposal generator, and a
country intelligence dashboard.

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
docker compose up -d --build
# → http://localhost:5001
```

### Running Tests

```bash
pytest tests/ -v   # 169+ tests
```

### Linting

```bash
ruff check .
```

---

## 3. MCP Servers (optional)

The agent integrates three MCP (Model Context Protocol) servers:

- **arxiv** (uvx) — academic paper search
- **sequential-thinking** (npx) — structured reasoning
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
server.py                  — Flask app entry (config, middleware, blueprint registration)
config.py                  — Environment-driven configuration
auth.py                    — Firebase token verification, RBAC decorators
agent/                     — LangGraph agent (54 tools)
reliefweb_api/             — Tool groups (ReliefWeb, HDX, News, etc.)
blueprints/                — Flask blueprints + shared helpers
  helpers.py               — Shared utilities (DB, rate limit, chat CRUD)
  agent_bp.py              — Chat agent + model selection
  sitrep.py                — SITREP pipeline
  proposal.py              — Proposal V1
  guided_proposal.py       — Proposal V2 guided wizard
  proposal_pdf.py          — PDF export
  public_bp.py             — Map, dashboard, country data
  db_bp.py                 — Database search & reports
  admin_bp.py              — Admin panel & user management
templates/index.html       — SPA frontend
static/
  app.js                   — Core frontend (chat, SITREP, map, admin)
  proposal.js              — Proposal wizard (independently developable)
  auth.js                  — Firebase auth
tests/                     — Pytest tests (169 tests)
scripts/                   — Cron scripts (daily_ingest, bulletin)
```

---

## 8. Reporting Security Issues

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, see [`SECURITY.md`](./SECURITY.md) for the responsible disclosure
process.

---

## 9. Code of Conduct

Participation in this project is governed by the [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md).
By participating, you are expected to uphold this code.

---

_Thank you for contributing to Sightline! — Serkan Kizilirmak_
