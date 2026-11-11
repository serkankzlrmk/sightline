"""observability/store.py — SQLite telemetry store for chat turns.

Design constraints (deliberate):

- **Best-effort**: callers wrap writes in try/except; telemetry must never break
  a chat turn. Every public write returns a bool instead of raising.
- **Separate DB** (`OBS_DB_PATH`, default ``obs.db`` next to ``chats.db``) so
  admin dashboard scans and retention pruning never contend with the chats.db
  write path (single gunicorn worker, WAL).
- **One write per turn**: tool/LLM events are accumulated in memory during the
  SSE stream and persisted in a single short transaction when the turn ends.
- **No answer text**: only lengths + deterministic signals are stored. Full
  answers stay in ``chat_messages`` (the source of truth) for drill-down.

Schema:
    turns       one row per chat turn (status ok/error/empty)
    tool_calls  one row per tool invocation in that turn
    feedback    👍/👎 ratings (Phase 4; table created now)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from observability.metrics import answer_signals

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    turn_id      TEXT PRIMARY KEY,
    uid          TEXT NOT NULL DEFAULT '',
    chat_id      TEXT NOT NULL DEFAULT '',
    model_key    TEXT NOT NULL DEFAULT '',
    model_id     TEXT NOT NULL DEFAULT '',
    mode         TEXT NOT NULL DEFAULT 'analyst',
    started_at   REAL NOT NULL,
    finished_at  REAL NOT NULL DEFAULT 0,
    latency_ms   INTEGER NOT NULL DEFAULT 0,
    total_ms     INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'ok',
    error        TEXT NOT NULL DEFAULT '',
    iterations   INTEGER NOT NULL DEFAULT 0,
    tokens_in    INTEGER NOT NULL DEFAULT 0,
    tokens_out   INTEGER NOT NULL DEFAULT 0,
    cost         REAL NOT NULL DEFAULT 0,
    tools_count  INTEGER NOT NULL DEFAULT 0,
    tool_errors  INTEGER NOT NULL DEFAULT 0,
    groups_json  TEXT NOT NULL DEFAULT '{}',
    citations    INTEGER NOT NULL DEFAULT 0,
    answer_chars INTEGER NOT NULL DEFAULT 0,
    no_answer    INTEGER NOT NULL DEFAULT 0,
    meta_json    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_obs_turns_started ON turns(started_at);
CREATE INDEX IF NOT EXISTS idx_obs_turns_uid ON turns(uid, started_at);
CREATE INDEX IF NOT EXISTS idx_obs_turns_status ON turns(status, started_at);

CREATE TABLE IF NOT EXISTS tool_calls (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id      TEXT NOT NULL,
    seq          INTEGER NOT NULL DEFAULT 0,
    tool         TEXT NOT NULL DEFAULT '',
    group_name   TEXT NOT NULL DEFAULT '',
    server       TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'ok',
    error_class  TEXT NOT NULL DEFAULT '',
    duration_ms  INTEGER NOT NULL DEFAULT 0,
    result_chars INTEGER NOT NULL DEFAULT 0,
    result_preview TEXT NOT NULL DEFAULT '',
    summary      TEXT NOT NULL DEFAULT '',
    created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_tools_turn ON tool_calls(turn_id);
CREATE INDEX IF NOT EXISTS idx_obs_tools_tool ON tool_calls(tool, created_at);
CREATE INDEX IF NOT EXISTS idx_obs_tools_created ON tool_calls(created_at);

CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER,
    turn_id    TEXT NOT NULL DEFAULT '',
    uid        TEXT NOT NULL DEFAULT '',
    rating     INTEGER NOT NULL,
    comment    TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_feedback_created ON feedback(created_at);
CREATE INDEX IF NOT EXISTS idx_obs_feedback_turn ON feedback(turn_id);

CREATE TABLE IF NOT EXISTS eval_scores (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id     TEXT NOT NULL DEFAULT '',
    chat_id     TEXT NOT NULL DEFAULT '',
    judge_model TEXT NOT NULL DEFAULT '',
    judge       TEXT NOT NULL DEFAULT 'offline',
    score       REAL NOT NULL,
    issues_json TEXT NOT NULL DEFAULT '[]',
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_eval_created ON eval_scores(created_at);
CREATE INDEX IF NOT EXISTS idx_obs_eval_turn ON eval_scores(turn_id);

CREATE TABLE IF NOT EXISTS eval_retrieval (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    gold_path   TEXT NOT NULL DEFAULT '',
    k           INTEGER NOT NULL DEFAULT 10,
    stage1_k    INTEGER NOT NULL DEFAULT 50,
    queries     INTEGER NOT NULL DEFAULT 0,
    mean_recall REAL NOT NULL DEFAULT 0,
    mean_recall_stage1 REAL NOT NULL DEFAULT 0,
    mean_mrr    REAL NOT NULL DEFAULT 0,
    mean_ndcg   REAL NOT NULL DEFAULT 0,
    judge       TEXT NOT NULL DEFAULT 'ir',
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_evalret_created ON eval_retrieval(created_at);

CREATE TABLE IF NOT EXISTS human_labels (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id        TEXT NOT NULL DEFAULT '',
    rater          TEXT NOT NULL DEFAULT 'human',
    score          REAL NOT NULL,
    notes          TEXT NOT NULL DEFAULT '',
    rubric_version TEXT NOT NULL DEFAULT 'v1',
    created_at     REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_obs_human_unique ON human_labels(turn_id, rater);

CREATE TABLE IF NOT EXISTS calibration_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    judge_model  TEXT NOT NULL DEFAULT '',
    samples      INTEGER NOT NULL DEFAULT 0,
    n            INTEGER NOT NULL DEFAULT 0,
    qwk          REAL NOT NULL DEFAULT 0,
    spearman     REAL NOT NULL DEFAULT 0,
    pearson      REAL NOT NULL DEFAULT 0,
    mae          REAL NOT NULL DEFAULT 0,
    exact_rate   REAL NOT NULL DEFAULT 0,
    within1_rate REAL NOT NULL DEFAULT 0,
    detail_json  TEXT NOT NULL DEFAULT '{}',
    created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_calib_created ON calibration_runs(created_at);

CREATE TABLE IF NOT EXISTS retrieval_candidates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id    TEXT NOT NULL,
    query       TEXT NOT NULL DEFAULT '',
    country     TEXT NOT NULL DEFAULT '',
    report_id   TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    date        TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    relevant    INTEGER,
    labeled_at  REAL,
    labeled_by  TEXT NOT NULL DEFAULT '',
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL,
    UNIQUE(query_id, report_id)
);
CREATE INDEX IF NOT EXISTS idx_obs_retcand_query ON retrieval_candidates(query_id, position);
CREATE INDEX IF NOT EXISTS idx_obs_retcand_label ON retrieval_candidates(relevant);
"""

