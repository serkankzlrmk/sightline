"""
blueprints/public_bp.py — Public / Map routes extracted from server.py.

Flask Blueprint for all /api/public/*, /api/country/*, and /api/map/* endpoints.

Register in server.py with:
    from blueprints.public_bp import public_bp
    app.register_blueprint(public_bp)
"""

import json
import logging
import sqlite3
import threading
import time as _time
from pathlib import Path

from flask import Blueprint, jsonify, request

from auth import current_uid, require_admin, require_auth
from config import DB_PATH, OUTPUT_REPORTS_DIR

logger = logging.getLogger(__name__)

public_bp = Blueprint('public', __name__, url_prefix='/api')

# ── Late import helpers from server.py ──────────────────────────────────────
# These are defined in server.py and accessed via `import server` to avoid
# circular-import issues at module-load time.

def _db_conn():
    """Proxy for server._db_conn – connects to the reliefweb SQLite database."""
    import server as _srv
    return _srv._db_conn()


def _log_event(uid, event, props=None, session=""):
    """Proxy for server._log_event – logs analytics events."""
    import server as _srv
    return _srv._log_event(uid, event, props, session)


def _parse_countries(json_str):
    """Parse a JSON countries string into a list."""
    try:
        return json.loads(json_str or "[]")
    except Exception:
        return []


def _trim_bulletin_for_preview(bulletin: dict) -> dict:
    """Trim a full bulletin for public preview — keeps all content visible
    on the home/dashboard. Only removes crisis sources (external links) and
    HDX key figures for anonymous users. Everything else is public."""
    trimmed = dict(bulletin)
    # Keep global_overview, key_figures, top_themes fully visible
    # For crises: keep headline, summary, severity, coords, report_count, themes
    # but remove sources (external ReliefWeb links) and hdx_key_figures
    if "crises" in trimmed:
        trimmed_crises = []
        for c in trimmed["crises"]:
            tc = dict(c)
            tc.pop("sources", None)
            tc.pop("hdx_key_figures", None)
            trimmed_crises.append(tc)
        trimmed["crises"] = trimmed_crises
    return trimmed


# ── ChromaDB adapter singleton (lazily initialised) ──────────────────────────
_chroma_adapter = None
_chroma_adapter_lock = threading.Lock()
_map_countries_cache = None
_map_countries_cache_time = 0.0


def _get_chroma_adapter():
    global _chroma_adapter
    if _chroma_adapter is not None:
        return _chroma_adapter
    with _chroma_adapter_lock:
        if _chroma_adapter is not None:
            return _chroma_adapter
        from sitrep.chroma_adapter import ChromaAdapter
        _chroma_adapter = ChromaAdapter()
        return _chroma_adapter


# =============================================================================
# ROUTES — Public stats & bulletins
# =============================================================================

@public_bp.route("/public/stats")
def api_public_stats():
    """Public DB stats — aggregate counts only, no sensitive data."""
    conn = _db_conn()
    try:
        report_count = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        chunk_count  = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        country_rows = conn.execute("SELECT countries FROM reports LIMIT 2000").fetchall()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return jsonify({"report_count": 0, "chunk_count": 0, "top_countries": []})
    finally:
        try:
            conn.close()
        except Exception:
            pass

    country_counts: dict = {}
    for r in country_rows:
        for c in _parse_countries(r[0]):
            country_counts[c] = country_counts.get(c, 0) + 1

    return jsonify({
        "report_count": report_count,
        "chunk_count":  chunk_count,
        "top_countries": sorted(country_counts.items(), key=lambda x: -x[1])[:15],
    })


@public_bp.route("/public/bulletins")
def api_public_bulletins():
    """Public bulletin list — metadata only (titles, dates, counts)."""
    from sitrep.weekly_bulletin import list_bulletins
    bulletins = list_bulletins()
    return jsonify(bulletins)


@public_bp.route("/public/bulletin/<filename>")
def api_public_bulletin_get(filename):
    """Public bulletin — trimmed version (headlines + severity + coords only)."""
    from sitrep.weekly_bulletin import get_bulletin
    if ".." in filename or "/" in filename or "\\" in filename:
        return jsonify({"error": "Invalid filename"}), 400
    bulletin = get_bulletin(filename)
    if bulletin is None:
        return jsonify({"error": "Bulletin not found"}), 404
    return jsonify(_trim_bulletin_for_preview(bulletin))


