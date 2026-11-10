#!/usr/bin/env python3
"""scripts/backfill_turns.py — reconstruct obs.db turns from historical chats.db.

Production starts with an empty ``obs.db``: telemetry is only written for chat
turns after the observability feature ships. Without historical turns the offline
evaluator has nothing to sample for weeks. This script converts existing
``chat_messages`` pairs (user question → assistant answer) into ``turns`` rows so
chat evaluation can run immediately.

What is available and what is not:
- available: question/answer text, timestamps, chat/uid, model display name,
  tool names/summaries from ``chat_messages.meta`` (if present), citations and
  no-answer signals derived from the answer.
- NOT available: token usage, cost, per-tool latency/result previews, status.
  Backfilled turns are marked ``meta.backfilled = true`` and have zero tokens/cost.
  Judge prompts explicitly receive no evidence for them.

Usage (dry run by default):
    python scripts/backfill_turns.py --days 90            # report only
    python scripts/backfill_turns.py --days 90 --apply    # write to obs.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from observability import store  # noqa: E402
from observability.metrics import answer_signals  # noqa: E402


def iter_turns(days: int = 3650, limit: int = 1000) -> list[dict]:
    """Read assistant messages plus their preceding user message from chats.db."""
    path = Path(config.CHATS_DB_PATH)
    if not path.exists():
        return []
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT m.id, m.chat_id, m.content AS answer, m.ts AS finished_at, m.meta,
                   (SELECT content FROM chat_messages u
                     WHERE u.chat_id = m.chat_id AND u.role = 'user' AND u.id < m.id
                     ORDER BY u.id DESC LIMIT 1) AS question,
                   (SELECT ts FROM chat_messages u
                     WHERE u.chat_id = m.chat_id AND u.role = 'user' AND u.id < m.id
                     ORDER BY u.id DESC LIMIT 1) AS question_ts,
                   c.uid
            FROM chat_messages m
            JOIN chats c ON c.id = m.chat_id
            WHERE m.role = 'assistant'
              AND m.ts >= ?
              AND TRIM(COALESCE(m.content, '')) != ''
            ORDER BY m.ts DESC
            LIMIT ?
            """,
            (time.time() - max(1, int(days)) * 86400, max(1, int(limit))),
        ).fetchall()
    finally:
        conn.close()

    turns = []
    for r in rows:
        if not r["question"] or not str(r["question"]).strip():
            continue
        try:
            meta = json.loads(r["meta"] or "{}")
        except (json.JSONDecodeError, TypeError):
            meta = {}
        tools = [
            {
                "tool": t.get("tool", ""),
                "group": t.get("group", ""),
                "server": t.get("server", "native"),
                "status": t.get("status", "ok"),
                "duration_ms": int(t.get("duration_ms") or 0),
                "result_chars": int(t.get("result_chars") or 0),
                "summary": t.get("summary", ""),
            }
            for t in (meta.get("tools") or [])
            if isinstance(t, dict)
        ]
        signals = answer_signals(r["answer"])
        finished_at = float(r["finished_at"] or 0)
        turns.append(
            {
                "turn_id": f"backfill-{r['id']}",
                "uid": r["uid"] or "",
                "chat_id": r["chat_id"],
                "model_key": "backfilled",
                "model_id": str(meta.get("model") or ""),
                "mode": str(meta.get("mode") or "analyst"),
                "started_at": float(r["question_ts"] or finished_at - 1),
                "finished_at": finished_at,
                "latency_ms": int(meta.get("latency_ms") or 0),
                "total_ms": int(meta.get("total_ms") or 0),
                "status": "ok",
                "iterations": int(meta.get("iterations") or 0),
                "tokens_in": int((meta.get("usage") or {}).get("in") or 0),
                "tokens_out": int((meta.get("usage") or {}).get("out") or 0),
                "cost": float(meta.get("cost") or 0.0),
                "groups": meta.get("sources") or {},
                "citations": signals["citations"],
                "answer_chars": signals["answer_chars"],
                "no_answer": signals["no_answer"],
                "meta": {
                    "backfilled": True,
                    "model_label": meta.get("model") or "",
                    "question": str(r["question"])[:400],
                },
                "answer": r["answer"],
                "tools": tools,
            }
        )
    return turns


def backfill(days: int = 3650, limit: int = 1000, apply: bool = False) -> dict:
    turns = iter_turns(days=days, limit=limit)
    written = 0
    if apply:
        for t in turns:
            tools = t.pop("tools")
            if store.record_chat_turn(t, tools=tools):
                written += 1
    return {
        "found": len(turns),
        "written": written,
        "dry_run": not apply,
        "days": days,
        "limit": limit,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill obs.db turns from historical chats.db messages")
    ap.add_argument("--days", type=int, default=3650, help="look back N days (default: all history)")
    ap.add_argument("--limit", type=int, default=1000, help="max turns to scan")
    ap.add_argument("--apply", action="store_true", help="write to obs.db (default: dry run)")
    args = ap.parse_args()
    report = backfill(days=args.days, limit=args.limit, apply=args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
