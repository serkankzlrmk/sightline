"""
News Tools — LangChain @tool definitions for Sightline.

These tools give the agent access to world news data via NewsAPI.org.
No MCP server dependency — direct HTTP client.

3 tools:
  1. news_search     — Search news articles by keyword, country, language, date range
  2. news_headlines   — Get top/breaking headlines by country and category
  3. news_sources     — List available news sources by category, language, country

Usage:
  The agent automatically uses these tools when the user asks about
  current news, media coverage, or recent events. ReliefWeb tools
  are for humanitarian reports; HDX tools for quantitative data;
  News tools for current news coverage and media perspective.
"""

import logging
from typing import Optional

from langchain.tools import tool

from reliefweb_api.news_client import NewsClient
from reliefweb_api.reliefweb_utils import format_response, format_error

logger = logging.getLogger(__name__)

_news_client: Optional[NewsClient] = None


def init_news_tools(api_key: str = "", base_url: str = "",
                    timeout: float = 15.0,
                    rate_limit_requests: int = 80,
                    rate_limit_period: float = 86400.0,
                    cache_ttl: int = 3600) -> bool:
    """Initialize the global News client singleton.

    Called from server.py at startup. Returns True if initialized successfully,
    False if NEWS_API_KEY is not set (tools will return error messages).
    """
    global _news_client
    try:
        _news_client = NewsClient(
            api_key=api_key,
            base_url=base_url or "https://newsapi.org/v2",
            timeout=timeout,
            rate_limit_requests=rate_limit_requests,
            rate_limit_period=rate_limit_period,
            cache_ttl=cache_ttl,
        )
        logger.info("News client initialized successfully")
        return True
    except Exception as e:
        logger.warning(f"News client initialization failed: {e}")
        _news_client = None
        return False


def get_news_client() -> Optional[NewsClient]:
    """Get the global News client singleton."""
    return _news_client


def _news_result_to_json(result) -> str:
    """Convert NewsResult to JSON string for agent tool response."""
    if result is None:
        return format_error("ServiceUnavailable",
                            "News client is not initialized. Set NEWS_API_KEY in .env")

    if hasattr(result, "to_dict"):
        return format_response(result.to_dict())

    return format_response(result)


# ══════════════════════════════════════════════════════════════════════════════
# News Tool Definitions
# ══════════════════════════════════════════════════════════════════════════════

@tool
def news_search(query: str, country: Optional[str] = None,
                language: Optional[str] = None,
                from_date: Optional[str] = None, to_date: Optional[str] = None,
                sort_by: str = "relevancy", limit: int = 10) -> str:
    """Search global news articles by keyword, country, language, and date range.

    Use this for finding recent news coverage about humanitarian crises,
    disasters, conflicts, and displacement events. Returns article titles,
    descriptions, sources, URLs, and publication dates.

    This is best for: "latest news about X", "what happened recently in Y",
    "media coverage of crisis Z".

    Country codes: ISO 3166-1 alpha-2 (e.g., 'sy' for Syria, 'tr' for Turkey,
    'af' for Afghanistan, 'ua' for Ukraine, 'sd' for Sudan). Also accepts
    alpha-3 codes like 'SYR', 'AFG' which are automatically converted.

    Args:
        query: Search keywords (e.g., "earthquake Turkey", "refugee crisis Sudan",
               "humanitarian aid Afghanistan")
        country: ISO 3166-1 country code — alpha-2 ('sy') or alpha-3 ('SYR').
                Filters sources to those relevant to the country.
        language: ISO 639-1 language code (e.g., 'en', 'ar', 'fr', 'es', 'tr')
        from_date: Start date in YYYY-MM-DD format (default: 30 days ago)
        to_date: End date in YYYY-MM-DD format (default: today)
        sort_by: Sort order — 'relevancy', 'popularity', or 'publishedAt'
        limit: Maximum number of results (default 10, max 50)
    """
    news = get_news_client()
    if not news:
        return format_error("ServiceUnavailable",
                            "News client is not initialized. Set NEWS_API_KEY in .env")
    try:
        result = news.search_everything_sync(
            query=query,
            country=country,
            language=language,
            from_date=from_date,
            to_date=to_date,
            sort_by=sort_by,
            page_size=min(limit, 50),
        )
        return _news_result_to_json(result)
    except Exception as e:
        logger.error(f"News search error for '{query}': {e}")
        return format_error("NewsError", f"Failed to search news for '{query}': {str(e)}")


@tool
def news_headlines(country: Optional[str] = None,
                    category: Optional[str] = None,
                    language: Optional[str] = None,
                    limit: int = 10) -> str:
    """Get top/breaking news headlines by country and category.

    Use this for getting a quick overview of the latest news in a country
    or about a topic. Returns headlines with source, description, and URL.

    Best for: "what's happening in Syria right now", "latest crisis headlines",
    "top news from Ukraine", "current events in Sudan".

    Country codes: ISO 3166-1 alpha-2 (e.g., 'sy', 'tr', 'af', 'ua', 'sd').
    Also accepts alpha-3 codes like 'SYR', 'AFG' which are automatically converted.

    Categories: general, business, entertainment, health, science, sports, technology

    Args:
        country: ISO 3166-1 country code — alpha-2 ('sy') or alpha-3 ('SYR')
        category: News category — 'general', 'business', 'entertainment',
                 'health', 'science', 'sports', 'technology'
        language: ISO 639-1 language code (e.g., 'en', 'ar', 'fr')
        limit: Maximum number of headlines (default 10, max 50)
    """
    news = get_news_client()
    if not news:
        return format_error("ServiceUnavailable",
                            "News client is not initialized. Set NEWS_API_KEY in .env")
    try:
        result = news.get_top_headlines_sync(
            country=country,
            category=category,
            language=language,
            page_size=min(limit, 50),
        )
        return _news_result_to_json(result)
    except Exception as e:
        logger.error(f"News headlines error: {e}")
        return format_error("NewsError", f"Failed to get headlines: {str(e)}")


@tool
def news_sources(category: Optional[str] = None,
                  language: Optional[str] = None,
                  country: Optional[str] = None) -> str:
    """List available news sources filtered by category, language, and country.

    Use this to discover which news sources cover a specific country or topic.
    Returns source names, descriptions, URLs, and categories.

    Best for: "what news sources cover Afghanistan", "English language sources",
    "health news sources".

    Country codes: ISO 3166-1 alpha-2 (e.g., 'sy', 'tr', 'af', 'ua', 'sd').
    Also accepts alpha-3 codes like 'SYR', 'AFG' which are automatically converted.

    Args:
        category: News category — 'general', 'business', 'entertainment',
                 'health', 'science', 'sports', 'technology'
        language: ISO 639-1 language code (e.g., 'en', 'ar', 'fr', 'es', 'tr')
        country: ISO 3166-1 country code — alpha-2 ('sy') or alpha-3 ('SYR')
    """
    news = get_news_client()
    if not news:
        return format_error("ServiceUnavailable",
                            "News client is not initialized. Set NEWS_API_KEY in .env")
    try:
        result = news.get_sources_sync(
            category=category,
            language=language,
            country=country,
        )
        return _news_result_to_json(result)
    except Exception as e:
        logger.error(f"News sources error: {e}")
        return format_error("NewsError", f"Failed to get sources: {str(e)}")


# ── Tool list for agent registration ─────────────────────────────────────────

NEWS_TOOLS = [
    news_search,
    news_headlines,
    news_sources,
]