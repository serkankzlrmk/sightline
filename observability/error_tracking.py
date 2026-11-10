"""observability/error_tracking.py — centralized error store (errors.db).

Design goals:
- **Always available**: a separate SQLite DB, so error monitoring keeps working
  even when turn telemetry (`OBS_ENABLED`) is off.
- **Best-effort**: recording an error must never raise into the request path.
- **Actionable**: one row per occurrence; a stable fingerprint groups repeats;
  request_id/release/uid-hash let an admin correlate logs, users and releases.
- **Privacy**: request bodies are never stored; tokens/emails/nonces are
  scrubbed; uid is hashed with a configurable salt.

Tables:
    error_events       one row per backend/frontend/tool/llm/sse/job error
    error_stats_minute per-minute request/error counters (SLO + alerts)
    alert_state        cooldown bookkeeping for scripts/alert_check.py
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS error_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             REAL NOT NULL,
    fingerprint    TEXT NOT NULL,
    kind           TEXT NOT NULL DEFAULT 'backend',
    route          TEXT NOT NULL DEFAULT '',
    method         TEXT NOT NULL DEFAULT '',
    status         INTEGER NOT NULL DEFAULT 0,
    request_id     TEXT NOT NULL DEFAULT '',
    release        TEXT NOT NULL DEFAULT '',
    uid_hash       TEXT NOT NULL DEFAULT '',
    exception_type TEXT NOT NULL DEFAULT '',
    message        TEXT NOT NULL DEFAULT '',
    stack_hash     TEXT NOT NULL DEFAULT '',
    context_json   TEXT NOT NULL DEFAULT '{}',
    resolved       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_err_ts ON error_events(ts);
CREATE INDEX IF NOT EXISTS idx_err_fp ON error_events(fingerprint, ts);
CREATE INDEX IF NOT EXISTS idx_err_kind ON error_events(kind, ts);
CREATE INDEX IF NOT EXISTS idx_err_resolved ON error_events(resolved, ts);

CREATE TABLE IF NOT EXISTS error_stats_minute (
    minute    TEXT NOT NULL,
    route     TEXT NOT NULL DEFAULT '',
    count     INTEGER NOT NULL DEFAULT 0,
    errors    INTEGER NOT NULL DEFAULT 0,
    total_ms  INTEGER NOT NULL DEFAULT 0,
    max_ms    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (minute, route)
);
CREATE INDEX IF NOT EXISTS idx_errstats_minute ON error_stats_minute(minute);

CREATE TABLE IF NOT EXISTS alert_state (
    key       TEXT PRIMARY KEY,
    last_sent REAL NOT NULL DEFAULT 0,
    count     INTEGER NOT NULL DEFAULT 0
);
"""

_init_lock = threading.Lock()
_initialized: set[str] = set()

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]+=*")
_SECRET_RE = re.compile(r"(?i)\b(token|api[_-]?key|secret|password|nonce|authorization)=([^&\s]+)")
_HEX_RE = re.compile(r"\b[0-9a-fA-F]{24,}\b")
_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_NUM_RE = re.compile(r"/\d{2,}(?=/|$)")


def _db_path() -> Path:
    import config

    return Path(config.ERRORS_DB_PATH)


def _enabled() -> bool:
    import config

    return bool(getattr(config, "ERRORS_ENABLED", True))


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _ensure_schema() -> None:
    path = _db_path()
    key = str(path)
    with _init_lock:
        if key in _initialized:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(_connect(path)) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()
        _initialized.add(key)
    # Prune outside the lock: prune() re-enters _ensure_schema().
    prune()


def reset_for_tests() -> None:
    with _init_lock:
        _initialized.clear()


# ── Sanitization / fingerprints ─────────────────────────────────────────────


def sanitize_text(text: str, limit: int = 2000) -> str:
    """Remove credentials/PII from error text before storing it."""
    value = str(text or "")[: max(0, limit * 4)]
    value = value.replace("\x00", "")
    value = _BEARER_RE.sub("Bearer [redacted]", value)
    value = _SECRET_RE.sub(lambda m: f"{m.group(1)}=[redacted]", value)
    value = _EMAIL_RE.sub("[email]", value)
    value = _HEX_RE.sub("[hex]", value)
    value = value.replace("\r", "")
    return value[:limit]


def normalize_route(path: str) -> str:
    """Normalize dynamic path segments so errors group by route shape."""
    route = str(path or "").split("?", 1)[0]
    route = _UUID_RE.sub(":uuid", route)
    route = _NUM_RE.sub("/:n", route)
    return route[:200]


