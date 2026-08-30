"""
NASA FIRMS Client — Sightline
==============================
FIRMS (Fire Information for Resource Management System) — MODIS/VIIRS
termal anomali (yangın) verisi. NRT (Near Real Time) yangın tespiti.

API: GET https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{source}/{day}/{coords}/{radius}
  - MAP_KEY: NASA Earthdata hesabıyla ücretsiz alınır
  - source: VIIRS_SNPP_NRT (günlük), MODIS_NRT (günlük)
  - day: 1-10 günlük pencere
  - coords: lat,lon  |  radius: km
  - CSV döner: latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,
    satellite,instrument,confidence,version,bright_ti5,frp,daynight

Entegrasyon:
1. config.py'de FIRMS_MAP_KEY (key yoksa graceful skip — ACLED deseni)
2. firms_tools.py'da @tool tanımı
3. server.py'de init_firms_tools() çağrısı
4. agent/relief_agent.py all_tools'a ekler
"""

import csv
import io
import logging
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class SimpleCache:
    """TTL-based thread-safe cache (diğer client'larla aynı desen)."""

    def __init__(self, ttl: int = 1800, max_size: int = 100):
        self.ttl = ttl
        self.max_size = max_size
        self._cache: dict[str, tuple] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key in self._cache:
                value, ts = self._cache[key]
                if time.time() - ts < self.ttl:
                    return value
                del self._cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if len(self._cache) >= self.max_size and key not in self._cache:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (value, time.time())


class FIRMSClient:
    """NASA FIRMS API client — MAP_KEY, CSV parse, TTL cache."""

    BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

    def __init__(
        self,
        map_key: str,
        base_url: str = "",
        timeout: float = 25.0,
        cache_ttl: int = 1800,
        rate_limit_requests: int = 15,
        rate_limit_period: float = 60.0,
    ):
        self.map_key = map_key
        self.base_url = base_url.rstrip("/") or self.BASE_URL
        self.timeout = timeout
        self._cache = SimpleCache(ttl=cache_ttl, max_size=100)
        self._rl_lock = threading.Lock()
        self._rl_times: list[float] = []
        self._rl_max = rate_limit_requests
        self._rl_period = rate_limit_period
        self._client = httpx.Client(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": "Sightline/1.0 (humanitarian analytics)"}
        )

    def _rate_limit(self) -> None:
        with self._rl_lock:
            now = time.time()
            self._rl_times = [t for t in self._rl_times if now - t < self._rl_period]
            if len(self._rl_times) >= self._rl_max:
                sleep_s = self._rl_period - (now - self._rl_times[0])
                time.sleep(max(sleep_s, 0.5))
                self._rl_times = [t for t in self._rl_times if now - t < self._rl_period]
            self._rl_times.append(time.time())

    def get_fires(
        self, lat: float, lon: float, radius_km: int = 50, days: int = 1, source: str = "VIIRS_SNPP_NRT"
    ) -> dict:
        """Koordinat çevresinde aktif yangın/termal anomali ara.

        Döner: {"ok": bool, "fires": [...], "count": int, "error": str?}
        Her yangın: lat, lon, acq_date, frp, confidence, satellite.
        """
        cache_key = f"fires:{lat}:{lon}:{radius_km}:{days}:{source}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        url = f"{self.base_url}/{self.map_key}/{source}/{min(days, 10)}/{lat},{lon}/{radius_km}"
        try:
            self._rate_limit()
            resp = self._client.get(url)
            if resp.status_code == 200 and "latitude" in resp.text:
                reader = csv.DictReader(io.StringIO(resp.text))
                rows = list(reader)
                fires = [
                    {
                        "lat": float(r.get("latitude", 0)),
                        "lon": float(r.get("longitude", 0)),
                        "date": r.get("acq_date", ""),
                        "frp": r.get("frp", ""),
                        "confidence": r.get("confidence", ""),
                        "satellite": r.get("satellite", ""),
                    }
                    for r in rows[:100]
                ]
                result = {"ok": True, "fires": fires, "count": len(fires)}
            elif resp.status_code in (400, 401, 403):
                result = {
                    "ok": False,
                    "fires": [],
                    "error": f"FIRMS auth/param hatası ({resp.status_code}): {resp.text[:200]}",
                }
            else:
                result = {"ok": False, "fires": [], "error": f"FIRMS HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:  # noqa: BLE001
            result = {"ok": False, "fires": [], "error": str(e)}
        self._cache.set(cache_key, result)
        return result

    def close(self) -> None:
        self._client.close()


# ── Singleton + init ──────────────────────────────────────────────────────────
_firms_client: FIRMSClient | None = None


def get_firms_client() -> FIRMSClient | None:
    return _firms_client


def init_firms_client(map_key: str = "", **kwargs: Any) -> bool:
    """MAP_KEY yoksa False — tool'lar eklenmez (graceful skip)."""
    global _firms_client
    if not map_key:
        logger.warning("FIRMS_MAP_KEY yok — FIRMS tool'ları devre dışı")
        return False
    try:
        _firms_client = FIRMSClient(map_key=map_key, **kwargs)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("FIRMS client init hatası: %s", e)
        return False
