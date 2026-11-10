# Tool Inventory

Sightline defines 46 native tools and 28 MCP tools. The default deployment activates
**60 tools** (40 native + 20 MCP); availability depends on environment keys and feature
flags. Admin check: `GET /api/agent/capabilities` with a Bearer token, or Admin >
Observability > Tool Usage.

## Native tools

| Group | Count | Requirement | Purpose |
|---|---|---|---|
| ReliefWeb | 17 | `RELIEFWEB_APPNAME` | Search reports/disasters/headlines, read full content, ingest, knowledge base |
| HDX | 7 | `HDX_APP_IDENTIFIER` | Country overview, refugees, IDPs, IPC phases, funding, conflict events |
| NewsAPI | 3 | `NEWS_API_KEY` | News search, headlines, sources |
| GDACS | 2 | none | Rapid-onset disaster alerts and event details |
| Weather | 3 | none | Forecast, geocoding, air quality |
| World Bank | 2 | none | Development indicators and country profiles |
| ACLED | 2 | `ACLED_EMAIL`+`ACLED_PASSWORD` or `ACLED_API_KEY` | Conflict event counts and searches |
| FTS (OCHA) | 2 | none | Humanitarian funding plans and gaps |
| OSM/Overpass | 1 | none | Nearby infrastructure (hospitals, shelters, water points) |
| GIEWS | 2 | `GIEWS_ENABLED=true` | Food prices and crop forecasts (disabled until schema is verified) |
| UNHCR | 3 | `UNHCR_API_KEY` | Refugee population, demographics, nowcast |
| FIRMS | 1 | `FIRMS_MAP_KEY` | Active fire detections |
| SQL | 1 | local DB | Read-only database analytics (premium/admin) |

## MCP tools

| Server | Count | Requirement | Purpose |
|---|---|---|---|
| arXiv | 19 | `uvx` installed | Academic paper search, download, abstract, citation graph |
| sequential-thinking | 1 | `npx` installed | Structured reasoning for Deep Think mode |
| Brave Search | 8 | `MCP_BRAVE_ENABLED=true` + `BRAVE_API_KEY` | Web/news/image/video/local search, summarizer |

## Enabling optional sources

Add keys to `.env` and restart the app container:

```env
ACLED_EMAIL=
ACLED_PASSWORD=
# or ACLED_API_KEY=
UNHCR_API_KEY=
FIRMS_MAP_KEY=
GIEWS_ENABLED=false
MCP_BRAVE_ENABLED=false
BRAVE_API_KEY=
```

`FTS` and `Overpass` require no key. `HDX` and `News` bind tools even when keys are absent,
but calls fail at runtime; configure keys for production use.

## Tool health

- Admin > Observability > Tool Usage: calls, error rate, p95 latency per tool.
- Admin > Errors (`kind=tool`): structured tool failures (auth, timeout, schema pending).
- Startup logs distinguish `initialized` from `disabled`.
- Tool calls are retried for transient timeout/429/5xx errors; repeated failures open a
  short circuit breaker per tool (`agent/tool_resilience.py`).