def _stack_digest(stack: str) -> str:
    """Hash the first few meaningful frames (not the whole traceback)."""
    lines = [ln.strip() for ln in str(stack or "").splitlines() if ln.strip()]
    frames = [ln for ln in lines if ln.startswith("File ")][:6] or lines[:6]
    cleaned = "\n".join(re.sub(r"0x[0-9a-fA-F]+", "0x?", ln)[:300] for ln in frames)
    return hashlib.sha1(cleaned.encode("utf-8", "ignore")).hexdigest()[:16]


def fingerprint(
    kind: str,
    route: str,
    exc_type: str = "",
    stack: str = "",
    message: str = "",
    source: str = "",
    lineno: int = 0,
) -> str:
    """Stable grouping key. Same bug → same fingerprint, different route → new."""
    base = "|".join(
        [
            str(kind or "backend"),
            normalize_route(route),
            str(exc_type or ""),
            _stack_digest(stack),
            sanitize_text(message, 160) if not stack else "",
            str(source or ""),
            str(lineno or ""),
        ]
    )
    return hashlib.sha1(base.encode("utf-8", "ignore")).hexdigest()[:16]


def classify_tool_error(text: str) -> str:
    """Map a tool error message to a small actionable taxonomy."""
    t = (text or "").lower()
    if "timed out" in t or "timeout" in t:
        return "timeout"
    if "401" in t or "403" in t or "unauthorized" in t or "forbidden" in t or "auth" in t:
        return "auth"
    if "429" in t or "rate limit" in t or "quota" in t:
        return "rate_limit"
    if any(code in t for code in ("500", "502", "503", "504")) or "upstream" in t:
        return "upstream_5xx"
    if "no results" in t or "not found" in t or "empty" in t:
        return "empty"
    if "schema pending" in t or "schemapending" in t or "schema_pending" in t or "not configured" in t:
        return "unavailable"
    if "json" in t or "parse" in t or "decode" in t:
        return "parse"
    if "invalid" in t or "validation" in t or "missing" in t or "required" in t:
        return "invalid_args"
    return "unknown"


# ── Writes ───────────────────────────────────────────────────────────────────


def _uid_hash(uid: str) -> str:
    import config

    salt = str(getattr(config, "ERRORS_SALT", "sightline-local-salt"))
    return hashlib.sha256(f"{salt}:{uid}".encode("utf-8", "ignore")).hexdigest()[:16]


def record_error(
    kind: str,
    route: str,
    method: str = "",
    status: int = 0,
    request_id: str = "",
    uid: str = "",
    exc_type: str = "",
    message: str = "",
    stack: str = "",
    context: dict | None = None,
    release: str = "",
    source: str = "",
    lineno: int = 0,
) -> bool:
    """Persist one error occurrence. Never raises."""
    if not _enabled():
        return False
    try:
        safe_message = sanitize_text(message)
        safe_stack = sanitize_text(stack, 6000)
        fp = fingerprint(kind, route, exc_type, safe_stack, safe_message, source, lineno)
        import config

        resolved_release = release or str(getattr(config, "RELEASE_SHA", "dev"))
        _ensure_schema()
        with closing(_connect(_db_path())) as conn:
            conn.execute(
                """
                INSERT INTO error_events
                    (ts, fingerprint, kind, route, method, status, request_id, release,
                     uid_hash, exception_type, message, stack_hash, context_json, resolved)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0)
                """,
                (
                    time.time(),
                    fp,
                    str(kind or "backend")[:24],
                    normalize_route(route),
                    str(method or "")[:10],
                    int(status or 0),
                    str(request_id or "")[:32],
                    resolved_release[:40],
                    _uid_hash(uid),
                    str(exc_type or "")[:120],
                    safe_message,
                    _stack_digest(safe_stack),
                    json.dumps(context or {}, default=str)[:4000],
                ),
            )
            conn.commit()
        return True
    except Exception as exc:
        logger.debug("error_tracking: record_error failed (non-fatal): %s", exc)
        return False


_stats_lock = threading.Lock()
_stats_buffer: dict[tuple[str, str], list[int]] = {}
_last_flush = 0.0


