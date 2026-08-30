"""
server.py — Unified Flask server for ReliefWeb AI Platform.

All shared helpers (DB, rate limiting, chat ops, nonces, events, SITREP job runner)
live in blueprints/helpers.py. All routes live in blueprints/*. This file only
contains app initialisation, config, blueprint registration, and middleware.

Run:
    python server.py
    → http://localhost:5000
"""

import logging

# ── Suppress ONNX / TensorRT log noise before any onnxruntime import ─────────
import os
from pathlib import Path

os.environ.setdefault("ORT_LOGGING_LEVEL", "3")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("ORT_TENSORRT_ENGINE_CACHE_ENABLE", "0")
os.environ.setdefault("ONNXRUNTIME_PROVIDERS", "CUDAExecutionProvider,CPUExecutionProvider")

import urllib3
from flask import Flask, jsonify, request
from flask_compress import Compress
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import (
    CORS_ORIGINS,
    LOG_LEVEL,
    SECRET_KEY,
    SERVER_API_KEY,
    SERVER_DEBUG,
    SERVER_HOST,
    SERVER_PORT,
    SSL_VERIFY,
)

if not SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Import shared helpers (single source of truth) ────────────────────────────
from blueprints.helpers import (
    check_api_rate_limit as _check_api_rate_limit,
)
from config import (
    HDX_APP_IDENTIFIER,
    HDX_BASE_URL,
    HDX_RATE_LIMIT_PERIOD,
    HDX_RATE_LIMIT_REQUESTS,
    HDX_TIMEOUT,
    NEWS_API_KEY,
    NEWS_BASE_URL,
    NEWS_RATE_LIMIT_PERIOD,
    NEWS_RATE_LIMIT_REQUESTS,
    NEWS_TIMEOUT,
)

# ── HDX Client (Humanitarian Data Exchange) ──────────────────────────────────
from reliefweb_api.hdx_tools import init_hdx_tools

# ── News Client (NewsAPI.org — World News) ──────────────────────────────────
from reliefweb_api.news_tools import init_news_tools

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ── App setup ─────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
    static_url_path="/static",
)
app.secret_key = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB upload limit (PDF reports)

# ── Register Blueprints ──────────────────────────────────────────────────────
from blueprints.admin_bp import admin_bp
from blueprints.agent_bp import agent_bp
from blueprints.db_bp import db_bp
from blueprints.hdx_bp import hdx_bp
from blueprints.ingest_bp import ingest_bp
from blueprints.news_bp import news_bp
from blueprints.public_bp import public_bp
from blueprints.sitrep import sitrep_bp

app.register_blueprint(admin_bp)
app.register_blueprint(sitrep_bp)
app.register_blueprint(agent_bp)
app.register_blueprint(public_bp)
app.register_blueprint(hdx_bp)
app.register_blueprint(news_bp)
app.register_blueprint(db_bp)
app.register_blueprint(ingest_bp)

# ── Initialize HDX client ────────────────────────────────────────────────────
_hdx_ok = init_hdx_tools(
    app_identifier=HDX_APP_IDENTIFIER,
    base_url=HDX_BASE_URL,
    timeout=HDX_TIMEOUT,
    rate_limit_requests=HDX_RATE_LIMIT_REQUESTS,
    rate_limit_period=HDX_RATE_LIMIT_PERIOD,
)
if _hdx_ok:
    logger.info("✓ HDX client initialized — /api/hdx/* endpoints available")
else:
    logger.warning("HDX client not initialized (HDX_APP_IDENTIFIER not set). HDX endpoints will return 503.")

# ── Initialize News client ────────────────────────────────────────────────────
_news_ok = init_news_tools(
    api_key=NEWS_API_KEY,
    base_url=NEWS_BASE_URL,
    timeout=NEWS_TIMEOUT,
    rate_limit_requests=NEWS_RATE_LIMIT_REQUESTS,
    rate_limit_period=NEWS_RATE_LIMIT_PERIOD,
)
if _news_ok:
    logger.info("✓ News client initialized — /api/news/* endpoints available")
else:
    logger.warning("News client not initialized (NEWS_API_KEY not set). News endpoints will return 503.")

