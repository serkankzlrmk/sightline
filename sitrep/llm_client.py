"""
sitrep_pipeline/llm_client.py
LLM wrapper — OpenRouter / Ollama (OpenAI-compatible API).
"""

import time
import logging
from typing import List, Dict, Optional

import requests

from config import (
    LLM_PROVIDER,
    _LLM_BASE_URL,
    _LLM_API_KEY,
    OLLAMA_BASE_URL,
    OLLAMA_API_KEY,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS_DEFAULT,
    LLM_TIMEOUT,
    LLM_MAX_RETRIES,
)

logger = logging.getLogger(__name__)

_RATE_LIMIT_WAIT = 10


def _get_base_url_and_headers() -> tuple[str, dict]:
    """LLM provider base URL and HTTP headers."""
    headers = {"Content-Type": "application/json"}
    
    if LLM_PROVIDER == "openrouter":
        headers["Authorization"] = f"Bearer {_LLM_API_KEY}"
        headers["HTTP-Referer"] = "https://reliefagent.org"
        headers["X-Title"] = "ReliefAgent"
        return _LLM_BASE_URL, headers
    else:
        if OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
        return OLLAMA_BASE_URL, headers


def chat(
    messages: List[Dict[str, str]],
    model: str = LLM_MODEL,
    temperature: float = LLM_TEMPERATURE,
    max_tokens: int = LLM_MAX_TOKENS_DEFAULT,
) -> str:
    """
    Ollama /chat/completions endpoint'ini cagirir.

    Args:
        messages : [{"role": "system"|"user"|"assistant", "content": str}, ...]
        model    : Model ID
        temperature: 0.0 = deterministik
        max_tokens : Yanit icin max token

    Returns:
        Modelin yanit metni (string).

    Raises:
        RuntimeError: Tum retry'lar tukendikten sonra ulasilamazsa.
    """
    base_url, headers = _get_base_url_and_headers()

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "think": False,
    }

    last_error: Optional[Exception] = None

    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            response = requests.post(
                url=f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=LLM_TIMEOUT,
            )

            if response.status_code == 429:
                wait = _RATE_LIMIT_WAIT * attempt
                logger.warning(
                    "Rate limit (429). Deneme %d/%d. %ds bekleniyor.",
                    attempt, LLM_MAX_RETRIES, wait,
                )
                time.sleep(wait)
                continue

            response.raise_for_status()

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if content is None:
                finish_reason = data["choices"][0].get("finish_reason", "unknown")
                raise RuntimeError(
                    f"LLM null content döndürdü (finish_reason={finish_reason}). "
                    "Prompt çok uzun olabilir veya model bunu desteklemiyor olabilir."
                )
            # qwen3 ve benzeri reasoning modelleri <think>...</think> bloğu ekler — temizle
            import re as _re
            content = _re.sub(r"<think>.*?</think>", "", content, flags=_re.DOTALL).strip()
            return content.strip()

        except requests.exceptions.Timeout:
            last_error = TimeoutError(
                f"LLM isteği zaman aşımına uğradı ({LLM_TIMEOUT}s). "
                f"Deneme {attempt}/{LLM_MAX_RETRIES}."
            )
            logger.warning(str(last_error))
            time.sleep(2 * attempt)

        except requests.exceptions.RequestException as exc:
            last_error = exc
            logger.warning(
                "İstek hatası (deneme %d/%d): %s", attempt, LLM_MAX_RETRIES, exc
            )
            time.sleep(2 * attempt)

        except (KeyError, IndexError, RuntimeError) as exc:
            raw = response.text[:300] if "response" in dir() else "—"
            last_error = RuntimeError(
                f"LLM yanıtı ayrıştırılamadı: {exc}. Ham yanıt: {raw}"
            )
            logger.warning("Response error (attempt %d/%d): %s", attempt, LLM_MAX_RETRIES, exc)
            time.sleep(2 * attempt)
            continue

    raise RuntimeError(
        f"Ollama'e {LLM_MAX_RETRIES} denemede ulaşılamadı. "
        f"Son hata: {last_error}"
    )


def chat_simple(user_prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
    """
    Tek kullanıcı mesajı için kısayol.

    Args:
        user_prompt  : Kullanıcı mesajı
        system_prompt: Sistem talimatı (opsiyonel)
        **kwargs     : chat() fonksiyonuna iletilen ek parametreler (temperature, max_tokens vb.)
    """
    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    return chat(messages, **kwargs)
