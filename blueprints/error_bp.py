"""blueprints/error_bp.py — client error ingestion + admin error dashboard API.

Routes:
    POST /api/client-errors                         (anonymous, rate-limited)
    GET  /api/admin/errors/summary?days=1
    GET  /api/admin/errors/groups?days=7&kind=&resolved=
    GET  /api/admin/errors/recent?days=1&limit=50&fingerprint=
    GET  /api/admin/errors/<fingerprint>
    POST /api/admin/errors/<fingerprint>/resolve
    POST /api/admin/errors/test                     (admin smoke test)
"""

import logging
import threading
import time

from flask import Blueprint, jsonify, request

from auth import current_uid, optional_auth, require_admin
from blueprints.helpers import _log_audit
from observability import error_tracking

logger = logging.getLogger(__name__)

error_bp = Blueprint("errors", __name__)

# Simple in-process limiter for the public client-error endpoint (no auth).
_client_lock = threading.Lock()
_client_hits: dict[str, list[float]] = {}
_CLIENT_LIMIT = 20  # per IP per minute
_CLIENT_WINDOW = 60.0


def _client_rate_ok(ip: str) -> bool:
    now = time.time()
    with _client_lock:
        hits = [t for t in _client_hits.get(ip, []) if now - t < _CLIENT_WINDOW]
        if len(hits) >= _CLIENT_LIMIT:
            _client_hits[ip] = hits
            return False
        hits.append(now)
        _client_hits[ip] = hits
        if len(_client_hits) > 5000:  # opportunistic cleanup
            for key in [k for k, v in _client_hits.items() if not v or now - v[-1] > _CLIENT_WINDOW][:1000]:
                _client_hits.pop(key, None)
        return True


def _int_arg(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


@error_bp.route("/api/client-errors", methods=["POST"])
@optional_auth
def api_client_errors():
    """Ingest a browser/JS error report (best-effort, scoped + rate-limited)."""
    ip = request.remote_addr or "unknown"
    if not _client_rate_ok(ip):
        return jsonify({"error": "Too many reports"}), 429
    if request.content_length and request.content_length > 16 * 1024:
        return jsonify({"error": "Payload too large"}), 413
    data = request.get_json(silent=True) or {}
    message = str(data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400
    kind = str(data.get("kind") or "frontend").lower()
    if kind not in ("frontend", "network", "ui"):
        kind = "frontend"
    request_id = str(data.get("request_id") or "")[:32]
    release = str(data.get("release") or "")[:40]
    route = str(data.get("route") or request.path)[:200]
    context = {
        "source": str(data.get("source") or "")[:300],
        "lineno": data.get("lineno") or 0,
        "colno": data.get("colno") or 0,
        "user_agent": (request.headers.get("User-Agent") or "")[:300],
        "client_kind": kind,
    }
    error_tracking.record_error(
        kind=kind,
        route=route,
        method=request.method,
        status=0,
        request_id=request_id,
        uid=current_uid(),
        exc_type="ClientError",
        message=message,
        stack=str(data.get("stack") or ""),
        context=context,
        release=release,
        source=str(data.get("source") or "")[:200],
        lineno=int(data.get("lineno") or 0),
    )
    return jsonify({"ok": True}), 202


# ── Admin read API ───────────────────────────────────────────────────────────


@error_bp.route("/api/admin/errors/summary", methods=["GET"])
@require_admin
def api_error_summary():
    try:
        return jsonify(error_tracking.summary(days=_int_arg("days", 1, 1, 365)))
    except Exception as exc:
        logger.error("error summary failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load error summary"}), 500


@error_bp.route("/api/admin/errors/groups", methods=["GET"])
@require_admin
def api_error_groups():
    try:
        resolved_raw = (request.args.get("resolved") or "").strip()
        resolved = None if resolved_raw == "" else (1 if resolved_raw in ("1", "true") else 0)
        kind = (request.args.get("kind") or "").strip()
        if kind and kind not in ("backend", "frontend", "network", "ui", "tool", "llm", "sse", "job", "canary"):
            return jsonify({"error": "Invalid kind"}), 400
        return jsonify(
            {
                "groups": error_tracking.groups(
                    days=_int_arg("days", 7, 1, 365),
                    kind=kind,
                    resolved=resolved,
                    limit=_int_arg("limit", 100, 1, 500),
                ),
                "series": error_tracking.stats_timeseries(days=_int_arg("days", 7, 1, 365)),
            }
        )
    except Exception as exc:
        logger.error("error groups failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load error groups"}), 500


@error_bp.route("/api/admin/errors/recent", methods=["GET"])
@require_admin
def api_error_recent():
    try:
        return jsonify(
            {
                "events": error_tracking.recent(
                    days=_int_arg("days", 1, 1, 365),
                    limit=_int_arg("limit", 50, 1, 500),
                    fingerprint_value=(request.args.get("fingerprint") or "").strip(),
                )
            }
        )
    except Exception as exc:
        logger.error("error recent failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load recent errors"}), 500


@error_bp.route("/api/admin/errors/<fingerprint_value>", methods=["GET"])
@require_admin
def api_error_detail(fingerprint_value):
    try:
        detail = error_tracking.detail(fingerprint_value)
        if detail is None:
            return jsonify({"error": "Error group not found"}), 404
        return jsonify(detail)
    except Exception as exc:
        logger.error("error detail failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load error group"}), 500


@error_bp.route("/api/admin/errors/<fingerprint_value>/resolve", methods=["POST"])
@require_admin
def api_error_resolve(fingerprint_value):
    data = request.get_json(silent=True) or {}
    resolved = bool(data.get("resolved", True))
    if not error_tracking.resolve(fingerprint_value, resolved=resolved):
        return jsonify({"error": "Error group not found"}), 404
    _log_audit(current_uid() or "admin", "error_resolved", fingerprint_value, {"resolved": resolved})
    return jsonify({"ok": True, "fingerprint": fingerprint_value, "resolved": resolved})


@error_bp.route("/api/admin/errors/test", methods=["POST"])
@require_admin
def api_error_test():
    """Admin smoke test: create one synthetic backend error (for alert/config tests)."""
    error_tracking.record_error(
        kind="backend",
        route="/api/admin/errors/test",
        method="POST",
        status=500,
        request_id="test",
        uid=current_uid(),
        exc_type="SyntheticTestError",
        message="Synthetic test error created from the admin dashboard",
        stack='File "test.py", line 1, in test',
        context={"synthetic": True},
    )
    return jsonify({"ok": True})
