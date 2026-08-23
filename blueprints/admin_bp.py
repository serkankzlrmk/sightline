"""
blueprints/admin_bp.py — Admin routes extracted from server.py.

Flask Blueprint for all /api/admin/* endpoints.

Register in server.py with:
    from blueprints.admin_bp import admin_bp
    app.register_blueprint(admin_bp)
"""

import logging
import time as _time
from pathlib import Path

from flask import Blueprint, jsonify, request

from auth import _admins, current_uid, require_admin
from blueprints.helpers import _chats_db, _log_event
from config import OUTPUT_REPORTS_DIR

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


# =============================================================================
# Admin routes
# =============================================================================


@admin_bp.route("/users", methods=["GET"])
@require_admin
def api_admin_users():
    """List all Firebase Auth users with their roles.  Admin only."""
    from auth import _firebase_app

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
            users.append(
                {
                    "uid": user_record.uid,
                    "email": user_record.email or "",
                    "displayName": user_record.display_name or "",
                    "role": role,
                    "disabled": user_record.disabled,
                }
            )
        return jsonify({"users": users})
    except Exception as exc:
        logger.error("api_admin_users error: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to list users"}), 500


@admin_bp.route("/users/<uid>/role", methods=["PUT"])
@require_admin
def api_admin_set_role(uid):
    """Set a user's role via Firebase Custom Claims.  Admin only."""
    from auth import ROLE_HIERARCHY, set_user_role

    data = request.get_json(silent=True) or {}
    new_role = (data.get("role") or "").strip().lower()
    if new_role not in ROLE_HIERARCHY:
        return jsonify({"error": f"Invalid role. Must be one of: {', '.join(ROLE_HIERARCHY)}"}), 400
    success = set_user_role(uid, new_role)
    if not success:
        return jsonify({"error": "Failed to set role — Firebase Admin SDK not available or user not found"}), 500
    logger.info("api_admin_set_role: uid=%s → role=%s (by admin=%s)", uid, new_role, current_uid())
    _log_event(current_uid(), "role_changed", {"target_uid": uid, "new_role": new_role})
    return jsonify({"ok": True, "uid": uid, "role": new_role})


@admin_bp.route("/users/<uid>", methods=["GET"])
@require_admin
def api_admin_get_user(uid):
    """Get a single user's details including role.  Admin only."""
    from auth import _firebase_app

    fb = _firebase_app()
    if not fb:
        return jsonify({"error": "Firebase not configured"}), 503
    try:
        from firebase_admin import auth as firebase_auth

        user_record = firebase_auth.get_user(uid)
        role = (user_record.custom_claims or {}).get("role", "free")
        if role == "free" and user_record.uid in _admins():
            role = "admin"
        return jsonify(
            {
                "uid": user_record.uid,
                "email": user_record.email or "",
                "displayName": user_record.display_name or "",
                "role": role,
                "disabled": user_record.disabled,
            }
        )
    except Exception as exc:
        logger.error("api_admin_get_user error: %s", exc, exc_info=True)
        return jsonify({"error": "User not found"}), 404


