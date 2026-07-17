"""
blueprints/ingest_bp.py — Flask Blueprint for /api/ingest/* routes.

Extracted from server.py lines 2823–3025.
All shared helpers (DB functions, state dicts, etc.) are accessed
via `import server` to avoid circular imports and duplication.
"""

import logging
import os
import re
import subprocess
import sys
from pathlib import Path

from flask import Blueprint, jsonify, request

from auth import current_uid, require_admin
from config import DB_PATH

logger = logging.getLogger(__name__)

ingest_bp = Blueprint("ingest", __name__, url_prefix="/api/ingest")

MANUAL_ID_BASE = 9_000_000_000  # manual TR-prefixed IDs start above this


# ─── Daily ingestion ────────────────────────────────────────────────────────

@ingest_bp.route("/daily", methods=["POST"])
@require_admin
def api_ingest_daily():
    """Run daily ingestion: fetch yesterday's reports + purge old data.

    Accepts optional JSON body: {"date": "YYYY-MM-DD", "purge_days": 90, "no_purge": false}
    Returns: {fetched, ingested, skipped, errors, purged_sql, purged_chroma}
    """
    import server

    data = request.get_json(silent=True) or {}
    target_date = data.get("date", "")  # empty = yesterday
    purge_days = data.get("purge_days", 90)
    no_purge = data.get("no_purge", False)

    # Validate target_date format (if provided)
    if target_date:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(target_date)):
            return jsonify({"error": "Invalid date format (YYYY-MM-DD)"}), 400
    # Validate purge_days is a positive int in a safe range (0-3650)
    try:
        purge_days = int(purge_days)
        if not (0 <= purge_days <= 3650):
            return jsonify({"error": "purge_days must be between 0 and 3650"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "purge_days must be an integer"}), 400

    # Build command
    cmd = [sys.executable, str(Path(__file__).resolve().parent.parent / "scripts" / "daily_ingest.py")]
    if target_date:
        cmd += ["--date", target_date]
    if no_purge:
        cmd.append("--no-purge")
    cmd += ["--purge-days", str(purge_days)]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min max
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        output = result.stdout + result.stderr

        # Parse the summary from output
        summary = {
            "fetched": 0, "ingested": 0, "skipped": 0, "errors": 0,
            "purged_sql": 0, "purged_chroma": 0,
            "log": output[-2000:] if len(output) > 2000 else output,
        }
        for line in output.splitlines():
            m = re.search(r"Fetched:\s+(\d+)", line)
            if m: summary["fetched"] = int(m.group(1))
            m = re.search(r"Ingested:\s+(\d+)", line)
            if m: summary["ingested"] = int(m.group(1))
            m = re.search(r"Skipped:\s+(\d+)", line)
            if m: summary["skipped"] = int(m.group(1))
            m = re.search(r"Errors:\s+(\d+)", line)
            if m: summary["errors"] = int(m.group(1))
            m = re.search(r"Purged \(SQL\):\s+(\d+)", line)
            if m: summary["purged_sql"] = int(m.group(1))
            m = re.search(r"Purged \(Vec\):\s+(\d+)", line)
            if m: summary["purged_chroma"] = int(m.group(1))

        if result.returncode != 0:
            summary["warning"] = "Script exited with non-zero code (some errors occurred)"

        server._log_event(current_uid(), "ingest_daily_completed", {
            "fetched": summary["fetched"], "ingested": summary["ingested"],
            "skipped": summary["skipped"], "errors": summary["errors"],
            "purged_sql": summary["purged_sql"], "purged_chroma": summary["purged_chroma"],
        })
        return jsonify(summary)

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Daily ingest timed out (10 min limit)"}), 504
    except Exception as e:
        logger.exception("Daily ingest failed: %s", e)
        return jsonify({"error": "Ingest failed. Check server logs for details."}), 500


# ─── Manual PDF upload ──────────────────────────────────────────────────────

