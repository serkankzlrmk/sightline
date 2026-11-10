#!/usr/bin/env python3
"""scripts/calibrate_judge.py — blind human calibration of the LLM judge.

Why: an LLM judge is only useful if its 1–5 scores agree with a human's. This
script exports a **blind** rating sheet (question + answer + evidence, *without*
the judge score), you fill the `human_score` column, then it compares human vs
judge scores and reports agreement metrics.

Workflow
--------
1. Judge some turns first (the sheet only contains already-judged turns)::

       python scripts/eval_agent.py --days 3650 --sample 30 --apply

2. Export a blind sheet::

       python scripts/calibrate_judge.py --export 30 --out data/calibration/round1.csv

3. Open the CSV in Excel/Sheets, read each answer against the rubric and fill
   `human_score` (integer 1–5) + optional `notes`. Do NOT look up judge scores.

4. Score the sheet (writes human labels + a calibration run into obs.db)::

       python scripts/calibrate_judge.py --score data/calibration/round1.csv

Metrics: quadratic weighted kappa (QWK, primary), Spearman, Pearson, MAE,
exact/within-1 agreement, confusion matrix and the biggest disagreements.
Guideline: QWK ≥ 0.6 good, ≥ 0.8 excellent; below 0.4 revise the rubric.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from observability import store  # noqa: E402
from scripts.eval_agent import _pair_with_messages, _tool_evidence  # noqa: E402

_ANSWER_CHARS = 4000
_EVIDENCE_CHARS = 2000


# ── Agreement metrics (shared with the admin calibration API) ───────────────
from observability.calibration import compute_metrics, confusion_matrix

# ── Export (blind sheet) ─────────────────────────────────────────────────────


def _judged_turns(days: int, judge_model: str = "") -> list[dict]:
    """Latest judge score per turn (optionally filtered by judge model)."""
    with closing(store.get_obs_db()) as conn:
        rows = conn.execute(
            """
            SELECT turn_id, score, judge_model, created_at
            FROM eval_scores WHERE created_at >= ?
            ORDER BY created_at DESC
            """,
            (time.time() - max(1, int(days)) * 86400,),
        ).fetchall()
    seen: dict[str, dict] = {}
    for r in rows:
        tid = r["turn_id"]
        if not tid or tid in seen:
            continue
        if judge_model and r["judge_model"] != judge_model:
            continue
        seen[tid] = {"turn_id": tid, "judge_score": float(r["score"]), "judge_model": r["judge_model"]}
    return list(seen.values())


def _stratified(rows: list[dict], n: int) -> list[dict]:
    """Round-robin across score buckets so the sheet covers low/mid/high."""
    buckets = {"low": [], "mid": [], "high": []}
    for r in rows:
        score = r["judge_score"]
        key = "low" if score < 2.5 else ("mid" if score < 3.5 else "high")
        buckets[key].append(r)
    for b in buckets.values():
        b.sort(key=lambda r: r["judge_score"])
    selected: list[dict] = []
    order = ["low", "mid", "high"]
    i = 0
    while len(selected) < n and any(buckets.values()):
        key = order[i % len(order)]
        if buckets[key]:
            selected.append(buckets[key].pop(0))
        i += 1
        if i > n * 10:
            break
    return selected


def export_sheet(
    n: int = 30, days: int = 3650, judge_model: str = "", out: str = "", rubric_version: str = "v1"
) -> dict:
    n = max(5, min(int(n or 30), 200))
    out_path = Path(out or "data/calibration/human_round1.csv")
    if not out_path.is_absolute():
        out_path = Path(config.PROJECT_ROOT) / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    judged = _judged_turns(days=days, judge_model=judge_model)
    if not judged:
        raise SystemExit(
            "no judged turns found — run scripts/eval_agent.py --apply first (e.g. --days 3650 --sample 30 --apply)"
        )
    selected = _stratified(judged, min(n, len(judged)))

    rows = []
    missing = 0
    with closing(store.get_obs_db()) as conn:
        for item in selected:
            turn = conn.execute(
                "SELECT turn_id, chat_id, model_id, finished_at FROM turns WHERE turn_id = ?",
                (item["turn_id"],),
            ).fetchone()
            if turn is None:
                missing += 1
                continue
            pair = _pair_with_messages(dict(turn))
            if not pair:
                missing += 1
                continue
            evidence = _tool_evidence(item["turn_id"], max_chars=_EVIDENCE_CHARS)
            rows.append(
                {
                    "turn_id": item["turn_id"],
                    "question": pair["question"],
                    "answer": pair["answer"][:_ANSWER_CHARS],
                    "evidence": evidence,
                    "human_score": "",
                    "notes": "",
                }
            )

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["turn_id", "question", "answer", "evidence", "human_score", "notes"],
        )
        writer.writeheader()
        writer.writerows(rows)
    meta = {
        "created_at": time.time(),
        "n_requested": n,
        "n_exported": len(rows),
        "days": days,
        "judge_model": judge_model or "(any)",
        "rubric_version": rubric_version,
        "out": str(out_path),
        "note": "Blind sheet: judge scores intentionally omitted. Fill human_score 1-5.",
    }
    out_path.with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "exported": len(rows),
        "missing_pairs": missing,
        "candidates": len(judged),
        "out": str(out_path),
        "buckets": {
            "low": sum(1 for r in selected if r["judge_score"] < 2.5),
            "mid": sum(1 for r in selected if 2.5 <= r["judge_score"] < 3.5),
            "high": sum(1 for r in selected if r["judge_score"] >= 3.5),
        },
        "warning": "En az 20–30 örnek önerilir; 1–5 çapalarını kullanarak kör puanla." if len(rows) < 20 else "",
    }


# ── Score (human vs judge) ───────────────────────────────────────────────────


def _read_sheet(path: Path) -> tuple[list[dict], list[dict], int]:
    rows: list[dict] = []
    invalid: list[dict] = []
    skipped = 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            tid = (raw.get("turn_id") or "").strip()
            human = (raw.get("human_score") or "").strip()
            if not tid or not human:
                skipped += 1
                continue
            try:
                score = float(human.replace(",", "."))
            except ValueError:
                invalid.append({"turn_id": tid, "reason": "human_score not a number"})
                continue
            if score < 1 or score > 5:
                invalid.append({"turn_id": tid, "reason": "human_score outside 1-5"})
                continue
            rows.append({"turn_id": tid, "human_score": score, "notes": (raw.get("notes") or "").strip()})
    return rows, invalid, skipped


def score_sheet(
    path: str,
    rater: str = "human",
    rubric_version: str = "v1",
    min_n: int = 10,
    judge_model: str = "",
) -> dict:
    sheet = Path(path)
    if not sheet.exists():
        raise SystemExit(f"sheet not found: {sheet}")
    rows, invalid, skipped = _read_sheet(sheet)
    if len(rows) < max(1, int(min_n)):
        raise SystemExit(f"need at least {min_n} completed rows (got {len(rows)})")

    turn_ids = [r["turn_id"] for r in rows]
    with closing(store.get_obs_db()) as conn:
        placeholders = ",".join("?" * len(turn_ids))
        judged = conn.execute(
            f"SELECT turn_id, score, judge_model, created_at FROM eval_scores "
            f"WHERE turn_id IN ({placeholders}) ORDER BY created_at DESC",
            tuple(turn_ids),
        ).fetchall()
    judge_by_turn: dict[str, dict] = {}
    for r in judged:
        if r["turn_id"] in judge_by_turn:
            continue
        if judge_model and r["judge_model"] != judge_model:
            continue
        judge_by_turn[r["turn_id"]] = {"score": float(r["score"]), "judge_model": r["judge_model"]}

    stored = 0
    paired: list[tuple[dict, dict]] = []
    missing_judge: list[str] = []
    for row in rows:
        if store.record_human_label(
            turn_id=row["turn_id"],
            score=row["human_score"],
            rater=rater,
            notes=row["notes"],
            rubric_version=rubric_version,
        ):
            stored += 1
        j = judge_by_turn.get(row["turn_id"])
        if j is None:
            missing_judge.append(row["turn_id"])
        else:
            paired.append((row, j))

    human = [r["human_score"] for r, _ in paired]
    judge = [j["score"] for _, j in paired]
    if len(paired) < 2:
        raise SystemExit(
            f"not enough matched human+judge pairs — ensure the sheet came from judged turns (matched {len(paired)})"
        )
    metrics = compute_metrics(human, judge)
    confusion = confusion_matrix(human, judge)
    disagreements = sorted(
        (
            {
                "turn_id": r["turn_id"],
                "human": r["human_score"],
                "judge": j["score"],
                "diff": round(j["score"] - r["human_score"], 2),
                "notes": r.get("notes", ""),
            }
            for r, j in paired
            if round(j["score"]) != round(r["human_score"])
        ),
        key=lambda d: -abs(d["diff"]),
    )[:10]
    jmodel = judge_model or next(iter(judge_by_turn.values()))["judge_model"]
    detail = {
        "rater": rater,
        "rubric_version": rubric_version,
        "skipped_rows": skipped,
        "invalid_rows": invalid,
        "missing_judge": missing_judge,
        "disagreements": disagreements,
        "confusion_rows_human_cols_judge": confusion,
    }
    store.record_calibration_run(jmodel, 0, len(paired), metrics, detail)
    return {
        "sheet": str(sheet),
        "rater": rater,
        "judge_model": jmodel,
        "stored_human_labels": stored,
        "matched_pairs": len(paired),
        "missing_judge": missing_judge,
        "invalid_rows": invalid,
        "skipped_rows": skipped,
        "metrics": metrics,
        "confusion": {"rows": "human 1-5", "cols": "judge 1-5", "matrix": confusion},
        "top_disagreements": disagreements,
        "next_step": "QWK < 0.6 ise rubric çapalarını güncelle ve judge'ı aynı örneklerle tekrar çalıştır.",
    }


def _latest() -> dict:
    return store.calibration_summary(days=3650)


def main() -> int:
    ap = argparse.ArgumentParser(description="Blind human calibration of the LLM judge (export + score)")
    ap.add_argument("--export", type=int, metavar="N", help="export N judged turns as a blind CSV sheet")
    ap.add_argument("--out", default="data/calibration/human_round1.csv", help="output CSV path")
    ap.add_argument("--days", type=int, default=3650, help="look back N days of judged turns")
    ap.add_argument("--judge-model", default="", help="filter judged turns by judge model")
    ap.add_argument("--rubric-version", default="v1", help="rubric version label")
    ap.add_argument("--score", metavar="CSV", help="score a completed human sheet")
    ap.add_argument("--rater", default="human", help="rater name stored with labels")
    ap.add_argument("--min-n", type=int, default=10, help="minimum completed rows for scoring")
    ap.add_argument("--latest", action="store_true", help="print the latest calibration summary")
    args = ap.parse_args()

    if args.export:
        report = export_sheet(
            n=args.export,
            days=args.days,
            judge_model=args.judge_model,
            out=args.out,
            rubric_version=args.rubric_version,
        )
    elif args.score:
        report = score_sheet(
            args.score,
            rater=args.rater,
            rubric_version=args.rubric_version,
            min_n=args.min_n,
            judge_model=args.judge_model,
        )
    elif args.latest:
        report = _latest()
    else:
        ap.error("use --export N, --score CSV, or --latest")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
