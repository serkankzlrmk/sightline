# SRE Runbook — Sightline (kısa)

> Alarm geldiğinde ilk 5 dakika. Tarih: 2026-11-10.

## 1. İlk kontrol

```bash
curl -s https://<domain>/api/health | jq
docker ps --filter name=sightline
docker logs --tail 200 sightline
```

- `/api/health`: `status=ok/degraded`, `db`, `vector`, `llm`, `release`.
- `degraded` → eksik env/volume/LLM key; `docker logs`'ta ipucu.

## 2. Hata panosu

- `/app → Admin → Errors`: son 7 gün, unresolved, route/kind.
- `GET /api/admin/errors/groups?days=1` → fingerprint + sample.
- Aynı `request_id` ile log/SSE eşleştir.

## 3. Sık nedenler

| Belirti | Olası neden | Aksiyon |
|---|---|---|
| 5xx artışı | deploy/regresyon, DB kilit | son release'i kontrol, rollback |
| `ERR-capacity` 503 | chat thread doygun | bekleyip retry; gerekirse limit/thread |
| Tool hata artışı | upstream 429/5xx, timeout | circuit/fallback; tool'u geçici kapat |
| Health degraded | DB/Chroma/LLM key | volume/env kontrol |
| Disk alarmı | output/chroma büyümesi | retention/temizlik |
| Yüksek latency | CPU/RAM/DB lock | load test, vertical/Redis |

## 4. Rollback

```bash
# önceki image tag (CI deploy önceki tag'i saklar)
docker pull ghcr.io/serkankzlrmk/sightline:<previous-sha>
docker rm -f sightline
docker run ... ghcr.io/serkankzlrmk/sightline:<previous-sha>
curl -sf http://127.0.0.1:5001/api/health
```

## 4.1 Canary / audit / maliyet

```bash
python scripts/canary.py --base-url https://<domain>
curl -s https://<domain>/api/admin/audit?days=7   # admin token
```

- Canary fail → errors.db `kind=canary`, webhook.
- Audit: kim hangi admin işlemini yaptı (`audit:*`).
- Maliyet alarmı: `ALERT_DAILY_COST_USD` / `ALERT_USER_DAILY_COST_USD`.

## 5. Alarmlar

```bash
python scripts/alert_check.py --dry-run
python scripts/alert_check.py --health-url https://<domain>
```

Eşik/cooldown `.env`: `ALERT_5XX_RATE`, `ALERT_TOOL_ERROR_RATE`,
`ALERT_MIN_REQUESTS`, `ALERT_COOLDOWN_MIN`.

## 6. Yük testi

```bash
python scripts/load_test.py --concurrency 20 --requests 200
```

Rapor: `docs/LOAD_TESTING.md`.
