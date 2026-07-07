"""
ReliefWeb API Integration Package
Tools and utilities for querying humanitarian data from ReliefWeb
"""

from .download_manager import DownloadManager, get_download_manager
from .pdf_converter import PDFConverter, ReportFormatConverter
from .reliefweb import (
    convert_report_to_json,
    convert_report_to_markdown,
    convert_reports_batch,
    download_and_read_full_pdf,
    get_latest_blog_posts,
    get_latest_headlines,
    get_recent_updates_summary,
    get_report_full_content,
    get_sitrep_summary,
    ingest_report_from_api,
    ingest_reports_batch,
    mcp_langchain_tools,
    parse_reliefweb_url,
    search_disasters,
    search_disasters_by_date,
    search_knowledge_base,
    search_sitreps,
    search_sources,
    tools_dict,
)

__all__ = [
    # Tools
    "search_sitreps",
    "get_sitrep_summary",
    "get_report_full_content",
    "search_disasters",
    "search_disasters_by_date",
    "get_latest_headlines",
    "get_latest_blog_posts",
    "get_recent_updates_summary",
    "download_and_read_full_pdf",
    "download_report_to_folder",
    "download_reports_batch",
    "convert_report_to_markdown",
    "convert_report_to_json",
    "convert_reports_batch",
    "search_knowledge_base",
    "parse_reliefweb_url",
    "search_sources",
    # Collections
    "mcp_langchain_tools",
    "tools_dict",
    # Managers
    "DownloadManager",
    "get_download_manager",
    "PDFConverter",
    "ReportFormatConverter",
]
