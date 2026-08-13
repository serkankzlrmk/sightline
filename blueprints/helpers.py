"""
blueprints/helpers.py — Shared helpers for Flask Blueprints.

Centralises database access, rate limiting, chat state, event logging,
SITREP job management, and other utilities used across multiple blueprints.

Blueprints should import from this module instead of importing server.py
directly, to avoid circular dependencies.
"""

import json
import logging
import os
import re
import secrets
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path

from config import (
    CHATS_DB_PATH,
    DB_PATH,
    DAILY_MESSAGE_LIMIT,
    PREMIUM_MESSAGE_LIMIT,
    SITREP_JOB_TIMEOUT,
)

logger = logging.getLogger(__name__)

# ── Chat database connection ─────────────────────────────────────────────────

_chats_lock = threading.Lock()
_user_active_chat = {}  # uid → chat_id
_user_active_chat_lock = threading.Lock()
_user_agent_busy = {}  # uid → bool
_user_agent_busy_since = {}  # uid → timestamp
_user_agent_busy_lock = threading.Lock()
_AGENT_BUSY_TIMEOUT = int(os.getenv("AGENT_BUSY_TIMEOUT", "120"))

# ── Per-IP API rate limiting ─────────────────────────────────────────────────

_api_rate_lock = threading.Lock()
_api_rate_counts = {}  # ip → {date: str, count: int}
_API_DAILY_LIMIT = int(os.getenv("API_DAILY_LIMIT", "100"))

# ── SITREP job runner state ──────────────────────────────────────────────────

_jobs: dict = {}
_jobs_lock = threading.Lock()
_JOBS_MAX_AGE = int(os.getenv("SITREP_JOBS_MAX_AGE", "3600"))

# ── Nonce store for SITREP stream auth ───────────────────────────────────────

_stream_nonces: dict = {}
_stream_nonces_lock = threading.Lock()
_STREAM_NONCE_TTL = int(os.getenv("STREAM_NONCE_TTL", "300"))

# ── ANSI / GPU noise suppression ─────────────────────────────────────────────

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mGKHF]")
_NOISE = [
    "onnxruntime",
    "tensorrt",
    "cublas",
    "cudnn",
    "ep error",
    "falling back to",
    "onnxruntime_providers",
    "executionprovider",
    "requires",
    "from tensorrt",
    "cann execution",
    "cublaslt",
    "provider_bridge_ort",
    "cudaexecutionprovider",
    "tensorrtexecutionprovider",
]


# ═══════════════════════════════════════════════════════════════════════════
# Database connections
# ═══════════════════════════════════════════════════════════════════════════


