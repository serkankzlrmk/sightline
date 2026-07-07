"""
GDACS Tools — LangChain @tool definitions for Sightline.

These tools give the agent access to real-time disaster alerts from
GDACS (Global Disaster Alert and Coordination System). GDACS is a free,
keyless RSS feed maintained by the EU Joint Research Centre (JRC).

No MCP server dependency — direct HTTP client (gdacs_client.py).

2 tools:
  1. gdacs_get_alerts        — List/filter real-time disaster alerts
  2. gdacs_get_event_detail  — Get detail on a specific alert by event_id or title

Usage:
  The agent uses these tools when the user asks about active disasters,
  earthquake/flood/cyclone alerts, or real-time hazard monitoring.
  ReliefWeb tools -> qualitative reports. HDX tools -> quantitative stats.
  News tools -> media coverage. GDACS tools -> real-time hazard alerts.

GDACS event types:
  EQ = earthquake, FL = flood, TC = tropical cyclone,
  WF = wildfire, VO = volcano, DR = drought

GDACS alert levels:
  Green (low), Orange (medium), Red (high)
"""

import logging

from langchain.tools import tool

from reliefweb_api.gdacs_client import GDACSClient
from reliefweb_api.reliefweb_utils import format_error, format_response

logger = logging.getLogger(__name__)

# ── Global GDACS client singleton ────────────────────────────────────────────
# Initialized in server.py at startup. GDACS is keyless, so this almost
# always succeeds.
_gdacs_client: GDACSClient | None = None


def init_gdacs_tools(base_url: str = "", timeout: float = 30.0,
                     rate_limit_requests: int = 30,
                     rate_limit_period: float = 60.0,
                     cache_ttl: int = 900) -> bool:
    """Initialize the global GDACS client singleton.

    Called from server.py at startup. GDACS is a free, keyless RSS feed,
    so this essentially always returns True unless the network is down.
    """
    global _gdacs_client
    try:
        _gdacs_client = GDACSClient(
            base_url=base_url or GDACSClient.DEFAULT_BASE_URL,
            timeout=timeout,
            rate_limit_requests=rate_limit_requests,
            rate_limit_period=rate_limit_period,
            cache_ttl=cache_ttl,
        )
        logger.info("GDACS client initialized successfully")
        return True
    except Exception as e:
        logger.warning(f"GDACS client initialization failed: {e}")
        _gdacs_client = None
        return False


def get_gdacs_client() -> GDACSClient | None:
    """Get the global GDACS client singleton."""
    return _gdacs_client


# ── Helper ───────────────────────────────────────────────────────────────────

def _alerts_to_json(alerts, params=None) -> str:
    """Format alert list as a JSON response string for agent tools."""
    payload = {
        "source": "GDACS",
        "success": True,
        "count": len(alerts) if isinstance(alerts, list) else 0,
        "data": alerts if isinstance(alerts, list) else [],
    }
    if params:
        payload["params"] = params
    return format_response(payload)


# ══════════════════════════════════════════════════════════════════════════════
# GDACS Tool Definitions
# ══════════════════════════════════════════════════════════════════════════════

@tool
def gdacs_get_alerts(event_type: str = "", alert_level: str = "",
                     country_iso3: str = "", limit: int = 20) -> str:
    """Get real-time disaster alerts from GDACS (Global Disaster Alert and Coordination System).

    GDACS provides near real-time alerts about natural disasters worldwide
    (earthquakes, floods, tropical cyclones, wildfires, volcanoes, droughts)
    with potential humanitarian impact. Updated every ~15 minutes.

    Use this for: "current disaster alerts", "active earthquakes", "flood warnings",
    "tropical cyclone alerts", "what disasters are happening right now".

    This is best for REAL-TIME hazard alerts. For detailed humanitarian reports,
    use ReliefWeb tools. For quantitative stats (refugee counts, funding),
    use HDX tools. For news coverage, use News tools.

    Args:
        event_type: Filter by event type. Options: EQ (earthquake), FL (flood),
                   TC (tropical cyclone), WF (wildfire), VO (volcano), DR (drought).
                   Empty string = all event types.
        alert_level: Filter by alert level. Options: Green (low), Orange (medium),
                    Red (high). Empty string = all levels.
        country_iso3: Filter by ISO3 country code (e.g., 'TUR' for Turkey,
                     'JPN' for Japan, 'USA' for United States, 'PHL' for Philippines).
                     Empty string = all countries.
        limit: Maximum number of alerts to return (default 20, max 50).
    """
    gdacs = get_gdacs_client()
    if not gdacs:
        return format_error(
            "ServiceUnavailable",
            "GDACS client is not initialized.",
        )
    try:
        alerts = gdacs.get_alerts(
            event_type=event_type or None,
            alert_level=alert_level or None,
            country_iso3=country_iso3 or None,
            limit=min(limit, 50),
        )
        params = {
            "event_type": event_type or "all",
            "alert_level": alert_level or "all",
            "country_iso3": country_iso3 or "all",
            "limit": min(limit, 50),
        }
        return _alerts_to_json(alerts, params)
    except Exception as e:
        logger.error(f"GDACS get_alerts error: {e}")
        return format_error("GDACSError", f"Failed to fetch GDACS alerts: {str(e)}")


@tool
def gdacs_get_event_detail(event_id: str = "", title: str = "") -> str:
    """Get detailed information about a specific GDACS disaster alert.

    Use this AFTER gdacs_get_alerts to get more context on a particular alert.
    You can look up by event_id (numeric, e.g. '1103920') or by title
    (full or partial, case-insensitive).

    Returns the full alert record including: title, description, link, alert
    level, event type, country, coordinates, from/to dates, population affected,
    and severity.

    Args:
        event_id: GDACS numeric event ID (e.g., '1103920'). Preferred lookup.
        title: Alert title (full or partial). Used if event_id is empty or not found.
    """
    gdacs = get_gdacs_client()
    if not gdacs:
        return format_error(
            "ServiceUnavailable",
            "GDACS client is not initialized.",
        )
    try:
        alert = None
        if event_id:
            alert = gdacs.get_event_detail(event_id)
        if alert is None and title:
            alert = gdacs.get_event_detail_by_title(title)

        if alert is None:
            return format_error(
                "NotFound",
                f"No GDACS alert found for event_id='{event_id}' title='{title}'. "
                "The alert may have expired (GDACS feed only carries active alerts).",
            )

        return _alerts_to_json([alert], {"event_id": event_id, "title": title})
    except Exception as e:
        logger.error(f"GDACS get_event_detail error: {e}")
        return format_error("GDACSError", f"Failed to fetch GDACS event detail: {str(e)}")


# ── Tool list for agent registration ─────────────────────────────────────────

GDACS_TOOLS = [
    gdacs_get_alerts,
    gdacs_get_event_detail,
]
