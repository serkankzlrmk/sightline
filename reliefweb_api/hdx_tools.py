"""
HDX Tools — LangChain @tool definitions for NovaSphere.

These tools give the agent access to HDX (Humanitarian Data Exchange) data
via the HDXClient direct API client. No MCP server dependency.

6 tools:
  1. hdx_get_country_overview  — Comprehensive humanitarian data overview (9 parallel endpoints)
  2. hdx_get_data_availability — Check what data categories exist for a country
  3. hdx_get_refugees          — Refugee/persons of concern data (UNHCR)
  4. hdx_get_idps              — Internally displaced persons data
  5. hdx_get_funding           — Humanitarian funding (requirements vs. received)
  6. hdx_get_conflict_events   — Conflict events data (ACLED)

Usage:
  The agent automatically uses these tools when the user asks about
  quantitative humanitarian data (refugee counts, IDP numbers, funding figures,
  conflict statistics). ReliefWeb tools are used for qualitative reports.
"""

import json
import logging
from typing import Optional

from langchain.tools import tool

from reliefweb_api.hdx_client import HDXClient
from reliefweb_api.reliefweb_utils import format_response, format_error

logger = logging.getLogger(__name__)

# ── Global HDX client singleton ──────────────────────────────────────────────
# Initialized in server.py after config is loaded.
_hdx_client: Optional[HDXClient] = None


def init_hdx_tools(app_identifier: str = "", base_url: str = "",
                   timeout: float = 30.0,
                   rate_limit_requests: int = 10,
                   rate_limit_period: float = 60.0) -> bool:
    """Initialize the global HDX client singleton.

    Called from server.py at startup. Returns True if initialized successfully,
    False if HDX_APP_IDENTIFIER is not set (tools will return error messages).
    """
    global _hdx_client
    try:
        _hdx_client = HDXClient(
            app_identifier=app_identifier,
            base_url=base_url or "https://hapi.humdata.org/api/v2",
            timeout=timeout,
            rate_limit_requests=rate_limit_requests,
            rate_limit_period=rate_limit_period,
        )
        logger.info("HDX client initialized successfully")
        return True
    except Exception as e:
        logger.warning(f"HDX client initialization failed: {e}")
        _hdx_client = None
        return False


def get_hdx_client() -> Optional[HDXClient]:
    """Get the global HDX client singleton."""
    return _hdx_client


# ── Helper ───────────────────────────────────────────────────────────────────

def _hdx_result_to_json(result) -> str:
    """Convert HDXResult to JSON string for agent tool response.

    If the result is a dict (from get_country_overview), convert each value.
    Otherwise, convert the single HDXResult.
    """
    if result is None:
        return format_error("ServiceUnavailable",
                            "HDX client is not initialized. Set HDX_APP_IDENTIFIER in .env")

    if isinstance(result, dict):
        # Country overview returns dict of category → HDXResult
        out = {}
        for key, val in result.items():
            if hasattr(val, "to_dict"):
                out[key] = val.to_dict()
            else:
                out[key] = val
        return format_response(out)

    if hasattr(result, "to_dict"):
        return format_response(result.to_dict())

    return format_response(result)


# ══════════════════════════════════════════════════════════════════════════════
# HDX Tool Definitions
# ══════════════════════════════════════════════════════════════════════════════

@tool
def hdx_get_country_overview(country_code: str) -> str:
    """Get a comprehensive humanitarian data overview for a country from HDX (Humanitarian Data Exchange).

    This fetches data from multiple HDX endpoints in parallel: refugee counts, IDP numbers,
    funding status, conflict events, food security, national risk, and data availability.
    Use this when the user asks for a broad humanitarian overview of a country.

    Args:
        country_code: ISO 3166-1 alpha-3 country code (e.g., 'SYR' for Syria, 'TUR' for Turkey,
                      'AFG' for Afghanistan, 'UKR' for Ukraine, 'YEM' for Yemen, 'SDN' for Sudan)
    """
    hdx = get_hdx_client()
    if not hdx:
        return format_error("ServiceUnavailable",
                            "HDX client is not initialized. Set HDX_APP_IDENTIFIER in .env")
    try:
        result = hdx.get_country_overview_sync(country_code.upper())
        return _hdx_result_to_json(result)
    except Exception as e:
        logger.error(f"HDX country overview error for {country_code}: {e}")
        return format_error("HDXError", f"Failed to get country overview for {country_code}: {str(e)}")


