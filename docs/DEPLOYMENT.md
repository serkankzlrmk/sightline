# Sightline — Deployment Guide

> For CI/CD, manual deploy, rollback, and production operations.

## Production Architecture

```
User → Caddy (80/443, auto-TLS) → Docker app (5001, gunicorn)
                                    ├── SQLite (reliefweb.db, chats.db)
                                    ├── ChromaDB (24,955 chunks)
                                    ├── MCP servers (arxiv + sequential + brave)
                                    └── OpenRouter API (LLM)
```

### Server
- **Hetzner CAX11 ARM64** (2 vCPU, 4GB RAM, Falkenstein)
- **IP:** YOUR_SERVER_IP
- **Domains:** YOUR_PROJECT_ID.com
- **OS:** Ubuntu 24.04 ARM64

### Docker Services
| Container | Image | Port | Purpose |
|-----------|-------|------|---------|
| `sightline` | `ghcr.io/serkankzlrmk/redagent:latest` | 127.0.0.1:5001 | Flask app + gunicorn |
| `sightline-caddy` | `caddy:2-alpine` | 80, 443 | Reverse proxy + auto-TLS |

### Docker Volumes (persistent data)
| Volume | Mount | Size | Content |
|--------|-------|------|---------|
| `reliefweb_db` | `/app/data` | 140 MB | reliefweb.db + chats.db |
| `chroma_data` | `/app/reliefweb_chroma` | 334 MB | ChromaDB vector store |
| `output_data` | `/app/output` | 336 MB | SITREP reports + bulletins + country summaries |
| `mcp_cache` | `/tmp/uv-cache` | ~50 MB | uvx package cache (arxiv MCP) |
| `npm_cache` | `/tmp/npm-cache` | ~50 MB | npx package cache (sequential + brave MCP) |
| `caddy_data` | `/data` | ~10 MB | Caddy TLS certificates + config |

---

## CI/CD Deploy (automatic — GitHub Actions)

### How it works
```
git push origin main
  → GitHub Actions: pytest (30s)
  → GitHub Actions: docker buildx ARM64 + push to GHCR (2-3 min)
  → GitHub Actions: SSH deploy (docker pull + restart + health check + rollback)
  → Canlıda! (~1 min total)
```

### Prerequisites
- GitHub Actions billing active (card added in GitHub Settings → Billing)
- GitHub Secrets configured (see below)
- GitHub repo Settings → Actions → General → Workflow permissions: "Read and write"

### GitHub Secrets (Settings → Secrets → Actions)
| Secret | Value | Purpose |
|--------|-------|---------|
| `SERVER_HOST` | `YOUR_SERVER_IP` | SSH host |
| `SERVER_USER` | `root` | SSH user |
| `SERVER_SSH_KEY` | Full content of `~/.ssh/id_ed25519` | SSH private key |

### Workflow file
`.github/workflows/deploy.yml` — 3 jobs: test → build → deploy

### Deploy process
1. **Test job:** `pytest tests/ -v` — fails = deploy aborted
2. **Build job:** Docker buildx ARM64, push to `ghcr.io/serkankzlrmk/redagent:latest` + `:SHA`
3. **Deploy job:** SSH to production, `docker pull`, `docker stop` + `docker run`, health check (10 retries), auto-rollback to previous image if health fails

### Rollback (automatic)
If health check fails after deploy, the workflow automatically:
1. Stops the new container
2. Restarts the previous image tag
3. Logs "Rollback to <prev_tag> complete"

### Manual rollback
```bash
ssh root@YOUR_SERVER_IP
docker stop sightline
docker run -d --name sightline ... ghcr.io/serkankzlrmk/redagent:<prev_sha>
```

---

## Manual Deploy (when CI/CD unavailable)

### Option A: Build locally + push to GHCR

```bash
# 1. Build ARM64 image and push
docker buildx build --platform linux/arm64 \
  -t ghcr.io/serkankzlrmk/redagent:latest \
  -t ghcr.io/serkankzlrmk/redagent:$(git rev-parse --short HEAD) \
  --push .

# 2. SSH to production and restart
ssh root@YOUR_SERVER_IP "
  docker pull ghcr.io/serkankzlrmk/redagent:latest
  cd /tmp/sightline-build && docker compose down
  docker compose up -d
"
```

### Option B: Build on production directly

```bash
ssh root@YOUR_SERVER_IP
cd /opt/reliefagent/repo && git fetch origin main:main
rm -rf /tmp/sightline-build
git clone -b main /opt/reliefagent/repo /tmp/sightline-build
cd /tmp/sightline-build
cp /opt/reliefagent/data/.env .env
cp /opt/reliefagent/data/firebase-service-account.json firebase-service-account.json
docker compose up -d --build
```

