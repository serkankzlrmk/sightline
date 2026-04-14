"""
server.py — Unified Flask server for ReliefWeb AI Platform.

Merges:
  - reliefwebapi/web_app.py   → /api/agent/* and /api/db/* routes
  - sitrep_pipeline/server.py → /api/sitrep/* routes

Run:
    python server.py
    → http://localhost:5000

Tabs:
    /  →  Tab 1: Veritabanı (SQLite reports browser)
          Tab 2: Agent     (LangGraph chat)
          Tab 3: SITREP    (9-stage pipeline runner)
"""

import sys
import os
import re
import uuid
import json
import sqlite3
import threading
import subprocess
import logging
from pathlib import Path
from queue import Queue, Empty
from functools import wraps

# ── Suppress ONNX / TensorRT log noise before any onnxruntime import ─────────
os.environ.setdefault("ORT_LOGGING_LEVEL", "3")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("ORT_TENSORRT_ENGINE_CACHE_ENABLE", "0")
os.environ.setdefault("ONNXRUNTIME_PROVIDERS", "CUDAExecutionProvider,CPUExecutionProvider")

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from flask import Flask, Response, request, jsonify, render_template, send_from_directory
from flask_cors import CORS

from config import (
    SERVER_HOST, SERVER_PORT, SERVER_DEBUG, SERVER_API_KEY, CORS_ORIGINS,
    DB_PATH, OUTPUT_REPORTS_DIR, DOWNLOADS_DIR, LOG_LEVEL,
)

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
app.secret_key = os.urandom(24)

_cors_origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()] or ["*"]
CORS(app, origins=_cors_origins, supports_credentials=False)

# ─────────────────────────────────────────────────────────────────────────────
# SHARED: API key auth decorator
# ─────────────────────────────────────────────────────────────────────────────

def _require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if SERVER_API_KEY:
            provided = request.headers.get("X-API-Key", "")
            if not provided:
                return jsonify({"error": "Missing X-API-Key header"}), 401
            if provided != SERVER_API_KEY:
                return jsonify({"error": "Invalid API key"}), 403
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────────────────────
# AGENT: Lazy import + multi-chat conversation state
# ─────────────────────────────────────────────────────────────────────────────

_relief_agent = None
_agent_lock   = threading.Lock()

# Multi-chat: { chat_id: { "title": str, "messages": [...], "created": float } }
import time as _time
_chats: dict    = {}
_chats_lock     = threading.Lock()
_active_chat_id = None
_agent_busy     = False

def _new_chat_id():
    return uuid.uuid4().hex[:8]

def _ensure_active_chat():
    """Return the active chat_id, creating one if needed."""
    global _active_chat_id
    with _chats_lock:
        if _active_chat_id is None or _active_chat_id not in _chats:
            cid = _new_chat_id()
            _chats[cid] = {"title": "New Chat", "messages": [], "created": _time.time()}
            _active_chat_id = cid
        return _active_chat_id


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
                model=_cfg.OLLAMA_MODEL,
                base_url=_cfg.OLLAMA_BASE_URL,
                api_key=_cfg.OLLAMA_API_KEY,
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
                with _chats_lock:
                    if chat_id in _chats:
                        _chats[chat_id]["title"] = title
        except Exception:
            logger.debug("Chat title generation failed, keeping default")
    threading.Thread(target=_do, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# DB: SQLite helpers   (from reliefwebapi/web_app.py)
# ─────────────────────────────────────────────────────────────────────────────

def _db_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
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
        with _jobs_lock:
            _jobs[job_id]["status"] = "done" if proc.returncode == 0 else "error"
    except Exception as exc:
        q.put(f"[SERVER ERROR] {exc}")
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
    finally:
        q.put(None)  # sentinel


# =============================================================================
# ROUTES — Frontend
# =============================================================================

@app.route("/")
def index():
    return render_template("index.html")


# =============================================================================
# ROUTES — Health
# =============================================================================

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "version": "1.0"})


