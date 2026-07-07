"""
Weather Tools — LangChain @tool definitions for Sightline.

These tools give the agent access to weather and air quality data via
the Open-Meteo free keyless API. No MCP server dependency.

3 tools:
  1. weather_get_forecast   — Current conditions + daily forecast (temp, precip, wind)
  2. weather_geocode        — City name → coordinates
  3. weather_get_air_quality— PM2.5, PM10, NO2, SO2, O3, CO + WHO guideline comparison

Usage:
  The agent automatically uses these tools when the user asks about
  weather, climate, floods, drought, air pollution, or disease vectors.
  ReliefWeb tools are for humanitarian reports; HDX tools for quantitative
  humanitarian data; Weather tools for meteorological conditions.
"""

import logging

from langchain.tools import tool

from reliefweb_api.reliefweb_utils import format_error, format_response
from reliefweb_api.weather_client import WeatherClient

logger = logging.getLogger(__name__)

# ── Global Weather client singleton ──────────────────────────────────────────
# Initialized in server.py at startup. Open-Meteo is keyless, so the client
# always initializes successfully — but we keep the singleton pattern for
# consistency with News/HDX clients.
_weather_client: WeatherClient | None = None


def init_weather_tools(base_url: str = "", geo_url: str = "",
                       aq_url: str = "",
                       timeout: float = 15.0,
                       cache_ttl: int = 3600,
                       geo_cache_ttl: int = 604800,
                       rate_limit_requests: int = 60,
                       rate_limit_period: float = 60.0) -> bool:
    """Initialize the global Weather client singleton.

    Called from server.py at startup. Open-Meteo is keyless, so this always
    succeeds. Returns True on success.
    """
    global _weather_client
    try:
        _weather_client = WeatherClient(
            base_url=base_url or WeatherClient.DEFAULT_BASE_URL,
            geo_url=geo_url or WeatherClient.DEFAULT_GEO_URL,
            aq_url=aq_url or WeatherClient.DEFAULT_AQ_URL,
            timeout=timeout,
            cache_ttl=cache_ttl,
            geo_cache_ttl=geo_cache_ttl,
            rate_limit_requests=rate_limit_requests,
            rate_limit_period=rate_limit_period,
        )
        logger.info("Weather client initialized successfully (Open-Meteo, keyless)")
        return True
    except Exception as e:
        logger.warning(f"Weather client initialization failed: {e}")
        _weather_client = None
        return False


def get_weather_client() -> WeatherClient | None:
    """Get the global Weather client singleton."""
    return _weather_client


# ── Helper ──────────────────────────────────────────────────────────────────

def _parse_location(location: str) -> tuple | None:
    """Parse 'lat,lon' string into (float, float). Returns None if not coords."""
    if not location or "," not in location:
        return None
    parts = location.split(",")
    if len(parts) != 2:
        return None
    try:
        return (float(parts[0].strip()), float(parts[1].strip()))
    except (ValueError, TypeError):
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Weather Tool Definitions
# ══════════════════════════════════════════════════════════════════════════════

@tool
def weather_get_forecast(location: str, days: int = 7) -> str:
    """Get weather forecast for a location (city name or coordinates).

    Useful for disaster response logistics, health risk assessment, and
    flood/drought monitoring. Returns current conditions (temperature,
    humidity, wind, weather description) and a daily forecast (high/low
    temperature, precipitation, max wind, weather description).

    Args:
        location: City name (e.g., 'Aleppo', 'Khartoum') or 'lat,lon'
                  coordinates (e.g., '15.5,32.5').
        days: Number of forecast days (1-16, default 7).
    """
    weather = get_weather_client()
    if not weather:
        return format_error("ServiceUnavailable",
                            "Weather client is not initialized.")
    try:
        # Parse coordinates if provided as 'lat,lon'
        coords = _parse_location(location)
        if coords:
            lat, lon = coords
        else:
            # Geocode city name first
            results = weather.geocode(location, limit=1)
            if not results:
                return format_error(
                    "NotFound",
                    f"Could not geocode location '{location}'. "
                    "Try 'lat,lon' coordinates instead.",
                )
            lat = results[0]["latitude"]
            lon = results[0]["longitude"]

        days = min(max(int(days), 1), 16)
        result = weather.get_forecast(lat, lon, days=days)
        if not result.get("success"):
            return format_error(
                "WeatherError",
                result.get("error", "Failed to fetch forecast"),
            )

        # Attach resolved location info for context
        if not _parse_location(location) and "results" in {}:
            pass  # no-op; handled above
        result["resolved_location"] = location
        return format_response(result)
    except Exception as e:
        logger.error(f"Weather forecast error for '{location}': {e}")
        return format_error(
            "WeatherError",
            f"Failed to get forecast for '{location}': {str(e)}",
        )


@tool
def weather_geocode(query: str, country_code: str = "", limit: int = 5) -> str:
    """Geocode a location name to coordinates.

    Use this to resolve a place name to latitude/longitude for subsequent
    weather or air quality queries, or to disambiguate ambiguous place names.

    Args:
        query: Location name (city, region, or country).
        country_code: Optional ISO2 country code to filter results
                      (e.g., 'SY' for Syria, 'SD' for Sudan).
        limit: Max results (default 5, max 10).
    """
    weather = get_weather_client()
    if not weather:
        return format_error("ServiceUnavailable",
                            "Weather client is not initialized.")
    try:
        limit = min(max(int(limit), 1), 10)
        results = weather.geocode(
            query,
            country_code=country_code or None,
            limit=limit,
        )
        if not results:
            return format_error(
                "NotFound",
                f"No locations found for '{query}'"
                + (f" in country '{country_code}'" if country_code else ""),
            )
        return format_response({
            "success": True,
            "query": query,
            "country_code": country_code or None,
            "count": len(results),
            "results": results,
        })
    except Exception as e:
        logger.error(f"Weather geocode error for '{query}': {e}")
        return format_error(
            "WeatherError",
            f"Failed to geocode '{query}': {str(e)}",
        )


@tool
def weather_get_air_quality(location: str) -> str:
    """Get air quality data for a location (PM2.5, PM10, NO2, SO2, O3, CO).

    Useful for health impact analysis in disaster zones (smoke, industrial
    damage, dust storms). Returns current readings with WHO guideline
    ratio comparison (values > 1.0 exceed WHO recommendations).

    Args:
        location: City name or 'lat,lon' coordinates.
    """
    weather = get_weather_client()
    if not weather:
        return format_error("ServiceUnavailable",
                            "Weather client is not initialized.")
    try:
        # Parse coordinates if provided as 'lat,lon'
        coords = _parse_location(location)
        if coords:
            lat, lon = coords
        else:
            results = weather.geocode(location, limit=1)
            if not results:
                return format_error(
                    "NotFound",
                    f"Could not geocode location '{location}'. "
                    "Try 'lat,lon' coordinates instead.",
                )
            lat = results[0]["latitude"]
            lon = results[0]["longitude"]

        result = weather.get_air_quality(lat, lon)
        if not result.get("success"):
            return format_error(
                "WeatherError",
                result.get("error", "Failed to fetch air quality data"),
            )

        result["resolved_location"] = location
        return format_response(result)
    except Exception as e:
        logger.error(f"Weather air quality error for '{location}': {e}")
        return format_error(
            "WeatherError",
            f"Failed to get air quality for '{location}': {str(e)}",
        )


# ── Tool list for agent registration ─────────────────────────────────────────

WEATHER_TOOLS = [
    weather_get_forecast,
    weather_geocode,
    weather_get_air_quality,
]