@tool
def hdx_get_data_availability(country_code: str) -> str:
    """Check what humanitarian data categories are available for a country on HDX.

    Use this BEFORE querying specific data to verify data exists. Returns a list of
    available data categories (refugees, IDPs, funding, conflict, food security, etc.)
    with record counts.

    Args:
        country_code: ISO 3166-1 alpha-3 country code (e.g., 'SYR', 'TUR', 'AFG', 'UKR')
    """
    hdx = get_hdx_client()
    if not hdx:
        return format_error("ServiceUnavailable",
                            "HDX client is not initialized. Set HDX_APP_IDENTIFIER in .env")
    try:
        result = hdx.get_data_availability_sync(location_code=country_code.upper())
        return _hdx_result_to_json(result)
    except Exception as e:
        logger.error(f"HDX data availability error for {country_code}: {e}")
        return format_error("HDXError", f"Failed to get data availability for {country_code}: {str(e)}")


@tool
def hdx_get_refugees(country_code: str, limit: int = 10) -> str:
    """Get refugee and persons of concern data from HDX for a specific country.

    Returns refugee counts, demographics, and origin/destination breakdowns
    from UNHCR data. Use for questions about refugee numbers, displacement,
    and persons of concern.

    Args:
        country_code: ISO 3166-1 alpha-3 country code (e.g., 'SYR', 'TUR', 'AFG')
        limit: Maximum number of records to return (default 10, max 50)
    """
    hdx = get_hdx_client()
    if not hdx:
        return format_error("ServiceUnavailable",
                            "HDX client is not initialized. Set HDX_APP_IDENTIFIER in .env")
    try:
        result = hdx.get_refugees_sync(location_code=country_code.upper(), limit=min(limit, 50))
        return _hdx_result_to_json(result)
    except Exception as e:
        logger.error(f"HDX refugees error for {country_code}: {e}")
        return format_error("HDXError", f"Failed to get refugee data for {country_code}: {str(e)}")


@tool
def hdx_get_idps(country_code: str, limit: int = 10) -> str:
    """Get internally displaced persons (IDP) data from HDX for a specific country.

    Returns IDP counts, locations, and displacement patterns. Use for questions
    about internal displacement, displacement figures, and IDP demographics.

    Args:
        country_code: ISO 3166-1 alpha-3 country code (e.g., 'SYR', 'UKR', 'SDN')
        limit: Maximum number of records to return (default 10, max 50)
    """
    hdx = get_hdx_client()
    if not hdx:
        return format_error("ServiceUnavailable",
                            "HDX client is not initialized. Set HDX_APP_IDENTIFIER in .env")
    try:
        result = hdx.get_idps_sync(location_code=country_code.upper(), limit=min(limit, 50))
        return _hdx_result_to_json(result)
    except Exception as e:
        logger.error(f"HDX IDPs error for {country_code}: {e}")
        return format_error("HDXError", f"Failed to get IDP data for {country_code}: {str(e)}")


@tool
def hdx_get_funding(country_code: str, limit: int = 10) -> str:
    """Get humanitarian funding data (requirements vs. funding received) from HDX for a country.

    Returns funding requirements, funded amounts, funding percentages, and
    organization-level breakdowns. Use for questions about humanitarian financing,
    funding gaps, and resource allocation.

    Args:
        country_code: ISO 3166-1 alpha-3 country code (e.g., 'SYR', 'UKR', 'ETH')
        limit: Maximum number of records to return (default 10, max 50)
    """
    hdx = get_hdx_client()
    if not hdx:
        return format_error("ServiceUnavailable",
                            "HDX client is not initialized. Set HDX_APP_IDENTIFIER in .env")
    try:
        result = hdx.get_funding_sync(location_code=country_code.upper(), limit=min(limit, 50))
        return _hdx_result_to_json(result)
    except Exception as e:
        logger.error(f"HDX funding error for {country_code}: {e}")
        return format_error("HDXError", f"Failed to get funding data for {country_code}: {str(e)}")


@tool
def hdx_get_conflict_events(country_code: str, limit: int = 10) -> str:
    """Get conflict event data (ACLED) from HDX for a specific country.

    Returns conflict event counts, types, actors, and geographic distribution.
    Use for questions about conflict intensity, violence patterns, and
    security incidents.

    Args:
        country_code: ISO 3166-1 alpha-3 country code (e.g., 'SYR', 'UKR', 'SDN', 'AFG')
        limit: Maximum number of records to return (default 10, max 50)
    """
    hdx = get_hdx_client()
    if not hdx:
        return format_error("ServiceUnavailable",
                            "HDX client is not initialized. Set HDX_APP_IDENTIFIER in .env")
    try:
        result = hdx.get_conflict_events_sync(location_code=country_code.upper(), limit=min(limit, 50))
        return _hdx_result_to_json(result)
    except Exception as e:
        logger.error(f"HDX conflict events error for {country_code}: {e}")
        return format_error("HDXError", f"Failed to get conflict events for {country_code}: {str(e)}")


# ── Tool list for agent registration ─────────────────────────────────────────

HDX_TOOLS = [
    hdx_get_country_overview,
    hdx_get_data_availability,
    hdx_get_refugees,
    hdx_get_idps,
    hdx_get_funding,
    hdx_get_conflict_events,
]