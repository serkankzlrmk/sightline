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

import sys
import os
import re
import json
import time
import uuid
import sqlite3
import hashlib
import threading
import subprocess
import logging
import secrets
from pathlib import Path
from queue import Queue, Empty

# ── Suppress ONNX / TensorRT log noise before any onnxruntime import ─────────
os.environ.setdefault("ORT_LOGGING_LEVEL", "3")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("ORT_TENSORRT_ENGINE_CACHE_ENABLE", "0")
os.environ.setdefault("ONNXRUNTIME_PROVIDERS", "CUDAExecutionProvider,CPUExecutionProvider")

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from flask import Flask, Response, request, jsonify, render_template, send_from_directory, g
from flask_cors import CORS

from config import (
    SERVER_HOST, SERVER_PORT, SERVER_DEBUG, SERVER_API_KEY, CORS_ORIGINS,
    DB_PATH, CHATS_DB_PATH, OUTPUT_REPORTS_DIR, DOWNLOADS_DIR, LOG_LEVEL,
    DAILY_MESSAGE_LIMIT, PREMIUM_MESSAGE_LIMIT, SSL_VERIFY, SSL_CA_BUNDLE, SECRET_KEY,
)

from auth import require_auth, require_admin, require_role, current_uid, current_role, _admins

# ── HDX Client (Humanitarian Data Exchange) ──────────────────────────────────
from reliefweb_api.hdx_tools import init_hdx_tools, get_hdx_client
from config import HDX_APP_IDENTIFIER, HDX_BASE_URL, HDX_TIMEOUT, HDX_RATE_LIMIT_REQUESTS, HDX_RATE_LIMIT_PERIOD

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
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB upload limit

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

_cors_origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()] or ["*"]
CORS(app, origins=_cors_origins, supports_credentials=False)

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
            "script-src 'self' 'unsafe-eval' https://cdn.jsdelivr.net https://unpkg.com https://www.gstatic.com https://apis.google.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https: http:; "
            "connect-src 'self' https://www.gstatic.com https://openrouter.ai https://www.googleapis.com https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://firebaseinstallations.googleapis.com https://firebaseremoteconfig.googleapis.com https://*.basemaps.cartocdn.com; "
            "frame-src https://YOUR_PROJECT.firebaseapp.com https://accounts.google.com; "
        )
    else:
        # Dev CSP — includes localhost for local development
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-eval' https://cdn.jsdelivr.net https://unpkg.com https://www.gstatic.com https://apis.google.com http://localhost:5000 http://localhost:5001; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https: http:; "
            "connect-src 'self' http://localhost:5000 http://localhost:5001 http://127.0.0.1:5000 http://127.0.0.1:5001 https://www.gstatic.com https://openrouter.ai https://www.googleapis.com https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://firebaseinstallations.googleapis.com https://firebaseremoteconfig.googleapis.com https://*.basemaps.cartocdn.com; "
            "frame-src https://YOUR_PROJECT.firebaseapp.com https://accounts.google.com; "
        )
    return response

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
_AGENT_BUSY_TIMEOUT = 600  # 10 min max — auto-unlock if stuck

# Simple per-IP rate limiter for unauthenticated endpoints
_api_rate_lock = threading.Lock()
_api_rate_counts = {}  # ip → {date: str, count: int}
_API_DAILY_LIMIT = 100

def _check_api_rate_limit():
    """Per-IP rate limit for API endpoints. Returns (ok, remaining)."""
    from datetime import date
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
    """)
    # Migration: add uid column if missing
    cols = [r[1] for r in conn.execute("PRAGMA table_info(chats)").fetchall()]
    if "uid" not in cols:
        conn.execute("ALTER TABLE chats ADD COLUMN uid TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chats_uid ON chats(uid)")
        conn.commit()
    conn.close()

_init_chats_db()

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
    from langchain_core.messages import HumanMessage, AIMessage
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
_JOBS_MAX_AGE = 3600  # Clean up completed jobs older than 1 hour

# ── Nonce store for SITREP stream auth ────────────────────────────────────────
# Replaces JWT-in-query-param (EventSource can't send Authorization headers).
# Nonces are single-use, expire after 5 minutes, tied to a UID.
_stream_nonces: dict = {}  # {nonce_str: {"uid": str, "expires": float, "used": bool}}
_stream_nonces_lock = threading.Lock()
_STREAM_NONCE_TTL = 300  # 5 minutes


def _create_stream_nonce(uid: str) -> str:
    """Create a single-use nonce for SITREP stream access, tied to a UID."""
    nonce = secrets.token_urlsafe(32)
    with _stream_nonces_lock:
        _stream_nonces[nonce] = {"uid": uid, "expires": time.time() + _STREAM_NONCE_TTL, "used": False}
    return nonce


def _consume_stream_nonce(nonce: str, uid: str) -> bool:
    """Validate and consume a stream nonce. Returns True if valid."""
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

        for raw_line in proc.stdout:
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
    rate = _check_rate_limit(uid, role)
    return jsonify({
        "uid": uid,
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "is_admin": is_admin,
        "role": role,
        "rate_limit": rate,
    })


# ═════════════════════════════════════════════════════════════════════════════
# ROUTES — Admin Role Management
# ═════════════════════════════════════════════════════════════════════════════

@app.route("/api/admin/users", methods=["GET"])
@require_admin
def api_admin_users():
    """List all Firebase Auth users with their roles.  Admin only."""
    from auth import get_user_role, _firebase_app
    fb = _firebase_app()
    if not fb:
        return jsonify({"error": "Firebase not configured"}), 503
    try:
        from firebase_admin import auth as firebase_auth
        users = []
        page = firebase_auth.list_users()
        for user_record in page.users:
            role = (user_record.custom_claims or {}).get("role", "free")
            # Fallback: check ADMIN_UIDS
            if role == "free" and user_record.uid in _admins():
                role = "admin"
            users.append({
                "uid": user_record.uid,
                "email": user_record.email or "",
                "displayName": user_record.display_name or "",
                "role": role,
                "disabled": user_record.disabled,
            })
        return jsonify({"users": users})
    except Exception as exc:
        logger.error("api_admin_users error: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to list users"}), 500


@app.route("/api/admin/users/<uid>/role", methods=["PUT"])
@require_admin
def api_admin_set_role(uid):
    """Set a user's role via Firebase Custom Claims.  Admin only."""
    from auth import set_user_role, ROLE_HIERARCHY
    data = request.get_json(silent=True) or {}
    new_role = (data.get("role") or "").strip().lower()
    if new_role not in ROLE_HIERARCHY:
        return jsonify({"error": f"Invalid role. Must be one of: {', '.join(ROLE_HIERARCHY)}"}), 400
    success = set_user_role(uid, new_role)
    if not success:
        return jsonify({"error": "Failed to set role — Firebase Admin SDK not available or user not found"}), 500
    logger.info("api_admin_set_role: uid=%s → role=%s (by admin=%s)", uid, new_role, current_uid())
    return jsonify({"ok": True, "uid": uid, "role": new_role})