def chats_db():
    """Return a connection to the chats SQLite database."""
    conn = sqlite3.connect(str(CHATS_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def db_conn():
    """Return a connection to the reliefweb SQLite database with WAL mode."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def row_to_dict(row):
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row)


def parse_countries(json_str):
    """Parse a JSON string of countries, returning [] on failure."""
    try:
        return json.loads(json_str or "[]")
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════════
# Rate limiting
# ═══════════════════════════════════════════════════════════════════════════


def check_api_rate_limit():
    """Per-IP rate limit for API endpoints. Returns (ok, remaining)."""
    from datetime import date
    from flask import request
    from auth import _dev_mode

    if _dev_mode():
        return True, 9999
    today = date.today().isoformat()
    ip = request.remote_addr or "0.0.0.0"
    with _api_rate_lock:
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


def check_rate_limit(uid: str, role: str = "free") -> dict:
    """Check daily message count for a user. Returns {remaining, limit, used}."""
    from datetime import date

    today = date.today().isoformat()
    conn = chats_db()
    try:
        row = conn.execute("SELECT date, count FROM rate_limits WHERE uid = ?", (uid,)).fetchone()
        if row and row["date"] == today:
            used = row["count"]
        else:
            used = 0
    finally:
        conn.close()
    if role == "admin":
        limit = 999
    elif role == "premium":
        limit = PREMIUM_MESSAGE_LIMIT
    else:
        limit = DAILY_MESSAGE_LIMIT
    remaining = max(0, limit - used)
    allowed = remaining > 0
    return {"remaining": remaining, "limit": limit, "used": used, "allowed": allowed}


def check_and_increment_rate_limit(uid: str, role: str = "free") -> dict:
    """Atomically check the daily rate limit AND increment the counter.
    Returns {remaining, limit, used, allowed}.
    """
    from datetime import date

    today = date.today().isoformat()
    if role == "admin":
        limit = 999
    elif role == "premium":
        limit = PREMIUM_MESSAGE_LIMIT
    else:
        limit = DAILY_MESSAGE_LIMIT
    conn = chats_db()
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        with conn:
            row = conn.execute("SELECT date, count FROM rate_limits WHERE uid = ?", (uid,)).fetchone()
            if row and row["date"] == today:
                used = row["count"]
            else:
                used = 0
            allowed = used < limit
            if allowed:
                new_count = used + 1
                if row:
                    conn.execute("UPDATE rate_limits SET count = ? WHERE uid = ?", (new_count, uid))
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


def increment_rate_limit(uid: str) -> int:
    """Atomically increment daily message count for a user. Returns new count."""
    from datetime import date

    today = date.today().isoformat()
    conn = chats_db()
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        with conn:
            row = conn.execute("SELECT date, count FROM rate_limits WHERE uid = ?", (uid,)).fetchone()
            if row and row["date"] == today:
                new_count = row["count"] + 1
                conn.execute("UPDATE rate_limits SET count = ? WHERE uid = ?", (new_count, uid))
            else:
                new_count = 1
                conn.execute(
                    "INSERT OR REPLACE INTO rate_limits (uid, date, count) VALUES (?, ?, 1)",
                    (uid, today),
                )
    finally:
        conn.close()
    return new_count


# ═══════════════════════════════════════════════════════════════════════════
# Chat database schema initialisation
# ═══════════════════════════════════════════════════════════════════════════


def init_chats_db():
    """Create chats tables if they don't exist."""
    conn = chats_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chats (
            id       TEXT PRIMARY KEY,
            uid      TEXT NOT NULL DEFAULT '',
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
        "cover_page": ("TEXT NOT NULL DEFAULT '{}'"),
        "background": ("TEXT NOT NULL DEFAULT ''"),
        "needs_assessment": ("TEXT NOT NULL DEFAULT ''"),
        "methodology": ("TEXT NOT NULL DEFAULT ''"),
        "budget": ("TEXT NOT NULL DEFAULT '{}'"),
        "mne_framework": ("TEXT NOT NULL DEFAULT '{}'"),
        "risk_matrix": ("TEXT NOT NULL DEFAULT '[]'"),
        "sustainability": ("TEXT NOT NULL DEFAULT ''"),
        "coordination": ("TEXT NOT NULL DEFAULT ''"),
        "current_step": ("TEXT NOT NULL DEFAULT 'cover'"),
        "step_status": ("TEXT NOT NULL DEFAULT '{}'"),
        "completed_at": ("REAL"),
        "reference_text": ("TEXT NOT NULL DEFAULT ''"),
        "reference_filename": ("TEXT NOT NULL DEFAULT ''"),
        "pinned_sources": ("TEXT NOT NULL DEFAULT '[]'"),
        "beneficiary_data": ("TEXT NOT NULL DEFAULT '{}'"),
        "toc_nodes": ("TEXT NOT NULL DEFAULT '[]'"),
        "logframe_data": ("TEXT NOT NULL DEFAULT '{}'"),
        "budget_details": ("TEXT NOT NULL DEFAULT '{}'"),
        "risk_details": ("TEXT NOT NULL DEFAULT '[]'"),
        "mne_plan": ("TEXT NOT NULL DEFAULT '[]'"),
    }
    for col, coldef in _new_prop_cols.items():
        if col not in prop_cols:
            conn.execute(f"ALTER TABLE proposals ADD COLUMN {col} {coldef}")
    # Guided Proposal V2 migration
    guided_tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
    if "proposal_v2_setups" in guided_tables:
        guided_cols = {r[1] for r in conn.execute("PRAGMA table_info(proposal_v2_setups)").fetchall()}
        if "call_brief" not in guided_cols:
            conn.execute("ALTER TABLE proposal_v2_setups ADD COLUMN call_brief TEXT NOT NULL DEFAULT '{}'")
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# Event logging & user tracking
# ═══════════════════════════════════════════════════════════════════════════


def log_event(uid: str, event: str, props: dict = None, session: str = ""):
    """Log a user/system event to the local events table."""
    try:
        conn = chats_db()
        conn.execute(
            "INSERT INTO events (ts, uid, event, props, session) VALUES (?, ?, ?, ?, ?)",
            (time.time(), uid or "", event, json.dumps(props or {}), session),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug("Failed to log event %s: %s", event, e)


def upsert_user(uid: str, email: str = "", role: str = "free", signup_source: str = "web"):
    """Insert or update a user in the local users table."""
    if not uid:
        return
    try:
        conn = chats_db()
        now = time.time()
        conn.execute(
            """
            INSERT INTO users (uid, email, role, created_at, last_seen, signup_source)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(uid) DO UPDATE SET
                email     = excluded.email,
                role      = excluded.role,
                last_seen = excluded.last_seen
        """,
            (uid, email, role, now, now, signup_source),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug("Failed to upsert user %s: %s", uid, e)


# ═══════════════════════════════════════════════════════════════════════════
# Chat CRUD helpers
# ═══════════════════════════════════════════════════════════════════════════


def new_chat_id():
    """Generate a new unique chat ID."""
    return uuid.uuid4().hex[:8]


def db_chat_exists(chat_id):
    conn = chats_db()
    row = conn.execute("SELECT 1 FROM chats WHERE id = ?", (chat_id,)).fetchone()
    conn.close()
    return row is not None


def db_create_chat(chat_id, uid="", title="New Chat"):
    conn = chats_db()
    conn.execute("INSERT INTO chats (id, uid, title, created) VALUES (?, ?, ?, ?)", (chat_id, uid, title, time.time()))
    conn.commit()
    conn.close()


def db_get_chats_by_uid(uid):
    conn = chats_db()
    rows = conn.execute(
        "SELECT c.id, c.title, c.created, COUNT(m.id) AS msg_count "
        "FROM chats c LEFT JOIN chat_messages m ON m.chat_id = c.id "
        "WHERE c.uid = ? "
        "GROUP BY c.id ORDER BY c.created DESC",
        (uid,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def db_chat_belongs_to(chat_id, uid):
    conn = chats_db()
    row = conn.execute("SELECT uid FROM chats WHERE id = ?", (chat_id,)).fetchone()
    conn.close()
    return row is not None and row["uid"] == uid


def db_add_message(chat_id, role, content):
    conn = chats_db()
    conn.execute(
        "INSERT INTO chat_messages (chat_id, role, content, ts) VALUES (?, ?, ?, ?)",
        (chat_id, role, content, time.time()),
    )
    conn.commit()
    conn.close()


def db_get_messages(chat_id):
    conn = chats_db()
    rows = conn.execute("SELECT role, content FROM chat_messages WHERE chat_id = ? ORDER BY id", (chat_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def db_rename_chat(chat_id, title):
    conn = chats_db()
    conn.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))
    conn.commit()
    conn.close()


def db_delete_chat(chat_id):
    conn = chats_db()
    conn.execute("DELETE FROM chat_messages WHERE chat_id = ?", (chat_id,))
    conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    conn.commit()
    conn.close()


def db_clear_messages(chat_id):
    conn = chats_db()
    conn.execute("DELETE FROM chat_messages WHERE chat_id = ?", (chat_id,))
    conn.execute("UPDATE chats SET title = 'New Chat' WHERE id = ?", (chat_id,))
    conn.commit()
    conn.close()


def ensure_active_chat(uid=""):
    """Return the active chat_id for the user, creating one if needed."""
    with _chats_lock:
        with _user_active_chat_lock:
            cid = _user_active_chat.get(uid)
            if cid and db_chat_exists(cid) and (not uid or db_chat_belongs_to(cid, uid)):
                return cid
            if uid:
                conn = chats_db()
                row = conn.execute(
                    "SELECT id FROM chats WHERE uid = ? ORDER BY created DESC LIMIT 1", (uid,)
                ).fetchone()
                conn.close()
                if row and db_chat_belongs_to(row["id"], uid):
                    _user_active_chat[uid] = row["id"]
                    return row["id"]
            cid = new_chat_id()
            db_create_chat(cid, uid=uid)
            _user_active_chat[uid] = cid
            return cid


def load_langchain_messages(chat_id):
    """Load messages from DB as LangChain message objects."""
    from langchain_core.messages import AIMessage, HumanMessage

    rows = db_get_messages(chat_id)
    msgs = []
    for r in rows:
        if r["role"] == "user":
            msgs.append(HumanMessage(content=r["content"]))
        elif r["role"] == "assistant":
            msgs.append(AIMessage(content=r["content"]))
    return msgs


# ── Agent singleton ──────────────────────────────────────────────────────────

_relief_agent = None
_agent_lock = threading.Lock()


def get_agent():
    """Lazy-load the LangGraph agent singleton."""
    global _relief_agent
    if _relief_agent is None:
        with _agent_lock:
            if _relief_agent is None:
                from agent.relief_agent import relief_agent
                _relief_agent = relief_agent
    return _relief_agent


def generate_chat_title(chat_id: str, user_msg: str, ai_reply: str):
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
            title = resp.content.strip().strip("\"'").strip()[:60]
            if title:
                db_rename_chat(chat_id, title)
                logger.info("Chat title generated: chat_id=%s title=%s", chat_id, title)
            else:
                logger.warning("Chat title generation returned empty for chat_id=%s", chat_id)
        except Exception as exc:
            logger.warning("Chat title generation failed for chat_id=%s: %s", chat_id, exc)

    threading.Thread(target=_do, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════════
# SITREP job runner
# ═══════════════════════════════════════════════════════════════════════════


def create_stream_nonce(uid: str, job_id: str = "") -> str:
    """Create a single-use nonce for SITREP stream access."""
    nonce = secrets.token_urlsafe(32)
    with _stream_nonces_lock:
        _stream_nonces[nonce] = {
            "uid": uid,
            "job_id": job_id,
            "expires": time.time() + _STREAM_NONCE_TTL,
            "used": False,
        }
    return nonce


def consume_stream_nonce(nonce: str, uid: str, job_id: str = "") -> bool:
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
        if entry.get("job_id") and job_id and entry["job_id"] != job_id:
            return False
        entry["used"] = True
        return True


def cleanup_stream_nonces():
    """Remove expired nonces. Called periodically."""
    now = time.time()
    with _stream_nonces_lock:
        expired = [k for k, v in _stream_nonces.items() if now > v["expires"]]
        for k in expired:
            del _stream_nonces[k]


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return _ANSI_RE.sub("", text)


def is_gpu_noise(line: str) -> bool:
    """Check if a line is GPU/TensorRT noise that should be filtered."""
    lo = line.lower()
    return any(kw in lo for kw in _NOISE)


def run_job(job_id: str, cmd: list, base_dir: str = None):
    """Run a SITREP pipeline job as a subprocess, streaming output via queue."""
    from config import BASE_DIR as _BASE_DIR

    if base_dir is None:
        base_dir = str(_BASE_DIR)
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
            cwd=base_dir,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        with _jobs_lock:
            _jobs[job_id]["proc"] = proc

        deadline = time.time() + SITREP_JOB_TIMEOUT
        while True:
            raw_line = proc.stdout.readline()
            if not raw_line:
                if proc.poll() is not None:
                    break
                if time.time() > deadline:
                    q.put(f"[SERVER TIMEOUT] SITREP job exceeded {SITREP_JOB_TIMEOUT}s, terminating.")
                    logger.warning("SITREP job %s exceeded %ds timeout, terminating", job_id, SITREP_JOB_TIMEOUT)
                    try:
                        proc.terminate()
                        time.sleep(5)
                        if proc.poll() is None:
                            proc.kill()
                    except Exception:
                        pass
                    break
                time.sleep(0.1)
                continue
            line = strip_ansi(raw_line.rstrip())
            if not line:
                continue
            if is_gpu_noise(line):
                q.put(f"[GPU_WARN] {line}")
            else:
                q.put(line)

        proc.wait()
        exit_code = proc.returncode
        with _jobs_lock:
            _jobs[job_id]["status"] = "done" if exit_code == 0 else "error"
            _jobs[job_id]["finished_at"] = time.time()
            _jobs[job_id]["exit_code"] = exit_code
    except Exception as exc:
        q.put(f"[SERVER ERROR] {exc}")
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["finished_at"] = time.time()
    finally:
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                time.sleep(1)
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
        q.put(None)  # sentinel


# ═══════════════════════════════════════════════════════════════════════════
# Proposal helpers
# ═══════════════════════════════════════════════════════════════════════════

PROPOSAL_SECTIONS = [
    "cover",
    "background",
    "needs_assessment",
    "toc",
    "logframe",
    "methodology",
    "budget",
    "mne_framework",
    "risk_matrix",
    "sustainability",
    "coordination",
    "final_review",
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


def get_proposal_for_edit(prop_id: str, uid: str, role: str):
    """Fetch proposal row, check edit permissions. Returns (row, conn) or (None, conn)."""
    conn = chats_db()
    try:
        if role == "admin":
            row = conn.execute("SELECT * FROM proposals WHERE id = ?", (prop_id,)).fetchone()
        else:
            row = conn.execute("SELECT * FROM proposals WHERE id = ? AND uid = ?", (prop_id, uid)).fetchone()
        return row, conn
    except Exception:
        conn.close()
        return None, None


def update_step_status(conn, prop_id: str, step: str, status: str, uid: str, role: str):
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
        conn.execute(
            "UPDATE proposals SET step_status = ? WHERE id = ? AND uid = ?", (json.dumps(step_status), prop_id, uid)
        )
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════
# Bulletin & ChromaDB helpers
# ═══════════════════════════════════════════════════════════════════════════


def trim_bulletin_for_preview(bulletin: dict) -> dict:
    """Trim a full bulletin for public preview."""
    trimmed = dict(bulletin)
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


def get_chroma_adapter():
    """Lazy-load the ChromaDB adapter singleton."""
    global _chroma_adapter
    if _chroma_adapter is not None:
        return _chroma_adapter
    with _chroma_adapter_lock:
        if _chroma_adapter is not None:
            return _chroma_adapter
        from sitrep.chroma_adapter import ChromaAdapter
        _chroma_adapter = ChromaAdapter()
        return _chroma_adapter


# ── Backward-compatible aliases (server.py legacy names) ─────────────────────
# These allow existing `import server` references in blueprints to work
# during the transition period. Once all blueprints import from helpers,
# these can be removed from server.py.

_chats_db = chats_db
_db_conn = db_conn
_row_to_dict = row_to_dict
_parse_countries = parse_countries
_log_event = log_event
_upsert_user = upsert_user
_new_chat_id = new_chat_id
_db_chat_exists = db_chat_exists
_db_create_chat = db_create_chat
_db_get_chats_by_uid = db_get_chats_by_uid
_db_chat_belongs_to = db_chat_belongs_to
_db_add_message = db_add_message
_db_get_messages = db_get_messages
_db_rename_chat = db_rename_chat
_db_delete_chat = db_delete_chat
_db_clear_messages = db_clear_messages
_ensure_active_chat = ensure_active_chat
_load_langchain_messages = load_langchain_messages
_get_agent = get_agent
_generate_chat_title = generate_chat_title
_check_rate_limit = check_rate_limit
_check_and_increment_rate_limit = check_and_increment_rate_limit
_increment_rate_limit = increment_rate_limit
_init_chats_db = init_chats_db
_check_api_rate_limit = check_api_rate_limit
_create_stream_nonce = create_stream_nonce
_consume_stream_nonce = consume_stream_nonce
_cleanup_stream_nonces = cleanup_stream_nonces
_strip_ansi = strip_ansi
_is_gpu_noise = is_gpu_noise
_run_job = run_job
_get_chroma_adapter = get_chroma_adapter
_trim_bulletin_for_preview = trim_bulletin_for_preview
_get_proposal_for_edit = get_proposal_for_edit
_update_step_status = update_step_status

MANUAL_ID_BASE = 9_000_000_000  # manual TR-prefixed IDs start above this