# =============================================================================
# ROUTES — /api/agent/*    (multi-chat with LangGraph agent)
# =============================================================================

@app.route("/api/agent/chats")
def api_agent_chats():
    """List all chats, newest first."""
    items = []
    with _chats_lock:
        for cid, c in _chats.items():
            items.append({
                "id":       cid,
                "title":    c["title"],
                "created":  c["created"],
                "msg_count": len(c["messages"]),
            })
    items.sort(key=lambda x: x["created"], reverse=True)
    return jsonify({"chats": items, "active": _active_chat_id})


@app.route("/api/agent/chats/new", methods=["POST"])
def api_agent_chats_new():
    """Create a new chat and make it active."""
    global _active_chat_id
    cid = _new_chat_id()
    with _chats_lock:
        _chats[cid] = {"title": "New Chat", "messages": [], "created": _time.time()}
        _active_chat_id = cid
    return jsonify({"id": cid})


@app.route("/api/agent/chats/<chat_id>/select", methods=["POST"])
def api_agent_chats_select(chat_id):
    """Switch active chat."""
    global _active_chat_id
    if chat_id not in _chats:
        return jsonify({"error": "Chat not found"}), 404
    _active_chat_id = chat_id
    return jsonify({"ok": True, "id": chat_id})


@app.route("/api/agent/chats/<chat_id>/messages")
def api_agent_chats_messages(chat_id):
    """Return all messages for a chat (for rendering on switch)."""
    if chat_id not in _chats:
        return jsonify({"error": "Chat not found"}), 404
    from langchain_core.messages import HumanMessage, AIMessage
    msgs = []
    with _chats_lock:
        for m in _chats[chat_id]["messages"]:
            if isinstance(m, HumanMessage):
                msgs.append({"role": "user", "content": m.content})
            elif isinstance(m, AIMessage):
                msgs.append({"role": "assistant", "content": m.content})
    return jsonify({"messages": msgs})


@app.route("/api/agent/chats/<chat_id>/rename", methods=["POST"])
def api_agent_chats_rename(chat_id):
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()[:100]
    if not title:
        return jsonify({"error": "title required"}), 400
    if chat_id not in _chats:
        return jsonify({"error": "Chat not found"}), 404
    with _chats_lock:
        _chats[chat_id]["title"] = title
    return jsonify({"ok": True})


@app.route("/api/agent/chats/<chat_id>", methods=["DELETE"])
def api_agent_chats_delete(chat_id):
    """Delete a chat."""
    global _active_chat_id
    if chat_id not in _chats:
        return jsonify({"error": "Chat not found"}), 404
    with _chats_lock:
        del _chats[chat_id]
        if _active_chat_id == chat_id:
            _active_chat_id = None
    # Ensure there's always at least one chat
    _ensure_active_chat()
    return jsonify({"ok": True, "active": _active_chat_id})


@app.route("/api/agent/chat", methods=["POST"])
def api_agent_chat():
    global _agent_busy

    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "empty message"}), 400

    if _agent_busy:
        return jsonify({"error": "Agent meşgul, lütfen bekleyin"}), 429

    chat_id = _ensure_active_chat()

    from langchain_core.messages import HumanMessage, AIMessage

    def generate():
        global _agent_busy
        _agent_busy = True

        try:
            with _chats_lock:
                chat = _chats[chat_id]
                chat["messages"].append(HumanMessage(content=user_message))
                messages_snapshot = list(chat["messages"])

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
                with _chats_lock:
                    _chats[chat_id]["messages"].append(AIMessage(content=full_response))

                # Auto-generate title with LLM after first exchange
                if _chats[chat_id]["title"] == "New Chat":
                    _generate_chat_title(chat_id, user_message, full_response)

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            logger.exception("Agent chat error")
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"
        finally:
            _agent_busy = False

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
def api_agent_chat_reset():
    """Reset the active chat (clear messages)."""
    chat_id = _ensure_active_chat()
    with _chats_lock:
        _chats[chat_id]["messages"] = []
        _chats[chat_id]["title"] = "New Chat"
    return jsonify({"ok": True})