def _flush_stats() -> None:
    """Flush buffered per-minute request counters (one write per route/minute)."""
    global _last_flush
    with _stats_lock:
        rows = list(_stats_buffer.items())
        _stats_buffer.clear()
        _last_flush = time.time()
    if not rows:
        return
    try:
        _ensure_schema()
        with closing(_connect(_db_path())) as conn:
            for (minute, route), (count, errors, total_ms, max_ms) in rows:
                conn.execute(
                    """
                    INSERT INTO error_stats_minute (minute, route, count, errors, total_ms, max_ms)
                    VALUES (?,?,?,?,?,?)
                    ON CONFLICT(minute, route) DO UPDATE SET
                        count = count + excluded.count,
                        errors = errors + excluded.errors,
                        total_ms = total_ms + excluded.total_ms,
                        max_ms = MAX(max_ms, excluded.max_ms)
                    """,
                    (minute, route, count, errors, total_ms, max_ms),
                )
            conn.commit()
    except Exception as exc:
        logger.debug("error_tracking: flush stats failed (non-fatal): %s", exc)


def record_request(route: str, status: int, duration_ms: int) -> None:
    """Buffer one request into per-minute counters; flushed every ~30s."""
    if not _enabled():
        return
    minute = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M")
    key = (minute, normalize_route(route)[:120])
    dur = max(0, int(duration_ms or 0))
    with _stats_lock:
        bucket = _stats_buffer.setdefault(key, [0, 0, 0, 0])
        bucket[0] += 1
        bucket[1] += 1 if int(status or 0) >= 500 else 0
        bucket[2] += dur
        bucket[3] = max(bucket[3], dur)
        should_flush = (time.time() - _last_flush) > 30
    if should_flush:
        _flush_stats()


def resolve(fingerprint_value: str, resolved: bool = True) -> bool:
    try:
        _ensure_schema()
        with closing(_connect(_db_path())) as conn:
            cur = conn.execute(
                "UPDATE error_events SET resolved = ? WHERE fingerprint = ?",
                (1 if resolved else 0, str(fingerprint_value)),
            )
            conn.commit()
        return cur.rowcount > 0
    except Exception as exc:
        logger.debug("error_tracking: resolve failed: %s", exc)
        return False


# ── Reads ────────────────────────────────────────────────────────────────────


def _cutoff(days: int) -> float:
    return time.time() - max(1, min(int(days or 1), 365)) * 86400


