"""
ReliefWeb Ingest Pipeline
Shared logic for inserting downloaded reports into SQLite + ChromaDB.

Used by:
  - ingest.py (batch CLI)
  - reliefweb.py download tools (auto-ingest on download)
  - server.py /api/ingest/download route (in-memory ingest, no disk writes)
"""

import json
import io
import logging
import requests
from pathlib import Path
from typing import Dict, Optional

from .db_manager import (
    DatabaseManager,
    extract_pdf_text,
    chunk_text,
    build_chunk_with_header,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    DEFAULT_DB_PATH,
)
from .vector_store import VectorStore, CHROMA_DIR
from config import VECTOR_BACKEND
from .reliefweb_config import (
    RELIEFWEB_REPORTS_API,
    RELIEFWEB_APPNAME,
    API_TIMEOUT_LONG,
    PDF_DOWNLOAD_TIMEOUT,
    PDF_SIZE_LIMIT,
    _ssl_verify,
)
from .reliefweb_utils import clean_html_body, retry_request

logger = logging.getLogger(__name__)


# ============================================================================
# DEDUP CHECK
# ============================================================================

def is_ingested(report_id: int, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Return True if this report is already in the SQLite database."""
    db = DatabaseManager(db_path)
    result = db.report_exists(report_id)
    db.close()
    return result


def is_ingested_with_pdf(report_id: int, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Return True if report is ingested AND has PDF content."""
    db = DatabaseManager(db_path)
    result = db.report_has_pdf(report_id)
    db.close()
    return result


# ============================================================================
# AUTO-INGEST A DOWNLOADED REPORT
# ============================================================================

def auto_ingest(
    report_id: int,
    downloads_root: str = "reliefweb_downloads",
    db_path: str = DEFAULT_DB_PATH,
    chroma_dir: str = CHROMA_DIR,
) -> Dict:
    """
    Read a downloaded report from disk and ingest into SQLite + ChromaDB.

    Locates the report folder by scanning downloads_root for a directory
    whose name starts with str(report_id).

    Args:
        report_id: Integer report ID
        downloads_root: Parent folder that contains all report sub-folders
        db_path: SQLite database path (default: reliefweb.db)
        chroma_dir: ChromaDB persist directory (default: reliefweb_chroma)

    Returns:
        Dict with keys: success (bool), report_id, chunks_added,
        has_pdf, has_content, and optionally error (str).
    """
    root = Path(downloads_root)

    # Locate the report folder
    matching = [
        d for d in root.iterdir()
        if d.is_dir() and d.name.startswith(str(report_id))
    ]
    if not matching:
        return {
            "success": False,
            "error": f"No folder for report {report_id} in {root}",
        }

    folder = matching[0]

    # Locate files
    meta_files = list(folder.glob("*_metadata.json"))
    content_files = list(folder.glob("*_content.txt"))
    pdf_files = list(folder.glob("*.pdf"))

    if not meta_files:
        return {"success": False, "error": "No metadata.json in folder"}

    # Load metadata
    try:
        with open(meta_files[0], encoding="utf-8") as f:
            metadata = json.load(f)
    except Exception as e:
        return {"success": False, "error": f"Metadata read failed: {e}"}

    chunks = []
    has_content = False
    has_pdf = False
    pdf_pages = 0

    # HTML content chunks
    if content_files:
        try:
            text = content_files[0].read_text(encoding="utf-8").strip()
            if text:
                has_content = True
                for raw in chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP):
                    enriched = build_chunk_with_header(raw, metadata, "html")
                    chunks.append({"source_type": "html", "content": enriched})
        except Exception:
            pass

    # PDF chunks
    if pdf_files:
        try:
            pdf_text, pdf_pages = extract_pdf_text(str(pdf_files[0]))
            if pdf_text.strip():
                has_pdf = True
                for raw in chunk_text(pdf_text, CHUNK_SIZE, CHUNK_OVERLAP):
                    enriched = build_chunk_with_header(raw, metadata, "pdf")
                    chunks.append({"source_type": "pdf", "content": enriched})
        except Exception:
            pass

    # --- Insert SQLite ---
    try:
        db = DatabaseManager(db_path)
        db.insert_report(
            metadata, chunks,
            has_pdf=has_pdf,
            has_content=has_content,
            pdf_pages=pdf_pages,
        )
        db.close()
    except Exception as e:
        return {"success": False, "error": f"SQLite insert failed: {e}"}

    # --- Insert into Vector Store (ChromaDB or pgvector) ---
    n_chunks = 0
    try:
        vs = VectorStore(chroma_dir, backend=VECTOR_BACKEND)
        n_chunks = vs.add_report(report_id, chunks, metadata)
    except Exception as e:
        # Vector store failed — rollback SQLite insert to avoid orphaned records
        logger.error(f"Vector store insert failed for {report_id}: {e}. Rolling back SQLite.")
        try:
            db = DatabaseManager(db_path)
            db.delete_report(report_id)
            db.close()
            logger.info(f"Rolled back SQLite insert for report {report_id}")
        except Exception as rollback_err:
            logger.error(f"SQLite rollback also failed for {report_id}: {rollback_err}")
        return {"success": False, "error": f"Vector store insert failed: {e}"}

    return {
        "success": True,
        "report_id": report_id,
        "chunks_added": n_chunks,
        "has_pdf": has_pdf,
        "has_content": has_content,
    }