@app.route("/api/admin/users/<uid>", methods=["GET"])
@require_admin
def api_admin_get_user(uid):
    """Get a single user's details including role.  Admin only."""
    from auth import get_user_role, _firebase_app
    fb = _firebase_app()
    if not fb:
        return jsonify({"error": "Firebase not configured"}), 503
    try:
        from firebase_admin import auth as firebase_auth
        user_record = firebase_auth.get_user(uid)
        role = (user_record.custom_claims or {}).get("role", "free")
        if role == "free" and user_record.uid in _admins():
            role = "admin"
        return jsonify({
            "uid": user_record.uid,
            "email": user_record.email or "",
            "displayName": user_record.display_name or "",
            "role": role,
            "disabled": user_record.disabled,
        })
    except Exception as exc:
        logger.error("api_admin_get_user error: %s", exc, exc_info=True)
        return jsonify({"error": "User not found"}), 404


@app.route("/api/admin/config", methods=["GET"])
@require_admin
def api_admin_config():
    """Get current runtime config values. Admin only."""
    from config import ACTIVE_MODEL, LLM_MODEL, LLM_PROVIDER, MODEL_TEMPERATURE, MODEL_MAX_TOKENS
    return jsonify({
        "ACTIVE_MODEL": ACTIVE_MODEL,
        "LLM_MODEL": LLM_MODEL,
        "LLM_PROVIDER": LLM_PROVIDER,
        "MODEL_TEMPERATURE": MODEL_TEMPERATURE,
        "MODEL_MAX_TOKENS": MODEL_MAX_TOKENS,
    })


@app.route("/api/admin/config", methods=["POST"])
@require_admin
def api_admin_update_config():
    """Update .env config values and reload config. Admin only.
    
    Accepts JSON body with key-value pairs to update in the .env file.
    Only whitelisted keys are allowed. After updating .env, reloads config
    and reinitializes the LLM model.
    """
    ALLOWED_KEYS = {"ACTIVE_MODEL", "LLM_MODEL", "MODEL_TEMPERATURE", "MODEL_MAX_TOKENS",
                    "LLM_MODEL_QUESTIONS", "LLM_MODEL_FILTER", "LLM_MODEL_ANSWERS"}
    data = request.get_json(silent=True) or {}
    updates = {k: v for k, v in data.items() if k in ALLOWED_KEYS}
    if not updates:
        return jsonify({"error": f"No valid keys. Allowed: {', '.join(sorted(ALLOWED_KEYS))}"}), 400

    # Read existing .env
    env_path = Path(__file__).parent / ".env"
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    
    # Update or add each key
    updated_keys = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                lines[i] = f"{key}={updates[key]}"
                updated_keys.add(key)
    # Add keys not yet in the file
    for key in updates:
        if key not in updated_keys:
            lines.append(f"{key}={updates[key]}")
    
    # Write back
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("api_admin_update_config: Updated .env keys: %s", list(updates.keys()))

    # Reload config module
    import importlib
    import config as config_module
    importlib.reload(config_module)
    # Re-import updated values into server module
    global ACTIVE_MODEL
    ACTIVE_MODEL = config_module.ACTIVE_MODEL
    logger.info("api_admin_update_config: ACTIVE_MODEL is now %s", ACTIVE_MODEL)

    # Reinitialize the LLM model if agent is loaded
    try:
        from agent.model import reinitialize_model
        reinitialize_model()
        logger.info("api_admin_update_config: LLM model reinitialized successfully")
    except Exception as e:
        logger.warning("api_admin_update_config: Could not reinitialize model: %s", e)

    return jsonify({
        "ok": True,
        "updated": list(updates.keys()),
        "ACTIVE_MODEL": config_module.ACTIVE_MODEL,
        "LLM_MODEL": config_module.LLM_MODEL,
    })


import time as _time

@app.route("/")
def index():
    return render_template("index.html", v=int(_time.time()))


# =============================================================================
# ROUTES — Health
# =============================================================================

