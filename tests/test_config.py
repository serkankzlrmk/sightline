"""
Test: Configuration validation.

Ensures config values are sensible and required settings exist.
"""

import pytest


def test_config_has_llm_provider():
    """LLM_PROVIDER must be set to a valid value."""
    from config import config
    assert config.LLM_PROVIDER in ("openrouter", "ollama"), \
        f"Invalid LLM_PROVIDER: {config.LLM_PROVIDER}"


def test_config_has_model_name():
    """Active model name must not be empty."""
    from config import config
    assert config.OLLAMA_MODEL, "OLLAMA_MODEL is empty"


def test_config_server_port_valid():
    """Server port must be a positive integer."""
    from config import config
    assert isinstance(config.SERVER_PORT, int), "SERVER_PORT is not int"
    assert config.SERVER_PORT > 0, f"SERVER_PORT must be > 0, got {config.SERVER_PORT}"


def test_config_chunk_size_valid():
    """Chunk size must be positive."""
    from reliefweb_api.db_manager import CHUNK_SIZE, CHUNK_OVERLAP
    assert CHUNK_SIZE > 0, f"CHUNK_SIZE must be > 0, got {CHUNK_SIZE}"
    assert CHUNK_OVERLAP >= 0, f"CHUNK_OVERLAP must be >= 0, got {CHUNK_OVERLAP}"
    assert CHUNK_OVERLAP < CHUNK_SIZE, "CHUNK_OVERLAP must be < CHUNK_SIZE"


def test_chunk_text_function():
    """chunk_text produces non-empty output for non-empty input."""
    from reliefweb_api.db_manager import chunk_text
    result = chunk_text("This is a test sentence. " * 50)
    assert len(result) > 0, "chunk_text returned empty list"
    assert all(isinstance(c, str) for c in result), "chunks must be strings"


def test_chunk_text_empty_input():
    """chunk_text returns empty list for empty input."""
    from reliefweb_api.db_manager import chunk_text
    assert chunk_text("") == []
    assert chunk_text("   ") == []