@admin_bp.route("/analytics")
@require_admin
def api_admin_analytics():
    """Analytics dashboard data — admin only. Aggregates from events + users tables."""
    conn = _chats_db()
    try:
        # 1. User metrics
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        # Daily Active Users (users with events in last 24h)
        dau = conn.execute(
            "SELECT COUNT(DISTINCT uid) FROM events WHERE ts > ? AND uid != ''", (_time.time() - 86400,)
        ).fetchone()[0]
        # Weekly Active Users
        wau = conn.execute(
            "SELECT COUNT(DISTINCT uid) FROM events WHERE ts > ? AND uid != ''", (_time.time() - 7 * 86400,)
        ).fetchone()[0]
        # New users this week
        new_this_week = conn.execute(
            "SELECT COUNT(*) FROM users WHERE created_at > ?", (_time.time() - 7 * 86400,)
        ).fetchone()[0]
        # Role breakdown
        role_breakdown = conn.execute("SELECT role, COUNT(*) as cnt FROM users GROUP BY role").fetchall()

        # 2. Event counts (last 30 days, top events)
        event_counts = conn.execute(
            """
            SELECT event, COUNT(*) as cnt
            FROM events
            WHERE ts > ?
            GROUP BY event
            ORDER BY cnt DESC
            LIMIT 20
        """,
            (_time.time() - 30 * 86400,),
        ).fetchall()

        # 3. DAU trend (last 14 days)
        dau_trend = conn.execute(
            """
            SELECT date(ts, 'unixepoch') as day, COUNT(DISTINCT uid) as users
            FROM events
            WHERE ts > ? AND uid != ''
            GROUP BY day
            ORDER BY day DESC
            LIMIT 14
        """,
            (_time.time() - 14 * 86400,),
        ).fetchall()

        # 4. Top SITREP runs (by country)
        sitrep_runs = conn.execute(
            """
            SELECT json_extract(props, '$.country') as country, COUNT(*) as cnt
            FROM events
            WHERE event = 'sitrep_run_started' AND ts > ?
            GROUP BY country
            ORDER BY cnt DESC
            LIMIT 10
        """,
            (_time.time() - 30 * 86400,),
        ).fetchall()

        # 5. Recent users (last 10 signups)
        recent_users = conn.execute("""
            SELECT uid, email, role, created_at, last_seen
            FROM users
            ORDER BY created_at DESC
            LIMIT 10
        """).fetchall()

        # 6. Event timeline (last 7 days, daily counts)
        event_timeline = conn.execute(
            """
            SELECT date(ts, 'unixepoch') as day, COUNT(*) as cnt
            FROM events
            WHERE ts > ?
            GROUP BY day
            ORDER BY day DESC
            LIMIT 7
        """,
            (_time.time() - 7 * 86400,),
        ).fetchall()

        # 7. Bulletin views (last 30 days)
        bulletin_views = conn.execute(
            """
            SELECT json_extract(props, '$.filename') as filename, COUNT(*) as cnt
            FROM events
            WHERE event = 'bulletin_viewed' AND ts > ?
            GROUP BY filename
            ORDER BY cnt DESC
            LIMIT 10
        """,
            (_time.time() - 30 * 86400,),
        ).fetchall()

        # 8. SEO public page views (last 30 days, per path)
        public_page_views = conn.execute(
            "SELECT date, path, count FROM page_views "
            "WHERE date >= date('now', '-30 days') ORDER BY date DESC, count DESC LIMIT 200"
        ).fetchall()

        result = {
            "users": {
                "total": total_users,
                "dau": dau,
                "wau": wau,
                "new_this_week": new_this_week,
                "role_breakdown": {r["role"]: r["cnt"] for r in role_breakdown},
            },
            "events": {
                "top_events": [{"event": r["event"], "count": r["cnt"]} for r in event_counts],
                "timeline": [{"day": r["day"], "count": r["cnt"]} for r in event_timeline],
            },
            "dau_trend": [{"day": r["day"], "users": r["users"]} for r in dau_trend],
            "sitrep_runs": [{"country": r["country"] or "Unknown", "count": r["cnt"]} for r in sitrep_runs],
            "bulletin_views": [{"filename": r["filename"] or "Unknown", "count": r["cnt"]} for r in bulletin_views],
            "public_page_views": [
                {"date": r["date"], "path": r["path"], "count": r["count"]} for r in public_page_views
            ],
            "recent_users": [
                {
                    "uid": r["uid"],
                    "email": r["email"],
                    "role": r["role"],
                    "created_at": r["created_at"],
                    "last_seen": r["last_seen"],
                }
                for r in recent_users
            ],
        }
        return jsonify(result)
    except Exception as exc:
        logger.error("api_admin_analytics error: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load analytics"}), 500
    finally:
        conn.close()


@admin_bp.route("/config", methods=["GET"])
@require_admin
def api_admin_config():
    """Get current runtime config values. Admin only."""
    from config import ACTIVE_MODEL, LLM_MODEL, LLM_PROVIDER, MODEL_MAX_TOKENS, MODEL_TEMPERATURE

    return jsonify(
        {
            "ACTIVE_MODEL": ACTIVE_MODEL,
            "LLM_MODEL": LLM_MODEL,
            "LLM_PROVIDER": LLM_PROVIDER,
            "MODEL_TEMPERATURE": MODEL_TEMPERATURE,
            "MODEL_MAX_TOKENS": MODEL_MAX_TOKENS,
        }
    )


