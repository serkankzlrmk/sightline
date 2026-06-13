"""
auth.py — Single source of truth for authentication and role management.

- Firebase Admin SDK: verifies ID tokens from Authorization: Bearer header.
- Legacy API-key mode: if SERVER_API_KEY is set, X-API-Key header is checked instead.
- Provides @require_auth, @require_admin, @require_role Flask decorators.
- Role hierarchy: admin > premium > free
- Roles stored in Firebase Custom Claims (role claim on the ID token).
- Admin UIDs also checked via ADMIN_UIDS env var (fallback / migration path).
- Helper: current_uid() returns the authenticated user's UID (or '').
- Helper: current_role() returns the authenticated user's role string.
- Helper: set_user_role() / get_user_role() for Firebase Custom Claims management.
"""
import os
import functools
import hmac
import secrets
from flask import request, jsonify, g

# ── Role hierarchy ────────────────────────────────────────────────────────────
# Higher index = higher privilege.  Used by require_role(minimum=).
ROLE_HIERARCHY = ["free", "premium", "admin"]


def _get_app_config():
    from config import config
    return config


def _firebase_app():
    """Lazy-init Firebase Admin SDK (only when needed)."""
    global _fb_app
    if _fb_app is not None:
        return _fb_app

    # Search for SA file in multiple locations
    _sa_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "firebase-service-account.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "firebase-service-account.json"),
        "/opt/sightline/data/firebase-service-account.json",
    ]
    sa_path = next((p for p in _sa_paths if os.path.exists(p)), None)
    if not sa_path:
        return None

    import firebase_admin
    from firebase_admin import credentials
    try:
        _fb_app = firebase_admin.get_app()
    except ValueError:
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


def _dev_mode() -> bool:
    """Return True if running in dev mode with auth bypass enabled.

    Auth is bypassed when DEV_AUTH_BYPASS=true is set in .env.
    This allows local testing without needing Google Sign-In (useful in
    VS Code integrated browser where popups don't work).

    When bypassed, all requests get a mock dev user with admin access.
    """
    if os.getenv("DEV_AUTH_BYPASS", "").lower() == "true":
        return True
    # Legacy check: SERVER_DEBUG=true AND no Firebase SA file AND no API key
    if os.getenv("SERVER_DEBUG", "").lower() != "true":
        return False
    if _api_key():
        return False
    if _firebase_app() is not None:
        return False
    return True


def _role_rank(role: str) -> int:
    """Return numeric rank for a role string.  Higher = more privileged."""
    try:
        return ROLE_HIERARCHY.index(role)
    except ValueError:
        return 0  # unknown role → treat as free


def _resolve_role(decoded_token: dict) -> str:
    """Determine the effective role for a decoded Firebase token.

    Priority:
      1. Firebase Custom Claims 'role' field (set by set_user_role)
      2. ADMIN_UIDS env var → admin
      3. Default → free
    """
    # Custom claims take precedence
    custom_claims = decoded_token.get("role", "")
    if custom_claims and custom_claims in ROLE_HIERARCHY:
        return custom_claims
    # Fallback: check ADMIN_UIDS env var
    uid = decoded_token.get("uid", "")
    if uid and uid in _admins():
        return "admin"
    return "free"


def current_role() -> str:
    """Return the authenticated user's role from g.current_user, or 'free'."""
    user = getattr(g, "current_user", None)
    if user and isinstance(user, dict):
        return user.get("role", "free")
    return "free"


def set_user_role(uid: str, role: str) -> bool:
    """Set a Firebase Custom Claim 'role' on a user.

    Valid roles: 'free', 'premium', 'admin'.
    Returns True on success, False on failure.
    Requires Firebase Admin SDK (service account).
    """
    if role not in ROLE_HIERARCHY:
        return False
    fb = _firebase_app()
    if not fb:
        return False
    try:
        from firebase_admin import auth as firebase_auth
        firebase_auth.set_custom_user_claims(uid, {"role": role})
        return True
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("set_user_role failed for uid=%s: %s", uid, exc)
        return False


