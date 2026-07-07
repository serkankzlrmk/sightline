"""
ReliefWeb API Tools for LangChain Integration
Provides tools for querying humanitarian data from ReliefWeb API

Usage:
    from reliefweb_api import search_sitreps, get_sitrep_summary, ...
    
    # Direct invocation
    result = search_sitreps.invoke({"country": "Syria", "limit": 10})
    
    # With tool agents
    from langchain.agents import Tool
    tools = [search_sitreps, get_sitrep_summary, ...]
"""

import json
import os
import re
import sqlite3
import tempfile

import requests
from langchain.tools import tool
from PyPDF2 import PdfReader

from .pdf_converter import ReportFormatConverter
from .reliefweb_config import (
    API_TIMEOUT_SHORT,
    DISASTER_LIMIT_MAX,
    LOCAL_DB_PATH,
    PDF_DOWNLOAD_TIMEOUT,
    PDF_SIZE_LIMIT,
    PDF_SIZE_LIMIT_MB,
    RELIEFWEB_APPNAME,
    RELIEFWEB_DISASTERS_API,
    RELIEFWEB_REPORTS_API,
    RELIEFWEB_SOURCES_API,
    REPORT_LIMIT_MAX,
    SUMMARY_CHAR_LIMIT,
    _ssl_verify,
)
from .reliefweb_utils import (
    clean_html_body,
    format_error,
    format_response,
    normalize_country_name,
    retry_request,
    truncate_text,
    validate_country,
    validate_date,
    validate_limit,
)

# ========================================================================
# LOCAL DB HELPERS — read from SQLite before hitting the external API
# ========================================================================

def _local_report_meta(report_id: int) -> dict | None:
    """Return the reports row as a dict, or None if not found."""
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM reports WHERE report_id = ?", (report_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None

def _local_report_chunks(report_id: int) -> list:
    """Return all chunks for a report as a list of dicts, ordered by index."""
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT content FROM chunks WHERE report_id = ? ORDER BY chunk_index",
            (report_id,)
        ).fetchall()
        conn.close()
        return [r["content"] for r in rows]
    except Exception:
        return []

# ========================================================================
# TOOL 1: Search Situation Reports
# ========================================================================

@tool
def search_sitreps(
    country: str | None = None,
    query: str | None = None,
    limit: int = 25,
    theme: str | None = None,
    source_org: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    format_type: str | None = None,
    language: str | None = None,
    primary_country: str | None = None,
    disaster: str | None = None,
    disaster_type: str | None = None,
    source_fullname: str | None = None,
    organization_type: str | None = None,
) -> str:
    """
    Search for humanitarian reports from ReliefWeb with advanced filters.
    Country is optional — omit it for global search across all countries.

    Args:
        country: Country name (e.g., 'Syria', 'Sudan', 'Pakistan'). Optional — omit for global search.
        query: Free-text keyword filter (e.g., 'food security', 'flood', 'displacement')
        limit: Number of reports to return (max 100, default 25)
        theme: Topic filter. Values: 'Health', 'Food and Nutrition', 'Education',
               'Shelter and Non-Food Items', 'Water Sanitation Hygiene', 'Protection',
               'Logistics and Telecommunications', 'Contributions', 'Mine Action'
        source_org: Filter by organization shortname (e.g., 'UNHCR', 'WFP', 'UNICEF',
                    'OCHA', 'WHO', 'IRC', 'MSF', 'IOM', 'NRC')
        date_from: Start date filter in YYYY-MM-DD format (e.g., '2025-01-01')
        date_to: End date filter in YYYY-MM-DD format (e.g., '2026-03-31')
        format_type: Report format filter. Values: 'Situation Report', 'News and Press Release',
                     'Assessment', 'Appeal', 'Map', 'Infographic', 'Analysis'
        language: Language filter. Values: 'en', 'ar', 'fr', 'es'
        primary_country: Filter by primary country (same as country but uses primary_country field)
        disaster: Filter by disaster name (e.g., 'Turkey-Syria Earthquake')
        disaster_type: Filter by disaster type (e.g., 'Earthquake', 'Flood', 'Epidemic', 'Drought', 'Cyclone', 'Complex Emergency')
        source_fullname: Filter by full organization name (e.g., 'World Health Organization'). Use when shortname is unknown.
        organization_type: Filter by organization type (e.g., 'International NGO', 'United Nations', 'Government', 'Red Cross / Red Crescent')

    Returns:
        JSON list of reports with id, title, date, source, url

    Examples:
        search_sitreps(country="Syria")
        search_sitreps(query="earthquake", limit=10)
        search_sitreps(country="Sudan", query="health", limit=5)
        search_sitreps(country="Yemen", theme="Food and Nutrition", source_org="WFP")
        search_sitreps(disaster_type="Earthquake", date_from="2023-02-01")
        search_sitreps(source_fullname="World Health Organization", country="Syria")
        search_sitreps(organization_type="Red Cross / Red Crescent")
    """
    try:
        is_valid, error_msg = validate_limit(limit, REPORT_LIMIT_MAX)
        if not is_valid:
            return format_error("InvalidInput", error_msg)

        # Build filter conditions list
        filters = []

        if country:
            is_valid, error_msg = validate_country(country)
            if not is_valid:
                return format_error("InvalidInput", error_msg)
            normalized_country = normalize_country_name(country)
            filters.append({"field": "country.name", "value": normalized_country})

        if primary_country:
            normalized_pc = normalize_country_name(primary_country)
            filters.append({"field": "primary_country.name", "value": normalized_pc})

        if theme:
            filters.append({"field": "theme.name", "value": theme})

        if source_org:
            filters.append({"field": "source.shortname", "value": source_org})

        if source_fullname:
            filters.append({"field": "source.name", "value": source_fullname})

        if organization_type:
            filters.append({"field": "source.type.name", "value": organization_type})

        if format_type:
            filters.append({"field": "format.name", "value": format_type})

        if language:
            filters.append({"field": "language.code", "value": language})

        if disaster:
            filters.append({"field": "disaster.name", "value": disaster})

        if disaster_type:
            filters.append({"field": "disaster_type.name", "value": disaster_type})

        if date_from or date_to:
            date_filter = {"field": "date.original"}
            if date_from and date_to:
                date_filter["value"] = {"from": f"{date_from}T00:00:00+00:00", "to": f"{date_to}T23:59:59+00:00"}
            elif date_from:
                date_filter["value"] = {"from": f"{date_from}T00:00:00+00:00"}
            else:
                date_filter["value"] = {"to": f"{date_to}T23:59:59+00:00"}
            filters.append(date_filter)

        # Combine filters
        combined_filter = None
        if len(filters) == 1:
            combined_filter = filters[0]
        elif len(filters) > 1:
            combined_filter = {"operator": "AND", "conditions": filters}

        body = {
            "preset": "latest",
            "limit": min(limit, REPORT_LIMIT_MAX),
            "fields": {
                "include": ["id", "title", "date", "source", "url", "theme", "format", "language", "country"]
            }
        }

        if combined_filter:
            body["filter"] = combined_filter

        if query:
            body["query"] = {"value": str(query).strip()}

        url = f"{RELIEFWEB_REPORTS_API}?appname={RELIEFWEB_APPNAME}"
        response = retry_request("post", url, json=body, timeout=API_TIMEOUT_SHORT, verify=_ssl_verify())
        response.raise_for_status()
        data = response.json()

        reports_data = data.get("data", [])
        if not reports_data:
            return format_response([])

        reports = []
        for item in reports_data:
            fields = item.get("fields", {})
            source_info = fields.get("source", [])
            source_name = source_info[0].get("shortname", "Unknown") if source_info else "Unknown"
            themes = [t.get("name", "") for t in fields.get("theme", [])]
            fmt = [f.get("name", "") for f in fields.get("format", [])]
            countries = [c.get("name", "") for c in fields.get("country", [])]

            reports.append({
                "id": item.get("id"),
                "title": fields.get("title", "No title"),
                "date": fields.get("date", {}).get("original", fields.get("date", {}).get("created", "Unknown")),
                "source": source_name,
                "url": fields.get("url", ""),
                "themes": themes,
                "format": fmt,
                "countries": countries,
            })

        return format_response(reports)

    except requests.exceptions.RequestException as e:
        return format_error("APIError", f"Failed to fetch reports: {str(e)}")
    except Exception as e:
        return format_error("UnexpectedError", str(e))


