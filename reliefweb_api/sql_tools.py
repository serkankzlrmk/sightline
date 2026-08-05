"""
sql_tools.py — Read-only SQL query tool for the Sightline agent.

Provides a single @tool function that lets the agent run read-only SQL queries
against the reliefweb.db SQLite database. SELECT-only enforcement, 5s timeout.

This is a custom alternative to mcp-server-sqlite — simpler, safer, no subprocess.
"""

import logging
import re
import sqlite3
import time
from pathlib import Path

from langchain.tools import tool

logger = logging.getLogger(__name__)

# Read-only SQL keywords that are ALLOWED (case-insensitive)
_SELECT_ONLY_PATTERN = re.compile(
    r"^\s*(SELECT|WITH)\s",
    re.IGNORECASE,
)

# Dangerous keywords that must NEVER appear in a query
_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|PRAGMA|VACUUM|REINDEX)\b",
    re.IGNORECASE,
)

# Default DB path — resolved lazily to avoid import-time config dependency
_DB_PATH = None


def _get_db_path():
    """Lazily resolve the DB path from config."""
    global _DB_PATH
    if _DB_PATH is None:
        try:
            from config import DB_PATH

            _DB_PATH = str(DB_PATH)
        except Exception:
            _DB_PATH = "reliefweb.db"
    return _DB_PATH


@tool
def sql_query(query: str, database: str = "reports") -> str:
    """Run a read-only SQL query on the Sightline database.

    Useful for quantitative questions about the report database:
    - "How many reports per country?"
    - "What's the date range of Chad reports?"
    - "Which sources have the most reports?"

    Args:
        query: A SELECT or WITH SQL query. Only read-only queries are allowed.
               INSERT/UPDATE/DELETE/DROP/ALTER/CREATE will be rejected.
        database: Which database to query: 'reports' (reliefweb.db, default) or
                  'chats' (chats.db with events/users/chats tables).

    Returns query results as a formatted table (first 50 rows max).
    """
    # Validate: only SELECT or WITH allowed
    if not _SELECT_ONLY_PATTERN.match(query):
        return "Error: Only SELECT or WITH queries are allowed. Read-only access only."

    # Check for forbidden keywords
    forbidden_match = _FORBIDDEN_KEYWORDS.search(query)
    if forbidden_match:
        return (
            f"Error: Forbidden keyword '{forbidden_match.group()}' detected. Only read-only SELECT queries are allowed."
        )

    # Resolve DB path
    if database == "chats":
        from server import CHATS_DB_PATH

        db_path = str(CHATS_DB_PATH)
    else:
        db_path = _get_db_path()

    if not Path(db_path).exists():
        return f"Error: Database file not found: {db_path}"

    # Execute with timeout
    try:
        # Open in read-only mode (uri=True + mode=ro)
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            timeout=5,
        )
        conn.row_factory = sqlite3.Row

        # Set a busy timeout
        conn.execute("PRAGMA busy_timeout=5000")

        start = time.time()
        cursor = conn.execute(query)

        # Fetch max 50 rows
        rows = cursor.fetchmany(50)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        elapsed = time.time() - start

        conn.close()

        if not rows:
            return "Query returned 0 rows."

        # Format as a simple table
        header = " | ".join(columns)
        separator = "-+-".join("-" * len(c) for c in columns)
        lines = [header, separator]
        for row in rows[:50]:
            lines.append(" | ".join(str(row[c] if c in row.keys() else row[i]) for i, c in enumerate(columns)))

        result = "\n".join(lines)
        result += f"\n\n({len(rows)} row(s) shown, {elapsed:.2f}s)"
        if len(rows) == 50:
            result += " — result may be truncated to 50 rows"
        return result

    except sqlite3.OperationalError as e:
        return f"SQL Error: {e}"
    except sqlite3.DatabaseError as e:
        return f"Database Error: {e}"
    except Exception as e:
        return f"Error: {e}"


SQL_TOOLS = [sql_query]
