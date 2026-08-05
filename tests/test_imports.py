"""
Test: All core modules can be imported without errors.

This catches broken imports, missing dependencies, and syntax errors
that would otherwise only surface at runtime.
"""


def test_import_config():
    from config import config

    assert config is not None


def test_import_auth():
    import auth

    assert auth is not None


def test_import_server():
    import server

    assert server is not None


def test_import_db_manager():
    from reliefweb_api.db_manager import DatabaseManager

    assert DatabaseManager is not None


def test_import_vector_store():
    from reliefweb_api.vector_store import VectorStore

    assert VectorStore is not None


def test_import_ingest_pipeline():
    from reliefweb_api.ingest_pipeline import ingest_from_api

    assert callable(ingest_from_api)


def test_import_reliefweb():
    from reliefweb_api.reliefweb import search_knowledge_base, search_sitreps

    assert search_sitreps is not None
    assert search_knowledge_base is not None


def test_import_agent_model():
    from agent.model import ModelInitializationError

    assert ModelInitializationError is not None


def test_import_download_manager():
    from reliefweb_api.download_manager import DownloadManager

    assert DownloadManager is not None


def test_import_pdf_converter():
    from reliefweb_api.pdf_converter import PDFConverter

    assert PDFConverter is not None