# ========================================================================
# TOOL 2: Get Report Summary
# ========================================================================

@tool
def get_sitrep_summary(report_id: int | None = None, ids: list | None = None) -> str:
    """
    Get a summary of a specific report.
    
    Returns a concise summary (700 characters) with metadata.
    Use this for quick overview of a report.
    
    Args:
        report_id: Report ID from search results (single report)
        ids: Deprecated - list of report IDs (will use first one)
        
    Returns:
        JSON with report summary, title, date, source, and URL
        
    Examples:
        get_sitrep_summary.invoke({"report_id": 4192591})
    """
    try:
        # Handle both parameter names - use report_id if provided, fallback to ids
        actual_report_id = report_id
        if actual_report_id is None and ids is not None:
            # If ids is provided as a list, use the first one
            if isinstance(ids, list) and len(ids) > 0:
                actual_report_id = ids[0]

        # Validate input
        if actual_report_id is None:
            return format_error("InvalidInput", "Either report_id or ids must be provided")

        if not isinstance(actual_report_id, int) or actual_report_id < 1:
            return format_error("InvalidInput", "Report ID must be a positive integer")

        # ── Fast path: local SQLite DB ───────────────────────────────────
        meta = _local_report_meta(actual_report_id)
        if meta:
            chunks = _local_report_chunks(actual_report_id)
            full_text = " ".join(chunks)
            summary = truncate_text(full_text, SUMMARY_CHAR_LIMIT)
            try:
                countries = json.loads(meta.get("countries") or "[]")
            except Exception:
                countries = []
            result = {
                "id": actual_report_id,
                "title": meta.get("title", ""),
                "date": meta.get("date", ""),
                "source": meta.get("source", ""),
                "url": meta.get("url", ""),
                "summary": summary,
                "summary_length": len(summary),
                "countries": countries,
                "_source": "local_db",
            }
            return format_response(result)

        # ── Slow path: external ReliefWeb API ────────────────────────────
        url = f"{RELIEFWEB_REPORTS_API}/{actual_report_id}?appname={RELIEFWEB_APPNAME}"
        response = retry_request("get", url, timeout=API_TIMEOUT_SHORT, verify=_ssl_verify())
        response.raise_for_status()
        data = response.json()

        fields = data["data"][0]["fields"]
        body_html = fields.get("body", "")
        clean_body = clean_html_body(body_html)

        # Truncate to summary length
        summary = truncate_text(clean_body, SUMMARY_CHAR_LIMIT)

        source_info = fields.get("source", [])
        source_name = source_info[0].get("shortname", "Unknown") if source_info else "Unknown"

        result = {
            "id": actual_report_id,
            "title": fields.get("title", ""),
            "date": fields.get("date", {}).get("created", ""),
            "source": source_name,
            "url": fields.get("url", ""),
            "summary": summary,
            "summary_length": len(summary),
        }

        return format_response(result)

    except requests.exceptions.RequestException as e:
        return format_error("APIError", f"Failed to fetch report: {str(e)}")
    except (KeyError, IndexError):
        return format_error("NotFound", f"Report {actual_report_id} not found")
    except Exception as e:
        return format_error("UnexpectedError", str(e))


# ========================================================================
# TOOL 3: Get Full Report Content
# ========================================================================

