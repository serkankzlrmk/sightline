"""
World Bank API Client — Sightline Entegrasyonu
================================================

World Bank Open Data API'ye dogrudan HTTP istekleri yapar.
Anahtar gerektirmez (keyless), ucretsiz ve acik API.

  MCP:  Sightline -> MCP Client -> MCP Server (ayri process) -> World Bank API
  Bizim: Sightline -> worldbank_client.py (bu dosya) -> api.worldbank.org/v2

Tek dosya, tek process, tek deployment.

Entegrasyon:
1. Anahtar gerekmez — sadece .env'de opsiyonel WORLDBANK_* parametreleri
2. config.py'de WORLDBANK_* parametreleri tanimli (opsiyonel)
3. worldbank_tools.py'da @tool tanimlari var
4. server.py baslangicta init_worldbank_tools() cagirir
5. agent/relief_agent.py all_tools'a ekler

World Bank API:
- Indicator endpoint: ulke+gosterge ile zaman serisi
  {base_url}/country/{country_code}/indicator/{indicator_code}?format=json&per_page={limit}
- Yanit formati: [metadata, data[]] — data[] icindeki kayitlar kullanilir
- Ulke kodu: ISO 3166-1 alpha-2 (e.g., 'SD' for Sudan, 'SY' for Syria)
  Bu modul alpha-3 ('SUD', 'SYR') kodlarini da kabul eder ve donusturur.

API dokumantasyonu: https://datahelpdesk.worldbank.org/knowledgebase/articles/889392
Gosterge arama: https://data.worldbank.org/indicator
"""

import os
import time
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


# ============================================================================
# Country code conversion: ISO3 (alpha-3) -> ISO2 (alpha-2)
# ============================================================================

# World Bank API uses ISO 3166-1 alpha-2 codes.
# We accept alpha-3 codes too and convert them.
_ISO3_TO_ISO2: Dict[str, str] = {
    "AFG": "AF", "ALB": "AL", "DZA": "DZ", "AND": "AD", "AGO": "AO",
    "ARG": "AR", "ARM": "AM", "AUS": "AU", "AUT": "AT", "AZE": "AZ",
    "BGD": "BD", "BLR": "BY", "BEL": "BE", "BEN": "BJ", "BFA": "BF",
    "BGR": "BG", "BHR": "BH", "BIH": "BA", "BLZ": "BZ", "BOL": "BO",
    "BRA": "BR", "BRN": "BN", "BTN": "BT", "BWA": "BW", "BDI": "BI",
    "KHM": "KH", "CMR": "CM", "CAN": "CA", "CAF": "CF", "TCD": "TD",
    "CHL": "CL", "CHN": "CN", "COL": "CO", "COM": "KM", "COD": "CD",
    "COG": "CG", "CRI": "CR", "CIV": "CI", "HRV": "HR", "CUB": "CU",
    "CYP": "CY", "CZE": "CZ", "DNK": "DK", "DJI": "DJ", "DOM": "DO",
    "ECU": "EC", "EGY": "EG", "SLV": "SV", "GNQ": "GQ", "ERI": "ER",
    "EST": "EE", "SWZ": "SZ", "ETH": "ET", "FJI": "FJ", "FIN": "FI",
    "FRA": "FR", "GAB": "GA", "GMB": "GM", "GEO": "GE", "DEU": "DE",
    "GHA": "GH", "GRC": "GR", "GTM": "GT", "GIN": "GN", "GNB": "GW",
    "GUY": "GY", "HTI": "HT", "HND": "HN", "HUN": "HU", "IND": "IN",
    "IDN": "ID", "IRN": "IR", "IRQ": "IQ", "IRL": "IE", "ISR": "IL",
    "ITA": "IT", "JAM": "JM", "JPN": "JP", "JOR": "JO", "KAZ": "KZ",
    "KEN": "KE", "KWT": "KW", "KGZ": "KG", "LAO": "LA", "LVA": "LV",
    "LBN": "LB", "LSO": "LS", "LBR": "LR", "LBY": "LY", "LTU": "LT",
    "LUX": "LU", "MDG": "MG", "MWI": "MW", "MYS": "MY", "MLI": "ML",
    "MRT": "MR", "MUS": "MU", "MEX": "MX", "MDA": "MD", "MNG": "MN",
    "MAR": "MA", "MOZ": "MZ", "MMR": "MM", "NAM": "NA", "NPL": "NP",
    "NLD": "NL", "NIC": "NI", "NER": "NE", "NGA": "NG", "PRK": "KP",
    "NOR": "NO", "OMN": "OM", "PAK": "PK", "PSE": "PS", "PAN": "PA",
    "PNG": "PG", "PRY": "PY", "PER": "PE", "PHL": "PH", "POL": "PL",
    "PRT": "PT", "QAT": "QA", "ROU": "RO", "RUS": "RU", "RWA": "RW",
    "SAU": "SA", "SEN": "SN", "SRB": "RS", "SLE": "SL", "SVK": "SK",
    "SVN": "SI", "SOM": "SO", "ZAF": "ZA", "SSD": "SS", "ESP": "ES",
    "LKA": "LK", "SDN": "SD", "SUR": "SR", "SWE": "SE", "CHE": "CH",
    "SYR": "SY", "TJK": "TJ", "TZA": "TZ", "THA": "TH", "TLS": "TL",
    "TGO": "TG", "TUN": "TN", "TUR": "TR", "TKM": "TM", "UGA": "UG",
    "UKR": "UA", "ARE": "AE", "GBR": "GB", "USA": "US", "URY": "UY",
    "UZB": "UZ", "VEN": "VE", "VNM": "VN", "YEM": "YE", "ZMB": "ZM",
    "ZWE": "ZW",
}


