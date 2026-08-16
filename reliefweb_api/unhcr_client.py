"""
UNHCR Client — Sightline
========================
UNHCR Refugee Data Finder API — mülteci nüfusu, demografik kırılım,
nowcasting (güncel tahmini sayı).

Auth: UNHCR API portalinden alınan API key — Authorization: Bearer <key>.
Endpoint'ler (api.unhcr.org):
  1. GET /population/v1/{year}?...  — mülteci/iltica nüfusu
  2. Demographics: cinsiyet/yaş grubu kırılımı
  3. Nowcast: güncel tahmini mülteci sayısı

STATUS: API key GEREKLİ — key yoksa init False (graceful skip, ACLED deseni).
Key gelince canlı şema doğrulaması yapılır (endpoint path'leri netleşir).

Not: UNHCR API'si değişken — ilk canlı testte gerçek endpoint/parametre
şeması doğrulanıp query fonksiyonları güncellenecek.
"""

import logging
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class SimpleCache:
    """TTL-based thread-safe cache (diğer client'larla aynı desen)."""

    def __init__(self, ttl: int = 86400, max_size: int = 200):
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


class UNHCRClient:
    """UNHCR API client — Bearer token, TTL cache, rate limit."""

    BASE_URL = "https://api.unhcr.org"

    def __init__(self, api_key: str, base_url: str = "", timeout: float = 20.0,
                 cache_ttl: int = 86400, rate_limit_requests: int = 30,
                 rate_limit_period: float = 60.0):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/") or self.BASE_URL
        self.timeout = timeout
        self._cache = SimpleCache(ttl=cache_ttl, max_size=200)
        self._rl_lock = threading.Lock()
        self._rl_times: list[float] = []
        self._rl_max = rate_limit_requests
        self._rl_period = rate_limit_period
        self._client = httpx.Client(
            timeout=timeout, follow_redirects=True,
            headers={"Authorization": f"Bearer {api_key}",
                     "User-Agent": "Sightline/1.0 (humanitarian analytics)"},
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

    def _get(self, path: str, params: dict | None = None) -> dict:
        """Genel GET — şema doğrulaması bekleyen path'ler için."""
        cache_key = f"{path}:{str(params)[:80]}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            self._rate_limit()
            resp = self._client.get(f"{self.base_url}{path}", params=params)
            if resp.status_code == 200:
                result = {"ok": True, "data": resp.json()}
            elif resp.status_code in (401, 403):
                result = {"ok": False, "error": f"UNHCR auth hatası ({resp.status_code}) — API key geçersiz olabilir"}
            else:
                result = {"ok": False, "error": f"UNHCR HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:  # noqa: BLE001
            result = {"ok": False, "error": str(e)}
        self._cache.set(cache_key, result)
        return result

    def get_population(self, country_code: str = "", year: int = 0) -> dict:
        """Mülteci nüfusu — endpoint şeması canlı testte doğrulanacak."""
        return self._get("/population/v1", {"year": year or None, "country_of_asylum": country_code or None})

    def get_demographics(self, country_code: str = "", year: int = 0) -> dict:
        """Demografik kırılım — endpoint şeması canlı testte doğrulanacak."""
        return self._get("/population/v1/demographics", {"year": year or None, "country_of_asylum": country_code or None})

    def get_nowcast(self, country_code: str = "") -> dict:
        """Nowcast (güncel tahmini nüfus) — endpoint şeması canlı testte doğrulanacak."""
        return self._get("/nowcast/v1", {"country_of_asylum": country_code or None})

    def close(self) -> None:
        self._client.close()


# ── Singleton + init ──────────────────────────────────────────────────────────
_unhcr_client: UNHCRClient | None = None


def get_unhcr_client() -> UNHCRClient | None:
    return _unhcr_client


def init_unhcr_client(api_key: str = "", **kwargs: Any) -> bool:
    """Key yoksa False — tool'lar eklenmez (graceful skip)."""
    global _unhcr_client
    if not api_key:
        logger.warning("UNHCR_API_KEY yok — UNHCR tool'ları devre dışı")
        return False
    try:
        _unhcr_client = UNHCRClient(api_key=api_key, **kwargs)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("UNHCR client init hatası: %s", e)
        return False
