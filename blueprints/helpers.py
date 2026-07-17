"""
blueprints/helpers.py — Shared helper proxies for Flask Blueprints.

All helpers delegate to server.py via late import to avoid circular dependencies.
Blueprints should import from this module instead of defining their own proxies.
"""

import time as _time


def _db_conn():
    """Proxy for server._db_conn — connects to the reliefweb SQLite database."""
    import server as _srv
    return _srv._db_conn()


def _chats_db():
    """Proxy for server._chats_db — connects to the chats SQLite database."""
    import server as _srv
    return _srv._chats_db()


def _log_event(uid, event, props=None, session=""):
    """Proxy for server._log_event — logs analytics events."""
    import server as _srv
    return _srv._log_event(uid, event, props, session)


def _get_agent():
    """Proxy for server._get_agent — returns the LangGraph agent instance."""
    import server as _srv
    return _srv._get_agent()


def _get_chroma_adapter():
    """Proxy for server._get_chroma_adapter — returns the shared ChromaDB singleton."""
    import server as _srv
    return _srv._get_chroma_adapter()


def _check_rate_limit(uid, role="user"):
    """Proxy for server._check_and_increment_rate_limit — daily rate limit check."""
    import server as _srv
    return _srv._check_and_increment_rate_limit(uid, role)


# ── Re-export time for convenience ──────────────────────────────────────────
import time as _time_mod
_time = _time_mod