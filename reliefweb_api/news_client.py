"""
NewsAPI.org Direct Client — Sightline Entegrasyonu
====================================================

NewsAPI.org REST API'ye dogrudan HTTP istekleri yapar.
MCP server'a ihtiyac duymaz, HDX client ile ayni pattern'i takip eder.

  MCP:  Sightline -> MCP Client -> MCP Server (ayri process) -> News API
  Bizim: Sightline -> news_client.py (bu dosya) -> NewsAPI.org REST API

Tek dosya, tek process, tek deployment.

Entegrasyon:
1. .env'e ekle: NEWS_API_KEY=<api_key>
2. config.py'de NEWS_* parametreleri tanimli
3. news_tools.py'da @tool tanimlari var
4. server.py baslangicta init_news_tools() cagirir
5. agent/relief_agent.py all_tools'a ekler

NewsAPI.org API:
- Everything endpoint: anahtar kelime ile arama (tum kaynaklar)
- Top Headlines endpoint: ulke/kategori bazli son dakika haberleri
- Sources endpoint: haber kaynaklarini listeleme

Ucretsiz plan: 100 istek/gun, 1 ay geriye donuk arama
Business plan: 250K istek/ay, 5 yil geriye donuk arama

API Key: https://newsapi.org/register
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
class NewsResult:
    success: bool
    tool: str = ""
    data: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    count: int = 0
    total_results: int = 0
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "tool": self.tool,
            "data": self.data,
            "error": self.error,
            "count": self.count,
            "total_results": self.total_results,
            "params": self.params,
        }

    def to_sitrep_context(self) -> dict[str, Any]:
        if not self.success:
            return {"source": "NewsAPI", "error": self.error, "tool": self.tool}

        return {
            "source": "NewsAPI",
            "tool": self.tool,
            "total_results": self.total_results,
            "returned_count": self.count,
            "data_preview": self.data[:5] if self.data else [],
        }


# ============================================================================
# Cache (TTL-based, Thread-Safe)
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
# NewsAPI Client
# ============================================================================

class NewsClient:
    DEFAULT_BASE_URL = "https://newsapi.org/v2"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://newsapi.org/v2",
        timeout: float = 15.0,
        rate_limit_requests: int = 80,
        rate_limit_period: float = 86400.0,
        cache_ttl: int = 3600,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.rate_limit_requests = rate_limit_requests
        self.rate_limit_period = rate_limit_period
        self.cache = SimpleCache(ttl=cache_ttl)

        self._sync_client: httpx.Client | None = None
        self._request_timestamps: list[float] = []
        self._rate_lock = threading.Lock()  # guards _request_timestamps

    @classmethod
    def from_env(cls) -> "NewsClient":
        from dotenv import load_dotenv
        load_dotenv()

        api_key = os.getenv("NEWS_API_KEY", "")
        if not api_key:
            raise ValueError(
                "NEWS_API_KEY zorunlu. "
                "https://newsapi.org/register adresinden alin."
            )

        return cls(
            api_key=api_key,
            base_url=os.getenv("NEWS_BASE_URL", cls.DEFAULT_BASE_URL),
            timeout=float(os.getenv("NEWS_TIMEOUT", "15.0")),
            rate_limit_requests=int(os.getenv("NEWS_RATE_LIMIT_REQUESTS", "80")),
            rate_limit_period=float(os.getenv("NEWS_RATE_LIMIT_PERIOD", "86400.0")),
            cache_ttl=int(os.getenv("NEWS_CACHE_TTL", "3600")),
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
            logger.warning(f"News rate limit reached, waiting {wait_time:.1f}s")
            time.sleep(wait_time)

    # =========================================================================
    # Core API Method
    # =========================================================================

    def _get(self, endpoint: str, params: dict[str, Any] = None) -> NewsResult:
        params = params or {}
        params["apiKey"] = self.api_key
        params = {k: v for k, v in params.items() if v is not None}

        cache_key = f"{endpoint}:{sorted(params.items())}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.debug(f"News cache hit: {endpoint}")
            return cached

        self._check_rate_limit()

        try:
            client = self._get_sync_client()
            response = client.get(f"{self.base_url}{endpoint}", params=params)
            data = response.json()

            if response.status_code != 200:
                error_msg = data.get("message", data.get("code", f"HTTP {response.status_code}"))
                logger.error(f"NewsAPI error: {response.status_code} - {error_msg}")
                return NewsResult(
                    success=False,
                    tool=endpoint.strip("/").replace("/", "_"),
                    error=error_msg,
                    params={k: v for k, v in params.items() if k != "apiKey"},
                )

            status = data.get("status", "")
            if status == "error":
                error_msg = data.get("message", "Unknown API error")
                logger.error(f"NewsAPI status error: {error_msg}")
                return NewsResult(
                    success=False,
                    tool=endpoint.strip("/").replace("/", "_"),
                    error=error_msg,
                    params={k: v for k, v in params.items() if k != "apiKey"},
                )

            articles = data.get("articles", [])
            total_results = data.get("totalResults", len(articles))

            result = NewsResult(
                success=True,
                tool=endpoint.strip("/").replace("/", "_"),
                data=articles,
                count=len(articles),
                total_results=total_results,
                params={k: v for k, v in params.items() if k != "apiKey"},
            )

            self.cache.set(cache_key, result)
            return result

        except httpx.HTTPStatusError as e:
            logger.error(f"NewsAPI HTTP error: {e.response.status_code} - {e.response.text[:200]}")
            return NewsResult(
                success=False,
                tool=endpoint.strip("/").replace("/", "_"),
                error=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
                params={k: v for k, v in params.items() if k != "apiKey"},
            )
        except Exception as e:
            logger.error(f"NewsAPI request failed: {e}")
            return NewsResult(
                success=False,
                tool=endpoint.strip("/").replace("/", "_"),
                error=str(e),
                params={k: v for k, v in params.items() if k != "apiKey"},
            )

    def _get_sources(self, endpoint: str, params: dict[str, Any] = None) -> NewsResult:
        params = params or {}
        params["apiKey"] = self.api_key
        params = {k: v for k, v in params.items() if v is not None}

        cache_key = f"{endpoint}:{sorted(params.items())}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.debug(f"News cache hit: {endpoint}")
            return cached

        self._check_rate_limit()

        try:
            client = self._get_sync_client()
            response = client.get(f"{self.base_url}{endpoint}", params=params)
            data = response.json()

            if response.status_code != 200:
                error_msg = data.get("message", data.get("code", f"HTTP {response.status_code}"))
                logger.error(f"NewsAPI error: {response.status_code} - {error_msg}")
                return NewsResult(
                    success=False,
                    tool=endpoint.strip("/").replace("/", "_"),
                    error=error_msg,
                    params={k: v for k, v in params.items() if k != "apiKey"},
                )

            status = data.get("status", "")
            if status == "error":
                error_msg = data.get("message", "Unknown API error")
                logger.error(f"NewsAPI status error: {error_msg}")
                return NewsResult(
                    success=False,
                    tool=endpoint.strip("/").replace("/", "_"),
                    error=error_msg,
                    params={k: v for k, v in params.items() if k != "apiKey"},
                )

            sources = data.get("sources", [])

            result = NewsResult(
                success=True,
                tool=endpoint.strip("/").replace("/", "_"),
                data=sources,
                count=len(sources),
                total_results=len(sources),
                params={k: v for k, v in params.items() if k != "apiKey"},
            )

            self.cache.set(cache_key, result)
            return result

        except httpx.HTTPStatusError as e:
            logger.error(f"NewsAPI HTTP error: {e.response.status_code} - {e.response.text[:200]}")
            return NewsResult(
                success=False,
                tool=endpoint.strip("/").replace("/", "_"),
                error=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
                params={k: v for k, v in params.items() if k != "apiKey"},
            )
        except Exception as e:
            logger.error(f"NewsAPI request failed: {e}")
            return NewsResult(
                success=False,
                tool=endpoint.strip("/").replace("/", "_"),
                error=str(e),
                params={k: v for k, v in params.items() if k != "apiKey"},
            )

    # =========================================================================
    # Public API — Sync Methods (Flask routes & agent tools)
    # =========================================================================

    def search_everything_sync(
        self,
        query: str,
        country: str | None = None,
        language: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        sort_by: str = "relevancy",
        page_size: int = 10,
        page: int = 1,
        sources: str | None = None,
        domains: str | None = None,
    ) -> NewsResult:
        params: dict[str, Any] = {
            "q": query,
            "sortBy": sort_by,
            "pageSize": min(page_size, 50),
            "page": page,
        }
        if language:
            params["language"] = language
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if sources:
            params["sources"] = sources
        if domains:
            params["domains"] = domains

        if country:
            country_sources = self._country_to_sources(country)
            if country_sources and not sources and not domains:
                params["sources"] = country_sources

        return self._get("/everything", params)

    def get_top_headlines_sync(
        self,
        country: str | None = None,
        category: str | None = None,
        language: str | None = None,
        query: str | None = None,
        page_size: int = 10,
        page: int = 1,
    ) -> NewsResult:
        params: dict[str, Any] = {
            "pageSize": min(page_size, 50),
            "page": page,
        }
        if country:
            params["country"] = country
        if category:
            params["category"] = category
        if language and not country:
            params["language"] = language
        if query:
            params["q"] = query

        return self._get("/top-headlines", params)

    def get_sources_sync(
        self,
        category: str | None = None,
        language: str | None = None,
        country: str | None = None,
    ) -> NewsResult:
        params: dict[str, Any] = {}
        if category:
            params["category"] = category
        if language:
            params["language"] = language
        if country:
            params["country"] = country

        return self._get_sources("/top-headlines/sources", params)

    # =========================================================================
    # Country Code Mapping
    # =========================================================================

    COUNTRY_CODE_MAP: dict[str, str] = {
        "af": "afghanistan", "al": "albania", "dz": "algeria", "ad": "andorra",
        "ao": "angola", "ag": "antigua-and-barbuda", "ar": "argentina", "am": "armenia",
        "au": "australia", "at": "austria", "az": "azerbaijan", "bs": "bahamas",
        "bh": "bahrain", "bd": "bangladesh", "bb": "barbados", "by": "belarus",
        "be": "belgium", "bz": "belize", "bj": "benin", "bt": "bhutan",
        "bo": "bolivia", "ba": "bosnia-and-herzegovina", "bw": "botswana", "br": "brazil",
        "bn": "brunei", "bg": "bulgaria", "bf": "burkina-faso", "bi": "burundi",
        "kh": "cambodia", "cm": "cameroon", "ca": "canada", "cv": "cape-verde",
        "cf": "central-african-republic", "td": "chad", "cl": "chile", "cn": "china",
        "co": "colombia", "km": "comoros", "cd": "congo-democratic-republic", "cg": "congo-republic",
        "cr": "costa-rica", "hr": "croatia", "cu": "cuba", "cy": "cyprus",
        "cz": "czech-republic", "dk": "denmark", "dj": "djibouti", "dm": "dominica",
        "do": "dominican-republic", "ec": "ecuador", "eg": "egypt", "sv": "el-salvador",
        "gq": "equatorial-guinea", "er": "eritrea", "ee": "estonia", "sz": "eswatini",
        "et": "ethiopia", "fj": "fiji", "fi": "finland", "fr": "france",
        "ga": "gabon", "gm": "gambia", "ge": "georgia", "de": "germany",
        "gh": "ghana", "gr": "greece", "gd": "grenada", "gt": "guatemala",
        "gn": "guinea", "gw": "guinea-bissau", "gy": "guyana", "ht": "haiti",
        "hn": "honduras", "hu": "hungary", "is": "iceland", "in": "india",
        "id": "indonesia", "ir": "iran", "iq": "iraq", "ie": "ireland",
        "il": "israel", "it": "italy", "jm": "jamaica", "jp": "japan",
        "jo": "jordan", "kz": "kazakhstan", "ke": "kenya", "ki": "kiribati",
        "kp": "korea-north", "kr": "korea-south", "kw": "kuwait", "kg": "kyrgyzstan",
        "la": "laos", "lv": "latvia", "lb": "lebanon", "ls": "lesotho",
        "lr": "liberia", "ly": "libya", "li": "liechtenstein", "lt": "lithuania",
        "lu": "luxembourg", "mg": "madagascar", "mw": "malawi", "my": "myanmar",
        "mv": "maldives", "ml": "mali", "mt": "malta", "mh": "marshall-islands",
        "mr": "mauritania", "mu": "mauritius", "mx": "mexico", "fm": "micronesia",
        "md": "moldova", "mn": "mongolia", "me": "montenegro", "ma": "morocco",
        "mz": "mozambique", "mm": "myanmar", "na": "namibia", "nr": "nauru",
        "np": "nepal", "nl": "netherlands", "nz": "new-zealand", "ni": "nicaragua",
        "ne": "niger", "ng": "nigeria", "mk": "north-macedonia", "no": "norway",
        "om": "oman", "pk": "pakistan", "pw": "palau", "ps": "palestine",
        "pa": "panama", "pg": "papua-new-guinea", "py": "paraguay", "pe": "peru",
        "ph": "philippines", "pl": "poland", "pt": "portugal", "qa": "qatar",
        "ro": "romania", "ru": "russia", "rw": "rwanda", "kn": "saint-kitts-and-nevis",
        "lc": "saint-lucia", "vc": "saint-vincent-and-the-grenadines", "ws": "samoa",
        "sm": "san-marino", "st": "sao-tome-and-principe", "sa": "saudi-arabia",
        "sn": "senegal", "rs": "serbia", "sc": "seychelles", "sl": "sierra-leone",
        "sg": "singapore", "sk": "slovakia", "si": "slovenia", "sb": "solomon-islands",
        "so": "somalia", "za": "south-africa", "ss": "south-sudan", "es": "spain",
        "lk": "sri-lanka", "sd": "sudan", "sr": "suriname", "se": "sweden",
        "ch": "switzerland", "sy": "syria", "tw": "taiwan", "tj": "tajikistan",
        "tz": "tanzania", "th": "thailand", "tl": "timor-leste", "tg": "togo",
        "to": "tonga", "tt": "trinidad-and-tobago", "tn": "tunisia", "tr": "turkey",
        "tm": "turkmenistan", "tv": "tuvalu", "ug": "uganda", "ua": "ukraine",
        "ae": "united-arab-emirates", "gb": "united-kingdom", "us": "united-states",
        "uy": "uruguay", "uz": "uzbekistan", "vu": "vanuatu", "va": "vatican-city",
        "ve": "venezuela", "vn": "vietnam", "ye": "yemen", "zm": "zambia",
        "zw": "zimbabwe",
    }

    HUMANITARIAN_COUNTRY_MAP: dict[str, list[str]] = {
        "SYR": ["syria", "lebanon", "jordan", "turkey", "iraq"],
        "AFG": ["afghanistan", "pakistan", "iran"],
        "SDN": ["sudan", "chad", "ethiopia", "south-sudan", "central-african-republic"],
        "SSD": ["south-sudan", "sudan", "ethiopia", "uganda", "kenya"],
        "UKR": ["ukraine", "poland", "romania", "hungary", "moldova"],
        "ETH": ["ethiopia", "somalia", "kenya", "sudan"],
        "YEM": ["yemen", "saudi-arabia"],
        "SOM": ["somalia", "kenya", "ethiopia", "djibouti"],
        "MLI": ["mali", "burkina-faso", "niger"],
        "NER": ["niger", "mali", "nigeria", "chad"],
        "NGA": ["nigeria", "chad", "cameroon", "niger"],
        "BGD": ["bangladesh", "myanmar"],
        "MMR": ["myanmar", "bangladesh", "thailand"],
        "PSE": ["palestine", "israel", "jordan", "lebanon", "egypt"],
        "LBN": ["lebanon", "syria"],
        "JOR": ["jordan", "syria", "iraq"],
        "TUR": ["turkey", "syria", "iraq"],
        "IRQ": ["iraq", "syria", "turkey"],
        "PAK": ["pakistan", "afghanistan", "iran"],
        "IRN": ["iran", "iraq", "afghanistan", "pakistan"],
        "COL": ["colombia", "venezuela", "ecuador", "peru"],
        "VEN": ["venezuela", "colombia", "brazil", "peru"],
        "DRC": ["congo-democratic-republic", "uganda", "rwanda", "burundi"],
        "HTI": ["haiti", "dominican-republic"],
        "PHL": ["philippines"],
        "IDN": ["indonesia"],
    }

    def _country_to_sources(self, country_code: str) -> str | None:
        alpha3_to_alpha2 = {
            "SYR": "sy", "AFG": "af", "SDN": "sd", "SSD": "ss", "UKR": "ua",
            "ETH": "et", "YEM": "ye", "SOM": "so", "MLI": "ml", "NER": "ne",
            "NGA": "ng", "BGD": "bd", "MMR": "mm", "PSE": "ps", "LBN": "lb",
            "JOR": "jo", "TUR": "tr", "IRQ": "iq", "PAK": "pk", "IRN": "ir",
            "COL": "co", "VEN": "ve", "DRC": "cd", "HTI": "ht", "PHL": "ph",
            "IDN": "id", "RUS": "ru", "USA": "us", "GBR": "gb", "FRA": "fr",
            "DEU": "de", "CHN": "cn", "IND": "in", "BRA": "br", "ZAF": "za",
            "EGY": "eg", "KEN": "ke", "UGA": "ug", "TZA": "tz", "MOZ": "mz",
            "MWI": "mw", "LKA": "lk", "NPL": "np", "GRC": "gr", "ITA": "it",
        }

        code = country_code.upper()
        if len(code) == 3:
            code = alpha3_to_alpha2.get(code, code.lower())
        else:
            code = code.lower()

        return code if len(code) == 2 else None