@app.route("/api/health")
def health():
    """Enhanced health check — verifies DB, vector store, and LLM config."""
    from config import CHROMA_DIR, _LLM_API_KEY, ACTIVE_MODEL, LLM_PROVIDER, VECTOR_BACKEND

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

    # Vector store check
    checks["vector_backend"] = VECTOR_BACKEND
    if VECTOR_BACKEND == "pgvector":
        # Check Supabase connectivity
        try:
            from config import SUPABASE_URL, SUPABASE_DB_URL
            pg_ok = bool(SUPABASE_URL and SUPABASE_DB_URL)
            checks["vector"] = pg_ok
        except Exception:
            checks["vector"] = False
    else:
        # ChromaDB directory check
        chroma_ok = Path(str(CHROMA_DIR)).exists()
        checks["vector"] = chroma_ok

    # LLM config check
    llm_ok = bool(_LLM_API_KEY)
    checks["llm"] = llm_ok
    checks["llm_provider"] = LLM_PROVIDER
    checks["model"] = ACTIVE_MODEL

    # HDX check
    hdx = get_hdx_client()
    checks["hdx"] = hdx is not None

    # Release info (if available — written by deploy.sh)
    release_info_path = Path(__file__).parent / "RELEASE_INFO"
    if release_info_path.exists():
        try:
            for line in release_info_path.read_text().strip().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    checks[f"release_{k.lower()}"] = v
        except Exception:
            pass

    # Overall status: ok only if all critical checks pass
    all_ok = db_ok and checks.get("vector", False) and llm_ok
    checks["status"] = "ok" if all_ok else "degraded"

    # Dev mode flag — frontend uses this to auto-bypass auth overlay
    from auth import _dev_mode
    checks["dev_mode"] = _dev_mode()

    code = 200 if all_ok else 503
    return jsonify(checks), code


# =============================================================================
# ROUTES — /api/agent/*    (multi-chat with LangGraph agent)
# =============================================================================

@app.route("/api/agent/chats")
@require_auth
def api_agent_chats():
    """List all chats for the current user, newest first."""
    uid = current_uid()
    items = _db_get_chats_by_uid(uid)
    active = _user_active_chat.get(uid, None)
    return jsonify({"chats": items, "active": active})


@app.route("/api/agent/chats/new", methods=["POST"])
@require_auth
def api_agent_chats_new():
    """Create a new chat and make it active."""
    uid = current_uid()
    cid = _new_chat_id()
    _db_create_chat(cid, uid=uid)
    _user_active_chat[uid] = cid
    return jsonify({"id": cid})


@app.route("/api/agent/chats/new-with-context", methods=["POST"])
@require_auth
def api_agent_chats_new_with_context():
    """Create a new chat pre-loaded with a context message (e.g. SITREP)."""
    uid = current_uid()
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "New Chat")[:120]
    context_text = (data.get("context") or "").strip()
    if not context_text:
        return jsonify({"error": "context required"}), 400
    cid = _new_chat_id()
    _db_create_chat(cid, uid=uid)
    _db_rename_chat(cid, title)
    _db_add_message(cid, "assistant", context_text)
    _user_active_chat[uid] = cid
    return jsonify({"id": cid, "active": cid})


@app.route("/api/agent/chats/<chat_id>/select", methods=["POST"])
@require_auth
def api_agent_chats_select(chat_id):
    """Switch active chat."""
    uid = current_uid()
    if not _db_chat_belongs_to(chat_id, uid):
        return jsonify({"error": "Chat not found"}), 404
    _user_active_chat[uid] = chat_id
    return jsonify({"ok": True, "id": chat_id})


@app.route("/api/agent/chats/<chat_id>/messages")
@require_auth
def api_agent_chats_messages(chat_id):
    """Return all messages for a chat (for rendering on switch)."""
    uid = current_uid()
    if not _db_chat_belongs_to(chat_id, uid):
        return jsonify({"error": "Chat not found"}), 404
    msgs = _db_get_messages(chat_id)
    return jsonify({"messages": msgs})


@app.route("/api/agent/chats/<chat_id>/rename", methods=["POST"])
@require_auth
def api_agent_chats_rename(chat_id):
    uid = current_uid()
    if not _db_chat_belongs_to(chat_id, uid):
        return jsonify({"error": "Chat not found"}), 404
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()[:100]
    if not title:
        return jsonify({"error": "title required"}), 400
    _db_rename_chat(chat_id, title)
    return jsonify({"ok": True})


@app.route("/api/agent/chats/<chat_id>", methods=["DELETE"])
@require_auth
def api_agent_chats_delete(chat_id):
    """Delete a chat."""
    uid = current_uid()
    if not _db_chat_belongs_to(chat_id, uid):
        return jsonify({"error": "Chat not found"}), 404
    _db_delete_chat(chat_id)
    if _user_active_chat.get(uid) == chat_id:
        _user_active_chat.pop(uid, None)
    _ensure_active_chat(uid)
    return jsonify({"ok": True, "active": _user_active_chat.get(uid)})