def summary(days: int = 1) -> dict:
    days = max(1, min(int(days or 1), 365))
    cutoff = _cutoff(days)
    _flush_stats()
    _ensure_schema()
    with closing(_connect(_db_path())) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS errors,
                   COUNT(DISTINCT fingerprint) AS fingerprints,
                   COUNT(DISTINCT uid_hash) AS users,
                   SUM(CASE WHEN resolved = 0 THEN 1 ELSE 0 END) AS unresolved
            FROM error_events WHERE ts >= ?
            """,
            (cutoff,),
        ).fetchone()
        kinds = {
            r["kind"]: r["n"]
            for r in conn.execute(
                "SELECT kind, COUNT(*) AS n FROM error_events WHERE ts >= ? GROUP BY kind", (cutoff,)
            ).fetchall()
        }
        stats = conn.execute(
            "SELECT COALESCE(SUM(count),0) AS requests, COALESCE(SUM(errors),0) AS errors "
            "FROM error_stats_minute WHERE minute >= ?",
            (datetime.fromtimestamp(cutoff, tz=UTC).strftime("%Y-%m-%dT%H:%M"),),
        ).fetchone()
    requests = int(stats["requests"] or 0)
    errors_5xx = int(stats["errors"] or 0)
    return {
        "range_days": days,
        "errors": int(row["errors"] or 0),
        "fingerprints": int(row["fingerprints"] or 0),
        "users": int(row["users"] or 0),
        "unresolved": int(row["unresolved"] or 0),
        "by_kind": kinds,
        "requests": requests,
        "errors_5xx": errors_5xx,
        "error_rate": round(errors_5xx / requests, 4) if requests else 0.0,
    }


def window_stats(minutes: int = 15) -> dict:
    """Request/5xx counters for the last N minutes (alerting window)."""
    minutes = max(1, min(int(minutes or 15), 1440))
    start = (datetime.now(tz=UTC) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M")
    _flush_stats()
    _ensure_schema()
    with closing(_connect(_db_path())) as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(count),0) AS requests, COALESCE(SUM(errors),0) AS errors "
            "FROM error_stats_minute WHERE minute >= ?",
            (start,),
        ).fetchone()
    requests = int(row["requests"] or 0)
    errors = int(row["errors"] or 0)
    return {
        "window_minutes": minutes,
        "requests": requests,
        "errors": errors,
        "error_rate": round(errors / requests, 4) if requests else 0.0,
    }


def groups(days: int = 7, kind: str = "", resolved: int | None = None, limit: int = 100) -> list[dict]:
    days = max(1, min(int(days or 7), 365))
    limit = max(1, min(int(limit or 100), 500))
    where = ["ts >= ?"]
    params: list = [_cutoff(days)]
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if resolved is not None:
        where.append("resolved = ?")
        params.append(1 if resolved else 0)
    sql = f"""
        SELECT fingerprint, kind, route, exception_type, COUNT(*) AS count,
               MIN(ts) AS first_ts, MAX(ts) AS last_ts,
               COUNT(DISTINCT uid_hash) AS users, MAX(message) AS sample_message,
               MAX(resolved) AS resolved
        FROM error_events WHERE {" AND ".join(where)}
        GROUP BY fingerprint ORDER BY last_ts DESC LIMIT ?
    """
    params.append(limit)
    _ensure_schema()
    with closing(_connect(_db_path())) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def recent(days: int = 1, limit: int = 50, fingerprint_value: str = "") -> list[dict]:
    days = max(1, min(int(days or 1), 365))
    limit = max(1, min(int(limit or 50), 500))
    where = ["ts >= ?"]
    params: list = [_cutoff(days)]
    if fingerprint_value:
        where.append("fingerprint = ?")
        params.append(str(fingerprint_value))
    params.append(limit)
    _ensure_schema()
    with closing(_connect(_db_path())) as conn:
        rows = conn.execute(
            f"""SELECT id, ts, fingerprint, kind, route, method, status, request_id, release,
                       exception_type, message, stack_hash, context_json, resolved
                FROM error_events WHERE {" AND ".join(where)}
                ORDER BY ts DESC LIMIT ?""",
            tuple(params),
        ).fetchall()
    return [dict(r) for r in rows]


def detail(fingerprint_value: str, limit: int = 20) -> dict | None:
    events = recent(days=365, limit=limit, fingerprint_value=fingerprint_value)
    if not events:
        return None
    group = next((g for g in groups(days=365, limit=500) if g["fingerprint"] == fingerprint_value), None)
    return {"fingerprint": fingerprint_value, "group": group, "events": events}


def stats_timeseries(days: int = 7) -> list[dict]:
    days = max(1, min(int(days or 7), 365))
    start = datetime.fromtimestamp(_cutoff(days), tz=UTC).strftime("%Y-%m-%dT%H:%M")
    _flush_stats()
    _ensure_schema()
    with closing(_connect(_db_path())) as conn:
        rows = conn.execute(
            """
            SELECT substr(minute, 1, 10) AS date, SUM(count) AS requests,
                   SUM(errors) AS errors, SUM(total_ms) AS total_ms, MAX(max_ms) AS max_ms
            FROM error_stats_minute WHERE minute >= ?
            GROUP BY date ORDER BY date
            """,
            (start,),
        ).fetchall()
    out = []
    for r in rows:
        req = int(r["requests"] or 0)
        err = int(r["errors"] or 0)
        out.append(
            {
                "date": r["date"],
                "requests": req,
                "errors": err,
                "error_rate": round(err / req, 4) if req else 0.0,
                "avg_ms": int((r["total_ms"] or 0) / req) if req else 0,
                "max_ms": int(r["max_ms"] or 0),
            }
        )
    return out


def prune() -> int:
    """Delete error rows older than retention (called on schema init)."""
    import config

    days = int(getattr(config, "ERRORS_RETENTION_DAYS", 90) or 0)
    if days <= 0:
        return 0
    cutoff = time.time() - days * 86400
    try:
        _ensure_schema()
        with closing(_connect(_db_path())) as conn:
            deleted = conn.execute("DELETE FROM error_events WHERE ts < ?", (cutoff,)).rowcount
            conn.execute(
                "DELETE FROM error_stats_minute WHERE minute < ?",
                (datetime.fromtimestamp(cutoff, tz=UTC).strftime("%Y-%m-%dT%H:%M"),),
            )
            conn.commit()
        return max(0, int(deleted or 0))
    except Exception:
        return 0


# ── Alerts ───────────────────────────────────────────────────────────────────


def alert_allowed(key: str, cooldown_seconds: int = 1800) -> bool:
    """True if this alert key has not fired within the cooldown window."""
    try:
        _ensure_schema()
        now = time.time()
        with closing(_connect(_db_path())) as conn:
            row = conn.execute("SELECT last_sent FROM alert_state WHERE key = ?", (str(key),)).fetchone()
            if row and now - float(row["last_sent"]) < max(0, int(cooldown_seconds)):
                return False
            conn.execute(
                """
                INSERT INTO alert_state (key, last_sent, count) VALUES (?,?,1)
                ON CONFLICT(key) DO UPDATE SET last_sent = excluded.last_sent, count = count + 1
                """,
                (str(key), now),
            )
            conn.commit()
        return True
    except Exception:
        return False
