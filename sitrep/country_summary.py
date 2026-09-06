"""
country_summary.py — Per-country intelligence summary generator.

Aggregates all available data for a country into a single JSON card:
- ReliefWeb: report count, date range, top themes, top sources, recent reports
- HDX: refugees, IDPs, funding, conflict events (if available, 30-day TTL)
- GDACS: active disaster alerts (refreshed every run)
- World Bank: key economic indicators (if available, 30-day TTL)
- Headline + narrative: deterministic, data-driven templates (NO LLM)

Generated daily via cron (scripts/generate_country_summaries.py).
DB-derived fields are recomputed every run; external APIs (HDX, World Bank)
are only refetched when older than EXTERNAL_DATA_TTL_DAYS (default 30).

Output: output/country_summaries/{Country}.json
"""

import json
import logging
import os
import time
from collections import Counter
from datetime import UTC, datetime

logger = logging.getLogger("country_summary")

# Reuse from shared countries module
from config import OUTPUT_DIR
from sitrep.countries import COUNTRY_COORDS
from sitrep.utils import parse_themes, safe_filename
from sitrep.weekly_bulletin import _determine_severity

COUNTRY_SUMMARY_DIR = OUTPUT_DIR / "country_summaries"
COUNTRY_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

# Countries with < this many reports are skipped
MIN_REPORTS = int(os.getenv("COUNTRY_SUMMARY_MIN_REPORTS", "3"))

# Only fetch HDX for top N countries (by report count) to respect rate limits
HDX_TOP_COUNTRIES = int(os.getenv("COUNTRY_SUMMARY_HDX_TOP", "30"))

# External data (HDX, World Bank) is refetched only when older than this.
# These datasets change slowly (monthly at best) — 30 days is the sweet spot.
EXTERNAL_DATA_TTL_DAYS = int(os.getenv("COUNTRY_SUMMARY_EXTERNAL_TTL_DAYS", "30"))
EXTERNAL_DATA_TTL = EXTERNAL_DATA_TTL_DAYS * 86400
COUNTRY_SUMMARY_SCHEMA_VERSION = 2


def _get_db():
    """Get ChromaAdapter instance for data access."""
    from sitrep.chroma_adapter import ChromaAdapter

    return ChromaAdapter()


def _get_country_coords(country: str) -> dict:
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
    # Use shared countries module fallback
    from sitrep.countries import country_to_iso3

    return country_to_iso3(country)


def _fetch_hdx_data(country: str, iso3: str) -> dict:
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


def _fetch_gdacs_alerts(iso3: str) -> list[dict]:
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


def _fetch_worldbank_profile(iso3: str) -> dict:
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


def _build_data_narrative(
    country: str,
    report_count: int,
    themes: list[str],
    sources: list[dict],
    hdx_data: dict,
    gdacs_alerts: list[dict],
    date_range: str,
) -> dict:
    """Build a compact, deterministic headline + one-line narrative (NO LLM).

    Replaces the old LLM narrative. The card UI renders these as short
    "hap" chips/badges rather than long paragraphs — the headline is a
    one-liner (count + top theme), the narrative a single summary line.
    """
    # --- Headline: compact — count + top theme (country name shown in panel) ---
    theme_hint = ""
    if themes:
        theme_hint = f" · {themes[0]}"
    headline = f"{report_count} reports{theme_hint}"

    # --- Narrative: single data-driven line, no filler ---
    # NOTE: organizations are NOT listed here — the card renders them in the
    # dedicated "Reporting Organizations" section (avoids duplication).
    bits = []
    hdx_figures = (hdx_data or {}).get("key_figures", [])
    if hdx_figures:
        fig_text = "; ".join(f"{f.get('label', '')} {f.get('value', '')}" for f in hdx_figures[:3])
        bits.append(f"HDX: {fig_text}")
    if gdacs_alerts:
        alert_text = "; ".join(f"{a['alert_level']} {a['event_type']}" for a in gdacs_alerts[:2])
        bits.append(f"Alerts: {alert_text}")

    narrative = " · ".join(bits)
    return {"headline": headline, "narrative": narrative}


