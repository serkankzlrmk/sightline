"""
Test: SQL tool security — read-only enforcement, PII redaction, no chats.db access.

These tests verify the sql_query tool's security boundaries:
1. Only SELECT/WITH queries are allowed
2. Forbidden keywords (INSERT, DROP, etc.) are rejected
3. PII columns (uid, email, token) are redacted from results
4. The database parameter is removed (no chats.db access)
5. Results are capped at 50 rows
"""

import inspect
import sqlite3
from pathlib import Path

import pytest


# ── Helper: create a temp database with sample data ──────────────────────────

def _create_test_db(path: Path, table_name: str = "reports"):
    """Create a temporary SQLite database with test data."""
    conn = sqlite3.connect(str(path))
    c = conn.cursor()
    c.execute(f"""
        CREATE TABLE {table_name} (
            id INTEGER PRIMARY KEY,
            title TEXT,
            country TEXT,
            source TEXT,
            date TEXT
        )
    """)
    for i in range(60):
        c.execute(
            f"INSERT INTO {table_name} (title, country, source, date) VALUES (?, ?, ?, ?)",
            (f"Report {i}", "Sudan" if i % 3 == 0 else "Ukraine", "UNHCR", f"2024-01-{i % 28 + 1:02d}"),
        )
    conn.commit()
    conn.close()


def _create_test_db_with_pii(path: Path):
    """Create a database with PII columns to test redaction."""
    conn = sqlite3.connect(str(path))
    c = conn.cursor()
    c.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            uid TEXT,
            email TEXT,
            name TEXT,
            token TEXT
        )
    """)
    c.execute("INSERT INTO users (uid, email, name, token) VALUES (?, ?, ?, ?)",
              ("secret-uid-123", "user@test.com", "John Doe", "secret-token-abc"))
    conn.commit()
    conn.close()


# ── Test: SELECT-only enforcement ─────────────────────────────────────────────

class TestSQLReadOnly:
    """Verify that only SELECT and WITH queries are allowed."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path):
        """Create a test database and patch the DB path."""
        self.db_path = tmp_path / "test_reports.db"
        _create_test_db(self.db_path)
        import reliefweb_api.sql_tools as mod
        self._orig_db_path = mod._DB_PATH
        mod._DB_PATH = str(self.db_path)
        yield
        mod._DB_PATH = self._orig_db_path

    def test_select_allowed(self):
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "SELECT COUNT(*) FROM reports"})
        assert "Error" not in result
        assert "60" in result

    def test_with_allowed(self):
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "WITH counts AS (SELECT country, COUNT(*) as cnt FROM reports GROUP BY country) SELECT * FROM counts"})
        assert "Error" not in result

    def test_insert_rejected(self):
        """INSERT starts with a forbidden keyword — rejected by both checks."""
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "INSERT INTO reports (title) VALUES ('hacked')"})
        assert "Error" in result

    def test_update_rejected(self):
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "UPDATE reports SET title='hacked' WHERE id=1"})
        assert "Error" in result

    def test_delete_rejected(self):
        """DELETE doesn't start with SELECT/WITH, so it's caught by the first check."""
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "DELETE FROM reports WHERE id=1"})
        assert "Error" in result
        assert "Only SELECT" in result or "read-only" in result.lower()

    def test_drop_rejected(self):
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "DROP TABLE reports"})
        assert "Error" in result
        assert "Only SELECT" in result or "read-only" in result.lower()

    def test_alter_rejected(self):
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "ALTER TABLE reports ADD COLUMN hacked TEXT"})
        assert "Error" in result
        assert "Only SELECT" in result or "read-only" in result.lower()

    def test_create_rejected(self):
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "CREATE TABLE hacked (id INTEGER)"})
        assert "Error" in result
        assert "Only SELECT" in result or "read-only" in result.lower()

    def test_attach_rejected(self):
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "ATTACH DATABASE '/tmp/hacked.db' AS hacked"})
        assert "Error" in result
        assert "Only SELECT" in result or "read-only" in result.lower()

    def test_pragma_rejected(self):
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "PRAGMA table_info(reports)"})
        assert "Error" in result
        assert "Only SELECT" in result or "read-only" in result.lower()

    def test_select_with_forbidden_keyword_inside(self):
        """SELECT query containing DROP inside a string should be caught."""
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "SELECT * FROM reports WHERE title = 'DROP TABLE'"})
        assert "Forbidden keyword" in result

    def test_sql_injection_union_rejected_if_not_select(self):
        """A DROP disguised inside a SELECT should still be caught."""
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "SELECT * FROM reports; DROP TABLE reports"})
        assert "Forbidden keyword" in result or "Error" in result


# ── Test: PII redaction ──────────────────────────────────────────────────────

class TestSQLPIIRedaction:
    """Verify that PII columns are redacted from results."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path):
        self.db_path = tmp_path / "test_reports.db"
        _create_test_db_with_pii(self.db_path)
        import reliefweb_api.sql_tools as mod
        self._orig_db_path = mod._DB_PATH
        mod._DB_PATH = str(self.db_path)
        yield
        mod._DB_PATH = self._orig_db_path

    def test_uid_redacted(self):
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "SELECT uid, name FROM users"})
        assert "[REDACTED]" in result
        assert "secret-uid-123" not in result

    def test_email_redacted(self):
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "SELECT email, name FROM users"})
        assert "[REDACTED]" in result
        assert "user@test.com" not in result

    def test_token_redacted(self):
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "SELECT token, name FROM users"})
        assert "[REDACTED]" in result
        assert "secret-token-abc" not in result

    def test_non_pii_columns_visible(self):
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "SELECT name FROM users"})
        assert "John Doe" in result

    def test_star_query_redacts_pii(self):
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "SELECT * FROM users"})
        assert "[REDACTED]" in result
        assert "secret-uid-123" not in result
        assert "user@test.com" not in result


# ── Test: Result limiting ────────────────────────────────────────────────────

class TestSQLResultLimiting:
    """Verify that results are capped at 50 rows."""

    @pytest.fixture(autouse=True)
    def _setup_db(self, tmp_path):
        self.db_path = tmp_path / "test_reports.db"
        _create_test_db(self.db_path)
        import reliefweb_api.sql_tools as mod
        self._orig_db_path = mod._DB_PATH
        mod._DB_PATH = str(self.db_path)
        yield
        mod._DB_PATH = self._orig_db_path

    def test_results_capped_at_50(self):
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "SELECT * FROM reports"})
        assert "50 row" in result
        assert "truncated" in result

    def test_small_result_not_truncated(self):
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "SELECT * FROM reports WHERE country='Ukraine' LIMIT 5"})
        assert "truncated" not in result


# ── Test: No database parameter ──────────────────────────────────────────────

class TestSQLNoDatabaseParam:
    """Verify that the database parameter has been removed (no chats.db access)."""

    def test_tool_has_no_database_param(self):
        """The sql_query tool should NOT accept a database parameter."""
        from reliefweb_api.sql_tools import sql_query
        schema = sql_query.args_schema
        fields = schema.model_fields
        assert "query" in fields, "sql_query should have a 'query' parameter"
        assert "database" not in fields, "sql_query should NOT have a 'database' parameter"

    def test_no_chats_db_access(self):
        """Even if someone tries to query chats tables, they won't find them in reliefweb.db."""
        from reliefweb_api.sql_tools import sql_query
        result = sql_query.invoke({"query": "SELECT * FROM chats"})
        assert "Error" in result or "no such table" in result.lower()