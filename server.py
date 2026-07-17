"""
server.py — Unified Flask server for ReliefWeb AI Platform.

Merges:
  - reliefwebapi/web_app.py   → /api/agent/* and /api/db/* routes
  - sitrep_pipeline/server.py → /api/sitrep/* routes

Run:
    python server.py
    → http://localhost:5000

Tabs:
    /  →  Tab 1: Database (SQLite reports browser)
          Tab 2: Agent     (LangGraph chat)
          Tab 3: SITREP    (9-stage pipeline runner)
"""

import json
import logging
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path


# ── Suppress ONNX / TensorRT log noise before any onnxruntime import ─────────
os.environ.setdefault("ORT_LOGGING_LEVEL", "3")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("ORT_TENSORRT_ENGINE_CACHE_ENABLE", "0")
os.environ.setdefault("ONNXRUNTIME_PROVIDERS", "CUDAExecutionProvider,CPUExecutionProvider")

import urllib3
from flask import Flask, Response, g, jsonify, render_template, request
from flask_cors import CORS
from flask_compress import Compress

from config import (
    _LLM_API_KEY,
    _LLM_BASE_URL,
    CHAT_MODELS,
    CHATS_DB_PATH,
    CORS_ORIGINS,
    DAILY_MESSAGE_LIMIT,
    DB_PATH,
    LOG_LEVEL,
    MODEL_MAX_TOKENS,
    MODEL_TEMPERATURE,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
    OUTPUT_REPORTS_DIR,
    PREMIUM_MESSAGE_LIMIT,
    SECRET_KEY,
    SERVER_API_KEY,
    SERVER_DEBUG,
    SERVER_HOST,
    SERVER_PORT,
    SITREP_JOB_TIMEOUT,
    SSL_CA_BUNDLE,
    SSL_VERIFY,
)

if not SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from auth import _admins, current_role, current_uid, require_admin, require_auth, require_role
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
from blueprints.proposal import proposal_bp
from blueprints.admin_bp import admin_bp
from blueprints.sitrep import sitrep_bp
from blueprints.agent_bp import agent_bp
from blueprints.public_bp import public_bp
from blueprints.hdx_bp import hdx_bp
from blueprints.news_bp import news_bp
from blueprints.db_bp import db_bp
from blueprints.ingest_bp import ingest_bp

app.register_blueprint(proposal_bp)
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

# ProxyFix: behind nginx, request.remote_addr is 127.0.0.1 for everyone.
# This makes the per-IP rate limiter see the real client IP from X-Forwarded-For.
from werkzeug.middleware.proxy_fix import ProxyFix

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

def _ssl_verify():
    """Return verify kwarg for requests calls based on config."""
    if not SSL_VERIFY:
        return False
    return SSL_CA_BUNDLE or True

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
            "frame-src https://YOUR_PROJECT.firebaseapp.com https://accounts.google.com https://sketchfab.com; "
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
            "frame-src https://YOUR_PROJECT.firebaseapp.com https://accounts.google.com https://sketchfab.com; "
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
    if path == "/api/health" or path.startswith("/api/sitrep/stream") or path.startswith("/api/public/") or path.startswith("/api/map/") or path.startswith("/api/country/summaries"):
        return None
    ok, remaining = _check_api_rate_limit()
    if not ok:
        return jsonify({
            "error": "Rate limit exceeded. Please try again later.",
            "remaining": 0,
        }), 429
    return None

# ─────────────────────────────────────────────────────────────────────────────
# AGENT: Lazy import + multi-chat conversation state
# ─────────────────────────────────────────────────────────────────────────────

_relief_agent = None
_agent_lock   = threading.Lock()

# Multi-chat: SQLite-backed persistence (survives server restarts)
import time as _time

