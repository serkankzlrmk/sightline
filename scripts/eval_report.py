#!/usr/bin/env python3
"""Generate a reproducible evaluation report from obs.db.

The report aggregates judge scores, deterministic outcome signals, human
calibration agreement and per-model breakdown. It is intentionally aggregate-only:
no questions, answers, user ids or tool payloads are included.

Usage:
    python scripts/eval_report.py --days 365 --out docs/EVALUATION_RESULTS.md
    python scripts/eval_report.py --days 365 --rater human
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from observability import calibration, store  # noqa: E402


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((pct / 100.0) * (len(ordered) - 1))))
    return float(ordered[idx])


def _rate(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def collect(days: int, rater: str, min_human: int = 20) -> dict:
    cutoff = time.time() - max(1, min(days, 365)) * 86400
    with closing(store.get_obs_db()) as conn:
        rows = conn.execute(
            """
            SELECT t.turn_id, t.model_id, t.model_key, t.citations, t.no_answer,
                   t.tools_count, t.cost, t.latency_ms,
                   e.score, e.judge_model, e.judge, e.created_at
            FROM turns t
            JOIN eval_scores e ON e.turn_id = t.turn_id
            WHERE e.created_at >= ?
              AND t.turn_id NOT LIKE 'demo-%'
              AND e.id = (SELECT MAX(e2.id) FROM eval_scores e2 WHERE e2.turn_id = t.turn_id)
            ORDER BY e.created_at
            """,
            (cutoff,),
        ).fetchall()
        judged_ids = [r["turn_id"] for r in rows]
        if judged_ids:
            placeholders = ",".join("?" * len(judged_ids))
            feedback = conn.execute(
                f"SELECT rating, COUNT(*) AS n FROM feedback WHERE created_at >= ? AND turn_id IN ({placeholders}) GROUP BY rating",
                (cutoff, *judged_ids),
            ).fetchall()
        else:
            feedback = []

    scores = [float(r["score"]) for r in rows]
    if not scores:
        return {"count": 0, "days": days}

    dist = {n: 0 for n in range(1, 6)}
    for s in scores:
        dist[min(5, max(1, round(s)))] += 1

    models: dict[str, dict] = {}
    for r in rows:
        key = r["model_id"] or r["model_key"] or "unknown"
        bucket = models.setdefault(key, {"n": 0, "scores": [], "cost": 0.0, "latency": []})
        bucket["n"] += 1
        bucket["scores"].append(float(r["score"]))
        bucket["cost"] += float(r["cost"] or 0)
        bucket["latency"].append(float(r["latency_ms"] or 0))

    pairs = [p for p in store.calibration_pairs(rater=rater) if not str(p["turn_id"]).startswith("demo-")]
    human = [float(p["human"]) for p in pairs]
    judge = [float(p["judge"]) for p in pairs]
    human_metrics = calibration.compute_metrics(human, judge) if pairs else None

    feedback_counts = {int(r["rating"]): int(r["n"]) for r in feedback}
    return {
        "count": len(scores),
        "days": days,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "mean": round(statistics.mean(scores), 3),
        "median": round(statistics.median(scores), 3),
        "min": min(scores),
        "max": max(scores),
        "distribution": dist,
        "low_count": sum(1 for s in scores if s < 3),
        "low_rate": _rate(sum(1 for s in scores if s < 3), len(scores)),
        "signals_n": sum(1 for r in rows if r["model_id"]),
        "citation_rate": _rate(
            sum(1 for r in rows if r["model_id"] and int(r["citations"] or 0) > 0),
            max(1, sum(1 for r in rows if r["model_id"])),
        ),
        "no_answer_rate": _rate(
            sum(1 for r in rows if r["model_id"] and int(r["no_answer"] or 0)),
            max(1, sum(1 for r in rows if r["model_id"])),
        ),
        "tool_use_rate": _rate(
            sum(1 for r in rows if r["model_id"] and int(r["tools_count"] or 0) > 0),
            max(1, sum(1 for r in rows if r["model_id"])),
        ),
        "avg_tools": round(statistics.mean(float(r["tools_count"] or 0) for r in rows if r["model_id"]), 2)
        if any(r["model_id"] for r in rows)
        else 0.0,
        "total_cost": round(sum(float(r["cost"] or 0) for r in rows), 4),
        "avg_cost": round(statistics.mean(float(r["cost"] or 0) for r in rows if r["model_id"]), 4)
        if any(r["model_id"] for r in rows)
        else 0.0,
        "p50_latency_ms": round(_percentile([float(r["latency_ms"] or 0) for r in rows if r["model_id"]], 50)),
        "p95_latency_ms": round(_percentile([float(r["latency_ms"] or 0) for r in rows if r["model_id"]], 95)),
        "judges": dict(Counter(r["judge_model"] or "unknown" for r in rows)),
        "models": {
            k: {
                "n": v["n"],
                "mean": round(statistics.mean(v["scores"]), 3),
                "low_rate": _rate(sum(1 for s in v["scores"] if s < 3), v["n"]),
                "cost": round(v["cost"], 4),
                "p95_latency_ms": round(_percentile(v["latency"], 95)),
            }
            for k, v in sorted(models.items(), key=lambda item: -item[1]["n"])
        },
        "feedback": feedback_counts,
        "human": human_metrics,
        "human_labels": len(pairs),
        "min_human": min_human,
    }


def render(data: dict, rater: str) -> str:
    if not data.get("count"):
        return "# Chat Evaluation Results\n\nNo judged turns were found in the selected window.\n"

    min_human = int(data.get("min_human", 20))
    lines = [
        "# Chat Evaluation Results",
        "",
        f"Generated: {data['generated_at']}  ",
        f"Window: last {data['days']} days  ",
        f"Judged turns: {data['count']}  ",
        f"Judge model(s): {', '.join(f'{k} ({v})' for k, v in data['judges'].items())}",
        "",
        "This report is aggregate-only. It contains no questions, answers, user identifiers",
        "or tool payloads. The evaluation method is documented in [EVALUATION.md](EVALUATION.md).",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Mean judge score (1-5) | {data['mean']:.2f} |",
        f"| Median judge score | {data['median']:.2f} |",
        f"| Minimum / maximum | {data['min']:.2f} / {data['max']:.2f} |",
        f"| Low-score rate (<3) | {data['low_rate']:.1%} ({data['low_count']}/{data['count']}) |",
        f"| Instrumented turns (operational signals) | {data['signals_n']}/{data['count']} |",
        f"| Citation rate (instrumented) | {data['citation_rate']:.1%} |",
        f"| No-answer rate (instrumented) | {data['no_answer_rate']:.1%} |",
        f"| Tool-use rate (instrumented) | {data['tool_use_rate']:.1%} |",
        f"| Average tool calls (instrumented) | {data['avg_tools']:.2f} |",
        f"| Median / p95 latency (instrumented) | {data['p50_latency_ms']} / {data['p95_latency_ms']} ms |",
        f"| Average cost per instrumented turn | ${data['avg_cost']:.4f} |",
        f"| Total judged cost | ${data['total_cost']:.4f} |",
        "",
        "## Score distribution",
        "",
        "| Score | Turns | Share |",
        "|---:|---:|---:|",
    ]
    for score in range(1, 6):
        n = data["distribution"][score]
        lines.append(f"| {score} | {n} | {_rate(n, data['count']):.1%} |")

    lines += [
        "",
        "## Model breakdown",
        "",
        "| Model | Turns | Mean score | Low-score rate | p95 latency | Cost |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for model, m in data["models"].items():
        lines.append(
            f"| `{model}` | {m['n']} | {m['mean']:.2f} | {m['low_rate']:.1%} | "
            f"{m['p95_latency_ms']} ms | ${m['cost']:.4f} |"
        )

    lines += ["", "## User feedback", ""]
    up = data["feedback"].get(1, 0)
    down = data["feedback"].get(-1, 0)
    if up or down:
        lines.append(f"Recorded in the window: **{up} positive**, **{down} negative**.")
    else:
        lines.append("No user feedback was recorded in the window.")

    lines += ["", "## Human calibration", ""]
    if data["human"] and data["human_labels"] >= min_human:
        h = data["human"]
        lines += [
            f"Human labels: **{data['human_labels']}** (rater: `{rater}`).",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Quadratic weighted kappa (QWK) | {h['qwk']:.3f} |",
            f"| Spearman correlation | {h['spearman']:.3f} |",
            f"| MAE | {h['mae']:.2f} |",
            f"| Exact agreement | {h['exact_rate']:.1%} |",
            f"| Within-1 agreement | {h['within1_rate']:.1%} |",
            f"| Judge mean / human mean | {h['judge_mean']:.2f} / {h['human_mean']:.2f} |",
            "",
            f"Interpretation: {h['interpretation'].get('label', '')}.",
        ]
    else:
        have = data.get("human_labels", 0)
        lines += [
            f"Human calibration is pending: **{have}/{min_human}** required labels are available.",
            "Judge scores should not be presented as validated quality until at least 20-30",
            "answers are rated by a human reviewer.",
            "",
            "```bash",
            "python scripts/calibrate_judge.py --export 30 --out data/calibration/round1.csv",
            "python scripts/calibrate_judge.py --score data/calibration/round1.csv",
            "```",
        ]

    lines += [
        "",
        "## Limitations",
        "",
        "- This is a baseline, not a claim of general model quality.",
        "- Historical backfilled turns lack full telemetry; operational signals cover only instrumented turns.",
        "- Backfilled turns may lack tool evidence; the judge then scores internal consistency only.",
        "- Judge scores require human calibration before use as a quality gate.",
        "- Results are sensitive to model, prompt and judge versions; record them with every run.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate an aggregate evaluation report from obs.db")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--rater", default="human")
    ap.add_argument("--min-human", type=int, default=20, help="minimum labels before showing QWK")
    ap.add_argument("--out", default="docs/EVALUATION_RESULTS.md")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    data = collect(args.days, args.rater, min_human=args.min_human)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        report = render(data, args.rater)
        if args.out == "-":
            print(report)
        else:
            path = Path(args.out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(report, encoding="utf-8")
            print(f"wrote {path} ({data.get('count', 0)} judged turns)")
    return 0 if data.get("count") else 2


if __name__ == "__main__":
    raise SystemExit(main())
