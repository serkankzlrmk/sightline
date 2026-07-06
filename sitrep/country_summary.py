"""
country_summary.py — Per-country intelligence summary generator.

Aggregates all available data for a country into a single JSON card:
- ReliefWeb: report count, date range, top themes, top sources, recent reports
- HDX: refugees, IDPs, funding, conflict events (if available)
- GDACS: active disaster alerts
- World Bank: key economic indicators (if available)
- LLM: 2-3 paragraph narrative summary synthesizing all sources

Generated weekly via cron (scripts/generate_country_summaries.py).
Only regenerates countries with changed report_count (skip unchanged).

Output: output/country_summaries/{Country}.json
"""

import json
import logging
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("country_summary")

# Reuse from weekly_bulletin
from sitrep.weekly_bulletin import COUNTRY_COORDS, _determine_severity
from config import OUTPUT_DIR

COUNTRY_SUMMARY_DIR = OUTPUT_DIR / "country_summaries"
COUNTRY_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

# Countries with < this many reports are skipped
MIN_REPORTS = int(os.getenv("COUNTRY_SUMMARY_MIN_REPORTS", "3"))

# Only fetch HDX for top N countries (by report count) to respect rate limits
HDX_TOP_COUNTRIES = int(os.getenv("COUNTRY_SUMMARY_HDX_TOP", "30"))


def _get_db():
    """Get ChromaAdapter instance for data access."""
    from sitrep.chroma_adapter import ChromaAdapter
    return ChromaAdapter()


def _get_country_coords(country: str) -> Dict:
    """Get coordinates for a country, falling back to geocoding."""
    coords = COUNTRY_COORDS.get(country)
    if coords:
        return coords
    # Try aliases
    aliases = {
        "Syrian Arab Republic": "Syria",
        "Türkiye": "Turkey",
        "oPt": "occupied Palestinian territory",
    }
    alias = aliases.get(country)
    if alias:
        coords = COUNTRY_COORDS.get(alias)
        if coords:
            return coords
    return {"lat": 0, "lng": 0}


def _country_to_iso3(country: str) -> str:
    """Convert country name to ISO3 code for HDX/GDACS."""
    try:
        from reliefweb_api.country_codes import get_iso_code
        iso3 = get_iso_code(country)
        if iso3 and len(iso3) == 3:
            return iso3.upper()
    except Exception:
        pass
    # Manual fallbacks for common humanitarian country names
    manual = {
        "Syrian Arab Republic": "SYR",
        "occupied Palestinian territory": "PSE",
        "oPt": "PSE",
        "Democratic Republic of the Congo": "COD",
        "DR Congo": "COD",
        "Türkiye": "TUR",
        "Turkey": "TUR",
        "Iran": "IRN",
        "Iran (Islamic Republic of)": "IRN",
        "Venezuela": "VEN",
        "Bolivia": "BOL",
        "Tanzania": "TZA",
        "Czechia": "CZE",
        "Republic of Korea": "KOR",
        "Republic of Moldova": "MDA",
        "Russia": "RUS",
        "Russian Federation": "RUS",
    }
    return manual.get(country, "")


def _fetch_hdx_data(country: str, iso3: str) -> Dict:
    """Fetch HDX data for a country (refugees, IDPs, funding, conflict)."""
    if not iso3:
        return {}
    try:
        from sitrep.hdx_enrichment import fetch_hdx_context, format_hdx_for_bulletin
        context = fetch_hdx_context(country)
        if context:
            return format_hdx_for_bulletin(context)
    except Exception as e:
        logger.debug("HDX fetch failed for %s: %s", country, e)
    return {}


def _fetch_gdacs_alerts(iso3: str) -> List[Dict]:
    """Fetch active GDACS alerts for a country."""
    if not iso3:
        return []
    try:
        from reliefweb_api.gdacs_client import GDACSClient
        client = GDACSClient()
        alerts = client.get_alerts(country_iso3=iso3, limit=5)
        return [
            {
                "event_type": a.get("event_type", ""),
                "alert_level": a.get("alert_level", ""),
                "title": a.get("title", ""),
                "severity": a.get("severity", ""),
                "from_date": a.get("from_date", ""),
                "to_date": a.get("to_date", ""),
            }
            for a in alerts
        ]
    except Exception as e:
        logger.debug("GDACS fetch failed for %s: %s", iso3, e)
    return []


