"""
blueprints/agent_bp.py — Flask Blueprint for /api/agent/* routes.

Extracted from server.py lines 1654–1992.
All shared helpers (DB functions, state dicts, etc.) are imported
from blueprints.helpers to avoid circular imports.
"""

import json
import logging
import threading
import traceback
import uuid

from flask import Blueprint, Response, g, jsonify, request

from agent.memory import gated_recall, maybe_consolidate, remember_turn
from agent.pricing import compute_cost
from agent.relief_agent import TOOL_GROUP_MAP, TOOL_SERVER_MAP
from agent.tool_resilience import looks_like_tool_error
from auth import current_role, current_uid, require_admin, require_auth
from blueprints.helpers import (
    _AGENT_BUSY_TIMEOUT,
    _chats_db,
    _check_and_increment_rate_limit,
    _db_add_message,
    _db_chat_belongs_to,
    _db_clear_messages,
    _db_create_chat,
    _db_delete_chat,
    _db_get_chats_by_uid,
    _db_get_messages,
    _db_rename_chat,
    _ensure_active_chat,
    _generate_chat_title,
    _get_agent,
    _load_langchain_messages,
    _log_event,
    _new_chat_id,
    _user_active_chat,
    _user_active_chat_lock,
    _user_agent_busy,
    _user_agent_busy_lock,
    _user_agent_busy_since,
)
from config import (
    _LLM_API_KEY,
    _LLM_BASE_URL,
    CHAT_MAX_CONCURRENT,
    CHAT_MODELS,
    CUSTOM_MODELS,
    LLM_PROVIDER,
    MODEL_MAX_TOKENS,
    MODEL_TEMPERATURE,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
)
from observability import (
    answer_signals,
    error_tracking,
    feedback_for_turns,
    record_chat_turn,
    record_feedback,
    turn_owner,
)

logger = logging.getLogger(__name__)

agent_bp = Blueprint("agent", __name__, url_prefix="/api/agent")

# Bounded concurrent chat streams: each SSE holds a gunicorn thread for the whole
# answer, so saturation must be rejected with 503 instead of piling up threads.
_chat_sem = threading.BoundedSemaphore(max(1, int(CHAT_MAX_CONCURRENT)))


# ─── Chat list & management ──────────────────────────────────────────────────


@agent_bp.route("/chats")
@require_auth
def api_agent_chats():
    """List all chats for the current user, newest first."""

    uid = current_uid()
    items = _db_get_chats_by_uid(uid)
    with _user_active_chat_lock:
        active = _user_active_chat.get(uid, None)
    return jsonify({"chats": items, "active": active})


@agent_bp.route("/chats/new", methods=["POST"])
@require_auth
def api_agent_chats_new():
    """Create a new chat and make it active."""

    uid = current_uid()
    cid = _new_chat_id()
    _db_create_chat(cid, uid=uid)
    with _user_active_chat_lock:
        _user_active_chat[uid] = cid
    return jsonify({"id": cid})


@agent_bp.route("/chats/new-with-context", methods=["POST"])
@require_auth
def api_agent_chats_new_with_context():
    """Create a new chat pre-loaded with a context message (e.g. SITREP)."""

    uid = current_uid()
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "New Chat")[:120]
    context_text = (data.get("context") or "").strip()[:10000]  # Cap at 10K chars to prevent oversized LLM prompts
    if not context_text:
        return jsonify({"error": "context required"}), 400
    cid = _new_chat_id()
    _db_create_chat(cid, uid=uid)
    _db_rename_chat(cid, title)
    _db_add_message(cid, "assistant", context_text)
    with _user_active_chat_lock:
        _user_active_chat[uid] = cid
    return jsonify({"id": cid, "active": cid})


@agent_bp.route("/chats/<chat_id>/select", methods=["POST"])
@require_auth
def api_agent_chats_select(chat_id):
    """Switch active chat."""

    uid = current_uid()
    if not _db_chat_belongs_to(chat_id, uid):
        return jsonify({"error": "Chat not found"}), 404
    with _user_active_chat_lock:
        _user_active_chat[uid] = chat_id
    return jsonify({"ok": True, "id": chat_id})