@tool
def get_report_full_content(report_id: int | None = None, ids: list | None = None) -> str:
    """
    Get FULL content of a report.
    
    Returns complete metadata and HTML body content (typically 1000-5000 chars).
    Use this for detailed analysis of a report.
    
    Args:
        report_id: Report ID from search results (single report)
        ids: Deprecated - list of report IDs (will use first one)
        
    Returns:
        JSON with full report content, metadata, countries, and disasters
        
    Examples:
        get_report_full_content.invoke({"report_id": 4192591})
    """
    try:
        # Handle both parameter names - use report_id if provided, fallback to ids
        actual_report_id = report_id
        if actual_report_id is None and ids is not None:
            # If ids is provided as a list, use the first one
            if isinstance(ids, list) and len(ids) > 0:
                actual_report_id = ids[0]

        # Validate input
        if actual_report_id is None:
            return format_error("InvalidInput", "Either report_id or ids must be provided")

        if not isinstance(actual_report_id, int) or actual_report_id < 1:
            return format_error("InvalidInput", "Report ID must be a positive integer")

        # ── Fast path: local SQLite DB ───────────────────────────────────
        meta = _local_report_meta(actual_report_id)
        if meta:
            chunks = _local_report_chunks(actual_report_id)
            full_content = "\n\n".join(chunks)
            try:
                countries = json.loads(meta.get("countries") or "[]")
            except Exception:
                countries = []
            try:
                themes = json.loads(meta.get("themes") or "[]")
            except Exception:
                themes = []
            result = {
                "id": actual_report_id,
                "title": meta.get("title", ""),
                "date": meta.get("date", ""),
                "source": meta.get("source", ""),
                "url": meta.get("url", ""),
                "countries": countries,
                "themes": themes,
                "disasters": [],
                "headline_title": "",
                "headline_summary": "",
                "full_content": full_content,
                "content_length": len(full_content),
                "_source": "local_db",
            }
            return format_response(result)

        # ── Slow path: external ReliefWeb API ────────────────────────────
        url = f"{RELIEFWEB_REPORTS_API}/{actual_report_id}?appname={RELIEFWEB_APPNAME}"
        response = retry_request("get", url, timeout=API_TIMEOUT_SHORT, verify=_ssl_verify())
        response.raise_for_status()
        data = response.json()

        fields = data["data"][0]["fields"]

        # Extract body content
        body_html = fields.get("body-html") or fields.get("body", "")
        clean_body = clean_html_body(body_html)

        # Extract headline
        headline = fields.get("headline", {})
        headline_title = headline.get("title", "") if isinstance(headline, dict) else ""
        headline_summary = headline.get("summary", "") if isinstance(headline, dict) else ""

        # Extract countries and disasters
        countries = []
        if fields.get("country"):
            countries = [c.get("name", "") for c in fields["country"]]

        disasters = []
        if fields.get("disaster"):
            disasters = [d.get("name", "") for d in fields["disaster"]]

        source_info = fields.get("source", [])
        source_name = source_info[0].get("shortname", "Unknown") if source_info else "Unknown"

        result = {
            "id": actual_report_id,
            "title": fields.get("title", ""),
            "date": fields.get("date", {}).get("created", ""),
            "source": source_name,
            "url": fields.get("url", ""),
            "countries": countries,
            "disasters": disasters,
            "headline_title": headline_title,
            "headline_summary": headline_summary,
            "full_content": clean_body,
            "content_length": len(clean_body),
        }

        return format_response(result)

    except requests.exceptions.RequestException as e:
        return format_error("APIError", f"Failed to fetch report: {str(e)}")
    except (KeyError, IndexError):
        return format_error("NotFound", f"Report {actual_report_id} not found")
    except Exception as e:
        return format_error("UnexpectedError", str(e))


# ========================================================================
# TOOL 4: Search Disasters
# ========================================================================

@tool
def search_disasters(country: str | None = None, status: str = "current", limit: int = 20) -> str:
    """
    Search for disasters and emergencies from ReliefWeb.
    
    Returns list of disasters with type, status, affected countries.
    Filter by country or status (current/past/all).
    
    Args:
        country: Optional country name to filter (e.g., 'Turkey', 'Syria')
        status: 'current' (ongoing), 'past' (historical), or 'all'
        limit: Number of disasters to return (max 50)
        
    Returns:
        JSON list of disasters with names, types, status, and affected countries
        
    Examples:
        search_disasters.invoke({"status": "current"})
        search_disasters.invoke({"country": "Syria", "status": "current"})
    """
    try:
        # Validate inputs
        if status not in ["current", "past", "all"]:
            return format_error("InvalidInput", "Status must be 'current', 'past', or 'all'")

        is_valid, error_msg = validate_limit(limit, DISASTER_LIMIT_MAX)
        if not is_valid:
            return format_error("InvalidInput", error_msg)

        # Build API request
        body = {
            "limit": min(limit, DISASTER_LIMIT_MAX),
            "fields": {
                "include": ["id", "name", "type", "status", "date", "country", "url", "glide"]
            }
        }

        # Add filters
        conditions = []

        if country:
            normalized_country = normalize_country_name(country)
            conditions.append({
                "field": "country.name",
                "value": normalized_country
            })

        if status != "all":
            status_value = "ongoing" if status == "current" else "past"
            conditions.append({
                "field": "status",
                "value": status_value
            })

        if conditions:
            if len(conditions) == 1:
                body["filter"] = conditions[0]
            else:
                body["filter"] = {"conditions": conditions, "operator": "AND"}

        # Make API request
        url = f"{RELIEFWEB_DISASTERS_API}?appname={RELIEFWEB_APPNAME}"
        response = retry_request("post", url, json=body, timeout=API_TIMEOUT_SHORT, verify=_ssl_verify())
        response.raise_for_status()
        data = response.json()

        # Extract disasters
        disasters_data = data.get("data", [])
        if not disasters_data:
            return format_response([])

        disasters = []
        for item in disasters_data:
            fields = item.get("fields", {})
            country_list = [c.get("name", "") for c in fields.get("country", [])]

            disasters.append({
                "id": item.get("id"),
                "name": fields.get("name", ""),
                "type": fields.get("type", ""),
                "status": fields.get("status", ""),
                "date": fields.get("date", ""),
                "countries": country_list,
                "glide": fields.get("glide", ""),
                "url": fields.get("url", "")
            })

        return format_response(disasters)

    except requests.exceptions.RequestException as e:
        return format_error("APIError", f"Failed to fetch disasters: {str(e)}")
    except Exception as e:
        return format_error("UnexpectedError", str(e))


# ========================================================================
# TOOL 5: Search Disasters by Date
# ========================================================================

