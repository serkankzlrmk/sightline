"""
blueprints/db_bp.py — Flask Blueprint for /api/db/* routes.

Extracted from server.py lines 1999–2183.
All shared helpers (DB functions, state dicts, etc.) are accessed
via `import server` to avoid circular imports and duplication.
"""

import json
import logging
import sqlite3

from flask import Blueprint, jsonify, request

from auth import current_role, current_uid, require_auth
from config import DB_PATH

logger = logging.getLogger(__name__)

db_bp = Blueprint("db", __name__, url_prefix="/api/db")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _db_conn():
    """Return a connection to the reliefweb SQLite database with WAL mode."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _row_to_dict(row):
    return dict(row)


def _parse_countries(json_str):
    try:
        return json.loads(json_str or "[]")
    except Exception:
        return []


# ─── Stats ──────────────────────────────────────────────────────────────────

@db_bp.route("/stats")
@require_auth
def api_db_stats():
    conn = _db_conn()
    try:
        report_count = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        chunk_count  = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        # SQL-side aggregation for sources (stored as plain text in `source` column)
        source_rows = conn.execute(
            "SELECT source, COUNT(*) AS cnt FROM reports GROUP BY source ORDER BY cnt DESC LIMIT 10"
        ).fetchall()
        # Countries — SQL json_each aggregation (much faster than Python parsing)
        country_rows = conn.execute(
            "SELECT je.value, COUNT(*) as cnt FROM reports, json_each(countries) je "
            "GROUP BY je.value ORDER BY cnt DESC LIMIT 15"
        ).fetchall()
    except Exception:
        return jsonify({"report_count": 0, "chunk_count": 0, "top_countries": [], "top_sources": []})
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return jsonify({
        "report_count": report_count,
        "chunk_count":  chunk_count,
        "top_countries": [[r[0], r[1]] for r in country_rows],
        "top_sources":   [(r[0] or "?", r[1]) for r in source_rows],
    })


# ─── Countries list ─────────────────────────────────────────────────────────

@db_bp.route("/countries")
@require_auth
def api_db_countries():
    conn = _db_conn()
    try:
        # Cap rows loaded into memory (countries stored as JSON text, needs Python parse)
        rows = conn.execute("SELECT countries FROM reports LIMIT 2000").fetchall()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return jsonify([])
    finally:
        try:
            conn.close()
        except Exception:
            pass
    all_countries = set()
    for r in rows:
        for c in _parse_countries(r[0]):
            all_countries.add(c)
    return jsonify(sorted(all_countries))


# ─── Sources list ────────────────────────────────────────────────────────────

@db_bp.route("/sources")
@require_auth
def api_db_sources():
    conn = _db_conn()
    try:
        rows = conn.execute("SELECT DISTINCT source FROM reports ORDER BY source").fetchall()
    except Exception:
        return jsonify([])
    finally:
        conn.close()
    return jsonify([r[0] for r in rows if r[0]])


# ─── Reports search ─────────────────────────────────────────────────────────

@db_bp.route("/reports")
@require_auth
def api_db_reports():
    search   = request.args.get("search",   "").strip()
    country  = request.args.get("country",  "").strip()
    source   = request.args.get("source",   "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to   = request.args.get("date_to",   "").strip()
    limit    = request.args.get("limit",    "").strip()
    sort     = request.args.get("sort",      "date").strip()
    order    = request.args.get("order",     "desc").strip()

    role = current_role()

    conn = _db_conn()
    try:
        query = (
            "SELECT report_id, title, date, countries, source, themes, "
            "format_type, has_pdf, has_content, total_chunks, url "
            "FROM reports WHERE 1=1"
        )
        params = []

        if search:
            query += " AND title LIKE ?"
            params.append(f"%{search}%")
        if source:
            query += " AND source = ?"
            params.append(source)
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)

        if not date_from and not date_to and not search and not source and not country:
            query += " AND date >= date('now', '-7 days')"
        if role not in ("premium", "admin"):
            query += " AND date >= date('now', '-3 days')"
        order_dir = "ASC" if order.upper() == "ASC" else "DESC"
        sort_col = "date" if sort == "date" else "report_id"
        query += f" ORDER BY {sort_col} {order_dir}"

        if limit and limit.isdigit():
            query += f" LIMIT {int(limit)}"
        else:
            query += " LIMIT 50"

        rows = conn.execute(query, params).fetchall()
    except Exception:
        return jsonify([])
    finally:
        conn.close()

    results = []
    for r in rows:
        d = _row_to_dict(r)
        clist = _parse_countries(d.get("countries"))
        if country and not any(country == c for c in clist):
            continue
        d["primary_country"] = clist[0] if clist else ""
        d["all_countries"]   = clist
        results.append(d)

    import server
    server._log_event(current_uid(), "db_search_performed", {
        "country": country, "source": source, "result_count": len(results),
    })
    return jsonify(results)


# ─── Report detail ───────────────────────────────────────────────────────────

@db_bp.route("/reports/<int:report_id>")
@require_auth
def api_db_report_detail(report_id):
    conn = _db_conn()
    try:
        row = conn.execute(
            "SELECT * FROM reports WHERE report_id=?", (report_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404

        d = _row_to_dict(row)
        d["all_countries"] = _parse_countries(d.get("countries"))
        try:
            d["themes_list"] = json.loads(d.get("themes") or "[]")
        except Exception:
            d["themes_list"] = []

        chunks = conn.execute(
            "SELECT chunk_index, source_type, content FROM chunks "
            "WHERE report_id=? ORDER BY chunk_index LIMIT 3",
            (report_id,),
        ).fetchall()
        d["chunks_preview"] = [dict(c) for c in chunks]
    except Exception as e:
        logger.error("api_db_report_detail error: %s", e, exc_info=True)
        return jsonify({"error": "Failed to load report detail"}), 500
    finally:
        conn.close()

    return jsonify(d)