def to_iso2(country_code: str) -> str:
    """Convert an ISO 3166-1 country code to alpha-2.

    Accepts alpha-2 (e.g., 'SD') or alpha-3 (e.g., 'SDN', 'SUD').
    Returns the uppercased alpha-2 code. If the input is alpha-3 and not in
    the lookup table, returns the first two letters uppercased as a fallback.
    """
    if not country_code:
        return ""
    code = country_code.strip().upper()
    if len(code) == 2:
        return code
    if len(code) == 3:
        return _ISO3_TO_ISO2.get(code, code[:2])
    # Unexpected length — try to use as-is or first 2 chars
    return code[:2]


# ============================================================================
# Cache (TTL-based, Thread-Safe)
# ============================================================================

class SimpleCache:
    def __init__(self, ttl: int = 86400, max_size: int = 200):
        self.ttl = ttl
        self.max_size = max_size
        self._cache: Dict[str, tuple] = {}

    def get(self, key: str) -> Optional[Any]:
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

    def stats(self) -> Dict[str, int]:
        return {"size": len(self._cache), "max_size": self.max_size, "ttl": self.ttl}


# ============================================================================
# Key indicators curated for humanitarian context
# ============================================================================

# (indicator_code, human-readable label)
KEY_INDICATORS: List[Tuple[str, str]] = [
    ("NY.GDP.PCAP.CD", "GDP per capita (current US$)"),
    ("SI.POV.NAHC", "Poverty headcount at national poverty lines (% of population)"),
    ("SP.POP.TOTL", "Total population"),
    ("SP.DYN.LE00.IN", "Life expectancy at birth, total (years)"),
    ("SH.DYN.MORT", "Mortality rate, under-5 (per 1,000 live births)"),
    ("SH.STA.WASH.YR.ZS", "People using at least basic drinking water services (% of population)"),
    ("EG.ELC.ACCS.ZS", "Access to electricity (% of population)"),
    ("SH.STA.SMSS.ZS", "People using safely managed sanitation services (% of population)"),
    ("SN.ITK.DEFC.ZS", "Prevalence of undernourishment (% of population)"),
    ("SH.IMM.IDRS", "Immunization, DPT (% of children ages 12-23 months)"),
    ("NY.GNP.MKTP.CD", "GNI, Atlas method (current US$)"),
    ("DT.DOD.DECT.CD", "External debt stocks, total (current US$)"),
    ("SE.ADT.LITR.ZS", "Literacy rate, adult total (% of people ages 15 and above)"),
    ("EN.ATM.CO2E.PC", "CO2 emissions (metric tons per capita)"),
    ("HD.HCI.OVRL", "Human Capital Index (0-1 scale)"),
]


# ============================================================================
# World Bank Client
# ============================================================================