@tool
def search_disasters_by_date(
    start_date: str,
    country: str | None = None,
    end_date: str | None = None,
    limit: int = 20
) -> str:
    """
    Search for disasters within a date range.
    
    Args:
        start_date: Start date (YYYY-MM-DD format)
        country: Optional country name to filter
        end_date: End date (YYYY-MM-DD format), defaults to today
        limit: Number of results (max 50)
        
    Returns:
        JSON list of disasters in date range
        
    Examples:
        search_disasters_by_date.invoke({
            "start_date": "2025-01-01",
            "end_date": "2025-12-31"
        })
    """
    try:
        # Validate inputs
        is_valid, error_msg = validate_limit(limit, DISASTER_LIMIT_MAX)
        if not is_valid:
            return format_error("InvalidInput", error_msg)

        is_valid, error_msg = validate_date(start_date)
        if not is_valid:
            return format_error("InvalidInput", f"start_date: {error_msg}")

        if end_date:
            is_valid, error_msg = validate_date(end_date)
            if not is_valid:
                return format_error("InvalidInput", f"end_date: {error_msg}")

        # Build API request
        body = {
            "limit": min(limit, DISASTER_LIMIT_MAX),
            "sort": ["date:desc"],
            "fields": {
                "include": ["id", "name", "type", "status", "date", "country", "url"]
            }
        }

        # Build filters
        conditions = []

        # Date range filter
        date_filter = {"field": "date"}
        if end_date:
            date_filter["value"] = {
                "from": f"{start_date}T00:00:00+00:00",
                "to": f"{end_date}T23:59:59+00:00"
            }
        else:
            date_filter["value"] = {"from": f"{start_date}T00:00:00+00:00"}
        conditions.append(date_filter)

        # Country filter
        if country:
            normalized_country = normalize_country_name(country)
            conditions.append({
                "field": "country.name",
                "value": normalized_country
            })

        # Apply filters
        if len(conditions) == 1:
            body["filter"] = conditions[0]
        else:
            body["filter"] = {"conditions": conditions, "operator": "AND"}

        # Make API request
        url = f"{RELIEFWEB_DISASTERS_API}?appname={RELIEFWEB_APPNAME}"
        response = retry_request("post", url, json=body, timeout=API_TIMEOUT_SHORT, verify=_ssl_verify())
        response.raise_for_status()
        data = response.json()

        # Extract disasters
        disasters_data = data.get("data", [])
        if not disasters_data:
            return format_response([])

        disasters = []
        for item in disasters_data:
            fields = item.get("fields", {})
            country_list = [c.get("name", "") for c in fields.get("country", [])]

            disasters.append({
                "id": item.get("id"),
                "name": fields.get("name", ""),
                "type": fields.get("type", ""),
                "status": fields.get("status", ""),
                "date": fields.get("date", ""),
                "countries": country_list,
                "url": fields.get("url", "")
            })

        return format_response(disasters)

    except requests.exceptions.RequestException as e:
        return format_error("APIError", f"Failed to fetch disasters: {str(e)}")
    except Exception as e:
        return format_error("UnexpectedError", str(e))


# ========================================================================
# TOOL 6: Get Latest Headlines
# ========================================================================

@tool
def get_latest_headlines(limit: int = 15) -> str:
    """
    Get latest humanitarian headlines from ReliefWeb.
    
    Returns most recent news and updates across all crises.
    
    Args:
        limit: Number of headlines to return (max 50)
        
    Returns:
        JSON list of headlines with titles, dates, sources, and affected countries
        
    Examples:
        get_latest_headlines.invoke({})
        get_latest_headlines.invoke({"limit": 20})
    """
    try:
        # Validate input
        is_valid, error_msg = validate_limit(limit, 50)
        if not is_valid:
            return format_error("InvalidInput", error_msg)

        # Build API request
        body = {
            "preset": "latest",
            "limit": min(limit, 50),
            "sort": ["date:desc"],
            "fields": {
                "include": ["id", "title", "date", "source", "url", "country", "theme"]
            }
        }

        # Make API request
        url = f"{RELIEFWEB_REPORTS_API}?appname={RELIEFWEB_APPNAME}"
        response = retry_request("post", url, json=body, timeout=API_TIMEOUT_SHORT, verify=_ssl_verify())
        response.raise_for_status()
        data = response.json()

        # Extract headlines
        headlines_data = data.get("data", [])
        if not headlines_data:
            return format_response([])

        headlines = []
        for item in headlines_data:
            fields = item.get("fields", {})
            source_info = fields.get("source", [])
            source_name = source_info[0].get("shortname", "Unknown") if source_info else "Unknown"

            countries = [c.get("name", "") for c in fields.get("country", [])]
            themes = [t.get("name", "") for t in fields.get("theme", [])]

            headlines.append({
                "id": item.get("id"),
                "title": fields.get("title", ""),
                "date": fields.get("date", {}).get("created", ""),
                "source": source_name,
                "countries": countries,
                "themes": themes,
                "url": fields.get("url", "")
            })

        return format_response(headlines)

    except requests.exceptions.RequestException as e:
        return format_error("APIError", f"Failed to fetch headlines: {str(e)}")
    except Exception as e:
        return format_error("UnexpectedError", str(e))


# ========================================================================
# TOOL 7: Get Latest Blog Posts
# ========================================================================

@tool
def get_latest_blog_posts(limit: int = 10) -> str:
    """
    Get latest blog posts and analysis from humanitarian organizations.
    
    Returns recent posts with analysis and insights.
    
    Args:
        limit: Number of posts to return (max 30)
        
    Returns:
        JSON list of posts with titles, dates, sources, and URLs
        
    Examples:
        get_latest_blog_posts.invoke({})
        get_latest_blog_posts.invoke({"limit": 5})
    """
    try:
        # Validate input
        is_valid, error_msg = validate_limit(limit, 30)
        if not is_valid:
            return format_error("InvalidInput", error_msg)

        # Build API request - use latest reports as blog source
        body = {
            "preset": "latest",
            "limit": min(limit, 30),
            "sort": ["date:desc"],
            "fields": {
                "include": ["id", "title", "date", "source", "url", "source.type"]
            }
        }

        # Make API request
        url = f"{RELIEFWEB_REPORTS_API}?appname={RELIEFWEB_APPNAME}"
        response = retry_request("post", url, json=body, timeout=API_TIMEOUT_SHORT, verify=_ssl_verify())
        response.raise_for_status()
        data = response.json()

        # Extract posts
        posts_data = data.get("data", [])
        if not posts_data:
            return format_response([])

        posts = []
        for item in posts_data:
            fields = item.get("fields", {})
            source_info = fields.get("source", [])
            source_name = source_info[0].get("shortname", "Unknown") if source_info else "Unknown"
            source_type = source_info[0].get("type", "") if source_info else ""

            posts.append({
                "id": item.get("id"),
                "title": fields.get("title", ""),
                "date": fields.get("date", {}).get("created", ""),
                "source": source_name,
                "source_type": source_type,
                "url": fields.get("url", "")
            })

        return format_response(posts)

    except requests.exceptions.RequestException as e:
        return format_error("APIError", f"Failed to fetch blog posts: {str(e)}")
    except Exception as e:
        return format_error("UnexpectedError", str(e))


