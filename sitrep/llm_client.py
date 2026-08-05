"""
sitrep_pipeline/llm_client.py
LLM wrapper — OpenRouter / Ollama (OpenAI-compatible API).
"""

import logging
import time

import requests

from config import (
    _LLM_API_KEY,
    _LLM_BASE_URL,
    LLM_MAX_RETRIES,
    LLM_MAX_TOKENS_DEFAULT,
    LLM_MODEL,
    LLM_PROVIDER,
    LLM_TEMPERATURE,
    LLM_TIMEOUT,
    OLLAMA_API_KEY,
    OLLAMA_BASE_URL,
)

logger = logging.getLogger(__name__)

_RATE_LIMIT_WAIT = 10


def _get_base_url_and_headers() -> tuple[str, dict]:
    """LLM provider base URL and HTTP headers."""
    headers = {"Content-Type": "application/json"}

    if LLM_PROVIDER == "openrouter":
        headers["Authorization"] = f"Bearer {_LLM_API_KEY}"
        headers["HTTP-Referer"] = "https://sightline.io"
        headers["X-Title"] = "Sightline"
        return _LLM_BASE_URL, headers
    else:
        if OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
        return OLLAMA_BASE_URL, headers


def chat(
    messages: list[dict[str, str]],
    model: str = LLM_MODEL,
    temperature: float = LLM_TEMPERATURE,
    max_tokens: int = LLM_MAX_TOKENS_DEFAULT,
) -> str:
    """
    Calls the Ollama /chat/completions endpoint.

    Args:
        messages : [{"role": "system"|"user"|"assistant", "content": str}, ...]
        model    : Model ID
        temperature: 0.0 = deterministic
        max_tokens : Max tokens for the response

    Returns:
        The model's response text (string).

    Raises:
        RuntimeError: If unreachable after all retries are exhausted.
    """
    base_url, headers = _get_base_url_and_headers()

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "think": False,
    }

    last_error: Exception | None = None

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
                    "Rate limit (429). Attempt %d/%d. Waiting %ds.",
                    attempt,
                    LLM_MAX_RETRIES,
                    wait,
                )
                time.sleep(wait)
                continue

            response.raise_for_status()

            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if content is None:
                finish_reason = data["choices"][0].get("finish_reason", "unknown")
                raise RuntimeError(
                    f"LLM returned null content (finish_reason={finish_reason}). "
                    "Prompt may be too long or the model may not support this."
                )
            # qwen3 and similar reasoning models add a think block — clean it up
            import re as _re

            content = _re.sub(r"<think>.*?</think>", "", content, flags=_re.DOTALL).strip()
            return content.strip()

        except requests.exceptions.Timeout:
            last_error = TimeoutError(f"LLM request timed out ({LLM_TIMEOUT}s). Attempt {attempt}/{LLM_MAX_RETRIES}.")
            logger.warning(str(last_error))
            time.sleep(2 * attempt)

        except requests.exceptions.RequestException as exc:
            last_error = exc
            logger.warning("Request error (attempt %d/%d): %s", attempt, LLM_MAX_RETRIES, exc)
            time.sleep(2 * attempt)

        except (KeyError, IndexError, RuntimeError) as exc:
            raw = getattr(response, "text", "")[:300] if response is not None else "—"
            last_error = RuntimeError(f"Failed to parse LLM response: {exc}. Raw response: {raw}")
            logger.warning("Response error (attempt %d/%d): %s", attempt, LLM_MAX_RETRIES, exc)
            time.sleep(2 * attempt)
            continue

    raise RuntimeError(f"Could not reach LLM provider after {LLM_MAX_RETRIES} attempts. Last error: {last_error}")


def chat_simple(user_prompt: str, system_prompt: str | None = None, **kwargs) -> str:
    """
    Shortcut for a single user message.

    Args:
        user_prompt  : User message
        system_prompt: System instruction (optional)
        **kwargs     : Additional parameters passed to chat() (temperature, max_tokens, etc.)
    """
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    return chat(messages, **kwargs)
