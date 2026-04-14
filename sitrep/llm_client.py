"""
sitrep_pipeline/llm_client.py
LLM wrapper — OpenRouter veya Ollama (OpenAI-uyumlu API).

LLM_PROVIDER = "openrouter"  → https://openrouter.ai/api/v1
LLM_PROVIDER = "ollama"      → http://localhost:11434/v1  (varsayılan)
"""

import time
import logging
from typing import List, Dict, Optional

import requests

from config import (
    LLM_PROVIDER,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OLLAMA_BASE_URL,
    OLLAMA_API_KEY,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS_DEFAULT,
    LLM_TIMEOUT,
    LLM_MAX_RETRIES,
)

logger = logging.getLogger(__name__)

# Rate limit bekleme süresi (saniye)
_RATE_LIMIT_WAIT = 10


def _get_base_url_and_headers() -> tuple[str, dict]:
    """Provider'a göre base URL ve HTTP başlıklarını döndürür."""
    if LLM_PROVIDER == "ollama":
        headers = {"Content-Type": "application/json"}
        # Ollama Cloud modelleri için API key ekle
        if OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
        return OLLAMA_BASE_URL, headers
    else:  # openrouter
        return OPENROUTER_BASE_URL, {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/sitrep_pipeline",
            "X-Title": "SitrepPipeline",
        }


def chat(
    messages: List[Dict[str, str]],
    model: str = LLM_MODEL,
    temperature: float = LLM_TEMPERATURE,
    max_tokens: int = LLM_MAX_TOKENS_DEFAULT,
) -> str:
    """
    /chat/completions endpoint'ini çağırır (OpenRouter veya Ollama).

    Args:
        messages : [{"role": "system"|"user"|"assistant", "content": str}, ...]
        model    : Model ID (provider'a göre değişir)
        temperature: 0.0 = deterministik
        max_tokens : Yanıt için max token

    Returns:
        Modelin yanıt metni (string).

    Raises:
        RuntimeError: Tüm retry'lar tükendikten sonra ulaşılamazsa.
    """
    if LLM_PROVIDER == "openrouter" and not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY ayarlanmamış. "
            ".env dosyasına OPENROUTER_API_KEY=sk-or-... ekleyin."
        )

    base_url, headers = _get_base_url_and_headers()

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # qwen3 ve reasoning modellerinde think modunu kapat (daha hızlı + temiz çıktı)
    if LLM_PROVIDER == "ollama":
        payload["think"] = False

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

            if response.status_code == 402:
                raise RuntimeError(
                    "OpenRouter 402: Hesap kredisi yetersiz. "
                    "https://openrouter.ai adresinden bakiye yükleyin."
                )

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
        f"LLM'e ({LLM_PROVIDER}) {LLM_MAX_RETRIES} denemede ulaşılamadı. "
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
