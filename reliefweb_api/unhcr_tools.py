"""
UNHCR Tools — LangChain @tool definitions for Sightline.

UNHCR Refugee Data Finder — mülteci verisi.

3 tool:
  1. unhcr_get_population   — Mülteci/iltica nüfusu (yıllık)
  2. unhcr_get_demographics — Cinsiyet/yaş grubu kırılımı
  3. unhcr_get_nowcast      — Güncel tahmini mülteci sayısı

Auth: UNHCR_API_KEY (Bearer). Key yoksa init False → tool'lar eklenmez.
STATUS: endpoint şemaları canlı testte doğrulanacak (key gelince).
"""

import logging

from langchain.tools import tool

from reliefweb_api.reliefweb_utils import format_error, format_response
from reliefweb_api.unhcr_client import get_unhcr_client

logger = logging.getLogger(__name__)


@tool
def unhcr_get_population(country_code: str, year: int = 0) -> str:
    """UNHCR'den ülkedeki mülteci/iltica nüfusunu getir.

    Args:
        country_code: ISO3 ulke kodu (orn. 'TUR', 'SDN', 'COL').
        year: yil (0 = en guncel).

    Returns:
        Multeci sayisi, ulke ve yil. (Key ve canli dogrulama sonrasi aktif.)
    """
    client = get_unhcr_client()
    if not client:
        return format_error("UNHCRUnavailable", "UNHCR client başlatılmadı (UNHCR_API_KEY eksik olabilir)")
    res = client.get_population(country_code=country_code, year=year)
    if not res.get("ok"):
        return format_error("UNHCRError", res.get("error", "UNHCR isteği başarısız"))
    return format_response(res.get("data"))


@tool
def unhcr_get_demographics(country_code: str, year: int = 0) -> str:
    """UNHCR'den mülteci demografik kırılımını getir.

    Args:
        country_code: ISO3 ulke kodu.
        year: yil (0 = en guncel).

    Returns:
        Cinsiyet ve yas grubu dagilimi.
    """
    client = get_unhcr_client()
    if not client:
        return format_error("UNHCRUnavailable", "UNHCR client başlatılmadı (UNHCR_API_KEY eksik olabilir)")
    res = client.get_demographics(country_code=country_code, year=year)
    if not res.get("ok"):
        return format_error("UNHCRError", res.get("error", "UNHCR isteği başarısız"))
    return format_response(res.get("data"))


@tool
def unhcr_get_nowcast(country_code: str) -> str:
    """UNHCR nowcast — ülkenin güncel tahmini mülteci sayısı.

    Args:
        country_code: ISO3 ulke kodu.

    Returns:
        Tahmini guncel multeci sayisi.
    """
    client = get_unhcr_client()
    if not client:
        return format_error("UNHCRUnavailable", "UNHCR client başlatılmadı (UNHCR_API_KEY eksik olabilir)")
    res = client.get_nowcast(country_code=country_code)
    if not res.get("ok"):
        return format_error("UNHCRError", res.get("error", "UNHCR isteği başarısız"))
    return format_response(res.get("data"))


UNHCR_TOOLS = [unhcr_get_population, unhcr_get_demographics, unhcr_get_nowcast]


def init_unhcr_tools(api_key: str = "", **kwargs) -> bool:
    """server.py'den çağrılır. Key yoksa False (graceful skip)."""
    from reliefweb_api.unhcr_client import init_unhcr_client

    return init_unhcr_client(api_key=api_key, **kwargs)
