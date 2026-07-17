"""
blueprints/news_bp.py — Flask Blueprint for /api/news/* routes.

Extracted from server.py lines 2703–2821.
All shared helpers (DB functions, state dicts, etc.) are accessed
via `import server` to avoid circular imports and duplication.
"""

import logging

from flask import Blueprint, jsonify, request

from auth import require_admin, require_auth
from reliefweb_api.news_tools import get_news_client

logger = logging.getLogger(__name__)

news_bp = Blueprint("news", __name__, url_prefix="/api/news")


# ─── News API health check ──────────────────────────────────────────────────

@news_bp.route("/health")
def api_news_health():
    """News API connectivity check. No auth required."""
    news = get_news_client()
    if not news:
        return jsonify({
            "status": "not_configured",
            "message": "NEWS_API_KEY not set. Set it in .env to enable news data.",
        }), 503
    return jsonify({
        "status": "ok",
        "base_url": news.base_url,
        "cache_stats": news.cache.stats(),
    })


# ─── Search ─────────────────────────────────────────────────────────────────

@news_bp.route("/search")
@require_auth
def api_news_search():
    """Search news articles by keyword, country, language, and date range.
    Query params: q, country, language, from, to, sort_by, page_size
    """
    news = get_news_client()
    if not news:
        return jsonify({"error": "News client not configured"}), 503

    query = request.args.get("q", "")
    if not query:
        return jsonify({"error": "Missing required parameter: q"}), 400

    country = request.args.get("country")
    language = request.args.get("language")
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    sort_by = request.args.get("sort_by", "relevancy")
    page_size = request.args.get("page_size", 10, type=int)

    result = news.search_everything_sync(
        query=query,
        country=country,
        language=language,
        from_date=from_date,
        to_date=to_date,
        sort_by=sort_by,
        page_size=min(page_size, 50),
    )
    return jsonify(result.to_dict())


# ─── Headlines ──────────────────────────────────────────────────────────────

@news_bp.route("/headlines")
@require_auth
def api_news_headlines():
    """Get top/breaking headlines by country and category.
    Query params: country, category, language, page_size
    """
    news = get_news_client()
    if not news:
        return jsonify({"error": "News client not configured"}), 503

    country = request.args.get("country")
    category = request.args.get("category")
    language = request.args.get("language")
    page_size = request.args.get("page_size", 10, type=int)

    result = news.get_top_headlines_sync(
        country=country,
        category=category,
        language=language,
        page_size=min(page_size, 50),
    )
    return jsonify(result.to_dict())


# ─── Sources ────────────────────────────────────────────────────────────────

@news_bp.route("/sources")
@require_auth
def api_news_sources():
    """List available news sources by category, language, country.
    Query params: category, language, country
    """
    news = get_news_client()
    if not news:
        return jsonify({"error": "News client not configured"}), 503

    category = request.args.get("category")
    language = request.args.get("language")
    country = request.args.get("country")

    result = news.get_sources_sync(
        category=category,
        language=language,
        country=country,
    )
    return jsonify(result.to_dict())


# ─── Cache management (admin) ───────────────────────────────────────────────

@news_bp.route("/cache/stats")
@require_admin
def api_news_cache_stats():
    """Get News cache statistics (admin only)."""
    news = get_news_client()
    if not news:
        return jsonify({"error": "News client not configured"}), 503
    return jsonify(news.cache.stats())


@news_bp.route("/cache/clear", methods=["POST"])
@require_admin
def api_news_cache_clear():
    """Clear News cache (admin only)."""
    news = get_news_client()
    if not news:
        return jsonify({"error": "News client not configured"}), 503
    news.cache.clear()
    return jsonify({"status": "cache_cleared"})