@app.route("/api/agent/chat/status")
def api_agent_chat_status():
    chat_id = _ensure_active_chat()
    return jsonify({
        "busy": _agent_busy,
        "history_len": len(_chats.get(chat_id, {}).get("messages", [])),
        "active_chat": chat_id,
    })


# =============================================================================
# ROUTES — /api/db/*    (SQLite reports browser)
# =============================================================================

@app.route("/api/db/stats")
def api_db_stats():
    try:
        conn = _db_conn()
        report_count = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        chunk_count  = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        country_rows = conn.execute("SELECT countries FROM reports").fetchall()
        source_rows  = conn.execute("SELECT source FROM reports").fetchall()
        conn.close()
    except Exception:
        return jsonify({"report_count": 0, "chunk_count": 0, "top_countries": [], "top_sources": []})

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
def api_db_countries():
    try:
        conn = _db_conn()
        rows = conn.execute("SELECT countries FROM reports").fetchall()
        conn.close()
    except Exception:
        return jsonify([])
    all_countries = set()
    for r in rows:
        for c in _parse_countries(r[0]):
            all_countries.add(c)
    return jsonify(sorted(all_countries))


@app.route("/api/db/sources")
def api_db_sources():
    try:
        conn = _db_conn()
        rows = conn.execute("SELECT DISTINCT source FROM reports ORDER BY source").fetchall()
        conn.close()
    except Exception:
        return jsonify([])
    return jsonify([r[0] for r in rows if r[0]])


