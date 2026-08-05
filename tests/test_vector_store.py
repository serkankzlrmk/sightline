"""
Test: VectorStore (ChromaDB backend).

Uses a temporary directory for ChromaDB persistence to avoid
touching the production vector store.
"""

import pytest


class TestVectorStoreInit:
    def test_init_creates_collection(self, tmp_path):
        from reliefweb_api.vector_store import VectorStore

        vs = VectorStore(str(tmp_path / "chroma_test"))
        assert vs is not None

    def test_init_default_backend(self, tmp_path):
        from reliefweb_api.vector_store import VectorStore

        vs = VectorStore(str(tmp_path / "chroma_test2"))
        stats = vs.get_stats()
        assert "total_chunks" in stats
        assert stats["total_chunks"] == 0


class TestVectorStoreAddReport:
    @pytest.fixture
    def vs(self, tmp_path):
        from reliefweb_api.vector_store import VectorStore

        return VectorStore(str(tmp_path / "chroma_add"))

    def test_add_report_returns_count(self, vs):
        metadata = {
            "id": 10001,
            "title": "Test Vector Report",
            "date": {"original": "2025-01-15"},
            "source": [{"shortname": "WHO"}],
            "countries": [{"name": "Sudan"}],
            "themes": [{"name": "Health"}],
            "url": "https://example.com/10001",
            "format": [{"name": "Situation Report"}],
            "language": [{"code": "en"}],
        }
        chunks = [
            {
                "source_type": "html",
                "content": "This is test content for vector store testing about Sudan humanitarian crisis.",
            },
        ]
        count = vs.add_report(10001, chunks, metadata)
        assert count == 1

    def test_add_multiple_chunks(self, vs):
        metadata = {
            "id": 10002,
            "title": "Multi Chunk Report",
            "date": {"original": "2025-02-01"},
            "source": [{"shortname": "OCHA"}],
            "countries": [{"name": "Ukraine"}],
            "themes": [{"name": "Protection"}],
            "url": "",
            "format": [],
            "language": [],
        }
        chunks = [
            {"source_type": "html", "content": "First chunk about Ukraine humanitarian needs and protection concerns."},
            {"source_type": "pdf", "content": "Second chunk about displacement patterns in Ukraine conflict zones."},
        ]
        count = vs.add_report(10002, chunks, metadata)
        assert count == 2

    def test_report_exists_after_add(self, vs):
        metadata = {
            "id": 10003,
            "title": "Existence Check",
            "date": {},
            "source": [],
            "countries": [],
            "themes": [],
            "url": "",
            "format": [],
            "language": [],
        }
        chunks = [{"source_type": "html", "content": "Content for existence check report."}]
        vs.add_report(10003, chunks, metadata)
        assert vs.report_exists(10003) is True

    def test_report_not_exists(self, vs):
        assert vs.report_exists(999999) is False


class TestVectorStoreSearch:
    @pytest.fixture
    def vs_with_data(self, tmp_path):
        from reliefweb_api.vector_store import VectorStore

        vs = VectorStore(str(tmp_path / "chroma_search"))
        metadata = {
            "id": 20001,
            "title": "Sudan Crisis Report",
            "date": {"original": "2025-03-01"},
            "source": [{"shortname": "UNHCR"}],
            "countries": [{"name": "Sudan"}],
            "themes": [{"name": "Protection"}],
            "url": "https://example.com/20001",
            "format": [{"name": "Situation Report"}],
            "language": [{"code": "en"}],
        }
        chunks = [
            {
                "source_type": "html",
                "content": "Sudan faces severe humanitarian crisis with millions displaced and food insecurity affecting vast populations across the country.",
            },
        ]
        vs.add_report(20001, chunks, metadata)
        return vs

    def test_search_returns_results(self, vs_with_data):
        results = vs_with_data.search("Sudan humanitarian crisis", n_results=5)
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_search_result_structure(self, vs_with_data):
        results = vs_with_data.search("humanitarian crisis", n_results=5)
        if results:
            result = results[0]
            assert "report_id" in result
            assert "title" in result
            assert "similarity" in result

    def test_search_with_country_filter(self, vs_with_data):
        results = vs_with_data.search("crisis", n_results=5, country="Sudan")
        assert isinstance(results, list)

    def test_search_empty_query(self, vs_with_data):
        results = vs_with_data.search("", n_results=5)
        assert isinstance(results, list)


class TestVectorStoreStats:
    def test_stats_structure(self, tmp_path):
        from reliefweb_api.vector_store import VectorStore

        vs = VectorStore(str(tmp_path / "chroma_stats"))
        stats = vs.get_stats()
        assert "total_chunks" in stats
        assert isinstance(stats["total_chunks"], int)


class TestVectorStorePurge:
    @pytest.fixture
    def vs_with_data(self, tmp_path):
        from reliefweb_api.vector_store import VectorStore

        vs = VectorStore(str(tmp_path / "chroma_purge"))
        metadata = {
            "id": 30001,
            "title": "To Be Purged",
            "date": {},
            "source": [],
            "countries": [],
            "themes": [],
            "url": "",
            "format": [],
            "language": [],
        }
        chunks = [{"source_type": "html", "content": "Content that will be purged from the vector store."}]
        vs.add_report(30001, chunks, metadata)
        return vs

    def test_purge_by_report_ids(self, vs_with_data):
        purged = vs_with_data.purge_by_report_ids([30001])
        assert isinstance(purged, int)
        assert purged >= 0

    def test_purge_nonexistent_ids(self, vs_with_data):
        purged = vs_with_data.purge_by_report_ids([999999])
        assert purged == 0
