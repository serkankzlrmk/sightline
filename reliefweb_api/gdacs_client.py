"""
GDACS (Global Disaster Alert and Coordination System) RSS Client
=================================================================

GDACS, Avrupa Komisyonu JRC tarafindan isletilen ve gercek zamanli
dogal afet uyari sistemidir. Bu istemci, GDACS'in public RSS feed'inden
afet uyarilarini ceker.

  Feed: https://www.gdacs.org/xml/rss.xml  (her ~15 dakikada guncellenir)
  API Key: GEREKMEZ — tamamen ucretsiz ve aciktir
  Format: RSS 2.0 + gdacs:/geo:/georss: namespace'leri

HDXClient ve NewsClient ile ayni pattern'i takip eder:
  - Singleton (from_env ile env'den config)
  - httpx.Client (sync)
  - SimpleCache (TTL-based, thread-safe)
  - Rate limiting (threading.Lock)
  - Graceful error handling (network hatasi -> bos liste)

Entegrasyon:
  1. .env'e (opsiyonel): GDACS_BASE_URL, GDACS_TIMEOUT, GDACS_CACHE_TTL
  2. config.py'de GDACS_* parametreleri tanimli
  3. gdacs_tools.py'da @tool tanimlari var
  4. server.py baslangicta init_gdacs_tools() cagirir
  5. agent/relief_agent.py all_tools'a ekler

Event type kodlari:
  EQ = earthquake, FL = flood, TC = tropical cyclone,
  WF = wildfire, VO = volcano, DR = drought

Alert seviyeleri:
  Green (low), Orange (medium), Red (high)
"""

import os
import time
import logging
import threading
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
import xml.etree.ElementTree as ET

import httpx

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class GDACSResult:
    success: bool
    tool: str = ""
    data: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    count: int = 0
    total_results: int = 0
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "tool": self.tool,
            "data": self.data,
            "error": self.error,
            "count": self.count,
            "total_results": self.total_results,
            "params": self.params,
        }

    def to_sitrep_context(self) -> Dict[str, Any]:
        if not self.success:
            return {"source": "GDACS", "error": self.error, "tool": self.tool}
        return {
            "source": "GDACS",
            "tool": self.tool,
            "total_results": self.total_results,
            "returned_count": self.count,
            "data_preview": self.data[:5] if self.data else [],
        }


# ============================================================================
# Cache (TTL-based, Thread-Safe)
# ============================================================================

class SimpleCache:
    def __init__(self, ttl: int = 900, max_size: int = 200):
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
# Namespaces
# ============================================================================

# GDACS RSS kullanilan namespace'ler. ElementTree find()'lerinde
# "{namespace}tag" formatinda kullanilir.
_NS = {
    "gdacs": "http://www.gdacs.org",
    "geo": "http://www.w3.org/2003/01/geo/wgs84_pos#",
    "georss": "http://www.georss.org/georss",
    "dc": "http://purl.org/dc/elements/1.1/",
}

# Event type kodlari -> insan-okur etiketler
EVENT_TYPES: Dict[str, str] = {
    "EQ": "earthquake",
    "FL": "flood",
    "TC": "tropical cyclone",
    "WF": "wildfire",
    "VO": "volcano",
    "DR": "drought",
}

ALERT_LEVELS = {"Green", "Orange", "Red"}


# ============================================================================
# GDACS Client
# ============================================================================