# ── Initialize GDACS client (free, keyless — always succeeds) ────────────────
from config import GDACS_BASE_URL as _GDACS_URL
from config import GDACS_CACHE_TTL as _GDACS_C
from config import GDACS_TIMEOUT as _GDACS_T
from reliefweb_api.gdacs_tools import init_gdacs_tools as _init_gdacs

_gdacs_ok = _init_gdacs(base_url=_GDACS_URL, timeout=_GDACS_T, cache_ttl=_GDACS_C)
if _gdacs_ok:
    logger.info("✓ GDACS client initialized — disaster alert tools available")
else:
    logger.warning("GDACS client not initialized. Disaster alert tools will return errors.")

# ── Initialize Weather client (free, keyless — always succeeds) ─────────────
from config import (
    OPEN_METEO_AQ_URL as _OM_AQ,
)
from config import (
    OPEN_METEO_BASE_URL as _OM_BASE,
)
from config import (
    OPEN_METEO_CACHE_TTL as _OM_C,
)
from config import (
    OPEN_METEO_GEO_URL as _OM_GEO,
)
from config import (
    OPEN_METEO_TIMEOUT as _OM_T,
)
from reliefweb_api.weather_tools import init_weather_tools as _init_weather

_weather_ok = _init_weather(base_url=_OM_BASE, geo_url=_OM_GEO, aq_url=_OM_AQ, timeout=_OM_T, cache_ttl=_OM_C)
if _weather_ok:
    logger.info("✓ Weather client initialized — forecast + geocoding tools available")
else:
    logger.warning("Weather client not initialized. Weather tools will return errors.")

# ── Initialize World Bank client (free, keyless — always succeeds) ──────────
from config import WORLDBANK_BASE_URL as _WB_URL
from config import WORLDBANK_CACHE_TTL as _WB_C
from config import WORLDBANK_TIMEOUT as _WB_T
from reliefweb_api.worldbank_tools import init_worldbank_tools as _init_wb

_wb_ok = _init_wb(base_url=_WB_URL, timeout=_WB_T, cache_ttl=_WB_C)
if _wb_ok:
    logger.info("✓ World Bank client initialized — economic indicator tools available")
else:
    logger.warning("World Bank client not initialized. Economic tools will return errors.")

# ── Initialize ACLED client (conflict events; email+pass OR API key) ────────
# Graceful: credentials yoksa tool'lar eklenmez, agent çalışmaya devam eder.
from config import ACLED_API_KEY as _ACLED_KEY
from config import ACLED_BASE_URL as _ACLED_URL
from config import ACLED_CACHE_TTL as _ACLED_C
from config import ACLED_EMAIL as _ACLED_EMAIL
from config import ACLED_LOGIN_URL as _ACLED_LOGIN
from config import ACLED_PASSWORD as _ACLED_PASS
from config import ACLED_RATE_LIMIT_PERIOD as _ACLED_RP
from config import ACLED_RATE_LIMIT_REQUESTS as _ACLED_RR
from config import ACLED_TIMEOUT as _ACLED_T
from reliefweb_api.acled_tools import init_acled_tools as _init_acled

_acled_ok = _init_acled(
    email=_ACLED_EMAIL,
    password=_ACLED_PASS,
    api_key=_ACLED_KEY,
    base_url=_ACLED_URL,
    login_url=_ACLED_LOGIN,
    timeout=_ACLED_T,
    cache_ttl=_ACLED_C,
    rate_limit_requests=_ACLED_RR,
    rate_limit_period=_ACLED_RP,
)
if _acled_ok:
    logger.info("✓ ACLED client initialized — conflict event tools available")
else:
    logger.warning("ACLED credentials yok — ACLED tools devre dışı (ACLED_EMAIL/PASSWORD veya ACLED_API_KEY)")

# ── Initialize FTS client (OCHA funding plans; keyless — always succeeds) ───
from config import FTS_BASE_URL as _FTS_URL
from config import FTS_CACHE_TTL as _FTS_C
from config import FTS_RATE_LIMIT_PERIOD as _FTS_RP
from config import FTS_RATE_LIMIT_REQUESTS as _FTS_RR
from config import FTS_TIMEOUT as _FTS_T
from reliefweb_api.fts_tools import init_fts_tools as _init_fts

