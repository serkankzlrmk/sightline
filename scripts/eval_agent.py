#!/usr/bin/env python3
"""scripts/eval_agent.py — offline chat evaluation harness (G-Eval style).

Samples recent *ok* chat turns from ``obs.db``, pairs each with its question/answer
from ``chats.db`` and the tool evidence previews recorded for that turn, asks a
**cross-family** judge model to score the answer 1–5 against an anchored rubric,
and (optionally) persists the verdict into ``obs.db`` ``eval_scores``.

Design follows the NotebookLM research synthesis in
``docs/research/notebooklm_rag_eval.md``:

- G-Eval shape: task intro + explicit criteria + reasoning-then-score form.
- **Multi-sample scoring** (default 3) instead of a single integer — reduces the
  "everything is a 3" compression documented for 1–5 LLM judges.
- **Cross-family judge** by default (answers are usually Gemini; default judge is
  OpenAI GPT-5.1) to mitigate self-preference bias.
- **Evidence-aware**: when tool previews exist, the judge checks claims against
  them; when they do not, the prompt says so explicitly (no pretended grounding).
- Length is declared a non-signal; a grounded "no evidence found" is not penalised.
- Re-running with ``--apply`` **updates** the prior verdict (unique per
  turn+judge+mode) instead of double-counting.

Usage (defaults to a dry run):
    python scripts/eval_agent.py --sample 25 --days 30            # judge + report
    python scripts/eval_agent.py --sample 25 --apply              # persist verdicts
    python scripts/eval_agent.py --sample 10 --samples 1 --judge-model deepseek/deepseek-chat
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

import config  # noqa: E402
from observability import store  # noqa: E402

_QT = 4000  # max chars of question/answer sent to the judge
_EVIDENCE_CHARS = 3000  # total tool-evidence budget per turn
DEFAULT_JUDGE_MODEL = "openai/gpt-5.1"  # cross-family vs Gemini answer models
DEFAULT_SAMPLES = 3


# ── Sampling ─────────────────────────────────────────────────────────────────


def sample_turns(days: int = 30, limit: int = 25) -> list[dict]:
    """Pair recent ok turns (obs.db) with Q/A (chats.db) + tool evidence."""
    samples: list[dict] = []
    with closing(store.get_obs_db()) as conn:
        turns = conn.execute(
            """
            SELECT turn_id, chat_id, model_id, started_at, finished_at,
                   latency_ms, tokens_in, tokens_out, no_answer
            FROM turns
            WHERE status = 'ok' AND started_at >= ?
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (time.time() - max(1, int(days)) * 86400, max(1, int(limit))),
        ).fetchall()

    for t in turns:
        pair = _pair_with_messages(dict(t))
        if not pair:
            continue
        pair["turn_id"] = t["turn_id"]
        pair["chat_id"] = t["chat_id"]
        pair["model_id"] = t["model_id"]
        pair["latency_ms"] = t["latency_ms"]
        pair["no_answer"] = int(t["no_answer"] or 0)
        pair["evidence"] = _tool_evidence(t["turn_id"])
        samples.append(pair)
    return samples


def _pair_with_messages(t: dict) -> dict | None:
    """Match the assistant message nearest ``finished_at`` (+ its user turn).

    Turn ids are random UUIDs, so the join is chronological within the chat. A
    ±60 s window keeps the match safe against the sub-second clock skew between
    the two writes (they happen from the same process anyway).
    """
    import sqlite3

    path = config.CHATS_DB_PATH
    if not Path(path).exists():
        return None
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        m = conn.execute(
            """
            SELECT id, ts, content FROM chat_messages
            WHERE chat_id = ? AND role = 'assistant'
              AND ts BETWEEN ? - 60 AND ? + 60
            ORDER BY MIN(ABS(ts - ?), ABS(ts - ?)) LIMIT 1
            """,
            (t["chat_id"], t["finished_at"], t["finished_at"], t["finished_at"], t["finished_at"]),
        ).fetchone()
        if not m:
            return None
        u = conn.execute(
            """
            SELECT content FROM chat_messages
            WHERE chat_id = ? AND role = 'user' AND id < ?
            ORDER BY id DESC LIMIT 1
            """,
            (t["chat_id"], m["id"]),
        ).fetchone()
        if not u or not u["content"].strip():
            return None
        return {
            "question": u["content"][:_QT],
            "answer": m["content"][:_QT],
        }
    finally:
        conn.close()


