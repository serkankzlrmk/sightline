"""blueprints/obs_bp.py — Admin observability API (/api/admin/obs/*).

Read-only telemetry queries over obs.db (see observability/store.py) plus a
manual retention-prune endpoint. All routes are admin-only.

The chat turn itself writes telemetry in blueprints/agent_bp.py; this blueprint
only serves aggregate/read models for the admin dashboard and the eval harness.
"""

import logging
import threading
import time
import uuid
from collections import Counter

from flask import Blueprint, jsonify, request

from auth import current_uid, require_admin
from blueprints.helpers import _log_audit
from observability import store
from observability.calibration import compute_metrics, confusion_matrix

logger = logging.getLogger(__name__)

obs_bp = Blueprint("obs", __name__, url_prefix="/api/admin/obs")

# Bounded, admin-triggered chat eval jobs (one at a time; synchronous judge calls
# run in a daemon thread so the request never blocks gunicorn for minutes).
_eval_lock = threading.Lock()
_eval_jobs: dict = {}


def _int_arg(name: str, default: int, minimum: int, maximum: int) -> int:
    """Parse a clamped integer query/body arg without raising on garbage."""
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


@obs_bp.route("/health", methods=["GET"])
@require_admin
def api_obs_health():
    """Telemetry DB + MCP readiness snapshot."""
    try:
        return jsonify(store.health())
    except Exception as exc:
        logger.error("obs health failed: %s", exc, exc_info=True)
        return jsonify({"error": "Observability store unavailable"}), 500


@obs_bp.route("/summary", methods=["GET"])
@require_admin
def api_obs_summary():
    """Headline KPIs for the admin dashboard (default: last 7 days)."""
    try:
        return jsonify(store.summary(days=_int_arg("days", 7, 1, 365)))
    except Exception as exc:
        logger.error("obs summary failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to compute summary"}), 500


@obs_bp.route("/timeseries", methods=["GET"])
@require_admin
def api_obs_timeseries():
    """Per-day turns, errors, latency percentiles and cost."""
    try:
        return jsonify({"series": store.timeseries(days=_int_arg("days", 14, 1, 365))})
    except Exception as exc:
        logger.error("obs timeseries failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to compute timeseries"}), 500


@obs_bp.route("/tools", methods=["GET"])
@require_admin
def api_obs_tools():
    """Per-tool usage/error/latency table (MCP server kept separate)."""
    try:
        return jsonify({"tools": store.tool_stats(days=_int_arg("days", 7, 1, 365))})
    except Exception as exc:
        logger.error("obs tools failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to compute tool stats"}), 500


@obs_bp.route("/models", methods=["GET"])
@require_admin
def api_obs_models():
    """Per-model volume/latency/cost/citation comparison."""
    try:
        return jsonify({"models": store.model_stats(days=_int_arg("days", 7, 1, 365))})
    except Exception as exc:
        logger.error("obs models failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to compute model stats"}), 500


@obs_bp.route("/turns", methods=["GET"])
@require_admin
def api_obs_turns():
    """Recent turns, newest first. Filters: status, uid, limit."""
    try:
        status = (request.args.get("status") or "").strip()
        if status not in ("", "ok", "error", "empty", "cancelled"):
            return jsonify({"error": "Invalid status filter"}), 400
        uid = (request.args.get("uid") or "").strip()[:128]
        turns = store.recent_turns(limit=_int_arg("limit", 50, 1, 200), status=status, uid=uid)
        return jsonify({"turns": turns})
    except Exception as exc:
        logger.error("obs turns failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to list turns"}), 500


@obs_bp.route("/turn/<turn_id>", methods=["GET"])
@require_admin
def api_obs_turn_detail(turn_id):
    """One turn plus its tool-call trace (drill-down)."""
    try:
        detail = store.turn_detail(turn_id)
        if detail is None:
            return jsonify({"error": "Turn not found"}), 404
        return jsonify(detail)
    except Exception as exc:
        logger.error("obs turn detail failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load turn"}), 500


