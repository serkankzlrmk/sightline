"""Daily digest storage and loading for Sightline content enrichment.

Single source of truth for reading digest artifacts. Both the daily
enrichment script (write path) and the SEO blueprint (read path, SSR)
import from here so the schema lives in exactly one place.

Storage layout: output/daily_digests/{coverage_date}/{Safe_Country}.json
Coverage date = the date the digest data covers (yesterday at run time),
matching the daily ingest convention.

ARM64 note: this module never touches ChromaDB. Chunks are read from
SQLite by the enrichment script; digests are flat JSON files.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from sitrep.utils import safe_filename

logger = logging.getLogger(__name__)

# Directory inside the shared output volume (mounted in both containers).
DIGEST_ROOT = Path(os.getenv("DIGEST_ROOT", "output/daily_digests"))
STATUS_FILE = DIGEST_ROOT / "status.json"

# Backward-walk window for _crisis_page() digest lookups (D5).
MAX_WALK_BACK_DAYS = 3

# Required fields of a digest document (D1 schema validation, strings only).
REQUIRED_FIELDS = (
    "headline",
    "key_developments",
    "key_concerns",
    "humanitarian_impact",
    "information_gaps",
)


def digest_path(country: str, coverage_date: str) -> Path:
    """Deterministic digest file path for a country + coverage date."""
    return DIGEST_ROOT / coverage_date / f"{safe_filename(country)}.json"


def _validate_digest(payload: object) -> dict | None:
    """Validate a digest document shape (D1). Returns the dict or None.

    All required fields must exist and be non-empty strings. Extra keys
    are preserved; junk types anywhere in the required set reject the file.
    """
    if not isinstance(payload, dict):
        return None
    for field in REQUIRED_FIELDS:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            return None
    return payload


def load_digest(country: str, coverage_date: str) -> dict | None:
    """Load and validate one digest file. Returns None on any problem."""
    path = digest_path(country, coverage_date)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("Digest read failed for %s/%s: %s", coverage_date, country, exc)
        return None
    return _validate_digest(payload)


def load_day(coverage_date: str) -> dict[str, dict]:
    """Load every valid digest for a coverage date. Keys are country names."""
    day_dir = DIGEST_ROOT / coverage_date
    if not day_dir.is_dir():
        return {}
    results: dict[str, dict] = {}
    for path in sorted(day_dir.glob("*.json")):
        if path.name == STATUS_FILE.name:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Digest read failed for %s: %s", path, exc)
            continue
        valid = _validate_digest(payload)
        if valid is not None:
            country = path.stem  # safe_filename(country) — reverse not needed for display
            results[country] = valid
    return results


def list_published_dates() -> list[str]:
    """All coverage dates that have at least one valid digest, newest first."""
    if not DIGEST_ROOT.is_dir():
        return []
    dates: list[str] = []
    for day_dir in sorted(DIGEST_ROOT.iterdir(), reverse=True):
        if not day_dir.is_dir():
            continue
        has_content = any(p.suffix == ".json" and p.name != STATUS_FILE.name for p in day_dir.iterdir())
        if has_content:
            dates.append(day_dir.name)
    return dates


def newest_digest(country: str, today: Callable[[], date] | None = None) -> dict | None:
    """Newest valid digest for a country within the walk-back window (D5).

    Walks backward from today up to MAX_WALK_BACK_DAYS so pre-dawn requests
    and timezone drift still find the latest coverage.
    """
    _today = (today or date.today)()
    for offset in range(MAX_WALK_BACK_DAYS + 1):
        coverage_date = (_today - timedelta(days=offset)).isoformat()
        digest = load_digest(country, coverage_date)
        if digest is not None:
            return digest
    return None


class _IndexCache:
    """5-minute in-process cache for the date -> country index (D7)."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = ttl_seconds
        self._snapshot: dict[str, float] = {}
        self._stamp: float = 0.0

    def get(self) -> dict[str, float]:
        now = time.time()
        if self._snapshot and (now - self._stamp) < self._ttl:
            return self._snapshot
        snapshot: dict[str, float] = {}
        if DIGEST_ROOT.is_dir():
            for day_dir in DIGEST_ROOT.iterdir():
                if day_dir.is_dir():
                    snapshot[day_dir.name] = day_dir.stat().st_mtime
        self._snapshot = snapshot
        self._stamp = now
        return snapshot


_index_cache = _IndexCache()


def cached_published_dates() -> list[str]:
    """Published dates newest-first, backed by the 5-minute index cache."""
    snapshot = _index_cache.get()
    return sorted(snapshot.keys(), reverse=True)


def read_status() -> dict | None:
    """Read the enrichment status file (D2/D12 health freshness)."""
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_digest_atomic(
    country: str,
    coverage_date: str,
    payload: dict,
    validate: bool = True,
) -> Path:
    """Atomically write a digest document (D11: tmp + os.replace).

    The daily-ingest container writes while the app container reads the
    same volume; readers must never observe a partial file.
    """
    if validate and _validate_digest(payload) is None:
        raise ValueError(f"Digest payload failed schema validation for {country}")
    path = digest_path(country, coverage_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    _index_cache._snapshot = {}  # invalidate the index cache on new content
    return path


def write_status_atomic(status: dict) -> Path:
    """Atomically write the enrichment status file (D2)."""
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STATUS_FILE)
    return STATUS_FILE
