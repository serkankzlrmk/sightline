"""
Shared utility functions for the Sightline backend.

Prevents code duplication across modules and blueprints.
"""

import json
import re


def parse_themes(raw: str) -> list[str]:
    """Parse a comma-separated themes string into a list of stripped, non-empty strings.
    
    Used across country_summary, public_bp, weekly_bulletin, etc.
    Handles None, empty strings, and extra whitespace.
    """
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def clean_json_response(text: str) -> str:
    """Extract JSON from LLM responses that may be wrapped in ```json...``` code blocks.
    
    Strips markdown code fences and returns the cleaned JSON string.
    """
    if not text:
        return text
    # Remove ```json...``` or ```...``` wrappers
    text = text.strip()
    if text.startswith("```"):
        # Remove opening line
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        # Remove closing line
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def safe_filename(name: str) -> str:
    """Convert a string to a filesystem-safe filename.
    
    Replaces any character that isn't alphanumeric, underscore, or hyphen
    with an underscore. Prevents path traversal and filesystem errors.
    """
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
