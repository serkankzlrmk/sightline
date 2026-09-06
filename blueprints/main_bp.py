"""
blueprints/main_bp.py — Landing page, SPA entry, and health check.

Routes:
    /            → Landing page (public)
    /app         → SPA entry point (requires auth via frontend)
    /api/health  → Health check (unauthenticated, for Docker healthcheck)
"""

import json
import sqlite3
from pathlib import Path

from flask import Blueprint, jsonify, render_template, send_from_directory

from config import (
    _LLM_API_KEY,
    BASE_DIR,
    CONTACT_EMAIL,
    DB_PATH,
    SITE_URL,
)
from reliefweb_api.hdx_tools import get_hdx_client
from reliefweb_api.news_tools import get_news_client

main_bp = Blueprint("main", __name__)

# ── Frontend cache-busting version ────────────────────────────────────────────
# After `npm run build`, static/dist/version.json holds content hashes for the
# minified bundles. Served as ?v=<hash> so browsers cache aggressively and only
# re-download when the bundle actually changes (previously v=timestamp forced a
# full re-download on EVERY page load).
_VERSION_CACHE: dict = {}


def _frontend_version() -> str:
    """Content hash of the current frontend bundle (from dist/version.json)."""
    if "v" in _VERSION_CACHE:
        return _VERSION_CACHE["v"]
    try:
        vf = BASE_DIR / "static" / "dist" / "version.json"
        if vf.exists():
            data = json.loads(vf.read_text())
            _VERSION_CACHE["v"] = data.get("app", "0") + data.get("css", "0")
            return _VERSION_CACHE["v"]
    except Exception:
        pass
    # Fallback: timestamp (dev, before first build)
    return str(int(__import__("time").time()))


@main_bp.route("/")
def landing():
    from config import GOOGLE_ANALYTICS_ID

    return render_template(
        "landing.html",
        v=_frontend_version(),
        analytics_id=GOOGLE_ANALYTICS_ID,
        site_url=SITE_URL,
    )


@main_bp.route("/googleb68b482e730d338b.html")
def google_verification():
    """Google Search Console domain verification file (root path)."""
    return send_from_directory(BASE_DIR / "static", "googleb68b482e730d338b.html")


@main_bp.route("/app")
def spa():
    from config import GOOGLE_ANALYTICS_ID, CARTO_API_KEY

    return render_template(
        "index.html",
        v=_frontend_version(),
        contact_email=CONTACT_EMAIL,
        analytics_id=GOOGLE_ANALYTICS_ID,
        carto_api_key=CARTO_API_KEY,
    )


@main_bp.route("/privacy")
def privacy_policy():
    from config import (
        GOOGLE_ADSENSE_CLIENT,
        GOOGLE_ADSENSE_CMP_READY,
        GOOGLE_ADSENSE_SLOT_ID,
        GOOGLE_ANALYTICS_ID,
    )

    return render_template(
        "legal.html",
        document="privacy",
        page_title="Privacy Policy",
        canonical=f"{SITE_URL}/privacy",
        contact_email=CONTACT_EMAIL,
        analytics_id=GOOGLE_ANALYTICS_ID,
        analytics_enabled=bool(GOOGLE_ANALYTICS_ID),
        ads_enabled=bool(GOOGLE_ADSENSE_CLIENT and GOOGLE_ADSENSE_SLOT_ID and GOOGLE_ADSENSE_CMP_READY),
    )


@main_bp.route("/terms")
def terms_of_use():
    from config import GOOGLE_ANALYTICS_ID

    return render_template(
        "legal.html",
        document="terms",
        page_title="Terms of Use",
        canonical=f"{SITE_URL}/terms",
        contact_email=CONTACT_EMAIL,
        analytics_id=GOOGLE_ANALYTICS_ID,
        analytics_enabled=bool(GOOGLE_ANALYTICS_ID),
        ads_enabled=False,
    )


@main_bp.route("/api/health")
def health():
    """Enhanced health check — verifies DB, vector store, and LLM config.

    Security: this endpoint is unauthenticated, so it returns only boolean
    status flags — no model names, no release info, no dev_mode flag (which
    would be a banner saying 'auth is disabled here').
    """
    from config import CHROMA_DIR

    checks = {"status": "ok", "version": "1.3"}

    # SQLite DB check
    db_ok = False
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("SELECT 1")
        conn.close()
        db_ok = True
    except Exception:
        pass
    checks["db"] = db_ok

    # ChromaDB is the only live vector store.
    checks["vector"] = Path(str(CHROMA_DIR)).exists()

    # LLM config check (boolean only — no model/provider name leak)
    checks["llm"] = bool(_LLM_API_KEY)

    # HDX/News checks (boolean only)
    checks["hdx"] = get_hdx_client() is not None
    checks["news"] = get_news_client() is not None

    # Data freshness is observable but non-critical for process health. A
    # stale source snapshot should alert operators without restarting the app.
    try:
        from reliefweb_api.ingest_status import database_freshness

        checks["data_fresh"] = database_freshness()["is_fresh"]
    except Exception:
        checks["data_fresh"] = False

    # Overall status: ok only if all critical checks pass
    all_ok = db_ok and checks.get("vector", False) and checks["llm"]
    checks["status"] = "ok" if all_ok else "degraded"

    code = 200 if all_ok else 503
    return jsonify(checks), code
