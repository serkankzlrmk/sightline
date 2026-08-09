#!/usr/bin/env python3
"""Daily visual enrichment for Sightline (production-only, no PixelRAG).

Adds Gemini-based page captioning on top of the text daily ingest:

  1. For every newly ingested report with a PDF, render each page to a JPEG.
  2. Send each page image to the Gemini vision model.
  3. Classify it (chart/map/table/.../decorative) and write a caption.
  4. Insert the result into SQLite visual_units.
  5. Embed the meaningful captions into ChromaDB for retrieval.

This runs entirely on the production container. No local worker is required.
The vision call happens on Gemini's servers, so no heavy embedding model is
installed on production hardware.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import config

DB_PATH = str(config.DB_PATH)
CHROMA_DIR = str(config.CHROMA_DIR)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-flash-latest")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# OpenRouter vision provider
VISION_PROVIDER = os.getenv("VISION_PROVIDER", "gemini")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("VISION_MODEL", "google/gemma-3-4b-it")
PIPELINE_VERSION = "visual-daily-v1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("daily_visual")

PROMPT = """Classify this page from a humanitarian report. Return JSON only with:
visual_type: one of chart, map, table, diagram, infographic, scanned_document, evidence_photo, decorative
caption: concise factual description of the meaningful content
relevance: number from 0 to 1 for humanitarian information retrieval
is_decorative: boolean

