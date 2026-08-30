"""
Test: Configuration validation.

Ensures config values are sensible and required settings exist.
"""


def test_config_has_llm_provider():
    """LLM_PROVIDER must be set to a valid value."""
    from config import config

    assert config.LLM_PROVIDER in ("openrouter", "ollama"), f"Invalid LLM_PROVIDER: {config.LLM_PROVIDER}"


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
    from reliefweb_api.db_manager import CHUNK_OVERLAP, CHUNK_SIZE

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


class TestAnalyticsConfig:
    def test_analytics_id_env(self):
        """Fresh subprocess: GOOGLE_ANALYTICS_ID env must reach config.

        A brand-new interpreter is used so the env is read during the actual
        config module import — identical to how production loads it.
        """
        import os
        import subprocess
        import sys

        env = {**os.environ, "GOOGLE_ANALYTICS_ID": "G-ABC123"}
        out = subprocess.run(
            [sys.executable, "-c", "import config; print(config.GOOGLE_ANALYTICS_ID)"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == "G-ABC123"

    def test_analytics_id_default_empty(self):
        """Fresh subprocess without the env var: defaults to empty (analytics off)."""
        import os
        import subprocess
        import sys

        env = {k: v for k, v in os.environ.items() if k != "GOOGLE_ANALYTICS_ID"}
        out = subprocess.run(
            [sys.executable, "-c", "import config; print(repr(config.GOOGLE_ANALYTICS_ID))"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == "''"

    def test_adsense_client_env(self):
        """Fresh subprocess: GOOGLE_ADSENSE_CLIENT env must reach config."""
        import os
        import subprocess
        import sys

        env = {**os.environ, "GOOGLE_ADSENSE_CLIENT": "pub-123456"}
        out = subprocess.run(
            [sys.executable, "-c", "import config; print(config.GOOGLE_ADSENSE_CLIENT)"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        assert out.returncode == 0, out.stderr
        # 'pub-' form is normalized to the 'ca-pub-' prefix the loader needs.
        assert out.stdout.strip() == "ca-pub-123456"

    def test_adsense_client_default_empty(self):
        """Fresh subprocess without the env var: defaults to empty (ads off)."""
        import os
        import subprocess
        import sys

        env = {k: v for k, v in os.environ.items() if k != "GOOGLE_ADSENSE_CLIENT"}
        out = subprocess.run(
            [sys.executable, "-c", "import config; print(repr(config.GOOGLE_ADSENSE_CLIENT))"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == "''"