def _aggregate_report_evidence(rows: list[dict]) -> dict:
    """Aggregate chunk metadata once per report, prioritizing primary-country evidence."""
    reports: dict[object, dict] = {}
    for row in rows:
        report_id = row.get("report_id")
        key = report_id or (
            row.get("url", ""),
            row.get("title", ""),
            row.get("date", ""),
        )
        report = reports.setdefault(
            key,
            {
                "report_id": report_id,
                "title": row.get("title", ""),
                "date": row.get("date", ""),
                "source": row.get("source", ""),
                "url": row.get("url", ""),
                "is_primary_country": bool(row.get("is_primary_country", True)),
                "themes": set(),
            },
        )
        report["themes"].update(parse_themes(row.get("themes", "")))

    ranked = sorted(
        reports.values(),
        key=lambda report: (
            bool(report["is_primary_country"]),
            str(report.get("date") or ""),
            int(report.get("report_id") or 0),
        ),
        reverse=True,
    )
    primary_reports = [report for report in ranked if report["is_primary_country"]]
    evidence_reports = primary_reports or ranked

    theme_counter = Counter()
    source_counter = Counter()
    for report in evidence_reports:
        theme_counter.update(report["themes"])
        source = report.get("source", "")
        if source:
            source_counter[source] += 1

    recent_reports = [
        {
            "title": report.get("title", ""),
            "date": report.get("date", ""),
            "source": report.get("source", ""),
            "url": report.get("url", ""),
            "country_relevance": "primary" if report["is_primary_country"] else "mentioned",
        }
        for report in ranked
        if report.get("title")
    ]
    return {
        "top_themes": [theme for theme, _ in theme_counter.most_common(8)],
        "top_sources": [{"name": source, "count": count} for source, count in source_counter.most_common(5)],
        "recent_reports": recent_reports,
        "evidence_report_count": len(reports),
    }


def _data_freshness(max_date: str | None, now: datetime | None = None) -> dict:
    """Return a stable freshness label for the newest ReliefWeb report date."""
    if not max_date:
        return {"status": "unknown", "age_days": None, "coverage_through": ""}
    try:
        coverage_date = datetime.fromisoformat(str(max_date)[:10]).date()
        current_date = (now or datetime.now(UTC)).date()
        age_days = max(0, (current_date - coverage_date).days)
    except (TypeError, ValueError):
        return {"status": "unknown", "age_days": None, "coverage_through": ""}

    if age_days <= 7:
        status = "active"
    elif age_days <= 30:
        status = "current"
    elif age_days <= 90:
        status = "aging"
    else:
        status = "stale"
    return {
        "status": status,
        "age_days": age_days,
        "coverage_through": coverage_date.isoformat(),
    }


def generate_country_summary(country: str, force_hdx: bool = False) -> dict | None:
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

    # 2. Get report metadata for themes, sources, and recent reports
    try:
        report_rows = db.get_reports_by_country(country, limit=100)
    except Exception as e:
        logger.warning("Failed to fetch report metadata for %s: %s", country, e)
        report_rows = []

    evidence = _aggregate_report_evidence(report_rows)
    top_themes = evidence["top_themes"]
    top_sources = evidence["top_sources"]
    recent_reports = evidence["recent_reports"]
    severity = _determine_severity(report_count, top_themes)
    coords = _get_country_coords(country)
    iso3 = _country_to_iso3(country)

    # --- External data with TTL: reuse cached values when fresh ---
    # Load previous summary if it exists (for TTL reuse of HDX/World Bank)
    existing = {}
    safe_name = safe_filename(country)
    existing_path = COUNTRY_SUMMARY_DIR / f"{safe_name}.json"
    if existing_path.exists():
        try:
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    # 3. HDX data (only for top countries or if forced) — 30-day TTL
    hdx_fetched_at = 0
    hdx_data = {}
    if force_hdx or report_count >= 10:  # Fetch HDX for countries with 10+ reports
        prev_fetched = existing.get("hdx_fetched_at", 0) or 0
        if force_hdx or (time.time() - prev_fetched) > EXTERNAL_DATA_TTL:
            hdx_data = _fetch_hdx_data(country, iso3)
            hdx_fetched_at = time.time()
        else:
            # Reuse cached HDX figures (still fresh)
            hdx_data = existing.get("hdx_data", {})
            hdx_fetched_at = prev_fetched

    # 4. GDACS alerts — always fresh (disaster alerts change daily)
    gdacs_alerts = _fetch_gdacs_alerts(iso3)
    gdacs_fetched_at = time.time()

    # 5. World Bank (quick, cached) — 30-day TTL
    worldbank_fetched_at = 0
    worldbank = {}
    prev_wb_fetched = existing.get("worldbank_fetched_at", 0) or 0
    if force_hdx or (time.time() - prev_wb_fetched) > EXTERNAL_DATA_TTL:
        worldbank = _fetch_worldbank_profile(iso3)
        worldbank_fetched_at = time.time()
    else:
        # Reuse cached World Bank indicators (still fresh)
        worldbank = existing.get("worldbank_indicators", {})
        worldbank_fetched_at = prev_wb_fetched

    # 6. Data-driven narrative (NO LLM — deterministic templates)
    min_date = date_range.get("min_date") or date_range.get("min") or ""
    max_date = date_range.get("max_date") or date_range.get("max") or ""
    date_str = f"{min_date or '?'} to {max_date or '?'}"
    narrative = _build_data_narrative(country, report_count, top_themes, top_sources, hdx_data, gdacs_alerts, date_str)

    # 7. Check for existing SITREP reports
    sitrep_reports = []
    reports_dir = OUTPUT_DIR / "reports"
    if reports_dir.exists():
        for f in reports_dir.glob("*report.json"):
            if country.lower().replace(" ", "_") in f.name.lower():
                sitrep_reports.append(f.name)

    # 8. Build summary
    summary = {
        "schema_version": COUNTRY_SUMMARY_SCHEMA_VERSION,
        "country": country,
        "iso3": iso3,
        "coords": coords,
        "severity": severity,
        "report_count": report_count,
        "primary_report_count": date_range.get("primary_count"),
        "mentioned_report_count": date_range.get("mentioned_count"),
        "evidence_report_count": evidence["evidence_report_count"],
        "date_range": {
            "min_date": min_date,
            "max_date": max_date,
        },
        "data_freshness": _data_freshness(max_date),
        "headline": narrative.get("headline", ""),
        "narrative": narrative.get("narrative", ""),
        "top_themes": top_themes,
        "top_sources": top_sources,
        "recent_reports": recent_reports[:5],
        # hdx_key_figures is a LIST of {label, value, icon} dicts (frontend
        # renders it directly). Raw HDX payload stored separately for TTL reuse.
        "hdx_key_figures": (hdx_data or {}).get("key_figures", []),
        "hdx_context_text": (hdx_data or {}).get("context_text", ""),
        "hdx_data_sources": (hdx_data or {}).get("data_sources", {}),
        "hdx_data": hdx_data,
        "hdx_fetched_at": hdx_fetched_at,
        "gdacs_alerts": gdacs_alerts,
        "gdacs_fetched_at": gdacs_fetched_at,
        "worldbank_indicators": worldbank,
        "worldbank_fetched_at": worldbank_fetched_at,
        "sitrep_reports": sitrep_reports,
        "has_sitrep": len(sitrep_reports) > 0,
        "generated_at": datetime.now(UTC).isoformat(),
        "generated_ts": time.time(),
    }

    # Save to JSON file
    safe_name = safe_filename(country)
    output_path = COUNTRY_SUMMARY_DIR / f"{safe_name}.json"
    output_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Country summary saved: %s (%d reports, %s)", country, report_count, severity)

    return summary


