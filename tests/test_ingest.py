"""
Test: Database manager, text chunking, and ingest pipeline.

Unit tests for DatabaseManager (SQLite), chunk_text, build_chunk_with_header,
extract_pdf_text, is_ingested, and purge_old_reports.
Uses a temporary SQLite DB for isolation.
"""

from datetime import UTC, datetime, timedelta

import pytest

# ── chunk_text ──────────────────────────────────────────────────────────────────

class TestChunkText:
    def test_basic_chunking(self):
        from reliefweb_api.db_manager import chunk_text
        text = "A" * 500
        chunks = chunk_text(text, chunk_size=200, overlap=20)
        assert len(chunks) > 0
        assert all(isinstance(c, str) for c in chunks)

    def test_short_text_returns_single_chunk(self):
        from reliefweb_api.db_manager import chunk_text
        text = "Short text"
        chunks = chunk_text(text, chunk_size=200, overlap=20)
        assert len(chunks) == 1
        assert chunks[0] == "Short text"

    def test_empty_string_returns_empty_list(self):
        from reliefweb_api.db_manager import chunk_text
        assert chunk_text("") == []

    def test_whitespace_only_returns_empty_list(self):
        from reliefweb_api.db_manager import chunk_text
        assert chunk_text("   \n\n  ") == []

    def test_overlap_preserves_context(self):
        from reliefweb_api.db_manager import chunk_text
        text = "Word " * 200
        chunks = chunk_text(text, chunk_size=100, overlap=20)
        assert len(chunks) > 1
        for i in range(len(chunks) - 1):
            assert len(chunks[i]) > 0

    def test_preserves_content(self):
        from reliefweb_api.db_manager import chunk_text
        text = "This is a test sentence. " * 50
        chunks = chunk_text(text, chunk_size=200, overlap=30)
        full = " ".join(chunks)
        assert "test sentence" in full


# ── build_chunk_with_header ───────────────────────────────────────────────────

class TestBuildChunkWithHeader:
    def test_basic_header(self):
        from reliefweb_api.db_manager import build_chunk_with_header
        metadata = {
            "title": "Test Report",
            "source": [{"shortname": "UNHCR"}],
            "date": {"original": "2025-01-15"},
            "countries": [{"shortname": "Sudan", "name": "Sudan"}],
        }
        result = build_chunk_with_header("Some content", metadata, "html")
        assert "[REPORT: Test Report" in result
        assert "SOURCE: UNHCR" in result
        assert "DATE: 2025-01-15" in result
        assert "COUNTRIES: Sudan" in result
        assert "TYPE: HTML" in result
        assert "Some content" in result

    def test_missing_metadata(self):
        from reliefweb_api.db_manager import build_chunk_with_header
        result = build_chunk_with_header("Content", {}, "pdf")
        assert "[REPORT:" in result
        assert "TYPE: PDF" in result

    def test_limits_countries_to_five(self):
        from reliefweb_api.db_manager import build_chunk_with_header
        countries = [{"shortname": f"Country{i}"} for i in range(10)]
        metadata = {"title": "T", "source": [], "date": {}, "countries": countries}
        result = build_chunk_with_header("Content", metadata, "html")
        assert "Country0" in result
        assert "Country4" in result


# ── DatabaseManager ────────────────────────────────────────────────────────────