_init_lock = threading.Lock()
_initialized: set[str] = set()


# ── Connection / schema ──────────────────────────────────────────────────────


def db_path() -> Path:
    """Resolve the current OBS_DB_PATH (read dynamically so tests can patch it)."""
    import config

    return Path(config.OBS_DB_PATH)


def _enabled() -> bool:
    import config

    return bool(getattr(config, "OBS_ENABLED", True))


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=5.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Apply additive migrations to an existing obs.db (idempotent).

    - tool_calls.result_preview (chat eval needs tool evidence, not just summaries)
    - eval_scores uniqueness + de-duplication (re-running --apply must not double-count)
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(tool_calls)").fetchall()}
    if "result_preview" not in cols:
        conn.execute("ALTER TABLE tool_calls ADD COLUMN result_preview TEXT NOT NULL DEFAULT ''")
    if "error_class" not in cols:
        conn.execute("ALTER TABLE tool_calls ADD COLUMN error_class TEXT NOT NULL DEFAULT ''")

    # Keep only the newest verdict per (turn, judge_model, judge) before the index.
    conn.execute(
        """
        DELETE FROM eval_scores
        WHERE id NOT IN (
            SELECT MAX(id) FROM eval_scores GROUP BY turn_id, judge_model, judge
        )
        """
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_obs_eval_unique ON eval_scores(turn_id, judge_model, judge)")

    # Feedback is one vote per (turn, user): clicking 👍 then 👎 updates the vote.
    conn.execute(
        """
        DELETE FROM feedback
        WHERE id NOT IN (SELECT MAX(id) FROM feedback GROUP BY turn_id, uid)
        """
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_obs_feedback_unique ON feedback(turn_id, uid)")
    conn.commit()


def _ensure_schema() -> None:
    """Internal: create tables/indexes once per path. Safe from any thread."""
    path = db_path()
    key = str(path)
    with _init_lock:
        if key in _initialized:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(_connect(path)) as conn:
            conn.executescript(_SCHEMA)
            _migrate_schema(conn)
            conn.commit()
        _initialized.add(key)


def init_obs_db(force: bool = False) -> None:
    """Public: ensure schema then opportunistically prune expired rows."""
    if force:
        reset_for_tests()
    _ensure_schema()
    prune()


def reset_for_tests() -> None:
    """Forget the init cache (tests switch OBS_DB_PATH between cases)."""
    with _init_lock:
        _initialized.clear()


def get_obs_db() -> sqlite3.Connection:
    """Open a connection (schema ensured). Caller closes it."""
    _ensure_schema()
    return _connect(db_path())


# ── Writes ───────────────────────────────────────────────────────────────────


def record_chat_turn(turn: dict, tools: list[dict] | None = None) -> bool:
    """Persist one chat turn (+ its tool calls) in a single transaction.

    ``turn`` keys (all optional except turn_id/started_at):
        turn_id, uid, chat_id, model_key, model_id, mode, started_at, finished_at,
        latency_ms, total_ms, status, error, iterations, tokens_in, tokens_out,
        cost, groups (dict), citations, answer_chars, no_answer, meta (dict)
        answer (str, optional — used to derive signals, never stored)
    """
    if not _enabled():
        return False
    try:
        turn_id = str(turn.get("turn_id") or "")
        if not turn_id:
            return False

        signals = {}
        if turn.get("answer") is not None and "citations" not in turn:
            signals = answer_signals(turn.get("answer") or "")
        citations = int(turn.get("citations", signals.get("citations", 0)) or 0)
        answer_chars = int(turn.get("answer_chars", signals.get("answer_chars", 0)) or 0)
        no_answer = int(bool(turn.get("no_answer", signals.get("no_answer", False))))

        tool_rows = list(tools or turn.get("tools") or [])
        groups = turn.get("groups") or {}
        started_at = float(turn.get("started_at") or time.time())
        params = (
            turn_id,
            str(turn.get("uid") or ""),
            str(turn.get("chat_id") or ""),
            str(turn.get("model_key") or ""),
            str(turn.get("model_id") or ""),
            str(turn.get("mode") or "analyst"),
            started_at,
            float(turn.get("finished_at") or time.time()),
            int(turn.get("latency_ms") or 0),
            int(turn.get("total_ms") or 0),
            str(turn.get("status") or "ok"),
            str(turn.get("error") or "")[:1000],
            int(turn.get("iterations") or 0),
            int(turn.get("tokens_in") or 0),
            int(turn.get("tokens_out") or 0),
            float(turn.get("cost") or 0.0),
            len(tool_rows),
            sum(1 for t in tool_rows if t.get("status") == "error"),
            json.dumps(groups, default=str),
            citations,
            answer_chars,
            no_answer,
            json.dumps(turn.get("meta") or {}, default=str),
        )

        _ensure_schema()
        with closing(_connect(db_path())) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO turns (
                    turn_id, uid, chat_id, model_key, model_id, mode,
                    started_at, finished_at, latency_ms, total_ms, status, error,
                    iterations, tokens_in, tokens_out, cost, tools_count,
                    tool_errors, groups_json, citations, answer_chars, no_answer,
                    meta_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                params,
            )
            if tool_rows:
                conn.execute("DELETE FROM tool_calls WHERE turn_id = ?", (turn_id,))
                conn.executemany(
                    """
                    INSERT INTO tool_calls
                        (turn_id, seq, tool, group_name, server, status, error_class,
                         duration_ms, result_chars, result_preview, summary, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    [
                        (
                            turn_id,
                            i,
                            str(t.get("tool") or ""),
                            str(t.get("group") or ""),
                            str(t.get("server") or ""),
                            str(t.get("status") or "ok"),
                            str(t.get("error_class") or ""),
                            int(t.get("duration_ms") or 0),
                            int(t.get("result_chars") or 0),
                            str(t.get("result_preview") or "")[:1200],
                            str(t.get("summary") or "")[:200],
                            started_at,
                        )
                        for i, t in enumerate(tool_rows)
                    ],
                )
            conn.commit()
        return True
    except Exception as exc:  # never break a chat turn
        logger.debug("obs: record_chat_turn failed (non-fatal): %s", exc)
        return False


def record_feedback(
    rating: int,
    uid: str = "",
    turn_id: str = "",
    message_id: int | None = None,
    comment: str = "",
) -> bool:
    """Store a user rating (+1/-1) for an assistant answer."""
    if not _enabled():
        return False
    try:
        rating = 1 if int(rating) > 0 else -1
    except (TypeError, ValueError):
        return False
    try:
        _ensure_schema()
        with closing(_connect(db_path())) as conn:
            if turn_id:
                # One vote per (turn_id, uid); changing 👍/👎 updates it.
                conn.execute(
                    """
                    INSERT INTO feedback (message_id, turn_id, uid, rating, comment, created_at)
                    VALUES (?,?,?,?,?,?)
                    ON CONFLICT(turn_id, uid) DO UPDATE SET
                        message_id = excluded.message_id,
                        rating = excluded.rating,
                        comment = excluded.comment,
                        created_at = excluded.created_at
                    """,
                    (message_id, str(turn_id), str(uid or ""), rating, str(comment or "")[:1000], time.time()),
                )
            else:
                conn.execute(
                    "INSERT INTO feedback (message_id, turn_id, uid, rating, comment, created_at) VALUES (?,?,?,?,?,?)",
                    (message_id, "", str(uid or ""), rating, str(comment or "")[:1000], time.time()),
                )
            conn.commit()
        return True
    except Exception as exc:
        logger.debug("obs: record_feedback failed (non-fatal): %s", exc)
        return False


def feedback_for_turns(uid: str, turn_ids: list[str]) -> dict:
    """Return {turn_id: {rating, comment}} for one user's feedback on turns."""
    ids = [str(t) for t in (turn_ids or []) if t]
    if not ids:
        return {}
    _ensure_schema()
    placeholders = ",".join("?" * len(ids))
    with closing(_connect(db_path())) as conn:
        rows = conn.execute(
            f"SELECT turn_id, rating, comment, created_at FROM feedback WHERE uid = ? AND turn_id IN ({placeholders})",
            (str(uid or ""), *ids),
        ).fetchall()
    return {
        r["turn_id"]: {
            "rating": int(r["rating"]),
            "comment": r["comment"],
            "created_at": float(r["created_at"]),
        }
        for r in rows
    }


def turn_owner(turn_id: str) -> dict | None:
    """Owner/chat lookup for a turn (feedback authorization + UI context)."""
    if not turn_id:
        return None
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        row = conn.execute(
            "SELECT turn_id, uid, chat_id, status, model_key, model_id, started_at, finished_at "
            "FROM turns WHERE turn_id = ?",
            (str(turn_id),),
        ).fetchone()
    return dict(row) if row else None


def record_eval_score(
    turn_id: str,
    score: float,
    judge_model: str = "",
    chat_id: str = "",
    judge: str = "offline",
    issues: list | None = None,
) -> bool:
    """Persist one offline judge verdict for a turn (deliberate CLI action).

    Unlike the hot-path writers this is NOT gated on OBS_ENABLED: the eval
    harness is an explicit admin action and its scores are the primary output.
    """
    if not turn_id:
        return False
    try:
        score = max(1.0, min(5.0, float(score)))
    except (TypeError, ValueError):
        return False
    try:
        _ensure_schema()
        with closing(_connect(db_path())) as conn:
            conn.execute(
                """
                INSERT INTO eval_scores
                    (turn_id, chat_id, judge_model, judge, score, issues_json, created_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(turn_id, judge_model, judge) DO UPDATE SET
                    chat_id = excluded.chat_id,
                    score = excluded.score,
                    issues_json = excluded.issues_json,
                    created_at = excluded.created_at
                """,
                (
                    str(turn_id),
                    str(chat_id or ""),
                    str(judge_model or ""),
                    str(judge or "offline"),
                    score,
                    json.dumps(issues or [], default=str),
                    time.time(),
                ),
            )
            conn.commit()
        return True
    except Exception as exc:
        logger.debug("obs: record_eval_score failed (non-fatal): %s", exc)
        return False


def eval_summary(days: int = 30) -> dict:
    """Aggregate offline judge verdicts for the last N days."""
    days = max(1, min(int(days or 30), 365))
    cutoff = _cutoff(days)
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        rows = conn.execute(
            "SELECT score, turn_id FROM eval_scores WHERE created_at >= ? ORDER BY created_at",
            (cutoff,),
        ).fetchall()
    scores = [float(r["score"]) for r in rows]
    if not scores:
        return {"range_days": days, "count": 0}
    dist = {n: 0 for n in range(1, 6)}
    for s in scores:
        dist[min(5, max(1, int(round(s))))] += 1
    return {
        "range_days": days,
        "count": len(scores),
        "avg": round(sum(scores) / len(scores), 3),
        "min": min(scores),
        "low_count": sum(1 for s in scores if s < 3),
        "low_rate": _rate(sum(1 for s in scores if s < 3), len(scores)),
        "distribution": dist,
    }


def eval_recent(days: int = 30, limit: int = 50, low_only: bool = False) -> list[dict]:
    """Recent offline judge verdicts, newest first (admin drill-down list)."""
    days = max(1, min(int(days or 30), 365))
    limit = max(1, min(int(limit or 50), 200))
    cutoff = _cutoff(days)
    where = "created_at >= ?" + (" AND score < 3" if low_only else "")
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        rows = conn.execute(
            f"""
            SELECT turn_id, chat_id, judge_model, judge, score, issues_json, created_at
            FROM eval_scores WHERE {where}
            ORDER BY created_at DESC LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
    out = []
    for r in rows:
        try:
            issues = json.loads(r["issues_json"])
        except (json.JSONDecodeError, TypeError):
            issues = []
        out.append(
            {
                "turn_id": r["turn_id"],
                "chat_id": r["chat_id"],
                "judge_model": r["judge_model"],
                "judge": r["judge"],
                "score": float(r["score"]),
                "issues": issues,
                "created_at": float(r["created_at"]),
            }
        )
    return out


def record_retrieval_eval(
    gold_path: str,
    k: int,
    result: dict,
    stage1_k: int = 50,
    judge: str = "ir",
) -> bool:
    """Persist one golden-set retrieval evaluation run (Recall/nDCG/MRR).

    ``result`` is the dict returned by ``scripts/eval_retrieval.run``:
    ``{"k": 10, "per_query": [...], "aggregate": {...}}``.
    """
    if not isinstance(result, dict):
        return False
    agg = result.get("aggregate") or {}
    per_query = [
        {key: q.get(key) for key in ("query", "recall_at_k", "recall_at_k_stage1", "mrr", "ndcg_at_k")}
        for q in (result.get("per_query") or [])
    ]
    try:
        _ensure_schema()
        with closing(_connect(db_path())) as conn:
            conn.execute(
                """
                INSERT INTO eval_retrieval
                    (gold_path, k, stage1_k, queries, mean_recall, mean_recall_stage1,
                     mean_mrr, mean_ndcg, judge, detail_json, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(gold_path or ""),
                    int(k or 10),
                    int(stage1_k or 50),
                    int(agg.get("queries") or len(per_query)),
                    float(agg.get("mean_recall_at_k") or 0.0),
                    float(agg.get("mean_recall_at_stage1") or 0.0),
                    float(agg.get("mean_mrr") or 0.0),
                    float(agg.get("mean_ndcg_at_k") or 0.0),
                    str(judge or "ir"),
                    json.dumps({"aggregate": agg, "per_query": per_query}, default=str),
                    time.time(),
                ),
            )
            conn.commit()
        return True
    except Exception as exc:
        logger.debug("obs: record_retrieval_eval failed (non-fatal): %s", exc)
        return False


def eval_retrieval_recent(days: int = 90, limit: int = 20) -> list[dict]:
    """Recent golden-set retrieval runs, newest first (without per-query detail)."""
    days = max(1, min(int(days or 90), 365))
    limit = max(1, min(int(limit or 20), 100))
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        rows = conn.execute(
            """
            SELECT id, gold_path, k, stage1_k, queries, mean_recall,
                   mean_recall_stage1, mean_mrr, mean_ndcg, judge, created_at
            FROM eval_retrieval WHERE created_at >= ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (_cutoff(days), limit),
        ).fetchall()
    return [dict(r) for r in rows]


def eval_retrieval_summary(days: int = 90) -> dict:
    """Latest retrieval run + recent-run trend for the admin dashboard."""
    runs = eval_retrieval_recent(days=days, limit=20)
    return {"latest": runs[0] if runs else None, "runs": runs}


def record_human_label(
    turn_id: str,
    score: float,
    rater: str = "human",
    notes: str = "",
    rubric_version: str = "v1",
) -> bool:
    """Save/update one human rating (1–5) for a turn (deliberate calibration action)."""
    if not turn_id:
        return False
    try:
        score = max(1.0, min(5.0, float(score)))
    except (TypeError, ValueError):
        return False
    try:
        _ensure_schema()
        with closing(_connect(db_path())) as conn:
            conn.execute(
                """
                INSERT INTO human_labels (turn_id, rater, score, notes, rubric_version, created_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(turn_id, rater) DO UPDATE SET
                    score = excluded.score,
                    notes = excluded.notes,
                    rubric_version = excluded.rubric_version,
                    created_at = excluded.created_at
                """,
                (
                    str(turn_id),
                    str(rater or "human"),
                    score,
                    str(notes or "")[:1000],
                    str(rubric_version or "v1"),
                    time.time(),
                ),
            )
            conn.commit()
        return True
    except Exception as exc:
        logger.debug("obs: record_human_label failed (non-fatal): %s", exc)
        return False


def human_labels_for(turn_ids: list[str], rater: str = "human") -> dict:
    """Return {turn_id: {score, notes, rubric_version}} for the requested turns."""
    ids = [str(t) for t in (turn_ids or []) if t]
    if not ids:
        return {}
    _ensure_schema()
    placeholders = ",".join("?" * len(ids))
    with closing(_connect(db_path())) as conn:
        rows = conn.execute(
            f"SELECT turn_id, score, notes, rubric_version, created_at "
            f"FROM human_labels WHERE rater = ? AND turn_id IN ({placeholders})",
            (str(rater or "human"), *ids),
        ).fetchall()
    return {
        r["turn_id"]: {
            "score": float(r["score"]),
            "notes": r["notes"],
            "rubric_version": r["rubric_version"],
            "created_at": float(r["created_at"]),
        }
        for r in rows
    }


def record_calibration_run(
    judge_model: str,
    samples: int,
    n: int,
    metrics: dict,
    detail: dict | None = None,
) -> bool:
    """Persist one judge-human calibration result."""
    try:
        _ensure_schema()
        with closing(_connect(db_path())) as conn:
            conn.execute(
                """
                INSERT INTO calibration_runs
                    (judge_model, samples, n, qwk, spearman, pearson, mae,
                     exact_rate, within1_rate, detail_json, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(judge_model or ""),
                    int(samples or 0),
                    int(n or 0),
                    float(metrics.get("qwk") or 0.0),
                    float(metrics.get("spearman") or 0.0),
                    float(metrics.get("pearson") or 0.0),
                    float(metrics.get("mae") or 0.0),
                    float(metrics.get("exact_rate") or 0.0),
                    float(metrics.get("within1_rate") or 0.0),
                    json.dumps(detail or {}, default=str),
                    time.time(),
                ),
            )
            conn.commit()
        return True
    except Exception as exc:
        logger.debug("obs: record_calibration_run failed (non-fatal): %s", exc)
        return False


def calibration_summary(days: int = 180) -> dict:
    """Latest judge-human calibration + human label count (admin read model)."""
    days = max(1, min(int(days or 180), 3650))
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        latest = conn.execute(
            "SELECT * FROM calibration_runs WHERE created_at >= ? ORDER BY created_at DESC LIMIT 1",
            (_cutoff(days),),
        ).fetchone()
        labels = conn.execute(
            "SELECT COUNT(*) AS n, COUNT(DISTINCT turn_id) AS turns FROM human_labels WHERE created_at >= ?",
            (_cutoff(days),),
        ).fetchone()
    run = dict(latest) if latest else None
    if run:
        try:
            run["detail"] = json.loads(run.pop("detail_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            run["detail"] = {}
    return {
        "latest": run,
        "human_labels": int(labels["n"] or 0),
        "human_labeled_turns": int(labels["turns"] or 0),
        "thresholds": {"good": 0.6, "excellent": 0.8},
    }


def human_labeled_turn_ids(rater: str = "human") -> set[str]:
    """Turn ids already rated by one rater (admin calibration queue exclusion)."""
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        rows = conn.execute("SELECT turn_id FROM human_labels WHERE rater = ?", (str(rater or "human"),)).fetchall()
    return {r["turn_id"] for r in rows}


def latest_eval_score(turn_id: str) -> dict | None:
    """Newest judge verdict for a turn (used when revealing it after human rating)."""
    if not turn_id:
        return None
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        row = conn.execute(
            "SELECT turn_id, score, judge_model, created_at FROM eval_scores "
            "WHERE turn_id = ? ORDER BY id DESC LIMIT 1",
            (str(turn_id),),
        ).fetchone()
    return dict(row) if row else None


def calibration_queue(days: int = 3650, rater: str = "human", limit: int = 20) -> list[dict]:
    """Judged turns that this rater has not labeled yet (newest first)."""
    days = max(1, min(int(days or 3650), 3650))
    limit = max(1, min(int(limit or 20), 200))
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        rows = conn.execute(
            """
            SELECT e.turn_id, e.score, e.judge_model, e.created_at
            FROM eval_scores e
            LEFT JOIN human_labels h ON h.turn_id = e.turn_id AND h.rater = ?
            WHERE h.id IS NULL
              AND e.turn_id NOT LIKE 'demo-%'
              AND e.created_at >= ?
              AND e.id = (SELECT MAX(e2.id) FROM eval_scores e2 WHERE e2.turn_id = e.turn_id)
            ORDER BY e.created_at DESC
            LIMIT ?
            """,
            (str(rater or "human"), _cutoff(days), limit),
        ).fetchall()
    return [dict(r) for r in rows]


def calibration_progress(days: int = 3650, rater: str = "human") -> dict:
    """How many judged turns are labeled / remaining for one rater."""
    days = max(1, min(int(days or 3650), 3650))
    cutoff = _cutoff(days)
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        judged = conn.execute(
            "SELECT COUNT(DISTINCT turn_id) AS n FROM eval_scores WHERE created_at >= ? AND turn_id NOT LIKE 'demo-%'",
            (cutoff,),
        ).fetchone()["n"]
        labeled = conn.execute(
            "SELECT COUNT(*) AS n FROM human_labels h WHERE h.rater = ? AND EXISTS ("
            "SELECT 1 FROM eval_scores e WHERE e.turn_id = h.turn_id AND e.created_at >= ? AND e.turn_id NOT LIKE 'demo-%')",
            (str(rater or "human"), cutoff),
        ).fetchone()["n"]
    judged = int(judged or 0)
    labeled = int(labeled or 0)
    return {"judged": judged, "labeled": labeled, "remaining": max(0, judged - labeled)}


def calibration_pairs(rater: str = "human") -> list[dict]:
    """Human/judge pairs for one rater (newest judge verdict per turn)."""
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        rows = conn.execute(
            """
            SELECT h.turn_id, h.score AS human, e.score AS judge, e.judge_model,
                   h.created_at AS labeled_at
            FROM human_labels h
            JOIN eval_scores e ON e.turn_id = h.turn_id
            WHERE h.rater = ?
              AND e.id = (SELECT MAX(e2.id) FROM eval_scores e2 WHERE e2.turn_id = h.turn_id)
            ORDER BY h.created_at DESC
            """,
            (str(rater or "human"),),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Aggregations (admin API) ─────────────────────────────────────────────────


def _cutoff(days: int) -> float:
    days = max(1, min(int(days or 7), 365))
    return time.time() - days * 86400


def _pct(sorted_values: list[int], p: float) -> int:
    if not sorted_values:
        return 0
    idx = min(len(sorted_values) - 1, max(0, int(round((p / 100.0) * (len(sorted_values) - 1)))))
    return int(sorted_values[idx])


def _rate(num: float, den: float) -> float:
    return round(float(num) / float(den), 4) if den else 0.0


def summary(days: int = 7) -> dict:
    """Headline KPIs for the last N days (all users)."""
    days = max(1, min(int(days or 7), 365))
    cutoff = _cutoff(days)
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS turns,
                   SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok,
                   SUM(CASE WHEN status IN ('error','cancelled') THEN 1 ELSE 0 END) AS errors,
                   SUM(CASE WHEN status='empty' THEN 1 ELSE 0 END) AS empty,
                   SUM(tokens_in) AS tokens_in,
                   SUM(tokens_out) AS tokens_out,
                   SUM(cost) AS cost,
                   AVG(tools_count) AS avg_tools,
                   SUM(tool_errors) AS tool_errors,
                   SUM(citations) AS citations,
                   SUM(CASE WHEN citations > 0 THEN 1 ELSE 0 END) AS with_citations,
                   SUM(no_answer) AS no_answer,
                   COUNT(DISTINCT uid) AS users
            FROM turns WHERE started_at >= ?
            """,
            (cutoff,),
        ).fetchone()
        latencies = [
            int(r["latency_ms"])
            for r in conn.execute(
                "SELECT latency_ms FROM turns WHERE started_at >= ? AND latency_ms > 0", (cutoff,)
            ).fetchall()
        ]
        feedback = {
            r["rating"]: r["n"]
            for r in conn.execute(
                "SELECT rating, COUNT(*) AS n FROM feedback WHERE created_at >= ? GROUP BY rating", (cutoff,)
            ).fetchall()
        }
        tool_calls = conn.execute("SELECT COUNT(*) AS n FROM tool_calls WHERE created_at >= ?", (cutoff,)).fetchone()[
            "n"
        ]

    latencies.sort()
    total = int(row["turns"] or 0)
    ok = int(row["ok"] or 0)
    errors = int(row["errors"] or 0)
    empty = int(row["empty"] or 0)
    return {
        "range_days": days,
        "since": cutoff,
        "turns": total,
        "ok": ok,
        "errors": errors,
        "empty": empty,
        "error_rate": _rate(errors, total),
        "empty_rate": _rate(empty, total),
        "users": int(row["users"] or 0),
        "latency_p50_ms": _pct(latencies, 50),
        "latency_p95_ms": _pct(latencies, 95),
        "latency_avg_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
        "tokens_in": int(row["tokens_in"] or 0),
        "tokens_out": int(row["tokens_out"] or 0),
        "cost": round(float(row["cost"] or 0.0), 4),
        "avg_tools_per_turn": round(float(row["avg_tools"] or 0.0), 2),
        "tool_calls": int(tool_calls or 0),
        "tool_errors": int(row["tool_errors"] or 0),
        "citation_rate": _rate(int(row["with_citations"] or 0), ok),
        "no_answer_rate": _rate(int(row["no_answer"] or 0), ok),
        "feedback_up": int(feedback.get(1, 0)),
        "feedback_down": int(feedback.get(-1, 0)),
    }


def daily_cost_summary(days: int = 1) -> dict:
    """Cost/token totals + top spenders for the last N days (alerting/abuse)."""
    days = max(1, min(int(days or 1), 365))
    cutoff = _cutoff(days)
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(cost), 0) AS cost,
                   COALESCE(SUM(tokens_in), 0) AS tokens_in,
                   COALESCE(SUM(tokens_out), 0) AS tokens_out,
                   COUNT(*) AS turns
            FROM turns WHERE started_at >= ?
            """,
            (cutoff,),
        ).fetchone()
        users = conn.execute(
            """
            SELECT uid, COALESCE(SUM(cost), 0) AS cost, COUNT(*) AS turns
            FROM turns WHERE started_at >= ? AND uid != ''
            GROUP BY uid ORDER BY cost DESC LIMIT 5
            """,
            (cutoff,),
        ).fetchall()
    top_users = [
        {"uid": r["uid"], "cost": round(float(r["cost"] or 0), 4), "turns": int(r["turns"] or 0)} for r in users
    ]
    return {
        "range_days": days,
        "cost": round(float(row["cost"] or 0), 4),
        "tokens_in": int(row["tokens_in"] or 0),
        "tokens_out": int(row["tokens_out"] or 0),
        "turns": int(row["turns"] or 0),
        "top_user": top_users[0] if top_users else None,
        "top_users": top_users,
    }


def timeseries(days: int = 14) -> list[dict]:
    """Per-day turn counts, error rate, latency percentiles and cost."""
    days = max(1, min(int(days or 14), 365))
    cutoff = _cutoff(days)
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        rows = conn.execute(
            """
            SELECT started_at, status, latency_ms, cost, tools_count, citations, no_answer
            FROM turns WHERE started_at >= ?
            """,
            (cutoff,),
        ).fetchall()

    buckets: dict[str, dict] = {}
    for r in rows:
        day = datetime.fromtimestamp(float(r["started_at"]), tz=UTC).date().isoformat()
        b = buckets.setdefault(day, {"latencies": [], "turns": 0, "errors": 0, "cost": 0.0, "tools": 0, "cited": 0})
        b["turns"] += 1
        if r["status"] == "error":
            b["errors"] += 1
        if r["latency_ms"]:
            b["latencies"].append(int(r["latency_ms"]))
        b["cost"] += float(r["cost"] or 0.0)
        b["tools"] += int(r["tools_count"] or 0)
        b["cited"] += 1 if int(r["citations"] or 0) > 0 else 0

    out = []
    today = datetime.now(tz=UTC).date()
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        b = buckets.get(day)
        if not b:
            out.append(
                {
                    "date": day,
                    "turns": 0,
                    "errors": 0,
                    "error_rate": 0.0,
                    "p50_ms": 0,
                    "p95_ms": 0,
                    "cost": 0.0,
                    "avg_tools": 0.0,
                    "citation_rate": 0.0,
                }
            )
            continue
        lats = sorted(b["latencies"])
        out.append(
            {
                "date": day,
                "turns": b["turns"],
                "errors": b["errors"],
                "error_rate": _rate(b["errors"], b["turns"]),
                "p50_ms": _pct(lats, 50),
                "p95_ms": _pct(lats, 95),
                "cost": round(b["cost"], 4),
                "avg_tools": round(b["tools"] / b["turns"], 2) if b["turns"] else 0.0,
                "citation_rate": _rate(b["cited"], b["turns"]),
            }
        )
    return out


def tool_stats(days: int = 7) -> list[dict]:
    """Per-tool usage, error rate and latency (MCP server kept separate)."""
    days = max(1, min(int(days or 7), 365))
    cutoff = _cutoff(days)
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        rows = conn.execute(
            """
            SELECT tool, group_name, server, status, duration_ms, result_chars, created_at
            FROM tool_calls WHERE created_at >= ?
            """,
            (cutoff,),
        ).fetchall()

    groups: dict[tuple, dict] = {}
    for r in rows:
        key = (r["tool"], r["group_name"], r["server"])
        g = groups.setdefault(key, {"durations": [], "calls": 0, "errors": 0, "chars": 0, "last": 0.0})
        g["calls"] += 1
        if r["status"] == "error":
            g["errors"] += 1
        if r["duration_ms"]:
            g["durations"].append(int(r["duration_ms"]))
        g["chars"] += int(r["result_chars"] or 0)
        g["last"] = max(g["last"], float(r["created_at"] or 0))

    out = []
    for (tool, group_name, server), g in groups.items():
        lats = sorted(g["durations"])
        out.append(
            {
                "tool": tool,
                "group": group_name,
                "server": server,
                "calls": g["calls"],
                "errors": g["errors"],
                "error_rate": _rate(g["errors"], g["calls"]),
                "avg_ms": int(sum(lats) / len(lats)) if lats else 0,
                "p95_ms": _pct(lats, 95),
                "avg_result_chars": int(g["chars"] / g["calls"]) if g["calls"] else 0,
                "last_used": g["last"],
            }
        )
    out.sort(key=lambda x: (-x["calls"], x["tool"]))
    return out


def model_stats(days: int = 7) -> list[dict]:
    """Per-model volume, latency, cost, citation and error rates."""
    days = max(1, min(int(days or 7), 365))
    cutoff = _cutoff(days)
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        rows = conn.execute(
            """
            SELECT model_key, model_id, status, latency_ms, cost, tokens_in, tokens_out, citations
            FROM turns WHERE started_at >= ?
            """,
            (cutoff,),
        ).fetchall()

    groups: dict[tuple, dict] = {}
    for r in rows:
        key = (r["model_key"] or r["model_id"] or "unknown", r["model_id"] or "")
        g = groups.setdefault(
            key, {"turns": 0, "errors": 0, "latencies": [], "cost": 0.0, "tin": 0, "tout": 0, "cited": 0}
        )
        g["turns"] += 1
        if r["status"] == "error":
            g["errors"] += 1
        if r["latency_ms"]:
            g["latencies"].append(int(r["latency_ms"]))
        g["cost"] += float(r["cost"] or 0.0)
        g["tin"] += int(r["tokens_in"] or 0)
        g["tout"] += int(r["tokens_out"] or 0)
        g["cited"] += 1 if int(r["citations"] or 0) > 0 else 0

    total = sum(g["turns"] for g in groups.values()) or 1
    out = []
    for (model_key, model_id), g in groups.items():
        lats = sorted(g["latencies"])
        out.append(
            {
                "model_key": model_key,
                "model_id": model_id,
                "turns": g["turns"],
                "share": _rate(g["turns"], total),
                "errors": g["errors"],
                "error_rate": _rate(g["errors"], g["turns"]),
                "p50_ms": _pct(lats, 50),
                "p95_ms": _pct(lats, 95),
                "tokens_in": g["tin"],
                "tokens_out": g["tout"],
                "cost": round(g["cost"], 4),
                "citation_rate": _rate(g["cited"], g["turns"]),
            }
        )
    out.sort(key=lambda x: -x["turns"])
    return out


def recent_turns(limit: int = 50, status: str = "", uid: str = "") -> list[dict]:
    """Newest turns for the admin table; optional status/uid filter."""
    limit = max(1, min(int(limit or 50), 200))
    sql = (
        "SELECT turn_id, uid, chat_id, model_key, model_id, mode, started_at, finished_at, "
        "latency_ms, total_ms, status, error, iterations, tokens_in, tokens_out, cost, "
        "tools_count, tool_errors, groups_json, citations, answer_chars, no_answer "
        "FROM turns WHERE 1=1"
    )
    params: list = []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if uid:
        sql += " AND uid = ?"
        params.append(uid)
    sql += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)

    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["groups"] = json.loads(d.pop("groups_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["groups"] = {}
        out.append(d)
    return out


def turn_detail(turn_id: str) -> dict | None:
    """One turn + its tool calls, for the trace drill-down."""
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        row = conn.execute("SELECT * FROM turns WHERE turn_id = ?", (str(turn_id or ""),)).fetchone()
        if row is None:
            return None
        tools = conn.execute(
            "SELECT seq, tool, group_name, server, status, error_class, duration_ms, result_chars, "
            "result_preview, summary "
            "FROM tool_calls WHERE turn_id = ? ORDER BY seq",
            (str(turn_id),),
        ).fetchall()
    turn = dict(row)
    try:
        turn["groups"] = json.loads(turn.pop("groups_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        turn["groups"] = {}
    try:
        turn["meta"] = json.loads(turn.pop("meta_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        turn["meta"] = {}
    return {"turn": turn, "tools": [dict(t) for t in tools]}


def feedback_summary(days: int = 7) -> dict:
    days = max(1, min(int(days or 7), 365))
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        rows = conn.execute(
            "SELECT rating, COUNT(*) AS n FROM feedback WHERE created_at >= ? GROUP BY rating",
            (_cutoff(days),),
        ).fetchall()
    up = sum(int(r["n"]) for r in rows if int(r["rating"]) > 0)
    down = sum(int(r["n"]) for r in rows if int(r["rating"]) < 0)
    total = up + down
    return {"up": up, "down": down, "total": total, "positive_rate": round(up / total, 4) if total else 0.0}


def health() -> dict:
    """Telemetry + MCP readiness snapshot for the admin dashboard."""
    import config

    path = db_path()
    info: dict = {
        "enabled": bool(getattr(config, "OBS_ENABLED", True)),
        "db_path": str(path),
        "db_exists": path.exists(),
        "retention_days": int(getattr(config, "OBS_RETENTION_DAYS", 90) or 0),
    }
    if info["db_exists"]:
        try:
            with closing(_connect(path)) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS n, MIN(started_at) AS first, MAX(started_at) AS last FROM turns"
                ).fetchone()
            info.update(
                turns=int(row["n"] or 0),
                first_turn_at=float(row["first"] or 0),
                last_turn_at=float(row["last"] or 0),
            )
        except Exception:
            pass
    try:
        import mcp_integration

        event = getattr(mcp_integration, "_mcp_ready_event", None)
        info["mcp"] = {
            "tool_count": len(mcp_integration.MCP_TOOLS),
            "servers": list(getattr(mcp_integration, "MCP_TOOL_SERVERS", {}).values())[:20],
            "ready": bool(event.is_set()) if event is not None else False,
            "ready_at": getattr(mcp_integration, "MCP_READY_AT", None),
        }
    except Exception:
        info["mcp"] = {}
    return info


# ── Retrieval golden-set labeling (admin UI) ────────────────────────────────


def seed_retrieval_candidates(rows: list[dict]) -> int:
    """Upsert retrieval candidates (metadata only; labels are preserved)."""
    if not rows:
        return 0
    _ensure_schema()
    now = time.time()
    written = 0
    with closing(_connect(db_path())) as conn:
        positions: dict[str, int] = {}
        for row in rows:
            query_id = str(row.get("query_id") or "")
            report_id = str(row.get("report_id") or "")
            if not query_id or not report_id:
                continue
            pos = positions.get(query_id, 0)
            positions[query_id] = pos + 1
            conn.execute(
                """
                INSERT INTO retrieval_candidates
                    (query_id, query, country, report_id, title, date, url, position, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(query_id, report_id) DO UPDATE SET
                    query=excluded.query, country=excluded.country, title=excluded.title,
                    date=excluded.date, url=excluded.url, position=excluded.position
                """,
                (
                    query_id,
                    str(row.get("query") or ""),
                    str(row.get("country") or ""),
                    report_id,
                    str(row.get("title") or "")[:400],
                    str(row.get("date") or "")[:32],
                    str(row.get("url") or ""),
                    pos,
                    now,
                ),
            )
            written += 1
        conn.commit()
    return written


def retrieval_progress() -> dict:
    """Progress for retrieval relevance labeling."""
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        total_q = conn.execute("SELECT COUNT(DISTINCT query_id) AS n FROM retrieval_candidates").fetchone()["n"]
        labeled_q = conn.execute(
            "SELECT COUNT(*) AS n FROM (SELECT query_id FROM retrieval_candidates "
            "GROUP BY query_id HAVING SUM(CASE WHEN relevant IS NULL THEN 1 ELSE 0 END)=0)"
        ).fetchone()["n"]
        total_c = conn.execute("SELECT COUNT(*) AS n FROM retrieval_candidates").fetchone()["n"]
        labeled_c = conn.execute(
            "SELECT COUNT(*) AS n FROM retrieval_candidates WHERE relevant IS NOT NULL"
        ).fetchone()["n"]
        relevant = conn.execute("SELECT COUNT(*) AS n FROM retrieval_candidates WHERE relevant=1").fetchone()["n"]
    return {
        "queries": int(total_q or 0),
        "labeled_queries": int(labeled_q or 0),
        "candidates": int(total_c or 0),
        "labeled_candidates": int(labeled_c or 0),
        "relevant": int(relevant or 0),
    }


def retrieval_next_query() -> dict | None:
    """Return the first query with any unlabeled candidate, with candidates."""
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        row = conn.execute(
            "SELECT query_id FROM retrieval_candidates GROUP BY query_id "
            "HAVING SUM(CASE WHEN relevant IS NULL THEN 1 ELSE 0 END) > 0 "
            "ORDER BY MIN(position), query_id LIMIT 1"
        ).fetchone()
        if not row:
            return None
        qid = row["query_id"]
        rows = conn.execute(
            "SELECT id, query_id, query, country, report_id, title, date, url, relevant, position "
            "FROM retrieval_candidates WHERE query_id=? ORDER BY position, id",
            (qid,),
        ).fetchall()
    items = [dict(r) for r in rows]
    return {
        "query_id": qid,
        "query": items[0]["query"],
        "country": items[0]["country"],
        "candidates": items,
        "progress": retrieval_progress(),
    }


def save_retrieval_labels(query_id: str, relevant_report_ids: list[str], rater: str = "admin") -> int:
    """Lock one query's candidate labels: 1 for supplied ids, 0 for the rest."""
    qid = str(query_id or "")
    if not qid:
        return 0
    _ensure_schema()
    now = time.time()
    ids = [str(x) for x in (relevant_report_ids or []) if str(x)]
    with closing(_connect(db_path())) as conn:
        exists = conn.execute("SELECT COUNT(*) AS n FROM retrieval_candidates WHERE query_id=?", (qid,)).fetchone()["n"]
        if not exists:
            return 0
        conn.execute(
            "UPDATE retrieval_candidates SET relevant=0, labeled_at=?, labeled_by=? WHERE query_id=?",
            (now, str(rater or "admin"), qid),
        )
        if ids:
            marks = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE retrieval_candidates SET relevant=1, labeled_at=?, labeled_by=? "
                f"WHERE query_id=? AND report_id IN ({marks})",
                (now, str(rater or "admin"), qid, *ids),
            )
        conn.commit()
        return len(ids)


def retrieval_golden_set() -> list[dict]:
    """Export labeled queries that have at least one relevant report."""
    _ensure_schema()
    with closing(_connect(db_path())) as conn:
        qrows = conn.execute(
            "SELECT query_id, query, country FROM retrieval_candidates "
            "GROUP BY query_id HAVING SUM(CASE WHEN relevant=1 THEN 1 ELSE 0 END) > 0 "
            "ORDER BY MIN(position), query_id"
        ).fetchall()
        out = []
        for q in qrows:
            ids = [
                r["report_id"]
                for r in conn.execute(
                    "SELECT report_id FROM retrieval_candidates WHERE query_id=? AND relevant=1 ORDER BY position",
                    (q["query_id"],),
                ).fetchall()
            ]
            out.append({"query": q["query"], "relevant": ids, "country": q["country"]})
    return out


def prune(days: int | None = None) -> int:
    """Delete turns (and orphaned tool calls/feedback) older than retention."""
    import config

    if days is None:
        days = int(getattr(config, "OBS_RETENTION_DAYS", 90) or 90)
    try:
        days = int(days)
    except (TypeError, ValueError):
        return 0
    if days <= 0:
        return 0
    cutoff = time.time() - days * 86400
    try:
        _ensure_schema()
        with closing(_connect(db_path())) as conn:
            deleted = conn.execute("DELETE FROM turns WHERE started_at < ?", (cutoff,)).rowcount
            conn.execute("DELETE FROM tool_calls WHERE turn_id NOT IN (SELECT turn_id FROM turns)")
            conn.execute("DELETE FROM feedback WHERE created_at < ?", (cutoff,))
            conn.execute("DELETE FROM eval_scores WHERE created_at < ?", (cutoff,))
            conn.execute("DELETE FROM eval_retrieval WHERE created_at < ?", (cutoff,))
            conn.commit()
        return max(0, int(deleted or 0))
    except Exception as exc:
        logger.debug("obs: prune failed (non-fatal): %s", exc)
        return 0
