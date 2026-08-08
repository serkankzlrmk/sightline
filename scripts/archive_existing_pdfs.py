#!/usr/bin/env python3
"""Archive already-ingested PDF sources to R2 without re-embedding them."""

from __future__ import annotations

import logging
import sqlite3

import config
from reliefweb_api.ingest_pipeline import _archive_pdf_to_r2
from reliefweb_api.reliefweb_config import API_TIMEOUT_LONG, RELIEFWEB_APPNAME, RELIEFWEB_REPORTS_API, _ssl_verify
from reliefweb_api.reliefweb_utils import retry_request

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("archive_existing_pdfs")


def main() -> None:
    conn = sqlite3.connect(config.DB_PATH)
    rows = conn.execute(
        "SELECT report_id FROM reports WHERE has_pdf = 1 AND (source_object_key IS NULL OR source_object_key = '')"
    ).fetchall()
    log.info("Found %d PDF sources to archive", len(rows))
    archived = errors = 0
    try:
        for index, (report_id,) in enumerate(rows, 1):
            try:
                url = f"{RELIEFWEB_REPORTS_API}/{report_id}?appname={RELIEFWEB_APPNAME}&fields[include][]=file"
                response = retry_request("get", url, timeout=API_TIMEOUT_LONG, verify=_ssl_verify())
                response.raise_for_status()
                fields = (response.json().get("data") or [{}])[0].get("fields", {})
                pdf = next(
                    (item for item in fields.get("file", []) if item.get("mimetype", "").lower() == "application/pdf"),
                    None,
                )
                if not pdf or not pdf.get("url"):
                    errors += 1
                    log.warning("[%d/%d] No PDF URL for %s", index, len(rows), report_id)
                    continue
                pdf_response = retry_request("get", pdf["url"], timeout=API_TIMEOUT_LONG, verify=_ssl_verify())
                pdf_response.raise_for_status()
                object_key = _archive_pdf_to_r2(report_id, pdf_response.content)
                if not object_key:
                    raise RuntimeError("R2 archive returned no object key")
                conn.execute("UPDATE reports SET source_object_key = ? WHERE report_id = ?", (object_key, report_id))
                conn.commit()
                archived += 1
                log.info("[%d/%d] Archived %s", index, len(rows), report_id)
            except Exception as exc:
                errors += 1
                log.warning("[%d/%d] Failed %s: %s", index, len(rows), report_id, exc)
    finally:
        conn.close()
    log.info("Archive complete: %d archived, %d errors", archived, errors)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