@public_bp.route("/public/sitrep/reports")
def api_public_sitrep_reports():
    """Public SITREP report list — filenames only, no content."""
    items = []
    if OUTPUT_REPORTS_DIR.exists():
        for f in sorted(
            OUTPUT_REPORTS_DIR.glob("*report.json"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        ):
            items.append({"filename": f.name})
    return jsonify(items)


# =============================================================================
# ROUTES — Country Intelligence Cards
# =============================================================================

@public_bp.route("/country/summaries")
def api_country_summaries():
    """Public: lightweight list of all country summaries for map markers."""
    from sitrep.country_summary import list_country_summaries
    summaries = list_country_summaries()
    return jsonify(summaries)


# =============================================================================
# ROUTES — /api/map/* (Crisis Map — all-in-one data endpoint)
# =============================================================================

@public_bp.route("/map/countries")
def api_map_countries():
    """Public: Top 60 countries with rich data for the crisis map.

    Returns an array of country objects, sorted by report_count descending,
    each containing:
      - Basic: country, iso3, coords, severity, report_count, last_updated
      - Summary: headline, narrative (from country_summary if available, else generated from chunks)
      - Reports: recent_reports (last 3), date_range
      - Extras: hdx_key_figures, gdacs_alerts, has_sitrep, top_themes

    This replaces the previous 3-call pattern (bulletin + summaries + countries).
    The data is cached in-memory for 5 minutes.
    """
    global _map_countries_cache, _map_countries_cache_time

    # Cache for 5 minutes
    if _map_countries_cache is not None and (_time.time() - _map_countries_cache_time) < 300:
        return jsonify(_map_countries_cache)

    try:
        from sitrep.weekly_bulletin import COUNTRY_COORDS, _determine_severity
        from sitrep.country_summary import (
            get_country_summary, COUNTRY_SUMMARY_DIR, _country_to_iso3,
        )
        db = _get_chroma_adapter()
        all_countries = db.list_countries_with_counts()

        # Sort by count, take top 60 (exclude non-country entries)
        all_countries = [c for c in all_countries if c.get("name", c.get("country", "")).lower() not in ("world", "global", "international", "region", "unknown")]
        all_countries.sort(key=lambda x: x.get("count", 0), reverse=True)
        top_countries = all_countries[:60]

        # Alias mapping for country name variants
        aliases = {
            "Syrian Arab Republic": "Syria",
            "Türkiye": "Turkey",
            "oPt": "occupied Palestinian territory",
            "DR Congo": "Democratic Republic of the Congo",
            "Iran (Islamic Republic of)": "Iran",
        }
        reverse_aliases = {v: k for k, v in aliases.items()}

        results = []
        for entry in top_countries:
            country = entry.get("name", "")
            count = entry.get("count", 0)
            if not country:
                continue

            # Resolve coords — try direct, then alias, then reverse alias
            coords = COUNTRY_COORDS.get(country, {})
            if not coords:
                coords = COUNTRY_COORDS.get(aliases.get(country, ""), {})
            if not coords:
                coords = COUNTRY_COORDS.get(reverse_aliases.get(country, ""), {})
            if not coords:
                coords = {"lat": 0, "lng": 0}

            # Try to load existing country summary JSON
            safe_name = country.replace(" ", "_").replace("/", "_").replace("\\", "_")
            summary_path = COUNTRY_SUMMARY_DIR / f"{safe_name}.json"
            summary_data = None
            if summary_path.exists():
                try:
                    summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

            # Build the response object
            iso3 = (summary_data or {}).get("iso3", "") or _country_to_iso3(country) if country else ""

            # Get date range from summary or compute from DB
            date_range = (summary_data or {}).get("date_range", {})
            last_updated = (summary_data or {}).get("generated_at", "")

            # Severity from summary or compute
            severity = (summary_data or {}).get("severity", "")
            if not severity:
                top_themes_raw = (summary_data or {}).get("top_themes", [])
                severity = _determine_severity(count, top_themes_raw)

            # Headline + narrative from summary
            headline = (summary_data or {}).get("headline", "")
            narrative = (summary_data or {}).get("narrative", "")

            # Recent reports from summary or compute
            recent_reports = (summary_data or {}).get("recent_reports", [])
            if not recent_reports:
                try:
                    chunks = db.get_chunks_by_country(country, limit=30)
                    seen_titles = set()
                    for chunk in chunks:
                        title = chunk.get("title", "")
                        if title and title not in seen_titles and len(recent_reports) < 3:
                            seen_titles.add(title)
                            recent_reports.append({
                                "title": title,
                                "date": chunk.get("date", ""),
                                "source": chunk.get("source", ""),
                                "url": chunk.get("url", ""),
                            })
                except Exception:
                    pass

            # Top themes from summary or compute
            top_themes = (summary_data or {}).get("top_themes", [])
            chunks = None  # Will be loaded from DB if needed
            if not top_themes:
                try:
                    chunks = db.get_chunks_by_country(country, limit=50)
                    from collections import Counter as _Counter
                    theme_counter = _Counter()
                    for chunk in chunks:
                        raw_themes = chunk.get("themes", "")
                        if raw_themes:
                            for t in raw_themes.split(","):
                                t = t.strip()
                                if t:
                                    theme_counter[t] += 1
                    top_themes = [t for t, _ in theme_counter.most_common(5)]
                except Exception:
                    pass

            # HDX key figures + GDACS alerts from summary
            hdx_key_figures = (summary_data or {}).get("hdx_key_figures", {})
            gdacs_alerts = (summary_data or {}).get("gdacs_alerts", [])
            has_sitrep = (summary_data or {}).get("has_sitrep", False)

            # If no generated_at date, use date_range max_date
            if not last_updated and date_range:
                last_updated = date_range.get("max_date", "")

            result = {
                "country": country,
                "iso3": iso3,
                "coords": coords,
                "severity": severity,
                "report_count": count,
                "headline": headline,
                "narrative": narrative,
                "date_range": date_range,
                "last_updated": last_updated,
                "recent_reports": recent_reports[:3],
                "top_themes": top_themes[:5],
                "hdx_key_figures": hdx_key_figures,
                "gdacs_alerts": gdacs_alerts,
                "has_sitrep": has_sitrep,
                "has_summary": summary_data is not None,
            }
            results.append(result)

        _map_countries_cache = results
        _map_countries_cache_time = _time.time()

        return jsonify(results)
    except Exception as exc:
        logger.error("api_map_countries error: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load map data"}), 500