@ingest_bp.route("/upload", methods=["POST"])
@require_admin
def api_ingest_upload():
    """Upload a PDF with user-supplied metadata → SQLite + ChromaDB."""
    import shutil
    import tempfile

    from reliefweb_api.db_manager import (
        CHUNK_OVERLAP,
        CHUNK_SIZE,
        DatabaseManager,
        build_chunk_with_header,
        chunk_text,
        extract_pdf_text,
    )
    from reliefweb_api.vector_store import VectorStore

    import server

    title       = (request.form.get("title")       or "").strip()[:500]
    source      = (request.form.get("source")      or "").strip()[:200]
    country     = (request.form.get("country")     or "").strip()[:500]
    format_type = (request.form.get("format_type") or "").strip()[:100]
    language    = (request.form.get("language")    or "").strip()[:10]
    date_str    = (request.form.get("date")        or "").strip()[:10]
    theme       = (request.form.get("theme")       or "").strip()[:1000]
    pdf_file    = request.files.get("pdf")

    missing = [f for f, v in [
        ("title", title), ("source", source), ("country", country),
        ("format_type", format_type), ("language", language), ("date", date_str),
    ] if not v]
    if not pdf_file or not pdf_file.filename:
        missing.append("pdf")
    if missing:
        return jsonify({"error": "Missing required fields", "fields": missing}), 400

    if not pdf_file.mimetype or pdf_file.mimetype not in ("application/pdf",):
        return jsonify({"error": "Only PDF files are accepted"}), 400

    # Magic-byte check: PDF files must start with %PDF-
    header = pdf_file.read(5)
    pdf_file.seek(0)
    if header != b"%PDF-":
        return jsonify({"error": "File does not appear to be a valid PDF"}), 400

    conn = server._db_conn()
    try:
        max_row = conn.execute(
            "SELECT MAX(report_id) FROM reports WHERE report_id > ?", (MANUAL_ID_BASE,)
        ).fetchone()
    finally:
        conn.close()
    new_id     = (max_row[0] or MANUAL_ID_BASE) + 1
    tr_display = f"TR-{new_id - MANUAL_ID_BASE:05d}"

    tmp      = tempfile.mkdtemp()
    try:
        from werkzeug.utils import secure_filename
        safe_nm  = secure_filename(pdf_file.filename) or "upload.pdf"
        pdf_path = os.path.join(tmp, safe_nm)
        pdf_file.save(pdf_path)

        pdf_text, pdf_pages = extract_pdf_text(pdf_path)
        if not pdf_text.strip():
            return jsonify({"error": "Could not extract text from PDF"}), 422

        countries_list = [c.strip() for c in country.split(",") if c.strip()]
        themes_list    = [t.strip() for t in theme.split(",")   if t.strip()]
        metadata = {
            "id":        new_id,
            "title":     title,
            "date":      {"original": date_str},
            "source":    [{"shortname": source}],
            "countries": [{"name": c} for c in countries_list],
            "themes":    [{"name": t} for t in themes_list],
            "format":    [{"name": format_type}],
            "language":  [{"code": language}],
            "url":       f"manual://{tr_display}",
        }

        chunks = []
        for raw in chunk_text(pdf_text, CHUNK_SIZE, CHUNK_OVERLAP):
            enriched = build_chunk_with_header(raw, metadata, "pdf")
            chunks.append({"source_type": "pdf", "content": enriched})

        try:
            db = DatabaseManager(str(DB_PATH))
            db.insert_report(metadata, chunks, has_pdf=True, has_content=False, pdf_pages=pdf_pages)
            db.close()
        except Exception as e:
            logger.error("Upload DB insert failed: %s", e, exc_info=True)
            return jsonify({"error": "Database insert failed"}), 500

        try:
            from config import CHROMA_DIR
            vs = VectorStore(str(CHROMA_DIR))
            vs.add_report(new_id, chunks, metadata)
        except Exception as e:
            logger.error("Upload vector store insert failed: %s", e, exc_info=True)
            return jsonify({"error": "Vector store insert failed"}), 500

        return jsonify({
            "success":      True,
            "report_id":    new_id,
            "tr_id":        tr_display,
            "title":        title,
            "chunks_added": len(chunks),
            "pdf_pages":    pdf_pages,
        })
    finally:
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass