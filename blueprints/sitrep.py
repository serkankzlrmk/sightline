"""
blueprints/sitrep.py — Flask Blueprint for /api/sitrep/* routes.

Extracted from server.py lines 2186–2585.
All routes use url_prefix='/api/sitrep', so route strings omit that prefix.
Shared state and helpers are imported from blueprints.helpers.
"""

import logging
import re
import sys
import threading
import time as _time
import uuid
from collections import Counter
from pathlib import Path
from queue import Empty, Queue

from flask import Blueprint, Response, jsonify, request

from auth import _dev_mode, current_role, current_uid, require_admin, require_auth, require_role
from blueprints.helpers import (
    _JOBS_MAX_AGE,
    _cleanup_stream_nonces,
    _consume_stream_nonce,
    _create_stream_nonce,
    _get_chroma_adapter,
    _jobs,
    _jobs_lock,
    _log_event,
    _run_job,
)

BASE_DIR = Path(__file__).resolve().parent.parent

sitrep_bp = Blueprint("sitrep", __name__, url_prefix="/api/sitrep")

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _run_sitrep_job(job_id: str, cmd: list):
    """Run a SITREP pipeline subprocess and stream its output to the job queue.

    Delegates to ``blueprints.helpers._run_job`` so the single implementation
    stays in one place and any future changes are automatically picked up.
    """

    _run_job(job_id, cmd)


# ── Routes ────────────────────────────────────────────────────────────────────


@sitrep_bp.route("/themes")
@require_auth
def api_sitrep_themes():
    """Return unique theme values — ChromaDB first, SQLite fallback."""
    try:
        from sitrep.chroma_adapter import ChromaAdapter

        db = ChromaAdapter()
        return jsonify(db.list_themes())
    except Exception as exc:
        logger.error("api_sitrep_themes error: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load themes"}), 500


@sitrep_bp.route("/countries")
@require_auth
def api_sitrep_countries():
    """Return country values with chunk counts for SITREP dropdown."""
    try:

        db = _get_chroma_adapter()
        return jsonify(db.list_countries_with_counts())
    except Exception as exc:
        logger.error("api_sitrep_countries error: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load countries"}), 500


@sitrep_bp.route("/date-range/<country>")
@require_auth
def api_sitrep_date_range(country):
    try:

        db = _get_chroma_adapter()
        return jsonify(db.get_date_range(country))
    except Exception as exc:
        logger.error("api_sitrep_date_range error: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load date range"}), 500


@sitrep_bp.route("/chunk-preview", methods=["POST"])
@require_auth
def api_sitrep_chunk_preview():
    """Return chunk count and theme breakdown matching the given filters."""
    try:
        from sitrep.chroma_adapter import ChromaAdapter

        db = ChromaAdapter()
        data = request.get_json(silent=True) or {}
        country = data.get("country", "").strip()
        if not country:
            return jsonify({"error": "country is required"}), 400

        themes = [t.strip() for t in data.get("themes", []) if t.strip()]
        date_from = (data.get("date_from") or "").strip()
        date_to = (data.get("date_to") or "").strip()

        chunks = db.get_chunks_by_country_and_themes(
            country,
            themes or None,
            date_from=date_from or None,
            date_to=date_to or None,
        )
        theme_counts = Counter()
        for c in chunks:
            raw = c.get("themes", "")
            if raw:
                for t in raw.split(","):
                    t = t.strip()
                    if t:
                        theme_counts[t] += 1
        top_themes = [k for k, _ in theme_counts.most_common(5)]

        return jsonify(
            {
                "count": len(chunks),
                "themes_found": top_themes,
                "filters": {"themes": themes, "date_from": date_from, "date_to": date_to},
            }
        )
    except Exception as exc:
        logger.error("api_sitrep_chunk_preview error: %s", exc, exc_info=True)
        return jsonify({"error": "Failed to load chunk preview"}), 500


