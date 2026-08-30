"""
FTS Tools — LangChain @tool definitions for Sightline.

OCHA FTS (Financial Tracking Service) — insani fonlama planları.

2 tool:
  1. fts_get_funding_plan     — Ülke insani planı: requirement, kategori, acil durumlar
  2. fts_get_funding_gap      — Ülke toplam fonlama ihtiyacı (tüm planların requirement toplamı)

NOT: FTS v2 public'te gerçekleşen fon (flow) endpoint'i yok — bu tool'lar
REQUIREMENT (ihtiyaç) verisi sunar. Gerçekleşen fon için HDX hdx_get_funding
tool'u kullanılabilir (karşılaştırmayı agent yapar).
"""

import logging

from langchain.tools import tool

from reliefweb_api.fts_client import get_fts_client
from reliefweb_api.reliefweb_utils import format_error, format_response

logger = logging.getLogger(__name__)


@tool
def fts_get_funding_plan(country_code: str, year: int = 2025) -> str:
    """OCHA FTS'ten ülkenin insani fonlama planını getir.

    Args:
        country_code: ISO3 ülke kodu (örn. 'SDN', 'COL', 'UKR').
        year: plan yılı (varsayılan 2025).

    Returns:
        Plan adı, kategori (HRP/Flash Appeal), fonlama ihtiyacı (USD),
        ilgili acil durumlar.
    """
    client = get_fts_client()
    if not client:
        return format_error("FTSUnavailable", "FTS client başlatılmadı")
    res = client.get_country_plans(iso3=country_code, year=year)
    if not res.get("ok"):
        return format_error("FTSError", res.get("error", "FTS isteği başarısız"))
    plans = res.get("data", [])
    if not plans:
        return format_response({"success": True, "country": country_code, "year": year, "count": 0, "plans": []})
    return format_response(
        {
            "success": True,
            "country": country_code,
            "year": year,
            "count": len(plans),
            "plans": plans,
        }
    )


@tool
def fts_get_funding_gap(country_code: str, year: int = 2025) -> str:
    """OCHA FTS'ten ülkenin toplam insani fonlama ihtiyacını getir.

    Args:
        country_code: ISO3 ülke kodu (örn. 'SDN', 'COL', 'UKR').
        year: plan yılı (varsayılan 2025).

    Returns:
        Tüm planların toplam orijinal/revize requirement'ı (USD).
        Gerçekleşen fonla karşılaştırmak için hdx_get_funding kullanın.
    """
    client = get_fts_client()
    if not client:
        return format_error("FTSUnavailable", "FTS client başlatılmadı")
    res = client.get_country_plans(iso3=country_code, year=year)
    if not res.get("ok"):
        return format_error("FTSError", res.get("error", "FTS isteği başarısız"))
    plans = res.get("data", [])
    if not plans:
        return format_response(
            {"success": True, "country": country_code, "year": year, "total_requirements": 0, "plan_count": 0}
        )
    total_orig = sum(int(p.get("orig_requirements") or 0) for p in plans)
    total_rev = sum(int(p.get("revised_requirements") or 0) for p in plans)
    return format_response(
        {
            "success": True,
            "country": country_code,
            "year": year,
            "plan_count": len(plans),
            "total_requirements": total_orig,
            "total_revised_requirements": total_rev,
            "plans": [{"name": p["name"][:60], "requirements": p.get("orig_requirements")} for p in plans],
        }
    )


FTS_TOOLS = [fts_get_funding_plan, fts_get_funding_gap]


def init_fts_tools(base_url: str = "", **kwargs) -> bool:
    """server.py'den çağrılır. Keyless — her zaman True."""
    from reliefweb_api.fts_client import init_fts_client

    return init_fts_client(base_url=base_url, **kwargs)