_chats_lock     = threading.Lock()
_user_active_chat = {}  # uid → chat_id
_user_active_chat_lock = threading.Lock()
_user_agent_busy = {}  # uid → bool  (per-user agent busy flag)
_user_agent_busy_since = {}  # uid → timestamp
_user_agent_busy_lock = threading.Lock()  # guards _user_agent_busy + _user_agent_busy_since
_AGENT_BUSY_TIMEOUT = int(os.getenv("AGENT_BUSY_TIMEOUT", "120"))  # 2 min max — auto-unlock if stuck

# Simple per-IP rate limiter for unauthenticated endpoints
_api_rate_lock = threading.Lock()
_api_rate_counts = {}  # ip → {date: str, count: int}
_API_DAILY_LIMIT = int(os.getenv("API_DAILY_LIMIT", "100"))

def _check_api_rate_limit():
    """Per-IP rate limit for API endpoints. Returns (ok, remaining)."""
    from datetime import date
    # Dev mode: bypass IP rate limiting entirely for loopback
    from auth import _dev_mode
    if _dev_mode():
        return True, 9999
    today = date.today().isoformat()
    ip = request.remote_addr or "0.0.0.0"
    with _api_rate_lock:
        # Clean up old entries (keep only today's)
        if len(_api_rate_counts) > 1000:
            stale = [k for k, v in _api_rate_counts.items() if v["date"] != today]
            for k in stale:
                del _api_rate_counts[k]
        entry = _api_rate_counts.get(ip)
        if not entry or entry["date"] != today:
            entry = {"date": today, "count": 0}
            _api_rate_counts[ip] = entry
        entry["count"] += 1
        remaining = max(0, _API_DAILY_LIMIT - entry["count"])
    return entry["count"] <= _API_DAILY_LIMIT, remaining