_fts_ok = _init_fts(
    base_url=_FTS_URL,
    timeout=_FTS_T,
    cache_ttl=_FTS_C,
    rate_limit_requests=_FTS_RR,
    rate_limit_period=_FTS_RP,
)
if _fts_ok:
    logger.info("✓ FTS client initialized — humanitarian funding plan tools available")
else:
    logger.warning("FTS client not initialized. Funding tools will return errors.")

# ── Initialize Overpass client (OSM; keyless — always succeeds) ──────────────
from config import OVERPASS_BASE_URL as _OP_URL
from config import OVERPASS_CACHE_TTL as _OP_C
from config import OVERPASS_RATE_LIMIT_PERIOD as _OP_RP
from config import OVERPASS_RATE_LIMIT_REQUESTS as _OP_RR
from config import OVERPASS_TIMEOUT as _OP_T
from reliefweb_api.overpass_tools import init_overpass_tools as _init_op

_op_ok = _init_op(
    base_url=_OP_URL,
    timeout=_OP_T,
    cache_ttl=_OP_C,
    rate_limit_requests=_OP_RR,
    rate_limit_period=_OP_RP,
)
if _op_ok:
    logger.info("✓ Overpass client initialized — OSM infrastructure query tools available")
else:
    logger.warning("Overpass client not initialized. OSM tools will return errors.")

# ── Initialize GIEWS client (FAO food prices; keyless, schema pending) ──────
from config import GIEWS_BASE_URL as _GIEWS_URL
from config import GIEWS_CACHE_TTL as _GIEWS_C
from config import GIEWS_TIMEOUT as _GIEWS_T
from reliefweb_api.giews_tools import init_giews_tools as _init_giews

_giews_ok = _init_giews(base_url=_GIEWS_URL, timeout=_GIEWS_T, cache_ttl=_GIEWS_C)
if _giews_ok:
    logger.info("✓ GIEWS client initialized — food price tools available (schema pending)")
else:
    logger.warning("GIEWS client not initialized. Food tools will return errors.")

# ── Initialize UNHCR client (refugees; key gerekli — graceful skip) ─────────
from config import UNHCR_API_KEY as _UNHCR_KEY
from config import UNHCR_BASE_URL as _UNHCR_URL
from config import UNHCR_CACHE_TTL as _UNHCR_C
from config import UNHCR_TIMEOUT as _UNHCR_T
from reliefweb_api.unhcr_tools import init_unhcr_tools as _init_unhcr

_unhcr_ok = _init_unhcr(api_key=_UNHCR_KEY, base_url=_UNHCR_URL, timeout=_UNHCR_T, cache_ttl=_UNHCR_C)
if _unhcr_ok:
    logger.info("✓ UNHCR client initialized — refugee data tools available")
else:
    logger.warning("UNHCR_API_KEY yok — UNHCR tools devre dışı (graceful)")

# ── Initialize FIRMS client (NASA fires; key gerekli — graceful skip) ───────
from config import FIRMS_BASE_URL as _FIRMS_URL
from config import FIRMS_CACHE_TTL as _FIRMS_C
from config import FIRMS_MAP_KEY as _FIRMS_KEY
from config import FIRMS_TIMEOUT as _FIRMS_T
from reliefweb_api.firms_tools import init_firms_tools as _init_firms

_firms_ok = _init_firms(map_key=_FIRMS_KEY, base_url=_FIRMS_URL, timeout=_FIRMS_T, cache_ttl=_FIRMS_C)
if _firms_ok:
    logger.info("✓ FIRMS client initialized — fire detection tools available")
else:
    logger.warning("FIRMS_MAP_KEY yok — FIRMS tools devre dışı (graceful)")

# ── Initialize MCP tools (arxiv, sequential-thinking, brave) ────────────────
# Non-blocking: starts background thread, returns immediately. Tools added
# to agent when ready (~30-60s for npx/uvx subprocess startup).
from mcp_integration import init_mcp_tools as _init_mcp

_mcp_ok = _init_mcp()
logger.info("MCP: Background init started — arxiv/sequential/brave tools will be available shortly")