@obs_bp.route("/feedback", methods=["GET"])
@require_admin
def api_obs_feedback():
    """👍/👎 rollup for the selected window."""
    try:
        return jsonify(store.feedback_summary(days=_int_arg("days", 7, 1, 365)))
    except Exception as exc:
        logger.error("obs feedback failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to compute feedback"}), 500


@obs_bp.route("/eval", methods=["GET"])
@require_admin
def api_obs_eval():
    """Offline judge verdicts: aggregate summary + recent verdict list.

    Optional filters: ?days= (window), ?limit= (recent list clamp), ?low=1
    (list only sub-3 scores for the review queue).
    """
    try:
        days = _int_arg("days", 30, 1, 365)
        return jsonify(
            {
                "summary": store.eval_summary(days=days),
                "recent": store.eval_recent(
                    days=days,
                    limit=_int_arg("limit", 50, 1, 200),
                    low_only=(request.args.get("low") in ("1", "true")),
                ),
                "retrieval": store.eval_retrieval_summary(days=max(days, 90)),
                "feedback": store.feedback_summary(days=days),
            }
        )
    except Exception as exc:
        logger.error("obs eval failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to compute eval scores"}), 500


def _clamp_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def _run_eval_job(job_id: str, params: dict) -> None:
    """Execute one bounded chat-eval batch in the background."""
    try:
        from scripts.eval_agent import run as run_eval

        report = run_eval(
            days=params["days"],
            limit=params["sample"],
            apply=params["apply"],
            judge_model=params["judge_model"],
            samples=params["samples"],
            use_evidence=params["use_evidence"],
        )
        with _eval_lock:
            _eval_jobs[job_id].update(status="done", report=report, finished_at=time.time())
    except Exception as exc:
        logger.error("obs eval run failed: %s", exc, exc_info=True)
        with _eval_lock:
            _eval_jobs[job_id].update(status="error", error=str(exc)[:500], finished_at=time.time())


@obs_bp.route("/eval/run", methods=["POST"])
@require_admin
def api_obs_eval_run():
    """Start a bounded offline chat-eval batch (default: 10 turns, 3 judge samples).

    Body: {"sample": 10, "samples": 3, "days": 30, "apply": true,
           "judge_model": "openai/gpt-5.1", "use_evidence": true}
    """
    data = request.get_json(silent=True) or {}
    params = {
        "sample": _clamp_int(data.get("sample"), 10, 1, 25),
        "samples": _clamp_int(data.get("samples"), 3, 1, 3),
        "days": _clamp_int(data.get("days"), 30, 1, 90),
        "apply": bool(data.get("apply", True)),
        "judge_model": str(data.get("judge_model") or "")[:80] or None,
        "use_evidence": bool(data.get("use_evidence", True)),
    }
    with _eval_lock:
        running = next((j for j in _eval_jobs.values() if j["status"] == "running"), None)
        if running:
            return jsonify({"error": "An eval run is already in progress", "job_id": running["job_id"]}), 409
        job_id = uuid.uuid4().hex[:12]
        _eval_jobs[job_id] = {
            "job_id": job_id,
            "status": "running",
            "started_at": time.time(),
            "finished_at": None,
            "params": params,
            "report": None,
            "error": None,
        }
    _log_audit(current_uid() or "admin", "eval_run_started", job_id, {"sample": params["sample"]})
    threading.Thread(target=_run_eval_job, args=(job_id, params), daemon=True).start()
    return jsonify({"job_id": job_id, "status": "running", "params": params}), 202


@obs_bp.route("/eval/run/status/<job_id>", methods=["GET"])
@require_admin
def api_obs_eval_run_status(job_id):
    """Poll one background eval job."""
    with _eval_lock:
        job = _eval_jobs.get(str(job_id))
    if job is None:
        return jsonify({"error": "Eval job not found"}), 404
    return jsonify(job)


