"""
blueprints/agent_bp.py — Flask Blueprint for /api/agent/* routes.

Extracted from server.py lines 1654–1992.
All shared helpers (DB functions, state dicts, etc.) are imported
from blueprints.helpers to avoid circular imports.
"""

import json
import logging

from flask import Blueprint, Response, jsonify, request

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
    _db_update_message_meta,
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
    CHAT_MODELS,
    LLM_PROVIDER,
    MODEL_MAX_TOKENS,
    MODEL_TEMPERATURE,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
)
from agent.pricing import compute_cost

logger = logging.getLogger(__name__)

agent_bp = Blueprint("agent", __name__, url_prefix="/api/agent")


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
    return jsonify({"messages": msgs})


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

    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "empty message"}), 400
    attachment = data.get("attachment") or None

    # ── Pre-flight checks (BEFORE setting busy flag) ──────────────────────
    # Do all validation that can return early here so we never leave the
    # busy flag stuck if a later step returns/throws before generate() runs.

    # Agent mode: analyst (default), proposal, me_reviewer
    agent_mode = data.get("mode", "analyst")
    if agent_mode not in ("analyst", "proposal", "me_reviewer"):
        agent_mode = "analyst"

    # Model selection for chat
    requested_model = data.get("model", "thinking")
    model_key = requested_model if requested_model in CHAT_MODELS else "thinking"
    model_config = CHAT_MODELS[model_key]
    # Premium model check — done before busy lock so we don't lock out on 403
    if model_config["premium"] and role not in ("premium", "admin"):
        return jsonify({"error": "Premium model requires a premium account", "premium_required": True}), 403

    # Deep Think: sequential reasoning flag
    use_sequential = model_config.get("sequential", False)

    # If proposal/review mode, attach proposal_id to config
    proposal_id = data.get("proposal_id", "")
    if agent_mode in ("proposal", "me_reviewer") and not proposal_id:
        try:
            _pconn = _chats_db()
            _prow = _pconn.execute(
                "SELECT id FROM proposals WHERE uid = ? ORDER BY created_at DESC LIMIT 1",
                (uid,),
            ).fetchone()
            _pconn.close()
            if _prow:
                proposal_id = _prow["id"]
        except Exception:
            pass

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
            return jsonify({"error": "Agent is busy processing your previous message, please wait"}), 429

        # Atomic rate-limit check + increment in a single DB transaction
        if role != "admin":
            rate = _check_and_increment_rate_limit(uid, role)
            if not rate["allowed"]:
                _log_event(uid, "rate_limit_hit", {"reason": "daily_limit", "limit": rate["limit"]})
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
        _log_event(
            uid, "chat_message_sent", {"role": role, "model": data.get("model", "thinking"), "mode": agent_mode}
        )
        chat_id = _ensure_active_chat(uid)
    except Exception:
        # If setup fails before generate() starts, free the busy flag
        with _user_agent_busy_lock:
            _user_agent_busy[uid] = False
        logger.exception("Agent chat pre-stream setup failed for uid=%s", uid)
        return jsonify({"error": "Failed to start chat session"}), 500

    def generate():
        # busy flag was already set under _user_agent_busy_lock before this generator starts
        try:
            # Save user message to DB and load full history
            _db_add_message(chat_id, "user", user_message)
            messages_snapshot = _load_langchain_messages(chat_id)

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
                )
            else:
                agent = _get_agent()
            full_response = ""
            tools_used = []       # [{tool, output, status, summary, duration_ms}]
            usage_in = 0
            usage_out = 0
            iterations = 0
            turn_start = _time.time()
            _tool_start_times = []  # FIFO of (name, start_time) — parallel-safe duration

            stream_config = {
                "recursion_limit": 25,
                "configurable": {
                    "uid": uid,
                    "proposal_id": proposal_id,
                },
            }

            for chunk, metadata in agent.stream(
                {"messages": messages_snapshot},
                config=stream_config,
                stream_mode="messages",
            ):
                node = metadata.get("langgraph_node", "")

                if node == "llm_call":
                    if hasattr(chunk, "content") and isinstance(chunk.content, str) and chunk.content:
                        full_response += chunk.content
                        yield f"data: {json.dumps({'type': 'token', 'text': chunk.content})}\n\n"

                    # Per-turn token accounting — usage_metadata arrives on the
                    # final chunk of each LLM call (requires stream_usage=True).
                    um = getattr(chunk, "usage_metadata", None)
                    if um:
                        try:
                            usage_in += int(um.get("input_tokens") or um.get("prompt_tokens") or 0)
                            usage_out += int(um.get("output_tokens") or um.get("completion_tokens") or 0)
                            iterations += 1
                        except (TypeError, ValueError):
                            pass

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
                    status = "error" if tool_output.lower().startswith("error") else "ok"
                    summary = (tool_output.split(". ")[0] if ". " in tool_output else tool_output)[:120]
                    duration_ms = 0
                    for i, (tn, ts) in enumerate(_tool_start_times):
                        if tn == tool_name:
                            duration_ms = int((_time.time() - ts) * 1000)
                            _tool_start_times.pop(i)
                            break
                    tools_used.append(
                        {
                            "tool": tool_name,
                            "output": tool_output[:500],
                            "status": status,
                            "summary": summary,
                            "duration_ms": duration_ms,
                        }
                    )
                    yield f"data: {json.dumps({'type': 'tool_done', 'name': tool_name, 'output': tool_output[:500], 'status': status, 'summary': summary, 'duration_ms': duration_ms})}\n\n"

            latency_ms = int((_time.time() - turn_start) * 1000)
            model_id = model_config.get("model", selected_model_name)
            cost = compute_cost(usage_in, usage_out, model_id, LLM_PROVIDER)
            turn_meta = {
                "tools": [{"tool": t["tool"], "status": t["status"], "summary": t["summary"], "duration_ms": t["duration_ms"]} for t in tools_used],
                "usage": {"in": usage_in, "out": usage_out},
                "cost": cost,
                "iterations": iterations,
                "latency_ms": latency_ms,
                "model": model_config.get("name", model_key),
            }

            if full_response:
                _db_add_message(chat_id, "assistant", full_response, meta=turn_meta)

                # Auto-generate title with LLM after first exchange
                conn = _chats_db()
                row = conn.execute("SELECT title FROM chats WHERE id = ?", (chat_id,)).fetchone()
                conn.close()
                if row and row["title"] == "New Chat":
                    _generate_chat_title(chat_id, user_message, full_response)

            yield f"data: {json.dumps({'type': 'done', 'tools': [{'tool': t['tool'], 'status': t['status'], 'summary': t['summary'], 'duration_ms': t['duration_ms']} for t in tools_used], 'usage': {'in': usage_in, 'out': usage_out}, 'cost': cost, 'iterations': iterations, 'latency_ms': latency_ms, 'model': model_config.get('name', model_key)})}\n\n"

        except Exception as e:
            logger.exception("Agent chat error: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'text': 'An internal error occurred. Please try again.'})}\n\n"
        finally:
            with _user_agent_busy_lock:
                _user_agent_busy[uid] = False

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
    return jsonify(
        {
            "models": {
                k: {
                    "name": v["name"],
                    "desc": v["desc"],
                    "premium": v["premium"],
                    "allowed": not v["premium"] or role in ("premium", "admin"),
                }
                for k, v in CHAT_MODELS.items()
            },
            "default": "thinking",
        }
    )