_cors_origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
# If no origins configured, default to same-origin only (no wildcard in production)
if not _cors_origins:
    _cors_origins = []  # Flask-CORS with empty list = same-origin only
CORS(app, origins=_cors_origins, supports_credentials=False)
Compress(app)

# ── Global rate limiting ──────────────────────────────────────────────────────
# Default: 120/minute per IP. Blueprint-specific overrides below.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["120/minute"],
    storage_uri="memory://",
    strategy="fixed-window",
)

# Per-blueprint rate limits
limiter.limit("30/minute")(agent_bp)  # Expensive LLM calls
limiter.limit("10/minute")(ingest_bp)  # Very heavy — PDF upload + processing
limiter.limit("60/minute")(admin_bp)  # Light queries
# Public/DB/HDX/News/Sitrep: default 120/min (already set)

# ProxyFix: behind nginx, request.remote_addr is 127.0.0.1 for everyone.
# This makes the per-IP rate limiter see the real client IP from X-Forwarded-For.
from werkzeug.middleware.proxy_fix import ProxyFix

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)


@app.after_request
def add_security_headers(response):
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    response.headers["Cross-Origin-Embedder-Policy"] = "unsafe-none"
    response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if not SERVER_DEBUG:
        # Production CSP — no localhost, includes OpenRouter for LLM calls
        # NOTE: 'unsafe-eval' required by marked.js (new Function()). 'unsafe-inline' removed from script-src (onclick handlers migrated to addEventListener).
        # 'unpkg.com' required for Leaflet.js map library. '*.basemaps.cartocdn.com' required for map tiles.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'self'; "
            "script-src 'self' 'unsafe-eval' https://cdn.jsdelivr.net https://unpkg.com https://www.gstatic.com https://apis.google.com https://static.sketchfab.com https://www.googletagmanager.com https://www.google-analytics.com https://pagead2.googlesyndication.com https://googleads.g.doubleclick.net https://tpc.googlesyndication.com https://adservice.google.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://www.gstatic.com https://openrouter.ai https://www.googleapis.com https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://firebaseinstallations.googleapis.com https://firebaseremoteconfig.googleapis.com https://*.basemaps.cartocdn.com https://www.googletagmanager.com https://www.google-analytics.com https://pagead2.googlesyndication.com https://googleads.g.doubleclick.net; "
            "frame-src https://sightlinehumanitarian.firebaseapp.com https://sightlinehumanitarian.com https://accounts.google.com https://sketchfab.com https://googleads.g.doubleclick.net https://tpc.googlesyndication.com; "
        )
    else:
        # Dev CSP — includes localhost for local development
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'self'; "
            "script-src 'self' 'unsafe-eval' https://cdn.jsdelivr.net https://unpkg.com https://www.gstatic.com https://apis.google.com https://static.sketchfab.com https://www.googletagmanager.com https://www.google-analytics.com https://pagead2.googlesyndication.com https://googleads.g.doubleclick.net https://tpc.googlesyndication.com https://adservice.google.com http://localhost:5000 http://localhost:5001; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' http://localhost:5000 http://localhost:5001 http://127.0.0.1:5000 http://127.0.0.1:5001 https://www.gstatic.com https://openrouter.ai https://www.googleapis.com https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://firebaseinstallations.googleapis.com https://firebaseremoteconfig.googleapis.com https://*.basemaps.cartocdn.com https://www.googletagmanager.com https://www.google-analytics.com https://pagead2.googlesyndication.com https://googleads.g.doubleclick.net; "
            "frame-src https://sightlinehumanitarian.firebaseapp.com https://sightlinehumanitarian.com https://accounts.google.com https://sketchfab.com https://googleads.g.doubleclick.net https://tpc.googlesyndication.com; "
        )
    # HSTS — only when behind HTTPS (nginx sets X-Forwarded-Proto)
    if request.headers.get("X-Forwarded-Proto", "") == "https" or request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Per-IP rate limiting on all /api/* routes (defense-in-depth)
# ─────────────────────────────────────────────────────────────────────────────
# Exempt: / (index), static files. The SITREP stream uses nonce auth + is
# long-lived, so we exempt it too (it has its own auth gate).
_API_RATE_EXEMPT_PATHS = {"/api/health", "/api/sitrep/stream"}  # stream is long-lived SSE


@app.before_request
def _apply_api_rate_limit():
    """Apply per-IP rate limit to all /api/* endpoints (except exempt)."""
    path = request.path
    if not path.startswith("/api/"):
        return None
    # Exempt: health (Docker healthcheck), stream (long-lived SSE), public endpoints
    if (
        path == "/api/health"
        or path.startswith("/api/sitrep/stream")
        or path.startswith("/api/public/")
        or path.startswith("/api/map/")
        or path.startswith("/api/country/summaries")
    ):
        return None
    ok, remaining = _check_api_rate_limit()
    if not ok:
        return jsonify(
            {
                "error": "Rate limit exceeded. Please try again later.",
                "remaining": 0,
            }
        ), 429
    return None


# ── Register remaining routes via blueprints ─────────────────────────────────
# Auth/me, chat/models, landing, health are now in their own blueprints:
from blueprints.auth_route import auth_route_bp  # /api/auth/me
from blueprints.main_bp import main_bp  # landing, spa, health
from blueprints.seo_bp import seo_bp  # /bulletins, /countries, /sitrep/<slug>, sitemap, robots

app.register_blueprint(main_bp)
app.register_blueprint(auth_route_bp)
app.register_blueprint(seo_bp)

# ── Proposal Studio (separate repo, embedded as blueprints) ─────────────────
from proposal_bridge import register_proposal_blueprints

register_proposal_blueprints(app)


# ── Proposal Studio SPA + static serving ─────────────────────────────────────
# The Proposal repo lives under /app/proposal; /proposal and /proposal/static/*
# are served from Sightline's process → single origin, token never lost.
from flask import render_template_string, send_from_directory

from proposal_bridge import proposal_asset_version, proposal_root

_PROPOSAL_STATIC_DIR = os.path.join(proposal_root(), "static")
_PROPOSAL_TEMPLATE = os.path.join(proposal_root(), "templates", "index.html")


@app.route("/proposal")
@app.route("/proposal/")
def proposal_spa():
    """Proposal Studio SPA — renders its own template with config.

    The Proposal template uses url_for('static', ...), which would resolve
    to Sightline's /static/... here. Fix: give the Jinja environment a
    proposal-static-aware url_for — the 'static' endpoint produces
    /proposal/static/...
    """
    from flask import url_for as _flask_url_for

    def _proposal_url_for(endpoint, **values):
        if endpoint == "static":
            filename = values.pop("filename", "")
            return f"/proposal/static/{filename}"
        return _flask_url_for(endpoint, **values)

    with open(_PROPOSAL_TEMPLATE, encoding="utf-8") as _f:
        _html = _f.read()
    return render_template_string(
        _html,
        config={
            "PROPOSAL_BASE_PATH": "/proposal",
            "ASSET_VERSION": proposal_asset_version(),
            # Use Sightline's canonical Firebase web app so Firebase Auth's
            # browser persistence is shared with /app (it is keyed by apiKey).
            "FIREBASE_CONFIG_URL": "/static/firebase-config.js",
        },
        url_for=_proposal_url_for,
    )


@app.route("/proposal/static/<path:filename>", endpoint="proposal_static")
def proposal_static(filename):
    """Proposal static files (js/, css/, images/, modules/)."""
    return send_from_directory(_PROPOSAL_STATIC_DIR, filename)


# ═════════════════════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    auth_status = "ENABLED" if SERVER_API_KEY else "DISABLED"
    cors_display = ", ".join(_cors_origins)
    print("=" * 58)
    print("  ReliefWeb AI Platform  —  Unified Server")
    print(f"  http://{SERVER_HOST}:{SERVER_PORT}")
    print(f"  Auth : {auth_status}")
    print(f"  CORS : {cors_display}")
    print("  Tabs : Database | Sightline | SITREP")
    print("=" * 58)
    app.run(
        host=SERVER_HOST,
        port=SERVER_PORT,
        debug=SERVER_DEBUG,
        threaded=True,
    )
