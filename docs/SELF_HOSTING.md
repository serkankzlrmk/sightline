# Self-Hosting Guide

This guide covers deploying Sightline on your own server.

---

## Option 1: Docker Compose (recommended for VPS)

Best for: VPS (Hetzner, DigitalOcean, AWS EC2), 2+ vCPU, 4+ GB RAM.

### Prerequisites

- Docker + Docker Compose installed
- A domain name (for auto-TLS via Caddy)
- API keys (at minimum: `OPENROUTER_API_KEY`, `RELIEFWEB_APPNAME`)

### Steps

```bash
# 1. Clone
git clone https://github.com/serkankzlrmk/sightline.git
cd sightline

# 2. Configure
cp .env.example .env
# Edit .env:
#   SERVER_HOST=0.0.0.0
#   SERVER_DEBUG=false
#   DESKTOP_MODE=false
#   Fill in API keys
#   Set SECRET_KEY to a random 64-char string

# 3. Firebase (optional — for Google Sign-In)
# Place firebase-service-account.json in the project root
# Copy static/firebase-config.example.js → static/firebase-config.js
# Fill in your Firebase web config

# 4. Edit Caddyfile — replace with your domain
# In Caddyfile:
#   sightline.example.com {
#     reverse_proxy sightline:5001
#   }

# 5. Create Docker volumes
docker volume create reliefweb_db
docker volume create chroma_data
docker volume create output_data
docker volume create caddy_data
docker volume create caddy_config

# 6. Start
docker compose up -d --build

# 7. Verify
curl http://localhost:5001/api/health
# → {"status":"ok","db":true,"vector":true,"llm":true,...}

# 8. Caddy auto-obtains Let's Encrypt certs on first request
# → https://sightline.example.com
```

### Cron Jobs (for live data)

```bash
# Edit crontab on the host
crontab -e

# Daily ingest — 06:00 UTC
0 6 * * * docker exec sightline python /app/scripts/daily_ingest.py

# Weekly bulletin — Monday 06:30 UTC
30 6 * * 1 docker exec sightline python /app/scripts/generate_bulletin.py --last-week

# Country summaries — Monday 07:00 UTC
0 7 * * 1 docker exec sightline python /app/scripts/generate_country_summaries.py

# Daily backup — 03:00 UTC
0 3 * * * /path/to/sightline/deploy/backup.sh
```

---

## Option 2: Local Desktop (no Docker)

Best for: Local development, testing, offline use.

```bash
git clone https://github.com/serkankzlrmk/sightline.git
cd sightline
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu

cp .env.example .env
# Edit .env:
#   SERVER_HOST=127.0.0.1
#   DESKTOP_MODE=true
#   Fill in API keys

python server.py
# → http://localhost:5001
```

**DESKTOP_MODE=true** bypasses Firebase auth. All features unlocked locally.
No `firebase-config.js` needed.

---

## Option 3: Manual Deployment (without Docker)

Best for: Servers where Docker is not available.

### Prerequisites

- Python 3.12+
- Node.js 20+ (for MCP servers)
- `uv` (for arxiv MCP server)
- nginx or Caddy (for TLS termination)

### Steps

```bash
# 1. Clone & install
git clone https://github.com/serkankzlrmk/sightline.git
cd sightline
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu

# 2. Configure
cp .env.example .env
# Edit .env with your settings

# 3. Firebase (optional)
# Place firebase-service-account.json in project root
# Copy static/firebase-config.example.js → static/firebase-config.js

# 4. Run with gunicorn
python -m gunicorn -c deploy/gunicorn.conf.py server:app

# 5. Set up nginx/Caddy as reverse proxy
# Example Caddyfile:
# sightline.example.com {
#   reverse_proxy 127.0.0.1:5001
# }
```

---

## Resource Requirements

| Component | Minimum | Recommended |
|---|---|---|
| CPU | 1 vCPU | 2 vCPU |
| RAM | 2 GB | 4 GB |
| Disk | 2 GB | 5 GB |
| Network | Required for APIs + LLM | — |

### ARM64 (Raspberry Pi, Hetzner CAX)

Sightline runs on ARM64. The Dockerfile is single-stage ARM64-compatible.
No changes needed — `docker compose up --build` works.

---

## Environment Variables

See [`.env.example`](../.env.example) for all ~75 variables. Key ones for production:

| Variable | Production Value |
|---|---|
| `SERVER_HOST` | `0.0.0.0` |
| `SERVER_DEBUG` | `false` |
| `DESKTOP_MODE` | `false` |
| `SSL_VERIFY` | `true` |
| `CORS_ORIGINS` | `https://yourdomain.com` |
| `SECRET_KEY` | Random 64-char string |
| `DAILY_MESSAGE_LIMIT` | `10` (adjust per your policy) |

---

## Backup

```bash
# Backup SQLite + ChromaDB
docker exec sightline tar czf - /app/data /app/reliefweb_chroma > sightline-backup-$(date +%Y%m%d).tar.gz

# Or use the backup script
./deploy/backup.sh
```

Restore:

```bash
docker exec -i sightline tar xzf - -C / < sightline-backup-20250101.tar.gz
docker compose restart
```

---

## Monitoring

### Health Check

```bash
curl http://localhost:5001/api/health
# → {"status":"ok","db":true,"vector":true,"llm":true,"hdx":true,"news":true}
```

- `status: ok` — all critical checks pass
- `status: degraded` — some checks failed (check individual flags)
- HTTP 200 if ok, HTTP 503 if degraded

### Logs

```bash
# Docker
docker compose logs -f sightline

# Gunicorn (manual)
journalctl -u sightline -f
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| ChromaDB lock errors | Restart the app (single-worker constraint) |
| OOM on 4GB VM | Set `BULLETIN_MAX_COUNTRIES=15`, `BULLETIN_CHUNK_LIMIT=100` |
| MCP cold start | First agent message takes ~10s — normal |
| Firebase auth fails | Check `firebase-config.js` + service account JSON |
| Caddy TLS fails | Ensure ports 80 + 443 are open, domain DNS is correct |
| ReliefWeb API 429 | Reduce ingest frequency or respect rate limits |

---

_Sightline Self-Hosting Guide v0.1.0_
