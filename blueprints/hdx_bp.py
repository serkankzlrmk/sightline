"""
blueprints/hdx_bp.py — HDX (Humanitarian Data Exchange) routes extracted from server.py.

Flask Blueprint for all /api/hdx/* endpoints.

Register in server.py with:
    from blueprints.hdx_bp import hdx_bp
    app.register_blueprint(hdx_bp)
"""

import logging

from flask import Blueprint, jsonify, request

from auth import require_admin, require_role
from reliefweb_api.hdx_tools import get_hdx_client

logger = logging.getLogger(__name__)

hdx_bp = Blueprint("hdx", __name__, url_prefix="/api/hdx")


# =============================================================================
# ROUTES — HDX (Humanitarian Data Exchange)
# =============================================================================


@hdx_bp.route("/health")
def api_hdx_health():
    """HDX connectivity check. No auth required — just checks if client is initialized."""
    hdx = get_hdx_client()
    if not hdx:
        return jsonify(
            {
                "status": "not_configured",
                "message": "HDX_APP_IDENTIFIER not set. Set it in .env to enable HDX data.",
            }
        ), 503
    return jsonify(
        {
            "status": "ok",
            "base_url": hdx.base_url,
            "cache_stats": hdx.cache.stats(),
        }
    )


@hdx_bp.route("/availability/<country_code>")
@require_role("premium")
def api_hdx_availability(country_code):
    """Check what HDX data categories are available for a country."""
    hdx = get_hdx_client()
    if not hdx:
        return jsonify({"error": "HDX client not configured"}), 503
    result = hdx.get_data_availability_sync(location_code=country_code.upper())
    return jsonify(result.to_dict())


@hdx_bp.route("/overview/<country_code>")
@require_role("premium")
def api_hdx_overview(country_code):
    """Get comprehensive humanitarian data overview for a country (9 parallel endpoints)."""
    hdx = get_hdx_client()
    if not hdx:
        return jsonify({"error": "HDX client not configured"}), 503
    result = hdx.get_country_overview_sync(country_code.upper())
    return jsonify({k: v.to_dict() for k, v in result.items()})


@hdx_bp.route("/refugees/<country_code>")
@require_role("premium")
def api_hdx_refugees(country_code):
    """Get refugee/persons of concern data for a country."""
    hdx = get_hdx_client()
    if not hdx:
        return jsonify({"error": "HDX client not configured"}), 503
    limit = request.args.get("limit", 10, type=int)
    result = hdx.get_refugees_sync(location_code=country_code.upper(), limit=min(limit, 50))
    return jsonify(result.to_dict())


@hdx_bp.route("/idps/<country_code>")
@require_role("premium")
def api_hdx_idps(country_code):
    """Get internally displaced persons (IDP) data for a country."""
    hdx = get_hdx_client()
    if not hdx:
        return jsonify({"error": "HDX client not configured"}), 503
    limit = request.args.get("limit", 10, type=int)
    result = hdx.get_idps_sync(location_code=country_code.upper(), limit=min(limit, 50))
    return jsonify(result.to_dict())


@hdx_bp.route("/funding/<country_code>")
@require_role("premium")
def api_hdx_funding(country_code):
    """Get humanitarian funding data for a country."""
    hdx = get_hdx_client()
    if not hdx:
        return jsonify({"error": "HDX client not configured"}), 503
    limit = request.args.get("limit", 10, type=int)
    result = hdx.get_funding_sync(location_code=country_code.upper(), limit=min(limit, 50))
    return jsonify(result.to_dict())


@hdx_bp.route("/conflict/<country_code>")
@require_role("premium")
def api_hdx_conflict(country_code):
    """Get conflict events data (ACLED) for a country."""
    hdx = get_hdx_client()
    if not hdx:
        return jsonify({"error": "HDX client not configured"}), 503
    limit = request.args.get("limit", 10, type=int)
    result = hdx.get_conflict_events_sync(location_code=country_code.upper(), limit=min(limit, 50))
    return jsonify(result.to_dict())


@hdx_bp.route("/cache/stats")
@require_admin
def api_hdx_cache_stats():
    """Get HDX cache statistics (admin only)."""
    hdx = get_hdx_client()
    if not hdx:
        return jsonify({"error": "HDX client not configured"}), 503
    return jsonify(hdx.cache.stats())


@hdx_bp.route("/cache/clear", methods=["POST"])
@require_admin
def api_hdx_cache_clear():
    """Clear HDX cache (admin only)."""
    hdx = get_hdx_client()
    if not hdx:
        return jsonify({"error": "HDX client not configured"}), 503
    hdx.cache.clear()
    return jsonify({"status": "cache_cleared"})