@agent_bp.route("/chats/<chat_id>/messages")
@require_auth
def api_agent_chats_messages(chat_id):
    """Return all messages for a chat (for rendering on switch)."""

    uid = current_uid()
    if not _db_chat_belongs_to(chat_id, uid):
        return jsonify({"error": "Chat not found"}), 404
    msgs = _db_get_messages(chat_id)
    # Attach this user's 👍/👎 (keyed by turn_id) so the UI can show the vote state.
    turn_ids = []
    for m in msgs:
        meta = m.get("meta") if isinstance(m.get("meta"), dict) else {}
        if m.get("role") == "assistant" and meta.get("turn_id"):
            turn_ids.append(meta["turn_id"])
    feedback = feedback_for_turns(uid, turn_ids)
    for m in msgs:
        meta = m.get("meta") if isinstance(m.get("meta"), dict) else {}
        m["feedback"] = feedback.get(meta.get("turn_id")) if meta.get("turn_id") else None
    return jsonify({"messages": msgs})


@agent_bp.route("/feedback", methods=["POST"])
@require_auth
def api_agent_feedback():
    """Record 👍/👎 for one assistant turn (one vote per user+turn, toggles update)."""
    uid = current_uid()
    data = request.get_json(silent=True) or {}
    turn_id = str(data.get("turn_id") or "").strip()[:64]
    try:
        rating = int(data.get("rating"))
    except (TypeError, ValueError):
        return jsonify({"error": "rating must be +1 or -1"}), 400
    if not turn_id or rating not in (1, -1):
        return jsonify({"error": "turn_id and rating (+1/-1) are required"}), 400
    owner = turn_owner(turn_id)
    if not owner or owner.get("uid") != uid:
        return jsonify({"error": "Turn not found"}), 404
    comment = str(data.get("comment") or "")[:500]
    if not record_feedback(rating=rating, uid=uid, turn_id=turn_id, comment=comment):
        return jsonify({"error": "Feedback could not be saved"}), 500
    _log_event(uid, "chat_feedback", {"turn_id": turn_id, "rating": rating})
    return jsonify({"ok": True, "turn_id": turn_id, "rating": rating})


@agent_bp.route("/chats/<chat_id>/rename", methods=["POST"])
@require_auth
def api_agent_chats_rename(chat_id):

    uid = current_uid()
    if not _db_chat_belongs_to(chat_id, uid):
        return jsonify({"error": "Chat not found"}), 404
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()[:100]
    if not title:
        return jsonify({"error": "title required"}), 400
    _db_rename_chat(chat_id, title)
    return jsonify({"ok": True})


@agent_bp.route("/chats/<chat_id>", methods=["DELETE"])
@require_auth
def api_agent_chats_delete(chat_id):
    """Delete a chat."""

    uid = current_uid()
    if not _db_chat_belongs_to(chat_id, uid):
        return jsonify({"error": "Chat not found"}), 404
    _db_delete_chat(chat_id)
    with _user_active_chat_lock:
        if _user_active_chat.get(uid) == chat_id:
            _user_active_chat.pop(uid, None)
    _ensure_active_chat(uid)
    with _user_active_chat_lock:
        active = _user_active_chat.get(uid)
    return jsonify({"ok": True, "active": active})


# ─── Agent chat (SSE streaming) ──────────────────────────────────────────────


