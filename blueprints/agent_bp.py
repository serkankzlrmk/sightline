"""
blueprints/agent_bp.py — Flask Blueprint for /api/agent/* routes.

Extracted from server.py lines 1654–1992.
All shared helpers (DB functions, state dicts, etc.) are accessed
via `import server` to avoid circular imports and duplication.
"""

import json
import logging

from flask import Blueprint, Response, jsonify, request

from auth import current_role, current_uid, require_admin, require_auth
from config import (
    _LLM_API_KEY,
    _LLM_BASE_URL,
    CHAT_MODELS,
    MODEL_MAX_TOKENS,
    MODEL_TEMPERATURE,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
)

logger = logging.getLogger(__name__)

agent_bp = Blueprint("agent", __name__, url_prefix="/api/agent")


# ─── Chat list & management ──────────────────────────────────────────────────


@agent_bp.route("/chats")
@require_auth
def api_agent_chats():
    """List all chats for the current user, newest first."""
    import server

    uid = current_uid()
    items = server._db_get_chats_by_uid(uid)
    with server._user_active_chat_lock:
        active = server._user_active_chat.get(uid, None)
    return jsonify({"chats": items, "active": active})


@agent_bp.route("/chats/new", methods=["POST"])
@require_auth
def api_agent_chats_new():
    """Create a new chat and make it active."""
    import server

    uid = current_uid()
    cid = server._new_chat_id()
    server._db_create_chat(cid, uid=uid)
    with server._user_active_chat_lock:
        server._user_active_chat[uid] = cid
    return jsonify({"id": cid})


@agent_bp.route("/chats/new-with-context", methods=["POST"])
@require_auth
def api_agent_chats_new_with_context():
    """Create a new chat pre-loaded with a context message (e.g. SITREP)."""
    import server

    uid = current_uid()
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "New Chat")[:120]
    context_text = (data.get("context") or "").strip()[:10000]  # Cap at 10K chars to prevent oversized LLM prompts
    if not context_text:
        return jsonify({"error": "context required"}), 400
    cid = server._new_chat_id()
    server._db_create_chat(cid, uid=uid)
    server._db_rename_chat(cid, title)
    server._db_add_message(cid, "assistant", context_text)
    with server._user_active_chat_lock:
        server._user_active_chat[uid] = cid
    return jsonify({"id": cid, "active": cid})


@agent_bp.route("/chats/<chat_id>/select", methods=["POST"])
@require_auth
def api_agent_chats_select(chat_id):
    """Switch active chat."""
    import server

    uid = current_uid()
    if not server._db_chat_belongs_to(chat_id, uid):
        return jsonify({"error": "Chat not found"}), 404
    with server._user_active_chat_lock:
        server._user_active_chat[uid] = chat_id
    return jsonify({"ok": True, "id": chat_id})


@agent_bp.route("/chats/<chat_id>/messages")
@require_auth
def api_agent_chats_messages(chat_id):
    """Return all messages for a chat (for rendering on switch)."""
    import server

    uid = current_uid()
    if not server._db_chat_belongs_to(chat_id, uid):
        return jsonify({"error": "Chat not found"}), 404
    msgs = server._db_get_messages(chat_id)
    return jsonify({"messages": msgs})


@agent_bp.route("/chats/<chat_id>/rename", methods=["POST"])
@require_auth
def api_agent_chats_rename(chat_id):
    import server

    uid = current_uid()
    if not server._db_chat_belongs_to(chat_id, uid):
        return jsonify({"error": "Chat not found"}), 404
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()[:100]
    if not title:
        return jsonify({"error": "title required"}), 400
    server._db_rename_chat(chat_id, title)
    return jsonify({"ok": True})