def _tool_evidence(turn_id: str, max_chars: int = _EVIDENCE_CHARS) -> str:
    """Rebuild a compact evidence block from persisted tool previews.

    Only the first ~1.2 KB of each tool result is stored (privacy/size), which is
    enough for the judge to check whether specific claims are supported by the
    retrieved evidence. Returns "" for backfilled turns without tool records.
    """
    try:
        with closing(store.get_obs_db()) as conn:
            rows = conn.execute(
                """
                SELECT tool, status, summary, result_preview
                FROM tool_calls WHERE turn_id = ? ORDER BY seq LIMIT 6
                """,
                (str(turn_id),),
            ).fetchall()
    except Exception:
        return ""
    if not rows:
        return ""
    chunks: list[str] = []
    used = 0
    for r in rows:
        block = f"[{r['tool']} | {r['status']}] {r['summary']}\n{(r['result_preview'] or '')[:900]}"
        if used + len(block) > max_chars:
            block = block[: max(0, max_chars - used)]
        if not block:
            break
        chunks.append(block)
        used += len(block)
    return "\n\n".join(chunks)


# ── Judge ────────────────────────────────────────────────────────────────────

_RUBRIC = """You are a strict but fair evaluator of a humanitarian Q&A assistant's answers.

The user asked a research question about humanitarian crises / disaster data. A
tool-calling agent answered using live sources (ReliefWeb, HDX, GDACS, weather,
etc.). Score ONLY the answer below.

Evaluate with these anchored criteria (1-5):
5 - Fully grounded, on-point, complete, clearly written; operational details and
    citations are consistent with the evidence provided.
4 - Correct and relevant with minor gaps or phrasing issues.
3 - Partially useful: relevant but thin, tangential, or under-answered.
2 - Mostly wrong, misleading, or grossly evasive.
1 - Fabricated, dangerous, or entirely off-target.

Evaluation steps:
1. Read the QUESTION and the EVIDENCE (tool previews) if provided.
2. Decompose the ANSWER into factual claims.
3. Check each claim against the EVIDENCE. If no evidence was stored, say so and
   evaluate internal consistency only — do not pretend claims were verified.
4. Check relevance to the question, completeness (relative to the question, not
   maximal detail), and citation discipline (inline [n] markers are a plus; missing
   citations only hurt if specific claims are made).
5. A grounded "no sufficient evidence" answer is a CORRECT outcome, not a failure.

Anti-bias rules (hard):
- Length is NOT quality. Never reward verbosity; never penalize concise answers.
- Do not prefer your own style or model family over a different factual style.
- Do not reward confident tone; reward evidence alignment.

Return a single JSON object and nothing else:
{"reasoning": "<max 60 words>", "score": <integer 1-5>, "issues": ["<max 12 words each>", ...]}
"""  # noqa: E501


def _judge_messages(sample: dict) -> list[dict]:
    evidence = (sample.get("evidence") or "").strip()
    evidence_block = (
        f"EVIDENCE (retrieved tool previews):\n{evidence}"
        if evidence
        else "EVIDENCE: none stored for this turn (judge internal consistency only)."
    )
    return [
        {"role": "system", "content": _RUBRIC},
        {
            "role": "user",
            "content": (
                f"QUESTION:\n{sample['question']}\n\n{evidence_block}\n\nANSWER TO EVALUATE:\n{sample['answer']}"
            ),
        },
    ]


