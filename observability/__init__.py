"""observability — LLM / RAG telemetry and evaluation for Sightline.

Public surface:
    from observability import record_chat_turn, summary, timeseries, ...
    from observability import answer_signals

Read-only consumers (admin API, eval scripts) may import store query helpers
directly from ``observability.store``.
"""

from observability.metrics import answer_signals, citation_count, extract_citations, is_no_answer
from observability.store import (
    calibration_pairs,
    calibration_progress,
    calibration_queue,
    calibration_summary,
    daily_cost_summary,
    eval_recent,
    eval_retrieval_recent,
    eval_retrieval_summary,
    eval_summary,
    feedback_for_turns,
    feedback_summary,
    health,
    human_labeled_turn_ids,
    human_labels_for,
    init_obs_db,
    latest_eval_score,
    model_stats,
    prune,
    recent_turns,
    record_calibration_run,
    record_chat_turn,
    record_eval_score,
    record_feedback,
    record_human_label,
    record_retrieval_eval,
    summary,
    timeseries,
    tool_stats,
    turn_detail,
    turn_owner,
)

__all__ = [
    "answer_signals",
    "calibration_pairs",
    "calibration_progress",
    "calibration_queue",
    "calibration_summary",
    "daily_cost_summary",
    "citation_count",
    "eval_recent",
    "eval_retrieval_recent",
    "eval_retrieval_summary",
    "eval_summary",
    "extract_citations",
    "feedback_for_turns",
    "feedback_summary",
    "health",
    "human_labeled_turn_ids",
    "human_labels_for",
    "init_obs_db",
    "is_no_answer",
    "latest_eval_score",
    "model_stats",
    "prune",
    "recent_turns",
    "record_calibration_run",
    "record_chat_turn",
    "record_eval_score",
    "record_feedback",
    "record_human_label",
    "record_retrieval_eval",
    "summary",
    "timeseries",
    "tool_stats",
    "turn_detail",
    "turn_owner",
]
