"""
Open-Meteo Weather Client — Sightline Entegrasyonu
====================================================

Open-Meteo REST API'ye dogrudan HTTP istekleri yapar. MCP server'a
ihtiyac duymaz, NewsClient ile ayni pattern'i takip eder.

   Bizim: Sightline -> weather_client.py (bu dosya) -> Open-Meteo REST API

Tek dosya, tek process, tek deployment. API anahtari GEREKMEZ (keyless).

3 endpoint:
  1. Weather Forecast: current + 16-day forecast
     https://api.open-meteo.com/v1/forecast
  2. Geocoding: city name -> coordinates
     https://geocoding-api.open-meteo.com/v1/search
  3. Air Quality: PM2.5, PM10, NO2, SO2, O3, CO
     https://air-quality-api.open-meteo.com/v1/air-quality

Entegrasyon:
1. config.py'de OPEN_METEO_* parametreleri tanimli (opsiyonel, defaults mevcut)
2. weather_tools.py'da @tool tanimlari var
3. server.py baslangicta init_weather_tools() cagirir
4. agent/relief_agent.py all_tools'a ekler

Open-Meteo API: https://open-meteo.com/en/docs
"""

import logging
import os
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ============================================================================
# Cache (TTL-based, Thread-Safe) — copied from news_client.py
# ============================================================================

class SimpleCache:
    def __init__(self, ttl: int = 3600, max_size: int = 200):
        self.ttl = ttl
        self.max_size = max_size
        self._cache: dict[str, tuple] = {}

    def get(self, key: str) -> Any | None:
        if key in self._cache:
            value, ts = self._cache[key]
            if time.time() - ts < self.ttl:
                return value
            del self._cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        if len(self._cache) >= self.max_size and key not in self._cache:
            oldest = min(self._cache, key=lambda k: self._cache[k][1])
            del self._cache[oldest]
        self._cache[key] = (value, time.time())

    def clear(self) -> None:
        self._cache.clear()

    def stats(self) -> dict[str, int]:
        return {"size": len(self._cache), "max_size": self.max_size, "ttl": self.ttl}


# ============================================================================
# WMO Weather Code Mapping
# ============================================================================

WMO_WEATHER_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def describe_weather_code(code: int) -> str:
    """Return a human-readable description for a WMO weather code."""
    return WMO_WEATHER_CODES.get(int(code), f"Unknown code {code}")


# ============================================================================
# Open-Meteo Weather Client
# ============================================================================