@agent_bp.route("/chats/<chat_id>", methods=["DELETE"])
@require_auth
def api_agent_chats_delete(chat_id):
    """Delete a chat."""
    import server

    uid = current_uid()
    if not server._db_chat_belongs_to(chat_id, uid):
        return jsonify({"error": "Chat not found"}), 404
    server._db_delete_chat(chat_id)
    with server._user_active_chat_lock:
        if server._user_active_chat.get(uid) == chat_id:
            server._user_active_chat.pop(uid, None)
    server._ensure_active_chat(uid)
    with server._user_active_chat_lock:
        active = server._user_active_chat.get(uid)
    return jsonify({"ok": True, "active": active})


# ─── Agent chat (SSE streaming) ──────────────────────────────────────────────


@agent_bp.route("/chat", methods=["POST"])
@require_auth
def api_agent_chat():
    import time as _time

    import server

    uid = current_uid()
    role = current_role()

    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "empty message"}), 400

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
            _pconn = server._chats_db()
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
    with server._user_agent_busy_lock:
        # Auto-unlock if stuck (client disconnected, finally didn't run)
        if server._user_agent_busy.get(uid, False):
            if (_time.time() - server._user_agent_busy_since.get(uid, 0)) > server._AGENT_BUSY_TIMEOUT:
                logger.warning("Agent busy flag stuck for uid=%s >%ds, auto-resetting", uid, server._AGENT_BUSY_TIMEOUT)
                server._user_agent_busy[uid] = False

        if server._user_agent_busy.get(uid, False):
            server._log_event(uid, "rate_limit_hit", {"reason": "agent_busy"})
            return jsonify({"error": "Agent is busy processing your previous message, please wait"}), 429

        # Atomic rate-limit check + increment in a single DB transaction
        if role != "admin":
            rate = server._check_and_increment_rate_limit(uid, role)
            if not rate["allowed"]:
                server._log_event(uid, "rate_limit_hit", {"reason": "daily_limit", "limit": rate["limit"]})
                return jsonify(
                    {
                        "error": "Daily message limit reached",
                        "limit": rate["limit"],
                        "used": rate["used"],
                        "remaining": 0,
                    }
                ), 429
        # Mark busy NOW (under the lock) so a concurrent request sees it
        server._user_agent_busy[uid] = True
        server._user_agent_busy_since[uid] = _time.time()

    # ── Post-busy setup (wrapped in try/finally — clears busy on failure) ──
    chat_id = None
    try:
        server._log_event(
            uid, "chat_message_sent", {"role": role, "model": data.get("model", "thinking"), "mode": agent_mode}
        )
        chat_id = server._ensure_active_chat(uid)
    except Exception:
        # If setup fails before generate() starts, free the busy flag
        with server._user_agent_busy_lock:
            server._user_agent_busy[uid] = False
        logger.exception("Agent chat pre-stream setup failed for uid=%s", uid)
        return jsonify({"error": "Failed to start chat session"}), 500

    def generate():
        # busy flag was already set under _user_agent_busy_lock before this generator starts
        try:
            # Save user message to DB and load full history
            server._db_add_message(chat_id, "user", user_message)
            messages_snapshot = server._load_langchain_messages(chat_id)

            # Use selected model or default agent
            selected_model_name = model_config["model"]
            if selected_model_name != OLLAMA_MODEL:
                # Create a temporary agent with the selected model
                from langchain_openai import ChatOpenAI
                from langgraph.graph import START, StateGraph
                from langgraph.graph.message import MessagesState
                from langgraph.prebuilt import ToolNode

                from agent.relief_agent import _build_system_prompt, all_tools

                temp_llm = ChatOpenAI(
                    model=selected_model_name,
                    base_url=_LLM_BASE_URL,
                    api_key=_LLM_API_KEY,
                    temperature=MODEL_TEMPERATURE,
                    max_tokens=MODEL_MAX_TOKENS,
                    timeout=OLLAMA_TIMEOUT,
                )
                temp_llm_with_tools = temp_llm.bind_tools(all_tools)
                _system_prompt_text = _build_system_prompt(use_sequential=use_sequential, mode=agent_mode)

                def temp_llm_call(state: MessagesState):
                    messages = state["messages"]
                    from langchain_core.messages import SystemMessage

                    if not messages or not isinstance(messages[0], SystemMessage):
                        messages = [SystemMessage(content=_system_prompt_text)] + messages
                    return {"messages": temp_llm_with_tools.invoke(messages)}

                _temp_builder = StateGraph(MessagesState)
                _temp_builder.add_node("llm_call", temp_llm_call)
                _temp_builder.add_node("tool_node", ToolNode(all_tools))
                _temp_builder.add_edge(START, "llm_call")
                _temp_builder.add_conditional_edges(
                    "llm_call",
                    lambda s: "tool_node" if s["messages"][-1].tool_calls else "__end__",
                    ["tool_node", "__end__"],
                )
                _temp_builder.add_edge("tool_node", "llm_call")
                agent = _temp_builder.compile()
            else:
                agent = server._get_agent()
            full_response = ""

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

                    if hasattr(chunk, "tool_call_chunks") and chunk.tool_call_chunks:
                        for tcc in chunk.tool_call_chunks:
                            name = (tcc.get("name", "") if isinstance(tcc, dict) else getattr(tcc, "name", "")) or ""
                            if name:
                                yield f"data: {json.dumps({'type': 'tool_start', 'name': name})}\n\n"

                elif node == "tool_node":
                    tool_name = getattr(chunk, "name", "") or ""
                    yield f"data: {json.dumps({'type': 'tool_done', 'name': tool_name})}\n\n"

            if full_response:
                server._db_add_message(chat_id, "assistant", full_response)

                # Auto-generate title with LLM after first exchange
                conn = server._chats_db()
                row = conn.execute("SELECT title FROM chats WHERE id = ?", (chat_id,)).fetchone()
                conn.close()
                if row and row["title"] == "New Chat":
                    server._generate_chat_title(chat_id, user_message, full_response)

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            logger.exception("Agent chat error: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'text': 'An internal error occurred. Please try again.'})}\n\n"
        finally:
            with server._user_agent_busy_lock:
                server._user_agent_busy[uid] = False

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
    import server

    uid = current_uid()
    chat_id = server._ensure_active_chat(uid)
    server._db_clear_messages(chat_id)
    return jsonify({"ok": True})


@agent_bp.route("/chat/unlock", methods=["POST"])
@require_admin
def api_agent_chat_unlock():
    """Force-unlock the agent busy flag for a specific user (emergency reset)."""
    import server

    data = request.get_json(silent=True) or {}
    target_uid = data.get("uid")
    with server._user_agent_busy_lock:
        if target_uid:
            was_busy = server._user_agent_busy.get(target_uid, False)
            server._user_agent_busy[target_uid] = False
            logger.info(
                "Admin %s unlocked agent busy flag for uid=%s (was_busy=%s)", current_uid(), target_uid, was_busy
            )
            return jsonify({"ok": True, "was_busy": was_busy, "uid": target_uid})
        else:
            # Unlock all users
            busy_count = sum(1 for v in server._user_agent_busy.values() if v)
            server._user_agent_busy.clear()
            server._user_agent_busy_since.clear()
            logger.info("Admin %s unlocked ALL agent busy flags (count=%d)", current_uid(), busy_count)
            return jsonify({"ok": True, "unlocked_count": busy_count})


@agent_bp.route("/chat/status")
@require_auth
def api_agent_chat_status():
    import server

    uid = current_uid()
    chat_id = server._ensure_active_chat(uid)
    msg_count = len(server._db_get_messages(chat_id))
    with server._user_agent_busy_lock:
        busy = server._user_agent_busy.get(uid, False)
    return jsonify(
        {
            "busy": busy,
            "history_len": msg_count,
            "active_chat": chat_id,
        }
    )
