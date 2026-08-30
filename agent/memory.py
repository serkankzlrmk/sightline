"""agent/memory.py — cross-chat memory for the Sightline agent.

Two pillars (adapted from waku-agent's memory architecture):

  episodic  — `agent_memory` collection: one Q/A turn per exchange, embedded
              for cosine recall. "What the agent remembers talking about."
  semantic  — `agent_facts` collection: durable facts about the user, their
              projects, countries/regions of interest and preferences, distilled
              from turns by consolidation. "What is durably true."

Two managing helpers (the waku "hero" pattern):

  retrieval_gate  — a cheap model decides whether a turn needs memory at all.
                    Default-on recall is slow AND lets irrelevant memories bias
                    the answer. One small call; retrieval only when it helps.
  consolidation   — every N unconsolidated turns, a cheap model reads them and
                    extracts durable facts into the semantic store. Batching N
                    turns gives the summarizer enough context to find signal.

Design notes:
- Best-effort: every call is wrapped so a memory failure NEVER breaks a chat.
- Reuses the ChromaAdapter client + embedding function (no second model load).
- uid-scoped: a user only ever recalls their own memories (privacy).
"""

from __future__ import annotations

import json
import logging
import threading
import time

logger = logging.getLogger(__name__)

_collection = None
_facts_collection = None
_memory_disabled = False
_lock = threading.Lock()

_MEMORY_COLLECTION = "agent_memory"
_FACTS_COLLECTION = "agent_facts"

# Small/fast model used for the gate + consolidator (cheap single decisions).
_SMALL_MODEL = "google/gemini-2.5-flash"
_small_llm_cache = {}
_small_llm_lock = threading.Lock()


def _get_collection():
    """Lazy-load the episodic `agent_memory` collection (thread-safe)."""
    global _collection, _memory_disabled
    if _collection is not None:
        return _collection
    if _memory_disabled:
        return None
    with _lock:
        if _collection is not None:
            return _collection
        if _memory_disabled:
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
            _memory_disabled = True
            _collection = None
        return _collection