---

## Production Operations

### Check status
```bash
ssh root@YOUR_SERVER_IP
docker ps                          # See running containers
docker logs sightline --tail 50    # App logs
docker logs sightline-caddy --tail 50  # Caddy logs
curl http://localhost:5001/api/health  # Health check
```

### Restart app
```bash
ssh root@YOUR_SERVER_IP
cd /tmp/sightline-build
docker compose restart app
```

### View MCP tool status
```bash
docker logs sightline 2>&1 | grep "MCP:"
# Expected: "MCP: 19 tools loaded and ready (background init complete)"
```

### Update .env
```bash
ssh root@YOUR_SERVER_IP
nano /opt/reliefagent/data/.env     # Edit env vars
cd /tmp/sightline-build
docker compose restart app          # Restart to pick up changes
```

### Cron jobs
```bash
# View installed crons
ls /etc/cron.d/reliefagent-*

# Cron jobs run via docker exec:
# 06:00 UTC — daily ingest:        docker exec sightline python /app/scripts/daily_ingest.py
# Mon 06:30 UTC — weekly bulletin: docker exec sightline python /app/scripts/generate_bulletin.py --last-week
# Mon 07:00 UTC — country summaries: docker exec sightline python /app/scripts/generate_country_summaries.py
# 03:00 UTC — daily backup:        /opt/reliefagent/current/deploy/backup.sh

# Reinstall crons
cd /tmp/sightline-build && bash deploy/setup-crons-docker.sh
```

### Manual cron trigger
```bash
ssh root@YOUR_SERVER_IP
docker exec sightline python /app/scripts/daily_ingest.py
docker exec sightline python /app/scripts/generate_bulletin.py --last-week
docker exec sightline python /app/scripts/generate_country_summaries.py
```

### Backup
```bash
ssh root@YOUR_SERVER_IP
docker exec sightline sqlite3 /app/data/reliefweb.db ".backup /app/data/reliefweb_backup.db"
docker exec sightline cp /app/data/reliefweb_backup.db /backup/
```

---

## Environment Variables

### Secrets (in /opt/reliefagent/data/.env)
- `OPENROUTER_API_KEY` — LLM API key
- `SECRET_KEY` — Flask session key
- `ADMIN_UIDS` — Firebase admin UIDs
- `HDX_APP_IDENTIFIER` — HDX API auth
- `NEWS_API_KEY` — NewsAPI key
- `BRAVE_API_KEY` — Brave Search MCP key
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `SUPABASE_DB_URL` — Supabase (optional)
- `RELIEFWEB_APPNAME` — ReliefWeb API appname
- `firebase-service-account.json` — Firebase Admin SDK (file, bind-mounted)

### Docker-specific (set in docker-compose.yml environment:)
- `DB_PATH=/app/data/reliefweb.db` — override .env path for container
- `CHATS_DB_PATH=/app/data/chats.db`
- `CHROMA_DIR=/app/reliefweb_chroma`
- `CONTAINER_MODE=true` — gunicorn binds 0.0.0.0, logs to stdout

### MCP config
- `MCP_ARXIV_ENABLED=true`
- `MCP_SEQUENTIAL_THINKING_ENABLED=true`
- `MCP_BRAVE_ENABLED=true` (requires `BRAVE_API_KEY`)
- `BRAVE_DAILY_LIMIT=30` — rate limit to protect free credit

---

## First-time Setup (reference — already done)

```bash
# 1. Install Docker on VM
curl -fsSL https://get.docker.com | sh

# 2. Create volumes
docker volume create reliefweb_db chroma_data output_data mcp_cache npm_cache caddy_data caddy_config

# 3. Copy data to volumes
docker run --rm -v reliefweb_db:/data -v /opt/reliefagent/data:/src alpine cp /src/reliefweb.db /data/
docker run --rm -v reliefweb_db:/data -v /opt/reliefagent/data:/src alpine cp /src/chats.db /data/
docker run --rm -v chroma_data:/data -v /opt/reliefagent/data:/src alpine sh -c 'cp -r /src/reliefweb_chroma/* /data/'
docker run --rm -v output_data:/data -v /opt/reliefagent/data:/src alpine sh -c 'cp -r /src/output/* /data/'

# 4. Clone repo + configure
git clone -b main /opt/reliefagent/repo /tmp/sightline-build
cd /tmp/sightline-build
cp /opt/reliefagent/data/.env .env
cp /opt/reliefagent/data/firebase-service-account.json firebase-service-account.json

# 5. Start
docker compose up -d --build

# 6. Install crons
bash deploy/setup-crons-docker.sh

# 7. Disable old services
systemctl disable nginx reliefagent
```