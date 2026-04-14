"""
ReliefWeb API Integration Package
Tools and utilities for querying humanitarian data from ReliefWeb
"""

from .reliefweb import (
    search_sitreps,
    get_sitrep_summary,
    get_report_full_content,
    search_disasters,
    search_disasters_by_date,
    get_latest_headlines,
    get_latest_blog_posts,
    get_recent_updates_summary,
    download_and_read_full_pdf,
    download_report_to_folder,
    download_reports_batch,
    convert_report_to_markdown,
    convert_report_to_json,
    convert_reports_batch,
    search_knowledge_base,
    parse_reliefweb_url,
    search_sources,
    mcp_langchain_tools,
    tools_dict,
)

from .download_manager import DownloadManager, get_download_manager
from .pdf_converter import PDFConverter, ReportFormatConverter

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
