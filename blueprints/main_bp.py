"""
blueprints/main_bp.py — Landing page, SPA entry, and health check.

Routes:
    /            → Landing page (public)
    /app         → SPA entry point (requires auth via frontend)
    /api/health  → Health check (unauthenticated, for Docker healthcheck)
"""

import sqlite3
from pathlib import Path

from flask import Blueprint, jsonify, render_template

from config import (
    _LLM_API_KEY,
    CONTACT_EMAIL,
    DB_PATH,
)
from reliefweb_api.hdx_tools import get_hdx_client
from reliefweb_api.news_tools import get_news_client

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def landing():
    return render_template("landing.html", v=int(__import__("time").time()))


@main_bp.route("/app")
def spa():
    return render_template("index.html", v=int(__import__("time").time()), contact_email=CONTACT_EMAIL)


@main_bp.route("/api/health")
def health():
    """Enhanced health check — verifies DB, vector store, and LLM config.

    Security: this endpoint is unauthenticated, so it returns only boolean
    status flags — no model names, no release info, no dev_mode flag (which
    would be a banner saying 'auth is disabled here').
    """
    from config import CHROMA_DIR

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

    # ChromaDB is the only live vector store.
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