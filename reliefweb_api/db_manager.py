"""
ReliefWeb SQLite Database Manager
RAG-ready storage for humanitarian reports with deduplication and chunking.

Schema:
  reports  → one row per unique report (dedup key: report_id)
  chunks   → text chunks for vector embedding later (source: pdf or html)
"""

import sqlite3
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Tuple

# ============================================================================
# CONFIGURATION
# ============================================================================
DEFAULT_DB_PATH = "reliefweb.db"
CHUNK_SIZE = 800       # characters per chunk
CHUNK_OVERLAP = 150    # overlap between consecutive chunks


# ============================================================================
# DATABASE MANAGER
# ============================================================================

class DatabaseManager:
    """
    SQLite-backed store for ReliefWeb reports.
    Designed for later migration to a vector database (ChromaDB, Qdrant, Pinecone).

    Two tables:
      reports - full metadata, one row per report (unique on report_id)
      chunks  - text fragments with metadata header, ready for embedding
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")  # faster concurrent reads
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS reports (
                report_id     INTEGER PRIMARY KEY,
                title         TEXT    NOT NULL,
                date          TEXT,
                source        TEXT,
                url           TEXT,
                countries     TEXT,   -- JSON array of country names
                themes        TEXT,   -- JSON array of theme names
                format_type   TEXT,
                language      TEXT,
                has_pdf       INTEGER DEFAULT 0,
                has_content   INTEGER DEFAULT 0,
                pdf_pages     INTEGER DEFAULT 0,
                total_chunks  INTEGER DEFAULT 0,
                ingested_at   TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id     INTEGER NOT NULL,
                chunk_index   INTEGER NOT NULL,
                source_type   TEXT    NOT NULL,  -- 'pdf' | 'html'
                content       TEXT    NOT NULL,
                char_count    INTEGER,
                FOREIGN KEY (report_id) REFERENCES reports(report_id),
                UNIQUE (report_id, chunk_index)
            );

            CREATE INDEX IF NOT EXISTS idx_chunks_report_id ON chunks(report_id);
            CREATE INDEX IF NOT EXISTS idx_reports_date ON reports(date);
            CREATE INDEX IF NOT EXISTS idx_reports_source ON reports(source);
        """)
        self.conn.commit()

    # -------------------------------------------------------------------------
    # DEDUPLICATION
    # -------------------------------------------------------------------------

    def report_exists(self, report_id: int) -> bool:
        """Return True if this report_id is already in the database."""
        row = self.conn.execute(
            "SELECT 1 FROM reports WHERE report_id = ?", (report_id,)
        ).fetchone()
        return row is not None

    def report_has_pdf(self, report_id: int) -> bool:
        """Return True if report exists AND has_pdf=1."""
        row = self.conn.execute(
            "SELECT has_pdf FROM reports WHERE report_id = ?", (report_id,)
        ).fetchone()
        if row is None:
            return False
        return bool(row[0])

    # -------------------------------------------------------------------------
    # INSERT
    # -------------------------------------------------------------------------

    def insert_report(
        self,
        metadata: Dict,
        chunks: List[Dict],
        has_pdf: bool = False,
        has_content: bool = False,
        pdf_pages: int = 0,
    ) -> bool:
        """
        Insert a report and its text chunks.
        If the report already exists, skips silently (idempotent).

        Args:
            metadata: Parsed metadata.json dict
            chunks: List of {"source_type": "pdf"|"html", "content": str}
            has_pdf: Whether a PDF file was found
            has_content: Whether an HTML content file was found
            pdf_pages: Page count of the PDF

        Returns:
            True if inserted, False if already existed
        """
        report_id = metadata.get("id")
        if self.report_exists(report_id):
            return False

        # Flatten metadata fields
        date_obj = metadata.get("date", {})
        date_str = (
            date_obj.get("original", date_obj.get("created", ""))
            if isinstance(date_obj, dict) else str(date_obj)
        )[:10]  # keep only YYYY-MM-DD

        sources = metadata.get("source", [])
        source_name = sources[0].get("shortname", "") if sources else ""

        countries = [c.get("name", "") for c in metadata.get("countries", [])]
        themes = [t.get("name", "") for t in metadata.get("themes", [])]

        formats = metadata.get("format", [])
        format_type = formats[0].get("name", "") if formats else ""

        languages = metadata.get("language", [])
        language = languages[0].get("code", "") if languages else ""

        now = datetime.utcnow().isoformat()

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO reports
                    (report_id, title, date, source, url, countries, themes,
                     format_type, language, has_pdf, has_content, pdf_pages,
                     total_chunks, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    metadata.get("title", ""),
                    date_str,
                    source_name,
                    metadata.get("url", ""),
                    json.dumps(countries, ensure_ascii=False),
                    json.dumps(themes, ensure_ascii=False),
                    format_type,
                    language,
                    int(has_pdf),
                    int(has_content),
                    pdf_pages,
                    len(chunks),
                    now,
                ),
            )

            for idx, chunk in enumerate(chunks):
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO chunks
                        (report_id, chunk_index, source_type, content, char_count)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        report_id,
                        idx,
                        chunk["source_type"],
                        chunk["content"],
                        len(chunk["content"]),
                    ),
                )

        return True

    # -------------------------------------------------------------------------
    # STATS
    # -------------------------------------------------------------------------

    def get_stats(self) -> Dict:
        row = self.conn.execute(
            "SELECT COUNT(*) as reports FROM reports"
        ).fetchone()
        row2 = self.conn.execute(
            "SELECT COUNT(*) as chunks FROM chunks"
        ).fetchone()
        row3 = self.conn.execute(
            "SELECT COUNT(*) as with_pdf FROM reports WHERE has_pdf = 1"
        ).fetchone()
        row4 = self.conn.execute(
            "SELECT COUNT(*) as with_content FROM reports WHERE has_content = 1"
        ).fetchone()
        size_bytes = Path(self.db_path).stat().st_size if Path(self.db_path).exists() else 0
        return {
            "reports": row["reports"],
            "chunks": row2["chunks"],
            "with_pdf": row3["with_pdf"],
            "with_content": row4["with_content"],
            "db_size_kb": round(size_bytes / 1024, 1),
        }

    def close(self):
        self.conn.close()


