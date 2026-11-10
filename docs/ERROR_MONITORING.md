# Error Monitoring

Sightline captures backend, frontend, tool, LLM and streaming failures in a dedicated
store and exposes them to administrators.

## Storage

`errors.db` is separate from turn telemetry so error monitoring still works when
`OBS_ENABLED=false`.

| Table | Content |
|---|---|
| `error_events` | one row per occurrence: kind, route, method, status, request id, release, uid hash, exception, sanitized message, stack hash, context, resolved |
| `error_stats_minute` | per-minute request/error counters for SLOs and alerts |
| `alert_state` | cooldown bookkeeping for alert checks |

Configuration: `ERRORS_DB_PATH`, `ERRORS_ENABLED`, `ERRORS_RETENTION_DAYS=90`,
`ERRORS_SALT`, `RELEASE_SHA`.

## Request correlation

- Every request receives `X-Request-ID`; API errors include `request_id` and an
  `ERR-xxxxxxxx` code.
- Chat streaming includes the request id and code in the SSE `error` event.
- Error fingerprints combine kind, normalized route, exception type, stack top and
  message so repeated failures group together.

## Capture points

| Layer | Source |
|---|---|
| Backend | global `HTTPException`/`Exception` handlers in `server.py` |
| Frontend | `static/error-reporter.js` (`window.onerror`, `unhandledrejection`, fetch failures) |
| Tool | `tool_calls.error_class` plus `error_events` for structured/JSON errors |
| LLM | chat exceptions and provider failures with sanitized stack |
| Jobs | SITREP/bulletin failures with exit status and stderr excerpt |

`POST /api/client-errors` is public but rate-limited (20/min/IP, 16 KB body limit) and
sanitizes tokens, emails and nonces before storage.

## Admin interface

`/app > Admin > Errors` shows:

- error counts, unresolved groups, affected users, request and 5xx rates;
- grouped errors (kind, route, count, users, first/last, sample message);
- recent events with request id and status;
- resolve action and a synthetic test-error action.

APIs: `GET /api/admin/errors/summary|groups|recent`, `GET /api/admin/errors/<fingerprint>`,
`POST /api/admin/errors/<fingerprint>/resolve`, `POST /api/admin/errors/test`.

## Alerts

`scripts/alert_check.py` is intended for cron (every 5 minutes):

```bash
python scripts/alert_check.py --dry-run --health-url https://example.com
python scripts/alert_check.py --test
```

Thresholds: 5xx rate (`ALERT_5XX_RATE`), tool error rate (`ALERT_TOOL_ERROR_RATE`),
daily cost (`ALERT_DAILY_COST_USD`), per-user cost (`ALERT_USER_DAILY_COST_USD`),
minimum request sample (`ALERT_MIN_REQUESTS`) and cooldown (`ALERT_COOLDOWN_MIN`).
Delivery uses `ALERT_WEBHOOK_URL` and/or Telegram (`ALERT_TELEGRAM_BOT_TOKEN`,
`ALERT_TELEGRAM_CHAT_ID`). A health URL can be probed with `--health-url`.

## Synthetic canary

`scripts/canary.py --base-url https://example.com` checks `/api/health`,
`/api/public/stats` and `/crisis`; failures are recorded as `kind=canary` and can send the
same webhook/Telegram alert.

## Audit log

Administrative actions are stored as `audit:<action>` in `chats.db.events` and exposed at
`GET /api/admin/audit?days=30`. Covered actions include role changes, config updates,
deletions, evaluation runs, calibration labels, error resolution and telemetry pruning.

## Privacy

Request bodies and authorization headers are never stored. Tokens, emails, nonces and long
hex identifiers are redacted; user ids are salted SHA-256 hashes; retention is 90 days.