If this is a logo, stock photo, cover decoration, background, or layout-only page,
use visual_type=decorative, is_decorative=true, relevance <= 0.2."""


def parse_result(content: str) -> dict:
    content = content.strip().removeprefix("```json").removesuffix("```").strip()
    try:
        return json.loads(content)
    except Exception:
        return {"visual_type": "unknown", "caption": "Could not classify.", "relevance": 0.0, "is_decorative": True}


def _classify_gemini(image_bytes: bytes) -> dict:
    import base64
    import time

    import requests

    encoded = base64.b64encode(image_bytes).decode("ascii")
    time.sleep(4.2)  # Gemini free tier ~15 RPM.
    for attempt in range(5):
        response = requests.post(
            GEMINI_URL.format(model=GEMINI_MODEL),
            headers={"X-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
            json={
                "contents": [
                    {
                        "parts": [
                            {"text": PROMPT},
                            {"inline_data": {"mime_type": "image/jpeg", "data": encoded}},
                        ]
                    }
                ],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
            },
            timeout=120,
        )
        if response.status_code == 429:
            retry = response.headers.get("Retry-After")
            wait = float(retry) if retry else 15 + (attempt * 10)
            log.warning("Gemini rate limit, backing off %.1fs", wait)
            time.sleep(wait)
            continue
        response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text) if text.strip().startswith("{") else parse_result(text)
    raise RuntimeError("Gemini rate limit retries exhausted")


def _classify_openrouter(image_bytes: bytes) -> dict:
    import base64

    import requests

    encoded = base64.b64encode(image_bytes).decode("ascii")
    response = requests.post(
        f"{OPENROUTER_BASE_URL.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": OPENROUTER_MODEL,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                    ],
                }
            ],
        },
        timeout=120,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return parse_result(content)


def classify_image(image_bytes: bytes) -> dict:
    if VISION_PROVIDER == "openrouter":
        return _classify_openrouter(image_bytes)
    return _classify_gemini(image_bytes)


def render_pdf_pages(pdf_bytes: bytes, max_pages: int = 40) -> list[bytes]:
    """Render a PDF to page JPEGs using PyMuPDF (fitz)."""
    try:
        import fitz
    except ImportError:
        try:
            import pymupdf as fitz
        except ImportError:
            log.error("PyMuPDF not installed")
            return []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    try:
        for page_number in range(min(len(doc), max_pages)):
            page = doc.load_page(page_number)
            pix = page.get_pixmap(dpi=120)
            buffer = io.BytesIO(pix.tobytes("png"))
            images.append(buffer.getvalue())
    finally:
        doc.close()
    return images


def add_visual_units(report_id: int, units: list[dict]) -> int:
    """Insert visual units into SQLite and embed meaningful ones into ChromaDB."""
    import sqlite3

    conn = sqlite3.connect(DB_PATH)
    now = datetime.now(UTC).isoformat()
    try:
        for unit in units:
            unit_id = f"{report_id}-p{int(unit['page_number']):04d}"
            conn.execute(
                """INSERT OR REPLACE INTO visual_units
                (unit_id, report_id, page_number, visual_type, caption, asset_key,
                 relevance, is_decorative, index_for_retrieval, pipeline_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    unit_id,
                    report_id,
                    int(unit["page_number"]),
                    unit["visual_type"],
                    unit["caption"],
                    unit.get("asset_key", ""),
                    float(unit["relevance"]),
                    int(unit["is_decorative"]),
                    int(not unit["is_decorative"]),
                    PIPELINE_VERSION,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    # Embed meaningful captions into ChromaDB.
    eligible = [u for u in units if u["index_for_retrieval"] and not u["is_decorative"]]
    if not eligible:
        return 0
    from reliefweb_api.vector_store import VectorStore

    # Pull report metadata for retrieval context.
    meta = None
    try:
        import sqlite3 as _s

        c = _s.connect(DB_PATH)
        row = c.execute("SELECT title, date, source, url FROM reports WHERE report_id=?", (report_id,)).fetchone()
        c.close()
        if row:
            meta = {"title": row[0], "date": row[1], "source": row[2], "url": row[3]}
    except Exception:
        pass

    decorated = []
    for u in eligible:
        item = {
            "unit_id": f"{report_id}-p{int(u['page_number']):04d}",
            "report_id": report_id,
            "page_number": int(u["page_number"]),
            "visual_type": u["visual_type"],
            "caption": u["caption"],
            "relevance": float(u["relevance"]),
            "asset_key": f"r2://source-pdfs/{report_id}#p{int(u['page_number']):04d}",
        }
        if meta:
            item.update(meta)
        decorated.append(item)
    vs = VectorStore(CHROMA_DIR)
    return vs.add_visual_units(decorated)


def process_report(report_id: int, pdf_bytes: bytes) -> int:
    """Render PDF pages and add Gemini captions for one report."""
    pages = render_pdf_pages(pdf_bytes)
    if not pages:
        log.info("report %s: no pages rendered", report_id)
        return 0
    units = []
    for idx, page_bytes in enumerate(pages, 1):
        try:
            result = classify_image(page_bytes)
            units.append(
                {
                    "page_number": idx,
                    "visual_type": result.get("visual_type", "unknown"),
                    "caption": result.get("caption", "Visual page"),
                    "relevance": result.get("relevance", 0.5),
                    "is_decorative": result.get("is_decorative", False),
                    "index_for_retrieval": not result.get("is_decorative", False),
                }
            )
        except Exception as exc:
            log.warning("report %s page %d gemini failed: %s", report_id, idx, exc)
    if units:
        added = add_visual_units(report_id, units)
        log.info("report %s: %d pages, %d indexed", report_id, len(units), added)
        return len(units)
    return 0


def get_pdf_bytes(report_id: int) -> bytes | None:
    """Return report PDF bytes (from R2 or API)."""
    import sqlite3

    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT source_object_key FROM reports WHERE report_id=? AND has_pdf=1", (report_id,)).fetchone()
    conn.close()

    if row and row[0]:
        import boto3

        required = ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
        if all(os.getenv(x) for x in required):
            client = boto3.client(
                "s3",
                endpoint_url=os.environ["R2_ENDPOINT_URL"],
                aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            )
            import io

            buf = io.BytesIO()
            client.download_fileobj(os.environ["R2_BUCKET"], row[0], buf)
            return buf.getvalue()

    # Fallback: fetch from ReliefWeb API.
    import requests

    from reliefweb_api.reliefweb_config import RELIEFWEB_APPNAME, RELIEFWEB_REPORTS_API, _ssl_verify
    from reliefweb_api.reliefweb_utils import retry_request

    url = f"{RELIEFWEB_REPORTS_API}/{report_id}?appname={RELIEFWEB_APPNAME}&fields[include][]=file"
    resp = retry_request("get", url, timeout=30, verify=_ssl_verify())
    resp.raise_for_status()
    fields = (resp.json().get("data") or [{}])[0].get("fields", {})
    pdf = next((item for item in fields.get("file", []) if item.get("mimetype", "").lower() == "application/pdf"), None)
    if not pdf or not pdf.get("url"):
        return None
    pdf_resp = requests.get(pdf["url"], timeout=60)
    pdf_resp.raise_for_status()
    return pdf_resp.content


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_ids", nargs="*", type=int, help="Specific report IDs (optional)")
    parser.add_argument("--date", help="Process reports dated YYYY-MM-DD")
    parser.add_argument("--r2-required", action="store_true", help="Fail if R2 not configured")
    args = parser.parse_args()

    if args.r2_required:
        for var in ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
            if not os.getenv(var):
                raise SystemExit(f"Missing R2 env var: {var}")

    if VISION_PROVIDER == "openrouter":
        if not OPENROUTER_API_KEY:
            raise SystemExit("OPENROUTER_API_KEY is required (VISION_PROVIDER=openrouter)")
    elif not GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY is required")

    import sqlite3

    if args.report_ids:
        report_ids = list(args.report_ids)
    else:
        conn = sqlite3.connect(DB_PATH)
        query = "SELECT report_id FROM reports WHERE has_pdf = 1"
        params: list = []
        if args.date:
            query += " AND date = ?"
            params.append(args.date)
        report_ids = [r[0] for r in conn.execute(query, params).fetchall()]
        conn.close()

    if not report_ids:
        log.info("No reports to process")
        return

    log.info("Processing %d reports for visual enrichment", len(report_ids))
    done = errors = 0
    for report_id in report_ids:
        try:
            pdf_bytes = get_pdf_bytes(report_id)
            if not pdf_bytes:
                log.warning("report %s: no PDF bytes", report_id)
                continue
            n = process_report(report_id, pdf_bytes)
            done += n
        except Exception as exc:
            errors += 1
            log.warning("report %s failed: %s", report_id, exc)
    log.info("Complete: %d pages classified, %d errors", done, errors)


if __name__ == "__main__":
    main()
