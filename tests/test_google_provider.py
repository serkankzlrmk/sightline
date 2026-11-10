"""Google Gemini provider wiring tests (no live API calls)."""


def test_provider_model_name_mapping():
    from config import model_available_for_provider, provider_model_name

    assert provider_model_name("google/gemini-3.8-flash", "google") == "gemini-3.8-flash"
    assert provider_model_name("google/gemini-3.8-flash", "openrouter") == "google/gemini-3.8-flash"
    assert provider_model_name("deepseek/deepseek-chat", "google") == "deepseek/deepseek-chat"
    assert model_available_for_provider("google/gemini-3.8-flash", "google") is True
    assert model_available_for_provider("openai/gpt-5.1", "google") is False
    assert model_available_for_provider("openai/gpt-5.1", "openrouter") is True


def test_sitrep_google_headers(monkeypatch):
    import sitrep.llm_client as lc

    monkeypatch.setattr(lc, "LLM_PROVIDER", "google")
    monkeypatch.setattr(lc, "_LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
    monkeypatch.setattr(lc, "_LLM_API_KEY", "test-key")
    base, headers = lc._get_base_url_and_headers()
    assert base.endswith("/v1beta/openai")
    assert headers["Authorization"] == "Bearer test-key"
    assert "HTTP-Referer" not in headers


def test_google_connectivity_uses_key(monkeypatch):
    import agent.model as model_mod

    class FakeResponse:
        status_code = 200

    class FakeRequests:
        @staticmethod
        def get(url, headers=None, timeout=None):
            assert "generativelanguage.googleapis.com" in url
            assert headers["Authorization"] == "Bearer google-test"
            return FakeResponse()

    monkeypatch.setattr(model_mod.config, "LLM_PROVIDER", "google")
    monkeypatch.setattr(model_mod.config, "GOOGLE_API_KEY", "google-test")
    monkeypatch.setattr(model_mod.config, "GOOGLE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
    monkeypatch.setattr(model_mod, "requests", FakeRequests)
    assert model_mod.check_llm_connectivity(max_retries=1, retry_delay=0) is True