@sitrep_bp.route("/run", methods=["POST"])
@require_role("premium")
def api_sitrep_run():

    data = request.get_json(silent=True) or {}
    country = data.get("country", "").strip()[:100]
    event = data.get("event", "").strip()[:200]
    if not country:
        return jsonify({"error": "country is required"}), 400
    if not event:
        event = country

    themes = [t.strip()[:80] for t in data.get("themes", []) if t.strip()][:10]
    skip_cache = bool(data.get("skip_cache", False))
    date_from = (data.get("date_from") or "").strip()[:10]
    date_to = (data.get("date_to") or "").strip()[:10]

    _DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    if date_from and not _DATE_RE.match(date_from):
        return jsonify({"error": "Invalid date_from format (YYYY-MM-DD)"}), 400
    if date_to and not _DATE_RE.match(date_to):
        return jsonify({"error": "Invalid date_to format (YYYY-MM-DD)"}), 400

    cmd = [sys.executable, str(BASE_DIR / "sitrep" / "pipeline.py"), "--country", country, "--event", event]
    if themes:
        cmd += ["--themes"] + themes
    if date_from:
        cmd += ["--date-from", date_from]
    if date_to:
        cmd += ["--date-to", date_to]
    if skip_cache:
        cmd.append("--skip-cache")

    job_id = uuid.uuid4().hex[:8]
    with _jobs_lock:
        # Clean up old completed jobs to prevent memory leak
        now = _time.time()
        stale = [
            jid
            for jid, j in _jobs.items()
            if j.get("status") in ("done", "error") and now - j.get("finished_at", now) > _JOBS_MAX_AGE
        ]
        for jid in stale:
            del _jobs[jid]

        _jobs[job_id] = {
            "queue": Queue(),
            "status": "running",
            "proc": None,
            "country": country,
            "event": event,
            "uid": current_uid(),  # bind job to creator for ownership check
        }

    t = threading.Thread(target=_run_sitrep_job, args=(job_id, cmd), daemon=True)
    t.start()
    nonce = _create_stream_nonce(current_uid(), job_id)
    _log_event(
        current_uid(),
        "sitrep_run_started",
        {
            "job_id": job_id,
            "country": country,
            "event": event,
            "themes": themes,
            "role": current_role(),
        },
    )
    return jsonify({"job_id": job_id, "stream_nonce": nonce})


@sitrep_bp.route("/stream/<job_id>")
def api_sitrep_stream(job_id):
    """SITREP SSE stream. Auth via single-use nonce (bound to job_id + UID).

    The nonce is issued by /api/sitrep/run and is single-use, 5-min TTL.
    EventSource cannot send Authorization headers, so we use ?nonce=<token>.
    The old ?token=<JWT> and ?api_key= query-param fallbacks were removed
    because they leaked secrets to access logs, browser history, and referrers.
    """

    # Dev mode: no auth required, but still bind to the job
    if _dev_mode():
        requesting_uid = "dev-local"
    else:
        nonce = request.args.get("nonce", "").strip()
        if not nonce:
            return jsonify({"error": "Missing stream nonce. Obtain one from /api/sitrep/run."}), 401
        # We don't know the UID yet — the nonce carries it.
        # _consume_stream_nonce checks the nonce's UID against the job's owner UID.
        # First, look up the job to get the owner UID, then validate the nonce against it.
        with _jobs_lock:
            job = _jobs.get(job_id)
            owner_uid = job.get("uid", "") if job else ""
        if not owner_uid:
            return jsonify({"error": "Unknown job id"}), 404
        if not _consume_stream_nonce(nonce, owner_uid, job_id):
            return jsonify({"error": "Invalid, expired, or mismatched nonce."}), 401
        requesting_uid = owner_uid

    _cleanup_stream_nonces()

    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return jsonify({"error": "Unknown job id"}), 404
        # Ownership check: the requesting UID must match the job creator
        if job.get("uid", "") and requesting_uid != job["uid"]:
            logger.warning(
                "SITREP stream access denied: uid=%s attempted to read job %s owned by uid=%s",
                requesting_uid,
                job_id,
                job.get("uid"),
            )
            return jsonify({"error": "Access denied"}), 403
        q = job["queue"]
        job.get("status", "running")

    def generate():
        while True:
            try:
                line = q.get(timeout=25)
                if line is None:
                    with _jobs_lock:
                        status = _jobs.get(job_id, {}).get("status", "done")
                    yield f"data: __DONE__{status}\n\n"
                    break
                safe = line.replace("\n", " ").replace("\r", "")
                yield f"data: {safe}\n\n"
            except Empty:
                yield "data: __PING__\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@sitrep_bp.route("/job/<job_id>")
@require_auth
def api_sitrep_job(job_id):

    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return jsonify({"error": "Unknown job id"}), 404
        # Ownership check
        uid = current_uid()
        if job.get("uid", "") and uid != job["uid"]:
            return jsonify({"error": "Access denied"}), 403
        j = job
    return jsonify(
        {
            "job_id": job_id,
            "status": j.get("status", "running"),
            "country": j.get("country", ""),
            "event": j.get("event", ""),
        }
    )


@sitrep_bp.route("/reports")
@require_auth
def api_sitrep_reports():
    from config import OUTPUT_REPORTS_DIR

    items = []
    if OUTPUT_REPORTS_DIR.exists():
        for f in sorted(
            OUTPUT_REPORTS_DIR.glob("*report.json"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        ):
            items.append(
                {
                    "filename": f.name,
                    "size_kb": round(f.stat().st_size / 1024, 1),
                    "mtime": f.stat().st_mtime,
                }
            )
    return jsonify(items)


@sitrep_bp.route("/report")
@require_auth
def api_sitrep_report():
    from config import OUTPUT_REPORTS_DIR

    filename = request.args.get("file", "")
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        return jsonify({"error": "Invalid filename"}), 400
    base = OUTPUT_REPORTS_DIR.resolve()
    path = (OUTPUT_REPORTS_DIR / filename).resolve()
    # Defense-in-depth: verify the resolved path is inside the reports dir.
    # is_relative_to handles the trailing-separator correctly (avoids prefix
    # collision where /app/output/reports_evil would pass a startswith check).
    if not path.is_relative_to(base):
        return jsonify({"error": "Invalid filename"}), 400
    if not path.exists():
        return jsonify({"error": "Report not found"}), 404
    return path.read_text(encoding="utf-8"), 200, {"Content-Type": "application/json"}


# =============================================================================
# ROUTES — Weekly Bulletin
# =============================================================================


@sitrep_bp.route("/bulletins")
@require_auth
def api_bulletin_list():
    """List available weekly bulletins, sorted by date descending."""
    from sitrep.weekly_bulletin import list_bulletins

    bulletins = list_bulletins()
    return jsonify(bulletins)


@sitrep_bp.route("/bulletin/<filename>")
@require_auth
def api_bulletin_get(filename):
    """Get a specific bulletin JSON by filename."""
    from sitrep.weekly_bulletin import get_bulletin

    if ".." in filename or "/" in filename or "\\" in filename:
        return jsonify({"error": "Invalid filename"}), 400
    bulletin = get_bulletin(filename)
    if bulletin is None:
        return jsonify({"error": "Bulletin not found"}), 404
    _log_event(current_uid(), "bulletin_viewed", {"filename": filename})
    return jsonify(bulletin)


@sitrep_bp.route("/bulletin/generate", methods=["POST"])
@require_admin
def api_bulletin_generate():
    """Manually trigger bulletin generation (admin only).

    Accepts optional JSON body: {"date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD"}
    If no dates provided, defaults to last week (Mon-Sun).

    Runs generation in a background thread and returns a job_id immediately.
    Frontend can poll /api/sitrep/bulletin/generate/status/<job_id> for progress.
    """
    from datetime import datetime, timedelta

    from sitrep.weekly_bulletin import generate_weekly_bulletin

    data = request.get_json(silent=True) or {}
    date_from = data.get("date_from", "")
    date_to = data.get("date_to", "")

    if not date_from or not date_to:
        # Default to last week
        today = datetime.now()
        last_monday = today - timedelta(days=today.weekday() + 7)
        last_sunday = last_monday + timedelta(days=6)
        date_from = date_from or last_monday.strftime("%Y-%m-%d")
        date_to = date_to or last_sunday.strftime("%Y-%m-%d")

    # Create a job for background generation
    job_id = f"bulletin-{_time.time():.0f}"
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "queue": Queue(),
            "started_at": _time.time(),
            "type": "bulletin",
            "date_from": date_from,
            "date_to": date_to,
        }

    def _run_bulletin():
        q = _jobs[job_id]["queue"]
        try:
            q.put(f"Generating bulletin for {date_from} to {date_to}...")
            path = generate_weekly_bulletin(date_from=date_from, date_to=date_to)
            q.put(f"Bulletin saved: {path.name}")
            with _jobs_lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["finished_at"] = _time.time()
                _jobs[job_id]["result"] = {
                    "filename": path.name,
                    "date_from": date_from,
                    "date_to": date_to,
                }
        except Exception as exc:
            logging.exception("Bulletin generation failed")
            q.put(f"[ERROR] {exc}")
            with _jobs_lock:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["finished_at"] = _time.time()
                _jobs[job_id]["error"] = str(exc)
        finally:
            q.put(None)  # sentinel

    thread = threading.Thread(target=_run_bulletin, daemon=True)
    thread.start()

    return jsonify(
        {
            "status": "started",
            "job_id": job_id,
            "message": f"Generating bulletin for {date_from} to {date_to}",
            "date_from": date_from,
            "date_to": date_to,
        }
    )


@sitrep_bp.route("/bulletin/generate/status/<job_id>")
@require_admin
def api_bulletin_generate_status(job_id):
    """Poll bulletin generation job status (admin only)."""

    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # Collect any new log lines from the queue
    logs = []
    q = job["queue"]
    try:
        while True:
            line = q.get_nowait()
            if line is None:
                break
            logs.append(line)
    except Empty:
        pass

    response = {
        "status": job["status"],
        "logs": logs,
        "date_from": job.get("date_from", ""),
        "date_to": job.get("date_to", ""),
    }
    if job["status"] == "done" and "result" in job:
        response["result"] = job["result"]
    if job["status"] == "error" and "error" in job:
        response["error"] = job["error"]

    return jsonify(response)
