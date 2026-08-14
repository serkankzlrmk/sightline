#!/usr/bin/env python3
"""
generate_country_summaries.py — Daily country intelligence summary generator.

Cron: daily 06:15 UTC (after daily_ingest at 06:00)
DB-derived fields refresh every run; HDX + World Bank respect a 30-day TTL
(see EXTERNAL_DATA_TTL_DAYS in sitrep/country_summary.py).

Usage: python scripts/generate_country_summaries.py
"""

import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("country_summaries_cron")


def main():
    log.info("Starting country summary generation...")

    # Suppress ONNX/TensorRT noise
    os.environ.setdefault("ORT_LOGGING_LEVEL", "3")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

    # Initialize HDX tools (needed for HDX data fetching)
    try:
        from config import config
        from reliefweb_api.hdx_tools import init_hdx_tools

        hdx_app_id = getattr(config, "HDX_APP_IDENTIFIER", "") or ""
        if hdx_app_id:
            init_hdx_tools(app_identifier=hdx_app_id)
            log.info("HDX client initialized")
        else:
            log.warning("HDX_APP_IDENTIFIER not set — HDX data will be skipped")
    except Exception as e:
        log.warning("HDX init failed (non-fatal): %s", e)

    # Generate summaries
    from sitrep.country_summary import generate_all_country_summaries

    result = generate_all_country_summaries()

    log.info(
        "Done: %d generated, %d skipped, %d errors, %d total",
        result["generated"],
        result["skipped"],
        result["errors"],
        result["total"],
    )

    if result["errors"] > 0:
        log.warning("Some errors occurred — check logs above")
        sys.exit(1)


if __name__ == "__main__":
    main()
