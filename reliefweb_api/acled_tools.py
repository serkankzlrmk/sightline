"""
ACLED Tools — LangChain @tool definitions for Sightline.

ACLED = Armed Conflict Location & Event Data — çatışma olay verisi.

2 tool:
  1. acled_search_events    — Çatışma olaylarını ara (ülke, tarih, event type, fatalities)
  2. acled_country_summary  — Ülke bazlı çatışma özeti (toplam olay, fatality, top event types)

Auth: ACLED_EMAIL + ACLED_PASSWORD (session login) VEYA ACLED_API_KEY.
İkisi de yoksa init False → tool'lar all_tools'a eklenmez (graceful).

Event types: battles | explosions/remote violence | protests | riots |
strategic developments | violence against civilians
"""

import logging
from collections import Counter
from datetime import date, timedelta

from langchain.tools import tool

from reliefweb_api.acled_client import get_acled_client
from reliefweb_api.reliefweb_utils import format_error, format_response

logger = logging.getLogger(__name__)


@tool
def acled_search_events(
    country: str,
    event_type: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 25,
) -> str:
    """ACLED çatışma olaylarını ara.

    Args:
        country: ISO3 ülke kodu (orn. 'SYR', 'COL', 'SDN').
        event_type: battles, explosions/remote violence, protests, riots,
            strategic developments, violence against civilians (bos = tum tipler).
        date_from: baslangic tarihi YYYY-MM-DD (bos = tum zamanlar).
        date_to: bitis tarihi YYYY-MM-DD (bos = tum zamanlar).
        limit: donecek olay sayisi (max 25).

    Returns:
        Olay listesi: tarih, tip, aktor, fatalities, konum.
    """
    client = get_acled_client()
    if not client:
        return format_error(
            "ACLEDUnavailable",
            "ACLED client başlatılmadı (ACLED_EMAIL/ACLED_API_KEY eksik olabilir)",
        )
    res = client.search_events(
        country=country, event_type=event_type,
        date_from=date_from, date_to=date_to, limit=limit,
    )
    if not res.get("ok"):
        return format_error("ACLEDError", res.get("error", "ACLED isteği başarısız"))
    events = res.get("data", [])
    if not events:
        return format_response(
            {"success": True, "country": country, "count": 0, "events": []}
        )
    rows = []
    for e in events[:limit]:
        rows.append({
            "date": e.get("event_date", ""),
            "type": e.get("event_type", ""),
            "actor": (e.get("actor1") or "")[:60],
            "fatalities": e.get("fatalities", 0),
            "location": (e.get("location") or "")[:60],
        })
    return format_response(
        {
            "success": True,
            "country": country,
            "count": len(rows),
            "events": rows,
        }
    )


@tool
def acled_country_summary(country: str, days: int = 90) -> str:
    """ACLED ülke çatışma özeti.

    Args:
        country: ISO3 ülke kodu (örn. 'SYR', 'COL', 'SDN').
        days: kaç günlük pencere (varsayılan 90).

    Returns:
        Toplam olay sayısı, toplam fatalities, event type dağılımı,
        en aktif aktörler.
    """
    client = get_acled_client()
    if not client:
        return format_error(
            "ACLEDUnavailable",
            "ACLED client başlatılmadı (ACLED_EMAIL/ACLED_API_KEY eksik olabilir)",
        )
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=days)).isoformat()
    res = client.search_events(country=country, date_from=start, date_to=end, limit=1000)
    if not res.get("ok"):
        return format_error("ACLEDError", res.get("error", "ACLED isteği başarısız"))
    events = res.get("data", [])
    if not events:
        return format_response(
            {"success": True, "country": country, "days": days, "count": 0, "total_fatalities": 0}
        )
    types = Counter(e.get("event_type", "unknown") for e in events)
    actors = Counter((e.get("actor1") or "unknown") for e in events)
    total_fatalities = sum(int(e.get("fatalities") or 0) for e in events)
    return format_response(
        {
            "success": True,
            "country": country,
            "days": days,
            "total_events": len(events),
            "total_fatalities": total_fatalities,
            "event_types": dict(types.most_common(5)),
            "top_actors": dict(actors.most_common(3)),
        }
    )


ACLED_TOOLS = [acled_search_events, acled_country_summary]


def init_acled_tools(
    email: str = "",
    password: str = "",
    api_key: str = "",
    **kwargs,
) -> bool:
    """server.py'den çağrılır. Credential yoksa False (graceful skip)."""
    from reliefweb_api.acled_client import init_acled_client

    return init_acled_client(email=email, password=password, api_key=api_key, **kwargs)
