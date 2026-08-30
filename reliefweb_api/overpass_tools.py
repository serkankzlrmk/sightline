"""
Overpass Tools — LangChain @tool definitions for Sightline.

OpenStreetMap Overpass API — coğrafi altyapı sorguları (keyless).

1 tool:
  1. osm_query_nearby — Koordinat çevresinde amenity ara (hastane, okul,
     su kaynağı, barınak...). İnsani senaryo: "kampın 5km içinde kaç
     hastane var?", "su kaynakları nerede?"

Overpass politikası gereği User-Agent zorunlu — client içinde ayarlı.
"""

import logging

from langchain.tools import tool

from reliefweb_api.overpass_client import get_overpass_client
from reliefweb_api.reliefweb_utils import format_error, format_response

logger = logging.getLogger(__name__)

_AMENITIES = (
    "hospital, clinic, pharmacy, school, drinking_water, shelter, "
    "place_of_worship, community_centre, toilets, fire_station"
)


@tool
def osm_query_nearby(lat: float, lon: float, radius_m: int = 5000, amenity: str = "hospital", limit: int = 10) -> str:
    """OpenStreetMap'te koordinat çevresinde altyapı (amenity) ara.

    Args:
        lat: enlem (orn. 12.05).
        lon: boylam (orn. 24.88).
        radius_m: arama yaricapi metre (varsayilan 5000 = 5 km).
        amenity: aranan tesis tipi: hospital, clinic, pharmacy, school,
            drinking_water, shelter, place_of_worship, community_centre,
            toilets, fire_station (varsayilan hospital).
        limit: donecek sonuc sayisi (max 25).

    Returns:
        Tesis adlari, koordinatlari ve tipi.
    """
    client = get_overpass_client()
    if not client:
        return format_error("OverpassUnavailable", "Overpass client başlatılmadı")
    res = client.query_nearby(lat=lat, lon=lon, radius_m=radius_m, amenity=amenity, limit=min(limit, 25))
    if not res.get("ok"):
        return format_error("OverpassError", res.get("error", "Overpass isteği başarısız"))
    items = res.get("items", [])
    if not items:
        return format_response({"success": True, "amenity": amenity, "radius_m": radius_m, "count": 0, "items": []})
    return format_response(
        {
            "success": True,
            "amenity": amenity,
            "radius_m": radius_m,
            "center": {"lat": lat, "lon": lon},
            "count": len(items),
            "items": items,
        }
    )


OSM_TOOLS = [osm_query_nearby]


def init_overpass_tools(base_url: str = "", **kwargs) -> bool:
    """server.py'den çağrılır. Keyless — her zaman True."""
    from reliefweb_api.overpass_client import init_overpass_client

    return init_overpass_client(base_url=base_url, **kwargs)