def _chats_db():
    """Return a connection to the chats SQLite database."""
    conn = sqlite3.connect(str(CHATS_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def _check_rate_limit(uid: str, role: str = "free") -> dict:
    """Check daily message count for a user. Returns {remaining, limit, used}.

    Role-aware: free users get DAILY_MESSAGE_LIMIT, premium get PREMIUM_MESSAGE_LIMIT,
    admin gets 999 (unlimited).
    """
    from datetime import date
    today = date.today().isoformat()
    conn = _chats_db()
    try:
        row = conn.execute(
            "SELECT date, count FROM rate_limits WHERE uid = ?", (uid,)
        ).fetchone()
        if row and row["date"] == today:
            used = row["count"]
        else:
            used = 0
    finally:
        conn.close()
    # Role-based limits
    if role == "admin":
        limit = 999
    elif role == "premium":
        limit = PREMIUM_MESSAGE_LIMIT
    else:
        limit = DAILY_MESSAGE_LIMIT
    remaining = max(0, limit - used)
    return {"remaining": remaining, "limit": limit, "used": used}

def _check_and_increment_rate_limit(uid: str, role: str = "free") -> dict:
    """Atomically check the daily rate limit AND increment the counter in a single
    SQLite transaction. Returns {remaining, limit, used, allowed}.

    This prevents the TOCTOU race where concurrent requests all pass the check
    before any increment runs. Use this instead of _check_rate_limit + _increment_rate_limit
    when you need to gate a single request.
    """
    from datetime import date
    today = date.today().isoformat()
    if role == "admin":
        limit = 999
    elif role == "premium":
        limit = PREMIUM_MESSAGE_LIMIT
    else:
        limit = DAILY_MESSAGE_LIMIT
    conn = _chats_db()
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        with conn:
            row = conn.execute(
                "SELECT date, count FROM rate_limits WHERE uid = ?", (uid,)
            ).fetchone()
            if row and row["date"] == today:
                used = row["count"]
            else:
                used = 0
            allowed = used < limit
            if allowed:
                new_count = used + 1
                if row:
                    conn.execute(
                        "UPDATE rate_limits SET count = ? WHERE uid = ?", (new_count, uid)
                    )
                else:
                    conn.execute(
                        "INSERT OR REPLACE INTO rate_limits (uid, date, count) VALUES (?, ?, 1)",
                        (uid, today),
                    )
            else:
                new_count = used
        remaining = max(0, limit - new_count)
        return {"remaining": remaining, "limit": limit, "used": new_count, "allowed": allowed}
    finally:
        conn.close()

def _increment_rate_limit(uid: str) -> int:
    """Atomically increment daily message count for a user. Returns new count."""
    from datetime import date
    today = date.today().isoformat()
    conn = _chats_db()
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        with conn:
            row = conn.execute(
                "SELECT date, count FROM rate_limits WHERE uid = ?", (uid,)
            ).fetchone()
            if row and row["date"] == today:
                new_count = row["count"] + 1
                conn.execute(
                    "UPDATE rate_limits SET count = ? WHERE uid = ?", (new_count, uid)
                )
            else:
                new_count = 1
                conn.execute(
                    "INSERT OR REPLACE INTO rate_limits (uid, date, count) VALUES (?, ?, 1)",
                    (uid, today),
                )
    finally:
        conn.close()
    return new_count

def _init_chats_db():
    """Create chats tables if they don't exist."""
    conn = _chats_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chats (
            id       TEXT PRIMARY KEY,
            title    TEXT NOT NULL DEFAULT 'New Chat',
            created  REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id  TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
            role     TEXT NOT NULL,
            content  TEXT NOT NULL,
            ts       REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chatmsg_chat ON chat_messages(chat_id);
        CREATE TABLE IF NOT EXISTS rate_limits (
            uid  TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS events (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ts        REAL NOT NULL,
            uid       TEXT NOT NULL DEFAULT '',
            event     TEXT NOT NULL,
            props     TEXT NOT NULL DEFAULT '{}',
            session   TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_events_ts    ON events(ts);
        CREATE INDEX IF NOT EXISTS idx_events_uid   ON events(uid);
        CREATE INDEX IF NOT EXISTS idx_events_event ON events(event);
        CREATE TABLE IF NOT EXISTS users (
            uid            TEXT PRIMARY KEY,
            email          TEXT NOT NULL DEFAULT '',
            role           TEXT NOT NULL DEFAULT 'free',
            created_at     REAL NOT NULL,
            last_seen      REAL NOT NULL,
            signup_source  TEXT NOT NULL DEFAULT 'web'
        );
        CREATE TABLE IF NOT EXISTS proposals (
            id              TEXT PRIMARY KEY,
            uid             TEXT NOT NULL,
            title           TEXT NOT NULL,
            country         TEXT NOT NULL,
            event           TEXT NOT NULL,
            themes          TEXT NOT NULL,
            donor           TEXT NOT NULL,
            date_from       TEXT NOT NULL DEFAULT '',
            date_to         TEXT NOT NULL DEFAULT '',
            toc             TEXT NOT NULL DEFAULT '[]',
            logframe        TEXT NOT NULL DEFAULT '{}',
            narrative       TEXT NOT NULL DEFAULT '',
            created_at      REAL NOT NULL,
            cover_page      TEXT NOT NULL DEFAULT '{}',
            background      TEXT NOT NULL DEFAULT '',
            needs_assessment TEXT NOT NULL DEFAULT '',
            methodology     TEXT NOT NULL DEFAULT '',
            budget          TEXT NOT NULL DEFAULT '{}',
            mne_framework   TEXT NOT NULL DEFAULT '{}',
            risk_matrix     TEXT NOT NULL DEFAULT '[]',
            sustainability  TEXT NOT NULL DEFAULT '',
            coordination    TEXT NOT NULL DEFAULT '',
            current_step    TEXT NOT NULL DEFAULT 'cover',
            step_status     TEXT NOT NULL DEFAULT '{}',
            completed_at    REAL,
            pinned_sources  TEXT NOT NULL DEFAULT '[]',
            beneficiary_data TEXT NOT NULL DEFAULT '{}',
            toc_nodes       TEXT NOT NULL DEFAULT '[]',
            logframe_data   TEXT NOT NULL DEFAULT '{}',
            budget_details  TEXT NOT NULL DEFAULT '{}',
            risk_details    TEXT NOT NULL DEFAULT '[]',
            mne_plan        TEXT NOT NULL DEFAULT '[]'
        );
        CREATE INDEX IF NOT EXISTS idx_proposals_uid ON proposals(uid);
    """)
    # Migration: add uid column if missing
    cols = [r[1] for r in conn.execute("PRAGMA table_info(chats)").fetchall()]
    if "uid" not in cols:
        conn.execute("ALTER TABLE chats ADD COLUMN uid TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chats_uid ON chats(uid)")
        conn.commit()
    # Migration: add new section columns to existing proposals table
    prop_cols = [r[1] for r in conn.execute("PRAGMA table_info(proposals)").fetchall()]
    _new_prop_cols = {
        "cover_page":      ("TEXT NOT NULL DEFAULT '{}'"),
        "background":      ("TEXT NOT NULL DEFAULT ''"),
        "needs_assessment":("TEXT NOT NULL DEFAULT ''"),
        "methodology":     ("TEXT NOT NULL DEFAULT ''"),
        "budget":          ("TEXT NOT NULL DEFAULT '{}'"),
        "mne_framework":   ("TEXT NOT NULL DEFAULT '{}'"),
        "risk_matrix":     ("TEXT NOT NULL DEFAULT '[]'"),
        "sustainability":  ("TEXT NOT NULL DEFAULT ''"),
        "coordination":    ("TEXT NOT NULL DEFAULT ''"),
        "current_step":    ("TEXT NOT NULL DEFAULT 'cover'"),
        "step_status":     ("TEXT NOT NULL DEFAULT '{}'"),
        "completed_at":    ("REAL"),
        "reference_text":  ("TEXT NOT NULL DEFAULT ''"),
        "reference_filename": ("TEXT NOT NULL DEFAULT ''"),
        "pinned_sources":  ("TEXT NOT NULL DEFAULT '[]'"),
        "beneficiary_data":("TEXT NOT NULL DEFAULT '{}'"),
        "toc_nodes":       ("TEXT NOT NULL DEFAULT '[]'"),
        "logframe_data":   ("TEXT NOT NULL DEFAULT '{}'"),
        "budget_details":  ("TEXT NOT NULL DEFAULT '{}'"),
        "risk_details":    ("TEXT NOT NULL DEFAULT '[]'"),
        "mne_plan":        ("TEXT NOT NULL DEFAULT '[]'"),
    }
    for col, coldef in _new_prop_cols.items():
        if col not in prop_cols:
            conn.execute(f"ALTER TABLE proposals ADD COLUMN {col} {coldef}")
    conn.commit()
    conn.close()

_init_chats_db()


def _log_event(uid: str, event: str, props: dict = None, session: str = ""):
    """Log a user/system event to the local events table.

    Args:
        uid:       Firebase UID (empty string for anonymous/system events)
        event:     Event name (e.g. 'chat_message_sent', 'sitrep_run_started')
        props:     Optional JSON-serializable dict with event details
        session:   Optional session/correlation ID

    This is non-blocking on errors — a failed event log should never break the request.
    """
    try:
        conn = _chats_db()
        conn.execute(
            "INSERT INTO events (ts, uid, event, props, session) VALUES (?, ?, ?, ?, ?)",
            (_time.time(), uid or "", event, json.dumps(props or {}), session),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug("Failed to log event %s: %s", event, e)


def _upsert_user(uid: str, email: str = "", role: str = "free", signup_source: str = "web"):
    """Insert or update a user in the local users table.

    Called on every /api/auth/me to track created_at (first seen) and last_seen.
    """
    if not uid:
        return
    try:
        conn = _chats_db()
        now = _time.time()
        conn.execute("""
            INSERT INTO users (uid, email, role, created_at, last_seen, signup_source)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(uid) DO UPDATE SET
                email     = excluded.email,
                role      = excluded.role,
                last_seen = excluded.last_seen
        """, (uid, email, role, now, now, signup_source))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug("Failed to upsert user %s: %s", uid, e)

def _new_chat_id():
    return uuid.uuid4().hex[:8]

def _db_chat_exists(chat_id):
    conn = _chats_db()
    row = conn.execute("SELECT 1 FROM chats WHERE id = ?", (chat_id,)).fetchone()
    conn.close()
    return row is not None

def _db_create_chat(chat_id, uid="", title="New Chat"):
    conn = _chats_db()
    conn.execute("INSERT INTO chats (id, uid, title, created) VALUES (?, ?, ?, ?)",
                 (chat_id, uid, title, _time.time()))
    conn.commit()
    conn.close()

def _db_get_chats_by_uid(uid):
    conn = _chats_db()
    rows = conn.execute(
        "SELECT c.id, c.title, c.created, COUNT(m.id) AS msg_count "
        "FROM chats c LEFT JOIN chat_messages m ON m.chat_id = c.id "
        "WHERE c.uid = ? "
        "GROUP BY c.id ORDER BY c.created DESC",
        (uid,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def _db_chat_belongs_to(chat_id, uid):
    conn = _chats_db()
    row = conn.execute("SELECT uid FROM chats WHERE id = ?", (chat_id,)).fetchone()
    conn.close()
    return row is not None and row["uid"] == uid

def _db_add_message(chat_id, role, content):
    conn = _chats_db()
    conn.execute("INSERT INTO chat_messages (chat_id, role, content, ts) VALUES (?, ?, ?, ?)",
                 (chat_id, role, content, _time.time()))
    conn.commit()
    conn.close()

def _db_get_messages(chat_id):
    conn = _chats_db()
    rows = conn.execute(
        "SELECT role, content FROM chat_messages WHERE chat_id = ? ORDER BY id",
        (chat_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def _db_rename_chat(chat_id, title):
    conn = _chats_db()
    conn.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))
    conn.commit()
    conn.close()

def _db_delete_chat(chat_id):
    conn = _chats_db()
    conn.execute("DELETE FROM chat_messages WHERE chat_id = ?", (chat_id,))
    conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    conn.commit()
    conn.close()

def _db_clear_messages(chat_id):
    conn = _chats_db()
    conn.execute("DELETE FROM chat_messages WHERE chat_id = ?", (chat_id,))
    conn.execute("UPDATE chats SET title = 'New Chat' WHERE id = ?", (chat_id,))
    conn.commit()
    conn.close()

def _ensure_active_chat(uid=""):
    """Return the active chat_id for the user, creating one if needed."""
    with _chats_lock:
        with _user_active_chat_lock:
            cid = _user_active_chat.get(uid)
            if cid and _db_chat_exists(cid) and (not uid or _db_chat_belongs_to(cid, uid)):
                return cid
            if uid:
                conn = _chats_db()
                row = conn.execute(
                    "SELECT id FROM chats WHERE uid = ? ORDER BY created DESC LIMIT 1",
                    (uid,)
                ).fetchone()
                conn.close()
                if row and _db_chat_belongs_to(row["id"], uid):
                    _user_active_chat[uid] = row["id"]
                    return row["id"]
            cid = _new_chat_id()
            _db_create_chat(cid, uid=uid)
            _user_active_chat[uid] = cid
            return cid

def _load_langchain_messages(chat_id):
    """Load messages from DB as LangChain message objects."""
    from langchain_core.messages import AIMessage, HumanMessage
    rows = _db_get_messages(chat_id)
    msgs = []
    for r in rows:
        if r["role"] == "user":
            msgs.append(HumanMessage(content=r["content"]))
        elif r["role"] == "assistant":
            msgs.append(AIMessage(content=r["content"]))
    return msgs


def _get_agent():
    global _relief_agent
    if _relief_agent is None:
        with _agent_lock:
            if _relief_agent is None:
                from agent.relief_agent import relief_agent
                _relief_agent = relief_agent
    return _relief_agent


def _generate_chat_title(chat_id: str, user_msg: str, ai_reply: str):
    """Generate a short chat title using the LLM in a background thread."""
    def _do():
        try:
            from langchain_openai import ChatOpenAI

            from config import config as _cfg
            mini = ChatOpenAI(
                model=_cfg.LLM_MODEL,
                base_url=_cfg._LLM_BASE_URL,
                api_key=_cfg._LLM_API_KEY,
                temperature=0.3,
                max_tokens=30,
                timeout=30,
            )
            prompt = (
                "Generate a very short title (max 6 words, no quotes) "
                "for this chat conversation:\n"
                f"User: {user_msg[:200]}\n"
                f"Assistant: {ai_reply[:200]}"
            )
            resp = mini.invoke(prompt)
            title = resp.content.strip().strip('"\'').strip()[:60]
            if title:
                _db_rename_chat(chat_id, title)
                logger.info("Chat title generated: chat_id=%s title=%s", chat_id, title)
            else:
                logger.warning("Chat title generation returned empty for chat_id=%s", chat_id)
        except Exception as exc:
            logger.warning("Chat title generation failed for chat_id=%s: %s", chat_id, exc)
    threading.Thread(target=_do, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# DB: SQLite helpers   (from reliefwebapi/web_app.py)
# ─────────────────────────────────────────────────────────────────────────────

def _db_conn():
    """Return a connection to the reliefweb SQLite database with WAL mode."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _row_to_dict(row):
    return dict(row)


def _parse_countries(json_str):
    try:
        return json.loads(json_str or "[]")
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# SITREP PIPELINE: Job runner + ANSI stripper  (from sitrep_pipeline/server.py)
# ─────────────────────────────────────────────────────────────────────────────

_jobs: dict = {}
_jobs_lock  = threading.Lock()
_JOBS_MAX_AGE = int(os.getenv("SITREP_JOBS_MAX_AGE", "3600"))  # Clean up completed jobs older than 1 hour

# ── Nonce store for SITREP stream auth ────────────────────────────────────────
# Replaces JWT-in-query-param (EventSource can't send Authorization headers).
# Nonces are single-use, expire after 5 minutes, tied to a UID.
_stream_nonces: dict = {}  # {nonce_str: {"uid": str, "job_id": str, "expires": float, "used": bool}}
_stream_nonces_lock = threading.Lock()
_STREAM_NONCE_TTL = int(os.getenv("STREAM_NONCE_TTL", "300"))  # 5 minutes


def _create_stream_nonce(uid: str, job_id: str = "") -> str:
    """Create a single-use nonce for SITREP stream access, tied to a UID and job_id."""
    nonce = secrets.token_urlsafe(32)
    with _stream_nonces_lock:
        _stream_nonces[nonce] = {
            "uid": uid,
            "job_id": job_id,
            "expires": time.time() + _STREAM_NONCE_TTL,
            "used": False,
        }
    return nonce


def _consume_stream_nonce(nonce: str, uid: str, job_id: str = "") -> bool:
    """Validate and consume a stream nonce. Returns True if valid.

    Checks: nonce exists, not used, not expired, UID matches, job_id matches (if set).
    """
    with _stream_nonces_lock:
        entry = _stream_nonces.get(nonce)
        if entry is None:
            return False
        if entry["used"]:
            return False
        if time.time() > entry["expires"]:
            del _stream_nonces[nonce]
            return False
        if entry["uid"] != uid:
            return False
        # If the nonce was created for a specific job, verify it matches
        if entry.get("job_id") and job_id and entry["job_id"] != job_id:
            return False
        entry["used"] = True
        return True


def _cleanup_stream_nonces():
    """Remove expired nonces. Called periodically."""
    now = time.time()
    with _stream_nonces_lock:
        expired = [k for k, v in _stream_nonces.items() if now > v["expires"]]
        for k in expired:
            del _stream_nonces[k]

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[mGKHF]')
_NOISE   = [
    "onnxruntime", "tensorrt", "cublas", "cudnn", "ep error",
    "falling back to", "onnxruntime_providers", "executionprovider",
    "requires", "from tensorrt", "cann execution",
    "cublaslt", "provider_bridge_ort", "cudaexecutionprovider",
    "tensorrtexecutionprovider",
]


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _is_gpu_noise(line: str) -> bool:
    lo = line.lower()
    return any(kw in lo for kw in _NOISE)


def _run_job(job_id: str, cmd: list):
    q = _jobs[job_id]["queue"]
    proc = None
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(BASE_DIR),
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        with _jobs_lock:
            _jobs[job_id]["proc"] = proc

        deadline = _time.time() + SITREP_JOB_TIMEOUT
        while True:
            raw_line = proc.stdout.readline()
            if not raw_line:
                # Process closed stdout — check if it actually exited
                if proc.poll() is not None:
                    break
                # No output yet — check timeout, then wait briefly
                if _time.time() > deadline:
                    q.put(f"[SERVER TIMEOUT] SITREP job exceeded {SITREP_JOB_TIMEOUT}s, terminating.")
                    logger.warning("SITREP job %s exceeded %ds timeout, terminating", job_id, SITREP_JOB_TIMEOUT)
                    try:
                        proc.terminate()
                        _time.sleep(5)
                        if proc.poll() is None:
                            proc.kill()
                    except Exception:
                        pass
                    break
                _time.sleep(0.1)
                continue
            line = _strip_ansi(raw_line.rstrip())
            if not line:
                continue
            if _is_gpu_noise(line):
                q.put(f"[GPU_WARN] {line}")
            else:
                q.put(line)

        proc.wait()
        exit_code = proc.returncode
        with _jobs_lock:
            _jobs[job_id]["status"] = "done" if exit_code == 0 else "error"
            _jobs[job_id]["finished_at"] = _time.time()
            _jobs[job_id]["exit_code"] = exit_code
    except Exception as exc:
        q.put(f"[SERVER ERROR] {exc}")
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["finished_at"] = _time.time()
    finally:
        # Ensure the child process is dead if we're leaving with it still running
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                _time.sleep(1)
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
        q.put(None)  # sentinel


# ═════════════════════════════════════════════════════════════════════════════
# ROUTES — Auth / Me
# ═════════════════════════════════════════════════════════════════════════════

@app.route("/api/auth/me")
@require_auth
def api_auth_me():
    from auth import _admins, _dev_mode
    user = getattr(g, "current_user", None) or {}
    uid = user.get("uid", "")
    role = user.get("role", "free")
    admins = _admins()
    is_admin = role == "admin" or uid in admins or _dev_mode()
    if is_admin and role != "admin":
        role = "admin"
    logger.info(f"auth/me: uid={uid!r}, role={role}, is_admin={is_admin}")
    # Track user (upsert) + log login event
    _upsert_user(uid, user.get("email", ""), role)
    rate = _check_rate_limit(uid, role)
    return jsonify({
        "uid": uid,
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "is_admin": is_admin,
        "role": role,
        "rate_limit": rate,
        "models": {k: {"name": v["name"], "desc": v["desc"], "premium": v["premium"]} for k, v in CHAT_MODELS.items()},
    })


@app.route("/api/chat/models")
@require_auth
def api_chat_models():
    role = current_role()
    return jsonify({
        "models": {k: {"name": v["name"], "desc": v["desc"], "premium": v["premium"], "allowed": not v["premium"] or role in ("premium", "admin")} for k, v in CHAT_MODELS.items()},
        "default": "thinking",
    })


# ═════════════════════════════════════════════════════════════════════════════
# ROUTES — Admin Role Management
# ═════════════════════════════════════════════════════════════════════════════


@app.route("/")
def landing():
    return render_template("landing.html", v=int(_time.time()))


@app.route("/app")
def spa():
    return render_template("index.html", v=int(_time.time()))


@app.route("/api/health")
def health():
    """Enhanced health check — verifies DB, vector store, and LLM config.

    Security: this endpoint is unauthenticated, so it returns only boolean
    status flags — no model names, no release info, no dev_mode flag (which
    would be a banner saying 'auth is disabled here').
    """
    from config import _LLM_API_KEY, CHROMA_DIR, VECTOR_BACKEND

    checks = {"status": "ok", "version": "1.2"}

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

    # Vector store check (boolean only — no backend name leak)
    if VECTOR_BACKEND == "pgvector":
        try:
            from config import SUPABASE_DB_URL, SUPABASE_URL
            checks["vector"] = bool(SUPABASE_URL and SUPABASE_DB_URL)
        except Exception:
            checks["vector"] = False
    else:
        checks["vector"] = Path(str(CHROMA_DIR)).exists()

    # LLM config check (boolean only — no model/provider name leak)
    checks["llm"] = bool(_LLM_API_KEY)

    # HDX/News checks (boolean only)
    checks["hdx"] = get_hdx_client() is not None
    checks["news"] = get_news_client() is not None

    # Overall status: ok only if all critical checks pass
    all_ok = db_ok and checks.get("vector", False) and checks["llm"]
    checks["status"] = "ok" if all_ok else "degraded"

    code = 200 if all_ok else 503
    return jsonify(checks), code


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


MANUAL_ID_BASE = 9_000_000_000   # manual TR-prefixed IDs start above this


# =============================================================================
# Proposals API (Proje Tasarım Odası)
# =============================================================================


# =============================================================================
# Proposal Wizard — Section Management
# =============================================================================

PROPOSAL_SECTIONS = [
    "cover", "background", "needs_assessment", "toc", "logframe",
    "methodology", "budget", "mne_framework", "risk_matrix",
    "sustainability", "coordination", "final_review",
]
PROPOSAL_SECTION_LABELS = {
    "cover": "Cover Page",
    "background": "Context & Background",
    "needs_assessment": "Needs Assessment",
    "toc": "Theory of Change",
    "logframe": "Logical Framework",
    "methodology": "Methodology",
    "budget": "Budget Summary",
    "mne_framework": "Monitoring & Evaluation",
    "risk_matrix": "Risk Matrix",
    "sustainability": "Sustainability & Exit",
    "coordination": "Coordination",
    "final_review": "Final Review & Export",
}
SECTION_DB_FIELDS = {
    "cover": "cover_page",
    "background": "background",
    "needs_assessment": "needs_assessment",
    "toc": "toc",
    "logframe": "logframe",
    "methodology": "methodology",
    "budget": "budget",
    "mne_framework": "mne_framework",
    "risk_matrix": "risk_matrix",
    "sustainability": "sustainability",
    "coordination": "coordination",
    "final_review": "narrative",
}


def _get_proposal_for_edit(prop_id: str, uid: str, role: str):
    """Fetch proposal row, check edit permissions. Returns (row, conn) or (None, conn)."""
    conn = _chats_db()
    try:
        if role == "admin":
            row = conn.execute("SELECT * FROM proposals WHERE id = ?", (prop_id,)).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM proposals WHERE id = ? AND uid = ?",
                (prop_id, uid)
            ).fetchone()
        return row, conn
    except Exception:
        conn.close()
        return None, None


def _update_step_status(conn, prop_id: str, step: str, status: str, uid: str, role: str):
    """Update the step_status JSON for a proposal."""
    row = conn.execute("SELECT step_status FROM proposals WHERE id = ?", (prop_id,)).fetchone()
    if not row:
        return
    try:
        step_status = json.loads(row["step_status"]) if row["step_status"] else {}
    except Exception:
        step_status = {}
    step_status[step] = status
    if role == "admin":
        conn.execute("UPDATE proposals SET step_status = ? WHERE id = ?", (json.dumps(step_status), prop_id))
    else:
        conn.execute("UPDATE proposals SET step_status = ? WHERE id = ? AND uid = ?", (json.dumps(step_status), prop_id, uid))
    conn.commit()


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    auth_status  = "ENABLED" if SERVER_API_KEY else "DISABLED"
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
