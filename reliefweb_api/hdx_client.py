"""
HDX Direct API Client — Sightline Entegrasyonu
==============================================

Bu modül Sightline'ın Python backend'ine doğrudan entegre edilmek üzere
tasarlanmıştır. MCP server'a ihtiyaç duymaz, HDX HAPI API'ye doğrudan
HTTP istekleri yapar.

Neden MCP Server'sız?
---------------------
MCP (Model Context Protocol) AI assistant'lar (Claude, GPT) için tasarlanmış
bir protokol. Sightline zaten bir Python Flask backend — araya MCP server sokmak
gereksiz karmaşıklık yaratır. Bunun yerine direkt HTTP client olarak HDX HAPI
API'ye bağlanıyoruz:

  ❌ MCP:  Sightline → MCP Client → MCP Server (ayrı process) → HDX API
  ✅ Bizim: Sightline → hdx_client.py (bu dosya) → HDX HAPI API

Tek dosya, tek process, tek deployment.

Sightline'a Entegrasyon:
1. Bu dosyayı Sightline repo root'una kopyala: hdx_client.py
2. .env'e ekle: HDX_APP_IDENTIFIER=<base64_encoded_key>
3. Flask app'te başlat: hdx = HDXClient.from_env()
4. API endpoint'lerde kullan: result = hdx.get_refugees_sync("SYR")
5. SITREP pipeline'da kullan: context = hdx.get_sitrep_context_sync("SYR")

HDX HAPI API Nedir?
-------------------
HDX (Humanitarian Data Exchange), OCHA'nın (UN Office for the Coordination of
Humanitarian Affairs) küresel insani veri platformudur. HAPI (HDX API), bu
platformdaki yapılandırılmış insani veriye programatik erişim sağlar.

Veri Kategorileri:
- Metadata: Lokasyonlar, admin bölgeleri, organizasyonlar, sektörler
- Affected People: Mülteciler, IDP'ler, ihtiyaç sahipleri, geri dönenler
- Baseline Population: Temel nüfus verileri
- Climate: Yağış verileri
- Coordination: Operasyonel varlık, finansman, çatışma olayları, ulusal risk
- Food Security: Gıda güvenliği (IPC), gıda fiyatları, yoksulluk oranları

Kullanım:
    from hdx_client import HDXClient

    # Başlat (env'den HDX_APP_IDENTIFIER okur)
    hdx = HDXClient.from_env()

    # Veya explicit
    hdx = HDXClient(app_identifier="your_base64_key_here")

    # --- Async metodlar (SITREP pipeline, background tasks) ---
    locations = await hdx.get_locations(limit=10)
    availability = await hdx.get_data_availability("TUR")
    refugees = await hdx.get_refugees("SYR", limit=10)
    overview = await hdx.get_country_overview("AFG")  # paralel fetch
    sitrep_ctx = await hdx.get_sitrep_context("SYR")  # SITREP-ready format

    # --- Sync metodlar (Flask route'ları) ---
    locations = hdx.get_locations_sync(limit=10)
    refugees = hdx.get_refugees_sync("SYR", limit=10)
    overview = hdx.get_country_overview_sync("AFG")
    sitrep_ctx = hdx.get_sitrep_context_sync("SYR")

API Key Nasıl Alınır?
---------------------
1. https://hapi.humdata.org/docs#/Generate%20App%20Identifier adresine git
2. Uygulama adı ve e-posta gir
3. Base64 ile encode edilmiş key al (format: base64("app_name:email"))
4. .env dosyasına ekle: HDX_APP_IDENTIFIER=<key>

Örnek: base64("hdx-mcp-agent:your-email@example.com")
       = "aGR4LW1jcC1hZ2VudDp5b3VyLWVtYWlsQGV4YW1wbGUuY29t=="
"""

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class HDXResult:
    """HDX API çağrı sonucu wrapper'ı.

    Tüm HDX API çağrıları bu nesneyi döndürür. Başarılı/başarısız durum,
    ham veri, hata mesajı ve parametre bilgisi içerir.

    Attributes:
        success: Çağrı başarılı mı?
        tool: HDX endpoint adı (ör: "metadata_location").
        data: Ham API response verisi (dict listesi).
        error: Hata mesajı (başarısızsa).
        count: Dönen kayıt sayısı.
        params: Çağrıda kullanılan parametreler.
    """
    success: bool
    tool: str = ""
    data: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    count: int = 0
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON serialization için dict'e çevir."""
        return {
            "success": self.success,
            "tool": self.tool,
            "data": self.data,
            "error": self.error,
            "count": self.count,
            "params": self.params,
        }

    def to_sitrep_context(self) -> dict[str, Any]:
        """SITREP prompt'una inject edilecek condensed format.

        LLM prompt'una doğrudan verilebilecek özet format.
        Tüm ham veri yerine sadece ilk 5 kayıt ve count döner.
        """
        if not self.success:
            return {"source": "HDX", "error": self.error, "tool": self.tool}

        return {
            "source": "HDX",
            "tool": self.tool,
            "record_count": self.count,
            "data_preview": self.data[:5] if self.data else [],
        }


