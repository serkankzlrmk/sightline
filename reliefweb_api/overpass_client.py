"""
OpenStreetMap Overpass Client — Sightline
==========================================
Overpass API — OSM verisi (hastaneler, okullar, su kaynakları, kamplar).
Keyless, ama User-Agent politikası zorunlu (Overpass kullanım kuralları).

   Bizim: Sightline -> overpass_client.py -> Overpass API (POST interpreter)

Tek dosya, tek process. API anahtarı GEREKMEZ (keyless).

1 endpoint:
  Query: POST https://overpass-api.de/api/interpreter  body: data=<QL sorgusu>

Kullanım senaryosu: insani — kamp çevresinde altyapı sorgusu
  ("kampın 5km içinde kaç hastane/su kaynağı var?")

Fallback: overpass-api.de aşırı yüklenince 504/529 döner — mirror'lara
sırayla dener (overpass.kumi.systems).

Entegrasyon:
1. config.py'de OVERPASS_* parametreleri (keyless, defaults mevcut)
2. overpass_tools.py'da @tool tanımı
3. server.py'de init_overpass_tools() çağrısı
4. agent/relief_agent.py all_tools'a ekler
"""

import logging
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Overpass ana sunucu + yedek mirror'lar (aşırı yüklenince sırayla denenir)
_DEFAULT_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


class SimpleCache:
    """TTL-based thread-safe cache (diğer client'larla aynı desen)."""

    def __init__(self, ttl: int = 3600, max_size: int = 200):
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


class OverpassClient:
    """Overpass API client — keyless, mirror fallback, TTL cache."""

    USER_AGENT = "Sightline/1.0 (humanitarian analytics; contact: support@sightlinehumanitarian.com)"

    def __init__(
        self,
        base_url: str = "",
        mirrors: list[str] | None = None,
        timeout: float = 30.0,
        cache_ttl: int = 3600,
        rate_limit_requests: int = 10,
        rate_limit_period: float = 60.0,
    ):
        self.timeout = timeout
        self._mirrors = mirrors or _DEFAULT_MIRRORS
        if base_url:
            self._mirrors = [base_url] + self._mirrors
        self._cache = SimpleCache(ttl=cache_ttl, max_size=200)
        self._rl_lock = threading.Lock()
        self._rl_times: list[float] = []
        self._rl_max = rate_limit_requests
        self._rl_period = rate_limit_period
        self._client = httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": self.USER_AGENT})

    def _rate_limit(self) -> None:
        with self._rl_lock:
            now = time.time()
            self._rl_times = [t for t in self._rl_times if now - t < self._rl_period]
            if len(self._rl_times) >= self._rl_max:
                sleep_s = self._rl_period - (now - self._rl_times[0])
                logger.info("Overpass rate limit: %.1fs bekleniyor", sleep_s)
                time.sleep(max(sleep_s, 0.5))
                self._rl_times = [t for t in self._rl_times if now - t < self._rl_period]
            self._rl_times.append(time.time())

    def query(self, ql_query: str) -> dict:
        """Overpass QL sorgusu çalıştır. Döner: {"ok": bool, "elements": [...], "error": str?}

        Sorgu örneği:
          [out:json][timeout:15];
          (node["amenity"="hospital"](around:5000,12.05,24.88););
          out body 10;
        """
        cache_key = f"q:{ql_query[:100]}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        last_error = ""
        for mirror in self._mirrors:
            try:
                self._rate_limit()
                resp = self._client.post(mirror, data={"data": ql_query})
                if resp.status_code == 200:
                    data = resp.json()
                    result = {"ok": True, "elements": data.get("elements", [])}
                    self._cache.set(cache_key, result)
                    return result
                last_error = f"Overpass HTTP {resp.status_code}"
                logger.warning("Overpass %s başarısız (%s) — sonraki mirror deneniyor", mirror, resp.status_code)
            except Exception as e:  # noqa: BLE001
                last_error = str(e)
                logger.warning("Overpass %s hatası: %s — sonraki mirror deneniyor", mirror, str(e)[:80])
        result = {"ok": False, "elements": [], "error": last_error or "Overpass erişilemedi"}
        self._cache.set(cache_key, result)
        return result

    def query_nearby(self, lat: float, lon: float, radius_m: int, amenity: str, limit: int = 10) -> dict:
        """Koordinat çevresinde belirli amenity tipini ara.

        amenity değerleri: hospital, school, drinking_water, shelter,
        clinic, pharmacy, place_of_worship, community_centre, toilets.
        """
        ql = (
            f"[out:json][timeout:20];"
            f'(node["amenity"="{amenity}"](around:{radius_m},{lat},{lon});'
            f'way["amenity"="{amenity}"](around:{radius_m},{lat},{lon}););'
            f"out body {limit};"
        )
        res = self.query(ql)
        if not res.get("ok"):
            return res
        # way elementleri için merkez nokta hesaplama gerekmez — isim + tip yeter
        items = []
        for e in res["elements"][:limit]:
            tags = e.get("tags") or {}
            items.append(
                {
                    "name": tags.get("name", ""),
                    "amenity": tags.get("amenity", amenity),
                    "lat": e.get("lat"),
                    "lon": e.get("lon"),
                }
            )
        return {"ok": True, "items": items, "count": len(items)}

    def close(self) -> None:
        self._client.close()


# ── Singleton + init ──────────────────────────────────────────────────────────
_overpass_client: OverpassClient | None = None


def get_overpass_client() -> OverpassClient | None:
    return _overpass_client


def init_overpass_client(base_url: str = "", **kwargs: Any) -> bool:
    """Keyless — her zaman başarılı."""
    global _overpass_client
    try:
        _overpass_client = OverpassClient(base_url=base_url, **kwargs)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("Overpass client init hatası: %s", e)
        return False
