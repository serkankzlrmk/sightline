# Quick Start — 5 Minute Guide

This guide gets Sightline running on your machine in under 5 minutes.

---

## Prerequisites

- **Docker** (recommended) — [install Docker Desktop](https://docs.docker.com/get-docker/)
- **OR** Python 3.12+ — [install Python](https://www.python.org/downloads/)

---

## Step 1: Clone & Configure

```bash
git clone https://github.com/serkankzlrmk/sightline.git
cd sightline
cp .env.example .env
```

Edit `.env` and fill in your API keys. **You can start with just these:**

```bash
# Required: LLM access
OPENROUTER_API_KEY=sk-or-v1-your-key-here

# Required: ReliefWeb API
RELIEFWEB_APPNAME=your-appname

# Everything else is optional for first run
```

> **No API keys at all?** Sightline still starts — GDACS, Open-Meteo, and World Bank
> are keyless. You'll see `status: degraded` on `/api/health`, but the app works
> for those data sources.

---

## Step 2: Start the Server

### Docker (recommended)

```bash
docker compose up -d --build
```

Wait ~30-60 seconds for first build (downloads Python deps + MCP packages).

```bash
# Check if it's running
curl http://localhost:5001/api/health
# → {"status":"ok","db":true,"vector":true,"llm":true,"hdx":false,"news":false}
```

### Local Python

```bash
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu
SERVER_HOST=127.0.0.1 DESKTOP_MODE=true python server.py
```

---

## Step 3: Open the App

Open **http://localhost:5001** in your browser.

### Auth Modes

| Mode | How | What you get |
|---|---|---|
| **DESKTOP_MODE** | `DESKTOP_MODE=true` + `SERVER_HOST=127.0.0.1` | All features unlocked, no login needed |
| **Firebase** | Copy `static/firebase-config.example.js` → `static/firebase-config.js`, fill in your Firebase web config | Google Sign-In, RBAC roles, freemium preview |

For local development, `DESKTOP_MODE` is easiest.

---

## Step 4: Ingest Data (first time only)

The vector database (ChromaDB) starts **empty**. To populate it:

### Option A: Manual ingest via UI

1. Open the app, go to the **Database** tab (needs auth or DESKTOP_MODE)
2. Click **"Ingest Reports"** — fetches recent ReliefWeb reports
3. Wait for ingest to complete (status shows in the UI)

### Option B: Via script

```bash
# Ingest yesterday's ReliefWeb reports
python scripts/daily_ingest.py

# Or via Docker
docker exec sightline python /app/scripts/daily_ingest.py
```

---

## Step 5: Try the Features

### Chat with the Agent

Go to the **Chat** tab. Try:

- *"What are the latest disasters in Sudan?"*
- *"Give me a situational overview of the humanitarian crisis in Gaza"*
- *"Search for reports about food security in the Sahel region"*

The agent uses ReliefWeb, HDX, GDACS, news, and weather APIs directly.

### Generate a SITREP

Go to the **SITREP** tab:

1. Enter a country (e.g., "Sudan")
2. Select a date range
3. Click **Generate**
4. Watch the 10.5-stage pipeline run (clustering → questions → answers → synthesis)

### Create a Proposal

Go to **Proposal → Start Guided Proposal**:

1. Select a donor (e.g., USAID BHA)
2. Step 1: Situational Overview (auto-generates from ReliefWeb + HDX)
3. Step 2: Strategic Approach
4. Step 3: Implementation & Coordination
5. Step 4: Budget & Compliance
6. Export as PDF

### View Country Intelligence

The dashboard shows 143 countries on the map. Click any country to see:
- Severity level
- Report count
- Key themes
- HDX figures (if available)

---

## MCP Servers (optional)

The agent integrates 3 MCP servers. To enable:

```bash
# Install uv (for arxiv)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Node.js 20+ (for sequential-thinking + brave-search)
# https://nodejs.org/ or use nvm

# Pre-warm MCP packages
uvx arxiv-mcp-server --help
npx -y @modelcontextprotocol/server-sequential-thinking --help
npx -y @brave/brave-search-mcp-server --help
```

Without MCP servers, the agent still works with its 35 native tools.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `status: degraded` on /api/health | Missing API keys — check `.env` |
| ChromaDB errors | Delete `reliefweb_chroma/` and restart |
| Port 5001 in use | Change `SERVER_PORT` in `.env` |
| MCP cold start delay | First use takes ~10s — this is normal (subprocess startup) |
| Firebase auth fails | Ensure `firebase-config.js` exists + `DESKTOP_MODE=false` |
| Out of memory (4GB VM) | Set `BULLETIN_MAX_COUNTRIES=15` in `.env` |

---

## Next Steps

- Read [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) to understand the system
- Read [`docs/SELF_HOSTING.md`](SELF_HOSTING.md) for production deployment
- Read [`CONTRIBUTING.md`](../CONTRIBUTING.md) to contribute
- Read [`docs/ROADMAP.md`](ROADMAP.md) for the feature roadmap

---

_Sightline Quick Start v0.1.0_
