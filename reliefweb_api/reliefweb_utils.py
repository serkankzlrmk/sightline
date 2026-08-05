"""
ReliefWeb API Utility Functions
Shared utilities for API operations
"""

import json
import logging
import re
import time
from datetime import datetime
from typing import Any

import requests

from .reliefweb_config import (
    COUNTRY_NAME_MAP,
    DATE_FORMAT,
    ENABLE_RETRY,
    MAX_COUNTRY_LENGTH,
    MAX_RETRIES,
    MIN_COUNTRY_LENGTH,
    RETRY_DELAY,
)

# Setup logging
logger = logging.getLogger(__name__)

# ========================================================================
# TEXT PROCESSING UTILITIES
# ========================================================================


def normalize_country_name(country: str) -> str:
    """
    Normalize country name to match ReliefWeb's naming convention.

    Args:
        country: User-provided country name

    Returns:
        Normalized country name

    Examples:
        normalize_country_name("syria") → "Syrian Arab Republic"
        normalize_country_name("drc") → "Democratic Republic of the Congo"
    """
    if not country:
        return ""

    country_lower = country.lower().strip()

    if country_lower in COUNTRY_NAME_MAP:
        return COUNTRY_NAME_MAP[country_lower]

    return country.strip()


def clean_html_body(body_html: str) -> str:
    """
    Clean HTML content from ReliefWeb body.
    Removes tags, decodes entities, and normalizes whitespace.

    Args:
        body_html: HTML content string

    Returns:
        Cleaned plain text
    """
    if not body_html:
        return "No content available"

    # Remove HTML tags
    cleaned = re.sub("<[^<]+?>", " ", body_html)

    # Decode HTML entities
    entity_map = {"&nbsp;": " ", "&amp;": "&", "&quot;": '"', "&apos;": "'", "&lt;": "<", "&gt;": ">"}

    for entity, char in entity_map.items():
        cleaned = cleaned.replace(entity, char)

    # Normalize whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """
    Truncate text to maximum length with suffix.

    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add when truncated

    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text

    return text[: max_length - len(suffix)] + suffix


# ========================================================================
# INPUT VALIDATION UTILITIES
# ========================================================================


def validate_country(country: str) -> tuple[bool, str | None]:
    """
    Validate country name input.

    Args:
        country: Country name to validate

    Returns:
        (is_valid, error_message)
    """
    if not country:
        return False, "Country name is required"

    country_str = str(country).strip()

    if len(country_str) < MIN_COUNTRY_LENGTH:
        return False, f"Country name too short (minimum {MIN_COUNTRY_LENGTH} characters)"

    if len(country_str) > MAX_COUNTRY_LENGTH:
        return False, f"Country name too long (maximum {MAX_COUNTRY_LENGTH} characters)"

    # Check for valid characters (letters, spaces, hyphens, apostrophes)
    if not re.match(r"^[a-zA-Z\s\-']+$", country_str):
        return False, "Country name contains invalid characters"

    return True, None


def validate_limit(limit: int, max_limit: int) -> tuple[bool, str | None]:
    """
    Validate limit parameter.

    Args:
        limit: Limit value
        max_limit: Maximum allowed limit

    Returns:
        (is_valid, error_message)
    """
    try:
        limit_int = int(limit)
    except (ValueError, TypeError):
        return False, "Limit must be a valid number"

    if limit_int < 1:
        return False, "Limit must be at least 1"

    if limit_int > max_limit:
        return False, f"Limit exceeds maximum ({max_limit})"

    return True, None


def validate_date(date_str: str) -> tuple[bool, str | None]:
    """
    Validate date format (YYYY-MM-DD).

    Args:
        date_str: Date string to validate

    Returns:
        (is_valid, error_message)
    """
    try:
        datetime.strptime(date_str, DATE_FORMAT)
        return True, None
    except (ValueError, TypeError):
        return False, f"Invalid date format. Use {DATE_FORMAT}"


# ========================================================================
# RETRY UTILITY
# ========================================================================


