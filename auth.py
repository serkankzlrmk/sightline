"""
auth.py — Firebase Authentication middleware for RedAgent.

- Verifies Firebase ID tokens from `Authorization: Bearer <token>` header.
- Provides `@require_auth` and `@require_admin` decorators.
- Admin check uses `ADMIN_UIDS` env var (comma-separated Firebase UIDs).
"""
import os
import json
import functools
import traceback
from flask import request, jsonify, g
from config import config

# ---------------------------------------------------------------------------
# Lazy Firebase Admin SDK initialization
# ---------------------------------------------------------------------------
_firebase_app = None

def _get_firebase_app():
    """Return Firebase Admin app (init on first call)."""
    global _firebase_app
    if _firebase_app is None:
        try:
            import firebase_admin
            from firebase_admin import credentials
            sa_path = os.path.join(os.path.dirname(__file__), "firebase-service-account.json")
            if not os.path.exists(sa_path):
                raise RuntimeError(
                    f"Missing {sa_path} — place the Firebase service-account JSON file in project root."
                )
            cred = credentials.Certificate(sa_path)
            _firebase_app = firebase_admin.initialize_app(cred)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Firebase Admin init failed: %s", exc)
            raise
    return _firebase_app

def _admins() -> set:
    """Return set of admin UIDs from env."""
    raw = os.getenv("ADMIN_UIDS", "").strip()
    if not raw:
        return set()
    return {u.strip() for u in raw.split(",") if u.strip()}

# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------

def verify_firebase_token(token: str) -> dict:
    """Verify a Firebase ID token and return decoded claims."""
    _get_firebase_app()  # ensure init
    from firebase_admin import auth as firebase_auth
    try:
        decoded = firebase_auth.verify_id_token(token, check_revoked=True)
        return decoded
    except Exception as exc:
        raise ValueError(f"Invalid or expired Firebase token: {exc}")

# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def require_auth(f):
    """Require a valid Firebase ID token. Sets g.current_user = decoded claims."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing Authorization: Bearer token"}), 401
        token = auth_header[len("Bearer "):].strip()
        if not token:
            return jsonify({"error": "Empty token"}), 401
        try:
            decoded = verify_firebase_token(token)
            g.current_user = decoded
        except Exception as exc:
            return jsonify({"error": str(exc)}), 401
        return f(*args, **kwargs)
    return decorated

def require_admin(f):
    """Require valid token AND admin UID."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        # First enforce auth
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing Authorization: Bearer token"}), 401
        token = auth_header[len("Bearer "):].strip()
        if not token:
            return jsonify({"error": "Empty token"}), 401
        try:
            decoded = verify_firebase_token(token)
            g.current_user = decoded
        except Exception as exc:
            return jsonify({"error": str(exc)}), 401

        # Then enforce admin
        user_uid = decoded.get("uid", "")
        if user_uid not in _admins():
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated
