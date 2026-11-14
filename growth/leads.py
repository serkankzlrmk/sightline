"""Consent-based lead capture for public acquisition surfaces.

Stored in the separate growth DB (same file as Search Console snapshots) so it
never mixes with chat/user tables. This phase captures and exports leads; it
does not send email.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

from config import GSC_DB_PATH

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    email        TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL DEFAULT '',
    organization TEXT NOT NULL DEFAULT '',
    source       TEXT NOT NULL DEFAULT '',
    utm_json     TEXT NOT NULL DEFAULT '{}',
    consent      INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leads_created ON leads(created_at);
"""


def _connection() -> sqlite3.Connection:
    path = Path(GSC_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def add_lead(
    email: str,
    *,
    name: str = "",
    organization: str = "",
    source: str = "",
    utm: dict | None = None,
    consent: bool = False,
) -> bool:
    """Upsert one consenting lead. Returns False for invalid input or no consent."""
    value = str(email or "").strip().lower()[:254]
    if not consent or not _EMAIL_RE.match(value):
        return False
    now = time.time()
    with _connection() as conn:
        conn.execute(
            """
            INSERT INTO leads (email, name, organization, source, utm_json, consent, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(email) DO UPDATE SET
                name=excluded.name,
                organization=excluded.organization,
                source=excluded.source,
                utm_json=excluded.utm_json,
                consent=excluded.consent,
                updated_at=excluded.updated_at
            """,
            (
                value,
                str(name or "").strip()[:120],
                str(organization or "").strip()[:160],
                str(source or "").strip()[:80],
                json.dumps(utm or {}),
                1,
                now,
                now,
            ),
        )
        conn.commit()
    return True


def list_leads(limit: int = 200) -> list[dict]:
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, email, name, organization, source, utm_json, created_at "
            "FROM leads ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
    return [dict(r) for r in rows]


def count_leads() -> int:
    with _connection() as conn:
        return int(conn.execute("SELECT COUNT(*) AS n FROM leads").fetchone()["n"])