class WorldBankClient:
    """Synchronous World Bank Open Data API client.

    Keyless API. Uses httpx.Client, SimpleCache (24h default), thread-safe
    rate limiting, and singleton pattern via from_env().
    """

    DEFAULT_BASE_URL = "https://api.worldbank.org/v2"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15.0,
        cache_ttl: int = 86400,
        rate_limit_requests: int = 60,
        rate_limit_period: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.rate_limit_requests = rate_limit_requests
        self.rate_limit_period = rate_limit_period
        self.cache = SimpleCache(ttl=cache_ttl)

        self._sync_client: Optional[httpx.Client] = None
        self._request_timestamps: List[float] = []
        self._rate_lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "WorldBankClient":
        from dotenv import load_dotenv
        load_dotenv()

        return cls(
            base_url=os.getenv("WORLDBANK_BASE_URL", cls.DEFAULT_BASE_URL),
            timeout=float(os.getenv("WORLDBANK_TIMEOUT", "15")),
            cache_ttl=int(os.getenv("WORLDBANK_CACHE_TTL", "86400")),
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
            logger.warning(f"World Bank rate limit reached, waiting {wait_time:.1f}s")
            time.sleep(wait_time)

    # =========================================================================
    # Core API Method
    # =========================================================================

    def _fetch(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        cache_key: Optional[str] = None,
    ) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]], Optional[str]]:
        """Low-level GET that returns (data_list, metadata, error_msg)."""
        params = params or {}
        params = {k: v for k, v in params.items() if v is not None}

        ck = cache_key or f"{path}:{sorted(params.items())}"
        cached = self.cache.get(ck)
        if cached is not None:
            logger.debug(f"World Bank cache hit: {path}")
            return cached.get("data"), cached.get("metadata"), None

        self._check_rate_limit()

        try:
            client = self._get_sync_client()
            response = client.get(f"{self.base_url}{path}", params=params)
            data = response.json()

            if response.status_code != 200:
                msg = (
                    data.get("message", [{}])[0].get("value", f"HTTP {response.status_code}")
                    if isinstance(data, dict) and data.get("message")
                    else f"HTTP {response.status_code}"
                )
                logger.error(f"World Bank error: {response.status_code} - {msg}")
                return None, None, str(msg)

            # World Bank returns [metadata, data[]]
            if isinstance(data, list) and len(data) >= 2:
                metadata = data[0] if isinstance(data[0], dict) else {}
                records = data[1] if isinstance(data[1], list) else []
                self.cache.set(ck, {"data": records, "metadata": metadata})
                return records, metadata, None

            # Some endpoints return a dict with an error
            if isinstance(data, dict):
                msg_list = data.get("message", [])
                msg = msg_list[0].get("value", "Unknown API error") if msg_list else "Unknown API error"
                return None, None, str(msg)

            return None, None, "Unexpected response shape"

        except httpx.HTTPStatusError as e:
            logger.error(f"World Bank HTTP error: {e.response.status_code} - {e.response.text[:200]}")
            return None, None, f"HTTP {e.response.status_code}: {e.response.text[:200]}"
        except Exception as e:
            logger.error(f"World Bank request failed: {e}")
            return None, None, str(e)

    # =========================================================================
    # Public API — Sync Methods
    # =========================================================================

    def get_indicator(
        self,
        country_code: str,
        indicator_code: str,
        date_range: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Fetch a single indicator time series for a country.

        Args:
            country_code: ISO2 ('SD') or ISO3 ('SDN') country code.
            indicator_code: World Bank indicator code (e.g., 'NY.GDP.PCAP.CD').
            date_range: Optional 'YYYY:YYYY' range (e.g., '2010:2024').
                        If omitted, returns most recent data points.
            limit: Max number of data points (per_page).

        Returns:
            List of data records (newest first), each with keys like
            'value', 'date' (year), 'indicator' {'id','value'}, 'country'.
            Empty list on error.
        """
        cc = to_iso2(country_code)
        if not cc or not indicator_code:
            return []

        params: Dict[str, Any] = {
            "format": "json",
            "per_page": max(1, min(int(limit), 1000)),
        }
        if date_range:
            params["date"] = date_range

        path = f"/country/{cc}/indicator/{indicator_code}"
        records, _, err = self._fetch(path, params)
        if err:
            logger.warning(f"get_indicator failed for {cc}/{indicator_code}: {err}")
            return []
        return records or []

    def get_country_profile(self, country_code: str) -> Dict[str, Dict[str, Any]]:
        """Fetch a curated bundle of ~15 key indicators for a country.

        Fetches each indicator (most recent value) and returns a dict:
            {indicator_code: {"value": ..., "year": ..., "label": ...}}

        Missing/failed indicators are omitted from the result.
        """
        cc = to_iso2(country_code)
        if not cc:
            return {}

        profile: Dict[str, Dict[str, Any]] = {}
        for code, label in KEY_INDICATORS:
            records = self.get_indicator(cc, code, limit=5)
            if not records:
                continue
            # Find the most recent non-null value
            latest = None
            for rec in records:
                val = rec.get("value")
                if val is not None:
                    latest = rec
                    break
            if latest is None:
                # No non-null value in the returned window — skip this indicator
                continue
            profile[code] = {
                "value": latest.get("value"),
                "year": latest.get("date"),
                "label": label,
            }
        return profile