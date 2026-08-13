"""
blueprints/auth_route.py — Auth / me endpoint.

Routes:
    /api/auth/me  → Get current user info, role, rate limit
"""

import logging

from flask import Blueprint, g, jsonify

from auth import _admins, require_auth
from blueprints.helpers import _check_rate_limit, _upsert_user
from config import CHAT_MODELS

logger = logging.getLogger(__name__)

auth_route_bp = Blueprint("auth_route", __name__)


@auth_route_bp.route("/api/auth/me")
@require_auth
def api_auth_me():
    from auth import _dev_mode

    user = getattr(g, "current_user", None) or {}
    uid = user.get("uid", "")
    role = user.get("role", "free")
    admins = _admins()
    is_admin = role == "admin" or uid in admins or _dev_mode()
    if is_admin and role != "admin":
        role = "admin"
    logger.info("auth/me: uid=%r, role=%s, is_admin=%s, email=%s", uid, role, is_admin, user.get("email", ""))
    # Track user (upsert) + log login event
    _upsert_user(uid, user.get("email", ""), role)
    rate = _check_rate_limit(uid, role)
    return jsonify(
        {
            "uid": uid,
            "email": user.get("email", ""),
            "name": user.get("name", ""),
            "is_admin": is_admin,
            "role": role,
            "rate_limit": rate,
            "models": {
                k: {"name": v["name"], "desc": v["desc"], "premium": v["premium"]} for k, v in CHAT_MODELS.items()
            },
        }
    )