# ========================================================================
# TOOL 8: Get Recent Updates Summary
# ========================================================================

@tool
def get_recent_updates_summary(days: int = 7) -> str:
    """
    Get summary of recent humanitarian updates and emergencies.
    
    Aggregates disasters and headlines from the last N days.
    
    Args:
        days: Number of days to look back (default 7)
        
    Returns:
        JSON with summary including disasters and headlines
        
    Examples:
        get_recent_updates_summary.invoke({})
        get_recent_updates_summary.invoke({"days": 30})
    """
    try:
        # Validate input
        if not isinstance(days, int) or days < 1:
            return format_error("InvalidInput", "Days must be a positive integer")

        if days > 365:
            return format_error("InvalidInput", "Days must be 365 or less")

        # Get recent disasters
        disasters_body = {
            "limit": 10,
            "sort": ["date:desc"],
            "fields": {
                "include": ["id", "name", "type", "status", "date", "country"]
            }
        }

        disasters_url = f"{RELIEFWEB_DISASTERS_API}?appname={RELIEFWEB_APPNAME}"
        disasters_response = retry_request("post", disasters_url, json=disasters_body, timeout=API_TIMEOUT_SHORT, verify=_ssl_verify())
        disasters_response.raise_for_status()
        disasters_data = disasters_response.json().get("data", [])

        # Get recent headlines
        headlines_body = {
            "preset": "latest",
            "limit": 10,
            "sort": ["date:desc"],
            "fields": {
                "include": ["id", "title", "date", "source", "country"]
            }
        }

        headlines_url = f"{RELIEFWEB_REPORTS_API}?appname={RELIEFWEB_APPNAME}"
        headlines_response = retry_request("post", headlines_url, json=headlines_body, timeout=API_TIMEOUT_SHORT, verify=_ssl_verify())
        headlines_response.raise_for_status()
        headlines_data = headlines_response.json().get("data", [])

        # Format results
        result = {
            "period": f"Last {days} days",
            "disasters": [
                {
                    "name": item.get("fields", {}).get("name", ""),
                    "type": item.get("fields", {}).get("type", ""),
                    "status": item.get("fields", {}).get("status", ""),
                    "date": item.get("fields", {}).get("date", ""),
                    "countries": [c.get("name", "") for c in item.get("fields", {}).get("country", [])]
                }
                for item in disasters_data
            ],
            "major_headlines": [
                {
                    "title": item.get("fields", {}).get("title", ""),
                    "date": item.get("fields", {}).get("date", {}).get("created", ""),
                    "source": item.get("fields", {}).get("source", [{}])[0].get("shortname", "") if item.get("fields", {}).get("source") else "",
                    "countries": [c.get("name", "") for c in item.get("fields", {}).get("country", [])]
                }
                for item in headlines_data
            ]
        }

        return format_response(result)

    except requests.exceptions.RequestException as e:
        return format_error("APIError", f"Failed to fetch updates: {str(e)}")
    except Exception as e:
        return format_error("UnexpectedError", str(e))


# ========================================================================
# TOOL 9: Download and Read PDF
# ========================================================================

@tool
def download_and_read_full_pdf(report_id: int | None = None, ids: list | None = None) -> str:
    """
    Download and read PDF attachment from a report.
    
    Extracts full text from PDF file (max 5MB).
    Use only for detailed PDF analysis.
    
    Args:
        report_id: Report ID that contains the PDF (single report)
        ids: Deprecated - list of report IDs (will use first one)
        
    Returns:
        JSON with PDF content, metadata, and page count
        
    Examples:
        download_and_read_full_pdf.invoke({"report_id": 4192591})
    """
    try:
        # Handle both parameter names - use report_id if provided, fallback to ids
        actual_report_id = report_id
        if actual_report_id is None and ids is not None:
            # If ids is provided as a list, use the first one
            if isinstance(ids, list) and len(ids) > 0:
                actual_report_id = ids[0]

        # Validate input
        if actual_report_id is None:
            return format_error("InvalidInput", "Either report_id or ids must be provided")

        if not isinstance(actual_report_id, int) or actual_report_id < 1:
            return format_error("InvalidInput", "Report ID must be a positive integer")

        # Get report to find PDF attachment
        url = f"{RELIEFWEB_REPORTS_API}/{actual_report_id}?appname={RELIEFWEB_APPNAME}"
        response = retry_request("get", url, timeout=API_TIMEOUT_SHORT, verify=_ssl_verify())
        response.raise_for_status()
        data = response.json()

        fields = data["data"][0]["fields"]

        # Find PDF file in attachments
        files = fields.get("file", [])
        pdf_file = None
        for file_item in files:
            if file_item.get("mimetype", "").lower() == "application/pdf":
                pdf_file = file_item
                break

        if not pdf_file:
            return format_response({"message": "No PDF attachment found in this report"})

        # Get PDF URL and metadata
        pdf_url = pdf_file.get("url", "")
        pdf_filename = pdf_file.get("filename", "report.pdf")
        pdf_size = int(pdf_file.get("filesize", 0))

        # Check file size
        if pdf_size > PDF_SIZE_LIMIT:
            return format_response({
                "error": "PDF file too large to process",
                "report_id": actual_report_id,
                "title": fields.get("title", ""),
                "pdf_size_mb": round(pdf_size / 1_000_000, 2),
                "pdf_size_limit_mb": PDF_SIZE_LIMIT_MB,
                "pdf_url": pdf_url,
                "suggestion": f"PDF exceeds {PDF_SIZE_LIMIT_MB}MB limit. Use get_report_full_content for summary."
            })

        # Download PDF
        pdf_response = retry_request("get", pdf_url, timeout=PDF_DOWNLOAD_TIMEOUT, verify=_ssl_verify())
        pdf_response.raise_for_status()

        # Write to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            tmp_file.write(pdf_response.content)
            tmp_path = tmp_file.name

        try:
            # Extract text from PDF
            reader = PdfReader(tmp_path)
            full_text = ""

            for page_num, page in enumerate(reader.pages, 1):
                page_text = page.extract_text()
                full_text += f"\n\n--- PAGE {page_num} ---\n\n{page_text}"

            # Prepare result
            result = {
                "report_id": actual_report_id,
                "title": fields.get("title", ""),
                "date": fields.get("date", {}).get("created", ""),
                "source": fields.get("source", [{}])[0].get("shortname", "") if fields.get("source") else "",
                "url": fields.get("url", ""),
                "pdf_info": {
                    "filename": pdf_filename,
                    "size_kb": round(pdf_size / 1024, 2),
                    "total_pages": len(reader.pages),
                    "pdf_url": pdf_url
                },
                "full_pdf_content": full_text.strip(),
                "content_length_chars": len(full_text)
            }

            return format_response(result)

        finally:
            # Clean up temporary file
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    except requests.exceptions.RequestException as e:
        return format_error("APIError", f"Failed to download PDF: {str(e)}")
    except Exception as e:
        return format_error("PDFError", f"Failed to read PDF: {str(e)}")