def retry_request(
    method: str, url: str, max_retries: int = None, retry_delay: float = None, **kwargs
) -> requests.Response:
    """
    Execute an HTTP request with automatic retry on transient failures.

    Retries on:
    - Network errors (ConnectionError, Timeout)
    - HTTP 429 (rate limit) — exponential backoff
    - HTTP 5xx (server errors)

    Does NOT retry on:
    - HTTP 4xx client errors (except 429)

    Args:
        method: HTTP method ('get' or 'post')
        url: Request URL
        max_retries: Max retry attempts (default: from config MAX_RETRIES)
        retry_delay: Base delay between retries in seconds (default: from config RETRY_DELAY)
        **kwargs: Additional arguments passed to requests (timeout, verify, json, etc.)

    Returns:
        requests.Response object

    Raises:
        requests.exceptions.RequestException: After all retries exhausted
    """
    if not ENABLE_RETRY:
        # Retry disabled — single shot
        fn = getattr(requests, method.lower())
        return fn(url, **kwargs)

    _max_retries = max_retries if max_retries is not None else MAX_RETRIES
    _retry_delay = retry_delay if retry_delay is not None else RETRY_DELAY

    fn = getattr(requests, method.lower())
    last_error: Exception | None = None

    for attempt in range(1, _max_retries + 1):
        try:
            response = fn(url, **kwargs)

            # Rate limit — exponential backoff
            if response.status_code == 429:
                wait = _retry_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Rate limit (429) on %s %s. Attempt %d/%d. Waiting %.1fs.",
                    method.upper(),
                    url,
                    attempt,
                    _max_retries,
                    wait,
                )
                time.sleep(wait)
                continue

            # Server error — retry
            if response.status_code >= 500:
                wait = _retry_delay * attempt
                logger.warning(
                    "Server error (%d) on %s %s. Attempt %d/%d. Waiting %.1fs.",
                    response.status_code,
                    method.upper(),
                    url,
                    attempt,
                    _max_retries,
                    wait,
                )
                time.sleep(wait)
                continue

            # Success or client error (4xx except 429) — return immediately
            return response

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_error = exc
            wait = _retry_delay * attempt
            logger.warning(
                "Request failed on %s %s. Attempt %d/%d. Waiting %.1fs. Error: %s",
                method.upper(),
                url,
                attempt,
                _max_retries,
                wait,
                exc,
            )
            time.sleep(wait)

    # All retries exhausted
    if last_error:
        raise last_error
    raise requests.exceptions.RequestException(f"All {_max_retries} retries exhausted for {method.upper()} {url}")


# ========================================================================
# RESPONSE FORMATTING UTILITIES
# ========================================================================


def format_response(data: Any, as_json: bool = True) -> str:
    """
    Format response data as JSON string.

    Args:
        data: Data to format
        as_json: Whether to return as JSON (else str)

    Returns:
        Formatted string
    """
    if as_json:
        return json.dumps(data, indent=2, ensure_ascii=False)

    return str(data)


def format_error(error_type: str, message: str, details: dict | None = None) -> str:
    """
    Format error response.

    Args:
        error_type: Type of error
        message: Error message
        details: Additional details

    Returns:
        Formatted error JSON
    """
    error_obj = {"error": True, "error_type": error_type, "message": message, "timestamp": datetime.now().isoformat()}

    if details:
        error_obj["details"] = details

    return json.dumps(error_obj, indent=2, ensure_ascii=False)


def format_success(data: Any, message: str = None) -> str:
    """
    Format success response.

    Args:
        data: Response data
        message: Optional success message

    Returns:
        Formatted JSON
    """
    if isinstance(data, str):
        try:
            # If it's already JSON, return as-is
            json.loads(data)
            return data
        except json.JSONDecodeError:
            pass

    if isinstance(data, list):
        return json.dumps(data, indent=2, ensure_ascii=False)

    if isinstance(data, dict):
        return json.dumps(data, indent=2, ensure_ascii=False)

    return json.dumps({"data": data, "message": message}, indent=2, ensure_ascii=False)


# ========================================================================
# API REQUEST UTILITIES
# ========================================================================


def build_api_request_body(
    limit: int = 25,
    filter_field: str | None = None,
    filter_value: str | None = None,
    query: str | None = None,
    fields: list | None = None,
    sort: list | None = None,
    preset: str = "latest",
) -> dict[str, Any]:
    """
    Build ReliefWeb API request body.

    Args:
        limit: Result limit
        filter_field: Field to filter on
        filter_value: Filter value
        query: Search query
        fields: Fields to include
        sort: Sort order
        preset: Request preset

    Returns:
        Formatted request body
    """
    body = {"preset": preset, "limit": limit}

    if filter_field and filter_value:
        body["filter"] = {"field": filter_field, "value": filter_value}

    if query:
        body["query"] = {"value": query}

    if fields:
        body["fields"] = {"include": fields}

    if sort:
        body["sort"] = sort

    return body


# ========================================================================
# DATA EXTRACTION UTILITIES
# ========================================================================


def extract_field(obj: dict, path: str, default: Any = None) -> Any:
    """
    Extract nested field from dict using dot notation.

    Args:
        obj: Dictionary to extract from
        path: Dot-separated path (e.g., "data.fields.title")
        default: Default value if not found

    Returns:
        Extracted value or default

    Examples:
        extract_field(obj, "fields.title") → gets obj["fields"]["title"]
    """
    keys = path.split(".")
    current = obj

    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
            if current is None:
                return default
        elif isinstance(current, list) and key.isdigit():
            try:
                current = current[int(key)]
            except (IndexError, ValueError):
                return default
        else:
            return default

    return current


def extract_items(data: dict, item_key: str = "data") -> list:
    """
    Extract items list from API response.

    Args:
        data: API response dict
        item_key: Key containing items (usually "data")

    Returns:
        List of items
    """
    if not isinstance(data, dict):
        return []

    items = data.get(item_key, [])
    return items if isinstance(items, list) else []


# ========================================================================
