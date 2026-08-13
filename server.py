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
import time
from pathlib import Path

# ── Suppress ONNX / TensorRT log noise before any onnxruntime import ─────────
import os

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

# ── Import shared helpers (single source of truth) ────────────────────────────
from blueprints.helpers import (  # noqa: E402
    MANUAL_ID_BASE,
    PROPOSAL_SECTION_LABELS,
    PROPOSAL_SECTIONS,
    SECTION_DB_FIELDS,
    _AGENT_BUSY_TIMEOUT,
    _api_rate_counts,
    _api_rate_lock,
    _jobs,
    _jobs_lock,
    _stream_nonces,
    _stream_nonces_lock,
    _user_active_chat,
    _user_active_chat_lock,
    _user_agent_busy,
    _user_agent_busy_lock,
    _user_agent_busy_since,
    chats_db as _chats_db,
    check_and_increment_rate_limit as _check_and_increment_rate_limit,
    check_api_rate_limit as _check_api_rate_limit,
    check_rate_limit as _check_rate_limit,
    consume_stream_nonce as _consume_stream_nonce,
    create_stream_nonce as _create_stream_nonce,
    db_add_message as _db_add_message,
    db_chat_belongs_to as _db_chat_belongs_to,
    db_clear_messages as _db_clear_messages,
    db_conn as _db_conn,
    db_create_chat as _db_create_chat,
    db_delete_chat as _db_delete_chat,
    db_get_chats_by_uid as _db_get_chats_by_uid,
    db_get_messages as _db_get_messages,
    db_rename_chat as _db_rename_chat,
    ensure_active_chat as _ensure_active_chat,
    generate_chat_title as _generate_chat_title,
    get_agent as _get_agent,
    get_chroma_adapter as _get_chroma_adapter,
    get_proposal_for_edit as _get_proposal_for_edit,
    increment_rate_limit as _increment_rate_limit,
    init_chats_db as _init_chats_db,
    is_gpu_noise as _is_gpu_noise,
    load_langchain_messages as _load_langchain_messages,
    log_event as _log_event,
    new_chat_id as _new_chat_id,
    parse_countries as _parse_countries,
    row_to_dict as _row_to_dict,
    run_job as _run_job,
    strip_ansi as _strip_ansi,
    trim_bulletin_for_preview as _trim_bulletin_for_preview,
    update_step_status as _update_step_status,
    upsert_user as _upsert_user,
)

# ── HDX Client (Humanitarian Data Exchange) ──────────────────────────────────
from reliefweb_api.hdx_tools import get_hdx_client, init_hdx_tools

# ── News Client (NewsAPI.org — World News) ──────────────────────────────────
from reliefweb_api.news_tools import get_news_client, init_news_tools

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
from blueprints.guided_proposal import guided_proposal_bp
from blueprints.hdx_bp import hdx_bp
from blueprints.ingest_bp import ingest_bp
from blueprints.news_bp import news_bp
from blueprints.proposal import proposal_bp
from blueprints.public_bp import public_bp
from blueprints.sitrep import sitrep_bp

app.register_blueprint(proposal_bp)
app.register_blueprint(guided_proposal_bp)
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

# ── Initialize MCP tools (arxiv, sequential-thinking, brave) ────────────────
# Non-blocking: starts background thread, returns immediately. Tools added
# to agent when ready (~30-60s for npx/uvx subprocess startup).
from mcp_integration import init_mcp_tools as _init_mcp

_mcp_ok = _init_mcp()
logger.info("MCP: Background init started — arxiv/sequential/brave tools will be available shortly")

_cors_origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()] or ["*"]
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
limiter.limit("20/minute")(proposal_bp)  # Even more expensive
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
            "script-src 'self' 'unsafe-eval' https://cdn.jsdelivr.net https://unpkg.com https://www.gstatic.com https://apis.google.com https://static.sketchfab.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://www.gstatic.com https://openrouter.ai https://www.googleapis.com https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://firebaseinstallations.googleapis.com https://firebaseremoteconfig.googleapis.com https://*.basemaps.cartocdn.com; "
            "frame-src https://sightlinehumanitarian.firebaseapp.com https://sightlinehumanitarian.com https://accounts.google.com https://sketchfab.com; "
        )
    else:
        # Dev CSP — includes localhost for local development
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'self'; "
            "script-src 'self' 'unsafe-eval' https://cdn.jsdelivr.net https://unpkg.com https://www.gstatic.com https://apis.google.com https://static.sketchfab.com http://localhost:5000 http://localhost:5001; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' http://localhost:5000 http://localhost:5001 http://127.0.0.1:5000 http://127.0.0.1:5001 https://www.gstatic.com https://openrouter.ai https://www.googleapis.com https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://firebaseinstallations.googleapis.com https://firebaseremoteconfig.googleapis.com https://*.basemaps.cartocdn.com; "
            "frame-src https://sightlinehumanitarian.firebaseapp.com https://sightlinehumanitarian.com https://accounts.google.com https://sketchfab.com; "
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
from blueprints.main_bp import main_bp  # landing, spa, health
from blueprints.auth_route import auth_route_bp  # /api/auth/me

app.register_blueprint(main_bp)
app.register_blueprint(auth_route_bp)


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