# ========================================================================
# TOOL 10: Ingest Report from API (in-memory, no disk writes)
# ========================================================================

@tool
def ingest_report_from_api(report_id: int) -> str:
    """
    Fetch a report from the ReliefWeb API and ingest it directly into the
    knowledge base (SQLite + ChromaDB vector store) — **no files written to disk**.

    PDFs and HTML content are processed entirely in memory, so this does not
    consume local storage. If the report is already in the knowledge base
    (with PDF), it is skipped automatically.

    Args:
        report_id: Report ID to ingest

    Returns:
        JSON with ingestion results, or "already_ingested" status

    Examples:
        ingest_report_from_api.invoke({"report_id": 4205377})
    """
    try:
        if not isinstance(report_id, int) or report_id < 1:
            return format_error("InvalidInput", "Report ID must be a positive integer")

        # --- dedup check (allow re-ingest if PDF missing) ---
        from .ingest_pipeline import ingest_from_api, is_ingested, is_ingested_with_pdf
        if is_ingested(report_id) and is_ingested_with_pdf(report_id):
            return format_response({
                "status": "already_ingested",
                "report_id": report_id,
                "message": "Report already in knowledge base (with PDF). Skipping.",
            })

        re_ingest = is_ingested(report_id) and not is_ingested_with_pdf(report_id)

        # --- in-memory ingest (no disk writes) ---
        result = ingest_from_api(report_id)
        if re_ingest:
            result["note"] = "Re-ingested to fetch missing PDF content"

        return format_response(result)

    except Exception as e:
        return format_error("IngestError", str(e))


# ========================================================================
# TOOL 11: Ingest Multiple Reports Batch (in-memory, no disk writes)
# ========================================================================

@tool
def ingest_reports_batch(report_ids: list) -> str:
    """
    Fetch and ingest multiple reports from the ReliefWeb API in batch —
    **no files written to disk**. Each report is processed entirely in memory
    and inserted into the knowledge base (SQLite + ChromaDB vector store).

    Reports already in the knowledge base are SKIPPED — no duplicate ingests.
    Only new (unseen) reports are fetched and ingested.

    Args:
        report_ids: List of report IDs to ingest

    Returns:
        JSON summary: ingested (new), skipped (already in DB), errors

    Examples:
        ingest_reports_batch.invoke({"report_ids": [4205377, 4192591, 4100000]})
    """
    try:
        if not isinstance(report_ids, list) or len(report_ids) == 0:
            return format_error("InvalidInput", "report_ids must be a non-empty list")

        # Coerce string IDs to int (LLMs often pass strings)
        try:
            report_ids = [int(rid) for rid in report_ids]
        except (ValueError, TypeError) as e:
            return format_error("InvalidInput", f"All report IDs must be integers: {e}")

        for rid in report_ids:
            if rid < 1:
                return format_error("InvalidInput", f"Invalid report ID: {rid}")

        from .ingest_pipeline import ingest_from_api, is_ingested, is_ingested_with_pdf

        results = {"ingested": [], "skipped": [], "errors": []}

        for rid in report_ids:
            # --- dedup check (allow re-ingest if PDF missing) ---
            if is_ingested(rid) and is_ingested_with_pdf(rid):
                results["skipped"].append({"report_id": rid, "reason": "already_in_db"})
                continue

            re_ingest = is_ingested(rid) and not is_ingested_with_pdf(rid)

            # --- in-memory ingest (no disk writes) ---
            try:
                ingest_result = ingest_from_api(rid)
            except Exception as e:
                results["errors"].append({"report_id": rid, "error": str(e)})
                continue

            if ingest_result.get("success"):
                entry = {
                    "report_id":    rid,
                    "chunks_added": ingest_result.get("chunks_added", 0),
                    "has_pdf":      ingest_result.get("has_pdf", False),
                    "has_content":  ingest_result.get("has_content", False),
                }
                if re_ingest:
                    entry["note"] = "Re-ingested to fetch missing PDF content"
                results["ingested"].append(entry)
            else:
                results["errors"].append({
                    "report_id": rid,
                    "error": ingest_result.get("error", "unknown"),
                })

        results["summary"] = {
            "total": len(report_ids),
            "ingested": len(results["ingested"]),
            "skipped_already_in_db": len(results["skipped"]),
            "errors": len(results["errors"]),
        }

        return format_response(results)

    except Exception as e:
        return format_error("IngestError", str(e))


# ========================================================================
# TOOL 12: Convert Report PDF to Markdown
# ========================================================================

@tool
def convert_report_to_markdown(report_id: int, output_dir: str = "output") -> str:
    """
    Download and convert a report PDF to Markdown format.
    
    Uses Docling to extract structured content from PDF and save as Markdown.
    Perfect for agent reading and analysis.
    
    Args:
        report_id: Report ID to convert
        output_dir: Directory to save Markdown file (default: output/)
        
    Returns:
        JSON with Markdown file path and conversion status
        
    Examples:
        convert_report_to_markdown.invoke({"report_id": 4205377})
    """
    try:
        if not isinstance(report_id, int) or report_id < 1:
            return format_error("InvalidInput", "Report ID must be a positive integer")

        converter = ReportFormatConverter()
        result = converter.download_and_convert_report(
            report_id,
            output_dir,
            formats=['markdown']
        )

        return format_response(result)

    except Exception as e:
        return format_error("ConversionError", str(e))


