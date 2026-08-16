"""
GIEWS Tools — LangChain @tool definitions for Sightline.

FAO GIEWS — gıda fiyatları + mahsul tahmini.

2 tool:
  1. giews_get_food_prices  — Ülke gıda fiyatları (şema doğrulanınca aktif)
  2. giews_get_crop_forecast— Mahsul durumu/tahmini (şema doğrulanınca aktif)

STATUS: GIEWS public REST API şeması doğrulanamadı (SPA tabanlı) — tool'lar
pasif modda kayıtlı, çağrılınca yönlendirme mesajı döner. HDX IPC/prices
mevcut alternatif.
"""

import logging

from langchain.tools import tool

from reliefweb_api.giews_client import get_giews_client
from reliefweb_api.reliefweb_utils import format_error, format_response

logger = logging.getLogger(__name__)


@tool
def giews_get_food_prices(country_code: str, commodity: str = "") -> str:
    """FAO GIEWS'ten ülke gıda fiyatlarını getir.

    Args:
        country_code: ISO3 ülke kodu (orn. 'SDN', 'SOM').
        commodity: emtia adi (orn. 'wheat', 'maize', 'rice'; bos = hepsi).

    Returns:
        Gida fiyatlari ve trend. (Schema dogrulaninca aktif olur; su an
        HDX hdx_get_ipc_phases onerilir.)
    """
    client = get_giews_client()
    if not client:
        return format_error("GIEWSUnavailable", "GIEWS client başlatılmadı")
    res = client.get_food_prices(country=country_code, commodity=commodity)
    if not res.get("ok"):
        return format_error("GIEWSSchemaPending", res.get("error", "GIEWS şeması doğrulanmadı"))
    return format_response(res)


@tool
def giews_get_crop_forecast(country_code: str) -> str:
    """FAO GIEWS'ten ülke mahsul tahminini getir.

    Args:
        country_code: ISO3 ülke kodu (orn. 'SDN', 'SOM').

    Returns:
        Mahsul durumu ve tahmini. (Schema dogrulaninca aktif olur.)
    """
    client = get_giews_client()
    if not client:
        return format_error("GIEWSUnavailable", "GIEWS client başlatılmadı")
    res = client.get_crop_forecast(country=country_code)
    if not res.get("ok"):
        return format_error("GIEWSSchemaPending", res.get("error", "GIEWS şeması doğrulanmadı"))
    return format_response(res)


GIEWS_TOOLS = [giews_get_food_prices, giews_get_crop_forecast]


def init_giews_tools(base_url: str = "", **kwargs) -> bool:
    """server.py'den çağrılır. Keyless — her zaman True (pasif mod)."""
    from reliefweb_api.giews_client import init_giews_client

    return init_giews_client(base_url=base_url, **kwargs)