# ============================================================================
# IN-MEMORY INGEST (no disk writes — PDF/HTML processed directly in RAM)
# ============================================================================

def ingest_from_api(
    report_id: int,
    db_path: str = DEFAULT_DB_PATH,
    chroma_dir: str = CHROMA_DIR,
) -> Dict:
    """
    Fetch a report from ReliefWeb API, process it entirely in memory,
    and insert into SQLite + ChromaDB — **no files written to disk**.

    This replaces the old download-then-ingest two-step flow:
      OLD:  API → download PDF/HTML to reliefweb_downloads/ → read from disk → ingest
      NEW:  API → process PDF/HTML in RAM → ingest → done (no disk footprint)

    Args:
        report_id: Integer report ID
        db_path: SQLite database path
        chroma_dir: ChromaDB persist directory

    Returns:
        Dict with keys: success, report_id, chunks_added, has_pdf, has_content,
        and optionally error (str).
    """
    # ── 1. Fetch metadata from ReliefWeb API ──────────────────────
    try:
        url = (
            f"{RELIEFWEB_REPORTS_API}/{report_id}"
            f"?appname={RELIEFWEB_APPNAME}"
            f"&fields[include][]=file"
            f"&fields[include][]=body-html"
            f"&fields[include][]=body"
            f"&fields[include][]=title"
            f"&fields[include][]=date"
            f"&fields[include][]=source"
            f"&fields[include][]=country"
            f"&fields[include][]=disaster"
            f"&fields[include][]=theme"
            f"&fields[include][]=url"
            f"&fields[include][]=format"
            f"&fields[include][]=language"
        )
        resp = retry_request("get", url, timeout=API_TIMEOUT_LONG, verify=_ssl_verify())
        resp.raise_for_status()
        data = resp.json()

        if not data.get("data") or len(data["data"]) == 0:
            return {"success": False, "error": f"Report {report_id} not found in API"}

        report_data = data["data"][0]
        fields = report_data.get("fields", {})
    except Exception as e:
        return {"success": False, "error": f"API fetch failed: {e}"}

    # ── 2. Build metadata dict (same format as metadata.json) ────
    metadata = {
        "id": report_id,
        "title": fields.get("title", ""),
        "date": fields.get("date", {}),
        "source": fields.get("source", []),
        "countries": fields.get("country", []),
        "disasters": fields.get("disaster", []),
        "themes": fields.get("theme", []),
        "url": fields.get("url", ""),
        "language": fields.get("language", ""),
        "format": fields.get("format", ""),
    }

    chunks = []
    has_content = False
    has_pdf = False
    pdf_pages = 0

    # ── 3. Process HTML body content in memory ────────────────────
    body_html = (
        fields.get("body-html")
        or fields.get("body")
        or ""
    )
    if body_html:
        try:
            clean_text = clean_html_body(body_html)
            if clean_text.strip():
                has_content = True
                for raw in chunk_text(clean_text, CHUNK_SIZE, CHUNK_OVERLAP):
                    enriched = build_chunk_with_header(raw, metadata, "html")
                    chunks.append({"source_type": "html", "content": enriched})
        except Exception as e:
            logger.warning(f"HTML content processing failed for {report_id}: {e}")

    # ── 4. Process PDF in memory (download to RAM, not disk) ──────
    files = fields.get("file", [])
    pdf_file = None
    for file_item in files:
        mt = file_item.get("mimetype") or file_item.get("mime_type", "")
        if mt.lower() == "application/pdf":
            pdf_file = file_item
            break

    if pdf_file:
        try:
            pdf_url = pdf_file.get("url", "")
            pdf_size = int(pdf_file.get("filesize", 0))

            if pdf_size > PDF_SIZE_LIMIT:
                logger.warning(
                    f"PDF too large for report {report_id}: "
                    f"{pdf_size / 1_000_000:.2f}MB (max {PDF_SIZE_LIMIT // 1_000_000}MB)"
                )
            elif pdf_url:
                # Download PDF into memory (not to disk)
                pdf_resp = retry_request(
                    "get", pdf_url, timeout=PDF_DOWNLOAD_TIMEOUT, verify=_ssl_verify()
                )
                pdf_resp.raise_for_status()

                # Extract text from in-memory PDF bytes
                pdf_bytes = pdf_resp.content
                pdf_text, pdf_pages = _extract_pdf_from_bytes(pdf_bytes)

                if pdf_text.strip():
                    has_pdf = True
                    for raw in chunk_text(pdf_text, CHUNK_SIZE, CHUNK_OVERLAP):
                        enriched = build_chunk_with_header(raw, metadata, "pdf")
                        chunks.append({"source_type": "pdf", "content": enriched})
                else:
                    logger.info(f"PDF for report {report_id} had no extractable text")
        except Exception as e:
            logger.warning(f"PDF processing failed for {report_id}: {e}")

    # ── 5. Nothing to ingest? ────────────────────────────────────
    if not chunks:
        return {
            "success": False,
            "error": f"No content (HTML or PDF) found for report {report_id}",
        }

    # ── 6. Insert into SQLite ───────────────────────────────────
    try:
        db = DatabaseManager(db_path)
        db.insert_report(
            metadata, chunks,
            has_pdf=has_pdf,
            has_content=has_content,
            pdf_pages=pdf_pages,
        )
        db.close()
    except Exception as e:
        return {"success": False, "error": f"SQLite insert failed: {e}"}

    # ── 7. Insert into Vector Store (ChromaDB or pgvector) ──────
    n_chunks = 0
    try:
        vs = VectorStore(chroma_dir, backend=VECTOR_BACKEND)
        n_chunks = vs.add_report(report_id, chunks, metadata)
    except Exception as e:
        return {"success": False, "error": f"Vector store insert failed: {e}"}

    logger.info(
        f"In-memory ingest complete: report {report_id} → "
        f"{n_chunks} chunks (pdf={has_pdf}, html={has_content})"
    )

    return {
        "success": True,
        "report_id": report_id,
        "chunks_added": n_chunks,
        "has_pdf": has_pdf,
        "has_content": has_content,
    }


def _extract_pdf_from_bytes(pdf_bytes: bytes) -> tuple:
    """
    Extract text from PDF bytes in memory (no disk I/O).

    Falls back to writing to a temporary file only if PyPDF2
    cannot read from BytesIO (rare edge case with some PDFs).

    Returns:
        (text: str, page_count: int)
    """
    try:
        from PyPDF2 import PdfReader

        # Try BytesIO first (no disk write)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                pages.append(t.strip())
        return "\n\n".join(pages), len(reader.pages)
    except Exception as e:
        logger.warning(f"BytesIO PDF extraction failed, trying temp file: {e}")
        # Fallback: write to temp file, extract, delete
        import tempfile
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(pdf_bytes)
                tmp_path = tmp.name
            result_text, result_pages = extract_pdf_text(tmp_path)
            return result_text, result_pages
        except Exception as e2:
            logger.error(f"Temp file PDF extraction also failed: {e2}")
            return "", 0
        finally:
            try:
                import os
                os.unlink(tmp_path)
            except Exception:
                pass
