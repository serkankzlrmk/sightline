"""
ReliefWeb Supabase Database Manager
PostgreSQL-backed storage via Supabase for humanitarian reports.

Replaces SQLite DatabaseManager with a cloud-hosted PostgreSQL database.
Uses Supabase's REST API (via the supabase-py client) for all operations.

Schema mirrors the SQLite schema but uses native PostgreSQL types:
  - JSONB for countries/themes (instead of TEXT with JSON strings)
  - TIMESTAMP WITH TIME ZONE for dates
  - pgvector extension for embedding storage (replaces ChromaDB)
"""

import os
from datetime import UTC, datetime

try:
    from supabase import Client, create_client
except ImportError:
    raise ImportError(
        "supabase is required. Install it with: pip install supabase"
    )



# ============================================================================
# CONFIGURATION
# ============================================================================
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")


class SupabaseDB:
    """
    Supabase-backed store for ReliefWeb reports.
    Uses PostgreSQL via Supabase REST API.

    Tables:
      reports  - full metadata, one row per report (unique on report_id)
      chunks  - text fragments with metadata header, ready for embedding
                 Also stores vector embeddings via pgvector
    """

    def __init__(
        self,
        url: str = SUPABASE_URL,
        anon_key: str = SUPABASE_ANON_KEY,
        service_key: str = SUPABASE_SERVICE_KEY,
    ):
        if not url or not (anon_key or service_key):
            raise ValueError(
                "SUPABASE_URL and SUPABASE_ANON_KEY (or SERVICE_KEY) must be set. "
                "Add them to your .env file."
            )
        self.url = url
        self.key = service_key or anon_key
        self.client: Client = create_client(url, self.key)

    # -------------------------------------------------------------------------
    # DEDUPLICATION
    # -------------------------------------------------------------------------

    def report_exists(self, report_id: int) -> bool:
        """Return True if this report_id is already in the database."""
        result = (
            self.client.table("reports")
            .select("report_id")
            .eq("report_id", report_id)
            .execute()
        )
        return len(result.data) > 0

    def report_has_pdf(self, report_id: int) -> bool:
        """Return True if report exists AND has_pdf=true."""
        result = (
            self.client.table("reports")
            .select("has_pdf")
            .eq("report_id", report_id)
            .execute()
        )
        if not result.data:
            return False
        return bool(result.data[0].get("has_pdf", False))

    # -------------------------------------------------------------------------
    # INSERT
    # -------------------------------------------------------------------------

    def insert_report(
        self,
        metadata: dict,
        chunks: list[dict],
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
        )[:10]

        sources = metadata.get("source", [])
        source_name = sources[0].get("shortname", "") if sources else ""

        countries = [c.get("name", "") for c in metadata.get("countries", [])]
        themes = [t.get("name", "") for t in metadata.get("themes", [])]

        formats = metadata.get("format", [])
        format_type = formats[0].get("name", "") if formats else ""

        languages = metadata.get("language", [])
        language = languages[0].get("code", "") if languages else ""

        now = datetime.now(UTC).isoformat()

        # Insert report
        report_row = {
            "report_id": report_id,
            "title": metadata.get("title", ""),
            "date": date_str,
            "source": source_name,
            "url": metadata.get("url", ""),
            "countries": countries,  # JSONB array
            "themes": themes,        # JSONB array
            "format_type": format_type,
            "language": language,
            "has_pdf": has_pdf,
            "has_content": has_content,
            "pdf_pages": pdf_pages,
            "total_chunks": len(chunks),
            "ingested_at": now,
        }

        self.client.table("reports").insert(report_row).execute()

        # Insert chunks
        chunk_rows = []
        for idx, chunk in enumerate(chunks):
            chunk_rows.append({
                "report_id": report_id,
                "chunk_index": idx,
                "source_type": chunk["source_type"],
                "content": chunk["content"],
                "char_count": len(chunk["content"]),
            })

        if chunk_rows:
            self.client.table("chunks").insert(chunk_rows).execute()

        return True

    # -------------------------------------------------------------------------
    # STATS
    # -------------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Return database statistics."""
        # Supabase doesn't have a direct COUNT(*) REST endpoint,
        # so we use RPC or approximate
        try:
            reports_result = (
                self.client.table("reports")
                .select("report_id", count="exact")
                .limit(1)
                .execute()
            )
            chunks_result = (
                self.client.table("chunks")
                .select("id", count="exact")
                .limit(1)
                .execute()
            )
            pdf_result = (
                self.client.table("reports")
                .select("report_id", count="exact")
                .eq("has_pdf", True)
                .limit(1)
                .execute()
            )
            content_result = (
                self.client.table("reports")
                .select("report_id", count="exact")
                .eq("has_content", True)
                .limit(1)
                .execute()
            )
            return {
                "reports": reports_result.count or 0,
                "chunks": chunks_result.count or 0,
                "with_pdf": pdf_result.count or 0,
                "with_content": content_result.count or 0,
                "db_size_kb": 0,  # Not applicable for Supabase
            }
        except Exception as e:
            return {
                "reports": 0,
                "chunks": 0,
                "with_pdf": 0,
                "with_content": 0,
                "db_size_kb": 0,
                "error": str(e),
            }

    def close(self):
        """No-op — Supabase client doesn't need explicit closing."""
        pass

    # -------------------------------------------------------------------------
    # SINGLE REPORT DELETE (for rollback)
    # -------------------------------------------------------------------------

    def delete_report(self, report_id: int) -> bool:
        """Delete a single report and its chunks by report_id."""
        # Delete chunks first (FK constraint)
        self.client.table("chunks").delete().eq("report_id", report_id).execute()
        result = (
            self.client.table("reports")
            .delete()
            .eq("report_id", report_id)
            .execute()
        )
        return len(result.data) > 0

    # -------------------------------------------------------------------------
    # PURGE OLD DATA
    # -------------------------------------------------------------------------

    def purge_old_reports(self, days: int = 90) -> int:
        """Delete reports (and their chunks) older than `days` days."""
        from datetime import timedelta
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")

        # Get old report IDs
        result = (
            self.client.table("reports")
            .select("report_id")
            .lt("date", cutoff)
            .execute()
        )
        old_ids = [row["report_id"] for row in result.data]
        if not old_ids:
            return 0

        # Delete chunks for old reports
        self.client.table("chunks").in_("report_id", old_ids).execute()
        # Delete old reports
        self.client.table("reports").in_("report_id", old_ids).execute()
        return len(old_ids)

    def get_old_report_ids(self, days: int = 90) -> list[int]:
        """Return list of report_ids older than `days` days."""
        from datetime import timedelta
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
        result = (
            self.client.table("reports")
            .select("report_id")
            .lt("date", cutoff)
            .execute()
        )
        return [row["report_id"] for row in result.data]

    # -------------------------------------------------------------------------
    # QUERIES (for SITREP fallback)
    # -------------------------------------------------------------------------

    def list_countries(self) -> list[str]:
        """Get unique countries from reports table."""
        result = (
            self.client.table("reports")
            .select("countries")
            .not_.is_("countries", "null")
            .execute()
        )
        countries_set = set()
        for row in result.data:
            if row.get("countries"):
                for c in row["countries"]:
                    if c and isinstance(c, str):
                        countries_set.add(c.strip())
        return sorted(countries_set)

    def list_themes(self) -> list[str]:
        """Get unique themes from reports table."""
        result = (
            self.client.table("reports")
            .select("themes")
            .not_.is_("themes", "null")
            .execute()
        )
        themes_set = set()
        for row in result.data:
            if row.get("themes"):
                for t in row["themes"]:
                    if t and isinstance(t, str):
                        themes_set.add(t.strip())
        return sorted(themes_set)

    def get_date_range(self, country: str) -> dict:
        """Get min/max date for reports matching a country."""
        # Supabase doesn't support JSONB contains in REST API easily,
        # so we fetch all and filter in Python
        result = (
            self.client.table("reports")
            .select("date, countries")
            .not_.is_("date", "null")
            .execute()
        )
        dates = []
        for row in result.data:
            countries = row.get("countries", [])
            if countries and (country in countries or country.lower() in [c.lower() for c in countries]):
                if row.get("date"):
                    dates.append(row["date"][:10])
        if dates:
            return {"min": min(dates), "max": max(dates), "count": len(dates)}
        return {"min": None, "max": None, "count": 0}

    def get_chunks_by_report_id(self, report_id: int) -> list[dict]:
        """Get all chunks for a specific report."""
        result = (
            self.client.table("chunks")
            .select("id, report_id, chunk_index, source_type, content, char_count")
            .eq("report_id", report_id)
            .order("chunk_index")
            .execute()
        )
        return result.data

    def get_report_metadata(self, report_id: int) -> dict | None:
        """Get metadata for a specific report."""
        result = (
            self.client.table("reports")
            .select("*")
            .eq("report_id", report_id)
            .execute()
        )
        if result.data:
            return result.data[0]
        return None
