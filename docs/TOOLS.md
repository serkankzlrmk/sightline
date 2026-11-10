# Tool Inventory & Enablement — Sightline

> Son güncelleme: 2026-11-10. Kodda 46 native + 28 MCP (potansiyel 74) tool var;
> hangilerinin bağlanacağı env anahtarlarına bağlıdır. Admin doğrulaması:
> `GET /api/agent/capabilities` (Bearer token) veya Admin → Observability → Tool Usage.

## Native tools (46 potential)

| Group | Tools | Required | Notes |
|---|---|---|---|
| ReliefWeb | 17 | `RELIEFWEB_APPNAME` | Qualitative reports, KB, ingest, PDF |
| HDX | 7 | `HDX_APP_IDENTIFIER` | Quantitative: refugees, IDPs, funding, conflict events |
| NewsAPI | 3 | `NEWS_API_KEY` | Media narrative |
| GDACS | 2 | keyless | Rapid-onset disaster alerts |
| Weather | 3 | keyless | Forecast, geocode, air quality |
| World Bank | 2 | keyless | Macro/development baseline |
| ACLED | 2 | `ACLED_EMAIL`+`ACLED_PASSWORD` or `ACLED_API_KEY` | Conflict events; auth failures show as tool errors |
| FTS (OCHA) | 2 | keyless | Funding plans/gaps |
| OSM/Overpass | 1 | keyless | Nearby infrastructure |
| GIEWS | 2 | `GIEWS_ENABLED=true` | Disabled until schema verified; otherwise `GIEWSSchemaPending` |
| UNHCR | 3 | `UNHCR_API_KEY` | Refugee population/demographics/nowcast |
| FIRMS | 1 | `FIRMS_MAP_KEY` | Active fire detections |
| SQL | 1 | local DB | Free users excluded; premium/admin |

## MCP tools (28 potential)

| Server | Tools | Required | Notes |
|---|---|---|---|
| arxiv | 19 | `uvx` installed | Keyless academic search |
| sequential-thinking | 1 | `npx` installed | Deep Think mode |
| brave-search | 8 | `MCP_BRAVE_ENABLED=true` + `BRAVE_API_KEY` | 30/day limit |

## Health/debug

- `GET /api/agent/capabilities` → active groups + counts.
- Admin → Observability → Tool Usage → calls/error rate/p95 per tool.
- Admin → Errors (`kind=tool`) → ACLED auth, GIEWS schema, MCP failures.
- Log lines on startup: `✓ ... initialized` vs `... devre dışı`.
