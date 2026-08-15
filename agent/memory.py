"""agent/memory.py — cross-chat episodic memory for the Sightline agent.

Embeds completed Q/A turns into a dedicated ChromaDB collection so the agent
can recall what it discussed with a user in previous chats ("eskileri bilsin").

Philosophy (from waku-agent): store embeddings once, derive relevance at read
time. Every recall is a cheap cosine search — no separate index or
summarization pass, no extra LLM call.

Design notes:
- Best-effort: every call is wrapped so a memory failure NEVER breaks a chat.
- Uses the same ChromaAdapter client + embedding function as the report
  vector store (no second sentence-transformers model load in-process).
- uid-scoped: a user only ever recalls their own past turns (privacy).
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

_collection = None
_collection_disabled = False
_lock = threading.Lock()

_MEMORY_COLLECTION = "agent_memory"


def _get_collection():
    """Lazy-load the dedicated agent_memory collection (thread-safe).

    Returns the collection, or None if memory is unavailable (never raises).
    """
    global _collection, _collection_disabled
    if _collection is not None:
        return _collection
    if _collection_disabled:
        return None
    with _lock:
        if _collection is not None:
            return _collection
        if _collection_disabled:
            return None
        try:
            from blueprints.helpers import get_chroma_adapter

            adapter = get_chroma_adapter()
            _collection = adapter.client.get_or_create_collection(
                name=_MEMORY_COLLECTION,
                embedding_function=adapter.ef,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("✓ Agent memory collection ready (%s)", _MEMORY_COLLECTION)
        except Exception as e:
            logger.warning("Agent memory unavailable (disabled): %s", e)
            _collection_disabled = True
            _collection = None
        return _collection


def remember_turn(uid: str, chat_id: str, user_text: str, assistant_text: str) -> None:
    """Persist a completed Q/A turn to episodic memory (best-effort)."""
    if not user_text or not assistant_text:
        return
    col = _get_collection()
    if col is None:
        return
    try:
        doc = f"User asked: {user_text.strip()}\nAssistant answered: {assistant_text.strip()}"
        col.add(
            ids=[f"{uid or 'anon'}:{chat_id}:{int(time.time() * 1000)}"],
            documents=[doc[:4000]],
            metadatas=[{"uid": uid or "", "chat_id": chat_id, "ts": time.time(), "kind": "turn"}],
        )
    except Exception as e:
        logger.debug("remember_turn failed: %s", e)


def recall(uid: str, query: str, n: int = 3) -> list[str]:
    """Return snippets of past turns relevant to the current query.

    Returns a list of short text snippets (most relevant first), or [] if
    memory is unavailable or nothing matches.
    """
    if not query:
        return []
    col = _get_collection()
    if col is None:
        return []
    try:
        where = {"uid": uid or ""}
        res = col.query(query_texts=[query], n_results=n, where=where)
        docs = res.get("documents") if res else None
        if not docs:
            return []
        return [d for d in docs[0] if d]
    except Exception as e:
        logger.debug("recall failed: %s", e)
        return []