@obs_bp.route("/eval/retrieval", methods=["GET"])
@require_admin
def api_obs_eval_retrieval():
    """Latest golden-set retrieval metrics + recent runs."""
    try:
        return jsonify(store.eval_retrieval_summary(days=_int_arg("days", 90, 1, 365)))
    except Exception as exc:
        logger.error("obs eval retrieval failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load retrieval eval"}), 500


@obs_bp.route("/calibration", methods=["GET"])
@require_admin
def api_obs_calibration():
    """Latest judge-human calibration (QWK) + human label counts for this admin."""
    try:
        rater = current_uid() or "admin"
        summary = store.calibration_summary(days=_int_arg("days", 3650, 1, 3650))
        summary["rater"] = rater
        summary["progress"] = store.calibration_progress(days=_int_arg("days", 3650, 1, 3650), rater=rater)
        return jsonify(summary)
    except Exception as exc:
        logger.error("obs calibration failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load calibration"}), 500


@obs_bp.route("/calibration/queue", methods=["GET"])
@require_admin
def api_obs_calibration_queue():
    """Next judged-but-unlabeled turns for this admin — BLIND (no judge score)."""
    try:
        from scripts.eval_agent import _pair_with_messages, _tool_evidence

        rater = current_uid() or "admin"
        days = _int_arg("days", 3650, 1, 3650)
        limit = _int_arg("limit", 10, 1, 30)
        queue = []
        for item in store.calibration_queue(days=days, rater=rater, limit=limit):
            turn = store.turn_owner(item["turn_id"])
            if not turn:
                continue
            pair = _pair_with_messages({"chat_id": turn["chat_id"], "finished_at": turn["finished_at"]})
            if not pair:
                continue
            queue.append(
                {
                    "turn_id": item["turn_id"],
                    "question": pair["question"],
                    "answer": pair["answer"],
                    "evidence": _tool_evidence(item["turn_id"], max_chars=2000),
                    "model_id": turn.get("model_id") or "",
                    "judged_at": item["created_at"],
                }
            )
        return jsonify(
            {
                "rater": rater,
                "queue": queue,
                "progress": store.calibration_progress(days=days, rater=rater),
            }
        )
    except Exception as exc:
        logger.error("obs calibration queue failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load calibration queue"}), 500


@obs_bp.route("/calibration/label", methods=["POST"])
@require_admin
def api_obs_calibration_label():
    """Save one human rating; reveal the judge score only after the rating is saved."""
    data = request.get_json(silent=True) or {}
    turn_id = str(data.get("turn_id") or "").strip()[:64]
    try:
        score = float(data.get("score"))
    except (TypeError, ValueError):
        return jsonify({"error": "score must be 1-5"}), 400
    if not turn_id or score < 1 or score > 5:
        return jsonify({"error": "turn_id and score (1-5) are required"}), 400
    latest = store.latest_eval_score(turn_id)
    if latest is None:
        return jsonify({"error": "Turn has no judge score — run evaluation first"}), 404
    rater = current_uid() or "admin"
    stored = store.record_human_label(
        turn_id=turn_id,
        score=score,
        rater=rater,
        notes=str(data.get("notes") or "")[:500],
        rubric_version=str(data.get("rubric_version") or "v1")[:20],
    )
    if not stored:
        return jsonify({"error": "Human label could not be saved"}), 500
    _log_audit(rater, "human_labeled", turn_id, {"score": score})
    return jsonify(
        {
            "ok": True,
            "turn_id": turn_id,
            "human_score": score,
            "judge_score": float(latest["score"]),
            "judge_model": latest["judge_model"],
            "diff": round(float(latest["score"]) - score, 2),
            "progress": store.calibration_progress(rater=rater),
        }
    )