# ============================================================================
# Cache (TTL-based, Thread-Safe)
# ============================================================================

class SimpleCache:
    """HDX metadata sorguları için TTL tabanlı bellek içi önbellek.

    Metadata sorguları (lokasyonlar, organizasyonlar vb.) seyrek değiştiği
    için 24 saat TTL ile önbelleğe alınır. Bu sayede tekrarlanan API
    çağrıları azalır ve yanıt süresi düşer.

    Args:
        ttl: Önbellek süresi (saniye). Varsayılan 86400 (24 saat).
        max_size: Maksimum önbellek öğesi sayısı. Varsayılan 500.
    """

    def __init__(self, ttl: int = 86400, max_size: int = 500):
        self.ttl = ttl
        self.max_size = max_size
        self._cache: dict[str, tuple] = {}  # key -> (value, timestamp)

    def get(self, key: str) -> Any | None:
        """Önbellekten değer al. Süresi dolmuşsa sil."""
        if key in self._cache:
            value, ts = self._cache[key]
            if time.time() - ts < self.ttl:
                return value
            del self._cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        """Önbelleğe değer yaz. Doluysa en eski öğeyi sil."""
        if len(self._cache) >= self.max_size and key not in self._cache:
            oldest = min(self._cache, key=lambda k: self._cache[k][1])
            del self._cache[oldest]
        self._cache[key] = (value, time.time())

    def clear(self) -> None:
        """Tüm önbelleği temizle."""
        self._cache.clear()

    def stats(self) -> dict[str, int]:
        """Önbellek istatistikleri."""
        return {"size": len(self._cache), "max_size": self.max_size, "ttl": self.ttl}


# ============================================================================
# HDX Direct API Client
# ============================================================================

