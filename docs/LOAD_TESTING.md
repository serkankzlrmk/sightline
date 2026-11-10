# Load Testing

Sightline runs one gunicorn worker with four threads. Chat answers are streamed over SSE,
so each active streaming request occupies a thread for the duration of the answer. Public
SSR/API pages are cheaper but still share the same worker and SQLite connection.

## Capacity constraints

| Constraint | Current value | Effect |
|---|---|---|
| Gunicorn workers | 1 | SQLite/Chroma and in-memory state are single-process |
| Threads | 4 (`gthread`) | approximately 4 concurrent long requests |
| Chat stream | 6-30 s typical | each stream holds a thread |
| `max_requests` | 1000 | worker recycle resets nonces, jobs and in-memory rate counters |
| Caddy SSE timeouts | 300 s | proxy vs gunicorn timeout must stay aligned |
| Rate limits | 120/min/IP; agent 30/min; 100/day/IP custom | shared IPs can exhaust budgets |

Public SSR/API traffic scales better than chat. Chat capacity is the first limiting factor.

## Tool

`scripts/load_test.py` uses async httpx and reports latency percentiles:

```bash
python scripts/load_test.py --concurrency 20 --requests 200
python scripts/load_test.py --paths /crisis,/countries,/api/public/stats \
  --concurrency 50 --requests 500
python scripts/load_test.py --json
```

Output fields: `rps`, `p50_ms`, `p95_ms`, `p99_ms`, `max_ms`, `error_rate`, error samples.

Chat load tests should use a mock OpenAI-compatible server so runs consume no LLM tokens;
streaming load testing is a planned follow-up.

## Scenarios

1. Public reads: `/api/public/stats`, `/api/map/countries`, `/crisis`.
2. SSR pages: `/countries`, `/sitreps`, `/bulletins`.
3. Authenticated API: database search and report endpoints.
4. Chat: 1/4/8/16 concurrent streams against a mock LLM.
5. SITREP/bulletin/proposal: mock jobs or one controlled real run.

## Guards and caching

- Chat concurrency guard `CHAT_MAX_CONCURRENT` returns 503 with `Retry-After` when saturated.
- Public APIs and SSR pages send short cache headers (`max-age=60`, stale-while-revalidate).
- Map data is disk-cached with single-flight refresh and stale serving.
- Request/error counters are buffered and flushed to `errors.db` approximately every 30 s.

## Interpreting results

- Target: public API p95 < 500 ms and SSR p95 < 1 s with warm caches.
- A sharp p95 increase with rising RPS indicates CPU, thread-pool, SQLite or LLM saturation.
- Controlled 503s with `Retry-After` are expected at chat capacity; 5xx errors are not.
- Watch worker restarts during the test: they indicate `max_requests` recycling and
  in-memory state loss.

## Scaling path

First measure. Then, if sustained concurrency exceeds roughly 50 users or chat p95 exceeds
30 s, introduce Redis (rate limits/jobs/nonces), Postgres plus pgvector and a CDN, and move
long-running generation to queue workers. A vertical upgrade is the cheapest first step
before a multi-worker architecture.
