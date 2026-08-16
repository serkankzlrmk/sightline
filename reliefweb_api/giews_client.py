"""
FAO GIEWS Client — Sightline
=============================
GIEWS (Global Information and Early Warning System) — gıda fiyatları ve
mahsul verisi. FAO'nun gıda güvenliği erken uyarı sistemi.

STATUS: ŞEMA KEŞFİ BEKLİYOR (Aug 2026)
  - giews.fao.org DNS'te YOK
  - data.apps.fao.org/giews/ Terria tabanlı SPA — tüm path'ler aynı HTML
    döndürüyor (API endpoint'leri build JS'e gömülü, public REST API
    belgelenmemiş görünüyor)
  - Bu client graceful: init her zaman True ama query fonksiyonları
    "şema doğrulanmadı" uyarısı döner. Gerçek endpoint/şema netleşince
    query_* fonksiyonları güncellenir.

Not: HDX üzerinden food_prices + food_security zaten mevcut
(hdx_get_ipc_phases, get_food_prices_sync) — GIEWS ek değer katacaksa
bu client aktifleştirilir.
"""

import logging
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Bilinen potansiyel base'ler — şema netleşince ilk geçerli olan kullanılır
_CANDIDATE_BASES = [
    "https://data.apps.fao.org/giews",
    "https://giews.fao.org/giews",
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


class GIEWSClient:
    """GIEWS client — keyless. Şema netleşene kadar pasif."""

    def __init__(self, base_url: str = "", timeout: float = 20.0,
                 cache_ttl: int = 86400, rate_limit_requests: int = 20,
                 rate_limit_period: float = 60.0):
        self.base_url = base_url or _CANDIDATE_BASES[0]
        self.timeout = timeout
        self._cache = SimpleCache(ttl=cache_ttl, max_size=200)
        self._rl_lock = threading.Lock()
        self._rl_times: list[float] = []
        self._rl_max = rate_limit_requests
        self._rl_period = rate_limit_period
        self._client = httpx.Client(timeout=timeout, follow_redirects=True,
                                    headers={"User-Agent": "Sightline/1.0 (humanitarian analytics)"})
        self._schema_verified = False

    def _rate_limit(self) -> None:
        with self._rl_lock:
            now = time.time()
            self._rl_times = [t for t in self._rl_times if now - t < self._rl_period]
            if len(self._rl_times) >= self._rl_max:
                sleep_s = self._rl_period - (now - self._rl_times[0])
                time.sleep(max(sleep_s, 0.5))
                self._rl_times = [t for t in self._rl_times if now - t < self._rl_period]
            self._rl_times.append(time.time())

    def get_food_prices(self, country: str = "", commodity: str = "",
                        limit: int = 10) -> dict:
        """Gıda fiyatları — şema doğrulanmadıysa pasif uyarı döner."""
        return {
            "ok": False,
            "error": "GIEWS şeması doğrulanmadı — public REST API bulunamadı. "
                     "Endpoint netleşince aktifleşecek. HDX hdx_get_ipc_phases "
                     "kullanılabilir.",
        }

    def get_crop_forecast(self, country: str = "") -> dict:
        """Mahsul tahmini — şema doğrulanmadıysa pasif uyarı döner."""
        return {
            "ok": False,
            "error": "GIEWS şeması doğrulanmadı — public REST API bulunamadı.",
        }

    def close(self) -> None:
        self._client.close()


# ── Singleton + init ──────────────────────────────────────────────────────────
_giews_client: GIEWSClient | None = None


def get_giews_client() -> GIEWSClient | None:
    return _giews_client


def init_giews_client(base_url: str = "", **kwargs: Any) -> bool:
    """Keyless — her zaman başarılı (ama pasif mod)."""
    global _giews_client
    try:
        _giews_client = GIEWSClient(base_url=base_url, **kwargs)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("GIEWS client init hatası: %s", e)
        return False