@admin_bp.route("/config", methods=["POST"])
@require_admin
def api_admin_update_config():
    """Update .env config values and reload config. Admin only.

    Accepts JSON body with key-value pairs to update in the .env file.
    Only whitelisted keys are allowed. After updating .env, reloads config
    and reinitializes the LLM model.
    """
    ALLOWED_KEYS = {
        "ACTIVE_MODEL",
        "LLM_MODEL",
        "MODEL_TEMPERATURE",
        "MODEL_MAX_TOKENS",
        "LLM_MODEL_QUESTIONS",
        "LLM_MODEL_FILTER",
        "LLM_MODEL_ANSWERS",
    }
    # Validation regex per key type — prevents .env injection (newline in value
    # could add arbitrary env keys like ADMIN_UIDS=attacker-uid)
    import re as _re

    _VALUE_PATTERNS = {
        "ACTIVE_MODEL": _re.compile(r"^[a-zA-Z0-9._/:-]+$"),
        "LLM_MODEL": _re.compile(r"^[a-zA-Z0-9._/:-]+$"),
        "LLM_MODEL_QUESTIONS": _re.compile(r"^[a-zA-Z0-9._/:-]+$"),
        "LLM_MODEL_FILTER": _re.compile(r"^[a-zA-Z0-9._/:-]+$"),
        "LLM_MODEL_ANSWERS": _re.compile(r"^[a-zA-Z0-9._/:-]+$"),
        "MODEL_TEMPERATURE": _re.compile(r"^[0-9.]+$"),
        "MODEL_MAX_TOKENS": _re.compile(r"^[0-9]+$"),
    }
    data = request.get_json(silent=True) or {}
    updates = {}
    for k, v in data.items():
        if k not in ALLOWED_KEYS:
            continue
        # Reject newlines, carriage returns, and null bytes (env injection)
        sv = str(v).strip()
        if any(c in sv for c in ("\n", "\r", "\0")):
            return jsonify({"error": f"Invalid value for {k}: contains newline or null byte"}), 400
        pattern = _VALUE_PATTERNS.get(k)
        if pattern and not pattern.match(sv):
            return jsonify({"error": f"Invalid value for {k}: must match {pattern.pattern}"}), 400
        updates[k] = sv
    if not updates:
        return jsonify({"error": f"No valid keys. Allowed: {', '.join(sorted(ALLOWED_KEYS))}"}), 400

    # Read existing .env
    env_path = Path(__file__).resolve().parent.parent / ".env"
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

    return jsonify(
        {
            "ok": True,
            "updated": list(updates.keys()),
            "ACTIVE_MODEL": config_module.ACTIVE_MODEL,
            "LLM_MODEL": config_module.LLM_MODEL,
        }
    )


@admin_bp.route("/sitrep/<filename>", methods=["DELETE"])
@require_admin
def api_admin_delete_sitrep(filename):
    """Delete a SITREP report file (admin only)."""
    if ".." in filename or "/" in filename or "\\" in filename:
        return jsonify({"error": "Invalid filename"}), 400
    base = OUTPUT_REPORTS_DIR.resolve()
    path = (OUTPUT_REPORTS_DIR / filename).resolve()
    if not path.is_relative_to(base):
        return jsonify({"error": "Invalid filename"}), 400
    if not path.exists():
        return jsonify({"error": "Report not found"}), 404
    try:
        path.unlink()
        _log_event(current_uid(), "sitrep_deleted", {"filename": filename})
        return jsonify({"message": "Report deleted"})
    except Exception as e:
        logger.error(f"api_admin_delete_sitrep error: {filename}, {e}")
        return jsonify({"error": "Internal server error"}), 500


@admin_bp.route("/bulletin/<filename>", methods=["DELETE"])
@require_admin
def api_admin_delete_bulletin(filename):
    """Delete a weekly bulletin file (admin only)."""
    if ".." in filename or "/" in filename or "\\" in filename:
        return jsonify({"error": "Invalid filename"}), 400
    from sitrep.weekly_bulletin import BULLETINS_DIR

    base = BULLETINS_DIR.resolve()
    path = (BULLETINS_DIR / filename).resolve()
    if not path.is_relative_to(base):
        return jsonify({"error": "Invalid filename"}), 400
    if not path.exists():
        return jsonify({"error": "Bulletin not found"}), 404
    try:
        path.unlink()
        _log_event(current_uid(), "bulletin_deleted", {"filename": filename})
        return jsonify({"message": "Bulletin deleted"})
    except Exception as e:
        logger.error(f"api_admin_delete_bulletin error: {filename}, {e}")
        return jsonify({"error": "Internal server error"}), 500

