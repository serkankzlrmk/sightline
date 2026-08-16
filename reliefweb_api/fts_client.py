"""
OCHA FTS (Financial Tracking Service) v2 Client — Sightline
============================================================
FTS v2 public API — insani fonlama planları (keyless).

FTS v2 public'te SADECE iki endpoint aktif:
  1. /v2/public/plan      — insani planlar (HNO/HRP/Flash Appeal)
  2. /v2/public/location  — ülke/bölge listesi (iso3)

NOT: /v2/public/flow (gerçekleşen fon akışları) endpoint'i 2025 itibarıyla
public API'den kaldırılmış (404) — funding figure'ları yalnızca FTS web
arayüzünde. Bu client plan bazlı REQUIREMENT verisi sunar; gerçekleşen
fon karşılaştırması HDX funding tool'u ile yapılabilir.

Plan listesinde `locations[].iso3` alanı var — API `locationId` filtre
parametresini YOK SAYIYOR (tüm planları döndürüyor), bu yüzden client-side
eşleştirme yapılır: yıl için tüm planları çek (limit=300), iso3 eşle.

Entegrasyon:
1. config.py'de FTS_* parametreleri (keyless — her zaman init)
2. fts_tools.py'da @tool tanımları
3. server.py'de init_fts_tools() çağrısı
4. agent/relief_agent.py all_tools'a ekler
"""

import logging
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


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


class FTSClient:
    """OCHA FTS v2 public API client — keyless, singleton, TTL cache."""

    BASE_URL = "https://api.hpc.tools/v2/public"

    def __init__(self, base_url: str = "", timeout: float = 20.0,
                 cache_ttl: int = 3600, rate_limit_requests: int = 30,
                 rate_limit_period: float = 60.0):
        self.base_url = base_url.rstrip("/") or self.BASE_URL
        self.timeout = timeout
        self._cache = SimpleCache(ttl=cache_ttl, max_size=200)
        self._rl_lock = threading.Lock()
        self._rl_times: list[float] = []
        self._rl_max = rate_limit_requests
        self._rl_period = rate_limit_period
        self._client = httpx.Client(timeout=timeout, follow_redirects=True,
                                    headers={"User-Agent": "Sightline/1.0 (humanitarian analytics)"})

    def _rate_limit(self) -> None:
        with self._rl_lock:
            now = time.time()
            self._rl_times = [t for t in self._rl_times if now - t < self._rl_period]
            if len(self._rl_times) >= self._rl_max:
                sleep_s = self._rl_period - (now - self._rl_times[0])
                logger.info("FTS rate limit: %.1fs bekleniyor", sleep_s)
                time.sleep(max(sleep_s, 0.5))
                self._rl_times = [t for t in self._rl_times if now - t < self._rl_period]
            self._rl_times.append(time.time())

    def get_plans(self, year: int, limit: int = 300) -> dict:
        """Yıl için tüm insani planları getir (limit=300 — tümü)."""
        cache_key = f"plans:{year}:{limit}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            self._rate_limit()
            resp = self._client.get(f"{self.base_url}/plan", params={"year": year, "limit": limit})
            if resp.status_code == 200:
                result = {"ok": True, "data": resp.json().get("data", [])}
            else:
                result = {"ok": False, "error": f"FTS HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:  # noqa: BLE001
            result = {"ok": False, "error": str(e)}
        self._cache.set(cache_key, result)
        return result

    def get_country_plans(self, iso3: str, year: int) -> dict:
        """Ülke (iso3) için planları client-side filtrele.

        Plan şeması: locations[] her biri {id, iso3, name}. Filtre:
        locations içinde iso3 eşleşen planlar döner. Her plan:
        {id, name, category, orig_requirements, revised_requirements,
        emergencies[]} — ya da eşleşme yoksa {"ok": True, "data": []}.
        """
        res = self.get_plans(year=year, limit=300)
        if not res.get("ok"):
            return res
        iso3 = iso3.upper()
        matched = []
        for p in res["data"]:
            locs = p.get("locations") or []
            if any((l.get("iso3") or "").upper() == iso3 for l in locs):
                pv = p.get("planVersion") or {}
                cats = p.get("categories") or []
                ems = p.get("emergencies") or []
                matched.append({
                    "id": p.get("id"),
                    "name": pv.get("name") or pv.get("shortName") or "",
                    "category": cats[0].get("name", "") if cats else "",
                    "orig_requirements": p.get("origRequirements"),
                    "revised_requirements": p.get("revisedRequirements"),
                    "emergencies": [e.get("name", "") for e in ems[:3]],
                })
        return {"ok": True, "data": matched}

    def close(self) -> None:
        self._client.close()


# ── Singleton + init ──────────────────────────────────────────────────────────
_fts_client: FTSClient | None = None


def get_fts_client() -> FTSClient | None:
    return _fts_client


def init_fts_client(base_url: str = "", **kwargs: Any) -> bool:
    """Keyless — her zaman başarılı (HDX pattern)."""
    global _fts_client
    try:
        _fts_client = FTSClient(base_url=base_url, **kwargs)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("FTS client init hatası: %s", e)
        return False