# ========================================================================
# TOOL 13: Convert Report PDF to JSON
# ========================================================================

@tool
def convert_report_to_json(report_id: int, output_dir: str = "output") -> str:
    """
    Download and convert a report PDF to JSON structured format.
    
    Uses Docling to extract content blocks and metadata, saves as JSON.
    Ideal for programmatic processing and parsing.
    
    Args:
        report_id: Report ID to convert
        output_dir: Directory to save JSON file (default: output/)
        
    Returns:
        JSON with structured file path and conversion status
        
    Examples:
        convert_report_to_json.invoke({"report_id": 4205377})
    """
    try:
        if not isinstance(report_id, int) or report_id < 1:
            return format_error("InvalidInput", "Report ID must be a positive integer")

        converter = ReportFormatConverter()
        result = converter.download_and_convert_report(
            report_id,
            output_dir,
            formats=['json']
        )

        return format_response(result)

    except Exception as e:
        return format_error("ConversionError", str(e))


# ========================================================================
# TOOL 14: Convert Multiple Reports to Markdown/JSON
# ========================================================================

@tool
def convert_reports_batch(report_ids: list, output_dir: str = "output", format_type: str = "both") -> str:
    """
    Batch download and convert multiple reports to Markdown and/or JSON.
    
    Efficiently converts multiple reports for agent consumption.
    Easy reading and parsing of humanitarian data.
    
    Args:
        report_ids: List of report IDs to convert
        output_dir: Base directory for outputs (default: output/)
        format_type: 'markdown', 'json', or 'both'
        
    Returns:
        JSON summary with conversion results for each report
        
    Examples:
        convert_reports_batch.invoke({"report_ids": [4205377, 4192591]})
        convert_reports_batch.invoke({"report_ids": [4205377, 4205348], "format_type": "markdown"})
    """
    try:
        if not isinstance(report_ids, list) or len(report_ids) == 0:
            return format_error("InvalidInput", "report_ids must be a non-empty list")

        # Validate format
        if format_type not in ['markdown', 'json', 'both']:
            return format_error("InvalidInput", "format_type must be 'markdown', 'json', or 'both'")

        # Validate IDs
        for rid in report_ids:
            if not isinstance(rid, int) or rid < 1:
                return format_error("InvalidInput", f"Invalid report ID: {rid}")

        formats = {
            'markdown': ['markdown'],
            'json': ['json'],
            'both': ['markdown', 'json']
        }[format_type]

        converter = ReportFormatConverter()
        summary = converter.batch_convert_reports(
            report_ids,
            output_dir,
            formats
        )

        return format_response(summary)

    except Exception as e:
        return format_error("ConversionError", str(e))



# ========================================================================
# TOOL 15: Search Knowledge Base (Vector DB)
# ========================================================================

@tool
def search_knowledge_base(
    query: str,
    n_results: int = 5,
    country: str | None = None,
    source_org: str | None = None,
) -> str:
    """
    Search the local vector knowledge base (ChromaDB) for relevant content
    from previously downloaded reports using semantic similarity.

    Use this BEFORE calling search_sitreps when the user asks a question
    that might be answered from already-downloaded data.

    Args:
        query: Natural language question or topic (e.g., 'Sudan flooding health impact')
        n_results: Number of relevant chunks to return (default 5)
        country: Optional country filter — exact match on primary country
                 (e.g., 'Sudan', 'Iran', 'Pakistan')
        source_org: Optional source org filter (e.g., 'UNHCR', 'WHO', 'WFP')

    Returns:
        JSON list of relevant chunks ranked by similarity, each with:
        report_id, title, date, source, countries, chunk_preview, similarity score

    Examples:
        search_knowledge_base.invoke({"query": "health situation Sudan"})
        search_knowledge_base.invoke({"query": "displacement figures", "country": "Sudan"})
        search_knowledge_base.invoke({"query": "food insecurity", "source_org": "WFP"})
    """
    try:
        from .vector_store import CHROMA_DIR, VectorStore
        vs = VectorStore(CHROMA_DIR)
        stats = vs.get_stats()

        if stats["total_chunks"] == 0:
            return format_response({
                "message": "Knowledge base is empty. Download some reports first.",
                "results": [],
            })

        results = vs.search(query, n_results=n_results, country=country, source=source_org)
        return format_response({"total_chunks_in_db": stats["total_chunks"], "results": results})

    except Exception as e:
        return format_error("SearchError", str(e))


# ========================================================================
# TOOL 16: Parse ReliefWeb URL
# ========================================================================