@obs_bp.route("/calibration/score", methods=["POST"])
@require_admin
def api_obs_calibration_score():
    """Compute QWK/Spearman/MAE from this admin's saved human labels and persist it."""
    try:
        rater = current_uid() or "admin"
        pairs = store.calibration_pairs(rater=rater)
        if len(pairs) < 2:
            return jsonify({"error": "Need at least 2 human-labeled turns with judge scores"}), 400
        human = [float(p["human"]) for p in pairs]
        judge = [float(p["judge"]) for p in pairs]
        metrics = compute_metrics(human, judge)
        matrix = confusion_matrix(human, judge)
        disagreements = sorted(
            (
                {
                    "turn_id": p["turn_id"],
                    "human": p["human"],
                    "judge": p["judge"],
                    "diff": round(float(p["judge"]) - float(p["human"]), 2),
                    "judge_model": p["judge_model"],
                }
                for p in pairs
                if round(float(p["judge"])) != round(float(p["human"]))
            ),
            key=lambda d: -abs(d["diff"]),
        )[:10]
        judge_model = Counter(p["judge_model"] for p in pairs).most_common(1)[0][0]
        _log_audit(rater, "calibration_scored", judge_model, {"n": len(pairs), "qwk": metrics["qwk"]})
        store.record_calibration_run(
            judge_model=judge_model,
            samples=0,
            n=len(pairs),
            metrics=metrics,
            detail={
                "rater": rater,
                "confusion_rows_human_cols_judge": matrix,
                "disagreements": disagreements,
            },
        )
        return jsonify(
            {
                "rater": rater,
                "judge_model": judge_model,
                "metrics": metrics,
                "confusion": {"rows": "human 1-5", "cols": "judge 1-5", "matrix": matrix},
                "top_disagreements": disagreements,
            }
        )
    except Exception as exc:
        logger.error("obs calibration score failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to compute calibration"}), 500


@obs_bp.route("/retrieval/queue", methods=["GET"])
@require_admin
def api_obs_retrieval_queue():
    """Next unlabeled retrieval query with its candidate reports."""
    try:
        query = store.retrieval_next_query()
        return jsonify({"query": query, "progress": store.retrieval_progress()})
    except Exception as exc:
        logger.error("obs retrieval queue failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load retrieval queue"}), 500


@obs_bp.route("/retrieval/label", methods=["POST"])
@require_admin
def api_obs_retrieval_label():
    """Save relevance labels for one retrieval query (1 for supplied ids, 0 for rest)."""
    data = request.get_json(silent=True) or {}
    query_id = str(data.get("query_id") or "")[:120]
    relevant = data.get("relevant") or []
    if not query_id or not isinstance(relevant, list):
        return jsonify({"error": "query_id and relevant[] are required"}), 400
    relevant = [str(x)[:80] for x in relevant[:200]]
    try:
        saved = store.save_retrieval_labels(query_id, relevant, rater=current_uid() or "admin")
        if not saved:
            return jsonify({"error": "Query not found"}), 404
        _log_audit(current_uid() or "admin", "retrieval_labeled", query_id, {"relevant": len(relevant)})
        return jsonify(
            {"ok": True, "query_id": query_id, "relevant": len(relevant), "progress": store.retrieval_progress()}
        )
    except Exception as exc:
        logger.error("obs retrieval label failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to save retrieval labels"}), 500


@obs_bp.route("/retrieval/export", methods=["GET"])
@require_admin
def api_obs_retrieval_export():
    """Export the labeled golden set in the format consumed by eval_retrieval.py."""
    try:
        golden = store.retrieval_golden_set()
        return jsonify({"golden_set": golden, "progress": store.retrieval_progress()})
    except Exception as exc:
        logger.error("obs retrieval export failed: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to export golden set"}), 500


@obs_bp.route("/prune", methods=["POST"])
@require_admin
def api_obs_prune():
    """Manually prune telemetry older than retention (or ?days=)."""
    try:
        days = _int_arg("days", 0, 0, 3650)
        deleted = store.prune(days=days or None)
        _log_audit(current_uid() or "admin", "telemetry_pruned", "obs.db", {"deleted": deleted})
        return jsonify({"ok": True, "deleted": deleted})
    except Exception as exc:
        logger.error("obs prune failed: %s", exc, exc_info=True)
        return jsonify({"error": "Prune failed"}), 500