class WeatherClient:
    """Direct Open-Meteo API client (keyless, free)."""

    DEFAULT_BASE_URL = "https://api.open-meteo.com/v1/forecast"
    DEFAULT_GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
    DEFAULT_AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        geo_url: str = DEFAULT_GEO_URL,
        aq_url: str = DEFAULT_AQ_URL,
        timeout: float = 15.0,
        cache_ttl: int = 3600,
        geo_cache_ttl: int = 604800,
        rate_limit_requests: int = 60,
        rate_limit_period: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.geo_url = geo_url.rstrip("/")
        self.aq_url = aq_url.rstrip("/")
        self.timeout = timeout

        # Two caches: forecast (1h) and geocoding (7d, stable locations).
        self.cache = SimpleCache(ttl=cache_ttl)
        self.geo_cache = SimpleCache(ttl=geo_cache_ttl)

        self.rate_limit_requests = rate_limit_requests
        self.rate_limit_period = rate_limit_period

        self._sync_client: httpx.Client | None = None
        self._request_timestamps: list[float] = []
        self._rate_lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "WeatherClient":
        from dotenv import load_dotenv
        load_dotenv()

        return cls(
            base_url=os.getenv("OPEN_METEO_BASE_URL", cls.DEFAULT_BASE_URL),
            geo_url=os.getenv("OPEN_METEO_GEO_URL", cls.DEFAULT_GEO_URL),
            aq_url=os.getenv("OPEN_METEO_AQ_URL", cls.DEFAULT_AQ_URL),
            timeout=float(os.getenv("OPEN_METEO_TIMEOUT", "15.0")),
            cache_ttl=int(os.getenv("OPEN_METEO_CACHE_TTL", "3600")),
            geo_cache_ttl=int(os.getenv("OPEN_METEO_GEO_CACHE_TTL", "604800")),
            rate_limit_requests=int(os.getenv("OPEN_METEO_RATE_LIMIT_REQUESTS", "60")),
            rate_limit_period=float(os.getenv("OPEN_METEO_RATE_LIMIT_PERIOD", "60.0")),
        )

    # =========================================================================
    # HTTP Client Management
    # =========================================================================

    def _get_sync_client(self) -> httpx.Client:
        if self._sync_client is None or self._sync_client.is_closed:
            self._sync_client = httpx.Client(timeout=self.timeout)
        return self._sync_client

    def close(self) -> None:
        if self._sync_client and not self._sync_client.is_closed:
            self._sync_client.close()

    # =========================================================================
    # Rate Limiting
    # =========================================================================

    def _check_rate_limit(self) -> None:
        now = time.time()
        with self._rate_lock:
            self._request_timestamps = [
                t for t in self._request_timestamps
                if now - t < self.rate_limit_period
            ]
            if len(self._request_timestamps) >= self.rate_limit_requests:
                oldest = self._request_timestamps[0]
                wait_time = self.rate_limit_period - (now - oldest)
            else:
                wait_time = 0
            self._request_timestamps.append(now)
        if wait_time > 0:
            logger.warning(f"Open-Meteo rate limit reached, waiting {wait_time:.1f}s")
            time.sleep(wait_time)

    # =========================================================================
    # Internal HTTP helper
    # =========================================================================

    def _request(self, base: str, params: dict[str, Any],
                 cache: SimpleCache | None = None) -> dict[str, Any] | None:
        """Perform a GET request and return parsed JSON, or None on error.

        Results are cached in `cache` when provided, keyed by base+params.
        """
        params = {k: v for k, v in params.items() if v is not None}

        if cache is not None:
            cache_key = f"{base}:{sorted(params.items())}"
            cached = cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Open-Meteo cache hit: {base}")
                return cached

        self._check_rate_limit()

        try:
            client = self._get_sync_client()
            response = client.get(base, params=params)
            if response.status_code != 200:
                logger.error(
                    f"Open-Meteo error: {response.status_code} "
                    f"for {base} params={params} body={response.text[:200]}"
                )
                return None
            data = response.json()
            if cache is not None:
                cache.set(cache_key, data)
            return data
        except Exception as e:
            logger.error(f"Open-Meteo request failed for {base}: {e}")
            return None

    # =========================================================================
    # Public API — Geocoding
    # =========================================================================

    def geocode(self, location_name: str, country_code: str | None = None,
                limit: int = 5) -> list[dict[str, Any]]:
        """Geocode a place name to coordinates via Open-Meteo Geocoding API.

        Returns a list of dicts with keys:
          name, latitude, longitude, country, country_code, admin1, population
        """
        params: dict[str, Any] = {
            "name": location_name,
            "count": min(max(limit, 1), 10),
            "language": "en",
            "format": "json",
        }
        if country_code:
            params["countryCode"] = country_code.upper()

        data = self._request(self.geo_url, params, cache=self.geo_cache)
        if not data:
            return []

        results = data.get("results") or []
        out: list[dict[str, Any]] = []
        for r in results:
            out.append({
                "name": r.get("name", ""),
                "latitude": r.get("latitude"),
                "longitude": r.get("longitude"),
                "country": r.get("country", ""),
                "country_code": r.get("country_code", ""),
                "admin1": r.get("admin1", ""),
                "population": r.get("population"),
            })
        return out

    # =========================================================================
    # Public API — Weather Forecast
    # =========================================================================

    def get_forecast(self, latitude: float, longitude: float,
                     days: int = 7) -> dict[str, Any]:
        """Get current conditions + daily forecast for a coordinate.

        Returns dict:
          current: {temperature_2m, relative_humidity_2m, wind_speed_10m,
                    weather_code, weather_description, time}
          daily: {time[], temperature_2m_max[], temperature_2m_min[],
                  precipitation_sum[], wind_speed_10m_max[],
                  weather_code[], weather_description[]}
          units: {...}
          location: {latitude, longitude}
        """
        days = min(max(days, 1), 16)
        params: dict[str, Any] = {
            "latitude": round(float(latitude), 4),
            "longitude": round(float(longitude), 4),
            "timezone": "auto",
            "forecast_days": days,
            "current": ",".join([
                "temperature_2m",
                "relative_humidity_2m",
                "wind_speed_10m",
                "weather_code",
            ]),
            "daily": ",".join([
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "wind_speed_10m_max",
                "weather_code",
            ]),
        }

        data = self._request(self.base_url, params, cache=self.cache)
        if not data:
            return {
                "success": False,
                "error": "Failed to fetch forecast",
                "location": {"latitude": latitude, "longitude": longitude},
            }

        cur_raw = data.get("current") or {}
        daily_raw = data.get("daily") or {}

        current = {
            "time": cur_raw.get("time"),
            "temperature_2m": cur_raw.get("temperature_2m"),
            "relative_humidity_2m": cur_raw.get("relative_humidity_2m"),
            "wind_speed_10m": cur_raw.get("wind_speed_10m"),
            "weather_code": cur_raw.get("weather_code"),
            "weather_description": describe_weather_code(cur_raw.get("weather_code", 0)),
        }

        wc_daily = daily_raw.get("weather_code") or []
        daily = {
            "time": daily_raw.get("time") or [],
            "temperature_2m_max": daily_raw.get("temperature_2m_max") or [],
            "temperature_2m_min": daily_raw.get("temperature_2m_min") or [],
            "precipitation_sum": daily_raw.get("precipitation_sum") or [],
            "wind_speed_10m_max": daily_raw.get("wind_speed_10m_max") or [],
            "weather_code": wc_daily,
            "weather_description": [describe_weather_code(c) for c in wc_daily],
        }

        return {
            "success": True,
            "location": {
                "latitude": data.get("latitude", latitude),
                "longitude": data.get("longitude", longitude),
                "timezone": data.get("timezone"),
            },
            "current": current,
            "daily": daily,
            "units": {
                "current_units": data.get("current_units", {}),
                "daily_units": data.get("daily_units", {}),
            },
        }

    # =========================================================================
    # Public API — Air Quality
    # =========================================================================

    # WHO air quality guidelines (annual mean / 24h) for quick context.
    WHO_GUIDELINES = {
        "pm2_5": 5.0,      # µg/m³ annual mean
        "pm10": 15.0,      # µg/m³ 24-hour mean
        "no2": 10.0,       # µg/m³ annual mean
        "so2": 40.0,       # µg/m³ 24-hour mean
        "o3": 100.0,       # µg/m³ 8-hour mean
        "co": 4.0,         # mg/m³ 24-hour mean
    }

    def get_air_quality(self, latitude: float, longitude: float) -> dict[str, Any]:
        """Get current air quality readings (PM2.5, PM10, NO2, SO2, O3, CO).

        Returns dict with current readings and WHO guideline comparison.
        """
        params: dict[str, Any] = {
            "latitude": round(float(latitude), 4),
            "longitude": round(float(longitude), 4),
            "timezone": "auto",
            "current": ",".join([
                "pm2_5",
                "pm10",
                "nitrogen_dioxide",
                "sulphur_dioxide",
                "ozone",
                "carbon_monoxide",
            ]),
        }

        data = self._request(self.aq_url, params, cache=self.cache)
        if not data:
            return {
                "success": False,
                "error": "Failed to fetch air quality data",
                "location": {"latitude": latitude, "longitude": longitude},
            }

        cur_raw = data.get("current") or {}
        units_raw = data.get("current_units") or {}

        pm25 = cur_raw.get("pm2_5")
        pm10 = cur_raw.get("pm10")
        no2 = cur_raw.get("nitrogen_dioxide")
        so2 = cur_raw.get("sulphur_dioxide")
        o3 = cur_raw.get("ozone")
        co = cur_raw.get("carbon_monoxide")

        def _who_ratio(value: float | None, key: str) -> float | None:
            if value is None:
                return None
            guideline = self.WHO_GUIDELINES.get(key)
            if not guideline:
                return None
            return round(value / guideline, 2)

        current = {
            "time": cur_raw.get("time"),
            "pm2_5": pm25,
            "pm10": pm10,
            "no2": no2,
            "so2": so2,
            "o3": o3,
            "co": co,
            "units": {
                "pm2_5": units_raw.get("pm2_5", "µg/m³"),
                "pm10": units_raw.get("pm10", "µg/m³"),
                "no2": units_raw.get("nitrogen_dioxide", "µg/m³"),
                "so2": units_raw.get("sulphur_dioxide", "µg/m³"),
                "o3": units_raw.get("ozone", "µg/m³"),
                "co": units_raw.get("carbon_monoxide", "µg/m³"),
            },
            "who_guideline_ratio": {
                "pm2_5": _who_ratio(pm25, "pm2_5"),
                "pm10": _who_ratio(pm10, "pm10"),
                "no2": _who_ratio(no2, "no2"),
                "so2": _who_ratio(so2, "so2"),
                "o3": _who_ratio(o3, "o3"),
                "co": _who_ratio(co, "co"),
            },
        }

        return {
            "success": True,
            "location": {
                "latitude": data.get("latitude", latitude),
                "longitude": data.get("longitude", longitude),
                "timezone": data.get("timezone"),
            },
            "current": current,
            "who_guidelines": {
                "pm2_5": f"≤ {self.WHO_GUIDELINES['pm2_5']} µg/m³ (annual)",
                "pm10": f"≤ {self.WHO_GUIDELINES['pm10']} µg/m³ (24h)",
                "no2": f"≤ {self.WHO_GUIDELINES['no2']} µg/m³ (annual)",
                "so2": f"≤ {self.WHO_GUIDELINES['so2']} µg/m³ (24h)",
                "o3": f"≤ {self.WHO_GUIDELINES['o3']} µg/m³ (8h)",
                "co": f"≤ {self.WHO_GUIDELINES['co']} mg/m³ (24h)",
            },
        }