class GDACSClient:
    DEFAULT_BASE_URL = "https://www.gdacs.org/xml/rss.xml"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        rate_limit_requests: int = 30,
        rate_limit_period: float = 60.0,
        cache_ttl: int = 900,
    ):
        self.base_url = base_url
        self.timeout = timeout
        self.rate_limit_requests = rate_limit_requests
        self.rate_limit_period = rate_limit_period
        self.cache = SimpleCache(ttl=cache_ttl)

        self._sync_client: Optional[httpx.Client] = None
        self._request_timestamps: List[float] = []
        self._rate_lock = threading.Lock()
        # Son basarili fetch'ten elde edilen tum alert'ler (cache'lenmis)
        self._last_alerts: List[Dict[str, Any]] = []
        self._last_fetch_ts: float = 0.0

    @classmethod
    def from_env(cls) -> "GDACSClient":
        from dotenv import load_dotenv
        load_dotenv()

        return cls(
            base_url=os.getenv("GDACS_BASE_URL", cls.DEFAULT_BASE_URL),
            timeout=float(os.getenv("GDACS_TIMEOUT", "30")),
            rate_limit_requests=int(os.getenv("GDACS_RATE_LIMIT_REQUESTS", "30")),
            rate_limit_period=float(os.getenv("GDACS_RATE_LIMIT_PERIOD", "60.0")),
            cache_ttl=int(os.getenv("GDACS_CACHE_TTL", "900")),
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
            logger.warning(f"GDACS rate limit reached, waiting {wait_time:.1f}s")
            time.sleep(wait_time)

    # =========================================================================
    # XML Parsing
    # =========================================================================

    def _parse_rss(self, xml_text: str) -> List[Dict[str, Any]]:
        """GDACS RSS XML'ini parse edip alert dict listesi dondurur.

        Namespace'ler (gdacs:, geo:, georss:) duzgun handle edilir.
        Parse hatasinda bos liste doner (network hatasi gibi graceful).
        """
        if not xml_text:
            return []

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.error(f"GDACS XML parse error: {e}")
            return []

        channel = root.find("channel")
        if channel is None:
            logger.warning("GDACS RSS: no <channel> element found")
            return []

        items = channel.findall("item")
        alerts: List[Dict[str, Any]] = []

        for item in items:
            alert = self._parse_item(item)
            if alert:
                alerts.append(alert)

        return alerts

    def _parse_item(self, item: ET.Element) -> Optional[Dict[str, Any]]:
        """Tek bir <item> elementini parse eder.

        Not: ElementTree namespace-qualified tag formati
        "{uri}localname" seklindedir (kapali parantezden sonra colon YOK).
        Ornegin gdacs:eventtype -> "{http://www.gdacs.org}eventtype".
        """
        def text(tag: str, ns_prefix: str = "") -> str:
            if ns_prefix:
                el = item.find(f"{{{_NS[ns_prefix]}}}{tag}")
            else:
                el = item.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""

        def attr(tag: str, attr_name: str, ns_prefix: str = "") -> str:
            if ns_prefix:
                el = item.find(f"{{{_NS[ns_prefix]}}}{tag}")
            else:
                el = item.find(tag)
            if el is not None:
                return el.get(attr_name, "") or ""
            return ""

        # Geo: hem georss:point hem de geo:Point destekle
        georss_point = text("point", "georss")
        geo_lat = text("lat", "geo")
        geo_long = text("long", "geo")

        lat: Optional[float] = None
        lon: Optional[float] = None
        if georss_point:
            parts = georss_point.split()
            if len(parts) == 2:
                try:
                    lat = float(parts[0])
                    lon = float(parts[1])
                except ValueError:
                    pass
        elif geo_lat and geo_long:
            try:
                lat = float(geo_lat)
                lon = float(geo_long)
            except ValueError:
                pass

        # Severity / population icin value attribute da cek
        severity_value = attr("severity", "value", "gdacs")
        population_value = attr("population", "value", "gdacs")

        alert = {
            "title": text("title"),
            "link": text("link"),
            "description": text("description"),
            "pub_date": text("pubDate"),
            "event_type": text("eventtype", "gdacs"),
            "event_type_label": EVENT_TYPES.get(text("eventtype", "gdacs"), ""),
            "alert_level": text("alertlevel", "gdacs"),
            "alert_score": _to_float(text("alertscore", "gdacs")),
            "event_id": text("eventid", "gdacs"),
            "episode_id": text("episodeid", "gdacs"),
            "iso3": text("iso3", "gdacs"),
            "country": text("country", "gdacs"),
            "latitude": lat,
            "longitude": lon,
            "from_date": text("fromdate", "gdacs"),
            "to_date": text("todate", "gdacs"),
            "population": population_value or text("population", "gdacs"),
            "severity": severity_value or text("severity", "gdacs"),
            "guid": text("guid"),
            "icon": text("icon", "gdacs"),
        }

        # Bos title ise anlamsiz — atlama
        if not alert["title"]:
            return None

        return alert

    # =========================================================================
    # Core Fetch
    # =========================================================================

    def _fetch_alerts(self) -> List[Dict[str, Any]]:
        """GDACS RSS feed'ini cekip parse eder. Cache'ler.

        Network/XML hatasinda bos liste doner ve warning loglar.
        """
        cache_key = "__all_alerts__"
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.debug("GDACS cache hit (all alerts)")
            return cached

        self._check_rate_limit()

        try:
            client = self._get_sync_client()
            response = client.get(self.base_url)
            response.raise_for_status()
            xml_text = response.text

            alerts = self._parse_rss(xml_text)
            if not alerts:
                logger.warning("GDACS: parsed 0 alerts (feed may be empty)")

            self.cache.set(cache_key, alerts)
            self._last_alerts = alerts
            self._last_fetch_ts = time.time()
            return alerts

        except httpx.HTTPStatusError as e:
            logger.error(
                f"GDACS HTTP error: {e.response.status_code} - {e.response.text[:200]}"
            )
            return []
        except httpx.RequestError as e:
            logger.warning(f"GDACS request failed (network): {e}")
            return []
        except Exception as e:
            logger.error(f"GDACS fetch failed: {e}")
            return []

    # =========================================================================
    # Public API
    # =========================================================================

    def get_alerts(
        self,
        event_type: Optional[str] = None,
        alert_level: Optional[str] = None,
        country_iso3: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Filtreli afet uyari listesi dondurur.

        Args:
            event_type: EQ, FL, TC, WF, VO, DR (None/bos = tumu)
            alert_level: Green, Orange, Red (None/bos = tumu)
            country_iso3: ISO3 ulke kodu, ornegin 'TUR', 'JPN' (None/bos = tumu)
            limit: Maksimum kayit sayisi (default 20, max 50)

        Returns:
            Alert dict listesi. Her dict su alanlari icerir:
            title, link, description, pub_date, event_type, event_type_label,
            alert_level, alert_score, event_id, iso3, country, latitude,
            longitude, from_date, to_date, population, severity
        """
        limit = max(1, min(int(limit), 50))
        all_alerts = self._fetch_alerts()

        # Filtreleri normalize et
        et = (event_type or "").upper().strip()
        al = (alert_level or "").capitalize().strip()
        cc = (country_iso3 or "").upper().strip()

        filtered: List[Dict[str, Any]] = []
        for a in all_alerts:
            if et and a.get("event_type", "").upper() != et:
                continue
            if al and a.get("alert_level", "").capitalize() != al:
                continue
            if cc and a.get("iso3", "").upper() != cc:
                continue
            filtered.append(a)
            if len(filtered) >= limit:
                break

        return filtered

    def get_event_detail(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Belirli bir event_id'ye gore detay dondurur.

        GDACS RSS feed'i tum aktif uyarilari icerir, bu yuzden once
        cachelenmis listeden arariz. event_id bulunamazsa None doner.
        """
        if not event_id:
            return None

        eid = str(event_id).strip()
        all_alerts = self._fetch_alerts()

        # Once event_id ile dene
        for a in all_alerts:
            if str(a.get("event_id", "")) == eid:
                return a

        # guid'te event_id bulunabilir (orn. EQ1548381) — prefix'le ara
        for a in all_alerts:
            guid = str(a.get("guid", ""))
            if guid == eid or guid.endswith(eid):
                return a

        return None

    def get_event_detail_by_title(self, title: str) -> Optional[Dict[str, Any]]:
        """Title ile event detayi bulur (kismi eslesme)."""
        if not title:
            return None
        needle = title.lower().strip()
        all_alerts = self._fetch_alerts()

        # Once tam eslesme
        for a in all_alerts:
            if a.get("title", "").lower() == needle:
                return a

        # Sonra kismi eslesme
        for a in all_alerts:
            if needle in a.get("title", "").lower():
                return a

        return None


def _to_float(value: str) -> Optional[float]:
    """String'i float'a cevir, basarisizsa None doner."""
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None