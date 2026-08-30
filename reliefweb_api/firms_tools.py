"""
FIRMS Tools — LangChain @tool definitions for Sightline.

NASA FIRMS — orman yangını / termal anomali verisi.

1 tool:
  1. firms_get_fires — Koordinat çevresinde aktif yangın sayısı + FRP
     (fire radiative power) + gün dağılımı. Orman yangını senaryoları
     (GDACS ile tamamlayıcı).

Auth: FIRMS_MAP_KEY (NASA Earthdata ücretsiz). Key yoksa init False.
"""

import logging
from collections import Counter

from langchain.tools import tool

from reliefweb_api.firms_client import get_firms_client
from reliefweb_api.reliefweb_utils import format_error, format_response

logger = logging.getLogger(__name__)


@tool
def firms_get_fires(lat: float, lon: float, radius_km: int = 50, days: int = 1) -> str:
    """NASA FIRMS'ten koordinat çevresindeki aktif yangınları getir.

    Args:
        lat: enlem (orn. 38.5).
        lon: boylam (orn. -119.7).
        radius_km: arama yaricapi km (varsayilan 50).
        days: kac gunluk pencere (1-10, varsayilan 1 = bugun).

    Returns:
        Yangin sayisi, FRP (radyasyon gucu), gun bazli dagilim,
        uydu (VIIRS/MODIS).
    """
    client = get_firms_client()
    if not client:
        return format_error("FIRMSUnavailable", "FIRMS client başlatılmadı (FIRMS_MAP_KEY eksik olabilir)")
    res = client.get_fires(lat=lat, lon=lon, radius_km=radius_km, days=days)
    if not res.get("ok"):
        return format_error("FIRMSError", res.get("error", "FIRMS isteği başarısız"))
    fires = res.get("fires", [])
    if not fires:
        return format_response(
            {"success": True, "count": 0, "lat": lat, "lon": lon, "radius_km": radius_km, "fires": []}
        )
    by_date = Counter(f.get("date", "") for f in fires)
    total_frp = sum(float(f.get("frp") or 0) for f in fires)
    return format_response(
        {
            "success": True,
            "count": len(fires),
            "lat": lat,
            "lon": lon,
            "radius_km": radius_km,
            "days": days,
            "total_frp": round(total_frp, 2),
            "by_date": dict(sorted(by_date.items())),
            "fires": fires[:20],
        }
    )


FIRMS_TOOLS = [firms_get_fires]


def init_firms_tools(map_key: str = "", **kwargs) -> bool:
    """server.py'den çağrılır. Key yoksa False (graceful skip)."""
    from reliefweb_api.firms_client import init_firms_client

    return init_firms_client(map_key=map_key, **kwargs)
