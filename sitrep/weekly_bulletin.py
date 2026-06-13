"""
sitrep_pipeline/weekly_bulletin.py
Weekly humanitarian bulletin generator.

Queries the vector store for reports in a given date range,
groups them by country, and uses LLM to generate crisis summaries.
Produces a JSON bulletin saved to output/bulletins/.

Usage:
    python -m sitrep.weekly_bulletin --date-from 2026-06-01 --date-to 2026-06-07

    or from Python:
        from sitrep.weekly_bulletin import generate_weekly_bulletin
        path = generate_weekly_bulletin("2026-06-01", "2026-06-07")
"""

import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from collections import Counter

# Ensure sitrep/ and project root are on sys.path
_SITREP_DIR = str(Path(__file__).parent.resolve())
_ROOT_DIR = str(Path(__file__).parent.parent.resolve())
for _p in (_SITREP_DIR, _ROOT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from config import (
    OUTPUT_DIR,
    OUTPUT_BULLETINS_DIR,
    LLM_MODEL,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("weekly_bulletin")

# ---------------------------------------------------------------------------
# Output directory (from config)
# ---------------------------------------------------------------------------
BULLETINS_DIR = OUTPUT_BULLETINS_DIR

# ---------------------------------------------------------------------------
# Country coordinates (approximate center lat/lng for map dots)
# ---------------------------------------------------------------------------
COUNTRY_COORDS: Dict[str, Dict] = {
    "Sudan": {"lat": 15.5, "lng": 32.5},
    "South Sudan": {"lat": 7.0, "lng": 30.0},
    "Ukraine": {"lat": 48.5, "lng": 31.2},
    "Syria": {"lat": 35.0, "lng": 38.0},
    "Afghanistan": {"lat": 33.9, "lng": 67.7},
    "Yemen": {"lat": 15.5, "lng": 48.5},
    "Myanmar": {"lat": 19.7, "lng": 96.2},
    "Ethiopia": {"lat": 9.1, "lng": 40.5},
    "Somalia": {"lat": 5.1, "lng": 46.2},
    "Nigeria": {"lat": 9.1, "lng": 8.7},
    "Democratic Republic of the Congo": {"lat": -4.0, "lng": 21.8},
    "Haiti": {"lat": 18.9, "lng": -72.3},
    "occupied Palestinian territory": {"lat": 31.9, "lng": 35.0},
    "Iraq": {"lat": 33.2, "lng": 43.7},
    "Libya": {"lat": 26.3, "lng": 17.2},
    "Mali": {"lat": 17.6, "lng": -4.0},
    "Niger": {"lat": 17.6, "lng": 8.1},
    "Cameroon": {"lat": 7.4, "lng": 12.3},
    "Burkina Faso": {"lat": 12.2, "lng": -1.6},
    "Central African Republic": {"lat": 6.6, "lng": 20.9},
    "Chad": {"lat": 15.4, "lng": 18.7},
    "Mozambique": {"lat": -18.7, "lng": 35.5},
    "Bangladesh": {"lat": 23.7, "lng": 90.4},
    "Philippines": {"lat": 12.9, "lng": 121.8},
    "Pakistan": {"lat": 30.4, "lng": 69.3},
    "India": {"lat": 20.6, "lng": 79.0},
    "Kenya": {"lat": -0.02, "lng": 37.9},
    "Tanzania": {"lat": -6.4, "lng": 34.9},
    "Uganda": {"lat": 1.4, "lng": 32.3},
    "Zimbabwe": {"lat": -19.0, "lng": 29.2},
    "Venezuela": {"lat": 6.4, "lng": -66.6},
    "Colombia": {"lat": 4.6, "lng": -74.3},
    "Ecuador": {"lat": -1.8, "lng": -78.2},
    "Peru": {"lat": -12.0, "lng": -77.0},
    "Brazil": {"lat": -14.2, "lng": -51.9},
    "Türkiye": {"lat": 39.0, "lng": 35.2},
    "Turkey": {"lat": 39.0, "lng": 35.2},
    "Lebanon": {"lat": 33.9, "lng": 35.5},
    "Israel": {"lat": 31.0, "lng": 34.8},
}

# ---------------------------------------------------------------------------
# Severity thresholds
# ---------------------------------------------------------------------------
SEVERITY_HIGH_THRESHOLD = 10   # ≥10 reports = high
SEVERITY_MEDIUM_THRESHOLD = 5  # 5-9 reports = medium
# <5 reports = low

# ---------------------------------------------------------------------------
# LLM Prompts
# ---------------------------------------------------------------------------
_CRISIS_SUMMARY_SYSTEM = (
    "You are a humanitarian analyst writing concise crisis briefings. "
    "Respond ONLY with valid JSON. Do not include any text outside the JSON object."
)

_CRISIS_SUMMARY_USER = """\
Analyze the following humanitarian reports from {country} during the period {date_from} to {date_to}.
Generate a crisis briefing with:
1. A headline (max 12 words) summarizing the main humanitarian concern
2. A summary (2-3 sentences) describing the situation
3. Severity assessment: "high" (active conflict/mass displacement), "medium" (deteriorating situation), or "low" (monitoring required)

Reports ({count} total):
{report_list}
{hdx_data}
Respond with this exact JSON format:
{{"headline": "...", "summary": "...", "severity": "high|medium|low"}}
"""

_GLOBAL_OVERVIEW_SYSTEM = (
    "You are a humanitarian analyst writing a weekly global overview. "
    "Write 2-3 paragraphs summarizing the key humanitarian developments. "
    "Be factual, cite specific countries, and maintain a professional tone."
)

_GLOBAL_OVERVIEW_USER = """\
Write a 2-3 paragraph global humanitarian overview for the week of {date_from} to {date_to}.
Base your overview on the following crisis summaries:

{crisis_summaries}

Total reports this week: {total_reports}
Countries affected: {countries_count}
"""

# ---------------------------------------------------------------------------
# Data retrieval
# ---------------------------------------------------------------------------

def _get_db():
    """Get a ChromaAdapter instance."""
    from chroma_adapter import ChromaAdapter
    return ChromaAdapter()


def _get_available_date_range(db) -> Optional[Dict]:
    """
    Query the vector store for the actual date range of available data.
    Returns {'date_from': 'YYYY-MM-DD', 'date_to': 'YYYY-MM-DD'} or None.
    """
    try:
        # Get a sample of chunks to determine date range
        # Use a large country to get a representative sample
        countries = db.list_countries_with_counts()
        if not countries:
            return None

        # Check the top 5 countries for date range
        all_dates = []
        for entry in countries[:5]:
            chunks = db.get_chunks_by_country(entry["name"], limit=200)
            for c in chunks:
                d = c.get("date", "")[:10]
                if d and len(d) == 10:
                    all_dates.append(d)

        if not all_dates:
            return None

        return {"date_from": min(all_dates), "date_to": max(all_dates)}
    except Exception as exc:
        logger.warning("Failed to determine available date range: %s", exc)
        return None


def fetch_reports_by_date_range(
    date_from: str,
    date_to: str,
) -> Dict[str, Any]:
    """
    Fetch reports from the vector store for a date range,
    grouped by primary_country.

    If no data is found for the requested date range, falls back to
    the actual date range available in the database.

    Returns:
        {
            "grouped": {country: [chunk_dict, ...], ...},
            "actual_date_from": str,  # actual date range used (may differ from requested)
            "actual_date_to": str,
            "date_fallback": bool,    # True if fallback was used
        }
    """
    db = _get_db()
    # Get all countries with data
    countries_with_counts = db.list_countries_with_counts()

    grouped: Dict[str, List[Dict]] = {}
    used_fallback = False
    actual_from = date_from
    actual_to = date_to

    for entry in countries_with_counts:
        country = entry["name"]
        count = entry.get("count", 0)
        if count < 3:
            continue  # Skip countries with very few chunks

        # Fetch chunks for this country in the date range
        try:
            chunks = db.get_chunks_by_country_and_themes(
                country,
                themes=None,
                date_from=date_from,
                date_to=date_to,
                limit=500,
            )
        except Exception as exc:
            logger.warning("Failed to fetch chunks for %s: %s", country, exc)
            continue

        if not chunks:
            continue

        # Deduplicate by title (keep unique reports)
        seen_titles = set()
        unique_reports = []
        for c in chunks:
            title = c.get("title", "")
            if title and title not in seen_titles:
                seen_titles.add(title)
                unique_reports.append(c)

        if len(unique_reports) >= 3:
            grouped[country] = unique_reports

    # If no data found for the requested date range, fall back to available range
    if not grouped:
        available = _get_available_date_range(db)
        if available:
            logger.info(
                "No data found for %s to %s. Falling back to available range: %s to %s",
                date_from, date_to, available["date_from"], available["date_to"],
            )
            actual_from = available["date_from"]
            actual_to = available["date_to"]
            used_fallback = True

            for entry in countries_with_counts:
                country = entry["name"]
                count = entry.get("count", 0)
                if count < 3:
                    continue

                try:
                    chunks = db.get_chunks_by_country_and_themes(
                        country,
                        themes=None,
                        date_from=actual_from,
                        date_to=actual_to,
                        limit=500,
                    )
                except Exception as exc:
                    logger.warning("Failed to fetch chunks for %s: %s", country, exc)
                    continue

                if not chunks:
                    continue

                seen_titles = set()
                unique_reports = []
                for c in chunks:
                    title = c.get("title", "")
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        unique_reports.append(c)

                if len(unique_reports) >= 3:
                    grouped[country] = unique_reports

    logger.info("Fetched reports for %d countries in date range %s to %s",
                len(grouped), actual_from, actual_to)
    return {
        "grouped": grouped,
        "actual_date_from": actual_from,
        "actual_date_to": actual_to,
        "date_fallback": used_fallback,
    }


def _determine_severity(report_count: int, themes: List[str]) -> str:
    """Determine crisis severity based on report count and themes."""
    conflict_themes = {"Conflict", "Protection", "Displacement"}
    if report_count >= SEVERITY_HIGH_THRESHOLD:
        return "high"
    if report_count >= SEVERITY_MEDIUM_THRESHOLD:
        return "medium"
    # Check for conflict-related themes even with fewer reports
    if conflict_themes.intersection(set(themes)):
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# LLM-based generation
# ---------------------------------------------------------------------------

def generate_crisis_summary(
    country: str,
    reports: List[Dict],
    date_from: str,
    date_to: str,
    hdx_context_text: str = "",
) -> Optional[Dict]:
    """Generate a crisis summary for a single country using LLM."""
    from llm_client import chat_simple

    # Build report list for prompt (titles + dates + themes)
    report_lines = []
    for r in reports[:20]:  # Limit to 20 reports for prompt
        title = r.get("title", "Untitled")
        date = r.get("date", "")[:10]
        themes = r.get("themes", "")
        source = r.get("source", "")
        line = f"- [{date}] {title}"
        if themes:
            line += f" ({themes})"
        if source:
            line += f" — {source}"
        report_lines.append(line)

    report_list = "\n".join(report_lines)

    # Build HDX context section if available
    hdx_section = ""
    if hdx_context_text:
        hdx_section = f"\n\n**Quantitative Humanitarian Data (HDX):**\n{hdx_context_text}\n"

    prompt = _CRISIS_SUMMARY_USER.format(
        country=country,
        date_from=date_from,
        date_to=date_to,
        count=len(reports),
        report_list=report_list,
        hdx_data=hdx_section,
    )

    try:
        response = chat_simple(
            user_prompt=prompt,
            system_prompt=_CRISIS_SUMMARY_SYSTEM,
            max_tokens=300,
            temperature=0.3,
        )
        # Parse JSON response
        response = response.strip()
        if response.startswith("```json"):
            response = response[7:]
        if response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()

        result = json.loads(response)
        return {
            "headline": result.get("headline", f"{country} humanitarian situation"),
            "summary": result.get("summary", ""),
            "severity": result.get("severity", "low"),
        }
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("Failed to generate crisis summary for %s: %s", country, exc)
        return None


def generate_global_overview(
    crises: List[Dict],
    date_from: str,
    date_to: str,
    total_reports: int,
) -> str:
    """Generate a global overview paragraph using LLM."""
    from llm_client import chat_simple

    crisis_summaries = "\n\n".join(
        f"**{c['country']}** ({c['severity']}): {c['headline']}. {c['summary']}"
        for c in crises
    )

    prompt = _GLOBAL_OVERVIEW_USER.format(
        date_from=date_from,
        date_to=date_to,
        crisis_summaries=crisis_summaries,
        total_reports=total_reports,
        countries_count=len(crises),
    )

    try:
        return chat_simple(
            user_prompt=prompt,
            system_prompt=_GLOBAL_OVERVIEW_SYSTEM,
            max_tokens=500,
            temperature=0.3,
        )
    except Exception as exc:
        logger.warning("Failed to generate global overview: %s", exc)
        return f"This week saw humanitarian developments across {len(crises)} countries, with a total of {total_reports} reports analyzed."


# ---------------------------------------------------------------------------
# Bulletin generation
# ---------------------------------------------------------------------------

def generate_weekly_bulletin(
    date_from: str,
    date_to: str,
    skip_llm: bool = False,
) -> Path:
    """
    Generate a weekly bulletin for the given date range.

    Args:
        date_from: Start date (YYYY-MM-DD)
        date_to: End date (YYYY-MM-DD)
        skip_llm: If True, skip LLM calls and use metadata-only summaries

    Returns:
        Path to the saved bulletin JSON file.
    """
    logger.info("=" * 60)
    logger.info("Weekly Bulletin: %s to %s", date_from, date_to)
    logger.info("=" * 60)

    # 1. Fetch reports grouped by country
    fetch_result = fetch_reports_by_date_range(date_from, date_to)
    grouped = fetch_result["grouped"]
    actual_date_from = fetch_result["actual_date_from"]
    actual_date_to = fetch_result["actual_date_to"]
    date_fallback = fetch_result["date_fallback"]

    if date_fallback:
        logger.info(
            "Date fallback: requested %s-%s, using available data %s-%s",
            date_from, date_to, actual_date_from, actual_date_to,
        )

    if not grouped:
        logger.warning("No reports found for date range %s to %s", date_from, date_to)
        # Still create an empty bulletin
        bulletin = {
            "type": "weekly_bulletin",
            "week_start": date_from,
            "week_end": date_to,
            "week_label": f"{date_from} to {date_to}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_reports": 0,
            "total_chunks": 0,
            "countries_affected": 0,
            "global_overview": "No significant humanitarian developments were recorded during this period.",
            "key_figures": [
                {"label": "Total Reports", "value": "0", "icon": "description"},
                {"label": "Countries Affected", "value": "0", "icon": "public"},
                {"label": "Active Crises", "value": "0", "icon": "warning"},
            ],
            "crises": [],
        }
        return _save_bulletin(bulletin, date_from, date_to)

    # 2. Generate crisis summaries
    crises = []
    total_reports = 0
    all_themes = Counter()

    for country, reports in sorted(grouped.items(), key=lambda x: -len(x[1])):
        total_reports += len(reports)

        # Collect themes
        country_themes = []
        for r in reports:
            raw = r.get("themes", "")
            if raw:
                for t in raw.split(","):
                    t = t.strip()
                    if t:
                        country_themes.append(t)
                        all_themes[t] += 1

        unique_themes = list(dict.fromkeys(country_themes))[:6]  # Dedupe, limit to 6

        # Collect sources (deduplicated by URL)
        seen_urls = set()
        sources = []
        for r in reports:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                sources.append({
                    "title": r.get("title", ""),
                    "url": url,
                    "date": r.get("date", "")[:10],
                    "source": r.get("source", ""),
                })

        # Determine severity
        severity = _determine_severity(len(reports), unique_themes)

        # Fetch HDX enrichment data for this country
        hdx_data = None
        hdx_key_figures = []
        hdx_context_text = ""
        try:
            from hdx_enrichment import fetch_hdx_context, format_hdx_for_bulletin
            hdx_context = fetch_hdx_context(country)
            if hdx_context:
                hdx_bulletin = format_hdx_for_bulletin(hdx_context)
                hdx_key_figures = hdx_bulletin.get("key_figures", [])
                hdx_context_text = hdx_bulletin.get("context_text", "")
                hdx_data = hdx_context  # Store full context for the crisis entry
        except Exception as exc:
            logger.warning("HDX enrichment for %s failed (non-fatal): %s", country, exc)

        # Generate LLM summary (or use metadata-only fallback)
        if skip_llm:
            headline = f"{country} humanitarian situation"
            summary = f"Analysis of {len(reports)} reports from {country} covering themes: {', '.join(unique_themes[:3])}."
            if hdx_context_text:
                summary += f" {hdx_context_text}"
        else:
            llm_result = generate_crisis_summary(country, reports, date_from, date_to, hdx_context_text=hdx_context_text)
            if llm_result:
                headline = llm_result["headline"]
                summary = llm_result["summary"]
                severity = llm_result.get("severity", severity)
            else:
                headline = f"{country} humanitarian situation"
                summary = f"Analysis of {len(reports)} reports from {country}."
                if hdx_context_text:
                    summary += f" {hdx_context_text}"

        # Check if a SITREP report exists for this country
        report_dir = Path(_ROOT_DIR) / "output" / "reports"
        has_sitrep = False
        sitrep_file = None
        if report_dir.exists():
            for f in report_dir.glob(f"{country.replace(' ', '_')}_*_report.json"):
                has_sitrep = True
                sitrep_file = f.name
                break

        crisis = {
            "country": country,
            "headline": headline,
            "summary": summary,
            "severity": severity,
            "report_count": len(reports),
            "themes": unique_themes,
            "sources": sources[:10],  # Limit to 10 sources
            "has_sitrep": has_sitrep,
            "sitrep_file": sitrep_file,
            "coords": COUNTRY_COORDS.get(country, {"lat": 0, "lng": 0}),
            "hdx_key_figures": hdx_key_figures,
        }
        crises.append(crisis)

    # 3. Generate global overview
    if skip_llm:
        global_overview = (
            f"This week saw humanitarian developments across {len(crises)} countries, "
            f"with a total of {total_reports} reports analyzed. "
            f"Key themes include {', '.join(t for t, _ in all_themes.most_common(3))}."
        )
    else:
        global_overview = generate_global_overview(crises, date_from, date_to, total_reports)

    # 4. Build key figures (with HDX enrichment)
    top_themes = [t for t, _ in all_themes.most_common(5)]
    key_figures = [
        {"label": "Total Reports", "value": str(total_reports), "icon": "description"},
        {"label": "Countries Affected", "value": str(len(crises)), "icon": "public"},
        {"label": "Active Crises", "value": str(sum(1 for c in crises if c["severity"] == "high")), "icon": "warning"},
    ]

    # Add HDX key figures from crises that have them
    total_refugees = 0
    total_idps = 0
    for c in crises:
        for kf in c.get("hdx_key_figures", []):
            if kf.get("label") == "Refugees":
                try:
                    total_refugees += int(kf.get("value", "0").replace(",", ""))
                except (ValueError, TypeError):
                    pass
            elif kf.get("label") == "IDPs":
                try:
                    total_idps += int(kf.get("value", "0").replace(",", ""))
                except (ValueError, TypeError):
                    pass

    if total_refugees > 0:
        key_figures.append({"label": "Total Refugees", "value": f"{total_refugees:,}", "icon": "people"})
    if total_idps > 0:
        key_figures.append({"label": "Total IDPs", "value": f"{total_idps:,}", "icon": "home"})

    # 5. Assemble bulletin
    # Use actual data dates for week_start/week_end when fallback is used,
    # and include data_date_range to show the real data coverage
    bulletin_week_start = actual_date_from if date_fallback else date_from
    bulletin_week_end = actual_date_to if date_fallback else date_to
    bulletin_week_label = (
        f"{date_from} to {date_to} (data: {actual_date_from} to {actual_date_to})"
        if date_fallback
        else f"{date_from} to {date_to}"
    )

    bulletin = {
        "type": "weekly_bulletin",
        "week_start": bulletin_week_start,
        "week_end": bulletin_week_end,
        "week_label": bulletin_week_label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_reports": total_reports,
        "total_chunks": sum(len(r) for r in grouped.values()),
        "countries_affected": len(crises),
        "global_overview": global_overview,
        "key_figures": key_figures,
        "top_themes": top_themes,
        "crises": crises,
    }

    # Include data date range info when fallback was used
    if date_fallback:
        bulletin["data_date_range"] = {
            "requested_from": date_from,
            "requested_to": date_to,
            "actual_from": actual_date_from,
            "actual_to": actual_date_to,
            "fallback": True,
        }

    return _save_bulletin(bulletin, date_from, date_to)


def _save_bulletin(bulletin: Dict, date_from: str, date_to: str) -> Path:
    """Save bulletin JSON to output/bulletins/ directory."""
    # Use ISO week format for filename
    try:
        dt = datetime.strptime(date_from, "%Y-%m-%d")
        week_label = dt.strftime("%Y-W%W")
    except ValueError:
        week_label = f"{date_from}_{date_to}"

    filename = f"{week_label}_bulletin.json"
    path = BULLETINS_DIR / filename

    with open(path, "w", encoding="utf-8") as f:
        json.dump(bulletin, f, indent=2, ensure_ascii=False)

    logger.info("Bulletin saved: %s", path)
    logger.info("  %d crises, %d total reports", len(bulletin["crises"]), bulletin["total_reports"])
    return path


# ---------------------------------------------------------------------------
# List bulletins
# ---------------------------------------------------------------------------

def list_bulletins() -> List[Dict]:
    """List available bulletins, sorted by date descending."""
    if not BULLETINS_DIR.exists():
        return []

    bulletins = []
    for f in sorted(BULLETINS_DIR.glob("*_bulletin.json"), reverse=True):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            bulletins.append({
                "filename": f.name,
                "week_start": data.get("week_start", ""),
                "week_end": data.get("week_end", ""),
                "week_label": data.get("week_label", ""),
                "total_reports": data.get("total_reports", 0),
                "countries_affected": data.get("countries_affected", 0),
                "crises_count": len(data.get("crises", [])),
                "generated_at": data.get("generated_at", ""),
                "data_date_range": data.get("data_date_range"),
            })
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("Failed to read bulletin %s: %s", f.name, exc)

    return bulletins


def get_bulletin(filename: str) -> Optional[Dict]:
    """Load a specific bulletin by filename."""
    path = BULLETINS_DIR / filename
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("Failed to read bulletin %s: %s", filename, exc)
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Weekly Bulletin Generator — Sightline"
    )
    parser.add_argument(
        "--date-from", required=True,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--date-to", required=True,
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--skip-llm", action="store_true",
        help="Skip LLM calls, use metadata-only summaries",
    )

    args = parser.parse_args()
    path = generate_weekly_bulletin(
        date_from=args.date_from,
        date_to=args.date_to,
        skip_llm=args.skip_llm,
    )
    print(f"Bulletin saved to: {path}")