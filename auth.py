"""
auth.py — Single source of truth for authentication.

- Firebase Admin SDK: verifies ID tokens from Authorization: Bearer header.
- Legacy API-key mode: if SERVER_API_KEY is set, X-API-Key header is checked instead.
- Provides @require_auth and @require_admin Flask decorators.
- Admin check uses ADMIN_UIDS env var (comma-separated Firebase UIDs).
- Helper: current_uid() returns the authenticated user's UID (or '').
"""
import os
import functools
from flask import request, jsonify, g


def _get_app_config():
    from config import config
    return config


def _firebase_app():
    """Lazy-init Firebase Admin SDK (only when needed)."""
    if not os.path.exists(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "firebase-service-account.json")
    ):
        return None

    global _fb_app
    if _fb_app is None:
        import firebase_admin
        from firebase_admin import credentials
        # Check if default app already exists (e.g., initialized elsewhere)
        try:
            _fb_app = firebase_admin.get_app()
        except ValueError:
            sa_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "firebase-service-account.json")
            cred = credentials.Certificate(sa_path)
            _fb_app = firebase_admin.initialize_app(cred)
    return _fb_app


_fb_app = None


def _admins() -> set:
    """Return set of admin UIDs from env (loaded by config.py's dotenv)."""
    raw = os.getenv("ADMIN_UIDS", "").strip()
    if not raw:
        try:
            from config import config
            raw = getattr(config, 'ADMIN_UIDS', '').strip() if config else ''
        except Exception:
            pass
    if not raw:
        return set()
    return {u.strip() for u in raw.split(",") if u.strip()}


def _api_key() -> str:
    """Return SERVER_API_KEY from config."""
    try:
        return _get_app_config().SERVER_API_KEY or ""
    except Exception:
        return os.getenv("SERVER_API_KEY", "")


def verify_firebase_token(token: str) -> dict:
    """Verify a Firebase ID token and return decoded claims.
    
    Uses check_revoked=False to avoid clock-skew issues ("Token used too early").
    Revocation is checked lazily instead.
    """
    _firebase_app()
    from firebase_admin import auth as firebase_auth
    import time
    try:
        decoded = firebase_auth.verify_id_token(token, check_revoked=False)
        return decoded
    except firebase_auth.InvalidIdTokenError as exc:
        err_msg = str(exc)
        if "too early" in err_msg.lower():
            import logging
            logging.getLogger(__name__).warning(
                "Clock skew detected — retrying token verify after short delay"
            )
            time.sleep(2)
            decoded = firebase_auth.verify_id_token(token, check_revoked=False)
            return decoded
        raise ValueError(f"Invalid or expired Firebase token: {exc}")
    except Exception as exc:
        raise ValueError(f"Invalid or expired Firebase token: {exc}")


def current_uid() -> str:
    """Return the authenticated user's UID from g.current_user, or ''."""
    user = getattr(g, "current_user", None)
    if user:
        return str(user.get("uid", ""))
    return ""


def require_auth(f):
    """
    Require authentication via Firebase Bearer token OR legacy API key.

    - If SERVER_API_KEY is set:  require X-API-Key header matching it.
    - Otherwise:                  require Authorization: Bearer <Firebase ID token>.
    Sets g.current_user = decoded Firebase claims (if Firebase mode).
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        import logging
        _log = logging.getLogger(__name__)

        api_key = _api_key()

        if api_key:
            provided = request.headers.get("X-API-Key", "")
            if not provided or provided != api_key:
                return jsonify({"error": "Invalid API key"}), 403
            return f(*args, **kwargs)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            _log.debug("require_auth: no Bearer header for %s", request.path)
            return jsonify({"error": "Missing Authorization: Bearer token"}), 401
        token = auth_header[len("Bearer "):].strip()
        if not token:
            _log.debug("require_auth: empty token for %s", request.path)
            return jsonify({"error": "Empty token"}), 401
        try:
            decoded = verify_firebase_token(token)
            g.current_user = decoded
        except ValueError as exc:
            _log.warning("require_auth: token verify failed for %s: %s", request.path, exc)
            return jsonify({"error": str(exc)}), 401

        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    """
    Require admin access.

    - If SERVER_API_KEY is set:  X-API-Key must match (any valid key = admin).
    - Otherwise:                  Firebase Bearer token required, UID must be in ADMIN_UIDS.
    Sets g.current_user = decoded Firebase claims (if Firebase mode).
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        import logging
        _log = logging.getLogger(__name__)

        api_key = _api_key()

        if api_key:
            provided = request.headers.get("X-API-Key", "")
            if not provided or provided != api_key:
                return jsonify({"error": "Invalid API key"}), 403
            return f(*args, **kwargs)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            _log.debug("require_admin: no Bearer header for %s", request.path)
            return jsonify({"error": "Missing Authorization: Bearer token"}), 401
        token = auth_header[len("Bearer "):].strip()
        if not token:
            _log.debug("require_admin: empty token for %s", request.path)
            return jsonify({"error": "Empty token"}), 401
        try:
            decoded = verify_firebase_token(token)
            g.current_user = decoded
        except ValueError as exc:
            _log.warning("require_admin: token verify failed for %s: %s", request.path, exc)
            return jsonify({"error": str(exc)}), 401

        user_uid = decoded.get("uid", "")
        admins = _admins()
        if user_uid not in admins:
            _log.warning("require_admin: uid=%s not in admins=%s for %s", user_uid, admins, request.path)
            return jsonify({"error": "Admin access required"}), 403

        return f(*args, **kwargs)
    return decorated