@app.route("/api/agent/chat", methods=["POST"])
@require_auth
def api_agent_chat():

    uid = current_uid()
    role = current_role()

    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "empty message"}), 400

    # Rate limit check (role-aware: admin=unlimited, premium=100, free=10)
    if role != "admin":
        rate = _check_rate_limit(uid, role)
        if rate["remaining"] <= 0:
            return jsonify({
                "error": "Daily message limit reached",
                "limit": rate["limit"],
                "used": rate["used"],
                "remaining": 0,
            }), 429

    # Auto-unlock if stuck (client disconnected, finally didn't run)
    if uid in _user_agent_busy and _user_agent_busy.get(uid, False):
        if (_time.time() - _user_agent_busy_since.get(uid, 0)) > _AGENT_BUSY_TIMEOUT:
            logger.warning("Agent busy flag stuck for uid=%s >%ds, auto-resetting", uid, _AGENT_BUSY_TIMEOUT)
            _user_agent_busy[uid] = False

    if _user_agent_busy.get(uid, False):
        return jsonify({"error": "Agent is busy processing your previous message, please wait"}), 429

    chat_id = _ensure_active_chat(uid)
    if role != "admin":
        _increment_rate_limit(uid)

    from langchain_core.messages import HumanMessage, AIMessage

    def generate():
        _user_agent_busy[uid] = True
        _user_agent_busy_since[uid] = _time.time()

        try:
            # Save user message to DB and load full history
            _db_add_message(chat_id, "user", user_message)
            messages_snapshot = _load_langchain_messages(chat_id)

            agent = _get_agent()
            full_response = ""

            for chunk, metadata in agent.stream(
                {"messages": messages_snapshot},
                config={"recursion_limit": 25},
                stream_mode="messages",
            ):
                node = metadata.get("langgraph_node", "")

                if node == "llm_call":
                    if hasattr(chunk, "content") and isinstance(chunk.content, str) and chunk.content:
                        full_response += chunk.content
                        yield f"data: {json.dumps({'type': 'token', 'text': chunk.content})}\n\n"

                    if hasattr(chunk, "tool_call_chunks") and chunk.tool_call_chunks:
                        for tcc in chunk.tool_call_chunks:
                            name = (
                                tcc.get("name", "") if isinstance(tcc, dict)
                                else getattr(tcc, "name", "")
                            ) or ""
                            if name:
                                yield f"data: {json.dumps({'type': 'tool_start', 'name': name})}\n\n"

                elif node == "tool_node":
                    tool_name = getattr(chunk, "name", "") or ""
                    yield f"data: {json.dumps({'type': 'tool_done', 'name': tool_name})}\n\n"

            if full_response:
                _db_add_message(chat_id, "assistant", full_response)

                # Auto-generate title with LLM after first exchange
                conn = _chats_db()
                row = conn.execute("SELECT title FROM chats WHERE id = ?", (chat_id,)).fetchone()
                conn.close()
                if row and row["title"] == "New Chat":
                    _generate_chat_title(chat_id, user_message, full_response)

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            logger.exception("Agent chat error")
            yield f"data: {json.dumps({'type': 'error', 'text': 'An error occurred during processing'})}\n\n"
        finally:
            _user_agent_busy[uid] = False

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/agent/chat/reset", methods=["POST"])
@require_auth
def api_agent_chat_reset():
    """Reset the active chat (clear messages)."""
    uid = current_uid()
    chat_id = _ensure_active_chat(uid)
    _db_clear_messages(chat_id)
    return jsonify({"ok": True})


@app.route("/api/agent/chat/unlock", methods=["POST"])
@require_admin
def api_agent_chat_unlock():
    """Force-unlock the agent busy flag for a specific user (emergency reset)."""
    target_uid = request.json.get("uid") if request.is_json else None
    if target_uid:
        was_busy = _user_agent_busy.get(target_uid, False)
        _user_agent_busy[target_uid] = False
        return jsonify({"ok": True, "was_busy": was_busy, "uid": target_uid})
    else:
        # Unlock all users
        busy_count = sum(1 for v in _user_agent_busy.values() if v)
        _user_agent_busy.clear()
        return jsonify({"ok": True, "unlocked_count": busy_count})


@app.route("/api/agent/chat/status")
@require_auth
def api_agent_chat_status():
    uid = current_uid()
    chat_id = _ensure_active_chat(uid)
    msg_count = len(_db_get_messages(chat_id))
    return jsonify({
        "busy": _user_agent_busy.get(uid, False),
        "history_len": msg_count,
        "active_chat": chat_id,
    })


# =============================================================================
# ROUTES — /api/db/*    (SQLite reports browser)
# =============================================================================

@app.route("/api/db/stats")
@require_auth
def api_db_stats():
    conn = _db_conn()
    try:
        report_count = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        chunk_count  = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        country_rows = conn.execute("SELECT countries FROM reports").fetchall()
        source_rows  = conn.execute("SELECT source FROM reports").fetchall()
    except Exception:
        conn.close()
        return jsonify({"report_count": 0, "chunk_count": 0, "top_countries": [], "top_sources": []})
    finally:
        try:
            conn.close()
        except Exception:
            pass

    country_counts: dict = {}
    for r in country_rows:
        for c in _parse_countries(r[0]):
            country_counts[c] = country_counts.get(c, 0) + 1

    source_counts: dict = {}
    for r in source_rows:
        s = r[0] or "?"
        source_counts[s] = source_counts.get(s, 0) + 1

    return jsonify({
        "report_count": report_count,
        "chunk_count":  chunk_count,
        "top_countries": sorted(country_counts.items(), key=lambda x: -x[1])[:15],
        "top_sources":   sorted(source_counts.items(), key=lambda x: -x[1])[:10],
    })


@app.route("/api/db/countries")
@require_auth
def api_db_countries():
    conn = _db_conn()
    try:
        rows = conn.execute("SELECT countries FROM reports").fetchall()
    except Exception:
        return jsonify([])
    finally:
        conn.close()
    all_countries = set()
    for r in rows:
        for c in _parse_countries(r[0]):
            all_countries.add(c)
    return jsonify(sorted(all_countries))


@app.route("/api/db/sources")
@require_auth
def api_db_sources():
    conn = _db_conn()
    try:
        rows = conn.execute("SELECT DISTINCT source FROM reports ORDER BY source").fetchall()
    except Exception:
        return jsonify([])
    finally:
        conn.close()
    return jsonify([r[0] for r in rows if r[0]])


@app.route("/api/db/reports")
@require_auth
def api_db_reports():
    search   = request.args.get("search",   "").strip()
    country  = request.args.get("country",  "").strip()
    source   = request.args.get("source",   "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to   = request.args.get("date_to",   "").strip()

    conn = _db_conn()
    try:
        query = (
            "SELECT report_id, title, date, countries, source, themes, "
            "format_type, has_pdf, has_content, total_chunks, url "
            "FROM reports WHERE 1=1"
        )
        params = []

        if search:
            query += " AND title LIKE ?"
            params.append(f"%{search}%")
        if source:
            query += " AND source = ?"
            params.append(source)
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)

        query += " ORDER BY date DESC"
        rows = conn.execute(query, params).fetchall()
    except Exception:
        return jsonify([])
    finally:
        conn.close()

    results = []
    for r in rows:
        d = _row_to_dict(r)
        clist = _parse_countries(d.get("countries"))
        if country and not any(country == c for c in clist):
            continue
        d["primary_country"] = clist[0] if clist else ""
        d["all_countries"]   = clist
        results.append(d)

    return jsonify(results)


@app.route("/api/db/reports/<int:report_id>")
@require_auth
def api_db_report_detail(report_id):
    conn = _db_conn()
    try:
        row = conn.execute(
            "SELECT * FROM reports WHERE report_id=?", (report_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404

        d = _row_to_dict(row)
        d["all_countries"] = _parse_countries(d.get("countries"))
        try:
            d["themes_list"] = json.loads(d.get("themes") or "[]")
        except Exception:
            d["themes_list"] = []

        chunks = conn.execute(
            "SELECT chunk_index, source_type, content FROM chunks "
            "WHERE report_id=? ORDER BY chunk_index LIMIT 3",
            (report_id,),
        ).fetchall()
        d["chunks_preview"] = [dict(c) for c in chunks]
    except Exception as e:
        logger.error("api_db_report_detail error: %s", e, exc_info=True)
        return jsonify({"error": "Failed to load report detail"}), 500
    finally:
        conn.close()

    return jsonify(d)


# =============================================================================
# ROUTES — /api/sitrep/*    (SITREP pipeline runner)
# =============================================================================

@app.route("/api/sitrep/themes")
@require_auth
def api_sitrep_themes():
    """Return unique theme values — ChromaDB first, SQLite fallback."""
    try:
        from sitrep.chroma_adapter import ChromaAdapter
        db = ChromaAdapter()
        return jsonify(db.list_themes())
    except Exception as exc:
        logger.error("api_sitrep_themes error: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load themes"}), 500


@app.route("/api/sitrep/countries")
@require_auth
def api_sitrep_countries():
    """Return country values with chunk counts for SITREP dropdown."""
    try:
        from sitrep.chroma_adapter import ChromaAdapter
        db = ChromaAdapter()
        return jsonify(db.list_countries_with_counts())
    except Exception as exc:
        logger.error("api_sitrep_countries error: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load countries"}), 500


@app.route("/api/sitrep/date-range/<country>")
@require_auth
def api_sitrep_date_range(country):
    try:
        from sitrep.chroma_adapter import ChromaAdapter
        db = ChromaAdapter()
        return jsonify(db.get_date_range(country))
    except Exception as exc:
        logger.error("api_sitrep_date_range error: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load date range"}), 500


@app.route("/api/sitrep/chunk-preview", methods=["POST"])
@require_auth
def api_sitrep_chunk_preview():
    """Return chunk count and theme breakdown matching the given filters."""
    try:
        from sitrep.chroma_adapter import ChromaAdapter
        db = ChromaAdapter()
        data = request.get_json(silent=True) or {}
        country = data.get("country", "").strip()
        if not country:
            return jsonify({"error": "country is required"}), 400

        themes = [t.strip() for t in data.get("themes", []) if t.strip()]
        date_from = (data.get("date_from") or "").strip()
        date_to = (data.get("date_to") or "").strip()

        chunks = db.get_chunks_by_country_and_themes(
            country, themes or None, date_from=date_from or None, date_to=date_to or None,
        )
        from collections import Counter
        theme_counts = Counter()
        for c in chunks:
            raw = c.get("themes", "")
            if raw:
                for t in raw.split(","):
                    t = t.strip()
                    if t:
                        theme_counts[t] += 1
        top_themes = [k for k, _ in theme_counts.most_common(5)]

        return jsonify({
            "count": len(chunks),
            "themes_found": top_themes,
            "filters": {"themes": themes, "date_from": date_from, "date_to": date_to},
        })
    except Exception as exc:
        logger.error("api_sitrep_chunk_preview error: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load chunk preview"}), 500


@app.route("/api/sitrep/run", methods=["POST"])
@require_role("premium")
def api_sitrep_run():
    data    = request.get_json(silent=True) or {}
    country = data.get("country", "").strip()[:100]
    event   = data.get("event",   "").strip()[:200]
    if not country:
        return jsonify({"error": "country is required"}), 400
    if not event:
        event = country

    themes     = [t.strip()[:80] for t in data.get("themes", []) if t.strip()][:10]
    skip_cache = bool(data.get("skip_cache", False))
    date_from  = (data.get("date_from") or "").strip()[:10]
    date_to    = (data.get("date_to")   or "").strip()[:10]

    _DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    if date_from and not _DATE_RE.match(date_from):
        return jsonify({"error": "Invalid date_from format (YYYY-MM-DD)"}), 400
    if date_to and not _DATE_RE.match(date_to):
        return jsonify({"error": "Invalid date_to format (YYYY-MM-DD)"}), 400

    cmd = [sys.executable, str(BASE_DIR / "sitrep" / "pipeline.py"),
           "--country", country, "--event", event]
    if themes:
        cmd += ["--themes"] + themes
    if date_from:
        cmd += ["--date-from", date_from]
    if date_to:
        cmd += ["--date-to", date_to]
    if skip_cache:
        cmd.append("--skip-cache")

    job_id = uuid.uuid4().hex[:8]
    with _jobs_lock:
        # Clean up old completed jobs to prevent memory leak
        now = _time.time()
        stale = [jid for jid, j in _jobs.items()
                 if j.get("status") in ("done", "error") and
                 now - j.get("finished_at", now) > _JOBS_MAX_AGE]
        for jid in stale:
            del _jobs[jid]

        _jobs[job_id] = {
            "queue":   Queue(),
            "status":  "running",
            "proc":    None,
            "country": country,
            "event":   event,
        }

    t = threading.Thread(target=_run_job, args=(job_id, cmd), daemon=True)
    t.start()
    nonce = _create_stream_nonce(current_uid())
    return jsonify({"job_id": job_id, "stream_nonce": nonce})