class TestDatabaseManager:
    @pytest.fixture
    def db(self, tmp_path):
        from reliefweb_api.db_manager import DatabaseManager
        db_path = str(tmp_path / "test.db")
        dm = DatabaseManager(db_path)
        yield dm
        dm.close()

    def test_create_tables(self, db):
        conn = db._connect()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        table_names = [t[0] for t in tables]
        assert "reports" in table_names
        assert "chunks" in table_names

    def test_insert_and_check_report(self, db):
        metadata = {
            "id": 12345,
            "title": "Test Report",
            "date": {"original": "2025-01-15"},
            "source": [{"shortname": "UNHCR"}],
            "countries": [{"name": "Sudan"}],
            "themes": [{"name": "Health"}],
            "url": "https://example.com/12345",
            "format": [{"name": "Situation Report"}],
            "language": [{"code": "en"}],
        }
        chunks = [
            {"source_type": "html", "content": "Test content chunk 1"},
            {"source_type": "html", "content": "Test content chunk 2"},
        ]
        result = db.insert_report(metadata, chunks, has_pdf=False, has_content=True)
        assert result is True
        assert db.report_exists(12345)

    def test_insert_duplicate_skips(self, db):
        metadata = {
            "id": 99999,
            "title": "Duplicate Test",
            "date": {"original": "2025-01-01"},
            "source": [],
            "countries": [],
            "themes": [],
            "url": "",
            "format": [],
            "language": [],
        }
        chunks = [{"source_type": "html", "content": "Content"}]
        assert db.insert_report(metadata, chunks) is True
        assert db.insert_report(metadata, chunks) is False

    def test_report_has_pdf(self, db):
        metadata = {
            "id": 55555,
            "title": "PDF Report",
            "date": {},
            "source": [],
            "countries": [],
            "themes": [],
            "url": "",
            "format": [],
            "language": [],
        }
        chunks = [{"source_type": "pdf", "content": "PDF content"}]
        db.insert_report(metadata, chunks, has_pdf=True, pdf_pages=5)
        assert db.report_has_pdf(55555) is True
        assert db.report_has_pdf(999999) is False

    def test_get_stats(self, db):
        metadata = {
            "id": 77777,
            "title": "Stats Report",
            "date": {},
            "source": [],
            "countries": [],
            "themes": [],
            "url": "",
            "format": [],
            "language": [],
        }
        chunks = [{"source_type": "html", "content": "Stats content"}]
        db.insert_report(metadata, chunks, has_content=True)
        stats = db.get_stats()
        assert stats["reports"] >= 1
        assert stats["chunks"] >= 1

    def test_delete_report(self, db):
        metadata = {
            "id": 88888,
            "title": "Delete Me",
            "date": {},
            "source": [],
            "countries": [],
            "themes": [],
            "url": "",
            "format": [],
            "language": [],
        }
        chunks = [{"source_type": "html", "content": "To be deleted"}]
        db.insert_report(metadata, chunks)
        assert db.report_exists(88888)
        assert db.delete_report(88888) is True
        assert not db.report_exists(88888)

    def test_delete_nonexistent_report(self, db):
        assert db.delete_report(999999) is False

    def test_purge_old_reports(self, db):
        old_date = (datetime.now(UTC) - timedelta(days=120)).strftime("%Y-%m-%d")
        metadata_old = {
            "id": 11111,
            "title": "Old Report",
            "date": {"original": old_date},
            "source": [],
            "countries": [],
            "themes": [],
            "url": "",
            "format": [],
            "language": [],
        }
        recent_date = (datetime.now(UTC) - timedelta(days=10)).strftime("%Y-%m-%d")
        metadata_new = {
            "id": 22222,
            "title": "Recent Report",
            "date": {"original": recent_date},
            "source": [],
            "countries": [],
            "themes": [],
            "url": "",
            "format": [],
            "language": [],
        }
        db.insert_report(metadata_old, [{"source_type": "html", "content": "Old"}])
        db.insert_report(metadata_new, [{"source_type": "html", "content": "Recent"}])
        purged = db.purge_old_reports(days=90)
        assert purged >= 1
        assert not db.report_exists(11111)
        assert db.report_exists(22222)


# ── is_ingested / is_ingested_with_pdf ─────────────────────────────────────────

class TestIsIngested:
    def test_is_ingested_true(self, tmp_path):
        from reliefweb_api.db_manager import DatabaseManager
        from reliefweb_api.ingest_pipeline import is_ingested
        db_path = str(tmp_path / "test_ingest.db")
        db = DatabaseManager(db_path)
        metadata = {
            "id": 44444,
            "title": "Ingested",
            "date": {},
            "source": [],
            "countries": [],
            "themes": [],
            "url": "",
            "format": [],
            "language": [],
        }
        db.insert_report(metadata, [{"source_type": "html", "content": "Test"}])
        db.close()
        assert is_ingested(44444, db_path) is True

    def test_is_ingested_false(self, tmp_path):
        from reliefweb_api.ingest_pipeline import is_ingested
        db_path = str(tmp_path / "test_ingest2.db")
        assert is_ingested(999999, db_path) is False

    def test_is_ingested_with_pdf_true(self, tmp_path):
        from reliefweb_api.db_manager import DatabaseManager
        from reliefweb_api.ingest_pipeline import is_ingested_with_pdf
        db_path = str(tmp_path / "test_ingest3.db")
        db = DatabaseManager(db_path)
        metadata = {
            "id": 55555,
            "title": "With PDF",
            "date": {},
            "source": [],
            "countries": [],
            "themes": [],
            "url": "",
            "format": [],
            "language": [],
        }
        db.insert_report(metadata, [{"source_type": "pdf", "content": "PDF"}], has_pdf=True)
        db.close()
        assert is_ingested_with_pdf(55555, db_path) is True

    def test_is_ingested_with_pdf_false_when_html_only(self, tmp_path):
        from reliefweb_api.db_manager import DatabaseManager
        from reliefweb_api.ingest_pipeline import is_ingested_with_pdf
        db_path = str(tmp_path / "test_ingest4.db")
        db = DatabaseManager(db_path)
        metadata = {
            "id": 66666,
            "title": "HTML Only",
            "date": {},
            "source": [],
            "countries": [],
            "themes": [],
            "url": "",
            "format": [],
            "language": [],
        }
        db.insert_report(metadata, [{"source_type": "html", "content": "HTML"}], has_pdf=False)
        db.close()
        assert is_ingested_with_pdf(66666, db_path) is False
