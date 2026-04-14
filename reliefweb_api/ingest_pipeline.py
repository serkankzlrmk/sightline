"""
ReliefWeb Ingest Pipeline
Shared logic for inserting downloaded reports into SQLite + ChromaDB.

Used by:
  - ingest.py (batch CLI)
  - reliefweb.py download tools (auto-ingest on download)
"""

import json
from pathlib import Path
from typing import Dict

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


# ============================================================================
# DEDUP CHECK
# ============================================================================

def is_ingested(report_id: int, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Return True if this report is already in the SQLite database."""
    db = DatabaseManager(db_path)
    result = db.report_exists(report_id)
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

    # --- Insert ChromaDB ---
    n_chunks = 0
    try:
        vs = VectorStore(chroma_dir)
        n_chunks = vs.add_report(report_id, chunks, metadata)
    except Exception as e:
        return {"success": False, "error": f"ChromaDB insert failed: {e}"}

    return {
        "success": True,
        "report_id": report_id,
        "chunks_added": n_chunks,
        "has_pdf": has_pdf,
        "has_content": has_content,
    }