@app.route("/api/sitrep/stream/<job_id>")
def api_sitrep_stream(job_id):
    from auth import _api_key, verify_firebase_token, _dev_mode

    uid = ""

    if not _dev_mode():
        api_key = _api_key()
        if api_key:
            provided = request.args.get("api_key", "") or request.headers.get("X-API-Key", "")
            if not secrets.compare_digest(provided, api_key):
                return jsonify({"error": "Invalid API key"}), 403
            uid = "api-key"
        else:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[len("Bearer "):].strip()
            else:
                token = request.args.get("token", "")
            if not token:
                nonce = request.args.get("nonce", "")
                if nonce and _consume_stream_nonce(nonce, ""):
                    uid = "nonce"
                else:
                    return jsonify({"error": "Missing token or valid nonce"}), 401
            if uid != "nonce":
                try:
                    decoded = verify_firebase_token(token)
                    uid = decoded.get("uid", "")
                except Exception:
                    nonce = request.args.get("nonce", "")
                    if nonce and _consume_stream_nonce(nonce, uid):
                        uid = uid or "nonce"
                    else:
                        return jsonify({"error": "Invalid token"}), 401
    else:
        uid = "dev-local"

    _cleanup_stream_nonces()

    if job_id not in _jobs:
        return jsonify({"error": "Unknown job id"}), 404

    def generate():
        q = _jobs[job_id]["queue"]
        while True:
            try:
                line = q.get(timeout=25)
                if line is None:
                    status = _jobs[job_id].get("status", "done")
                    yield f"data: __DONE__{status}\n\n"
                    break
                safe = line.replace("\n", " ").replace("\r", "")
                yield f"data: {safe}\n\n"
            except Empty:
                yield "data: __PING__\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/sitrep/job/<job_id>")
@require_auth
def api_sitrep_job(job_id):
    if job_id not in _jobs:
        return jsonify({"error": "Unknown job id"}), 404
    j = _jobs[job_id]
    return jsonify({
        "job_id":  job_id,
        "status":  j.get("status", "running"),
        "country": j.get("country", ""),
        "event":   j.get("event",   ""),
    })


@app.route("/api/sitrep/reports")
@require_auth
def api_sitrep_reports():
    items = []
    if OUTPUT_REPORTS_DIR.exists():
        for f in sorted(
            OUTPUT_REPORTS_DIR.glob("*report.json"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        ):
            items.append({
                "filename": f.name,
                "size_kb":  round(f.stat().st_size / 1024, 1),
                "mtime":    f.stat().st_mtime,
            })
    return jsonify(items)


@app.route("/api/sitrep/report")
@require_auth
def api_sitrep_report():
    filename = request.args.get("file", "")
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        return jsonify({"error": "Invalid filename"}), 400
    path = (OUTPUT_REPORTS_DIR / filename).resolve()
    if not str(path).startswith(str(OUTPUT_REPORTS_DIR.resolve())):
        return jsonify({"error": "Invalid filename"}), 400
    if not path.exists():
        return jsonify({"error": "Report not found"}), 404
    return path.read_text(encoding="utf-8"), 200, {"Content-Type": "application/json"}


# =============================================================================
# ROUTES — Weekly Bulletin
# =============================================================================

@app.route("/api/sitrep/bulletins")
@require_auth
def api_bulletin_list():
    """List available weekly bulletins, sorted by date descending."""
    from sitrep.weekly_bulletin import list_bulletins
    bulletins = list_bulletins()
    return jsonify(bulletins)


@app.route("/api/sitrep/bulletin/<filename>")
@require_auth
def api_bulletin_get(filename):
    """Get a specific bulletin JSON by filename."""
    from sitrep.weekly_bulletin import get_bulletin
    if ".." in filename or "/" in filename or "\\" in filename:
        return jsonify({"error": "Invalid filename"}), 400
    bulletin = get_bulletin(filename)
    if bulletin is None:
        return jsonify({"error": "Bulletin not found"}), 404
    return jsonify(bulletin)


@app.route("/api/sitrep/bulletin/generate", methods=["POST"])
@require_admin
def api_bulletin_generate():
    """Manually trigger bulletin generation (admin only).
    
    Accepts optional JSON body: {"date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD"}
    If no dates provided, defaults to last week (Mon-Sun).
    
    Runs generation in a background thread and returns a job_id immediately.
    Frontend can poll /api/sitrep/bulletin/generate/status/<job_id> for progress.
    """
    from sitrep.weekly_bulletin import generate_weekly_bulletin
    from datetime import datetime, timedelta
    
    data = request.get_json(silent=True) or {}
    date_from = data.get("date_from", "")
    date_to = data.get("date_to", "")
    
    if not date_from or not date_to:
        # Default to last week
        today = datetime.now()
        last_monday = today - timedelta(days=today.weekday() + 7)
        last_sunday = last_monday + timedelta(days=6)
        date_from = date_from or last_monday.strftime("%Y-%m-%d")
        date_to = date_to or last_sunday.strftime("%Y-%m-%d")
    
    # Create a job for background generation
    job_id = f"bulletin-{_time.time():.0f}"
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "queue":   Queue(),
            "started_at": _time.time(),
            "type": "bulletin",
            "date_from": date_from,
            "date_to": date_to,
        }
    
    def _run_bulletin():
        q = _jobs[job_id]["queue"]
        try:
            q.put(f"Generating bulletin for {date_from} to {date_to}...")
            path = generate_weekly_bulletin(date_from=date_from, date_to=date_to)
            q.put(f"Bulletin saved: {path.name}")
            with _jobs_lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["finished_at"] = _time.time()
                _jobs[job_id]["result"] = {
                    "filename": path.name,
                    "date_from": date_from,
                    "date_to": date_to,
                }
        except Exception as exc:
            logging.exception("Bulletin generation failed")
            q.put(f"[ERROR] {exc}")
            with _jobs_lock:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["finished_at"] = _time.time()
                _jobs[job_id]["error"] = str(exc)
        finally:
            q.put(None)  # sentinel
    
    thread = threading.Thread(target=_run_bulletin, daemon=True)
    thread.start()
    
    return jsonify({
        "status": "started",
        "job_id": job_id,
        "message": f"Generating bulletin for {date_from} to {date_to}",
        "date_from": date_from,
        "date_to": date_to,
    })