@agent_bp.route("/chat", methods=["POST"])
@require_auth
def api_agent_chat():
    import time as _time

    uid = current_uid()
    role = current_role()
    request_id = getattr(g, "request_id", "")

    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "empty message"}), 400
    attachment = data.get("attachment") or None

    # ── Pre-flight checks (BEFORE setting busy flag) ──────────────────────
    # Do all validation that can return early here so we never leave the
    # busy flag stuck if a later step returns/throws before generate() runs.

    # Agent mode: analyst (default), me_reviewer
    agent_mode = data.get("mode", "analyst")
    if agent_mode not in ("analyst", "me_reviewer"):
        agent_mode = "analyst"

    # Model selection for chat
    requested_model = data.get("model", "flash")
    if requested_model in CHAT_MODELS:
        model_key = requested_model
        model_config = CHAT_MODELS[model_key]
    elif requested_model in CUSTOM_MODELS:
        model_key = requested_model
        model_config = CUSTOM_MODELS[model_key]
    else:
        model_key = "flash"
        model_config = CHAT_MODELS["flash"]
    # Premium model check — done before busy lock so we don't lock out on 403
    if model_config["premium"] and role not in ("premium", "admin"):
        return jsonify({"error": "Premium model requires a premium account", "premium_required": True}), 403

    # Deep Think: sequential reasoning flag
    use_sequential = model_config.get("sequential", False)

    # ── Global stream concurrency guard ──────────────────────────────────
    # Reject instead of stacking long-lived SSE requests beyond capacity.
    if not _chat_sem.acquire(timeout=5):
        return jsonify(
            {
                "error": "The assistant is at capacity right now. Please retry shortly.",
                "retry_after": 10,
                "code": "ERR-capacity",
            }
        ), 503
    # ── Busy flag + rate limit (atomic) ───────────────────────────────────
    # Rate limit check + busy flag check must be atomic to prevent TOCTOU races
    # where two concurrent requests for the same user both pass the checks.
    with _user_agent_busy_lock:
        # Auto-unlock if stuck (client disconnected, finally didn't run)
        if _user_agent_busy.get(uid, False):
            if (_time.time() - _user_agent_busy_since.get(uid, 0)) > _AGENT_BUSY_TIMEOUT:
                logger.warning("Agent busy flag stuck for uid=%s >%ds, auto-resetting", uid, _AGENT_BUSY_TIMEOUT)
                _user_agent_busy[uid] = False

        if _user_agent_busy.get(uid, False):
            _log_event(uid, "rate_limit_hit", {"reason": "agent_busy"})
            _chat_sem.release()
            return jsonify({"error": "Agent is busy processing your previous message, please wait"}), 429

        # Atomic rate-limit check + increment in a single DB transaction
        if role != "admin":
            rate = _check_and_increment_rate_limit(uid, role)
            if not rate["allowed"]:
                _log_event(uid, "rate_limit_hit", {"reason": "daily_limit", "limit": rate["limit"]})
                _chat_sem.release()
                return jsonify(
                    {
                        "error": "Daily message limit reached",
                        "limit": rate["limit"],
                        "used": rate["used"],
                        "remaining": 0,
                    }
                ), 429
        # Mark busy NOW (under the lock) so a concurrent request sees it
        _user_agent_busy[uid] = True
        _user_agent_busy_since[uid] = _time.time()

    # ── Post-busy setup (wrapped in try/finally — clears busy on failure) ──
    chat_id = None
    try:
        _log_event(uid, "chat_message_sent", {"role": role, "model": data.get("model", "flash"), "mode": agent_mode})
        chat_id = _ensure_active_chat(uid)
    except Exception:
        # If setup fails before generate() starts, free the busy flag
        with _user_agent_busy_lock:
            _user_agent_busy[uid] = False
        _chat_sem.release()
        logger.exception("Agent chat pre-stream setup failed for uid=%s", uid)
        return jsonify({"error": "Failed to start chat session"}), 500

    def generate():
        # busy flag was already set under _user_agent_busy_lock before this generator starts
        # ── Turn telemetry accumulators (must exist in `finally`, even on error) ──
        turn_id = uuid.uuid4().hex
        turn_wall_start = _time.time()
        full_response = ""
        tools_used = []  # [{tool, group, server, output, status, summary, duration_ms, result_chars}]
        usage_in = 0
        usage_out = 0
        iterations = 0
        latency_ms = 0
        turn_status = "error"
        turn_error = ""
        try:
            # Save user message to DB and load full history
            _db_add_message(chat_id, "user", user_message)
            messages_snapshot = _load_langchain_messages(chat_id)

            # ── Cross-chat memory recall (gated + best-effort — never breaks chat) ──
            memory_context = ""
            try:
                memory_context = gated_recall(uid, user_message)
            except Exception:
                pass

            # Use selected model or default agent
            selected_model_name = model_config["model"]
            if selected_model_name != OLLAMA_MODEL:
                # Build a per-request agent with the selected model (single factory)
                from langchain_openai import ChatOpenAI

                from agent.relief_agent import build_agent

                temp_llm = ChatOpenAI(
                    model=selected_model_name,
                    base_url=_LLM_BASE_URL,
                    api_key=_LLM_API_KEY,
                    temperature=MODEL_TEMPERATURE,
                    max_tokens=MODEL_MAX_TOKENS,
                    timeout=OLLAMA_TIMEOUT,
                    stream_usage=True,  # usage_metadata on streamed chunks → per-turn token accounting
                )
                agent = build_agent(
                    temp_llm,
                    mode=agent_mode,
                    role=role,
                    use_sequential=use_sequential,
                    vision=model_config.get("vision", False),
                    attachment=attachment,
                    memory_context=memory_context,
                )
            else:
                agent = _get_agent()
            full_response = ""
            tools_used = []  # [{tool, output, status, summary, duration_ms, result_chars}]
            usage_in = 0
            usage_out = 0
            iterations = 0
            turn_start = _time.time()
            _tool_start_times = []  # FIFO of (name, start_time) — parallel-safe duration

            stream_config = {
                "recursion_limit": 25,
                "configurable": {
                    "uid": uid,
                },
            }

            prev_node = None
            current_iteration = 0
            for chunk, metadata in agent.stream(
                {"messages": messages_snapshot},
                config=stream_config,
                stream_mode="messages",
            ):
                node = metadata.get("langgraph_node", "")

                if node == "llm_call":
                    # New LLM iteration — the agent is reasoning again
                    if prev_node != "llm_call":
                        current_iteration += 1
                        yield f"data: {json.dumps({'type': 'llm', 'iteration': current_iteration})}\n\n"

                    if hasattr(chunk, "content") and isinstance(chunk.content, str) and chunk.content:
                        full_response += chunk.content
                        yield f"data: {json.dumps({'type': 'token', 'text': chunk.content})}\n\n"

                    # Per-turn token accounting — usage_metadata arrives on the
                    # final chunk of each LLM call (requires stream_usage=True).
                    um = getattr(chunk, "usage_metadata", None)
                    if um:
                        _in = 0
                        _out = 0
                        try:
                            _in = int(um.get("input_tokens") or um.get("prompt_tokens") or 0)
                            _out = int(um.get("output_tokens") or um.get("completion_tokens") or 0)
                            usage_in += _in
                            usage_out += _out
                            iterations += 1
                        except (TypeError, ValueError):
                            pass
                        yield f"data: {json.dumps({'type': 'llm_done', 'iteration': current_iteration, 'usage': {'in': _in, 'out': _out}})}\n\n"

                    if hasattr(chunk, "tool_call_chunks") and chunk.tool_call_chunks:
                        for tcc in chunk.tool_call_chunks:
                            name = (tcc.get("name", "") if isinstance(tcc, dict) else getattr(tcc, "name", "")) or ""
                            if name:
                                _tool_start_times.append((name, _time.time()))
                                yield f"data: {json.dumps({'type': 'tool_start', 'name': name})}\n\n"

                elif node == "tool_node":
                    tool_name = getattr(chunk, "name", "") or ""
                    raw = getattr(chunk, "content", "")
                    if isinstance(raw, list):
                        raw = " ".join(str(x) for x in raw)
                    tool_output = str(raw)
                    status = "error" if looks_like_tool_error(tool_output) else "ok"
                    error_class = error_tracking.classify_tool_error(tool_output) if status == "error" else ""
                    summary = (tool_output.split(". ")[0] if ". " in tool_output else tool_output)[:120]
                    if status == "error":
                        error_tracking.record_error(
                            kind="tool",
                            route=f"/api/agent/tool/{tool_name}",
                            method="TOOL",
                            status=500,
                            request_id=request_id,
                            uid=uid,
                            exc_type="ToolError",
                            message=tool_output,
                            stack="",
                            context={
                                "tool": tool_name,
                                "group": TOOL_GROUP_MAP.get(tool_name, "Other"),
                                "server": TOOL_SERVER_MAP.get(tool_name, "native"),
                                "error_class": error_class,
                            },
                        )
                    duration_ms = 0
                    for i, (tn, ts) in enumerate(_tool_start_times):
                        if tn == tool_name:
                            duration_ms = int((_time.time() - ts) * 1000)
                            _tool_start_times.pop(i)
                            break
                    tools_used.append(
                        {
                            "tool": tool_name,
                            "group": TOOL_GROUP_MAP.get(tool_name, "Other"),
                            "server": TOOL_SERVER_MAP.get(tool_name, "native"),
                            "output": tool_output[:500],
                            "result_chars": len(tool_output),
                            "result_preview": tool_output[:1200],
                            "status": status,
                            "error_class": error_class,
                            "summary": summary,
                            "duration_ms": duration_ms,
                        }
                    )
                    yield f"data: {json.dumps({'type': 'tool_done', 'name': tool_name, 'group': TOOL_GROUP_MAP.get(tool_name, 'Other'), 'server': TOOL_SERVER_MAP.get(tool_name, 'native'), 'output': tool_output[:500], 'status': status, 'error_class': error_class, 'summary': summary, 'duration_ms': duration_ms})}\n\n"

                prev_node = node

            latency_ms = int((_time.time() - turn_start) * 1000)
            model_id = model_config.get("model", selected_model_name)
            cost = compute_cost(usage_in, usage_out, model_id, LLM_PROVIDER)
            # Group summary: which data sources the agent touched this turn
            sources = {}
            for t in tools_used:
                g = t.get("group", "Other")
                sources[g] = sources.get(g, 0) + 1
            turn_meta = {
                "turn_id": turn_id,
                "tools": [
                    {
                        "tool": t["tool"],
                        "group": t.get("group", "Other"),
                        "server": t.get("server", "native"),
                        "status": t["status"],
                        "summary": t["summary"],
                        "duration_ms": t["duration_ms"],
                        "result_chars": t.get("result_chars", 0),
                    }
                    for t in tools_used
                ],
                "sources": sources,
                "usage": {"in": usage_in, "out": usage_out},
                "cost": cost,
                "iterations": iterations,
                "latency_ms": latency_ms,
                "total_ms": int((_time.time() - turn_wall_start) * 1000),
                "model": model_config.get("name", model_key),
            }

            if full_response:
                turn_status = "ok"
                _db_add_message(chat_id, "assistant", full_response, meta=turn_meta)

                # Persist this turn to cross-chat episodic memory (best-effort)
                try:
                    remember_turn(uid, chat_id, user_message, full_response)
                except Exception:
                    pass

                # Consolidate unconsolidated turns into durable facts (best-effort)
                try:
                    maybe_consolidate(uid)
                except Exception:
                    pass

                # Auto-generate title with LLM after first exchange
                conn = _chats_db()
                row = conn.execute("SELECT title FROM chats WHERE id = ?", (chat_id,)).fetchone()
                conn.close()
                if row and row["title"] == "New Chat":
                    _generate_chat_title(chat_id, user_message, full_response)
            else:
                turn_status = "empty"

            signals = answer_signals(full_response)
            total_ms = int((_time.time() - turn_wall_start) * 1000)
            yield f"data: {json.dumps({'type': 'done', 'turn_id': turn_id, 'tools': [{'tool': t['tool'], 'group': t.get('group', 'Other'), 'server': t.get('server', 'native'), 'status': t['status'], 'error_class': t.get('error_class', ''), 'summary': t['summary'], 'duration_ms': t['duration_ms']} for t in tools_used], 'sources': sources, 'usage': {'in': usage_in, 'out': usage_out}, 'cost': cost, 'iterations': iterations, 'latency_ms': latency_ms, 'total_ms': total_ms, 'model': model_config.get('name', model_key), 'citations': signals['citations'], 'no_answer': signals['no_answer']})}\n\n"

        except GeneratorExit:
            turn_status = "cancelled"
            turn_error = "client disconnected"
            raise
        except Exception as e:
            turn_status = "error"
            turn_error = str(e)
            logger.exception("Agent chat error: %s", e)
            error_tracking.record_error(
                kind="llm",
                route="/api/agent/chat",
                method="POST",
                status=500,
                request_id=request_id,
                uid=uid,
                exc_type=type(e).__name__,
                message=str(e),
                stack=traceback.format_exc(),
                context={"model": model_key, "mode": agent_mode},
            )
            code = f"ERR-{request_id[:8]}" if request_id else ""
            yield f"data: {json.dumps({'type': 'error', 'text': 'An internal error occurred. Please try again.', 'code': code, 'request_id': request_id})}\n\n"
        finally:
            # Persist turn telemetry — best-effort, never break the chat turn.
            try:
                record_chat_turn(
                    {
                        "turn_id": turn_id,
                        "uid": uid,
                        "chat_id": chat_id or "",
                        "model_key": model_key,
                        "model_id": model_config.get("model", ""),
                        "mode": agent_mode,
                        "started_at": turn_wall_start,
                        "finished_at": _time.time(),
                        "latency_ms": latency_ms,
                        "total_ms": int((_time.time() - turn_wall_start) * 1000),
                        "status": turn_status,
                        "error": turn_error,
                        "iterations": iterations,
                        "tokens_in": usage_in,
                        "tokens_out": usage_out,
                        "cost": compute_cost(usage_in, usage_out, model_config.get("model", ""), LLM_PROVIDER),
                        "groups": {
                            g: sum(1 for t in tools_used if t.get("group", "Other") == g)
                            for g in {t.get("group", "Other") for t in tools_used}
                        },
                        "answer": full_response,
                        "meta": {"model": model_config.get("name", model_key), "mode": agent_mode},
                    },
                    tools=[
                        {
                            "tool": t.get("tool", ""),
                            "group": t.get("group", "Other"),
                            "server": t.get("server", "native"),
                            "status": t.get("status", "ok"),
                            "error_class": t.get("error_class", ""),
                            "duration_ms": t.get("duration_ms", 0),
                            "result_chars": t.get("result_chars", 0),
                            "result_preview": t.get("result_preview", ""),
                            "summary": t.get("summary", ""),
                        }
                        for t in tools_used
                    ],
                )
            except Exception:
                logger.debug("obs: turn record failed (non-fatal)", exc_info=True)
            with _user_agent_busy_lock:
                _user_agent_busy[uid] = False
            _chat_sem.release()

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@agent_bp.route("/chat/reset", methods=["POST"])
@require_auth
def api_agent_chat_reset():
    """Reset the active chat (clear messages)."""

    uid = current_uid()
    chat_id = _ensure_active_chat(uid)
    _db_clear_messages(chat_id)
    return jsonify({"ok": True})