def _get_facts_collection():
    """Lazy-load the semantic `agent_facts` collection (thread-safe)."""
    global _facts_collection
    if _facts_collection is not None:
        return _facts_collection
    if _memory_disabled:
        return None
    with _lock:
        if _facts_collection is not None:
            return _facts_collection
        try:
            from blueprints.helpers import get_chroma_adapter

            adapter = get_chroma_adapter()
            _facts_collection = adapter.client.get_or_create_collection(
                name=_FACTS_COLLECTION,
                embedding_function=adapter.ef,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("✓ Agent facts collection ready (%s)", _FACTS_COLLECTION)
        except Exception as e:
            logger.warning("Agent facts unavailable: %s", e)
            _facts_collection = None
        return _facts_collection


def _small_llm(max_tokens: int = 600):
    """A cheap flash model for gate + consolidation decisions (lazy, cached)."""
    if max_tokens in _small_llm_cache:
        return _small_llm_cache[max_tokens]
    with _small_llm_lock:
        if max_tokens in _small_llm_cache:
            return _small_llm_cache[max_tokens]
        from langchain_openai import ChatOpenAI

        from config import _LLM_API_KEY, _LLM_BASE_URL

        _small_llm_cache[max_tokens] = ChatOpenAI(
            model=_SMALL_MODEL,
            base_url=_LLM_BASE_URL,
            api_key=_LLM_API_KEY,
            temperature=0,
            max_tokens=max_tokens,
        )
        return _small_llm_cache[max_tokens]


def _llm_json(prompt: str, max_tokens: int = 600) -> str | None:
    """Run one small-model call and return its text, or None on any failure."""
    try:
        from langchain_core.messages import HumanMessage

        resp = _small_llm(max_tokens=max_tokens).invoke([HumanMessage(content=prompt)])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        return text
    except Exception as e:
        logger.debug("memory small-model call failed: %s", e)
        return None


def _extract_json(text: str) -> dict | None:
    """Pull the first {...} object out of a model reply (tolerates reasoning)."""
    if not text or "{" not in text:
        return None
    try:
        return json.loads(text[text.index("{") : text.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return None


# ── Episodic write ──────────────────────────────────────────────────────────
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
            metadatas=[
                {"uid": uid or "", "chat_id": chat_id, "ts": time.time(), "kind": "turn", "consolidated": False}
            ],
        )
    except Exception as e:
        logger.debug("remember_turn failed: %s", e)


# ── Episodic read ───────────────────────────────────────────────────────────
def recall(uid: str, query: str, n: int = 3) -> list[str]:
    """Return snippets of past turns relevant to the current query (episodic)."""
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


# ── Semantic read ───────────────────────────────────────────────────────────
def recall_facts(uid: str, query: str, n: int = 5) -> list[str]:
    """Return durable facts (subject: content) relevant to the query."""
    if not query:
        return []
    col = _get_facts_collection()
    if col is None:
        return []
    try:
        res = col.query(query_texts=[query], n_results=n, where={"uid": uid or ""})
        docs = res.get("documents") if res else None
        if not docs:
            return []
        return [d for d in docs[0] if d]
    except Exception as e:
        logger.debug("recall_facts failed: %s", e)
        return []


# ── Retrieval gate ──────────────────────────────────────────────────────────
GATE_PROMPT = """\
You are a retrieval gate for a humanitarian-intelligence assistant's long-term memory.
Given the user's message, decide if answering well requires the user's stored
memories (their past questions, ongoing projects, countries of interest, or preferences).

Reply with ONLY this JSON, nothing else:
{"retrieve": true/false, "query": "<search keywords if true, else empty>", "reason": "<5 words>"}

General knowledge, one-off data lookups, or self-contained requests -> false.
Anything referencing earlier conversations, the user's ongoing work, or their preferences -> true.

User message: {message}"""


def should_retrieve(message: str) -> tuple[bool, str, str]:
    """Returns (retrieve?, search_query, reason). Fails open — a stale memory
    beats a lost one, so any gate error retrieves."""
    text = _llm_json(GATE_PROMPT.format(message=message))
    if not text:
        return True, message, "gate failed open"
    decision = _extract_json(text)
    if decision is None:
        return True, message, "gate returned no JSON — failing open"
    return (
        bool(decision.get("retrieve")),
        decision.get("query") or message,
        decision.get("reason", ""),
    )


def gated_recall(uid: str, message: str, n: int = 3) -> str:
    """Gate + episodic + semantic → a compact memory block for the system prompt.

    Returns "" when the gate decides no memory is needed (no retrieval, no
    noise) or when nothing relevant is found.
    """
    try:
        retrieve, query, reason = should_retrieve(message)
        if not retrieve:
            return ""
        snippets = recall(uid, query, n) + recall_facts(uid, query, 5)
        if not snippets:
            return ""
        return "\n".join(f"- {s[:300]}" for s in snippets)
    except Exception as e:
        logger.debug("gated_recall failed: %s", e)
        return ""


# ── Consolidation ───────────────────────────────────────────────────────────
SUMMARIZER_PROMPT = """\
You distill a user's recent conversations with a humanitarian-intelligence assistant into long-term memory.

From the exchanges below, extract:
1. durable facts about the user, their projects, countries/regions of interest, or preferences — only things worth remembering in a month; skip one-off data lookups and chit-chat.

Reply with ONLY this JSON:
{"facts": [{"subject": "<who/what>", "content": "<one sentence>"}]}

Exchanges:
{log}"""


def _distill_facts(log: str) -> list[dict]:
    """Run the summarizer over a batch of turns; return [{subject, content}]."""
    text = _llm_json(SUMMARIZER_PROMPT.format(log=log), max_tokens=4096)
    if not text:
        return []
    data = _extract_json(text)
    if not data:
        return []
    return data.get("facts", [])


def maybe_consolidate(uid: str, every_n: int = 5) -> int:
    """Distill unconsolidated turns into durable facts (best-effort).

    Runs only when the user has >= `every_n` unconsolidated turns. Returns the
    number of new facts written (0 = not due, or nothing worth keeping).
    """
    col = _get_collection()
    if col is None:
        return 0
    try:
        res = col.get(where={"uid": uid or ""}, include=["documents", "metadatas"])
    except Exception as e:
        logger.debug("maybe_consolidate fetch failed: %s", e)
        return 0
    ids = res.get("ids") or []
    docs = res.get("documents") or []
    metas = res.get("metadatas") or []

    unconsolidated = []
    for did, doc, meta in zip(ids, docs, metas, strict=True):
        if meta and not meta.get("consolidated"):
            unconsolidated.append((did, doc))
    if len(unconsolidated) < every_n:
        return 0

    batch = unconsolidated[-every_n:]  # most recent N unconsolidated turns
    log = "\n".join(f"- {doc}" for _, doc in batch)
    facts = _distill_facts(log)
    if not facts:
        return 0

    fcol = _get_facts_collection()
    if fcol is None:
        return 0
    now = time.time()
    fids, fdocs, fmetas = [], [], []
    for f in facts:
        subj = (f.get("subject") or "").strip()
        content = (f.get("content") or "").strip()
        if not subj or not content:
            continue
        fids.append(f"{uid or 'anon'}:fact:{int(now * 1000)}:{len(fids)}")
        fdocs.append(f"{subj}: {content}")
        fmetas.append({"uid": uid or "", "subject": subj, "ts": now, "kind": "fact"})
    if not fdocs:
        return 0
    try:
        fcol.add(ids=fids, documents=fdocs, metadatas=fmetas)
    except Exception as e:
        logger.debug("facts write failed: %s", e)
        return 0
    # Mark the distilled turns consolidated so they aren't re-summarized
    try:
        col.update(ids=[d for d, _ in batch], metadatas=[{"consolidated": True} for _ in batch])
    except Exception as e:
        logger.debug("consolidated flag update failed: %s", e)
    logger.info("✓ Consolidated %d turns → %d facts (uid=%s)", len(batch), len(fdocs), uid)
    return len(fdocs)