# ============================================================================
# TEXT CHUNKING
# ============================================================================

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """
    Split text into overlapping chunks for RAG embedding.
    Tries to break at sentence/paragraph boundaries when possible.
    """
    text = text.strip()
    if not text:
        return []

    # Normalize whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size

        if end < len(text):
            # Try to break at paragraph, sentence, or word boundary
            for sep in ["\n\n", "\n", ". ", " "]:
                boundary = text.rfind(sep, start, end)
                if boundary > start + overlap:
                    end = boundary + len(sep)
                    break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - overlap

    return chunks


def build_chunk_with_header(raw_chunk: str, metadata: Dict, source_type: str) -> str:
    """
    Prepend a compact metadata header to each chunk so the LLM has context
    when retrieving it in RAG.

    Format:
        [REPORT: <title> | SOURCE: <org> | DATE: <date> | COUNTRIES: <list> | TYPE: <source_type>]
        <chunk text>
    """
    sources = metadata.get("source", [])
    source_name = sources[0].get("shortname", "") if sources else ""

    date_obj = metadata.get("date", {})
    date_str = (
        date_obj.get("original", date_obj.get("created", ""))
        if isinstance(date_obj, dict) else str(date_obj)
    )[:10]

    countries = [c.get("shortname", c.get("name", "")) for c in metadata.get("countries", [])]
    country_str = ", ".join(countries[:5])  # max 5 for brevity

    header = (
        f"[REPORT: {metadata.get('title', '')} | "
        f"SOURCE: {source_name} | "
        f"DATE: {date_str} | "
        f"COUNTRIES: {country_str} | "
        f"TYPE: {source_type.upper()}]\n"
    )
    return header + raw_chunk


# ============================================================================
# PDF TEXT EXTRACTION
# ============================================================================

def extract_pdf_text(pdf_path: str) -> Tuple[str, int]:
    """
    Extract text from a PDF file using PyPDF2.
    Returns (text, page_count).
    """
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(pdf_path)
        pages = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                pages.append(t.strip())
        return "\n\n".join(pages), len(reader.pages)
    except Exception as e:
        return "", 0


def get_db(db_path: str = DEFAULT_DB_PATH) -> DatabaseManager:
    """Get a DatabaseManager instance."""
    return DatabaseManager(db_path)