@tool
def parse_reliefweb_url(url: str) -> str:
    """
    Parse a ReliefWeb URL and fetch the report metadata and summary.
    Supports multiple URL formats from reliefweb.int.

    Args:
        url: A ReliefWeb URL, e.g.:
             - https://reliefweb.int/report/syrian-arab-republic/north-west-syria-situation-report-no-42
             - https://reliefweb.int/node/4205377
             - https://api.reliefweb.int/v2/reports/4205377

    Returns:
        JSON with report id, title, date, source, url, body excerpt

    Examples:
        parse_reliefweb_url(url="https://reliefweb.int/report/syrian-arab-republic/north-west-syria-situation-report-no-42")
        parse_reliefweb_url(url="https://reliefweb.int/node/4205377")
    """
    try:
        url = url.strip()
        report_id = None

        # Pattern 1: /node/<id>
        m = re.search(r'reliefweb\.int/node/(\d+)', url)
        if m:
            report_id = int(m.group(1))

        # Pattern 2: api.reliefweb.int/v2/reports/<id>
        if not report_id:
            m = re.search(r'api\.reliefweb\.int/v\d+/reports/(\d+)', url)
            if m:
                report_id = int(m.group(1))

        # Pattern 3: reliefweb.int/report/<country>/<slug>  — resolve via search
        if not report_id:
            m = re.search(r'reliefweb\.int/report/([^/]+)/([^/?#]+)', url)
            if m:
                slug = m.group(2).replace('-', ' ')
                # Search by slug keywords to find the report
                body = {
                    "preset": "latest",
                    "limit": 3,
                    "query": {"value": slug},
                    "fields": {"include": ["id", "title", "date", "source", "url", "body-html", "country"]}
                }
                api_url = f"{RELIEFWEB_REPORTS_API}?appname={RELIEFWEB_APPNAME}"
                resp = retry_request("post", api_url, json=body, timeout=API_TIMEOUT_SHORT, verify=_ssl_verify())
                resp.raise_for_status()
                data = resp.json().get("data", [])
                if data:
                    fields = data[0].get("fields", {})
                    body_text = clean_html_body(fields.get("body-html", ""))
                    source_info = fields.get("source", [])
                    source_name = source_info[0].get("shortname", "Unknown") if source_info else "Unknown"
                    countries = [c.get("name", "") for c in fields.get("country", [])]
                    return format_response({
                        "id": data[0].get("id"),
                        "title": fields.get("title", ""),
                        "date": fields.get("date", {}).get("original", ""),
                        "source": source_name,
                        "countries": countries,
                        "url": fields.get("url", ""),
                        "body_excerpt": truncate_text(body_text, 1000),
                    })
                return format_error("NotFound", f"Could not find report matching URL slug: {slug}")

        if not report_id:
            return format_error("InvalidInput", f"Could not parse report ID from URL: {url}")

        # Fetch by ID
        api_url = f"{RELIEFWEB_REPORTS_API}/{report_id}?appname={RELIEFWEB_APPNAME}"
        resp = retry_request("get", api_url, timeout=API_TIMEOUT_SHORT, verify=_ssl_verify())
        resp.raise_for_status()
        data = resp.json().get("data", [])

        if not data:
            return format_error("NotFound", f"Report {report_id} not found")

        fields = data[0].get("fields", {})
        body_text = clean_html_body(fields.get("body-html", ""))
        source_info = fields.get("source", [])
        source_name = source_info[0].get("shortname", "Unknown") if source_info else "Unknown"
        countries = [c.get("name", "") for c in fields.get("country", [])]

        return format_response({
            "id": report_id,
            "title": fields.get("title", ""),
            "date": fields.get("date", {}).get("original", ""),
            "source": source_name,
            "countries": countries,
            "url": fields.get("url", ""),
            "body_excerpt": truncate_text(body_text, 1000),
        })

    except requests.exceptions.RequestException as e:
        return format_error("APIError", f"Failed to fetch report: {str(e)}")
    except Exception as e:
        return format_error("UnexpectedError", str(e))


# ========================================================================
# TOOL 17: Search Sources / Organizations
# ========================================================================

@tool
def search_sources(
    query: str,
    country: str | None = None,
    org_type: str | None = None,
    limit: int = 10,
) -> str:
    """
    Search for organizations/sources on ReliefWeb by name, country, or type.
    Use this to discover the correct shortname for an organization.

    Args:
        query: Organization name or keyword (e.g., 'MSF', 'Red Crescent', 'Doctors Without Borders')
        country: Filter sources by country of operation (e.g., 'Turkey', 'Syria')
        org_type: Organization type filter. Values: 'International NGO', 'National NGO',
                  'Government', 'International Organization', 'United Nations',
                  'Academic and Research Institution', 'Donor', 'Media',
                  'Red Cross / Red Crescent', 'Other'
        limit: Max results (default 10)

    Returns:
        JSON list of sources with name, shortname, type, homepage, country

    Examples:
        search_sources(query="Red Crescent")
        search_sources(query="MSF", org_type="International NGO")
        search_sources(query="health", country="Turkey", org_type="Government")
    """
    try:
        filters = []

        if country:
            normalized = normalize_country_name(country)
            filters.append({"field": "country.name", "value": normalized})

        if org_type:
            filters.append({"field": "type.name", "value": org_type})

        body = {
            "limit": min(limit, 50),
            "query": {"value": str(query).strip()},
            "fields": {
                "include": ["id", "name", "shortname", "type", "homepage", "country"]
            }
        }

        if len(filters) == 1:
            body["filter"] = filters[0]
        elif len(filters) > 1:
            body["filter"] = {"operator": "AND", "conditions": filters}

        api_url = f"{RELIEFWEB_SOURCES_API}?appname={RELIEFWEB_APPNAME}"
        resp = retry_request("post", api_url, json=body, timeout=API_TIMEOUT_SHORT, verify=_ssl_verify())
        resp.raise_for_status()
        data = resp.json().get("data", [])

        sources = []
        for item in data:
            fields = item.get("fields", {})
            type_info = fields.get("type", [])
            type_name = type_info[0].get("name", "") if isinstance(type_info, list) and type_info else (type_info.get("name", "") if isinstance(type_info, dict) else "")
            countries = [c.get("name", "") for c in fields.get("country", [])] if isinstance(fields.get("country"), list) else []
            sources.append({
                "id": item.get("id"),
                "name": fields.get("name", ""),
                "shortname": fields.get("shortname", ""),
                "type": type_name,
                "homepage": fields.get("homepage", ""),
                "countries": countries,
            })

        return format_response(sources)

    except requests.exceptions.RequestException as e:
        return format_error("APIError", f"Failed to search sources: {str(e)}")
    except Exception as e:
        return format_error("UnexpectedError", str(e))


# ========================================================================
# TOOL COLLECTION FOR AGENT INTEGRATION
# ========================================================================

# All tools exported for use with LangChain agents
mcp_langchain_tools = [
    search_sitreps,
    get_sitrep_summary,
    get_report_full_content,
    search_disasters,
    search_disasters_by_date,
    get_latest_headlines,
    get_latest_blog_posts,
    get_recent_updates_summary,
    download_and_read_full_pdf,
    ingest_report_from_api,
    ingest_reports_batch,
    convert_report_to_markdown,
    convert_report_to_json,
    convert_reports_batch,
    search_knowledge_base,
    parse_reliefweb_url,
    search_sources,
]

# Alternative: Dictionary mapping for easier access
tools_dict = {tool.name: tool for tool in mcp_langchain_tools}

__all__ = [
    "search_sitreps",
    "get_sitrep_summary",
    "get_report_full_content",
    "search_disasters",
    "search_disasters_by_date",
    "get_latest_headlines",
    "get_latest_blog_posts",
    "get_recent_updates_summary",
    "download_and_read_full_pdf",
    "ingest_report_from_api",
    "ingest_reports_batch",
    "convert_report_to_markdown",
    "convert_report_to_json",
    "convert_reports_batch",
    "search_knowledge_base",
    "parse_reliefweb_url",
    "search_sources",
    "mcp_langchain_tools",
    "tools_dict"
]