class HDXClient:
    """HDX Direct API Client — Sightline Entegrasyonu.

    HDX HAPI API'ye doğrudan HTTP istekleri yapar. MCP server'a ihtiyaç duymaz.
    Flask app'te singleton olarak kullanılmak üzere tasarlanmıştır.

    Hem async hem sync metodlar sağlar:
    - Async metodlar: SITREP pipeline, background tasks için
    - Sync metodlar (_sync suffix): Flask route'ları için

    Özellikler:
    - Otomatik rate limiting (10 req/dk varsayılan)
    - Metadata sorguları için 24 saat TTL önbellek
    - Paralel veri çekme (get_country_overview)
    - SITREP-ready context formatı (get_sitrep_context)

    Flask'ta Kullanım:
        # app.py veya extensions.py
        from hdx_client import HDXClient
        hdx_client = HDXClient.from_env()

        # Route'larda
        @app.route('/api/hdx/refugees/<country>')
        def hdx_refugees(country):
            result = hdx_client.get_refugees_sync(country)
            return jsonify(result.to_dict())

        # SITREP pipeline'da
        context = hdx_client.get_sitrep_context_sync("SYR")
        prompt += format_hdx_context(context)
    """

    BASE_URL = "https://hapi.humdata.org/api/v2"

    # HDX HAPI endpoint adları (referans için)
    ENDPOINTS = {
        # Metadata & Discovery
        "location": "/metadata/location",
        "admin1": "/metadata/admin1",
        "admin2": "/metadata/admin2",
        "data_availability": "/metadata/data-availability",
        "dataset": "/metadata/dataset",
        "resource": "/metadata/resource",
        "org": "/metadata/org",
        "sector": "/metadata/sector",
        "currency": "/metadata/currency",
        "org_type": "/metadata/org-type",
        "wfp_commodity": "/metadata/wfp-commodity",
        "wfp_market": "/metadata/wfp-market",
        # Affected People
        "refugees": "/affected-people/refugees-persons-of-concern",
        "humanitarian_needs": "/affected-people/humanitarian-needs",
        "idps": "/affected-people/idps",
        "returnees": "/affected-people/returnees",
        # Demographics & Geography
        "population": "/geography-infrastructure/baseline-population",
        # Climate
        "rainfall": "/climate/rainfall",
        # Coordination & Context
        "operational_presence": "/coordination-context/operational-presence",
        "funding": "/coordination-context/funding",
        "conflict_events": "/coordination-context/conflict-events",
        "national_risk": "/coordination-context/national-risk",
        # Food Security & Poverty
        "food_security": "/food-security-nutrition-poverty/food-security",
        "food_prices": "/food-security-nutrition-poverty/food-prices-market-monitor",
        "poverty_rate": "/food-security-nutrition-poverty/poverty-rate",
        # Utility
        "version": "/util/version",
    }

    def __init__(
        self,
        app_identifier: str,
        base_url: str = "https://hapi.humdata.org/api/v2",
        timeout: float = 30.0,
        rate_limit_requests: int = 10,
        rate_limit_period: float = 60.0,
        cache_ttl: int = 86400,
    ):
        """HDX Client başlat.

        Args:
            app_identifier: HDX API uygulama tanımlayıcısı (base64 encoded).
                            Format: base64("app_name:email")
                            Örnek: base64("hdx-mcp-agent:user@example.com")
            base_url: HDX HAPI API base URL.
            timeout: HTTP istek zaman aşımı (saniye).
            rate_limit_requests: Zaman diliminde maksimum istek sayısı.
            rate_limit_period: Rate limit zaman dilimi (saniye).
            cache_ttl: Önbellek TTL süresi (saniye, varsayılan 24 saat).
        """
        self.app_identifier = app_identifier
        self.base_url = base_url
        self.timeout = timeout
        self.rate_limit_requests = rate_limit_requests
        self.rate_limit_period = rate_limit_period
        self.cache = SimpleCache(ttl=cache_ttl)

        self._client: httpx.AsyncClient | None = None
        self._sync_client: httpx.Client | None = None
        self._request_timestamps: list[float] = []
        self._rate_lock = threading.Lock()  # guards _request_timestamps

    @classmethod
    def from_env(cls) -> "HDXClient":
        """Ortam değişkenlerinden client oluştur.

        .env dosyasından veya sistem ortamından okur:
        - HDX_APP_IDENTIFIER (zorunlu)
        - HDX_BASE_URL (isteğe bağlı)
        - HDX_TIMEOUT (isteğe bağlı)

        Returns:
            HDXClient instance.

        Raises:
            ValueError: HDX_APP_IDENTIFIER tanımlı değilse.
        """
        from dotenv import load_dotenv
        load_dotenv()

        app_id = os.getenv("HDX_APP_IDENTIFIER", "")
        if not app_id:
            raise ValueError(
                "HDX_APP_IDENTIFIER zorunlu. "
                "https://hapi.humdata.org/docs#/Generate%20App%20Identifier "
                "adresinden alın."
            )

        return cls(
            app_identifier=app_id,
            base_url=os.getenv("HDX_BASE_URL", cls.BASE_URL),
            timeout=float(os.getenv("HDX_TIMEOUT", "30.0")),
        )

    # =========================================================================
    # HTTP Client Management
    # =========================================================================

    async def _get_async_client(self) -> httpx.AsyncClient:
        """Async HTTP client oluştur veya yeniden kullan."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _get_sync_client(self) -> httpx.Client:
        """Sync HTTP client oluştur veya yeniden kullan."""
        if self._sync_client is None or self._sync_client.is_closed:
            self._sync_client = httpx.Client(timeout=self.timeout)
        return self._sync_client

    async def close(self) -> None:
        """HTTP client'ları kapat."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        if self._sync_client and not self._sync_client.is_closed:
            self._sync_client.close()

    # =========================================================================
    # Rate Limiting
    # =========================================================================

    def _check_rate_limit(self) -> None:
        """Sliding window rate limit kontrolü.

        HDX API'nin rate limit'ini aşmamak için zaman dilimi içindeki
        istek sayısını kontrol eder. Limit aşılırsa bekler.
        """
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
            logger.warning(f"Rate limit reached, waiting {wait_time:.1f}s")
            time.sleep(wait_time)

    # =========================================================================
    # Core API Methods (Internal)
    # =========================================================================

    async def _aget(self, endpoint: str, params: dict[str, Any] = None) -> HDXResult:
        """Async GET isteği — HDX HAPI API'ye.

        Args:
            endpoint: API endpoint yolu (ör: "/metadata/location").
            params: Query parametreleri.

        Returns:
            HDXResult nesnesi (başarılı veya başarısız).
        """
        params = params or {}
        params["app_identifier"] = self.app_identifier
        params = {k: v for k, v in params.items() if v is not None}

        # Metadata sorguları için önbellek kontrolü
        cache_key = f"{endpoint}:{sorted(params.items())}"
        if endpoint.startswith("/metadata/"):
            cached = self.cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Cache hit: {endpoint}")
                return cached

        self._check_rate_limit()

        try:
            client = await self._get_async_client()
            response = await client.get(f"{self.base_url}{endpoint}", params=params)
            response.raise_for_status()
            data = response.json()

            result_data = data.get("data", data) if isinstance(data, dict) else data
            if not isinstance(result_data, list):
                result_data = [result_data] if result_data else []

            result = HDXResult(
                success=True,
                tool=endpoint.strip("/").replace("/", "_"),
                data=result_data,
                count=len(result_data) if isinstance(result_data, list) else 1,
                params={k: v for k, v in params.items() if k != "app_identifier"},
            )

            if endpoint.startswith("/metadata/"):
                self.cache.set(cache_key, result)

            return result

        except httpx.HTTPStatusError as e:
            logger.error(f"HDX API error: {e.response.status_code} - {e.response.text[:200]}")
            return HDXResult(
                success=False,
                tool=endpoint.strip("/").replace("/", "_"),
                error=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
                params={k: v for k, v in params.items() if k != "app_identifier"},
            )
        except Exception as e:
            logger.error(f"HDX request failed: {e}")
            return HDXResult(
                success=False,
                tool=endpoint.strip("/").replace("/", "_"),
                error=str(e),
                params={k: v for k, v in params.items() if k != "app_identifier"},
            )

    def _get(self, endpoint: str, params: dict[str, Any] = None) -> HDXResult:
        """Sync GET isteği — HDX HAPI API'ye (Flask route'ları için).

        Async versiyonun sync karşılığı. Flask route'larında kullanılır.
        """
        params = params or {}
        params["app_identifier"] = self.app_identifier
        params = {k: v for k, v in params.items() if v is not None}

        cache_key = f"{endpoint}:{sorted(params.items())}"
        if endpoint.startswith("/metadata/"):
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        self._check_rate_limit()

        try:
            client = self._get_sync_client()
            response = client.get(f"{self.base_url}{endpoint}", params=params)
            response.raise_for_status()
            data = response.json()

            result_data = data.get("data", data) if isinstance(data, dict) else data
            if not isinstance(result_data, list):
                result_data = [result_data] if result_data else []

            result = HDXResult(
                success=True,
                tool=endpoint.strip("/").replace("/", "_"),
                data=result_data,
                count=len(result_data) if isinstance(result_data, list) else 1,
                params={k: v for k, v in params.items() if k != "app_identifier"},
            )

            if endpoint.startswith("/metadata/"):
                self.cache.set(cache_key, result)

            return result

        except httpx.HTTPStatusError as e:
            return HDXResult(
                success=False,
                tool=endpoint.strip("/").replace("/", "_"),
                error=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
                params={k: v for k, v in params.items() if k != "app_identifier"},
            )
        except Exception as e:
            return HDXResult(
                success=False,
                tool=endpoint.strip("/").replace("/", "_"),
                error=str(e),
                params={k: v for k, v in params.items() if k != "app_identifier"},
            )

    # =========================================================================
    # Metadata & Discovery (12 endpoint)
    # =========================================================================

    async def get_locations(self, limit: int = 100, **kwargs) -> HDXResult:
        """HDX'deki tüm ülke/lokasyonları listele.

        Returns:
            Ülke kodu, isim, HRP durumu, GHO kapsamı bilgisi.
        """
        return await self._aget("/metadata/location", {"limit": limit, **kwargs})

    async def get_admin1(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Ülke için admin1 (il/eyalet) bölgelerini getir.

        Args:
            location_code: ISO 3166-1 alpha-3 ülke kodu (ör: "TUR").
        """
        return await self._aget("/metadata/admin1", {"location_code": location_code, "limit": limit, **kwargs})

    async def get_admin2(self, location_code: str = None, admin1_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Admin2 (ilçe/bölge) bölgelerini getir.

        Args:
            location_code: ISO ülke kodu.
            admin1_code: Admin1 kodu (il/eyalet filtresi).
        """
        return await self._aget("/metadata/admin2", {"location_code": location_code, "admin1_code": admin1_code, "limit": limit, **kwargs})

    async def get_data_availability(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Bir ülke için mevcut veri kategorilerini kontrol et.

        ÖNEMLİ: Veri sorgusu yapmadan önce bu endpoint'i çağırarak
        hedef ülke için veri olup olmadığını doğrula.

        Args:
            location_code: ISO ülke kodu (ör: "TUR", "SYR").
        """
        return await self._aget("/metadata/data-availability", {"location_code": location_code, "limit": limit, **kwargs})

    async def get_organizations(self, limit: int = 100, **kwargs) -> HDXResult:
        """HDX'deki organizasyonları listele."""
        return await self._aget("/metadata/org", {"limit": limit, **kwargs})

    async def get_sectors(self, limit: int = 100, **kwargs) -> HDXResult:
        """İnsani sektörleri listele (sağlık, eğitim, WASH vb.)."""
        return await self._aget("/metadata/sector", {"limit": limit, **kwargs})

    async def get_currencies(self, limit: int = 100, **kwargs) -> HDXResult:
        """Para birimi bilgilerini getir."""
        return await self._aget("/metadata/currency", {"limit": limit, **kwargs})

    async def get_org_types(self, limit: int = 100, **kwargs) -> HDXResult:
        """Organizasyon türlerini getir (UN, NGO, gov vb.)."""
        return await self._aget("/metadata/org-type", {"limit": limit, **kwargs})

    async def get_wfp_commodities(self, limit: int = 100, **kwargs) -> HDXResult:
        """WFP emtia bilgilerini getir."""
        return await self._aget("/metadata/wfp-commodity", {"limit": limit, **kwargs})

    async def get_wfp_markets(self, limit: int = 100, **kwargs) -> HDXResult:
        """WFP pazar bilgilerini getir."""
        return await self._aget("/metadata/wfp-market", {"limit": limit, **kwargs})

    # =========================================================================
    # Affected People (4 endpoint)
    # =========================================================================

    async def get_refugees(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Mülteci ve ilgilinen kişiler verisini getir (UNHCR).

        Args:
            location_code: Sığınma ülkesi ISO kodu.
        """
        return await self._aget("/affected-people/refugees-persons-of-concern", {"location_code": location_code, "limit": limit, **kwargs})

    async def get_humanitarian_needs(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """İnsani ihtiyaç verilerini getir (HRP/PIP).

        Args:
            location_code: ISO ülke kodu.
        """
        return await self._aget("/affected-people/humanitarian-needs", {"location_code": location_code, "limit": limit, **kwargs})

    async def get_idps(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """İçinden göç etmiş kişiler (IDP) verisini getir.

        Args:
            location_code: ISO ülke kodu.
        """
        return await self._aget("/affected-people/idps", {"location_code": location_code, "limit": limit, **kwargs})

    async def get_returnees(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Geri dönen kişiler verisini getir.

        Args:
            location_code: ISO ülke kodu.
        """
        return await self._aget("/affected-people/returnees", {"location_code": location_code, "limit": limit, **kwargs})

    # =========================================================================
    # Demographics & Geography (1 endpoint)
    # =========================================================================

    async def get_population(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Temel nüfus verilerini getir.

        Args:
            location_code: ISO ülke kodu.
        """
        return await self._aget("/geography-infrastructure/baseline-population", {"location_code": location_code, "limit": limit, **kwargs})

    # =========================================================================
    # Climate (1 endpoint)
    # =========================================================================

    async def get_rainfall(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Yağış verilerini getir.

        Args:
            location_code: ISO ülke kodu.
        """
        return await self._aget("/climate/rainfall", {"location_code": location_code, "limit": limit, **kwargs})

    # =========================================================================
    # Coordination & Context (4 endpoint)
    # =========================================================================

    async def get_operational_presence(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Operasyonel varlık verisini getir (hangi org nerede çalışıyor).

        Args:
            location_code: ISO ülke kodu.
        """
        return await self._aget("/coordination-context/operational-presence", {"location_code": location_code, "limit": limit, **kwargs})

    async def get_funding(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Finansman verisini getir (ihtiyaç vs. karşılanan).

        Args:
            location_code: ISO ülke kodu.
        """
        return await self._aget("/coordination-context/funding", {"location_code": location_code, "limit": limit, **kwargs})

    async def get_conflict_events(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Çatışma olayları verisini getir (ACLED).

        Args:
            location_code: ISO ülke kodu.
        """
        return await self._aget("/coordination-context/conflict-events", {"location_code": location_code, "limit": limit, **kwargs})

    async def get_national_risk(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Ulusal risk verisini getir (INFORM Risk Index).

        Args:
            location_code: ISO ülke kodu.
        """
        return await self._aget("/coordination-context/national-risk", {"location_code": location_code, "limit": limit, **kwargs})

    # =========================================================================
    # Food Security & Poverty (3 endpoint)
    # =========================================================================

    async def get_food_security(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Gıda güvenliği verisini getir (IPC sınıflandırması).

        Args:
            location_code: ISO ülke kodu.
        """
        return await self._aget("/food-security-nutrition-poverty/food-security", {"location_code": location_code, "limit": limit, **kwargs})

    async def get_food_prices(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Gıda fiyatları verisini getir (WFP Market Monitor).

        Args:
            location_code: ISO ülke kodu.
        """
        return await self._aget("/food-security-nutrition-poverty/food-prices-market-monitor", {"location_code": location_code, "limit": limit, **kwargs})

    async def get_poverty_rate(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Yoksulluk oranı verisini getir.

        Args:
            location_code: ISO ülke kodu.
        """
        return await self._aget("/food-security-nutrition-poverty/poverty-rate", {"location_code": location_code, "limit": limit, **kwargs})

    # =========================================================================
    # Utility (1 endpoint)
    # =========================================================================

    async def get_api_version(self, **kwargs) -> HDXResult:
        """HDX HAPI API versiyon bilgisini getir."""
        return await self._aget("/util/version", kwargs)

    # =========================================================================
    # High-Level Methods (Sightline SITREP Integration)
    # =========================================================================

    async def get_country_overview(self, location_code: str) -> dict[str, HDXResult]:
        """Bir ülke için kapsamlı insani durum özeti getir.

        Birden fazla veri kategorisini PARALEL olarak çeker.
        SITREP entegrasyonu için tasarlanmıştır.

        Şunları çeker:
        - Veri bulunabilirliği (data availability)
        - Mülteciler (refugees)
        - IDP'ler (internally displaced persons)
        - Finansman (funding)
        - Çatışma olayları (conflict events)
        - Nüfus (population)
        - Gıda güvenliği (food security)
        - Operasyonel varlık (operational presence)
        - Ulusal risk (national risk)

        Args:
            location_code: ISO 3166-1 alpha-3 ülke kodu (ör: "SYR", "TUR", "AFG").

        Returns:
            Kategori adları → HDXResult eşlemesi.
            Örnek: {"refugees": HDXResult(...), "funding": HDXResult(...)}
        """
        import asyncio

        tasks = {
            "availability": self.get_data_availability(location_code=location_code, limit=100),
            "refugees": self.get_refugees(location_code=location_code, limit=10),
            "idps": self.get_idps(location_code=location_code, limit=10),
            "funding": self.get_funding(location_code=location_code, limit=10),
            "conflict": self.get_conflict_events(location_code=location_code, limit=10),
            "population": self.get_population(location_code=location_code, limit=10),
            "food_security": self.get_food_security(location_code=location_code, limit=10),
            "operational_presence": self.get_operational_presence(location_code=location_code, limit=10),
            "national_risk": self.get_national_risk(location_code=location_code, limit=10),
        }

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        output = {}
        for (key, _), result in zip(tasks.items(), results):
            if isinstance(result, Exception):
                output[key] = HDXResult(success=False, tool=key, error=str(result))
            else:
                output[key] = result

        return output

    async def get_sitrep_context(self, location_code: str) -> dict[str, Any]:
        """SITREP-ready context oluştur.

        Bir ülke için kapsamlı insani durum özetini LLM prompt'una
        doğrudan inject edilebilecek formatta döndürür.

        Dönen context şunları içerir:
        - summary: Mülteci sayısı, IDP sayısı, finansman durumu, risk sınıfı
        - data_sources: Hangi veri kategorilerinde veri var
        - Her kategori için to_sitrep_context() çıktısı

        Args:
            location_code: ISO 3166-1 alpha-3 ülke kodu.

        Returns:
            SITREP context sözlüğü.
        """
        overview = await self.get_country_overview(location_code)

        context = {
            "country_code": location_code,
            "data_sources": {},
            "summary": {},
        }

        # Veri bulunabilirliği özeti
        if overview["availability"].success:
            categories = {}
            for item in overview["availability"].data:
                cat = item.get("category", "unknown")
                subcat = item.get("subcategory", "unknown")
                admin_level = item.get("admin_level", "?")
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append({"subcategory": subcat, "admin_level": admin_level})
            context["data_sources"]["availability"] = categories

        # Mülteci özeti
        if overview["refugees"].success and overview["refugees"].data:
            total_refugees = sum(r.get("population", 0) for r in overview["refugees"].data)
            context["summary"]["refugees_total"] = total_refugees
            context["data_sources"]["refugees"] = overview["refugees"].to_sitrep_context()

        # IDP özeti
        if overview["idps"].success and overview["idps"].data:
            total_idps = sum(r.get("population", 0) for r in overview["idps"].data)
            context["summary"]["idps_total"] = total_idps
            context["data_sources"]["idps"] = overview["idps"].to_sitrep_context()

        # Finansman özeti
        if overview["funding"].success and overview["funding"].data:
            total_required = sum(f.get("requirements_usd", 0) or 0 for f in overview["funding"].data)
            total_funded = sum(f.get("funding_usd", 0) or 0 for f in overview["funding"].data)
            context["summary"]["funding_required_usd"] = total_required
            context["summary"]["funding_funded_usd"] = total_funded
            context["data_sources"]["funding"] = overview["funding"].to_sitrep_context()

        # Çatışma özeti
        if overview["conflict"].success:
            context["data_sources"]["conflict"] = overview["conflict"].to_sitrep_context()

        # Ulusal risk özeti
        if overview["national_risk"].success and overview["national_risk"].data:
            risk = overview["national_risk"].data[0]
            context["summary"]["risk_class"] = risk.get("risk_class")
            context["summary"]["global_rank"] = risk.get("global_rank")
            context["summary"]["overall_risk"] = risk.get("overall_risk")
            context["data_sources"]["national_risk"] = overview["national_risk"].to_sitrep_context()

        return context

    # =========================================================================
    # Sync Versions (Flask Route'ları İçin)
    # =========================================================================
    # Flask route'larında async metodlar kullanılamadığı için
    # sync versiyonlar sağlıyoruz. Bu metodlar doğrudan HTTP isteği
    # yapar ve sonucu döner.

    def get_locations_sync(self, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: Tüm ülke/lokasyonları listele."""
        return self._get("/metadata/location", {"limit": limit, **kwargs})

    def get_admin1_sync(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: Admin1 (il/eyalet) bölgelerini getir."""
        return self._get("/metadata/admin1", {"location_code": location_code, "limit": limit, **kwargs})

    def get_admin2_sync(self, location_code: str = None, admin1_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: Admin2 (ilçe/bölge) bölgelerini getir."""
        return self._get("/metadata/admin2", {"location_code": location_code, "admin1_code": admin1_code, "limit": limit, **kwargs})

    def get_data_availability_sync(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: Veri bulunabilirliğini kontrol et."""
        return self._get("/metadata/data-availability", {"location_code": location_code, "limit": limit, **kwargs})

    def get_organizations_sync(self, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: Organizasyonları listele."""
        return self._get("/metadata/org", {"limit": limit, **kwargs})

    def get_sectors_sync(self, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: İnsani sektörleri listele."""
        return self._get("/metadata/sector", {"limit": limit, **kwargs})

    def get_refugees_sync(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: Mülteci verisini getir."""
        return self._get("/affected-people/refugees-persons-of-concern", {"location_code": location_code, "limit": limit, **kwargs})

    def get_humanitarian_needs_sync(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: İnsani ihtiyaç verisini getir."""
        return self._get("/affected-people/humanitarian-needs", {"location_code": location_code, "limit": limit, **kwargs})

    def get_idps_sync(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: IDP verisini getir."""
        return self._get("/affected-people/idps", {"location_code": location_code, "limit": limit, **kwargs})

    def get_returnees_sync(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: Geri dönenler verisini getir."""
        return self._get("/affected-people/returnees", {"location_code": location_code, "limit": limit, **kwargs})

    def get_population_sync(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: Nüfus verisini getir."""
        return self._get("/geography-infrastructure/baseline-population", {"location_code": location_code, "limit": limit, **kwargs})

    def get_rainfall_sync(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: Yağış verisini getir."""
        return self._get("/climate/rainfall", {"location_code": location_code, "limit": limit, **kwargs})

    def get_operational_presence_sync(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: Operasyonel varlık verisini getir."""
        return self._get("/coordination-context/operational-presence", {"location_code": location_code, "limit": limit, **kwargs})

    def get_funding_sync(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: Finansman verisini getir."""
        return self._get("/coordination-context/funding", {"location_code": location_code, "limit": limit, **kwargs})

    def get_conflict_events_sync(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: Çatışma olayları verisini getir."""
        return self._get("/coordination-context/conflict-events", {"location_code": location_code, "limit": limit, **kwargs})

    def get_national_risk_sync(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: Ulusal risk verisini getir."""
        return self._get("/coordination-context/national-risk", {"location_code": location_code, "limit": limit, **kwargs})

    def get_food_security_sync(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: Gıda güvenliği verisini getir."""
        return self._get("/food-security-nutrition-poverty/food-security", {"location_code": location_code, "limit": limit, **kwargs})

    def get_food_prices_sync(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: Gıda fiyatları verisini getir."""
        return self._get("/food-security-nutrition-poverty/food-prices-market-monitor", {"location_code": location_code, "limit": limit, **kwargs})

    def get_poverty_rate_sync(self, location_code: str = None, limit: int = 100, **kwargs) -> HDXResult:
        """Sync: Yoksulluk oranı verisini getir."""
        return self._get("/food-security-nutrition-poverty/poverty-rate", {"location_code": location_code, "limit": limit, **kwargs})

    def get_api_version_sync(self, **kwargs) -> HDXResult:
        """Sync: API versiyon bilgisini getir."""
        return self._get("/util/version", kwargs)

    def get_country_overview_sync(self, location_code: str) -> dict[str, HDXResult]:
        """Sync: Ülke kapsamlı insani durum özeti.

        Flask route'larında kullanılır. Async event loop sorununu
        ThreadPoolExecutor ile çözer.
        """
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self.get_country_overview(location_code))
                    return future.result()
            else:
                return loop.run_until_complete(self.get_country_overview(location_code))
        except RuntimeError:
            return asyncio.run(self.get_country_overview(location_code))

    def get_sitrep_context_sync(self, location_code: str) -> dict[str, Any]:
        """Sync: SITREP-ready context oluştur.

        Flask route'larında kullanılır. get_country_overview_sync()
        ile aynı mekanizmayı kullanır.
        """
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self.get_sitrep_context(location_code))
                    return future.result()
            else:
                return loop.run_until_complete(self.get_sitrep_context(location_code))
        except RuntimeError:
            return asyncio.run(self.get_sitrep_context(location_code))