@agent_bp.route("/chat/unlock", methods=["POST"])
@require_admin
def api_agent_chat_unlock():
    """Force-unlock the agent busy flag for a specific user (emergency reset)."""

    data = request.get_json(silent=True) or {}
    target_uid = data.get("uid")
    with _user_agent_busy_lock:
        if target_uid:
            was_busy = _user_agent_busy.get(target_uid, False)
            _user_agent_busy[target_uid] = False
            logger.info(
                "Admin %s unlocked agent busy flag for uid=%s (was_busy=%s)", current_uid(), target_uid, was_busy
            )
            return jsonify({"ok": True, "was_busy": was_busy, "uid": target_uid})
        else:
            # Unlock all users
            busy_count = sum(1 for v in _user_agent_busy.values() if v)
            _user_agent_busy.clear()
            _user_agent_busy_since.clear()
            logger.info("Admin %s unlocked ALL agent busy flags (count=%d)", current_uid(), busy_count)
            return jsonify({"ok": True, "unlocked_count": busy_count})


@agent_bp.route("/chat/status")
@require_auth
def api_agent_chat_status():

    uid = current_uid()
    chat_id = _ensure_active_chat(uid)
    msg_count = len(_db_get_messages(chat_id))
    with _user_agent_busy_lock:
        busy = _user_agent_busy.get(uid, False)
    return jsonify(
        {
            "busy": busy,
            "history_len": msg_count,
            "active_chat": chat_id,
        }
    )


