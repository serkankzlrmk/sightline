"""Read-only Google Search Console snapshots for the admin growth dashboard."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

READONLY_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


def _connection(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS gsc_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fetched_at TEXT NOT NULL,
            site_url TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            clicks REAL NOT NULL DEFAULT 0,
            impressions REAL NOT NULL DEFAULT 0,
            ctr REAL NOT NULL DEFAULT 0,
            position REAL NOT NULL DEFAULT 0,
            row_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS gsc_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            query TEXT NOT NULL DEFAULT '',
            page TEXT NOT NULL DEFAULT '',
            clicks REAL NOT NULL DEFAULT 0,
            impressions REAL NOT NULL DEFAULT 0,
            ctr REAL NOT NULL DEFAULT 0,
            position REAL NOT NULL DEFAULT 0,
            FOREIGN KEY(snapshot_id) REFERENCES gsc_snapshots(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_gsc_rows_snapshot ON gsc_rows(snapshot_id);
        CREATE INDEX IF NOT EXISTS idx_gsc_snapshots_fetched ON gsc_snapshots(fetched_at DESC);
        """
    )
    return conn


def _authorized_session(credentials_path: Path | str):
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.service_account import Credentials

    credentials = Credentials.from_service_account_file(
        str(credentials_path),
        scopes=[READONLY_SCOPE],
    )
    return AuthorizedSession(credentials)


def _search_analytics_query(session, site_url: str, body: dict) -> dict:
    encoded_site = quote(site_url, safe="")
    endpoint = f"https://www.googleapis.com/webmasters/v3/sites/{encoded_site}/searchAnalytics/query"
    response = session.post(endpoint, json=body, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Search Console returned an invalid response")
    return payload


def sync_search_console(
    *,
    now: datetime | None = None,
    session=None,
    site_url: str | None = None,
    credentials_path: Path | str | None = None,
    db_path: Path | str | None = None,
    lookback_days: int | None = None,
    data_lag_days: int | None = None,
    row_limit: int | None = None,
) -> dict:
    """Fetch finalized web-search totals and top query/page pairs."""
    from config import (
        GSC_CREDENTIALS_PATH,
        GSC_DATA_LAG_DAYS,
        GSC_DB_PATH,
        GSC_ENABLED,
        GSC_LOOKBACK_DAYS,
        GSC_ROW_LIMIT,
        GSC_SITE_URL,
    )

    if session is None and not GSC_ENABLED:
        return {"status": "disabled"}

    selected_site = (site_url or GSC_SITE_URL).strip()
    selected_db = Path(db_path or GSC_DB_PATH)
    selected_credentials = Path(credentials_path or GSC_CREDENTIALS_PATH) if (credentials_path or GSC_CREDENTIALS_PATH) else None
    days = max(1, int(lookback_days or GSC_LOOKBACK_DAYS))
    lag = max(0, int(data_lag_days if data_lag_days is not None else GSC_DATA_LAG_DAYS))
    limit = min(25000, max(1, int(row_limit or GSC_ROW_LIMIT)))

    if not selected_site:
        raise RuntimeError("GSC_SITE_URL is not configured")
    if session is None:
        if not selected_credentials or not selected_credentials.is_file():
            raise RuntimeError("GSC credentials file is not available")
        session = _authorized_session(selected_credentials)

    current = now or datetime.now(UTC)
    end_date = current.date() - timedelta(days=lag)
    start_date = end_date - timedelta(days=days - 1)
    base_body = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "type": "web",
        "dataState": "final",
    }
    total_payload = _search_analytics_query(
        session,
        selected_site,
        {**base_body, "aggregationType": "byProperty"},
    )
    detail_payload = _search_analytics_query(
        session,
        selected_site,
        {
            **base_body,
            "dimensions": ["query", "page"],
            "aggregationType": "auto",
            "rowLimit": limit,
        },
    )

    total_rows = total_payload.get("rows") or []
    totals = total_rows[0] if total_rows and isinstance(total_rows[0], dict) else {}
    detail_rows = [row for row in (detail_payload.get("rows") or []) if isinstance(row, dict)]
    fetched_at = current.astimezone(UTC).isoformat()

    conn = _connection(selected_db)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO gsc_snapshots
                    (fetched_at, site_url, start_date, end_date, clicks, impressions, ctr, position, row_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fetched_at,
                    selected_site,
                    start_date.isoformat(),
                    end_date.isoformat(),
                    float(totals.get("clicks") or 0),
                    float(totals.get("impressions") or 0),
                    float(totals.get("ctr") or 0),
                    float(totals.get("position") or 0),
                    len(detail_rows),
                ),
            )
            snapshot_id = int(cursor.lastrowid)
            for row in detail_rows:
                keys = row.get("keys") or []
                query_value = str(keys[0]) if len(keys) > 0 else ""
                page_value = str(keys[1]) if len(keys) > 1 else ""
                conn.execute(
                    """
                    INSERT INTO gsc_rows
                        (snapshot_id, query, page, clicks, impressions, ctr, position)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        query_value,
                        page_value,
                        float(row.get("clicks") or 0),
                        float(row.get("impressions") or 0),
                        float(row.get("ctr") or 0),
                        float(row.get("position") or 0),
                    ),
                )
    finally:
        conn.close()

    return {
        "status": "completed",
        "snapshot_id": snapshot_id,
        "site_url": selected_site,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "row_count": len(detail_rows),
        "clicks": float(totals.get("clicks") or 0),
        "impressions": float(totals.get("impressions") or 0),
    }


def _ranked_rows(conn: sqlite3.Connection, snapshot_id: int, dimension: str, limit: int) -> list[dict]:
    if dimension not in {"query", "page"}:
        raise ValueError("Unsupported Search Console dimension")
    rows = conn.execute(
        f"""
        SELECT {dimension} AS value,
               SUM(clicks) AS clicks,
               SUM(impressions) AS impressions,
               CASE WHEN SUM(impressions) > 0 THEN SUM(clicks) / SUM(impressions) ELSE 0 END AS ctr,
               CASE WHEN SUM(impressions) > 0
                    THEN SUM(position * impressions) / SUM(impressions)
                    ELSE 0 END AS position
        FROM gsc_rows
        WHERE snapshot_id = ? AND {dimension} != ''
        GROUP BY {dimension}
        ORDER BY clicks DESC, impressions DESC
        LIMIT ?
        """,
        (snapshot_id, limit),
    ).fetchall()
    return [
        {
            "value": row["value"],
            "clicks": row["clicks"],
            "impressions": row["impressions"],
            "ctr": row["ctr"],
            "position": row["position"],
        }
        for row in rows
    ]


def get_search_console_dashboard(db_path: Path | str | None = None, limit: int = 10) -> dict:
    from config import GSC_DB_PATH, GSC_ENABLED, GSC_SITE_URL

    selected_db = Path(db_path or GSC_DB_PATH)
    base = {
        "configured": GSC_ENABLED,
        "site_url": GSC_SITE_URL,
        "status": "disabled" if not GSC_ENABLED else "awaiting_first_sync",
        "snapshot": None,
        "top_queries": [],
        "top_pages": [],
    }
    if not selected_db.is_file():
        return base

    conn = _connection(selected_db)
    try:
        snapshot = conn.execute("SELECT * FROM gsc_snapshots ORDER BY fetched_at DESC LIMIT 1").fetchone()
        if not snapshot:
            return base
        snapshot_data = dict(snapshot)
        base.update(
            {
                "status": "ready",
                "snapshot": snapshot_data,
                "top_queries": _ranked_rows(conn, snapshot["id"], "query", limit),
                "top_pages": _ranked_rows(conn, snapshot["id"], "page", limit),
            }
        )
        return base
    finally:
        conn.close()
