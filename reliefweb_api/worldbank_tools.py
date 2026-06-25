"""
World Bank Tools — LangChain @tool definitions for Sightline.

These tools give the agent access to World Bank Open Data (economic, demographic,
social indicators) via the WorldBankClient direct API client. No API key required.

2 tools:
  1. worldbank_get_indicator    — Retrieve a specific indicator time series
  2. worldbank_country_profile  — Curated 15-indicator country profile

Usage:
  The agent automatically uses these tools when the user asks about
  pre-crisis baseline conditions (GDP, poverty, population, health, education,
  access to services). ReliefWeb tools are for humanitarian reports; HDX tools
  for humanitarian response data; World Bank tools for structural baseline data.
"""

import logging
from typing import Optional

from langchain.tools import tool

from reliefweb_api.worldbank_client import WorldBankClient, to_iso2
from reliefweb_api.reliefweb_utils import format_response, format_error

logger = logging.getLogger(__name__)

# ── Global World Bank client singleton ───────────────────────────────────────
# Initialized in server.py after config is loaded.
_worldbank_client: Optional[WorldBankClient] = None


def init_worldbank_tools(base_url: str = "", timeout: float = 15.0,
                         cache_ttl: int = 86400) -> bool:
    """Initialize the global World Bank client singleton.

    Called from server.py at startup. The World Bank API is keyless, so this
    always succeeds unless network/config is broken. Returns True on success.
    """
    global _worldbank_client
    try:
        _worldbank_client = WorldBankClient(
            base_url=base_url or "https://api.worldbank.org/v2",
            timeout=timeout,
            cache_ttl=cache_ttl,
        )
        logger.info("World Bank client initialized successfully")
        return True
    except Exception as e:
        logger.warning(f"World Bank client initialization failed: {e}")
        _worldbank_client = None
        return False


def get_worldbank_client() -> Optional[WorldBankClient]:
    """Get the global World Bank client singleton."""
    return _worldbank_client


# ── Helper ───────────────────────────────────────────────────────────────────

def _worldbank_to_json(data) -> str:
    """Convert World Bank response data to JSON string for agent tool response."""
    if data is None:
        return format_error(
            "ServiceUnavailable",
            "World Bank client is not initialized.",
        )
    return format_response(data)


# ══════════════════════════════════════════════════════════════════════════════
# World Bank Tool Definitions
# ══════════════════════════════════════════════════════════════════════════════

@tool
def worldbank_get_indicator(country_code: str, indicator_code: str, limit: int = 5) -> str:
    """Retrieve economic/demographic indicators for a country from the World Bank.

    Useful for understanding the pre-crisis baseline of a country (GDP, poverty, health, education).

    Args:
        country_code: ISO2 or ISO3 country code (e.g., 'SD' or 'SUD' for Sudan, 'SY' or 'SYR' for Syria).
        indicator_code: World Bank indicator code (e.g., 'NY.GDP.PCAP.CD' for GDP per capita, 'SP.POP.TOTL' for population).
                       Search at https://data.worldbank.org/indicator for available indicators.
        limit: Number of most recent data points (default 5).

    Returns time-series data with values, years, and indicator description.
    """
    wb = get_worldbank_client()
    if not wb:
        return format_error(
            "ServiceUnavailable",
            "World Bank client is not initialized.",
        )
    try:
        records = wb.get_indicator(country_code, indicator_code, limit=max(1, min(limit, 50)))
        if not records:
            cc = to_iso2(country_code)
            return format_error(
                "NoData",
                f"No data returned for country '{country_code}' (ISO2: {cc}) "
                f"and indicator '{indicator_code}'. The indicator code may be "
                f"invalid or no data exists for this country.",
            )
        return _worldbank_to_json(records)
    except Exception as e:
        logger.error(f"World Bank get_indicator error for {country_code}/{indicator_code}: {e}")
        return format_error(
            "WorldBankError",
            f"Failed to get indicator {indicator_code} for {country_code}: {str(e)}",
        )


@tool
def worldbank_country_profile(country_code: str) -> str:
    """Get a comprehensive economic and social profile of a country.

    Useful for understanding the baseline conditions before/during a humanitarian crisis.
    Returns 15+ key indicators: GDP, poverty, population, life expectancy, child mortality,
    access to water/sanitation/electricity, education, health, debt, and more.

    Args:
        country_code: ISO2 or ISO3 country code (e.g., 'SD' or 'SUD' for Sudan).

    Returns a formatted profile with indicator values, years, and descriptions.
    """
    wb = get_worldbank_client()
    if not wb:
        return format_error(
            "ServiceUnavailable",
            "World Bank client is not initialized.",
        )
    try:
        profile = wb.get_country_profile(country_code)
        if not profile:
            cc = to_iso2(country_code)
            return format_error(
                "NoData",
                f"No profile data returned for country '{country_code}' (ISO2: {cc}). "
                f"The country code may be invalid.",
            )
        return _worldbank_to_json(profile)
    except Exception as e:
        logger.error(f"World Bank country profile error for {country_code}: {e}")
        return format_error(
            "WorldBankError",
            f"Failed to get country profile for {country_code}: {str(e)}",
        )


# ── Tool list for agent registration ─────────────────────────────────────────

WORLDBANK_TOOLS = [
    worldbank_get_indicator,
    worldbank_country_profile,
]