@app.route("/api/sitrep/bulletin/generate/status/<job_id>")
@require_admin
def api_bulletin_generate_status(job_id):
    """Poll bulletin generation job status (admin only)."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    
    # Collect any new log lines from the queue
    logs = []
    q = job["queue"]
    try:
        while True:
            line = q.get_nowait()
            if line is None:
                break
            logs.append(line)
    except Empty:
        pass
    
    response = {
        "status": job["status"],
        "logs": logs,
        "date_from": job.get("date_from", ""),
        "date_to": job.get("date_to", ""),
    }
    if job["status"] == "done" and "result" in job:
        response["result"] = job["result"]
    if job["status"] == "error" and "error" in job:
        response["error"] = job["error"]
    
    return jsonify(response)


# =============================================================================
# ROUTES — HDX (Humanitarian Data Exchange)
# =============================================================================

@app.route("/api/hdx/health")
def api_hdx_health():
    """HDX connectivity check. No auth required — just checks if client is initialized."""
    hdx = get_hdx_client()
    if not hdx:
        return jsonify({
            "status": "not_configured",
            "message": "HDX_APP_IDENTIFIER not set. Set it in .env to enable HDX data.",
        }), 503
    return jsonify({
        "status": "ok",
        "base_url": hdx.base_url,
        "cache_stats": hdx.cache.stats(),
    })


@app.route("/api/hdx/availability/<country_code>")
@require_role("premium")
def api_hdx_availability(country_code):
    """Check what HDX data categories are available for a country."""
    hdx = get_hdx_client()
    if not hdx:
        return jsonify({"error": "HDX client not configured"}), 503
    result = hdx.get_data_availability_sync(location_code=country_code.upper())
    return jsonify(result.to_dict())


@app.route("/api/hdx/overview/<country_code>")
@require_role("premium")
def api_hdx_overview(country_code):
    """Get comprehensive humanitarian data overview for a country (9 parallel endpoints)."""
    hdx = get_hdx_client()
    if not hdx:
        return jsonify({"error": "HDX client not configured"}), 503
    result = hdx.get_country_overview_sync(country_code.upper())
    return jsonify({k: v.to_dict() for k, v in result.items()})


@app.route("/api/hdx/refugees/<country_code>")
@require_role("premium")
def api_hdx_refugees(country_code):
    """Get refugee/persons of concern data for a country."""
    hdx = get_hdx_client()
    if not hdx:
        return jsonify({"error": "HDX client not configured"}), 503
    limit = request.args.get("limit", 10, type=int)
    result = hdx.get_refugees_sync(location_code=country_code.upper(), limit=min(limit, 50))
    return jsonify(result.to_dict())


@app.route("/api/hdx/idps/<country_code>")
@require_role("premium")
def api_hdx_idps(country_code):
    """Get internally displaced persons (IDP) data for a country."""
    hdx = get_hdx_client()
    if not hdx:
        return jsonify({"error": "HDX client not configured"}), 503
    limit = request.args.get("limit", 10, type=int)
    result = hdx.get_idps_sync(location_code=country_code.upper(), limit=min(limit, 50))
    return jsonify(result.to_dict())


@app.route("/api/hdx/funding/<country_code>")
@require_role("premium")
def api_hdx_funding(country_code):
    """Get humanitarian funding data for a country."""
    hdx = get_hdx_client()
    if not hdx:
        return jsonify({"error": "HDX client not configured"}), 503
    limit = request.args.get("limit", 10, type=int)
    result = hdx.get_funding_sync(location_code=country_code.upper(), limit=min(limit, 50))
    return jsonify(result.to_dict())


@app.route("/api/hdx/conflict/<country_code>")
@require_role("premium")
def api_hdx_conflict(country_code):
    """Get conflict events data (ACLED) for a country."""
    hdx = get_hdx_client()
    if not hdx:
        return jsonify({"error": "HDX client not configured"}), 503
    limit = request.args.get("limit", 10, type=int)
    result = hdx.get_conflict_events_sync(location_code=country_code.upper(), limit=min(limit, 50))
    return jsonify(result.to_dict())


@app.route("/api/hdx/cache/stats")
@require_admin
def api_hdx_cache_stats():
    """Get HDX cache statistics (admin only)."""
    hdx = get_hdx_client()
    if not hdx:
        return jsonify({"error": "HDX client not configured"}), 503
    return jsonify(hdx.cache.stats())


@app.route("/api/hdx/cache/clear", methods=["POST"])
@require_admin
def api_hdx_cache_clear():
    """Clear HDX cache (admin only)."""
    hdx = get_hdx_client()
    if not hdx:
        return jsonify({"error": "HDX client not configured"}), 503
    hdx.cache.clear()
    return jsonify({"status": "cache_cleared"})


# =============================================================================
# ROUTES — Ingest (daily auto-ingest + manual PDF upload)
# =============================================================================

@app.route("/api/ingest/daily", methods=["POST"])
@require_admin
def api_ingest_daily():
    """Run daily ingestion: fetch yesterday's reports + purge old data.
    
    Accepts optional JSON body: {"date": "YYYY-MM-DD", "purge_days": 90, "no_purge": false}
    Returns: {fetched, ingested, skipped, errors, purged_sql, purged_chroma}
    """
    import subprocess
    
    data = request.get_json(silent=True) or {}
    target_date = data.get("date", "")  # empty = yesterday
    purge_days = data.get("purge_days", 90)
    no_purge = data.get("no_purge", False)
    
    # Build command
    cmd = [sys.executable, str(Path(__file__).parent / "scripts" / "daily_ingest.py")]
    if target_date:
        cmd += ["--date", target_date]
    if no_purge:
        cmd.append("--no-purge")
    cmd += ["--purge-days", str(purge_days)]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min max
            cwd=str(Path(__file__).parent),
        )
        output = result.stdout + result.stderr
        
        # Parse the summary from output
        summary = {
            "fetched": 0, "ingested": 0, "skipped": 0, "errors": 0,
            "purged_sql": 0, "purged_chroma": 0,
            "log": output[-2000:] if len(output) > 2000 else output,
        }
        import re
        for line in output.splitlines():
            m = re.search(r"Fetched:\s+(\d+)", line)
            if m: summary["fetched"] = int(m.group(1))
            m = re.search(r"Ingested:\s+(\d+)", line)
            if m: summary["ingested"] = int(m.group(1))
            m = re.search(r"Skipped:\s+(\d+)", line)
            if m: summary["skipped"] = int(m.group(1))
            m = re.search(r"Errors:\s+(\d+)", line)
            if m: summary["errors"] = int(m.group(1))
            m = re.search(r"Purged \(SQL\):\s+(\d+)", line)
            if m: summary["purged_sql"] = int(m.group(1))
            m = re.search(r"Purged \(Vec\):\s+(\d+)", line)
            if m: summary["purged_chroma"] = int(m.group(1))
        
        if result.returncode != 0:
            summary["warning"] = "Script exited with non-zero code (some errors occurred)"
        
        return jsonify(summary)
        
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Daily ingest timed out (10 min limit)"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


MANUAL_ID_BASE = 9_000_000_000   # manual TR-prefixed IDs start above this

@app.route("/api/ingest/upload", methods=["POST"])
@require_admin
def api_ingest_upload():
    """Upload a PDF with user-supplied metadata → SQLite + ChromaDB."""
    import tempfile, shutil
    from reliefweb_api.db_manager import (
        DatabaseManager, extract_pdf_text, chunk_text,
        build_chunk_with_header, CHUNK_SIZE, CHUNK_OVERLAP,
    )
    from reliefweb_api.vector_store import VectorStore

    title       = (request.form.get("title")       or "").strip()[:500]
    source      = (request.form.get("source")      or "").strip()[:200]
    country     = (request.form.get("country")     or "").strip()[:500]
    format_type = (request.form.get("format_type") or "").strip()[:100]
    language    = (request.form.get("language")    or "").strip()[:10]
    date_str    = (request.form.get("date")        or "").strip()[:10]
    theme       = (request.form.get("theme")       or "").strip()[:1000]
    pdf_file    = request.files.get("pdf")

    missing = [f for f, v in [
        ("title", title), ("source", source), ("country", country),
        ("format_type", format_type), ("language", language), ("date", date_str),
    ] if not v]
    if not pdf_file or not pdf_file.filename:
        missing.append("pdf")
    if missing:
        return jsonify({"error": "Missing required fields", "fields": missing}), 400

    if not pdf_file.mimetype or pdf_file.mimetype not in ("application/pdf",):
        return jsonify({"error": "Only PDF files are accepted"}), 400

    conn = _db_conn()
    try:
        max_row = conn.execute(
            "SELECT MAX(report_id) FROM reports WHERE report_id > ?", (MANUAL_ID_BASE,)
        ).fetchone()
    finally:
        conn.close()
    new_id     = (max_row[0] or MANUAL_ID_BASE) + 1
    tr_display = f"TR-{new_id - MANUAL_ID_BASE:05d}"

    tmp      = tempfile.mkdtemp()
    try:
        safe_nm  = re.sub(r'[/\\]', '_', pdf_file.filename)
        pdf_path = os.path.join(tmp, safe_nm)
        pdf_file.save(pdf_path)

        pdf_text, pdf_pages = extract_pdf_text(pdf_path)
        if not pdf_text.strip():
            return jsonify({"error": "Could not extract text from PDF"}), 422

        countries_list = [c.strip() for c in country.split(",") if c.strip()]
        themes_list    = [t.strip() for t in theme.split(",")   if t.strip()]
        metadata = {
            "id":        new_id,
            "title":     title,
            "date":      {"original": date_str},
            "source":    [{"shortname": source}],
            "countries": [{"name": c} for c in countries_list],
            "themes":    [{"name": t} for t in themes_list],
            "format":    [{"name": format_type}],
            "language":  [{"code": language}],
            "url":       f"manual://{tr_display}",
        }

        chunks = []
        for raw in chunk_text(pdf_text, CHUNK_SIZE, CHUNK_OVERLAP):
            enriched = build_chunk_with_header(raw, metadata, "pdf")
            chunks.append({"source_type": "pdf", "content": enriched})

        try:
            db = DatabaseManager(str(DB_PATH))
            db.insert_report(metadata, chunks, has_pdf=True, has_content=False, pdf_pages=pdf_pages)
            db.close()
        except Exception as e:
            logger.error("Upload DB insert failed: %s", e, exc_info=True)
            return jsonify({"error": "Database insert failed"}), 500

        try:
            from config import CHROMA_DIR
            vs = VectorStore(str(CHROMA_DIR))
            vs.add_report(new_id, chunks, metadata)
        except Exception as e:
            logger.error("Upload vector store insert failed: %s", e, exc_info=True)
            return jsonify({"error": "Vector store insert failed"}), 500

        return jsonify({
            "success":      True,
            "report_id":    new_id,
            "tr_id":        tr_display,
            "title":        title,
            "chunks_added": len(chunks),
            "pdf_pages":    pdf_pages,
        })
    finally:
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass


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
