# Error Monitoring — Sightline

> Merkezi hata yakalama: backend, frontend, tool, LLM ve SSE hataları tek yerde
> toplanır; admin panelinden görülür; eşik aşımında alarm üretir.
> Tarih: 2026-11-10 · Durum: local, canlıya alınmadı.

---

## 1. Neden ayrı `errors.db`?

- `obs.db` turn telemetrisi `OBS_ENABLED=false` ile kapatılabilir; hata izleme
  kapanmamalı.
- `chats.db` yazma yolu sohbetlerle paylaşılır; hata yazıları burayı kilitlemesin.
- Retention/backup ayrı yönetilir.

Env: `ERRORS_DB_PATH` (default `errors.db`), `ERRORS_ENABLED`,
`ERRORS_RETENTION_DAYS=90`, `ERRORS_SALT` (uid hash tuzu), `RELEASE_SHA`.

---

## 2. Akış

```
Backend exception ─┐
Frontend JS error ──┤
Tool failure ───────┼→ error_tracking.record_error()
LLM/SSE failure ────┤        │ fingerprint + sanitize
Job failure ────────┘        ▼
                       errors.db error_events
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
      Admin → Errors   scripts/alert_check.py  request_id in logs/UI
```

- Her istek `X-Request-ID` alır; hata yanıtlarında `request_id` + `ERR-xxxxxxxx`.
- Fingerprint: `kind + normalize(route) + exception_type + stack-top + message`.
  Aynı bug aynı grupta; farklı route yeni grup.
- Sanitize: Bearer/token/nonce/e-posta/uzun hex temizlenir; gövde saklanmaz;
  uid SHA-256 + salt ile hash'lenir.

---

## 3. Yakalama noktaları

| Katman | Nerede | Ne kaydedilir |
|---|---|---|
| Backend | `server.py` global error handlers | exception, route, status 500, stack hash, request_id |
| Frontend | `static/error-reporter.js` | `window.onerror`, `unhandledrejection`, ağ hatası |
| Tool | `blueprints/agent_bp.py` `tool_done` | tool adı, grup, server, `error_class` (timeout/auth/rate_limit/...) |
| LLM | `agent_bp` chat exception | model, mode, stack; SSE `error` event'inde `code` |
| Client API | `POST /api/client-errors` | rate-limit 20/dk/IP, gövde ≤16 KB, dedupe fingerprint |

`tool_calls.error_class` ayrıca `obs.db`'de saklanır; tool tablosunda görülebilir.

---

## 4. Admin paneli

`/app → Admin → Errors`:

- KPI: son 7 gün hata, unresolved, grup, etkilenen kullanıcı, istek, 5xx oranı.
- **Grouped errors**: kind / route / count / users / first-last / örnek mesaj / Resolve.
- **Recent events**: zaman, kind, route, status, request_id, mesaj.
- **Create test error** butonu uçtan uca test için.

API: `GET /api/admin/errors/{summary,groups,recent,<fingerprint>}`,
`POST /api/admin/errors/<fingerprint>/resolve`, `POST /api/admin/errors/test`.

---

## 5. Alarmlar

`scripts/alert_check.py` cron ile 5 dakikada bir çalışır:

```bash
# .env: ALERT_WEBHOOK_URL veya ALERT_TELEGRAM_BOT_TOKEN/CHAT_ID
python scripts/alert_check.py                 # gerçek gönderim
python scripts/alert_check.py --dry-run       # sadece rapor
python scripts/alert_check.py --test          # test mesajı
python scripts/alert_check.py --health-url https://sightlinehumanitarian.com
```

Eşikler (env): `ALERT_5XX_RATE=0.02`, `ALERT_TOOL_ERROR_RATE=0.10`,
`ALERT_MIN_REQUESTS=20`, `ALERT_COOLDOWN_MIN=30`. Cooldown `errors.db.alert_state`.

Örnek crontab (host):

```cron
*/5 * * * * cd /opt/reliefagent/current && docker exec sightline python /app/scripts/alert_check.py --health-url http://127.0.0.1:5001 >> /var/log/sightline-alerts.log 2>&1
```

---

## 6. Gizlilik / retention

- Gövde, Authorization, query string saklanmaz.
- E-posta/token/nonce scrub; uid hash; IP saklanmaz (client endpoint IP'si yalnız
  rate-limit için bellekte).
- 90 gün retention (`prune` schema init'te); admin-only okuma.
- Frontend raporları sayfa başına 20 ile sınırlı; sunucu 20/dk/IP.

---

## 7. Opsiyonel Sentry / OTel

İlk sürümde ek servis yok. İleride:
- `SENTRY_DSN` ile Flask + JS SDK (stack trace/source map).
- OTel SDK + OTLP exporter → Grafana/Tempo/Loki (metrik/trace).
Küçük VM'de self-host ağır; Sentry SaaS/GlitchTip dış servis önerilir.

---

## 7.1 Local smoke (2026-11-10)

- `/api/does-not-exist` → 404 JSON, `X-Request-ID` ve `ERR-xxxxxxxx`.
- `POST /api/client-errors` → 202; admin Errors'ta frontend grubu.
- `POST /api/admin/errors/test` → panelde backend grubu.
- Load test 100 istek → `errors_5xx: 0`; summary istek sayacı 217'ye çıktı.
- `scripts/alert_check.py --dry-run` → eşik altı, alarm yok (test ortamı).

---

## 7.2 Canary, audit, cost, tool resilience

**Canary** (`scripts/canary.py`, cron 5–15 dk): `/api/health` (status=ok),
`/api/public/stats`, `/crisis`; hata olursa `kind=canary` kaydı + webhook.
`--check-map` yalnız sıcak cache'te kullanılmalı.

**Audit log**: admin rol/config/silme/eval/kalibrasyon/error-resolve işlemleri
`events` tablosuna `audit:<action>` olarak yazılır; `GET /api/admin/audit?days=30`.

**Maliyet alarmı**: `scripts/alert_check.py` artık günlük toplam maliyet
(`ALERT_DAILY_COST_USD`) ve tek kullanıcı maliyetini (`ALERT_USER_DAILY_COST_USD`)
de kontrol eder (obs.db `turns.cost`).

**Tool resilience** (`agent/tool_resilience.py`): timeout/429/5xx için 2 deneme
(exponential backoff), art arda 3 hatada 60 sn circuit open; auth/validation'da
retry yok. `TOOL_RETRY_ATTEMPTS`, `TOOL_CIRCUIT_THRESHOLD`,
`TOOL_CIRCUIT_COOLDOWN_SECONDS` ile ayarlanır.

**Release**: deploy `RELEASE_SHA=${{ github.sha }}` geçirir; `/api/health` ve
error kayıtları release taşır.

---

## 8. Test

```bash
pytest tests/test_error_tracking.py tests/test_error_api.py tests/test_alert_check.py tests/test_load_test.py -q
```

Kabul:
- `/api/missing` → 404 JSON + `request_id`, `X-Request-ID`.
- Kasıtlı 500 → panelde backend grubu; log'da aynı ID.
- Frontend hatası → client-errors kaydı.
- Admin test error → panelde görünür.
- `alert_check --dry-run` eşik raporu; test mesajı gönderilebilir.