def _parse_verdict(text: str) -> dict | None:
    """Extract {"score": int, "issues": [...]} from a model reply (tolerant)."""
    m = re.search(r"\{.*}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            score = int(float(obj.get("score")))
            if 1 <= score <= 5:
                issues = [str(i)[:60] for i in obj.get("issues", []) if str(i).strip()][:5]
                return {"score": score, "issues": issues}
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    m = re.search(r"\b([1-5])\b", text)
    if m:
        return {"score": int(m.group(1)), "issues": ["unparsed verdict"]}
    return None


def _judge_once(
    sample: dict,
    judge_model: str,
    base_url: str,
    api_key: str,
    timeout: int,
) -> dict | None:
    payload = {
        "model": judge_model,
        "temperature": 0.2,
        "max_tokens": 500,
        "messages": _judge_messages(sample),
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = base_url.rstrip("/") + "/chat/completions"
    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=timeout)
            if r.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"] or ""
            return _parse_verdict(content)
        except Exception:
            if attempt == 2:
                return None
            time.sleep(2)
    return None


def ask_judge(
    sample: dict,
    judge_model: str,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: int = 180,
    samples: int = DEFAULT_SAMPLES,
) -> dict | None:
    """Judge one answer with ``samples`` independent calls and average the score.

    Multi-sampling is the logprob-free approximation of G-Eval's probability-
    weighted score: it smooths the 1-5 integer collapse without requiring a
    provider that exposes token logprobs. Returns None when every call fails.
    """
    base_url = base_url or config._LLM_BASE_URL
    api_key = api_key or config._LLM_API_KEY
    samples = max(1, min(int(samples or 1), 5))
    verdicts = []
    for _ in range(samples):
        v = _judge_once(sample, judge_model, base_url, api_key, timeout)
        if v is not None:
            verdicts.append(v)
        time.sleep(0.3)
    if not verdicts:
        return None
    avg = sum(v["score"] for v in verdicts) / len(verdicts)
    issues: list[str] = []
    for v in verdicts:
        for issue in v["issues"]:
            if issue not in issues:
                issues.append(issue)
    return {
        "score": round(avg, 2),
        "issues": issues[:5],
        "sample_scores": [v["score"] for v in verdicts],
        "agreement": 1.0 - (max(v["score"] for v in verdicts) - min(v["score"] for v in verdicts)) / 4.0,
    }


# ── Runner ───────────────────────────────────────────────────────────────────


def _same_family(judge_model: str, answer_model: str) -> bool:
    """Heuristic self-preference guard: compare provider prefixes (google/, openai/, ...)."""
    return bool(judge_model and answer_model and judge_model.split("/")[0] == answer_model.split("/")[0])


def run(
    days: int = 30,
    limit: int = 25,
    apply: bool = False,
    judge_model: str | None = None,
    samples: int = DEFAULT_SAMPLES,
    use_evidence: bool = True,
) -> dict:
    """Sample chat turns, judge them, report (and optionally persist) verdicts."""
    judge_model = judge_model or DEFAULT_JUDGE_MODEL
    sampled = sample_turns(days=days, limit=limit)
    results: list[dict] = []
    same_family_warnings: list[str] = []
    for s in sampled:
        if not use_evidence:
            s = {**s, "evidence": ""}
        if _same_family(judge_model, s.get("model_id") or ""):
            same_family_warnings.append(s["turn_id"])
        verdict = ask_judge(s, judge_model, samples=samples)
        rec = {
            "turn_id": s["turn_id"],
            "score": verdict["score"] if verdict else None,
            "issues": (verdict or {}).get("issues", []),
            "sample_scores": (verdict or {}).get("sample_scores", []),
            "agreement": (verdict or {}).get("agreement"),
        }
        if verdict:
            rec["question"] = s["question"][:80]
            if apply:
                store.record_eval_score(
                    turn_id=s["turn_id"],
                    score=verdict["score"],
                    judge_model=judge_model,
                    chat_id=s["chat_id"],
                    judge="offline",
                    issues=verdict["issues"],
                )
        results.append(rec)
        time.sleep(0.5)  # stay polite with the shared OpenRouter quota

    scored = [r["score"] for r in results if r["score"] is not None]
    low = [r for r in results if r["score"] is not None and r["score"] < 3]
    return {
        "judge_model": judge_model,
        "samples_per_answer": max(1, min(int(samples or 1), 5)),
        "sampled": len(sampled),
        "scored": len(scored),
        "failed": len(sampled) - len(scored),
        "avg": round(sum(scored) / len(scored), 3) if scored else None,
        "low": low,
        "dry_run": not apply,
        "same_family_warnings": same_family_warnings,
        "results": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Offline G-Eval chat quality eval over recent Sightline turns")
    ap.add_argument("--days", type=int, default=30, help="look back N days of turns")
    ap.add_argument("--sample", type=int, default=25, help="max turns to judge (clamped to 50)")
    ap.add_argument("--samples", type=int, default=DEFAULT_SAMPLES, help="judge calls per answer (1-5)")
    ap.add_argument("--apply", action="store_true", help="persist/update verdicts in obs.db (default: dry run)")
    ap.add_argument("--judge-model", default=None, help=f"judge model id (default: {DEFAULT_JUDGE_MODEL})")
    ap.add_argument("--no-evidence", action="store_true", help="do not send tool previews to the judge")
    args = ap.parse_args()

    if config.LLM_PROVIDER != "openrouter" or not config._LLM_API_KEY:
        print("error: no OpenRouter API key available for the judge (LLM_PROVIDER)", file=sys.stderr)
        return 2

    report = run(
        days=args.days,
        limit=max(1, min(args.sample, 50)),
        apply=args.apply,
        judge_model=args.judge_model,
        samples=args.samples,
        use_evidence=not args.no_evidence,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
