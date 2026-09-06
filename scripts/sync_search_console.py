#!/usr/bin/env python3
"""Fetch a finalized Search Console performance snapshot for Sightline."""

import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from growth.search_console import sync_search_console

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("search_console_sync")


def main() -> int:
    try:
        result = sync_search_console()
    except Exception as exc:
        logger.exception("Search Console sync failed: %s", exc)
        return 1
    logger.info("Search Console sync result: %s", json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
