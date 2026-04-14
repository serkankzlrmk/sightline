"""
Model initialization and management.
Handles Ollama model setup with proper error handling.
"""

import logging
from typing import Optional
import time
import requests

from langchain_openai import ChatOpenAI
from config import config

logger = logging.getLogger(__name__)


class ModelInitializationError(Exception):
    """Model initialization failed."""
    pass


def check_ollama_connectivity(max_retries: int = 3, retry_delay: int = 2) -> bool:
    """
    Check if Ollama is accessible before initializing the model.
    
    Args:
        max_retries: Number of retry attempts
        retry_delay: Delay between retries in seconds
        
    Returns:
        True if Ollama is accessible, False otherwise
    """
    base_url = config.OLLAMA_BASE_URL.rstrip('/v1')  # Get base URL without /v1
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
    Check if a specific model is available in Ollama.
    
    Args:
        model_name: Name of the model to check
        
    Returns:
        True if model is available, False otherwise
    """
    base_url = config.OLLAMA_BASE_URL.rstrip('/v1')
    tags_url = f"{base_url}/api/tags"
    
    try:
        response = requests.get(tags_url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            models = [m.get('name', '') for m in data.get('models', [])]
            
            # Check if model exists (exact match or partial match)
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
    Initialize the Ollama model with error handling.
    
    Args:
        skip_checks: Skip connectivity/model availability checks
        
    Returns:
        Initialized ChatOpenAI instance
        
    Raises:
        ModelInitializationError: If model initialization fails
    """
    logger.info(f"Initializing model: {config.OLLAMA_MODEL}")
    
    if not skip_checks:
        # Check Ollama connectivity
        if not check_ollama_connectivity():
            error_msg = (
                f"Cannot connect to Ollama at {config.OLLAMA_BASE_URL}. "
                "Make sure Ollama is running: `ollama serve`"
            )
            logger.error(error_msg)
            raise ModelInitializationError(error_msg)
        
        # Check if model is available
        if not check_model_available(config.OLLAMA_MODEL):
            pull_cmd = f"ollama pull {config.OLLAMA_MODEL}"
            error_msg = (
                f"Model '{config.OLLAMA_MODEL}' not found. "
                f"Pull it with: `{pull_cmd}`"
            )
            logger.warning(error_msg)
    
    try:
        model = ChatOpenAI(
            model=config.OLLAMA_MODEL,
            base_url=config.OLLAMA_BASE_URL,
            api_key=config.OLLAMA_API_KEY,
            temperature=config.MODEL_TEMPERATURE,
            max_tokens=config.MODEL_MAX_TOKENS,
            timeout=config.OLLAMA_TIMEOUT,
        )
        logger.info("✓ Model initialized successfully")
        return model
    except Exception as e:
        error_msg = f"Failed to initialize model: {e}"
        logger.error(error_msg)
        raise ModelInitializationError(error_msg) from e


def get_model(skip_checks: bool = False) -> Optional[ChatOpenAI]:
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
