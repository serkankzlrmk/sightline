"""agent/tool_resilience.py — retry + per-tool circuit breaker.

Why: upstream tools (ReliefWeb, HDX, MCP servers, news, weather) occasionally
time out, return 429, or fail with transient 5xx. Re-running the whole agent
turn is expensive; retrying a single tool once or twice is cheap and usually
enough. Persistent failures open a short circuit so the agent degrades
gracefully instead of hammering a dead dependency.

Errors are classified with the same taxonomy used by error monitoring
(``observability.error_tracking.classify_tool_error``):
timeout / auth / rate_limit / upstream_5xx / empty / parse / invalid_args / unknown.

State is process-local (one gunicorn worker). After a restart, circuits reset.
"""

from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

_ATTEMPTS = max(1, int(os.getenv("TOOL_RETRY_ATTEMPTS", "2")))
_CIRCUIT_THRESHOLD = max(1, int(os.getenv("TOOL_CIRCUIT_THRESHOLD", "3")))
_CIRCUIT_COOLDOWN = max(1, int(os.getenv("TOOL_CIRCUIT_COOLDOWN_SECONDS", "60")))

_state_lock = threading.Lock()
_failures: dict[str, int] = {}
_open_until: dict[str, float] = {}


def looks_like_tool_error(text: str) -> bool:
    """True for both plain 'Error: …' strings and JSON error envelopes.

    Tools like ACLED/GIEWS return structured failures such as
    ``{"error": true, "error_type": "ACLEDError", ...}``; treating those as
    success makes tool health metrics and alerts silently wrong.
    """
    s = (text or "").lstrip().lower()
    if s.startswith("error"):
        return True
    return any(
        marker in s
        for marker in ('"error": true', '"error":true', '"success": false', '"success":false', '"error_type"')
    )


def _classify(text: str) -> str:
    t = (text or "").lower()
    if "timed out" in t or "timeout" in t:
        return "timeout"
    if "schema pending" in t or "schemapending" in t or "schema_pending" in t or "not configured" in t:
        return "unavailable"
    if "401" in t or "403" in t or "unauthorized" in t or "forbidden" in t or "auth" in t:
        return "auth"
    if "429" in t or "rate limit" in t or "quota" in t:
        return "rate_limit"
    if any(code in t for code in ("500", "502", "503", "504")) or "upstream" in t:
        return "upstream_5xx"
    if "json" in t or "parse" in t or "decode" in t:
        return "parse"
    if "invalid" in t or "validation" in t or "missing" in t or "required" in t:
        return "invalid_args"
    return "unknown"


_TRANSIENT = {"timeout", "rate_limit", "upstream_5xx"}


def circuit_open(tool_name: str) -> bool:
    with _state_lock:
        until = _open_until.get(tool_name, 0.0)
        if until and until > time.time():
            return True
        if until:
            _open_until.pop(tool_name, None)
            _failures.pop(tool_name, None)
        return False


def _record_failure(tool_name: str) -> None:
    with _state_lock:
        count = _failures.get(tool_name, 0) + 1
        _failures[tool_name] = count
        if count >= _CIRCUIT_THRESHOLD:
            _open_until[tool_name] = time.time() + _CIRCUIT_COOLDOWN
            logger.warning(
                "tool circuit opened: %s after %d consecutive failures (%ds cooldown)",
                tool_name,
                count,
                _CIRCUIT_COOLDOWN,
            )


def _record_success(tool_name: str) -> None:
    with _state_lock:
        _failures.pop(tool_name, None)
        _open_until.pop(tool_name, None)


def reset_for_tests() -> None:
    with _state_lock:
        _failures.clear()
        _open_until.clear()


def invoke_tool(tool, args: dict | None, tool_name: str = "") -> str:
    """Invoke one LangChain tool with transient retry and circuit breaking.

    Returns a string (LangChain ToolMessage content). Never raises.
    """
    name = tool_name or getattr(tool, "name", "tool")
    if circuit_open(name):
        return f"Error: tool '{name}' is temporarily disabled after repeated failures. Try another source."

    args = args or {}
    last_error = ""
    for attempt in range(_ATTEMPTS + 1):
        try:
            result = tool.invoke(args)
            text = str(result)
            if looks_like_tool_error(text):
                last_error = text
                cls = _classify(text)
                if cls in _TRANSIENT and attempt < _ATTEMPTS:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                _record_failure(name)
                return text
            _record_success(name)
            return text
        except Exception as exc:
            last_error = str(exc)
            cls = _classify(last_error)
            if cls in _TRANSIENT and attempt < _ATTEMPTS:
                time.sleep(0.4 * (attempt + 1))
                continue
            _record_failure(name)
            logger.warning("tool %s failed (%s): %s", name, cls, exc)
            return f"Error: {exc}"
    _record_failure(name)
    return last_error or f"Error: tool '{name}' failed"
