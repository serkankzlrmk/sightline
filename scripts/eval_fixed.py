#!/usr/bin/env python3
"""Run the fixed evaluation questions through the chat agent and collect turn ids.

The runner does not judge answers. It produces a JSON run file with the question,
turn id, tool list and cost; then ``scripts/eval_agent.py --turn-ids`` can judge
exactly that set (no sampling contamination from unrelated chats).

Usage:
    python scripts/eval_fixed.py --dry-run
    python scripts/eval_fixed.py --base-url http://127.0.0.1:5001
    python scripts/eval_fixed.py --base-url https://example.com --token "$TOKEN"
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUESTIONS = ROOT / "scripts" / "eval_questions.json"
DEFAULT_OUT = ROOT / "data" / "eval" / "fixed_run.json"


def _headers(token: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _new_chat(base_url: str, headers: dict) -> str:
    """Create an isolated chat so each evaluation question starts clean."""
    resp = requests.post(base_url.rstrip("/") + "/api/agent/chats/new", headers=headers, timeout=30)
    resp.raise_for_status()
    return str(resp.json().get("id") or "")


def run_one(base_url: str, question: str, token: str, timeout: int) -> dict:
    headers = _headers(token)
    try:
        _new_chat(base_url, headers)
    except Exception:
        pass  # older servers / API key mode: fall back to the active chat
    payload = {"message": question}
    started = time.time()
    resp = requests.post(
        base_url.rstrip("/") + "/api/agent/chat", json=payload, headers=headers, stream=True, timeout=timeout
    )
    resp.raise_for_status()
    done = None
    error = None
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw or not raw.startswith("data: "):
            continue
        try:
            event = json.loads(raw[6:])
        except ValueError:
            continue
        if event.get("type") == "done":
            done = event
        elif event.get("type") == "error":
            error = event
    elapsed = round((time.time() - started) * 1000)
    if error:
        return {"status": "error", "error": error, "elapsed_ms": elapsed}
    if not done:
        return {"status": "no_done", "elapsed_ms": elapsed}
    return {
        "status": "ok",
        "turn_id": done.get("turn_id", ""),
        "tools": [t.get("tool") for t in done.get("tools", [])],
        "citations": done.get("citations"),
        "no_answer": done.get("no_answer"),
        "cost": done.get("cost"),
        "elapsed_ms": elapsed,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Run fixed eval questions and collect turn ids")
    ap.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    ap.add_argument("--base-url", default="http://127.0.0.1:5001")
    ap.add_argument("--token", default="")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--max", type=int, default=0, help="limit questions (0 = all)")
    ap.add_argument("--offset", type=int, default=0, help="skip the first N questions")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    if args.offset:
        questions = questions[args.offset :]
    if args.max:
        questions = questions[: args.max]
    if args.dry_run:
        for q in questions:
            print(f"{q['id']}: {q['question']}")
        print(f"\n{len(questions)} questions")
        return 0

    results = []
    for i, item in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {item['id']}", flush=True)
        try:
            outcome = run_one(args.base_url, item["question"], args.token, args.timeout)
        except Exception as exc:  # noqa: BLE001
            outcome = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        results.append({**item, **outcome})
        print(f"  -> {outcome.get('status')} {outcome.get('turn_id', '')}", flush=True)
        # Persist after every question so a timeout/kill cannot lose the run.
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"base_url": args.base_url, "results": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if args.sleep:
            time.sleep(args.sleep)

    ids = [r["turn_id"] for r in results if r.get("turn_id")]
    print(f"\nwrote {out} ({len(ids)}/{len(results)} turns)")
    if ids:
        print("\nJudge this exact set with:")
        print(f"  python scripts/eval_agent.py --days 365 --turn-ids {','.join(ids)} --samples 3 --apply")
    return 0 if len(ids) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