@agent_bp.route("/api/chat/models")
@require_auth
def api_chat_models():
    role = current_role()

    def _ser(v):
        return {
            "name": v["name"],
            "desc": v["desc"],
            "premium": v["premium"],
            "allowed": not v["premium"] or role in ("premium", "admin"),
        }

    return jsonify(
        {
            "models": {k: _ser(v) for k, v in CHAT_MODELS.items()},
            "custom": {k: _ser(v) for k, v in CUSTOM_MODELS.items()},
            "default": "flash",
        }
    )


@agent_bp.route("/capabilities", methods=["GET"])
@require_auth
def api_agent_capabilities():
    """Data sources + models available to the agent (observation panel overview)."""
    groups = {}
    for _nm, _g in TOOL_GROUP_MAP.items():
        groups[_g] = groups.get(_g, 0) + 1
    sources = [{"name": g, "count": n} for g, n in groups.items()]
    return jsonify(
        {
            "sources": sources,
            "tool_count": sum(n for _, n in groups.items()),
            "models": [
                {"key": k, "name": v.get("name", k), "premium": v.get("premium", False)} for k, v in CHAT_MODELS.items()
            ],
        }
    )


@agent_bp.route("/usage", methods=["GET"])
@require_auth
def api_agent_usage():
    """Cumulative usage for this user across ALL chats (cost, tokens, tool calls).

    Aggregates the `meta` JSON persisted on every assistant message (each turn
    stores tools/usage/cost), so this is derived from real recorded history —
    not a separate ledger that can drift out of sync.
    """
    uid = current_uid()
    conn = _chats_db()
    try:
        rows = conn.execute(
            "SELECT m.meta FROM chat_messages m JOIN chats c ON m.chat_id = c.id WHERE c.uid = ?",
            (uid,),
        ).fetchall()
        chat_count = conn.execute("SELECT COUNT(*) FROM chats WHERE uid = ?", (uid,)).fetchone()[0]
    finally:
        conn.close()

    total_in = 0
    total_out = 0
    total_tools = 0
    total_turns = 0
    total_cost = 0.0
    for (meta_json,) in rows:
        if not meta_json:
            continue
        total_turns += 1
        try:
            meta = json.loads(meta_json)
        except (TypeError, ValueError):
            continue
        usage = meta.get("usage") or {}
        try:
            total_in += int(usage.get("in") or 0)
            total_out += int(usage.get("out") or 0)
        except (TypeError, ValueError):
            pass
        tools = meta.get("tools") or []
        total_tools += len(tools)
        try:
            total_cost += float(meta.get("cost") or 0)
        except (TypeError, ValueError):
            pass

    return jsonify(
        {
            "total_chats": chat_count,
            "total_turns": total_turns,
            "total_tools": total_tools,
            "total_tokens": {"in": total_in, "out": total_out},
            "total_cost": round(total_cost, 4),
        }
    )
