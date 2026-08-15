"""
ACLED (Armed Conflict Location & Event Data) Client — Sightline
================================================================
ACLED REST API — çatışma olay verisi (battles, explosions, protests,
riots, violence against civilians). İKİ auth modu desteklenir:

  1. Session login (email + password):
     POST https://acleddata.com/user/login?_format=json
     body: {"name": "<email>", "pass": "<password>"}
     → session cookie + csrf_token. Cookie sonraki tüm isteklerde taşınır.
     (Kullanıcının ACLED dökümantasyonundaki "Make authentication request"
     adımı — getting-started sayfasında belgelenen yöntem.)

  2. API key (portaldan alınan):
     query param: ?key=<ACLED_API_KEY>

Endpoint:
  Event search: https://api.acleddata.com/acled/read
  (country / event_type / event_date filtreleri, fatalities dahil)

Entegrasyon:
1. config.py'de ACLED_* parametreleri (ACLED_EMAIL + ACLED_PASSWORD VEYA
   ACLED_API_KEY; ikisi de yoksa graceful skip)
2. acled_tools.py'da @tool tanımları
3. server.py'de init_acled_tools() çağrısı
4. agent/relief_agent.py all_tools'a ekler

Güvenlik notu: kimlik bilgileri asla koda/loga yazılmaz — yalnızca .env'den
okunur (gitignore'da).
"""

import logging
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class SimpleCache:
    """TTL-based thread-safe cache (weather_client.py ile aynı desen)."""

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


class ACLEDClient:
    """ACLED API client — singleton, thread-safe, TTL cache.

    Login modu: ``email`` + ``password`` verilirse __init__'te session
    cookie alınır (Drupal login endpoint'i). ``api_key`` verilirse query
    param olarak taşınır. İkisi de yoksa client yine oluşur ama tüm
    istekler ``{"ok": False, "error": "...auth eksik"}`` döner.
    """

    LOGIN_URL = "https://acleddata.com/user/login?_format=json"
    BASE_URL = "https://api.acleddata.com/acled/read"

    def __init__(
        self,
        email: str = "",
        password: str = "",
        api_key: str = "",
        base_url: str = "",
        login_url: str = "",
        timeout: float = 25.0,
        cache_ttl: int = 3600,
        rate_limit_requests: int = 10,
        rate_limit_period: float = 60.0,
    ):
        self.email = email
        self.password = password
        self.api_key = api_key
        self.base_url = base_url or self.BASE_URL
        self.login_url = login_url or self.LOGIN_URL
        self.timeout = timeout
        self._cache = SimpleCache(ttl=cache_ttl, max_size=200)
        self._rl_lock = threading.Lock()
        self._rl_times: list[float] = []
        self._rl_max = rate_limit_requests
        self._rl_period = rate_limit_period
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)
        self._logged_in = False
        self._csrf_token = ""
        # Session auth'u baştan dene (email+pass varsa)
        if email and password:
            self._logged_in = self._login()
        elif api_key:
            self._logged_in = True  # key modu — login gerekmez

    # ── Auth ──────────────────────────────────────────────────────────────────
    def _login(self) -> bool:
        """Drupal login: session cookie + csrf_token al."""
        try:
            resp = self._client.post(
                self.login_url,
                json={"name": self.email, "pass": self.password},
            )
            if resp.status_code == 200:
                data = resp.json()
                self._csrf_token = data.get("csrf_token", "")
                # httpx.Client cookie jar session cookie'yi otomatik tutar
                logger.info("ACLED session login başarılı (uid=%s)", data.get("current_user", {}).get("uid", "?"))
                return True
            logger.warning("ACLED login başarısız: HTTP %s", resp.status_code)
            return False
        except Exception as e:  # noqa: BLE001
            logger.warning("ACLED login hatası: %s", e)
            return False

    # ── Rate limit ─────────────────────────────────────────────────────────────
    def _rate_limit(self) -> None:
        """ACLED: 10 req/min (ücretsiz) — pencere içinde max istek."""
        with self._rl_lock:
            now = time.time()
            self._rl_times = [t for t in self._rl_times if now - t < self._rl_period]
            if len(self._rl_times) >= self._rl_max:
                sleep_s = self._rl_period - (now - self._rl_times[0])
                logger.info("ACLED rate limit: %.1fs bekleniyor", sleep_s)
                time.sleep(max(sleep_s, 0.5))
                self._rl_times = [t for t in self._rl_times if now - t < self._rl_period]
            self._rl_times.append(time.time())

    # ── Search ─────────────────────────────────────────────────────────────────
    def search_events(
        self,
        country: str = "",
        event_type: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 25,
        **kwargs: Any,
    ) -> dict:
        """Çatışma olaylarını ara. Döner: {"ok": bool, "data": [...], "error": str?}"""
        if not self._logged_in:
            return {"ok": False, "error": "ACLED auth yok — ACLED_EMAIL/ACLED_PASSWORD veya ACLED_API_KEY gerekli"}
        cache_key = f"evt:{country}:{event_type}:{date_from}:{date_to}:{limit}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        params: dict[str, Any] = {"limit": min(limit, 10000)}
        if self.api_key:
            params["key"] = self.api_key
        if country:
            params["country"] = country
        if event_type:
            params["event_type"] = event_type
        if date_from and date_to:
            params["event_date"] = f"{date_from}|{date_to}"

        try:
            self._rate_limit()
            resp = self._client.get(self.base_url, params=params)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                result: dict = {"ok": True, "data": data}
            elif resp.status_code in (401, 403):
                # Session cookie süresi dolmuş olabilir — tekrar login dene
                if self.email and self.password and not self.api_key:
                    self._logged_in = self._login()
                    if self._logged_in:
                        resp = self._client.get(self.base_url, params=params)
                        if resp.status_code == 200:
                            result = {"ok": True, "data": resp.json().get("data", [])}
                        else:
                            result = {"ok": False, "error": f"ACLED HTTP {resp.status_code}: {resp.text[:200]}"}
                    else:
                        result = {"ok": False, "error": "ACLED re-login başarısız"}
                else:
                    result = {"ok": False, "error": f"ACLED auth hatası ({resp.status_code}): {resp.text[:200]}"}
            else:
                result = {"ok": False, "error": f"ACLED HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:  # noqa: BLE001
            result = {"ok": False, "error": str(e)}

        self._cache.set(cache_key, result)
        return result

    def close(self) -> None:
        self._client.close()


# ── Singleton + init (weather/hdx deseni) ────────────────────────────────────
_acled_client: ACLEDClient | None = None


def get_acled_client() -> ACLEDClient | None:
    return _acled_client


def init_acled_client(
    email: str = "",
    password: str = "",
    api_key: str = "",
    **kwargs: Any,
) -> bool:
    """Email+pass veya API key yoksa False döner — agent tool'ları eklenmez.

    NOT: login ilk istek anında yapılır (init'te değil) — böylece yanlış
    şifre sunucu başlatmayı bloklamaz; tool çağrısında "auth hatası" döner.
    """
    global _acled_client
    if not email and not api_key:
        logger.warning("ACLED_EMAIL/ACLED_API_KEY yok — ACLED tool'ları devre dışı")
        return False
    try:
        _acled_client = ACLEDClient(email=email, password=password, api_key=api_key, **kwargs)
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("ACLED client init hatası: %s", e)
        return False