@public_bp.route("/public/countries")
def api_public_countries():
    """Public: all countries with chunk counts + coordinates (for map markers)."""
    try:
        from sitrep.weekly_bulletin import COUNTRY_COORDS
        db = _get_chroma_adapter()
        countries = db.list_countries_with_counts()
        for c in countries:
            name = c.get("name", "")
            coords = COUNTRY_COORDS.get(name, {})
            if not coords:
                aliases = {"Syrian Arab Republic": "Syria", "Türkiye": "Turkey", "oPt": "occupied Palestinian territory",
                       "DR Congo": "Democratic Republic of the Congo", "Iran (Islamic Republic of)": "Iran"}
                coords = COUNTRY_COORDS.get(aliases.get(name, ""), {})
            c["coords"] = coords if coords else {"lat": 0, "lng": 0}
        return jsonify(countries)
    except Exception as exc:
        logger.error("api_public_countries error: %s", exc, exc_info=True)
        return jsonify([])


@public_bp.route("/country/<path:country>/summary")
@require_auth
def api_country_summary(country):
    """Auth-gated: full country intelligence card."""
    from sitrep.country_summary import get_country_summary
    # Sanitize country name
    if ".." in country or "/" in country[:1]:
        return jsonify({"error": "Invalid country name"}), 400
    summary = get_country_summary(country)
    if summary is None:
        return jsonify({"error": "No summary available for " + country}), 404
    _log_event(current_uid(), "country_card_viewed", {"country": country})
    return jsonify(summary)


@public_bp.route("/country/<path:country>/refresh", methods=["POST"])
@require_admin
def api_country_refresh(country):
    """Admin only: force regenerate a country summary."""
    from sitrep.country_summary import generate_country_summary
    if ".." in country or "/" in country[:1]:
        return jsonify({"error": "Invalid country name"}), 400
    result = generate_country_summary(country, force_hdx=True)
    if result is None:
        return jsonify({"error": "Insufficient data for " + country}), 404
    _log_event(current_uid(), "country_card_refreshed", {"country": country})
    return jsonify({"ok": True, "country": country})