def generate_all_country_summaries(max_countries: int = 80) -> dict:
    """Generate summaries for all countries with sufficient data.

    Runs daily via cron. DB-derived fields (report count, severity, themes,
    sources, recent reports, GDACS alerts) are recomputed every run; HDX and
    World Bank payloads are only refetched when older than EXTERNAL_DATA_TTL
    (see generate_country_summary). Countries are only skipped when they were
    regenerated within the same 12h window with an unchanged report count
    (protects against accidental double-runs of the cron).

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

        # Skip only if regenerated within the last 12h AND report count unchanged
        # (guards against cron double-fires; daily runs still refresh everything)
        safe_name = safe_filename(country)
        existing_path = COUNTRY_SUMMARY_DIR / f"{safe_name}.json"
        if existing_path.exists():
            try:
                existing = json.loads(existing_path.read_text(encoding="utf-8"))
                if (
                    existing.get("schema_version") == COUNTRY_SUMMARY_SCHEMA_VERSION
                    and existing.get("report_count") == count
                    and time.time() - existing.get("generated_ts", 0) < 12 * 3600
                ):
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
        "Country summaries: %d generated, %d skipped, %d errors, %d total", generated, skipped, errors, len(countries)
    )
    return {"generated": generated, "skipped": skipped, "errors": errors, "total": len(countries)}


def list_country_summaries() -> list[dict]:
    """Return lightweight metadata for all country summaries (for map markers)."""
    results = []
    if not COUNTRY_SUMMARY_DIR.exists():
        return results

    for f in sorted(COUNTRY_SUMMARY_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append(
                {
                    "country": data.get("country", ""),
                    "iso3": data.get("iso3", ""),
                    "coords": data.get("coords", {"lat": 0, "lng": 0}),
                    "severity": data.get("severity", "low"),
                    "report_count": data.get("report_count", 0),
                    "has_sitrep": data.get("has_sitrep", False),
                    "headline": data.get("headline", ""),
                    "generated_at": data.get("generated_at", ""),
                }
            )
        except Exception:
            continue

    return results


def get_country_summary(country: str) -> dict | None:
    """Load a country summary from JSON file."""
    safe_name = safe_filename(country)
    path = COUNTRY_SUMMARY_DIR / f"{safe_name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("Failed to load country summary %s: %s", country, e)
        return None
