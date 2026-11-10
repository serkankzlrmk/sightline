# Operations Runbook

## First checks

```bash
curl -s https://example.com/api/health
docker ps --filter name=sightline
docker logs --tail 200 sightline
```

`/api/health` reports booleans (`db`, `vector`, `llm`, data/digest freshness) and the
`release` commit. A `degraded` status usually points to a missing environment variable,
volume or provider key.

## Triage

| Symptom | Likely cause | Action |
|---|---|---|
| 5xx increase | deploy regression, DB lock, upstream outage | check recent release, inspect Admin > Errors, roll back if needed |
| `ERR-capacity` 503 | chat thread pool saturated | retry after a short delay; inspect `CHAT_MAX_CONCURRENT` and load |
| Tool error increase | upstream 429/5xx/timeout, auth failure | check tool error classes, disable failing source, fall back |
| Health degraded | DB/Chroma/LLM key/volume | inspect logs and container mounts |
| Disk usage high | output/Chroma growth | retention/cleanup, backup verification |
| High latency | CPU/RAM/DB locks | run load test, consider vertical upgrade or Redis |

## Error dashboard and audit

- `/app > Admin > Errors`: grouped fingerprints, recent events, request ids, resolve.
- `GET /api/admin/audit?days=30`: administrative actions with actor and target.
- `GET /api/admin/obs/health`: telemetry store and MCP readiness.

## Alerts and canary

```bash
python scripts/alert_check.py --dry-run --health-url https://example.com
python scripts/alert_check.py --health-url https://example.com
python scripts/canary.py --base-url https://example.com
```

Schedule alert checks every five minutes and canaries every ten minutes in the host
crontab. Configure `ALERT_WEBHOOK_URL` and/or Telegram credentials in the container
environment.

## Rollback

The deploy workflow stores the previous image tag and restores it when the health check
fails. Manual rollback uses the previous image tag:

```bash
docker pull ghcr.io/<owner>/sightline:<previous-sha>
docker rm -f sightline
docker run ... ghcr.io/<owner>/sightline:<previous-sha>
curl -sf http://127.0.0.1:5001/api/health
```

## Post-deploy checks

1. `/api/health` returns 200 with the new release.
2. `/app` loads and admin pages are reachable.
3. `/api/map/countries` returns data (warm cache).
4. Run the canary and one admin chat; verify Turns/Feedback in Observability.
5. Inspect Admin > Errors for new fingerprints.