def get_user_role(uid: str) -> str:
    """Get the role of a Firebase user from Custom Claims.

    Returns the role string, or 'free' if no claims set.
    Requires Firebase Admin SDK (service account).
    """
    fb = _firebase_app()
    if not fb:
        # Fallback to ADMIN_UIDS check
        if uid in _admins():
            return "admin"
        return "free"
    try:
        from firebase_admin import auth as firebase_auth
        user = firebase_auth.get_user(uid)
        claims = user.custom_claims or {}
        return claims.get("role", "free")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("get_user_role failed for uid=%s: %s", uid, exc)
        if uid in _admins():
            return "admin"
        return "free"


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
    - Dev mode:                   if DEV_AUTH_BYPASS=true or SERVER_DEBUG=true + no Firebase/API key, bypass auth.
    Sets g.current_user = decoded Firebase claims with added 'role' field.
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        import logging
        _log = logging.getLogger(__name__)

        # Dev mode bypass — no Firebase SA file, no API key, SERVER_DEBUG=true
        if _dev_mode():
            g.current_user = {
                "uid": "dev-local",
                "email": "dev@localhost",
                "name": "Dev User",
                "admin": True,
                "role": "admin",
            }
            return f(*args, **kwargs)

        api_key = _api_key()

        if api_key:
            provided = request.headers.get("X-API-Key", "")
            if not provided or not hmac.compare_digest(provided, api_key):
                return jsonify({"error": "Invalid API key"}), 403
            g.current_user = {"uid": "api-key", "role": "admin", "admin": True}
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
            # Resolve and attach role from Custom Claims / ADMIN_UIDS fallback
            decoded["role"] = _resolve_role(decoded)
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
    - Otherwise:                  Firebase Bearer token required, role must be 'admin'.
    - Dev mode:                   bypassed as admin.
    Sets g.current_user = decoded Firebase claims with 'role' field.
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        import logging
        _log = logging.getLogger(__name__)

        # Dev mode bypass
        if _dev_mode():
            g.current_user = {
                "uid": "dev-local",
                "email": "dev@localhost",
                "name": "Dev User",
                "admin": True,
                "role": "admin",
            }
            return f(*args, **kwargs)

        api_key = _api_key()

        if api_key:
            provided = request.headers.get("X-API-Key", "")
            if not provided or not hmac.compare_digest(provided, api_key):
                return jsonify({"error": "Invalid API key"}), 403
            g.current_user = {"uid": "api-key", "role": "admin", "admin": True}
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
            decoded["role"] = _resolve_role(decoded)
            g.current_user = decoded
        except ValueError as exc:
            _log.warning("require_admin: token verify failed for %s: %s", request.path, exc)
            return jsonify({"error": str(exc)}), 401

        user_role = decoded.get("role", "free")
        if user_role != "admin":
            _log.warning("require_admin: uid=%s role=%s not admin for %s", decoded.get("uid", ""), user_role, request.path)
            return jsonify({"error": "Admin access required"}), 403

        return f(*args, **kwargs)
    return decorated


def require_role(minimum: str):
    """
    Decorator factory: require a minimum role level.

    Usage:
        @require_role("premium")   # premium + admin can access
        @require_role("admin")     # admin only (same as @require_admin)

    Role hierarchy: free < premium < admin
    """
    min_rank = _role_rank(minimum)

    def decorator(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            import logging
            _log = logging.getLogger(__name__)

            # Dev mode bypass — always treated as admin
            if _dev_mode():
                g.current_user = {
                    "uid": "dev-local",
                    "email": "dev@localhost",
                    "name": "Dev User",
                    "admin": True,
                    "role": "admin",
                }
                return f(*args, **kwargs)

            api_key = _api_key()

            if api_key:
                provided = request.headers.get("X-API-Key", "")
                if not provided or not hmac.compare_digest(provided, api_key):
                    return jsonify({"error": "Invalid API key"}), 403
                g.current_user = {"uid": "api-key", "role": "admin", "admin": True}
                return f(*args, **kwargs)

            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                _log.debug("require_role(%s): no Bearer header for %s", minimum, request.path)
                return jsonify({"error": "Missing Authorization: Bearer token"}), 401
            token = auth_header[len("Bearer "):].strip()
            if not token:
                _log.debug("require_role(%s): empty token for %s", minimum, request.path)
                return jsonify({"error": "Empty token"}), 401
            try:
                decoded = verify_firebase_token(token)
                decoded["role"] = _resolve_role(decoded)
                g.current_user = decoded
            except ValueError as exc:
                _log.warning("require_role(%s): token verify failed for %s: %s", minimum, request.path, exc)
                return jsonify({"error": str(exc)}), 401

            user_role = decoded.get("role", "free")
            user_rank = _role_rank(user_role)
            if user_rank < min_rank:
                _log.warning(
                    "require_role(%s): uid=%s role=%s insufficient for %s",
                    minimum, decoded.get("uid", ""), user_role, request.path,
                )
                return jsonify({"error": f"{minimum.capitalize()} access required"}), 403

            return f(*args, **kwargs)
        return decorated
    return decorator