@app.route("/api/db/reports")
def api_db_reports():
    search   = request.args.get("search",   "").strip()
    country  = request.args.get("country",  "").strip()
    source   = request.args.get("source",   "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to   = request.args.get("date_to",   "").strip()

    try:
        conn = _db_conn()
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
        conn.close()
    except Exception:
        return jsonify([])

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
def api_db_report_detail(report_id):
    try:
        conn = _db_conn()
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
        conn.close()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(d)


# =============================================================================
# ROUTES — /api/sitrep/*    (SITREP pipeline runner)
# =============================================================================

@app.route("/api/sitrep/run", methods=["POST"])
@_require_api_key
def api_sitrep_run():
    data    = request.get_json() or {}
    country = data.get("country", "").strip()
    event   = data.get("event",   "").strip()
    if not country:
        return jsonify({"error": "country is required"}), 400
    if not event:
        event = country

    themes     = [t.strip() for t in data.get("themes", []) if t.strip()]
    skip_cache = bool(data.get("skip_cache", False))

    cmd = [sys.executable, str(BASE_DIR / "sitrep" / "pipeline.py"),
           "--country", country, "--event", event]
    if themes:
        cmd += ["--themes"] + themes
    if skip_cache:
        cmd.append("--skip-cache")

    job_id = uuid.uuid4().hex[:8]
    with _jobs_lock:
        _jobs[job_id] = {
            "queue":   Queue(),
            "status":  "running",
            "proc":    None,
            "country": country,
            "event":   event,
        }

    t = threading.Thread(target=_run_job, args=(job_id, cmd), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/sitrep/stream/<job_id>")
@_require_api_key
def api_sitrep_stream(job_id):
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
@_require_api_key
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
@_require_api_key
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
@_require_api_key
def api_sitrep_report():
    filename = request.args.get("file", "")
    # Prevent path traversal
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        return jsonify({"error": "Invalid filename"}), 400
    path = OUTPUT_REPORTS_DIR / filename
    if not path.exists():
        return jsonify({"error": "Report not found"}), 404
    return path.read_text(encoding="utf-8"), 200, {"Content-Type": "application/json"}


# =============================================================================
# ROUTES — Ingest (direct API, no LLM tokens)
# =============================================================================

@app.route("/api/ingest/search", methods=["POST"])
def api_ingest_search():
    """Search ReliefWeb API directly and return results with local DB status."""
    import requests as req
    from reliefweb_api.reliefweb_config import (
        RELIEFWEB_REPORTS_API, RELIEFWEB_APPNAME, API_TIMEOUT_SHORT,
    )
    from reliefweb_api.reliefweb_utils import normalize_country_name
    from reliefweb_api.ingest_pipeline import is_ingested

    data       = request.get_json(silent=True) or {}
    country    = (data.get("country")     or "").strip()
    query_text = (data.get("query")       or "").strip()
    source_org = (data.get("source_org")  or "").strip()
    theme      = (data.get("theme")       or "").strip()
    date_from  = (data.get("date_from")   or "").strip()
    date_to    = (data.get("date_to")     or "").strip()
    fmt_type   = (data.get("format_type") or "").strip()
    language   = (data.get("language")    or "").strip()
    limit      = min(int(data.get("limit") or 50), 500)

    # New advanced filters (matching agent capabilities)
    disaster       = (data.get("disaster")       or "").strip()
    disaster_type  = (data.get("disaster_type")  or "").strip()
    source_full    = (data.get("source_fullname") or "").strip()
    org_type       = (data.get("organization_type") or "").strip()
    primary_country = (data.get("primary_country") or "").strip()

    filters = []
    if country:
        filters.append({"field": "country.name", "value": normalize_country_name(country)})
    if primary_country:
        filters.append({"field": "primary_country.name", "value": normalize_country_name(primary_country)})
    if theme:
        filters.append({"field": "theme.name", "value": theme})
    if source_org:
        filters.append({"field": "source.shortname", "value": source_org})
    if source_full:
        filters.append({"field": "source.name", "value": source_full})
    if org_type:
        filters.append({"field": "source.type.name", "value": org_type})
    if fmt_type:
        filters.append({"field": "format.name", "value": fmt_type})
    if language:
        filters.append({"field": "language.code", "value": language})
    if disaster:
        filters.append({"field": "disaster.name", "value": disaster})
    if disaster_type:
        filters.append({"field": "disaster_type.name", "value": disaster_type})
    if date_from or date_to:
        df = {"field": "date.original", "value": {}}
        if date_from:
            df["value"]["from"] = f"{date_from}T00:00:00+00:00"
        if date_to:
            df["value"]["to"] = f"{date_to}T23:59:59+00:00"
        filters.append(df)

    body = {
        "preset": "latest",
        "limit": limit,
        "fields": {"include": ["id", "title", "date", "source", "url",
                                "theme", "format", "language", "country"]},
    }
    if filters:
        body["filter"] = filters[0] if len(filters) == 1 else {
            "operator": "AND", "conditions": filters
        }
    if query_text:
        body["query"] = {"value": query_text}

    try:
        url = f"{RELIEFWEB_REPORTS_API}?appname={RELIEFWEB_APPNAME}"
        resp = req.post(url, json=body, timeout=API_TIMEOUT_SHORT, verify=False)
        resp.raise_for_status()
        raw = resp.json()
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    reports = []
    for item in raw.get("data", []):
        f   = item.get("fields", {})
        src = f.get("source", [])
        rid = item.get("id")
        reports.append({
            "id":               rid,
            "title":            f.get("title", ""),
            "date":             (f.get("date") or {}).get("original", ""),
            "source":           src[0].get("shortname", "?") if src else "?",
            "url":              f.get("url", ""),
            "themes":           [t.get("name", "") for t in f.get("theme", [])],
            "format":           [x.get("name", "") for x in f.get("format", [])],
            "countries":        [c.get("name", "") for c in f.get("country", [])],
            "already_ingested": is_ingested(rid, str(DB_PATH)),
        })

    return jsonify({"count": len(reports), "reports": reports})


@app.route("/api/ingest/download", methods=["POST"])
def api_ingest_download():
    """Download + ingest selected reports into SQLite + ChromaDB."""
    from reliefweb_api.ingest_pipeline import is_ingested, auto_ingest
    from reliefweb_api.download_manager import get_download_manager

    data       = request.get_json(silent=True) or {}
    report_ids = data.get("report_ids", [])
    if not report_ids:
        return jsonify({"error": "No report_ids provided"}), 400
    try:
        report_ids = [int(r) for r in report_ids]
    except (ValueError, TypeError):
        return jsonify({"error": "report_ids must be integers"}), 400

    manager = get_download_manager(str(DOWNLOADS_DIR))
    results = {"downloaded": [], "skipped": [], "errors": []}

    for rid in report_ids:
        if is_ingested(rid, str(DB_PATH)):
            results["skipped"].append({"report_id": rid, "reason": "already_in_db"})
            continue
        try:
            dl = manager.download_report(
                rid,
                include_pdf=True,
                include_content=True,
                include_metadata=True,
            )
            ingest = auto_ingest(rid, str(DOWNLOADS_DIR), str(DB_PATH))
            results["downloaded"].append({
                "report_id":    rid,
                "title":        dl.get("title", ""),
                "chunks_added": ingest.get("chunks_added", 0),
            })
        except Exception as e:
            results["errors"].append({"report_id": rid, "error": str(e)})

    results["summary"] = {
        "total":      len(report_ids),
        "downloaded": len(results["downloaded"]),
        "skipped":    len(results["skipped"]),
        "errors":     len(results["errors"]),
    }
    return jsonify(results)


MANUAL_ID_BASE = 9_000_000_000   # manual TR-prefixed IDs start above this

@app.route("/api/ingest/upload", methods=["POST"])
def api_ingest_upload():
    """Upload a PDF with user-supplied metadata → SQLite + ChromaDB."""
    import tempfile, shutil
    from reliefweb_api.db_manager import (
        DatabaseManager, extract_pdf_text, chunk_text,
        build_chunk_with_header, CHUNK_SIZE, CHUNK_OVERLAP,
    )
    from reliefweb_api.vector_store import VectorStore

    title       = (request.form.get("title")       or "").strip()
    source      = (request.form.get("source")      or "").strip()
    country     = (request.form.get("country")     or "").strip()
    format_type = (request.form.get("format_type") or "").strip()
    language    = (request.form.get("language")    or "").strip()
    date_str    = (request.form.get("date")        or "").strip()
    theme       = (request.form.get("theme")       or "").strip()
    pdf_file    = request.files.get("pdf")

    missing = [f for f, v in [
        ("title", title), ("source", source), ("country", country),
        ("format_type", format_type), ("language", language), ("date", date_str),
    ] if not v]
    if not pdf_file or not pdf_file.filename:
        missing.append("pdf")
    if missing:
        return jsonify({"error": "Missing required fields", "fields": missing}), 400

    conn = _db_conn()
    max_row = conn.execute(
        "SELECT MAX(report_id) FROM reports WHERE report_id > ?", (MANUAL_ID_BASE,)
    ).fetchone()
    conn.close()
    new_id     = (max_row[0] or MANUAL_ID_BASE) + 1
    tr_display = f"TR-{new_id - MANUAL_ID_BASE:05d}"

    tmp      = tempfile.mkdtemp()
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
        return jsonify({"error": f"DB insert failed: {e}"}), 500

    try:
        from config import CHROMA_DIR
        vs = VectorStore(str(CHROMA_DIR))
        vs.add_report(new_id, chunks, metadata)
    except Exception as e:
        return jsonify({"error": f"Vector store insert failed: {e}"}), 500

    slug     = re.sub(r'[^\w\s-]', '', title)[:50].strip()
    save_dir = DOWNLOADS_DIR / f"{new_id}_{slug}"
    save_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf_path, save_dir / safe_nm)
    with open(save_dir / f"{new_id}_metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    return jsonify({
        "success":      True,
        "report_id":    new_id,
        "tr_id":        tr_display,
        "title":        title,
        "chunks_added": len(chunks),
        "pdf_pages":    pdf_pages,
    })


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
    print("  Tabs : Database | Agent | SITREP | Ingest")
    print("=" * 58)
    app.run(
        host=SERVER_HOST,
        port=SERVER_PORT,
        debug=SERVER_DEBUG,
        threaded=True,
    )