def _fetch_worldbank_profile(iso3: str) -> Dict:
    """Fetch World Bank key indicators for a country."""
    if not iso3:
        return {}
    try:
        from reliefweb_api.worldbank_client import WorldBankClient
        client = WorldBankClient()
        profile = client.get_country_profile(iso3)
        # Extract just the most relevant indicators
        relevant = {}
        key_indicators = {
            "NY.GDP.PCAP.CD": "gdp_per_capita",
            "SP.POP.TOTL": "population",
            "SP.DYN.LE00.IN": "life_expectancy",
            "SI.POV.NAHC": "poverty_rate",
            "EG.ELC.ACCS.ZS": "electricity_access",
        }
        for code, label in key_indicators.items():
            if code in profile and profile[code].get("value") is not None:
                relevant[label] = profile[code]
        return relevant
    except Exception as e:
        logger.debug("World Bank fetch failed for %s: %s", iso3, e)
    return {}


def _generate_narrative(country: str, report_count: int, themes: List[str],
                        sources: List[str], hdx_data: Dict, gdacs_alerts: List[Dict],
                        date_range: str) -> Dict:
    """Use LLM to generate a 2-3 paragraph narrative summary for the country."""
    try:
        from sitrep.llm_client import llm_complete
    except ImportError:
        return {"headline": f"{country} humanitarian situation", "narrative": ""}

    # Build context text
    context_parts = [f"Country: {country}"]
    context_parts.append(f"Reports: {report_count} ({date_range})")
    if themes:
        context_parts.append(f"Themes: {', '.join(themes[:6])}")
    if sources:
        context_parts.append(f"Sources: {', '.join(sources[:5])}")
    if hdx_data:
        hdx_text = "; ".join(f"{k.get('label', k)}: {k.get('value', '')}" for k in hdx_data)
        context_parts.append(f"Key figures: {hdx_text}")
    if gdacs_alerts:
        alert_text = "; ".join(f"{a['alert_level']} {a['event_type']}" for a in gdacs_alerts[:3])
        context_parts.append(f"Active alerts: {alert_text}")

    context = "\n".join(context_parts)

    prompt = f"""You are a humanitarian analyst. Write a concise intelligence summary for {country}.

Based on the following data:
{context}

Generate:
1. A headline (max 12 words) summarizing the current humanitarian situation
2. A narrative summary (2-3 paragraphs) synthesizing all available information

Respond with this exact JSON format:
{{"headline": "...", "narrative": "..."}}
"""

    system = "You are a humanitarian analyst writing country intelligence briefings. Respond ONLY with valid JSON."
    result = llm_complete(prompt, system=system, temperature=0.3, max_tokens=500)
    if result:
        try:
            parsed = json.loads(result)
            return parsed
        except json.JSONDecodeError:
            # Try to extract JSON from response
            import re
            match = re.search(r'\{.*\}', result, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
    return {"headline": f"{country} humanitarian situation", "narrative": ""}


def generate_country_summary(country: str, force_hdx: bool = False) -> Optional[Dict]:
    """Generate a full intelligence summary for a single country.

    Args:
        country: Country name (as stored in ReliefWeb/ChromaDB)
        force_hdx: If True, always fetch HDX data (even if not in top countries)

    Returns:
        Summary dict or None if insufficient data.
    """
    db = _get_db()

    # 1. Get report count + date range
    try:
        date_range = db.get_date_range(country)
    except Exception:
        date_range = {"min_date": "", "max_date": "", "count": 0}

    report_count = date_range.get("count", 0)
    if report_count < MIN_REPORTS:
        return None

    # 2. Get chunks for themes, sources, recent reports
    try:
        chunks = db.get_chunks_by_country(country, limit=100)
    except Exception as e:
        logger.warning("Failed to fetch chunks for %s: %s", country, e)
        chunks = []

    # Aggregate themes + sources
    theme_counter = Counter()
    source_counter = Counter()
    recent_reports = []
    seen_titles = set()

    for chunk in chunks:
        # Themes
        raw_themes = chunk.get("themes", "")
        if raw_themes:
            for t in raw_themes.split(","):
                t = t.strip()
                if t:
                    theme_counter[t] += 1
        # Sources
        source = chunk.get("source", "")
        if source:
            source_counter[source] += 1
        # Recent reports (dedup by title)
        title = chunk.get("title", "")
        if title and title not in seen_titles and len(recent_reports) < 10:
            seen_titles.add(title)
            recent_reports.append({
                "title": title,
                "date": chunk.get("date", ""),
                "source": source,
                "url": chunk.get("url", ""),
            })

    top_themes = [t for t, _ in theme_counter.most_common(8)]
    top_sources = [s for s, _ in source_counter.most_common(5)]
    severity = _determine_severity(report_count, top_themes)
    coords = _get_country_coords(country)
    iso3 = _country_to_iso3(country)

    # 3. HDX data (only for top countries or if forced)
    hdx_data = {}
    if force_hdx or report_count >= 10:  # Fetch HDX for countries with 10+ reports
        hdx_data = _fetch_hdx_data(country, iso3)

    # 4. GDACS alerts
    gdacs_alerts = _fetch_gdacs_alerts(iso3)

    # 5. World Bank (quick, cached)
    worldbank = _fetch_worldbank_profile(iso3)

    # 6. LLM narrative
    date_str = f"{date_range.get('min_date', '?')} to {date_range.get('max_date', '?')}"
    narrative = _generate_narrative(
        country, report_count, top_themes, top_sources,
        hdx_data, gdacs_alerts, date_str
    )

    # 7. Check for existing SITREP reports
    sitrep_reports = []
    reports_dir = OUTPUT_DIR / "reports"
    if reports_dir.exists():
        for f in reports_dir.glob("*report.json"):
            if country.lower().replace(" ", "_") in f.name.lower():
                sitrep_reports.append(f.name)

    # 8. Build summary
    summary = {
        "country": country,
        "iso3": iso3,
        "coords": coords,
        "severity": severity,
        "report_count": report_count,
        "date_range": {
            "min_date": date_range.get("min_date", ""),
            "max_date": date_range.get("max_date", ""),
        },
        "headline": narrative.get("headline", ""),
        "narrative": narrative.get("narrative", ""),
        "top_themes": top_themes,
        "top_sources": top_sources,
        "recent_reports": recent_reports[:5],
        "hdx_key_figures": hdx_data,
        "gdacs_alerts": gdacs_alerts,
        "worldbank_indicators": worldbank,
        "sitrep_reports": sitrep_reports,
        "has_sitrep": len(sitrep_reports) > 0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_ts": time.time(),
    }

    # Save to JSON file
    safe_name = country.replace(" ", "_").replace("/", "_").replace("\\", "_")
    output_path = COUNTRY_SUMMARY_DIR / f"{safe_name}.json"
    output_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Country summary saved: %s (%d reports, %s)", country, report_count, severity)

    return summary


def generate_all_country_summaries(max_countries: int = 80) -> Dict:
    """Generate summaries for all countries with sufficient data.

    Only regenerates countries where report_count has changed since last summary.
    Skip countries with no new reports (compare report_count + max_date).

    Args:
        max_countries: Maximum number of countries to process (sorted by report count)

    Returns:
        {"generated": N, "skipped": N, "errors": N, "total": N}
    """
    db = _get_db()

    # Get all countries with chunk counts
    try:
        countries = db.list_countries_with_counts()
    except Exception as e:
        logger.error("Failed to list countries: %s", e)
        return {"generated": 0, "skipped": 0, "errors": 0, "total": 0}

    # Sort by report count (descending), take top N
    countries.sort(key=lambda x: x.get("count", 0), reverse=True)
    countries = [c for c in countries if c.get("count", 0) >= MIN_REPORTS][:max_countries]

    generated = 0
    skipped = 0
    errors = 0

    for entry in countries:
        country = entry["name"]
        count = entry.get("count", 0)

        # Check if we should skip (unchanged since last summary)
        safe_name = country.replace(" ", "_").replace("/", "_").replace("\\", "_")
        existing_path = COUNTRY_SUMMARY_DIR / f"{safe_name}.json"
        if existing_path.exists():
            try:
                existing = json.loads(existing_path.read_text(encoding="utf-8"))
                # Skip if report count unchanged AND generated within 7 days
                if (existing.get("report_count") == count and
                        time.time() - existing.get("generated_ts", 0) < 7 * 86400):
                    skipped += 1
                    continue
            except Exception:
                pass  # Regenerate if file is corrupt

        # Generate summary
        try:
            result = generate_country_summary(country)
            if result:
                generated += 1
            else:
                skipped += 1
        except Exception as e:
            logger.error("Failed to generate summary for %s: %s", country, e)
            errors += 1

    logger.info(
        "Country summaries: %d generated, %d skipped, %d errors, %d total",
        generated, skipped, errors, len(countries)
    )
    return {"generated": generated, "skipped": skipped, "errors": errors, "total": len(countries)}


def list_country_summaries() -> List[Dict]:
    """Return lightweight metadata for all country summaries (for map markers)."""
    results = []
    if not COUNTRY_SUMMARY_DIR.exists():
        return results

    for f in sorted(COUNTRY_SUMMARY_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append({
                "country": data.get("country", ""),
                "iso3": data.get("iso3", ""),
                "coords": data.get("coords", {"lat": 0, "lng": 0}),
                "severity": data.get("severity", "low"),
                "report_count": data.get("report_count", 0),
                "has_sitrep": data.get("has_sitrep", False),
                "headline": data.get("headline", ""),
                "generated_at": data.get("generated_at", ""),
            })
        except Exception:
            continue

    return results


def get_country_summary(country: str) -> Optional[Dict]:
    """Load a country summary from JSON file."""
    safe_name = country.replace(" ", "_").replace("/", "_").replace("\\", "_")
    path = COUNTRY_SUMMARY_DIR / f"{safe_name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("Failed to load country summary %s: %s", country, e)
        return None