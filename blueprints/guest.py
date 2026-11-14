"""Guest chat preview quota (no account required).

A signed-ish random cookie identifies a visitor; a per-IP daily cap catches
cookie resets. The quota is deliberately small and the chat route uses a cheap
model plus a two-tool budget.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from contextlib import closing

from flask import request

from blueprints.helpers import chats_db
from config import GUEST_IP_DAILY_LIMIT, GUEST_MESSAGE_LIMIT, SECRET_KEY

_COOKIE = "sightline_guest"
_GUEST_RE = re.compile(r"^[a-f0-9]{24,40}$")


def get_guest_id() -> tuple[str, bool]:
    """Return (guest_id, is_new) from the cookie."""
    raw = str(request.cookies.get(_COOKIE) or "")
    if _GUEST_RE.match(raw):
        return raw, False
    return secrets.token_hex(16), True


def set_guest_cookie(response, guest_id: str):
    response.set_cookie(
        _COOKIE,
        guest_id,
        max_age=30 * 86400,
        httponly=True,
        samesite="Lax",
        secure=request.is_secure,
    )
    return response


def _ip_hash() -> str:
    ip = request.remote_addr or "0.0.0.0"
    salt = str(SECRET_KEY or "sightline-guest")
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()[:32]


def status(guest_id: str) -> dict:
    """Current quota status for one guest id (does not consume)."""
    ip_hash = _ip_hash()
    with closing(chats_db()) as conn:
        row = conn.execute("SELECT messages FROM guest_usage WHERE guest_id=?", (guest_id,)).fetchone()
        used = int(row["messages"] or 0) if row else 0
        ip_used = int(
            conn.execute(
                "SELECT COALESCE(SUM(messages),0) AS n FROM guest_usage WHERE ip_hash=? AND last_at >= ?",
                (ip_hash, time.time() - 86400),
            ).fetchone()["n"]
            or 0
        )
    remaining = max(0, min(GUEST_MESSAGE_LIMIT - used, GUEST_IP_DAILY_LIMIT - ip_used))
    return {
        "limit": GUEST_MESSAGE_LIMIT,
        "used": used,
        "remaining": remaining,
        "login_required": remaining <= 0,
    }


def consume(guest_id: str) -> dict:
    """Atomically consume one guest message if quota remains."""
    ip_hash = _ip_hash()
    now = time.time()
    with closing(chats_db()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT messages FROM guest_usage WHERE guest_id=?", (guest_id,)).fetchone()
        used = int(row["messages"] or 0) if row else 0
        ip_used = int(
            conn.execute(
                "SELECT COALESCE(SUM(messages),0) AS n FROM guest_usage WHERE ip_hash=? AND last_at >= ?",
                (ip_hash, now - 86400),
            ).fetchone()["n"]
            or 0
        )
        allowed = used < GUEST_MESSAGE_LIMIT and ip_used < GUEST_IP_DAILY_LIMIT
        if allowed:
            conn.execute(
                """
                INSERT INTO guest_usage (guest_id, messages, first_at, last_at, ip_hash)
                VALUES (?, 1, ?, ?, ?)
                ON CONFLICT(guest_id) DO UPDATE SET
                    messages = guest_usage.messages + 1,
                    last_at = excluded.last_at,
                    ip_hash = excluded.ip_hash
                """,
                (guest_id, now, now, ip_hash),
            )
            used += 1
            ip_used += 1
        conn.commit()
    remaining = max(0, min(GUEST_MESSAGE_LIMIT - used, GUEST_IP_DAILY_LIMIT - ip_used))
    return {
        "allowed": allowed,
        "limit": GUEST_MESSAGE_LIMIT,
        "used": used,
        "remaining": remaining,
        "login_required": not allowed or remaining <= 0,
    }
