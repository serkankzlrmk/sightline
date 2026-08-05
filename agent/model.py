"""
Model initialization and management.
Handles LLM provider setup (OpenRouter or Ollama) with proper error handling.
"""

import logging
import time

import requests
from langchain_openai import ChatOpenAI

from config import config

logger = logging.getLogger(__name__)


class ModelInitializationError(Exception):
    """Model initialization failed."""

    pass


def check_llm_connectivity(max_retries: int = 3, retry_delay: int = 2) -> bool:
    """
    Check if the LLM provider is accessible before initializing the model.
    Supports both OpenRouter and Ollama.

    Args:
        max_retries: Number of retry attempts
        retry_delay: Delay between retries in seconds

    Returns:
        True if the provider is accessible, False otherwise
    """
    provider = config.LLM_PROVIDER

    if provider == "openrouter":
        # OpenRouter: check /models endpoint with auth
        url = f"{config._LLM_BASE_URL.rstrip('/')}/models"
        headers = {"Authorization": f"Bearer {config._LLM_API_KEY}"}

        for attempt in range(max_retries):
            try:
                logger.info(f"Checking OpenRouter connectivity (attempt {attempt + 1}/{max_retries})...")
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code == 200:
                    logger.info("✓ OpenRouter is accessible")
                    return True
                elif response.status_code == 401:
                    logger.error("✗ OpenRouter API key is invalid (401 Unauthorized)")
                    return False
                elif response.status_code == 429:
                    logger.warning(f"OpenRouter rate limited (429), retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    logger.warning(f"OpenRouter returned status {response.status_code}")
            except requests.exceptions.ConnectionError:
                logger.warning(f"OpenRouter connection failed (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
            except Exception as e:
                logger.warning(f"Error checking OpenRouter: {e}")
        return False
    else:
        # Ollama: check /api/tags endpoint
        base_url = config.OLLAMA_BASE_URL.rstrip("/v1")
        health_url = f"{base_url}/api/tags"

        for attempt in range(max_retries):
            try:
                logger.info(f"Checking Ollama connectivity (attempt {attempt + 1}/{max_retries})...")
                response = requests.get(health_url, timeout=5)
                if response.status_code == 200:
                    logger.info("✓ Ollama is accessible")
                    return True
            except requests.exceptions.ConnectionError:
                logger.warning(f"Ollama connection failed (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
            except Exception as e:
                logger.warning(f"Error checking Ollama: {e}")
        return False


def check_model_available(model_name: str) -> bool:
    """
    Check if a specific model is available.
    For OpenRouter, always returns True (models are available on-demand).
    For Ollama, checks the local model list.

    Args:
        model_name: Name of the model to check

    Returns:
        True if model is available, False otherwise
    """
    if config.LLM_PROVIDER == "openrouter":
        # OpenRouter serves models on-demand, no need to check availability
        logger.info(f"✓ OpenRouter model '{model_name}' will be served on-demand")
        return True

    # Ollama: check local model list
    base_url = config.OLLAMA_BASE_URL.rstrip("/v1")
    tags_url = f"{base_url}/api/tags"

    try:
        response = requests.get(tags_url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            models = [m.get("name", "") for m in data.get("models", [])]

            for available_model in models:
                if model_name in available_model or available_model in model_name:
                    logger.info(f"✓ Model '{model_name}' found")
                    return True

            logger.warning(f"Model '{model_name}' not found. Available models: {models}")
            return False
    except Exception as e:
        logger.warning(f"Error checking available models: {e}")
        return False


def initialize_model(skip_checks: bool = False) -> ChatOpenAI:
    """
    Initialize the LLM model with error handling.
    Supports OpenRouter and Ollama providers.

    Args:
        skip_checks: Skip connectivity/model availability checks

    Returns:
        Initialized ChatOpenAI instance

    Raises:
        ModelInitializationError: If model initialization fails
    """
    provider = config.LLM_PROVIDER
    model_name = config.OLLAMA_MODEL
    logger.info(f"Initializing model: {model_name} (provider: {provider})")

    if not skip_checks:
        if not check_llm_connectivity():
            if provider == "openrouter":
                raise ModelInitializationError(
                    f"Cannot connect to OpenRouter at {config._LLM_BASE_URL}. Check your OPENROUTER_API_KEY."
                )
            else:
                raise ModelInitializationError(
                    f"Cannot connect to Ollama at {config.OLLAMA_BASE_URL}. Make sure Ollama is running: `ollama serve`"
                )

        if not check_model_available(model_name):
            if provider == "ollama":
                pull_cmd = f"ollama pull {model_name}"
                logger.warning(f"Model '{model_name}' not found locally. Pull it with: `{pull_cmd}`")

    try:
        model = ChatOpenAI(
            model=model_name,
            base_url=config._LLM_BASE_URL,
            api_key=config._LLM_API_KEY,
            temperature=config.MODEL_TEMPERATURE,
            max_tokens=config.MODEL_MAX_TOKENS,
            timeout=config.OLLAMA_TIMEOUT,
        )
        logger.info(f"✓ Model initialized successfully (provider: {provider})")
        return model
    except Exception as e:
        error_msg = f"Failed to initialize model: {e}"
        logger.error(error_msg)
        raise ModelInitializationError(error_msg) from e


def get_model(skip_checks: bool = False) -> ChatOpenAI | None:
    """
    Get or initialize the model singleton.

    Args:
        skip_checks: Skip connectivity/model availability checks

    Returns:
        Initialized ChatOpenAI instance or None if initialization fails
    """
    try:
        return initialize_model(skip_checks=skip_checks)
    except ModelInitializationError as e:
        logger.error(f"Model initialization error: {e}")
        return None


def reinitialize_model() -> ChatOpenAI:
    """
    Reinitialize the model singleton with current config values.
    Useful after config reload to pick up new model settings.

    Returns:
        Newly initialized ChatOpenAI instance

    Raises:
        ModelInitializationError: If model initialization fails
    """
    import importlib

    importlib.reload(config)
    logger.info("Reinitializing model with updated config: %s", config.OLLAMA_MODEL)
    return initialize_model(skip_checks=True)
