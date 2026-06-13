#!/usr/bin/env python3
"""
scripts/generate_bulletin.py
CLI entry point for weekly bulletin generation.

Intended for cron scheduling (e.g., Monday 06:30 UTC after daily_ingest).

Usage:
    python scripts/generate_bulletin.py --date-from 2026-06-01 --date-to 2026-06-07
    python scripts/generate_bulletin.py --last-week
    python scripts/generate_bulletin.py --this-week
    python scripts/generate_bulletin.py --skip-llm --last-week
"""

import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Ensure project root is on sys.path
_ROOT = str(Path(__file__).parent.parent.resolve())
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def last_week_range():
    """Return (Monday, Sunday) of last week in YYYY-MM-DD format."""
    today = datetime.now()
    # Last Monday = today - (today.weekday()) - 7
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6)
    return last_monday.strftime("%Y-%m-%d"), last_sunday.strftime("%Y-%m-%d")


def this_week_range():
    """Return (Monday, today) of current week in YYYY-MM-DD format."""
    today = datetime.now()
    this_monday = today - timedelta(days=today.weekday())
    return this_monday.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def main():
    parser = argparse.ArgumentParser(
        description="Weekly Bulletin Generator — NovaSphere CLI"
    )
    date_group = parser.add_mutually_exclusive_group(required=True)
    date_group.add_argument(
        "--date-from",
        help="Start date (YYYY-MM-DD). Must also provide --date-to.",
    )
    date_group.add_argument(
        "--last-week",
        action="store_true",
        help="Generate bulletin for last week (Mon-Sun).",
    )
    date_group.add_argument(
        "--this-week",
        action="store_true",
        help="Generate bulletin for this week (Mon-today).",
    )

    parser.add_argument(
        "--date-to",
        help="End date (YYYY-MM-DD). Required with --date-from.",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip LLM calls, use metadata-only summaries (faster, no API cost).",
    )

    args = parser.parse_args()

    # Determine date range
    if args.last_week:
        date_from, date_to = last_week_range()
    elif args.this_week:
        date_from, date_to = this_week_range()
    else:
        date_from = args.date_from
        date_to = args.date_to
        if not date_to:
            parser.error("--date-to is required when using --date-from")

    print(f"Generating weekly bulletin: {date_from} to {date_to}")
    print(f"Skip LLM: {args.skip_llm}")

    # Initialize HDX client if configured (for enrichment)
    from config import config
    hdx_app_id = getattr(config, 'HDX_APP_IDENTIFIER', '') or ''
    if hdx_app_id:
        try:
            from reliefweb_api.hdx_tools import init_hdx_tools
            if init_hdx_tools(app_identifier=hdx_app_id):
                print("HDX client initialized successfully")
            else:
                print("Warning: HDX client initialization failed")
        except Exception as e:
            print(f"Warning: HDX init error: {e}")

    from sitrep.weekly_bulletin import generate_weekly_bulletin

    path = generate_weekly_bulletin(
        date_from=date_from,
        date_to=date_to,
        skip_llm=args.skip_llm,
    )

    print(f"\n✅ Bulletin saved to: {path}")


if __name__ == "__main__":
    main()